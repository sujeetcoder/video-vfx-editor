#!/usr/bin/env python3
"""Words -> SRT + styled ASS (2–4 words/line, ≤32 chars, safe zones, karaoke).

    python scripts/caption.py cut.mp4 --json
    python scripts/caption.py cut.mp4 --style karaoke --burn --json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args, fonts_dir  # noqa: E402
from _contract import InvalidInput, add_common, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, filter_path, project_root,  # noqa: E402
                    read_json, record_stage, run_cmd, work_dir)

STYLES = {
    "bold-pop": {"font": "Inter", "size_pct": 0.052, "bold": -1, "upper": True,
                 "primary": "&H00FFFFFF", "highlight": "&H0000D7FF", "outline": 6, "shadow": 2},
    "clean": {"font": "Inter", "size_pct": 0.040, "bold": 0, "upper": False,
              "primary": "&H00FFFFFF", "highlight": "&H00FFFFFF", "outline": 4, "shadow": 1},
    "karaoke": {"font": "Inter", "size_pct": 0.050, "bold": -1, "upper": False,
                "primary": "&H00FFFFFF", "highlight": "&H0000C8FF", "outline": 5, "shadow": 2},
}
DEVANAGARI_FONT = "Noto Sans Devanagari"


# --------------------------------------------------------------------------
# pure helpers (unit tested)
# --------------------------------------------------------------------------
def chunk_words(words, max_chars: int = 32, min_words: int = 2, max_words: int = 4) -> list:
    lines, cur = [], []

    def width(ws):
        return len(" ".join(w["w"] for w in ws))

    for w in words:
        token = str(w.get("w", "")).strip()
        if not token:
            continue
        if cur and (width(cur + [w]) > max_chars or len(cur) >= max_words):
            lines.append(cur)
            cur = []
        cur.append(w)
        if token.endswith((".", "!", "?", ",", "।")) and len(cur) >= min_words:
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    fixed = []
    for line in lines:
        # Re-join a lone trailing word only when the result still fits: an orphan
        # is ugly, an over-budget caption line is a gate failure.
        if len(line) == 1 and fixed and len(" ".join(w["w"] for w in fixed[-1] + line)) <= max_chars:
            fixed[-1].extend(line)
        else:
            fixed.append(line)
    return split_overlong(fixed, max_chars)


def split_overlong(lines, max_chars: int) -> list:
    """Split any single token wider than the budget into its own pieces.

    A recogniser loop can emit one "word" of 100+ characters, which would sail
    past every length gate as a one-word line.
    """
    out = []
    for line in lines:
        if all(len(w["w"]) <= max_chars for w in line):
            out.append(line)
            continue
        for w in line:
            token = w["w"]
            if len(token) <= max_chars:
                out.append([w])
            else:
                out.extend([dict(w, w=token[i:i + max_chars])]
                           for i in range(0, len(token), max_chars))
    return out


def srt_ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    ms = int(round((seconds - int(seconds)) * 1000))
    whole = int(seconds)
    h, rem = divmod(whole, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def to_srt(lines) -> str:
    out = []
    for i, line in enumerate(lines, 1):
        start = float(line[0].get("s", 0))
        end = float(line[-1].get("e", start + 1))
        text = " ".join(w["w"] for w in line)
        out.append(f"{i}\n{srt_ts(start)} --> {srt_ts(end)}\n{text}\n")
    return "\n".join(out)


def caption_font_px(width: int, height: int, size_pct: float) -> int:
    """ASS font size is in PlayRes units, so it scales with height, not width.

    Vertical video must not get the width-based half-size text it used to.
    """
    return max(12, int(min(height * size_pct, width * 0.09)))


def chars_per_line(width: int, font_px: int) -> int:
    """Keep a line inside ~88% of the frame at the chosen font size."""
    return max(12, int(width * 0.88 / max(font_px * 0.55, 1)))


def build_ass(lines, width: int, height: int, style: dict, position: str = "bottom",
              lang: str = "hi", resolution=None) -> str:
    res_x, res_y = resolution or (width, height)
    font_size = caption_font_px(res_x, res_y, style["size_pct"])
    margin_v = int(res_y * {"bottom": 0.16, "middle": 0.48, "top": 0.10}[position])
    align = {"bottom": 2, "middle": 5, "top": 8}[position]
    font = DEVANAGARI_FONT if lang in ("hi", "hinglish") else style["font"]
    header = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {res_x}",
        f"PlayResY: {res_y}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: VFE,{font},{font_size},{style['primary']},{style['highlight']},&H00101010,&H80000000,"
        f"{style['bold']},0,0,0,100,100,0,0,1,{style['outline']},{style['shadow']},{align},"
        f"{int(res_x * 0.06)},{int(res_x * 0.06)},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = []
    for line in lines:
        start = float(line[0].get("s", 0))
        end = float(line[-1].get("e", start + 0.6))
        pieces = []
        for w in line:
            text = w["w"]
            if style.get("upper"):
                text = text.upper()
            dur = max(int(round((float(w.get("e", 0)) - float(w.get("s", 0))) * 100)), 8)
            pieces.append(f"{{\\k{dur}}}{text}")
        events.append(f"Dialogue: 0,{ass_ts(start)},{ass_ts(end)},VFE,,0,0,0,,{' '.join(pieces)}")
    return "\n".join(header + events) + "\n"


def safe_zone_ok(lines, max_chars: int = 32, max_words: int = 4) -> list:
    bad = []
    for line in lines:
        text = " ".join(w["w"] for w in line)
        if len(text) > max_chars or len(line) > max_words:
            bad.append(text)
    return bad


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build SRT + ASS captions")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--lang", default=None, choices=["hi", "hinglish", "en", "none"])
    parser.add_argument("--style", default=None, choices=sorted(STYLES))
    parser.add_argument("--position", default="bottom", choices=["bottom", "middle", "top"])
    parser.add_argument("--burn", action="store_true", help="also render captions into a copy")
    parser.add_argument("--max-chars", type=int, default=32)
    parser.add_argument("--words", default=None, help="path to words.json")
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    dev = device_plan(args.device, caps)

    with stage("caption", args) as run:
        run.device = dev["resolved"]
        path = expand_inputs([args.input])[0]
        work = work_dir(root, f"p-{path.stem}")
        plan_path = state.get("artifacts", {}).get("plan")
        plan = read_json(plan_path, {}) if plan_path and Path(plan_path).is_file() else {}
        cap_cfg = plan.get("captions", {}) or {}
        lang = args.lang or cap_cfg.get("lang", "hi")
        style_name = args.style or cap_cfg.get("style", "bold-pop")
        style = dict(STYLES.get(style_name, STYLES["bold-pop"]))
        width = int((plan.get("output") or {}).get("width", 1080))
        height = int((plan.get("output") or {}).get("height", 1920))

        words_path = Path(args.words) if args.words else work / "words.json"
        if not words_path.is_file():
            asr_artifact = (state.get("artifacts") or {}).get("asr")
            if asr_artifact and Path(asr_artifact).is_file():
                words_path = Path(asr_artifact)
        if not words_path.is_file():
            raise InvalidInput(
                f"no transcript at {words_path}",
                fix=f'python scripts/asr.py "{path}" --lang {lang}',
                doc="references/troubleshooting.md#asr",
            )
        transcript = read_json(words_path, {})
        font_px = caption_font_px(width, height, style["size_pct"])
        max_chars = min(args.max_chars, chars_per_line(width, font_px))
        lines = chunk_words(transcript.get("words", []), max_chars,
                            cap_cfg.get("words_per_line", [2, 4])[0],
                            cap_cfg.get("words_per_line", [2, 4])[1])
        if not lines:
            raise InvalidInput("no caption lines produced", fix="check words.json has timings")

        srt = path.with_suffix(".srt")
        ass = path.with_suffix(".ass")
        if not args.dry_run:
            srt.write_text(to_srt(lines), encoding="utf-8", newline="\n")
            ass.write_text(build_ass(lines, width, height, style, args.position, lang), encoding="utf-8", newline="\n")

        bad = safe_zone_ok(lines, max_chars, 4)
        run.add_check("caption_lines", "pass" if not bad else "warn", len(lines), "> 0")
        run.add_check("caption_length", "pass" if not bad else "warn", len(bad), "0 lines over limit")

        out_path = str(srt)
        if args.burn:
            burned = work / "captioned.mp4"
            font_dir = fonts_dir(root)
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
                   "-vf", f"subtitles={filter_path(ass)}:fontsdir={filter_path(font_dir)}",
                   *encoder_args(dev["encoder"], 20), "-c:a", "copy", "-movflags", "+faststart", str(burned)]
            run_cmd(cmd, dry_run=args.dry_run, timeout=7200)
            out_path = str(burned)
        if not args.dry_run:
            state = ensure_edit(root)
            record_stage(root, state, "caption", out_path, lines=len(lines), style=style_name, lang=lang)
        artifacts = [str(srt), str(ass)] + ([out_path] if args.burn else [])
        run.ok(output=out_path, artifacts=artifacts,
               next_cmd=f'python scripts/audio.py "{out_path}" --json')
        if not args.json:
            print(f"{len(lines)} caption lines -> {srt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
