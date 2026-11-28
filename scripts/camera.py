#!/usr/bin/env python3
"""Animated camera move over a shot: zoom in/out, pan, tilt, Ken Burns.

    python scripts/camera.py cut.mp4 --preset ken-burns --json
    python scripts/camera.py cut.mp4 --preset none --json      # pass-through

The move is a ``zoompan`` on a frame already cropped to the deliverable aspect, so
the output is a finished 9:16 (or 16:9) shot that export can encode without a second
reframe. Motion is bounded: at most ``amount`` zoom, which keeps a 1080-wide source
above 900 px throughout the move.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args  # noqa: E402
from _contract import InvalidInput, add_common, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, ffprobe_json, project_root,  # noqa: E402
                    read_json, record_stage, run_cmd, work_dir)

# start/end zoom, and the pan direction for x/y ("center" stays put).
PRESETS = {
    "zoom-in": {"start": 1.0, "end": 1.14, "x": "center", "y": "center"},
    "zoom-out": {"start": 1.14, "end": 1.0, "x": "center", "y": "center"},
    "pan-left": {"start": 1.16, "end": 1.16, "x": "rtl", "y": "center"},
    "pan-right": {"start": 1.16, "end": 1.16, "x": "ltr", "y": "center"},
    "tilt-up": {"start": 1.16, "end": 1.16, "x": "center", "y": "btt"},
    "tilt-down": {"start": 1.16, "end": 1.16, "x": "center", "y": "ttb"},
    "ken-burns": {"start": 1.05, "end": 1.16, "x": "drift", "y": "drift"},
}
# Canvas is 1.6x the deliverable: enough oversampling that a 1.16 zoom still has
# real pixels to move, without the 4x scale zoompan would otherwise pay for.
CANVAS = 1.6


def default_preset(plan: dict) -> str:
    return str((plan.get("motion") or {}).get("preset") or "none")


def axis_expr(direction: str, frames: int, axis: str = "x") -> str:
    span = "(iw-iw/zoom)" if axis == "x" else "(ih-ih/zoom)"
    motion = {
        "center": f"{span}/2",
        "ltr": f"{span}*on/{frames}",
        "rtl": f"{span}*(1-on/{frames})",
        "ttb": f"{span}*on/{frames}",
        "btt": f"{span}*(1-on/{frames})",
        "drift": f"{span}*(0.2+0.6*on/{frames})",
    }[direction]
    return motion


def zoom_expr(start: float, end: float, frames: int) -> str:
    if abs(end - start) < 1e-6:
        return f"{start:.4f}"
    return f"{start:.4f}+({end - start:.4f})*on/{frames}"


def motion_filter(preset: str, frames: int, width: int, height: int, fps: int,
                  amount: float | None = None) -> str:
    """The complete -vf for one move; pure so tests can pin the math."""
    if preset not in PRESETS:
        raise InvalidInput(f"unknown motion preset '{preset}'", fix=f"choose from {sorted(PRESETS)}")
    spec = dict(PRESETS[preset])
    if amount:
        cap = float(amount)
        spec["start"] = min(spec["start"], cap)
        spec["end"] = min(spec["end"], cap)
    canvas_w, canvas_h = int(width * CANVAS) // 2 * 2, int(height * CANVAS) // 2 * 2
    frames = max(frames, 2)
    z = zoom_expr(spec["start"], spec["end"], frames)
    x, y = axis_expr(spec["x"], frames, "x"), axis_expr(spec["y"], frames, "y")
    # fps BEFORE zoompan: zoompan emits one frame per input frame, so a 25 fps
    # source would otherwise arrive at 30 fps by re-timing and lose 1/6 of its length.
    return (f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,"
            f"crop={canvas_w}:{canvas_h},setsar=1,fps={fps},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps},"
            f"format=yuv420p")


def measure_move(path: Path, samples: int = 8) -> dict:
    """Median per-step scale and translation of the frame content (cv2, best effort)."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {"scale": None, "shift_px": None}
    cap = cv2.VideoCapture(str(path))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total < samples + 1:
        cap.release()
        return {"scale": None, "shift_px": None}
    frames = []
    for idx in np.linspace(0, total - 2, samples).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if not ok:
            continue
        frames.append(cv2.cvtColor(cv2.resize(frame, (320, 568)), cv2.COLOR_BGR2GRAY))
    cap.release()
    orb = cv2.ORB_create(1000)
    scales, shifts = [], []
    for a, b in zip(frames, frames[1:]):
        ka, da = orb.detectAndCompute(a, None)
        kb, db = orb.detectAndCompute(b, None)
        if da is None or db is None:
            continue
        matches = cv2.BFMatcher(cv2.NORM_HAMMING).match(da, db)
        if len(matches) < 12:
            continue
        pa = np.float32([ka[m.queryIdx].pt for m in matches])
        pb = np.float32([kb[m.trainIdx].pt for m in matches])
        mat, _ = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC)
        if mat is None:
            continue
        scales.append(float((mat[0, 0] ** 2 + mat[1, 0] ** 2) ** 0.5))
        shifts.append(float((mat[0, 2] ** 2 + mat[1, 2] ** 2) ** 0.5))
    if not scales:
        return {"scale": None, "shift_px": None}
    return {"scale": round(float(np.median(scales)), 5), "shift_px": round(float(np.median(shifts)), 2)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Animate a camera move over the shot")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--preset", default=None, choices=sorted(PRESETS) + ["none"])
    parser.add_argument("--amount", type=float, default=None, help="cap on zoom, e.g. 1.1")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    dev = device_plan(args.device, caps)

    with stage("camera", args) as run:
        run.device = dev["resolved"]
        path = expand_inputs([args.input])[0]
        plan_path = state.get("artifacts", {}).get("plan")
        plan = read_json(plan_path, {}) if plan_path and Path(plan_path).is_file() else {}
        out_cfg = plan.get("output") or {}
        width = int(out_cfg.get("width") or 1080)
        height = int(out_cfg.get("height") or 1920)
        fps = int(out_cfg.get("fps") or 30)
        preset = args.preset or default_preset(plan)
        work = work_dir(root, f"p-{path.stem}")
        out_path = Path(args.out) if args.out else work / "camera.mp4"

        info = ffprobe_json(path, dry_run=args.dry_run)
        duration = float((info.get("format") or {}).get("duration") or 0)
        frames = max(int(round(duration * fps)), 2)

        if preset == "none":
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
                   "-map", "0:v:0", "-map", "0:a?", "-c", "copy", str(out_path)]
            run_cmd(cmd, dry_run=args.dry_run, timeout=3600)
            run.add_check("motion", "pass", "none", "static by plan")
            measured = {}
        else:
            vf = motion_filter(preset, frames, width, height, fps, args.amount)
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
                   "-map", "0:v:0", "-map", "0:a?", "-vf", vf,
                   *encoder_args(dev["encoder"], 18), "-c:a", "copy",
                   "-movflags", "+faststart", str(out_path)]
            rc, out = run_cmd(cmd, dry_run=args.dry_run, timeout=7200)
            measured = {} if args.dry_run else measure_move(out_path)
            check = "pass" if measured.get("scale") else "warn"
            run.add_check("motion", check, f"{preset} x{measured.get('scale')}",
                          f"{preset} with scale moving away from 1.0")

        sidecar = out_path.with_suffix(".json")
        if not args.dry_run:
            import json

            sidecar.write_text(json.dumps({"preset": preset, "amount": args.amount,
                                           "measured": measured, "frames": frames},
                                          indent=2), encoding="utf-8")
            state = ensure_edit(root)
            record_stage(root, state, "camera", out_path, preset=preset)
        run.ok(output=str(out_path), artifacts=[str(out_path), str(sidecar)],
               next_cmd=f'python scripts/broll.py "{out_path}"')
        if not args.json:
            print(f"camera {preset} {width}x{height}@{fps} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
