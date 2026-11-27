#!/usr/bin/env python3
"""Lower-third, logo, progress bar and chapter card with libass + bundled fonts.

    python scripts/graphics.py input.mp4 --lower-third "Sujeet / Editor" --json
    python scripts/graphics.py input.mp4 --progress-bar --logo logo.png --json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args, fonts_dir  # noqa: E402
from _contract import InvalidInput, add_common, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, ffprobe_json, filter_path,  # noqa: E402
                    project_root, record_stage, run_cmd, work_dir, write_json)


def lower_third_ass(name: str, role: str, width: int, height: int, start: float, end: float) -> str:
    font_size = max(int(min(width, height) * 0.030), 24)
    margin = int(width * 0.06)
    margin_v = int(height * 0.22)
    parts = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: LT,Inter,{font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,1,"
        f"{margin},{margin},{margin_v},1",
        f"Style: LR,Inter,{int(font_size * 0.7)},&H00D8D8D8,&H00D8D8D8,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,1,1,"
        f"{margin},{margin},{margin_v - font_size},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    ts = lambda s: f"{int(s // 3600)}:{int((s % 3600) // 60):02d}:{s % 60:05.2f}"
    parts.append(f"Dialogue: 0,{ts(start)},{ts(end)},LT,,0,0,0,,{{\\fad(250,250)}}{name}")
    if role:
        parts.append(f"Dialogue: 0,{ts(start)},{ts(end)},LR,,0,0,0,,{{\\fad(250,250)}}{role}")
    return "\n".join(parts) + "\n"


def progress_filter(duration: float) -> str:
    """drawbox rejects an unbounded t expression, so the width is clamped."""
    return (f"drawbox=x=0:y=ih-8:w='iw*min(t/{max(duration, 1):.3f},1)':h=8:"
            "color=0xFF3B30@0.9:t=fill")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Add lower-third, logo, progress bar or a chapter card")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--lower-third", default=None, help='"Name / Role"')
    parser.add_argument("--logo", default=None)
    parser.add_argument("--logo-pos", default="top-right", choices=["top-left", "top-right", "bottom-left", "bottom-right"])
    parser.add_argument("--progress-bar", action="store_true")
    parser.add_argument("--chapter-card", default=None)
    parser.add_argument("--start", type=float, default=0.8)
    parser.add_argument("--duration-on-screen", type=float, default=4.0)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root, refresh=args.refresh)
    dev = device_plan(args.device, caps)

    with stage("graphics", args) as run:
        run.device = dev["resolved"]
        if not caps["ffmpeg"]["has_libass"]:
            raise InvalidInput("this FFmpeg has no libass (subtitles filter)",
                               fix="install a full FFmpeg build: brew install ffmpeg-full / winget Gyan.FFmpeg",
                               doc="references/troubleshooting.md#libass")
        path = expand_inputs([args.input])[0]
        probe = ffprobe_json(path)
        duration = float((probe.get("format") or {}).get("duration") or 0)
        streams = probe.get("streams") or [{}]
        width = int(streams[0].get("width") or 1080)
        height = int(streams[0].get("height") or 1920)
        work = work_dir(root, f"p-{path.stem}")
        vf_parts, inputs = [], []

        if args.lower_third:
            name, _, role = args.lower_third.partition("/")
            ass = work / "lower-third.ass"
            ass.write_text(lower_third_ass(name.strip(), role.strip(), width, height,
                                           args.start, args.start + args.duration_on_screen),
                           encoding="utf-8", newline="\n")
            vf_parts.append(f"subtitles={filter_path(ass)}:fontsdir={filter_path(fonts_dir(root))}")

        if args.chapter_card:
            ass = work / "chapter.ass"
            ass.write_text(lower_third_ass(args.chapter_card, "", width, height, 0.0, 1.6),
                           encoding="utf-8", newline="\n")
            vf_parts.append(f"subtitles={filter_path(ass)}:fontsdir={filter_path(fonts_dir(root))}")

        if args.progress_bar:
            vf_parts.append(progress_filter(duration))

        logo = None
        if args.logo:
            logo = expand_inputs([args.logo])[0]
            inputs += ["-i", str(logo)]

        if not vf_parts and not logo:
            raise InvalidInput("nothing to draw",
                               fix="pass --lower-third, --logo, --progress-bar or --chapter-card")

        out_path = Path(args.out) if args.out else work / "graphics.mp4"
        vf = ",".join(vf_parts) or "null"
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path), *inputs]
        if logo is not None:
            pos = {"top-left": "24:24", "top-right": "W-w-24:24",
                   "bottom-left": "24:H-h-24", "bottom-right": "W-w-24:H-h-24"}[args.logo_pos]
            fc = (f"[0:v]{vf}[base];[1:v]scale=-1:{max(height // 8, 48)}[lg];"
                  f"[base][lg]overlay={pos}[out]")
            cmd += ["-filter_complex", fc, "-map", "[out]", "-map", "0:a?"]
        else:
            cmd += ["-vf", vf]
        cmd += [*encoder_args(dev["encoder"], 20), "-c:a", "copy",
                "-movflags", "+faststart", str(out_path)]
        run_cmd(cmd, dry_run=args.dry_run, timeout=7200, check=not args.dry_run)

        sidecar = work / "graphics.json"
        write_json(sidecar, {"lower_third": args.lower_third, "logo": args.logo,
                             "progress_bar": args.progress_bar, "chapter_card": args.chapter_card})
        if not args.dry_run:
            state = ensure_edit(root)
            record_stage(root, state, "graphics", out_path)
        run.add_check("graphics", "pass", len(vf_parts), ">= 1 element")
        run.ok(output=str(out_path), artifacts=[str(out_path)], next_cmd="python scripts/check.py <out>")
        if not args.json:
            print(f"graphics: {', '.join(vf_parts)} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
