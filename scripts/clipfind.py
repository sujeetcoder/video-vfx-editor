#!/usr/bin/env python3
"""Candidate clip windows + a compact 5-signal table for the agent to rank.

Honest label: this measures clip strength (hook / pace / self-containedness),
NOT virality.

    python scripts/clipfind.py --json
    python scripts/clipfind.py --rules --top 5 --json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import InvalidInput, add_common, stage  # noqa: E402
from _paths import (ensure_edit, project_root, read_json, record_stage, work_dir,  # noqa: E402
                    write_json)

HOOK_WORDS = {
    "hi": ["सबसे", "सच", "गलती", "कभी", "क्यों", "कैसे", "राज", "सीक्रेट", "पागल", "असली",
           "कभी नहीं", "ज़रूरी", "सब", "नहीं पता", "सुनो", "देखो"],
    "en": ["secret", "never", "why", "how", "biggest", "mistake", "truth", "nobody", "everyone",
           "stop", "listen", "actually", "worst", "best", "free"],
}
SENT_END = (".", "!", "?", "।")


def _sentence_bounds(transcript: dict) -> list:
    segs = transcript.get("segments") or []
    if segs:
        return [(float(s["s"]), float(s["e"]), (s.get("text") or "").strip()) for s in segs]
    words = transcript.get("words") or []
    if not words:
        return []
    out, cur = [], []
    for w in words:
        cur.append(w)
        if str(w.get("w", "")).strip().endswith(SENT_END):
            out.append((float(cur[0]["s"]), float(cur[-1]["e"]), " ".join(x["w"] for x in cur)))
            cur = []
    if cur:
        out.append((float(cur[0]["s"]), float(cur[-1]["e"]), " ".join(x["w"] for x in cur)))
    return out


def build_windows(transcript: dict, duration: float, length_range=(15, 90), stride: float = 5.0) -> list:
    sents = _sentence_bounds(transcript)
    if not sents:
        # no transcript: even windows so the flow still works
        lo, hi = length_range
        span = min(hi, max(lo, duration / 4))
        wins = []
        t = 0.0
        while t + span <= max(duration, span) and len(wins) < 40:
            wins.append({"in": round(t, 3), "out": round(t + span, 3), "text": ""})
            t += max(span / 2, stride)
        return wins
    lo, hi = length_range
    wins = []
    for start_s, _e, _t in sents:
        for end_s, _e2, _t2 in sents:
            dur = end_s - start_s
            if lo <= dur <= hi:
                wins.append({"in": round(start_s, 3), "out": round(end_s, 3),
                             "text": " ".join(s[2] for s in sents
                                              if s[0] >= start_s and s[1] <= end_s)[:1200]})
                break
    # dedupe overlapping near-duplicates, 5 s stride
    dedup = []
    for w in sorted(wins, key=lambda x: x["in"]):
        if dedup and w["in"] - dedup[-1]["in"] < stride:
            continue
        dedup.append(w)
    return dedup


def score_window(win: dict, transcript: dict, duration: float, avg_wps: float) -> dict:
    words = [w for w in (transcript.get("words") or [])
             if float(w.get("s", 0)) >= win["in"] and float(w.get("e", 0)) <= win["out"]]
    span = max(win["out"] - win["in"], 0.1)
    text = " ".join(str(w.get("w", "")) for w in words).lower()
    wps = len(words) / span
    speech = min(1.0, wps / max(avg_wps, 1.5)) if words else 0.55
    pace = min(1.0, (len(words) / span) / 3.6) if words else 0.4
    lower = text
    hooks = sum(1 for group in HOOK_WORDS.values() for h in group if h in lower)
    hook = min(1.0, 0.35 + hooks * 0.15)
    first_line = text[:120]
    self_contained = 0.9 if first_line and not first_line.startswith(("and ", "but ", "so ", "तो ", "और ")) else 0.55
    opening = win["in"] < duration * 0.25
    external = 0.8 if opening else (0.6 if span <= 45 else 0.5)
    signals = {"speech": round(speech, 2), "pace": round(pace, 2), "hook": round(hook, 2),
               "self_contained": round(self_contained, 2), "external": round(external, 2)}
    weight = {"speech": 0.28, "pace": 0.18, "hook": 0.24, "self_contained": 0.20, "external": 0.10}
    total = sum(signals[k] * weight[k] for k in signals)
    return {"score": round(total, 3), "signals": signals,
            "hook_line": _hook_line(words, HOOK_WORDS), "words": len(words)}


def _hook_line(words, hook_words) -> str:
    if not words:
        return ""
    for i, w in enumerate(words[:40]):
        token = str(w.get("w", "")).lower()
        if any(h in token for h in sum(hook_words.values(), [])):
            return " ".join(str(x.get("w", "")) for x in words[i:i + 8])
    return " ".join(str(x.get("w", "")) for x in words[:8])


def find_candidates(probe: dict, transcript: dict | None, plan: dict) -> dict:
    duration = float(probe.get("duration") or (transcript or {}).get("duration") or 0)
    length_range = tuple(plan.get("clip", {}).get("len", [15, 90]))
    windows = build_windows(transcript or {}, duration, length_range)
    words = (transcript or {}).get("words") or []
    avg_wps = (len(words) / duration) if words and duration else 3.0
    cands = []
    for i, win in enumerate(windows):
        if win["out"] - win["in"] < length_range[0]:
            continue
        scored = score_window(win, transcript or {}, duration, avg_wps)
        cands.append({"id": len(cands) + 1, **win, **scored,
                      "reason": _reason(scored),
                      "starts_clean": bool((win.get("text") or "").strip())})
    cands.sort(key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(cands, 1):
        c["id"] = i
    keep = int(plan.get("clip", {}).get("count", 5))
    return {"duration": duration, "count": len(cands), "candidates": cands[: max(keep * 4, 12)],
            "note": "clip strength, not a virality prediction"}


def _reason(scored: dict) -> str:
    s = scored["signals"]
    best = max(s, key=s.get)
    label = {"speech": "dense speech", "pace": "fast pace", "hook": "strong hook line",
             "self_contained": "stands alone", "external": "strong opening position"}[best]
    return f"{label}; hook line: {scored.get('hook_line', '')[:60]}"


def candidate_table(payload: dict) -> str:
    rows = ["| id | in–out | s | score | speech | pace | hook | self | ext | hook line |",
            "|----|--------|---|-------|--------|------|------|------|-----|-----------|"]
    for c in payload.get("candidates", [])[:30]:
        rows.append(f"| {c['id']} | {c['in']:.1f}–{c['out']:.1f} | {c['out'] - c['in']:.0f} | "
                    f"{c['score']:.2f} | {c['signals']['speech']:.2f} | {c['signals']['pace']:.2f} | "
                    f"{c['signals']['hook']:.2f} | {c['signals']['self_contained']:.2f} | "
                    f"{c['signals']['external']:.2f} | {c.get('hook_line', '')[:48]} |")
    return "\n".join(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Find clip candidates with a 5-signal score")
    add_common(parser)
    parser.add_argument("--transcript", default=None)
    parser.add_argument("--probe", default=None)
    parser.add_argument("--rules", action="store_true", help="return the rule top-N, no agent ranking")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    art = state.get("artifacts", {})

    with stage("clipfind", args) as run:
        transcript_path = args.transcript or art.get("asr") or (work_dir(root) / "words.json")
        transcript = read_json(transcript_path, {}) if Path(transcript_path).is_file() else {}
        if not transcript:
            raise InvalidInput(
                "no transcript for clip finding",
                fix="python scripts/asr.py <source> --lang hi --json",
                doc="references/clipping.md",
            )
        probe = read_json(args.probe, {}) if args.probe else read_json(art.get("probe"), {}) or {}
        plan = read_json(art.get("plan"), {}) or {}
        payload = find_candidates(probe, transcript, plan)
        work = work_dir(root, f"p-{Path(transcript.get('path', 'clip')).stem}")
        out_path = work / "candidates.json"
        if args.rules:
            payload["candidates"] = payload["candidates"][: args.top]
        if not args.dry_run:
            write_json(out_path, payload)
            state = ensure_edit(root)
            record_stage(root, state, "clipfind", out_path, candidates=payload["count"])
        run.add_check("candidates", "pass" if payload["candidates"] else "fail",
                      len(payload["candidates"]), ">= 3")
        run.ok(output=str(out_path), artifacts=[str(out_path)],
               next_cmd="python scripts/forge.py approve 1 2 3")
        if not args.json:
            print(candidate_table(payload))
            print("\nclip strength, not a virality prediction")
    return 0


if __name__ == "__main__":
    sys.exit(main())
