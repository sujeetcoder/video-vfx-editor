#!/usr/bin/env python3
"""Intake: 5–8 pre-filled questions, detected defaults, presets.

    python scripts/intake.py --ask            # numbered block, "ok" accepts defaults
    python scripts/intake.py --preset reel
    python scripts/intake.py --set lang=en --set energy=tight
    python scripts/intake.py --json           # questions for the agent to ask in chat
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import InvalidInput, add_common, stage  # noqa: E402
from _paths import (append_decision, decided_text, ensure_edit, project_root,  # noqa: E402
                    record_stage, work_dir, write_json)

QUESTIONS = [
    {
        "id": "job",
        "header": "Job",
        "question": "Do you want one polished edit, or clips cut out of a long video?",
        "options": [
            {"label": "edit", "description": "one finished video with captions, audio and gates", "recommended": True},
            {"label": "clip", "description": "3–10 self-contained vertical clips from a long recording"},
        ],
        "default": "edit",
    },
    {
        "id": "playbook",
        "header": "Format",
        "question": "Which format should the edit follow?",
        "options": [
            {"label": "auto", "description": "pick from duration, aspect and content", "recommended": True},
            {"label": "reel", "description": "short vertical reel / short (≤ 60 s)"},
            {"label": "youtube", "description": "long-form 16:9 edit"},
            {"label": "podcast", "description": "talking-head or two-person podcast"},
            {"label": "tutorial", "description": "screen or demo walkthrough"},
            {"label": "ad", "description": "short product/sales edit"},
            {"label": "wedding", "description": "event highlights"},
            {"label": "vlog", "description": "day-in-the-life travel/vlog"},
            {"label": "music", "description": "beat-cut music video"},
            {"label": "presenter", "description": "presenter to camera with graphics"},
            {"label": "clip-podcast", "description": "clips from a long conversation"},
            {"label": "clip-stream", "description": "clips from a stream or gameplay VOD"},
            {"label": "clip-lecture", "description": "clips from a class or webinar"},
        ],
        "default": "auto",
    },
    {
        "id": "aspect",
        "header": "Aspect",
        "question": "What aspect ratio is the deliverable?",
        "options": [
            {"label": "9:16", "description": "Reels, Shorts, TikTok", "recommended": True},
            {"label": "16:9", "description": "YouTube, web"},
            {"label": "1:1", "description": "feed posts"},
            {"label": "4:5", "description": "Instagram portrait feed"},
        ],
        "default": "9:16",
    },
    {
        "id": "lang",
        "header": "Language",
        "question": "Caption language?",
        "options": [
            {"label": "hi", "description": "Hindi in Devanagari — the default", "recommended": True},
            {"label": "hinglish", "description": "Hindi spoken, Roman script"},
            {"label": "en", "description": "English"},
            {"label": "none", "description": "no captions"},
        ],
        "default": "hi",
    },
    {
        "id": "caption_style",
        "header": "Captions",
        "question": "Caption look?",
        "options": [
            {"label": "bold-pop", "description": "big bold lines with a highlight colour", "recommended": True},
            {"label": "clean", "description": "small clean lower-third subtitles"},
            {"label": "karaoke", "description": "word-by-word highlight"},
            {"label": "none", "description": "burn nothing"},
        ],
        "default": "bold-pop",
    },
    {
        "id": "energy",
        "header": "Pace",
        "question": "How tight should the cut feel?",
        "options": [
            {"label": "tight", "description": "remove silences and fillers aggressively", "recommended": True},
            {"label": "natural", "description": "keep breaths, mild trimming"},
            {"label": "cinematic", "description": "keep pauses, let shots breathe"},
        ],
        "default": "tight",
    },
    {
        "id": "audio",
        "header": "Audio",
        "question": "Audio treatment?",
        "options": [
            {"label": "clean", "description": "denoise, dehum, −14 LUFS", "recommended": True},
            {"label": "music-bed", "description": "clean voice + ducked music bed"},
            {"label": "raw", "description": "keep the original mix (loudness check only)"},
        ],
        "default": "clean",
    },
    {
        "id": "effects",
        "header": "Effects",
        "question": "Any extra finishing?",
        "options": [
            {"label": "auto", "description": "use what the footage needs (chroma if green, reframe if faces)", "recommended": True},
            {"label": "none", "description": "cut, captions and audio only"},
            {"label": "lower-third", "description": "name/title lower-third"},
            {"label": "chroma", "description": "replace a green screen background"},
            {"label": "matte", "description": "cut the person out without a green screen"},
        ],
        "default": "auto",
    },
]

PRESETS = {
    "reel": {"job": "edit", "playbook": "reel", "aspect": "9:16", "lang": "hi", "caption_style": "bold-pop",
             "energy": "tight", "audio": "clean", "effects": "auto"},
    "podcast": {"job": "edit", "playbook": "podcast", "aspect": "16:9", "lang": "hi", "caption_style": "clean",
                "energy": "natural", "audio": "clean", "effects": "auto"},
    "tutorial": {"job": "edit", "playbook": "tutorial", "aspect": "16:9", "lang": "hi", "caption_style": "clean",
                 "energy": "natural", "audio": "clean", "effects": "none"},
    "ad": {"job": "edit", "playbook": "ad", "aspect": "9:16", "lang": "hi", "caption_style": "bold-pop",
           "energy": "tight", "audio": "music-bed", "effects": "lower-third"},
    "clip": {"job": "clip", "playbook": "clip-podcast", "aspect": "9:16", "lang": "hi",
             "caption_style": "bold-pop", "energy": "tight", "audio": "clean", "effects": "auto"},
    "wedding": {"job": "edit", "playbook": "wedding", "aspect": "16:9", "lang": "none", "caption_style": "none",
                "energy": "cinematic", "audio": "music-bed", "effects": "none"},
    "vlog": {"job": "edit", "playbook": "vlog", "aspect": "9:16", "lang": "hi", "caption_style": "bold-pop",
             "energy": "natural", "audio": "clean", "effects": "none"},
}

DEFAULTS_FROM_PROBE = {
    "duration_long": 600,
    "duration_short": 90,
}


def detected_defaults(probe: dict) -> dict:
    """Pre-fill answers from probe.json. Never guesses silently: each has a reason."""
    out = {}
    reasons = {}
    dur = float(probe.get("duration") or 0)
    aspect = probe.get("aspect") or 0
    quick = probe.get("quick") or {}
    if dur >= DEFAULTS_FROM_PROBE["duration_long"]:
        out["job"] = "clip"
        reasons["job"] = f"{int(dur)}s long — clip candidates pay off"
    else:
        out["job"] = "edit"
        reasons["job"] = f"{int(dur)}s — one edit"
    if aspect and 0.95 <= aspect <= 1.05:
        out["aspect"] = "1:1"
    elif aspect and aspect < 0.9:
        out["aspect"] = "9:16"
    else:
        out["aspect"] = "16:9"
    reasons["aspect"] = f"source aspect {aspect:.2f}"
    if quick.get("green_screen"):
        out["effects"] = "chroma"
        reasons["effects"] = f"green covers {quick.get('green_fraction', 0):.0%} of the border"
    elif quick.get("faces") is not None and quick.get("faces", 0) > 0 and out["aspect"] == "9:16":
        out["effects"] = "matte"
        reasons["effects"] = "face detected in a vertical deliverable"
    else:
        out["effects"] = "none"
    if quick.get("language_guess"):
        out["lang"] = quick["language_guess"]
        reasons["lang"] = "whisper tiny on the first 30 s"
    if out["job"] == "clip":
        out["playbook"] = "clip-podcast"
    return {"answers": out, "reasons": reasons}


def question_block(questions, answers) -> str:
    lines = ["Answer the numbers, or say 'ok' to accept every default.", ""]
    for i, q in enumerate(questions, 1):
        default = answers.get(q["id"], q["default"])
        lines.append(f"{i}. {q['header']}: {q['question']}")
        for j, opt in enumerate(q["options"], 1):
            mark = "*" if opt["label"] == default else " "
            lines.append(f"   {j}) {mark}{opt['label']:<12} {opt['description']}")
        lines.append(f"   default: {default}")
        lines.append("")
    return "\n".join(lines)


def merge_answers(base: dict, updates: dict) -> dict:
    out = dict(base)
    for key, value in updates.items():
        q = next((q for q in QUESTIONS if q["id"] == key), None)
        if q is None:
            raise InvalidInput(f"unknown intake key '{key}'",
                               fix=f"valid keys: {[q['id'] for q in QUESTIONS]}")
        allowed = [o["label"] for o in q["options"]]
        if value not in allowed:
            raise InvalidInput(f"'{value}' is not a valid answer for {key}",
                               fix=f"choose one of {allowed}")
        out[key] = value
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect the intake answers")
    add_common(parser)
    parser.add_argument("--ask", action="store_true", help="interactive numbered block")
    parser.add_argument("--preset", default=None, choices=sorted(PRESETS))
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--answers", default=None, help="JSON file with answers")
    parser.add_argument("--probe", default=None, help="probe.json used for detected defaults")
    parser.add_argument("--force", action="store_true", help="re-ask even if intake.json exists")
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    intake_path = work_dir(root) / "intake.json"

    with stage("intake", args) as run:
        probe = {}
        probe_path = args.probe or state.get("artifacts", {}).get("probe")
        if probe_path and Path(probe_path).is_file():
            probe = json.loads(Path(probe_path).read_text(encoding="utf-8"))
        detected = detected_defaults(probe)

        existing = {}
        if intake_path.is_file() and not args.force:
            existing = json.loads(intake_path.read_text(encoding="utf-8")).get("answers", {})
        answers = dict(detected["answers"])
        answers.update(existing or {})
        if args.preset:
            answers.update(PRESETS[args.preset])
        if args.answers:
            answers.update(json.loads(Path(args.answers).read_text(encoding="utf-8")))
        for pair in args.set:
            if "=" not in pair:
                raise InvalidInput(f"--set needs KEY=VALUE, got {pair!r}")
            key, value = pair.split("=", 1)
            answers = merge_answers(answers, {key.strip(): value.strip()})

        if args.ask and not args.json:
            answers = _ask(questions=QUESTIONS, answers=answers)
        elif args.json and not existing and not args.preset:
            # The agent asks in chat; we return the bank + detected defaults.
            run.ok(output=None, artifacts=[],
                   next_cmd="python scripts/intake.py --set job=edit --set aspect=9:16")
            payload = {"questions": QUESTIONS, "answers": answers, "reasons": detected["reasons"],
                       "decisions_seen": bool(decided_text(root).strip())}
            if not args.dry_run:
                write_json(work_dir(root) / "questions.json", payload)
            run.quiet = True
            sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
            return 0

        data = {"schema": 1, "answers": answers, "reasons": detected["reasons"],
                "preset": args.preset, "questions": QUESTIONS}
        if not args.dry_run:
            write_json(intake_path, data)
            state = ensure_edit(root)
            state.setdefault("params", {}).update({"job": answers.get("job", "edit"),
                                                   "lang": answers.get("lang", "hi"),
                                                   "preset": args.preset})
            record_stage(root, state, "intake", intake_path, job=answers.get("job"))
            append_decision(root, "intake " + json.dumps(answers, ensure_ascii=False, sort_keys=True))
        run.ok(output=str(intake_path), artifacts=[str(intake_path)],
               next_cmd=f'python scripts/plan.py "{state.get("artifacts", {}).get("probe", "")}"')
        if not args.json:
            print(json.dumps(answers, indent=2, ensure_ascii=False))
    return 0


def _ask(questions, answers) -> dict:
    print(question_block(questions, answers))
    raw = input("answers (numbers separated by space, or 'ok'): ").strip().lower()
    if raw in ("", "ok", "yes"):
        return answers
    tokens = raw.replace(",", " ").split()
    out = dict(answers)
    for i, q in enumerate(questions, 1):
        if str(i) in tokens:
            choice = input(f"  {q['header']} 1-{len(q['options'])} [{q['default']}]: ").strip()
            if not choice:
                continue
            idx = int(choice) - 1 if choice.isdigit() else -1
            if 0 <= idx < len(q["options"]):
                out[q["id"]] = q["options"][idx]["label"]
        elif q["id"] not in out:
            out[q["id"]] = q["default"]
    return merge_answers(answers, out) if out else answers


if __name__ == "__main__":
    sys.exit(main())
