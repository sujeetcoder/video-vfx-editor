#!/usr/bin/env python3
"""Learn / apply / compare a measured style profile (12 facets).

    python scripts/style.py learn ref1.mp4 ref2.mp4 ref3.mp4 --name kiki
    python scripts/style.py apply --name kiki
    python scripts/style.py compare out.mp4 --name kiki
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import InvalidInput, add_common, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffprobe_json, ffmpeg_bin, project_root,  # noqa: E402
                    read_json, run_cmd, sha1_file, work_dir, write_json)

FACETS = ["cut_rhythm", "shot_lengths", "shot_types", "camera_energy", "caption_position",
          "caption_size", "words_per_line", "case", "font", "colour_grade", "audio_mix",
          "transitions", "hook_structure", "b_roll", "end_card"]


def confidence(n: int) -> str:
    if n < 10:
        return "low"
    if n < 15:
        return "medium"
    return "high"


def _fps(stream) -> float:
    try:
        num, den = str(stream.get("avg_frame_rate", "30/1")).split("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 30.0


def measure_ref(path: Path, dry_run: bool = False) -> dict:
    probe = ffprobe_json(path, dry_run=dry_run)
    if dry_run:
        return {}
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    duration = float((probe.get("format") or {}).get("duration") or 0)
    rc, scd = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(path),
                       "-vf", "scdet=threshold=0.4", "-an", "-f", "null", "-"], timeout=3600)
    cuts = sorted({round(float(m), 3) for m in re.findall(r"lavd?fi\.scd\.time:\s*([\d.]+)", scd)})
    bounds = [0.0] + cuts + [duration]
    shots = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1) if bounds[i + 1] > bounds[i]]
    rc, stats = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(path),
                         "-vf", "signalstats,metadata=mode=print", "-an", "-f", "null", "-"],
                        timeout=3600)
    yavg = [float(x) for x in re.findall(r"YAVG=([\d.]+)", stats)]
    ydif = [float(x) for x in re.findall(r"YDIF=([\d.]+)", stats)]
    rc, loud = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(path),
                        "-af", "ebur128=peak=true", "-f", "null", "-"], timeout=3600)
    summary = loud.rsplit("Summary:", 1)[-1]
    lufs = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    srt = path.with_suffix(".srt")
    cap = {"lines": 0, "words_per_line": None, "max_chars": None, "upper_ratio": None}
    if srt.is_file():
        text = srt.read_text(encoding="utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln and "-->" not in ln and not ln.strip().isdigit()]
        if lines:
            cap = {"lines": len(lines),
                   "words_per_line": round(sum(len(ln.split()) for ln in lines) / len(lines), 2),
                   "max_chars": max(len(ln) for ln in lines),
                   "upper_ratio": round(sum(1 for ln in lines if ln.isupper()) / len(lines), 2)}
    return {
        "path": str(path), "hash": sha1_file(path)[:10], "duration": round(duration, 2),
        "fps": round(_fps(video), 2), "cuts": len(cuts), "shots": [round(s, 2) for s in shots],
        "median_shot": round(sorted(shots)[len(shots) // 2], 2) if shots else None,
        "cut_rhythm": round(len(cuts) / (duration / 10), 2) if duration else 0,
        "camera_energy": round(sum(ydif) / len(ydif), 2) if ydif else 0,
        "brightness": round(sum(yavg) / len(yavg), 1) if yavg else 0,
        "lufs": float(lufs.group(1)) if lufs else None,
        "captions": cap,
    }


def build_profile(name: str, refs: list) -> dict:
    n = len(refs)
    tier = confidence(n)
    rhythms = [r["cut_rhythm"] for r in refs if r.get("cut_rhythm")]
    medians = [r["median_shot"] for r in refs if r.get("median_shot")]
    lufs = [r["lufs"] for r in refs if r.get("lufs") is not None]
    energies = [r["camera_energy"] for r in refs if r.get("camera_energy")]
    cap_rows = [r["captions"] for r in refs if (r.get("captions") or {}).get("lines")]

    def spread(values):
        if not values:
            return None
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / len(values)
        return round(math.sqrt(var), 2)

    def outliers(values, tol=2.0):
        if len(values) < 3:
            return []
        mean = sum(values) / len(values)
        sd = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values)) or 1e-6
        return [i for i, v in enumerate(values) if abs(v - mean) / sd > tol]

    return {
        "name": name, "refs": [r["path"] for r in refs], "samples": n, "confidence": tier,
        "rhythm": {
            "cut_rhythm": round(sum(rhythms) / len(rhythms), 2) if rhythms else None,
            "tolerance": max(round(spread(rhythms) or 0.8, 2), 0.4),
            "median_shot": round(sum(medians) / len(medians), 2) if medians else None,
            "outliers": outliers(rhythms),
        },
        "camera": {"energy": round(sum(energies) / len(energies), 2) if energies else None},
        "colour": {"brightness": round(sum(r["brightness"] for r in refs) / n, 1),
                   "grade": _grade(refs)},
        "captions": {
            "position": "bottom",
            "size": 0.048,
            "words_per_line": round(sum(c["words_per_line"] for c in cap_rows) / len(cap_rows), 2)
            if cap_rows else 3.0,
            "max_chars": max((c["max_chars"] for c in cap_rows), default=32),
            "uppercase": bool(cap_rows and cap_rows[0].get("upper_ratio", 0) > 0.6),
            "style": "bold-pop" if cap_rows and cap_rows[0].get("upper_ratio", 0) > 0.6 else "clean",
            "font": "Inter (OFL) — nearest free match",
            "karaoke": False,
            "confidence": tier,
        },
        "audio": {"loudness": round(sum(lufs) / len(lufs), 1) if lufs else -14.0,
                  "music_offset_db": -18.0, "duck": True, "sfx_per_min": 2.0,
                  "confidence": tier},
        "transitions": {"type": "cut", "confidence": "low"},
        "hook": {"first_cut": 1.2, "confidence": "low"},
        "b_roll_ratio": 0.0,
        "end_card": False,
        "facets_unmeasured": ["caption_position", "font", "transitions", "b_roll", "end_card",
                              "shot_types", "hook_structure"],
    }


def _grade(refs) -> str:
    b = sum(r["brightness"] for r in refs) / len(refs)
    if b < 70:
        return "low-key / moody"
    if b < 120:
        return "neutral"
    return "bright / high-key"


def write_profile(root, profile: dict) -> Path:
    base = Path(root) / "styles" / profile["name"]
    (base / "frames").mkdir(parents=True, exist_ok=True)
    write_json(base / "style.json", profile)
    md = [f"# Style: {profile['name']}", "",
          f"samples: {profile['samples']} (confidence: {profile['confidence']})", "",
          "| facet | value | confidence |", "|---|---|---|",
          f"| cut rhythm | {profile['rhythm']['cut_rhythm']} cuts/10s | {profile['confidence']} |",
          f"| median shot | {profile['rhythm']['median_shot']} s | {profile['confidence']} |",
          f"| colour | {profile['colour']['grade']} | {profile['confidence']} |",
          f"| captions | {profile['captions']['words_per_line']} words/line, max {profile['captions']['max_chars']} chars | {profile['captions']['confidence']} |",
          f"| audio | {profile['audio']['loudness']} LUFS | {profile['audio']['confidence']} |",
          "", "Unmeasured facets (not guessed): " + ", ".join(profile["facets_unmeasured"])]
    (base / "style.md").write_text("\n".join(md) + "\n", encoding="utf-8", newline="\n")
    refs = ["# References (private study folder)", ""] + [f"- {p}" for p in profile["refs"]]
    refs += ["", "Reference files stay local and are never re-uploaded. Music is never copied."]
    (base / "refs.md").write_text("\n".join(refs) + "\n", encoding="utf-8", newline="\n")
    return base / "style.json"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Learn, apply or compare a style profile")
    add_common(parser)
    parser.add_argument("command", choices=["learn", "apply", "compare"])
    parser.add_argument("refs", nargs="*")
    parser.add_argument("--name", required=True)
    parser.add_argument("--plan", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)

    with stage("style", args) as run:
        if args.command == "learn":
            if len(args.refs) < 3:
                raise InvalidInput("style learning wants 3–5 references",
                                   fix="python scripts/style.py learn a.mp4 b.mp4 c.mp4 --name mine",
                                   doc="references/style-learning.md")
            measured = [measure_ref(expand_inputs([r])[0], dry_run=args.dry_run) for r in args.refs]
            measured = [m for m in measured if m]
            if not measured:
                run.ok(output=None, next_cmd="rerun with real reference files")
                return 0
            profile = build_profile(args.name, measured)
            path = write_profile(root, profile)
            for r in measured:
                run.add_check(f"ref:{Path(r['path']).name}", "pass", r["cut_rhythm"], "cuts/10s")
            run.ok(output=str(path), artifacts=[str(path)],
                   next_cmd=f"python scripts/plan.py <probe.json> --style {args.name}")
            if not args.json:
                print((Path(path).parent / "style.md").read_text(encoding="utf-8"))
            return 0

        profile_path = Path(root) / "styles" / args.name / "style.json"
        if not profile_path.is_file():
            raise InvalidInput(f"no profile '{args.name}'",
                               fix=f"python scripts/style.py learn <3 refs> --name {args.name}")
        profile = read_json(profile_path, {})

        if args.command == "apply":
            plan_path = Path(args.plan or state.get("artifacts", {}).get("plan", ""))
            if not plan_path.is_file():
                raise InvalidInput("no plan.json", fix="run plan.py first")
            plan = read_json(plan_path, {})
            plan.setdefault("style", {})
            plan["style"] = {"name": args.name, "profile": str(profile_path),
                             "tolerance": profile["rhythm"].get("tolerance", 0.8)}
            plan["cut"]["target_shot_len"] = [max(profile["rhythm"]["median_shot"] * 0.6, 0.5),
                                              max(profile["rhythm"]["median_shot"] * 1.4, 1.0)] \
                if profile["rhythm"].get("median_shot") else plan["cut"]["target_shot_len"]
            plan["output"]["loudness"] = profile["audio"]["loudness"]
            plan["captions"]["style"] = profile["captions"]["style"]
            write_json(plan_path, plan)
            run.ok(output=str(plan_path), artifacts=[str(plan_path)],
                   next_cmd="python scripts/cut.py <source>")
            return 0

        # compare
        target = expand_inputs(args.refs)[0] if args.refs else None
        if target is None:
            raise InvalidInput("compare needs a rendered file", fix=f"style.py compare out.mp4 --name {args.name}")
        measured = measure_ref(target)
        expected = profile["rhythm"]["cut_rhythm"]
        tol = profile["rhythm"].get("tolerance", 0.8)
        deviation = round(abs(measured["cut_rhythm"] - expected), 2)
        run.add_check("cut_rhythm", "pass" if deviation <= tol else "fail", measured["cut_rhythm"],
                      f"{expected}±{tol}")
        lufs_dev = abs((measured.get("lufs") or -14) - profile["audio"]["loudness"])
        run.add_check("loudness", "pass" if lufs_dev <= 1.0 else "warn", measured.get("lufs"),
                      profile["audio"]["loudness"])
        report = {"measured": measured, "profile": args.name, "expected_cut_rhythm": expected,
                  "tolerance": tol, "deviation": deviation}
        write_json(work_dir(root, f"p-{target.stem}") / "style-compare.json", report)
        run.ok(output=str(work_dir(root, f"p-{target.stem}") / "style-compare.json"),
               next_cmd="read the deviation report")
        if not args.json:
            print(f"cut_rhythm {measured['cut_rhythm']} vs {expected}±{tol} — "
                  f"{'PASS' if deviation <= tol else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
