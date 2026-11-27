#!/usr/bin/env python3
"""Platform presets and final render.

    python scripts/export.py audio.mp4 --preset reels --json
    python scripts/export.py audio.mp4 --plan edit/work/p-x/plan.json --json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args  # noqa: E402
from _contract import add_common, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, project_root,  # noqa: E402
                    read_json, record_stage, run_cmd, write_json)

PRESETS = {
    "reels": {"width": 1080, "height": 1920, "fps": 30, "max": 90, "v_bitrate": "6M",
              "audio": "192k", "loudness": -14.0},
    "shorts": {"width": 1080, "height": 1920, "fps": 30, "max": 60, "v_bitrate": "8M",
               "audio": "192k", "loudness": -14.0},
    "tiktok": {"width": 1080, "height": 1920, "fps": 30, "max": 180, "v_bitrate": "6M",
               "audio": "192k", "loudness": -14.0},
    "youtube": {"width": 1920, "height": 1080, "fps": 30, "max": None, "v_bitrate": "10M",
                "audio": "192k", "loudness": -14.0},
    "podcast": {"width": 1920, "height": 1080, "fps": 30, "max": None, "v_bitrate": "8M",
                "audio": "192k", "loudness": -16.0},
    "square": {"width": 1080, "height": 1080, "fps": 30, "max": 120, "v_bitrate": "6M",
               "audio": "192k", "loudness": -14.0},
    "feed": {"width": 1080, "height": 1350, "fps": 30, "max": 120, "v_bitrate": "6M",
             "audio": "192k", "loudness": -14.0},
}

ASPECT_PRESET = {"9:16": "reels", "16:9": "youtube", "1:1": "square", "4:5": "feed"}


def fit_filter(width: int, height: int, fps: int, mode: str = "fill") -> str:
    """Aspect-safe fit: fill crops, contain pads with blur."""
    if mode == "contain":
        return (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,fps={fps},format=yuv420p")
    return (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},format=yuv420p")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Render a platform-ready file")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--preset", default=None, choices=sorted(PRESETS))
    parser.add_argument("--plan", default=None)
    parser.add_argument("--fit", default="fill", choices=["fill", "contain"])
    parser.add_argument("--out", default=None)
    parser.add_argument("--crf", type=int, default=20)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root, refresh=args.refresh)
    dev = device_plan(args.device, caps)

    with stage("export", args) as run:
        run.device = dev["resolved"]
        path = expand_inputs([args.input])[0]
        plan_path = args.plan or state.get("artifacts", {}).get("plan")
        plan = read_json(plan_path, {}) if plan_path and Path(plan_path).is_file() else {}
        aspect = (plan.get("output") or {}).get("aspect", "9:16")
        preset_name = args.preset or ASPECT_PRESET.get(aspect, "reels")
        preset = dict(PRESETS[preset_name])
        width = int((plan.get("output") or {}).get("width") or preset["width"])
        height = int((plan.get("output") or {}).get("height") or preset["height"])
        fps = int((plan.get("output") or {}).get("fps") or preset["fps"])

        run_id = state.get("run_id", "run")
        out_path = Path(args.out) if args.out else root / "edit" / "out" / f"run-{run_id}" / f"{path.stem}-{preset_name}.mp4"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        vf = fit_filter(width, height, fps, args.fit)
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
               "-vf", vf, *encoder_args(dev["encoder"], args.crf),
               "-maxrate", preset["v_bitrate"], "-bufsize", "12M",
               "-c:a", "aac", "-b:a", preset["audio"], "-ar", "48000",
               "-movflags", "+faststart", "-pix_fmt", "yuv420p"]
        if preset.get("max"):
            cmd += ["-t", str(preset["max"])]
        cmd.append(str(out_path))
        rc, out = run_cmd(cmd, dry_run=args.dry_run, timeout=7200)

        sidecar = out_path.with_suffix(".json")
        if not args.dry_run:
            write_json(sidecar, {"preset": preset_name, "width": width, "height": height, "fps": fps,
                                 "encoder": dev["encoder"], "device": dev["resolved"],
                                 "loudness_target": preset["loudness"], "source": str(path)})
            state = ensure_edit(root)
            record_stage(root, state, "export", out_path, preset=preset_name)
        run.add_check("preset", "pass", preset_name, aspect)
        run.ok(output=str(out_path), artifacts=[str(out_path), str(sidecar)],
               next_cmd=f'python scripts/check.py "{out_path}" --json')
        if not args.json:
            print(f"{preset_name} {width}x{height}@{fps} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
