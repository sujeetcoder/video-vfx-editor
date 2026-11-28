#!/usr/bin/env python3
"""Compile intake + probe + playbook + style into plan.json (and candidates for clip jobs).

    python scripts/plan.py edit/work/p-xxx/probe.json --json
    python scripts/plan.py video.mp4 --job clip --json     # stops for approval
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan  # noqa: E402
from _contract import InvalidInput, add_common, stage  # noqa: E402
from _paths import (append_decision, ensure_edit, expand_inputs, project_root,  # noqa: E402
                    read_json, record_stage, work_dir, write_json)

PLAYBOOKS = {
    "reel": {"aspect": "9:16", "max_duration": 60, "shot_len": [1.2, 3.5], "caption": "bold-pop",
             "energy": "tight", "loudness": -14.0, "fps": 30, "layout": "fill"},
    "youtube": {"aspect": "16:9", "max_duration": 1800, "shot_len": [3.0, 8.0], "caption": "clean",
                "energy": "natural", "loudness": -14.0, "fps": 30, "layout": "fill"},
    "podcast": {"aspect": "16:9", "max_duration": 7200, "shot_len": [4.0, 12.0], "caption": "clean",
                "energy": "natural", "loudness": -16.0, "fps": 30, "layout": "split"},
    "tutorial": {"aspect": "16:9", "max_duration": 1200, "shot_len": [4.0, 10.0], "caption": "clean",
                 "energy": "natural", "loudness": -16.0, "fps": 30, "layout": "fill"},
    "ad": {"aspect": "9:16", "max_duration": 45, "shot_len": [0.8, 2.5], "caption": "bold-pop",
           "energy": "tight", "loudness": -14.0, "fps": 30, "layout": "fill"},
    "wedding": {"aspect": "16:9", "max_duration": 300, "shot_len": [2.5, 6.0], "caption": "none",
                "energy": "cinematic", "loudness": -16.0, "fps": 24, "layout": "fill"},
    "vlog": {"aspect": "9:16", "max_duration": 180, "shot_len": [2.0, 5.0], "caption": "bold-pop",
             "energy": "natural", "loudness": -14.0, "fps": 30, "layout": "fill"},
    "music": {"aspect": "9:16", "max_duration": 180, "shot_len": [0.6, 2.0], "caption": "none",
              "energy": "tight", "loudness": -14.0, "fps": 30, "layout": "fill"},
    "presenter": {"aspect": "9:16", "max_duration": 120, "shot_len": [2.0, 5.0], "caption": "bold-pop",
                  "energy": "natural", "loudness": -14.0, "fps": 30, "layout": "fill"},
    "clip-podcast": {"aspect": "9:16", "max_duration": 90, "shot_len": [2.0, 6.0], "caption": "bold-pop",
                     "energy": "tight", "loudness": -14.0, "fps": 30, "layout": "split",
                     "clip_len": [15, 90], "clip_count": 5},
    "clip-stream": {"aspect": "9:16", "max_duration": 60, "shot_len": [1.5, 4.0], "caption": "bold-pop",
                    "energy": "tight", "loudness": -14.0, "fps": 30, "layout": "fill",
                    "clip_len": [15, 60], "clip_count": 6},
    "clip-lecture": {"aspect": "9:16", "max_duration": 90, "shot_len": [3.0, 8.0], "caption": "clean",
                     "energy": "natural", "loudness": -14.0, "fps": 30, "layout": "fill",
                     "clip_len": [20, 90], "clip_count": 4},
}

# Motion a playbook earns: short-form gets a live camera, long-form talks stay still.
MOTION_BY_PLAYBOOK = {
    "reel": "ken-burns", "ad": "zoom-in", "vlog": "ken-burns", "presenter": "ken-burns",
    "music": "ken-burns", "wedding": "ken-burns", "clip-stream": "zoom-in",
}
# Long-form earns fewer, spaced inserts rather than none: 3 is a starting point, not a ceiling.
BROLL_BY_PLAYBOOK = {"reel": 2, "ad": 2, "vlog": 2, "presenter": 2, "youtube": 3, "tutorial": 3}

ASPECT_SIZE = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


def auto_playbook(probe: dict, answers: dict) -> str:
    if answers.get("job") == "clip":
        dur = float(probe.get("duration") or 0)
        return "clip-lecture" if dur > 2700 else "clip-podcast"
    if answers.get("playbook") and answers["playbook"] != "auto":
        return answers["playbook"]
    dur = float(probe.get("duration") or 0)
    if dur <= 90:
        return "reel"
    if dur <= 900:
        return "tutorial" if (probe.get("quick") or {}).get("faces") == 0 else "presenter"
    return "podcast"


def load_style(root, name: str | None) -> dict | None:
    if not name:
        return None
    path = Path(root) / "styles" / name / "style.json"
    if not path.is_file():
        raise InvalidInput(f"style profile '{name}' not found",
                           fix=f"train it first: python scripts/style.py learn <refs> --name {name}",
                           doc="references/style-learning.md")
    return read_json(path, {})


def apply_style(plan: dict, style: dict) -> dict:
    """Clamp plan fields inside the learned tolerances and record what moved."""
    out = json.loads(json.dumps(plan))
    dev = {}
    audio = style.get("audio", {})
    captions = style.get("captions", {})
    rhythm = style.get("rhythm", {})
    if audio.get("loudness") is not None:
        dev["loudness"] = out["output"]["loudness"]
        out["output"]["loudness"] = round(float(audio["loudness"]), 1)
    if captions.get("style"):
        out["captions"]["style"] = captions["style"]
    if captions.get("position"):
        out["captions"]["position"] = captions["position"]
    if rhythm.get("median_shot") and rhythm.get("cut_rhythm"):
        target = float(rhythm["median_shot"])
        out["cut"]["target_shot_len"] = round(target, 2)
    out["style"] = {"name": style.get("name"), "clamped": dev}
    return out


def build_plan(probe: dict, answers: dict, playbook: str, caps: dict, device: str) -> dict:
    pb = PLAYBOOKS.get(playbook)
    if pb is None:
        raise InvalidInput(f"unknown playbook '{playbook}'", fix=f"choose from {sorted(PLAYBOOKS)}")
    aspect = answers.get("aspect") or pb["aspect"]
    width, height = ASPECT_SIZE.get(aspect, ASPECT_SIZE[pb["aspect"]])
    lang = answers.get("lang", "hi")
    duration = float(probe.get("duration") or 0)
    target_dur = min(duration, float(pb["max_duration"])) if duration else float(pb["max_duration"])
    effects = answers.get("effects", "auto")
    caption_style = answers.get("caption_style") if answers.get("caption_style") not in (None, "none") \
        else pb["caption"]
    broll_answer = str(answers.get("broll") or "auto")
    broll_count = 0 if broll_answer == "none" else (
        int(broll_answer) if broll_answer.isdigit() else BROLL_BY_PLAYBOOK.get(playbook, 0))
    quick = probe.get("quick") or {}
    features = {
        "chroma": effects == "chroma" or (effects == "auto" and bool(quick.get("green_screen"))),
        "person_matte": effects == "matte",
        "lower_third": effects == "lower-third",
        "progress_bar": playbook in ("reel", "youtube") and duration > 60,
    }
    plan = {
        "schema": 1,
        "job": answers.get("job", "edit"),
        "playbook": playbook,
        "source": probe.get("path"),
        "source_duration": duration,
        "source_aspect": probe.get("aspect"),
        "source_width": probe.get("width"),
        "source_height": probe.get("height"),
        "output": {
            "aspect": aspect,
            "width": width,
            "height": height,
            "fps": int(pb["fps"]),
            "container": "mp4",
            "loudness": float(pb["loudness"]),
            "true_peak": -1.0,
            "duration_limit": float(pb["max_duration"]),
            "target_duration": round(target_dur, 2),
            "encoder": device_plan("auto", caps)["encoder"],
        },
        "captions": {
            "enabled": lang != "none",
            "lang": lang,
            "style": caption_style,
            "position": "middle" if caption_style == "kinetic" else "bottom",
            "max_chars": 32,
            "words_per_line": [1, 1] if caption_style == "kinetic" else [2, 4],
            "karaoke": answers.get("caption_style") == "karaoke",
            "safe_zone": {"bottom_pct": 18 if aspect == "9:16" else 8, "top_pct": 8},
        },
        "audio": {
            "chain": answers.get("audio", "clean"),
            "denoise": answers.get("audio") in ("clean", "music-bed"),
            "dehum": True,
            "highpass": 80,
            "music_bed": answers.get("audio") == "music-bed",
            "duck_db": 1.5,
        },
        "cut": {
            "enabled": True,
            "remove_silence": answers.get("energy", "tight") == "tight",
            "min_silence": 0.45 if answers.get("energy", "tight") == "tight" else 0.7,
            "pad": 0.12,
            "remove_fillers": answers.get("energy", "tight") == "tight",
            "filler_words": ["matlab", "yaani", "toh", "umm", "aaa", "matlab ki", "like", "you know"],
            "target_shot_len": pb["shot_len"],
            "fade_ms": 30,
        },
        "motion": {
            "preset": answers.get("motion") or MOTION_BY_PLAYBOOK.get(playbook, "none"),
            "amount": float(answers.get("motion_amount") or 1.16),
        },
        "broll": {"count": broll_count, "query": answers.get("broll_query") or None},
        "assets": {"background": None, "broll": [], "overlays": [], "subtitles": None},
        "effects": features,
        "layout": pb["layout"],
        "gates": {
            "loudness_tolerance": 1.0,
            "true_peak_max": -1.0,
            "blackdetect_min": 0.15,
            "freezedetect_min": 2.0,
            "caption_max_chars": 32,
            "hook_within": 1.5,
            "crop_keep_min": 0.55,
        },
        "device": device,
        "clip": {
            "count": pb.get("clip_count", 5),
            "len": pb.get("clip_len", [15, 90]),
        } if plan_job_is_clip(answers) else None,
    }
    return plan


def plan_job_is_clip(answers: dict) -> bool:
    return answers.get("job") == "clip"


def load_assets(root) -> dict:
    path = work_dir(root, "assets") / "assets.json"
    return read_json(path, {}) if path.is_file() else {}


def apply_assets(plan: dict, assets: dict) -> dict:
    """A scanned shoot folder supplies the bed, the backdrop, the inserts and the subs."""
    roles = (assets or {}).get("roles") or {}
    if roles.get("music"):
        plan["audio"].update({"music": roles["music"], "music_bed": True})
    if roles.get("background"):
        plan["assets"]["background"] = roles["background"]
        if plan["output"]["aspect"] != plan.get("source_aspect"):
            plan["layout"] = "backdrop"  # padded frame gets the supplied art, not black
    for key in ("broll", "overlays"):
        if roles.get(key):
            plan["assets"][key] = list(roles[key])
    if roles.get("subtitles"):
        plan["assets"]["subtitles"] = roles["subtitles"]
    return plan


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build plan.json from intake + probe + playbook")
    add_common(parser)
    parser.add_argument("input", help="probe.json or media file")
    parser.add_argument("--job", default=None, choices=["edit", "clip"])
    parser.add_argument("--preset", default=None)
    parser.add_argument("--style", default=None, help="style profile name from styles/")
    parser.add_argument("--set", action="append", default=[])
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    device = device_plan(args.device, caps)["resolved"]

    with stage("plan", args) as run:
        run.device = device
        src = Path(str(args.input).strip('"\''))
        probe = {}
        if src.is_file() and src.suffix.lower() == ".json":
            probe = read_json(src, {})
        else:
            files = expand_inputs([args.input])
            from probe import probe_file

            probe = probe_file(files[0], quick=False, dry_run=args.dry_run)

        intake_path = work_dir(root) / "intake.json"
        answers = {}
        if intake_path.is_file():
            answers = read_json(intake_path, {}).get("answers", {})
        if args.preset:
            from intake import PRESETS

            answers.update(PRESETS[args.preset])
        for pair in args.set:
            if "=" in pair:
                k, v = pair.split("=", 1)
                answers[k] = v
        if args.job:
            answers["job"] = args.job
        answers.setdefault("job", state.get("job", "edit"))
        answers.setdefault("lang", state.get("params", {}).get("lang", "hi"))
        answers.setdefault("energy", "tight")
        answers.setdefault("audio", "clean")
        answers.setdefault("effects", "auto")
        answers.setdefault("aspect", "9:16")
        answers.setdefault("motion", None)
        answers.setdefault("broll", "auto")
        answers.setdefault("broll_query", None)

        playbook = auto_playbook(probe, answers)
        plan = build_plan(probe, answers, playbook, caps, device)
        plan = apply_assets(plan, load_assets(root))
        if args.style:
            plan = apply_style(plan, load_style(root, args.style))

        key = Path(probe.get("path") or "plan").stem
        work = work_dir(root, f"p-{key}")
        plan_path = work / "plan.json"

        if plan["job"] == "clip":
            from clipfind import find_candidates, candidate_table

            transcript = None
            words_path = work / "words.json"
            if words_path.is_file():
                transcript = read_json(words_path, {})
            cands = find_candidates(probe, transcript, plan)
            write_json(work / "candidates.json", cands)
            plan["candidates"] = cands["candidates"]
            plan["candidates_path"] = str(work / "candidates.json")
            plan["approved"] = []
            if not args.dry_run:
                write_json(plan_path, plan)
                state = ensure_edit(root)
                state["job"] = "clip"
                state.setdefault("params", {}).update({"job": "clip", "playbook": playbook})
                record_stage(root, state, "plan", plan_path, job="clip", candidates=len(plan["candidates"]))
                append_decision(root, f"plan clip playbook={playbook} candidates={len(plan['candidates'])}")
            run.ok(output=str(plan_path), artifacts=[str(plan_path), str(work / "candidates.json")],
                   next_cmd="python scripts/forge.py approve 1 2 3",
                   checks=[{"id": "candidates", "status": "pass" if plan["candidates"] else "fail",
                            "value": len(plan["candidates"]), "target": ">= 3"}])
            if not args.json:
                print(candidate_table(cands))
                print("\nApprove some: python scripts/forge.py approve 1 4 7")
            return 0

        if not args.dry_run:
            write_json(plan_path, plan)
            state = ensure_edit(root)
            state["job"] = plan["job"]
            state.setdefault("params", {}).update({"job": plan["job"], "playbook": playbook})
            record_stage(root, state, "plan", plan_path, playbook=playbook)
            append_decision(root, f"plan edit playbook={playbook} aspect={plan['output']['aspect']} "
                                  f"lang={plan['captions']['lang']}")
        run.ok(output=str(plan_path), artifacts=[str(plan_path)],
               next_cmd=f'python scripts/cut.py "{probe.get("path")}"')
        if not args.json:
            print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
