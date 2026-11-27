#!/usr/bin/env python3
"""Probe media: duration, fps, VFR, HDR, rotation, audio, loudness, quick detect.

    python scripts/probe.py video.mp4 --json
    python scripts/probe.py video.mp4 --quick --json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan  # noqa: E402
from _contract import add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffprobe_json, ffmpeg_bin,  # noqa: E402
                    project_root, record_stage, run_cmd, work_dir)

GREEN_HINT = 0.18


def parse_fraction(value) -> float:
    try:
        if not value or value in ("0/0", "N/A"):
            return 0.0
        if "/" in str(value):
            num, den = str(value).split("/", 1)
            return float(num) / float(den) if float(den) else 0.0
        return float(value)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe_file(path: Path, quick: bool = False, dry_run: bool = False, lang_guess: bool = True) -> dict:
    data = ffprobe_json(path, dry_run=dry_run)
    if dry_run:
        return {}
    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    duration = float(fmt.get("duration") or (video or {}).get("duration") or 0.0)
    avg_fps = parse_fraction((video or {}).get("avg_frame_rate"))
    raw_fps = parse_fraction((video or {}).get("r_frame_rate"))
    rotation = 0
    if video:
        for side in video.get("side_data_list", []) or []:
            if "rotation" in side:
                rotation = int(float(side["rotation"]))
        rotation = rotation or int(float((video.get("tags") or {}).get("rotate", 0) or 0))
    width = int((video or {}).get("width") or 0)
    height = int((video or {}).get("height") or 0)
    if abs(rotation) % 180 == 90:
        width, height = height, width
    transfer = (video or {}).get("color_transfer") or ""
    primaries = (video or {}).get("color_primaries") or ""
    info = {
        "path": str(path),
        "size": path.stat().st_size,
        "duration": round(duration, 3),
        "width": width,
        "height": height,
        "aspect": round(width / height, 4) if height else 0,
        "fps": round(avg_fps, 4),
        "fps_raw": round(raw_fps, 4),
        "vfr": bool(avg_fps and raw_fps and abs(avg_fps - raw_fps) / max(raw_fps, 1e-6) > 0.01),
        "rotation": rotation,
        "hdr": transfer in ("smpte2084", "arib-std-b67") or primaries == "bt2020",
        "color": {"transfer": transfer, "primaries": primaries, "range": (video or {}).get("color_range")},
        "video_codec": (video or {}).get("codec_name"),
        "audio": [
            {
                "index": a.get("index"),
                "codec": a.get("codec_name"),
                "channels": a.get("channels"),
                "sample_rate": a.get("sample_rate"),
            }
            for a in audios
        ],
        "has_audio": bool(audios),
        "bitrate": int(float(fmt.get("bit_rate") or 0)),
    }
    if quick and video:
        info["quick"] = quick_detect(path, duration, dry_run=dry_run, lang_guess=lang_guess)
    return info


def _frame_raw(path: Path, at: float, size: str = "96x54") -> bytes:
    cmd = [
        ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error",
        "-ss", f"{max(at, 0):.3f}", "-i", str(path), "-frames:v", "1",
        "-vf", f"scale={size}:flags=area,format=rgb24", "-f", "rawvideo", "-",
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
        return proc.stdout or b""
    except Exception:  # noqa: BLE001
        return b""


def guess_language(path: Path) -> str | None:
    """Whisper tiny on the first 30 s. Returns None when the backend is absent."""
    try:
        from faster_whisper import WhisperModel
    except Exception:  # noqa: BLE001
        return None
    try:
        model = WhisperModel("tiny", device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(path), beam_size=1, vad_filter=True,
                                          condition_on_previous_text=False)
        for _ in segments:  # consume the first segment to force decoding
            break
        return getattr(info, "language", None)
    except Exception as exc:  # noqa: BLE001 - a guess must never fail the probe
        log(f"WARN language guess failed: {exc}")
        return None


def quick_detect(path: Path, duration: float, dry_run: bool = False, lang_guess: bool = True) -> dict:
    out = {"green_screen": False, "green_fraction": 0.0, "brightness": None,
           "noise": None, "faces": None, "language_guess": None}
    if dry_run:
        return out
    raw = _frame_raw(path, min(1.0, duration / 4 if duration else 0))
    if raw:
        w, h = 96, 54
        px = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw) - 2, 3)]
        if px:
            border = []
            for y in range(h):
                for x in range(w):
                    if x < 6 or x >= w - 6 or y < 6 or y >= h - 6:
                        border.append(px[y * w + x])
            greens = [1 for r, g, b in border if g > 90 and g > r * 1.35 and g > b * 1.25]
            frac = len(greens) / max(len(border), 1)
            out["green_fraction"] = round(frac, 3)
            out["green_screen"] = frac >= GREEN_HINT
            out["brightness"] = round(sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in px) / len(px), 1)

    rc, stats = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info",
                         "-ss", "1", "-i", str(path), "-frames:v", "1",
                         "-vf", "signalstats,metadata=mode=print", "-f", "null", "-"], timeout=90)
    if rc == 0:
        m = re.search(r"YAVG=([\d.]+)", stats)
        if m:
            out["brightness"] = float(m.group(1))
        n = re.search(r"YDIF=([\d.]+)", stats)
        if n:
            out["noise"] = float(n.group(1))

    try:
        import cv2  # noqa: F401
    except Exception:  # noqa: BLE001
        out["faces"] = None
    else:
        frame = _cv_frame(path, min(1.0, duration / 4 if duration else 0))
        if frame is not None:
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            faces = cascade.detectMultiScale(frame, 1.15, 5, minSize=(40, 40))
            out["faces"] = int(len(faces))
    if lang_guess:
        out["language_guess"] = guess_language(path)
    return out


def _cv_frame(path: Path, at: float):
    try:
        import numpy as np
        import cv2
    except Exception:  # noqa: BLE001
        return None
    raw = _frame_raw(path, at, "640x360")
    if not raw or len(raw) < 640 * 360 * 3:
        return None
    arr = np.frombuffer(raw[: 640 * 360 * 3], dtype=np.uint8).reshape((360, 640, 3))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def loudness_snapshot(path: Path, dry_run: bool = False) -> dict:
    rc, out = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(path),
                       "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"], dry_run=dry_run, timeout=1800)
    if dry_run:
        return {}
    summary = out.rsplit("Summary:", 1)[-1] if "Summary:" in out else out
    integ = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    return {"integrated_lufs": float(integ.group(1)) if integ else None,
            "true_peak_db": float(peak.group(1)) if peak else None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Probe media and quick-detect content")
    add_common(parser)
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--quick", action="store_true", help="green screen, faces, brightness, language")
    parser.add_argument("--loudness", action="store_true", help="measure integrated loudness")
    parser.add_argument("--no-lang-guess", action="store_true",
                        help="skip the whisper-tiny language guess during --quick")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)

    with stage("probe", args) as run:
        files = expand_inputs(args.inputs)
        caps = capabilities(root, refresh=args.refresh)
        run.device = device_plan(args.device, caps)["resolved"]
        results = []
        for f in files:
            info = probe_file(Path(f), quick=args.quick, dry_run=args.dry_run,
                              lang_guess=not args.no_lang_guess)
            if args.loudness and info.get("has_audio"):
                info["loudness"] = loudness_snapshot(Path(f), dry_run=args.dry_run)
            results.append(info)
            if not args.dry_run:
                run.add_check(f"duration:{f.name}", "pass" if info["duration"] > 0 else "fail",
                              info["duration"], "> 0 s")
        payload = results[0] if len(results) == 1 else {"files": results}
        key = Path(files[0]).stem if len(files) == 1 else "batch"
        out_path = Path(args.out) if args.out else work_dir(root, f"p-{key}") / "probe.json"
        if not args.dry_run:
            out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            state = ensure_edit(root)
            state["device"] = run.device
            state.setdefault("params", {})["lang"] = state.get("params", {}).get("lang", "hi")
            record_stage(root, state, "probe", out_path, device=run.device,
                         duration=payload.get("duration") if isinstance(payload, dict) else None)
        run.ok(output=str(out_path), artifacts=[str(out_path)],
               next_cmd="python scripts/intake.py --ask")
        if not args.json and isinstance(payload, dict):
            print(f"{payload['width']}x{payload['height']} {payload['fps']}fps "
                  f"{payload['duration']}s hdr={payload['hdr']} vfr={payload['vfr']}")
            if payload.get("quick"):
                print(json.dumps(payload["quick"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
