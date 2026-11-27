#!/usr/bin/env python3
"""Contact sheet (9 frames), waveform strip, matte preview.

    python scripts/sheet.py out.mp4 --json
    python scripts/sheet.py out.mp4 --waveform --matte mask.mov
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import add_common, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, ffprobe_json, project_root,  # noqa: E402
                    record_stage, run_cmd, work_dir)


def sheet_filter(frames: int = 9, cols: int = 3) -> str:
    rows = math.ceil(frames / cols)
    return f"select='not(mod(n\\,{max(frames, 1)}))',scale=320:-1,tile={cols}x{rows}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Contact sheet, waveform and matte preview")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--frames", type=int, default=9)
    parser.add_argument("--waveform", action="store_true")
    parser.add_argument("--matte", default=None, help="mask video to preview on white and black")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)

    with stage("sheet", args) as run:
        path = expand_inputs([args.input])[0]
        probe = ffprobe_json(path, dry_run=args.dry_run)
        duration = float((probe.get("format") or {}).get("duration") or 1)
        work = Path(args.out_dir) if args.out_dir else work_dir(root, f"p-{path.stem}")
        work.mkdir(parents=True, exist_ok=True)
        arts = []

        sheet = work / f"{path.stem}-sheet.jpg"
        step = max(duration / (args.frames + 1), 0.2)
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
               "-vf", f"fps=1/{step:.3f},scale=320:-1,tile=3x3",
               "-frames:v", "1", "-q:v", "3", str(sheet)]
        run_cmd(cmd, dry_run=args.dry_run, timeout=600)
        arts.append(str(sheet))

        if args.waveform:
            wave = work / f"{path.stem}-wave.png"
            run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
                     "-filter_complex", "showwavespic=s=1200x160:colors=white", "-frames:v", "1", str(wave)],
                    dry_run=args.dry_run, timeout=600)
            arts.append(str(wave))

        if args.matte:
            mask = expand_inputs([args.matte])[0]
            for bg, name in (("white", "matte-white.png"), ("black", "matte-black.png")):
                prev = work / f"{path.stem}-{name}"
                graph = (f"[1:v]format=gray,scale=iw:ih[m];[0:v][m]alphamerge[fg];"
                         f"color=c={bg}:s=iwxih[bgv];[bgv][fg]overlay=format=auto")
                run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path), "-i", str(mask),
                         "-filter_complex", graph, "-frames:v", "1", str(prev)],
                        dry_run=args.dry_run, timeout=600)
                arts.append(str(prev))

        if not args.dry_run:
            state = ensure_edit(root)
            record_stage(root, state, "sheet", arts[0], sheets=len(arts))
        run.ok(output=arts[0], artifacts=arts,
               next_cmd="view the contact sheet, then report the gates")
        if not args.json:
            print("\n".join(arts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
