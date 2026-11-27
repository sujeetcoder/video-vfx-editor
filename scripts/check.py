#!/usr/bin/env python3
"""Quality gates: PASS / WARN / FAIL with one fix suggestion per failure.

    python scripts/check.py out.mp4 --json
    python scripts/check.py edit/out/run-*/ --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, ffprobe_json, project_root,  # noqa: E402
                    read_json, record_stage, run_cmd, work_dir)

DEFAULT_GATES = {
    "loudness_tolerance": 1.0,
    "true_peak_max": -1.0,
    "blackdetect_min": 0.15,
    "freezedetect_min": 2.0,
    "caption_max_chars": 32,
    "hook_within": 1.5,
    "crop_keep_min": 0.55,
}


def parse_blackdetect(text: str) -> list:
    out, start = [], None
    for line in text.splitlines():
        m = re.search(r"black_start:\s*([\d.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"black_end:\s*([\d.]+)\s*\|\s*black_duration:\s*([\d.]+)", line)
        if m and start is not None:
            out.append({"start": start, "end": float(m.group(1)), "duration": float(m.group(2))})
            start = None
    return out


def parse_freezedetect(text: str) -> list:
    out, start = [], None
    for line in text.splitlines():
        m = re.search(r"freeze_start:\s*([\d.]+)", line)
        if m:
            start = float(m.group(1))
        m = re.search(r"freeze_duration:\s*([\d.]+)", line)
        if m and start is not None:
            out.append({"start": start, "duration": float(m.group(1))})
            start = None
    return out


def evaluate(info: dict, loud: dict, black: list, freeze: list, caption_report: dict,
             plan: dict, sidecar: dict) -> list:
    gates = dict(DEFAULT_GATES)
    gates.update((plan.get("gates") or {}))
    checks = []

    def add(cid, ok, value, target, fix=None, warn_only=False):
        checks.append({"id": cid, "status": "pass" if ok else ("warn" if warn_only else "fail"),
                       "value": value, "target": target, "fix": None if ok else fix})

    add("duration", info.get("duration", 0) > 0, info.get("duration"), "> 0 s",
        "the render produced an empty file — read the FFmpeg log")
    out_cfg = plan.get("output") or {}
    if out_cfg.get("width"):
        add("resolution", info.get("width") == out_cfg["width"] and info.get("height") == out_cfg["height"],
            f"{info.get('width')}x{info.get('height')}", f"{out_cfg['width']}x{out_cfg['height']}",
            "re-run export.py with the planned --preset")
    if out_cfg.get("fps"):
        add("fps", abs(float(info.get("fps") or 0) - float(out_cfg["fps"])) < 0.05,
            info.get("fps"), out_cfg["fps"], "re-encode with the planned fps (export.py does this)")
    add("audio_present", bool(info.get("audio")), len(info.get("audio") or []), ">= 1 stream",
        "the source may be silent — run audio.py with a music bed or check the input")
    target = float(out_cfg.get("loudness", -14.0))
    tol = float(gates["loudness_tolerance"])
    if loud.get("integrated_lufs") is not None:
        add("loudness", abs(loud["integrated_lufs"] - target) <= tol, loud["integrated_lufs"],
            f"{target}±{tol} LUFS", f"re-run audio.py with --loudness {target}")
    if loud.get("true_peak_db") is not None:
        tp_max = float(gates["true_peak_max"])
        add("true_peak", loud["true_peak_db"] <= tp_max + 0.01, loud["true_peak_db"],
            f"<= {tp_max} dBTP", "re-run audio.py; it aims 0.8 dB under the plan ceiling for AAC")
    long_black = [b for b in black if b["duration"] > max(float(gates["blackdetect_min"]), 0.5)]
    add("black_frames", not long_black, len(long_black), "0 black runs > 0.5 s",
        "a cut landed on black; adjust the cut padding", warn_only=True)
    long_freeze = [f for f in freeze if f["duration"] > float(gates["freezedetect_min"])]
    add("freeze_frames", not long_freeze, len(long_freeze), "0 freezes",
        "a still frame was held too long; trim the shot", warn_only=True)
    if caption_report:
        add("captions", caption_report.get("max_chars", 0) <= gates["caption_max_chars"],
            caption_report.get("max_chars"), f"<= {gates['caption_max_chars']} chars",
            "reduce --max-chars in caption.py")
        add("caption_tail", caption_report.get("last_end", 0) <= info.get("duration", 0) + 0.05,
            caption_report.get("last_end"), "inside the video",
            "the last caption outlives the video; re-run caption.py on the cut")
    if sidecar.get("clip"):
        clip = sidecar["clip"]
        add("clip_hook", float(clip.get("hook_offset", 99)) <= float(gates["hook_within"]),
            clip.get("hook_offset"), f"<= {gates['hook_within']} s",
            "pick a window that opens on the hook line")
        add("clip_sentence_start", bool(clip.get("starts_clean", True)), clip.get("starts_clean"),
            "starts at a sentence", "snap the window to the previous sentence boundary")
        add("clip_crop", float(clip.get("crop_keep", 1.0)) >= float(gates["crop_keep_min"]),
            clip.get("crop_keep"), f">= {gates['crop_keep_min']} of the subject",
            "switch reframe --layout contain for this clip")
    style_name = (plan.get("style") or {}).get("name")
    style_path = (plan.get("style") or {}).get("profile")
    if style_name and style_path and Path(style_path).is_file() and sidecar.get("measured"):
        style = read_json(style_path, {}) or {}
        rhythm = (style.get("rhythm") or {})
        expected = rhythm.get("cut_rhythm")
        actual = sidecar["measured"].get("cut_rhythm")
        if expected and actual:
            dev = abs(float(actual) - float(expected))
            add("style_rhythm", dev <= float(rhythm.get("tolerance", 0.8)), actual,
                f"{expected}±{rhythm.get('tolerance', 0.8)} cuts/10s",
                f"style '{style_name}' expects a different cut rhythm")
    return checks


def caption_report(path: Path) -> dict:
    srt = path.with_suffix(".srt")
    if not srt.is_file():
        return {}
    text = srt.read_text(encoding="utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln and "-->" not in ln and not ln.strip().isdigit()]
    last_end = 0.0
    for ln in text.splitlines():
        if "-->" in ln:
            end = ln.split("-->")[1].strip().split()[0].replace(",", ".")
            try:
                h, m, s = end.split(":")
                last_end = max(last_end, int(h) * 3600 + int(m) * 60 + float(s))
            except ValueError:
                pass
    return {"max_chars": max((len(ln) for ln in lines), default=0), "lines": len(lines),
            "last_end": round(last_end, 3)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run quality gates on rendered files")
    add_common(parser)
    parser.add_argument("inputs", nargs="+")
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)

    with stage("check", args) as run:
        paths = expand_inputs(args.inputs)
        plan_path = state.get("artifacts", {}).get("plan")
        plan = read_json(plan_path, {}) if plan_path and Path(plan_path).is_file() else {}
        reports = []
        for p in paths:
            info = ffprobe_json(p, dry_run=args.dry_run)
            if args.dry_run:
                continue
            duration = float((info.get("format") or {}).get("duration") or 0)
            streams = info.get("streams") or []
            video = next((s for s in streams if s.get("codec_type") == "video"), {})
            rc, loud_out = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(p),
                                    "-af", "ebur128=peak=true", "-f", "null", "-"], timeout=3600)
            summary = loud_out.rsplit("Summary:", 1)[-1]
            integrated = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
            peak = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
            rc, black_out = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(p),
                                     "-vf", "blackdetect=d=0.1:pix_th=0.10", "-an", "-f", "null", "-"],
                                    timeout=3600)
            rc, freeze_out = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(p),
                                      "-vf", "freezedetect=n=-60dB:d=1.0", "-an", "-f", "null", "-"],
                                     timeout=3600)
            sidecar_path = p.with_suffix(".json")
            sidecar = read_json(sidecar_path, {}) if sidecar_path.is_file() else {}
            result = {
                "path": str(p),
                "duration": round(duration, 3),
                "width": int(video.get("width") or 0),
                "height": int(video.get("height") or 0),
                "fps": round(_fps(video.get("avg_frame_rate")), 3),
                "audio": [s for s in streams if s.get("codec_type") == "audio"],
                "loudness": {"integrated_lufs": float(integrated.group(1)) if integrated else None,
                             "true_peak_db": float(peak.group(1)) if peak else None},
                "black": parse_blackdetect(black_out),
                "freeze": parse_freezedetect(freeze_out),
                "caption_report": caption_report(p),
                "sidecar": sidecar,
            }
            checks = evaluate(result, result["loudness"], result["black"], result["freeze"],
                              result["caption_report"], plan, sidecar)
            for c in checks:
                run.add_check(f"{p.stem}:{c['id']}", c["status"], c["value"], c["target"])
                if c.get("fix"):
                    log(f"fix {c['id']}: {c['fix']}")
            result["checks"] = checks
            reports.append(result)
            if not args.dry_run:
                report_path = work_dir(root, f"p-{p.stem}") / "check.json"
                report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
        if not args.dry_run:
            state = ensure_edit(root)
            record_stage(root, state, "check", reports[0]["path"] if reports else None,
                         status="done" if run.status == "ok" else run.status)
        fails = [c for c in run.checks if c["status"] == "fail"]
        run.ok(output=reports[0]["path"] if reports else None,
               artifacts=[r["path"] for r in reports],
               next_cmd=None if not fails else "read the fix lines and re-run the failing stage")
        if not args.json:
            for r in reports:
                print(f"{Path(r['path']).name}: {sum(1 for c in r['checks'] if c['status'] == 'pass')} pass / "
                      f"{sum(1 for c in r['checks'] if c['status'] == 'warn')} warn / "
                      f"{sum(1 for c in r['checks'] if c['status'] == 'fail')} fail")
    return 0


def _fps(value) -> float:
    try:
        if "/" in str(value):
            a, b = str(value).split("/", 1)
            return float(a) / float(b) if float(b) else 0.0
        return float(value or 0)
    except (ValueError, ZeroDivisionError):
        return 0.0


if __name__ == "__main__":
    sys.exit(main())
