#!/usr/bin/env python3
"""Scene detection via FFmpeg scdet (PySceneDetect optional).

    python scripts/scenes.py input.mp4 --json
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import add_common, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, project_root,  # noqa: E402
                    record_stage, run_cmd, work_dir, write_json)


def parse_scdet(text: str, threshold: float) -> list:
    cuts = []
    for line in text.splitlines():
        m = re.search(r"lavfi\.scd\.time:\s*([\d.]+)", line)
        if m:
            cuts.append(round(float(m.group(1)), 3))
    return sorted(set(cuts))


def scenes_from_cuts(cuts, duration: float) -> list:
    bounds = [0.0] + [c for c in cuts if 0 < c < duration] + [round(duration, 3)]
    return [{"index": i, "in": bounds[i], "out": bounds[i + 1],
             "duration": round(bounds[i + 1] - bounds[i], 3)}
            for i in range(len(bounds) - 1)]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Detect scene cuts")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--threshold", type=float, default=0.4)
    parser.add_argument("--pyscenedetect", action="store_true")
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)

    with stage("scenes", args) as run:
        path = expand_inputs([args.input])[0]
        rc, out = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(path),
                           "-vf", f"scdet=threshold={args.threshold}:sc_pass=0",
                           "-f", "null", "-"], dry_run=args.dry_run, timeout=3600)
        cuts = [] if args.dry_run else parse_scdet(out, args.threshold)
        duration = 0.0
        from _paths import ffprobe_json

        probe = ffprobe_json(path, dry_run=args.dry_run)
        duration = float((probe.get("format") or {}).get("duration") or 0)
        scenes = scenes_from_cuts(cuts, duration or (cuts[-1] if cuts else 0))
        work = work_dir(root, f"p-{path.stem}")
        out_path = work / "scenes.json"
        if not args.dry_run:
            write_json(out_path, {"cuts": cuts, "scenes": scenes, "threshold": args.threshold,
                                  "method": "scdet"})
            state = ensure_edit(root)
            record_stage(root, state, "scenes", out_path, cuts=len(cuts))
        run.ok(output=str(out_path), artifacts=[str(out_path)],
               next_cmd="python scripts/clipfind.py --json")
        if not args.json:
            print(f"{len(cuts)} cuts / {len(scenes)} scenes -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
