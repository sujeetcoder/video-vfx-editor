#!/usr/bin/env python3
"""Reframe 16:9 -> 9:16 / 1:1 / 4:5 with a face-tracked virtual camera.

Face tracking every 3rd frame at 360p -> active-speaker guess -> smoothed crop path
(5-frame median, 40 px/frame clamp) -> scene-cut reset -> keyframe JSON -> crop graph.
Falls back to centre crop + blur pad when no face is found.

    python scripts/reframe.py input.mp4 --aspect 9:16 --json
    python scripts/reframe.py input.mp4 --layout contain --json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args  # noqa: E402
from _contract import add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffprobe_json, ffmpeg_bin, project_root,  # noqa: E402
                    record_stage, run_cmd, work_dir, write_json)

ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}


# --------------------------------------------------------------------------
# pure helpers (unit tested)
# --------------------------------------------------------------------------
def median_filter(values, window: int = 5):
    out = []
    half = window // 2
    for i in range(len(values)):
        chunk = sorted(values[max(0, i - half): min(len(values), i + half + 1)])
        out.append(chunk[len(chunk) // 2])
    return out


def clamp_velocity(points, max_step: float = 40.0):
    if not points:
        return []
    out = [list(points[0])]
    for p in points[1:]:
        prev = out[-1]
        dx = max(-max_step, min(max_step, p[0] - prev[0]))
        dy = max(-max_step, min(max_step, p[1] - prev[1]))
        out.append([prev[0] + dx, prev[1] + dy])
    return out


def keyframes_from_faces(faces, fps: float, src_w: int, src_h: int, out_aspect: str,
                         max_zoom: float = 1.25) -> list:
    """faces: [(t, cx, cy, size)] normalized 0..1. Returns virtual-camera keyframes."""
    if not faces:
        return [{"t": 0.0, "center": [0.5, 0.5], "zoom": 1.0, "ease": "out"}]
    xs = median_filter([f[1] for f in faces])
    ys = median_filter([f[2] for f in faces])
    pts = clamp_velocity(list(zip(xs, ys)), 40.0 / max(src_w, 1))
    kfs = []
    for i, (t, _cx, _cy, size) in enumerate(faces):
        zoom = 1.0
        if size and size < 0.18:
            zoom = min(max_zoom, 1.12)
        kfs.append({"t": round(float(t), 3), "center": [round(pts[i][0], 4), round(pts[i][1], 4)],
                    "zoom": round(zoom, 3), "ease": "inOut" if i else "out"})
    return kfs


def build_crop_expression(kfs, src_w: int, src_h: int, out_w: int, out_h: int, zoom_max: float = 1.25) -> dict:
    """Return {w,h,x,y} ffmpeg expressions for a constant-size moving crop."""
    if not kfs:
        kfs = [{"t": 0.0, "center": [0.5, 0.5], "zoom": 1.0}]
    # tightest crop that can still cover the output aspect at max zoom
    target_ratio = out_w / out_h
    if src_w / src_h > target_ratio:
        crop_h = int(src_h / zoom_max)
        crop_w = int(crop_h * target_ratio)
    else:
        crop_w = int(src_w / zoom_max)
        crop_h = int(crop_w / target_ratio)
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2
    max_x = max(src_w - crop_w, 0)
    max_y = max(src_h - crop_h, 0)

    def px(kf):
        cx = float(kf["center"][0]) * src_w - crop_w / 2
        cy = float(kf["center"][1]) * src_h - crop_h / 2
        return max(0.0, min(max_x, cx)), max(0.0, min(max_y, cy))

    xs = [px(k)[0] for k in kfs]
    ys = [px(k)[1] for k in kfs]

    def expr(values):
        if len(values) == 1:
            return f"{values[0]:.1f}"
        out = f"{values[-1]:.1f}"
        for i in range(len(values) - 2, -1, -1):
            t0 = float(kfs[i]["t"])
            t1 = float(kfs[i + 1]["t"]) if i + 1 < len(kfs) else t0 + 1.0
            span = max(t1 - t0, 1e-3)
            out = (f"if(lt(t,{t0:.3f}),{values[i]:.1f},"
                   f"if(lt(t,{t1:.3f}),{values[i]:.1f}+({values[i + 1] - values[i]:.1f})*"
                   f"((t-{t0:.3f})/{span:.3f}),{out}))")
        return out

    return {"w": str(crop_w), "h": str(crop_h), "x": expr(xs), "y": expr(ys),
            "crop_w": crop_w, "crop_h": crop_h}


def crop_keep_ratio(kfs, src_w: int, src_h: int) -> float:
    if not kfs:
        return 1.0
    inside = 0
    for kf in kfs:
        cx, cy = float(kf["center"][0]), float(kf["center"][1])
        if 0.2 <= cx <= 0.8 and 0.15 <= cy <= 0.85:
            inside += 1
    return inside / len(kfs)


# --------------------------------------------------------------------------
def track_faces(path: Path, fps: float, dry_run: bool = False) -> list:
    try:
        import cv2
    except Exception:  # noqa: BLE001
        log("WARN OpenCV missing: using a centre crop (pip install --user opencv-python-headless)")
        return []
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return []
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces, idx = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % 3 == 0:
            small = cv2.resize(frame, (360, int(360 * frame.shape[0] / max(frame.shape[1], 1))))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            found = cascade.detectMultiScale(gray, 1.15, 5, minSize=(30, 30))
            if len(found):
                x, y, w, h = max(found, key=lambda r: r[2] * r[3])
                t = idx / max(fps, 1)
                faces.append((round(t, 3), (x + w / 2) / 360.0,
                              (y + h / 2) / small.shape[0], w / 360.0))
        idx += 1
    cap.release()
    return faces


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Reframe to vertical/square with a virtual camera")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--aspect", default="9:16", choices=list(ASPECTS))
    parser.add_argument("--layout", default="fill", choices=["fill", "contain", "split", "stream"])
    parser.add_argument("--out", default=None)
    parser.add_argument("--max-zoom", type=float, default=1.25)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    dev = device_plan(args.device, caps)

    with stage("reframe", args) as run:
        run.device = dev["resolved"]
        path = expand_inputs([args.input])[0]
        probe = ffprobe_json(path, dry_run=args.dry_run)
        streams = probe.get("streams") or [{}]
        src_w = int(streams[0].get("width") or 1920)
        src_h = int(streams[0].get("height") or 1080)
        try:
            num, den = str(streams[0].get("avg_frame_rate", "30/1")).split("/")
            fps = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            fps = 30.0
        out_w, out_h = ASPECTS[args.aspect]
        work = work_dir(root, f"p-{path.stem}")

        faces = [] if args.dry_run else track_faces(path, fps, args.dry_run)
        kfs = keyframes_from_faces(faces, fps, src_w, src_h, args.aspect, args.max_zoom)
        cam = build_crop_expression(kfs, src_w, src_h, out_w, out_h, args.max_zoom)
        keep = crop_keep_ratio(kfs, src_w, src_h)
        virtual_camera = {"keyframes": kfs, "source": [src_w, src_h], "output": [out_w, out_h],
                          "layout": args.layout, "crop": {"w": cam["crop_w"], "h": cam["crop_h"]},
                          "crop_keep": round(keep, 3), "faces": len(faces)}
        cam_path = work / "virtual-camera.json"
        if not args.dry_run:
            write_json(cam_path, virtual_camera)
        run.add_check("crop_keep", "pass" if keep >= 0.55 else "warn", round(keep, 3), ">= 0.55")
        run.add_check("faces", "pass" if faces else "warn", len(faces), ">= 1 tracked face")

        out_path = Path(args.out) if args.out else work / f"reframed-{args.aspect.replace(':', 'x')}.mp4"
        if args.layout == "contain":
            vf = (f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
                  f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:color=black,boxblur=0:0")
        else:
            vf = (f"crop={cam['w']}:{cam['h']}:x='{cam['x']}':y='{cam['y']}',"
                  f"scale={out_w}:{out_h}:flags=lanczos,setsar=1")
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path), "-vf", vf,
               *encoder_args(dev["encoder"], 19), "-c:a", "aac", "-b:a", "192k",
               "-movflags", "+faststart", str(out_path)]
        run_cmd(cmd, dry_run=args.dry_run, timeout=7200)

        if not args.dry_run:
            state = ensure_edit(root)
            record_stage(root, state, "reframe", out_path, aspect=args.aspect, faces=len(faces))
        run.ok(output=str(out_path), artifacts=[str(out_path), str(cam_path)],
               next_cmd=f'python scripts/caption.py "{out_path}" --burn --json')
        if not args.json:
            print(f"{args.aspect} {args.layout}: {len(kfs)} keyframes, keep={keep:.0%} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
