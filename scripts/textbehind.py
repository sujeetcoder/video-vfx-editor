#!/usr/bin/env python3
"""Text/graphics BEHIND a person: build the plate first, then overlay the cutout.

    python scripts/textbehind.py input.mp4 --mask mask.mov --text "MY TITLE" --bg bg.jpg --json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args, fonts_dir  # noqa: E402
from _contract import InvalidInput, add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, ffprobe_json, filter_path,  # noqa: E402
                    project_root, record_stage, run_cmd, work_dir, write_json)
from caption import STYLES, build_ass, chunk_words  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Composite text behind a person")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--mask", required=False, help="mask video from matte.py (alpha in luma)")
    parser.add_argument("--text", default=None)
    parser.add_argument("--text-file", default=None)
    parser.add_argument("--bg", default=None, help="background image (default: #101010)")
    parser.add_argument("--bg-color", default="0x101010")
    parser.add_argument("--position", default="middle", choices=["top", "middle", "bottom"])
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    dev = device_plan(args.device, caps)

    with stage("textbehind", args) as run:
        run.device = dev["resolved"]
        path = expand_inputs([args.input])[0]
        probe = ffprobe_json(path)
        duration = float((probe.get("format") or {}).get("duration") or 0)
        width = int((probe.get("streams") or [{}])[0].get("width") or 1080)
        height = int((probe.get("streams") or [{}])[0].get("height") or 1920)
        work = work_dir(root, f"p-{path.stem}")
        mask = None
        if args.mask:
            mask = expand_inputs([args.mask])[0]
        else:
            candidate = work / "mask.mov"
            if candidate.is_file():
                mask = candidate
                log("using matte mask from the work folder")
        if mask is None:
            raise InvalidInput(
                "text-behind needs a person mask",
                fix=f'python scripts/matte.py "{path}" --preview --json',
                doc="references/person-matte.md",
            )

        text = args.text
        if args.text_file:
            text = Path(args.text_file).read_text(encoding="utf-8").strip()
        if not text:
            raise InvalidInput("pass --text or --text-file", fix='--text "MY TITLE"')

        style = dict(STYLES["bold-pop"])
        words = [{"w": w, "s": 0.0, "e": max(duration, 1.0)} for w in text.split()]
        lines = chunk_words(words, max_chars=18, min_words=1, max_words=3)
        ass = work / "title-behind.ass"
        ass.write_text(build_ass(lines, width, height, style, args.position, "en"), encoding="utf-8", newline="\n")

        out_path = Path(args.out) if args.out else work / "textbehind.mp4"
        # [0]=person, [1]=bg, [2]=mask
        fc = (
            f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}[bgv];"
            f"[bgv]subtitles={filter_path(ass)}:fontsdir={filter_path(fonts_dir(root))}[plate];"
            f"[0:v][2:v]alphamerge[fg];[plate][fg]overlay=shortest=1[out]"
        )
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path)]
        if args.bg:
            cmd += ["-loop", "1", "-i", str(expand_inputs([args.bg])[0])]
        else:
            cmd += ["-f", "lavfi", "-i", f"color=c={args.bg_color}:s={width}x{height}:d={duration:.3f}"]
        cmd += ["-i", str(mask), "-filter_complex", fc, "-map", "[out]", "-map", "0:a?",
                *encoder_args(dev["encoder"], 19), "-c:a", "aac", "-movflags", "+faststart",
                str(out_path)]
        rc, out = run_cmd(cmd, dry_run=args.dry_run, timeout=7200)

        if not args.dry_run:
            state = ensure_edit(root)
            record_stage(root, state, "textbehind", out_path)
        sidecar = work / "textbehind.json"
        write_json(sidecar, {"text": text, "mask": str(mask), "position": args.position})
        run.add_check("mask_present", "pass" if mask else "fail", str(mask), "mask video")
        run.ok(output=str(out_path), artifacts=[str(out_path), str(ass)],
               next_cmd=f'python scripts/check.py "{out_path}" --json')
        if not args.json:
            print(f"text behind person -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
