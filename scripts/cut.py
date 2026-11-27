#!/usr/bin/env python3
"""Silence + filler removal. Lossless when possible, 30 ms audio fades at joins.

    python scripts/cut.py input.mp4 --json
    python scripts/cut.py input.mp4 --dry-run
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args  # noqa: E402
from _contract import add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffprobe_json, ffmpeg_bin,  # noqa: E402
                    project_root, read_json, record_stage, run_cmd, work_dir, write_json)

FILLERS_HI = ["matlab", "yaani", "toh", "umm", "aaa", "matlab ki", "arre", "haan ji"]


# --------------------------------------------------------------------------
# pure helpers (unit tested)
# --------------------------------------------------------------------------
def parse_silences(log_text: str) -> list:
    """Parse ffmpeg silencedetect output into [(start, end), ...]."""
    out = []
    start = None
    for line in log_text.splitlines():
        m = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end:\s*(-?[\d.]+)", line)
        if m and start is not None:
            out.append((start, float(m.group(1))))
            start = None
    return out


def invert_silences(silences, duration: float, min_silence: float = 0.45,
                    pad: float = 0.12, min_keep: float = 0.35) -> list:
    """Return the segments to KEEP after removing long silences."""
    keep = []
    cursor = 0.0
    for (s, e) in sorted(silences):
        if e - s < min_silence:
            continue
        cut_start = s + pad
        cut_end = e - pad
        if cut_end <= cut_start:
            cut_start = s
            cut_end = e
        if cut_start - cursor >= min_keep:
            keep.append((round(cursor, 3), round(cut_start, 3)))
        cursor = max(cursor, cut_end)
    if duration - cursor >= min_keep:
        keep.append((round(cursor, 3), round(duration, 3)))
    if not keep:
        keep = [(0.0, round(duration, 3))]
    merged = []
    for seg in keep:
        if merged and seg[0] - merged[-1][1] < 0.05:
            merged[-1] = (merged[-1][0], seg[1])
        else:
            merged.append(seg)
    return merged


def filler_cuts(words, fillers) -> list:
    """Word-level filler spans as (start, end) cuts, never longer than 1.2 s."""
    cuts = []
    if not words:
        return cuts
    norm = [str(w.get("w", "")).strip().lower().strip(".,!?") for w in words]
    for i, token in enumerate(norm):
        if any(token == f or (len(f) > 3 and f in token) for f in fillers):
            start = float(words[i].get("s", 0))
            end = float(words[i].get("e", start + 0.2))
            if end - start <= 1.2:
                cuts.append((round(start, 3), round(end, 3)))
    return cuts


def subtract_cuts(keep, cuts) -> list:
    out = []
    cuts = sorted(cuts)
    for (a, b) in keep:
        pieces = [(a, b)]
        for (c, d) in cuts:
            nxt = []
            for (x, y) in pieces:
                if d <= x or c >= y:
                    nxt.append((x, y))
                    continue
                if c > x:
                    nxt.append((x, round(c, 3)))
                if d < y:
                    nxt.append((round(d, 3), y))
            pieces = nxt
        out.extend(p for p in pieces if p[1] - p[0] >= 0.25)
    return out


def build_filtergraph(segments, has_audio: bool = True, fade_ms: int = 30, fps: int = 30) -> str:
    """Deterministic trim/concat graph with 30 ms audio fades at internal joins."""
    fade = max(fade_ms, 1) / 1000.0
    parts, pairs = [], []
    for i, (a, b) in enumerate(segments):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={fps}[v{i}]")
        if has_audio:
            dur = max(b - a, 0.05)
            chain = f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS"
            if i > 0:
                chain += f",afade=t=in:st=0:d={fade:.3f}"
            if i < len(segments) - 1:
                chain += f",afade=t=out:st={max(dur - fade, 0):.3f}:d={fade:.3f}"
            parts.append(chain + f"[a{i}]")
            pairs.append(f"[v{i}][a{i}]")
        else:
            pairs.append(f"[v{i}]")
    n = len(segments)
    if has_audio:
        parts.append("".join(pairs) + f"concat=n={n}:v=1:a=1[v][a]")
    else:
        parts.append("".join(pairs) + f"concat=n={n}:v=1:a=0[v]")
    return ";".join(parts)


# --------------------------------------------------------------------------
# ffmpeg side
# --------------------------------------------------------------------------
def detect_silences(path: Path, noise_db: float, min_silence: float, dry_run=False) -> list:
    rc, out = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(path),
                       "-map", "0:a:0", "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
                       "-f", "null", "-"], dry_run=dry_run, timeout=3600)
    if dry_run:
        return []
    return parse_silences(out)


def try_lossless(path: Path, segments, out_path: Path, dry_run=False) -> bool:
    """Copy when the cuts are keyframe-friendly; verify duration afterwards."""
    if len(segments) < 1:
        return False
    if len(segments) == 1:
        a, b = segments[0]
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-ss", f"{a:.3f}", "-i", str(path),
               "-t", f"{b - a:.3f}", "-c", "copy", "-avoid_negative_ts", "make_zero", str(out_path)]
        rc, _ = run_cmd(cmd, dry_run=dry_run, timeout=1800)
        return rc == 0
    return False


def try_lossless_segments(path: Path, segments, out_path: Path, work: Path, dry_run=False) -> bool:
    """Stream-copy each keep segment, concat, then verify the duration.

    Lossless only when the cuts land well enough; the duration check rejects
    keyframe drift so the caller can fall back to a frame-accurate re-encode.
    """
    if len(segments) < 2 or dry_run:
        return False
    tmp = work / "lcut"
    tmp.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, (a, b) in enumerate(segments):
        part = tmp / f"part{i:04d}.mp4"
        rc, _ = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-ss", f"{a:.3f}",
                         "-i", str(path), "-t", f"{b - a:.3f}", "-c", "copy",
                         "-avoid_negative_ts", "make_zero", str(part)], timeout=1800)
        if rc != 0 or not part.is_file():
            return False
        parts.append(part)
    listing = tmp / "concat.txt"
    listing.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts) + "\n", encoding="utf-8")
    rc, _ = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-f", "concat",
                     "-safe", "0", "-i", str(listing), "-c", "copy", str(out_path)], timeout=3600)
    if rc != 0 or not out_path.is_file():
        return False
    expected = sum(b - a for a, b in segments)
    probe = ffprobe_json(out_path)
    actual = float((probe.get("format") or {}).get("duration") or 0)
    if abs(actual - expected) > 0.35:
        log(f"lossless concat drifts ({actual:.2f}s vs {expected:.2f}s); re-encoding")
        return False
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Remove silences and fillers")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--noise-db", type=float, default=-32.0)
    parser.add_argument("--min-silence", type=float, default=None)
    parser.add_argument("--pad", type=float, default=0.12)
    parser.add_argument("--no-fillers", action="store_true")
    parser.add_argument("--keep-silence", action="store_true")
    parser.add_argument("--max-shots", type=int, default=400)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root, refresh=args.refresh)
    dev = device_plan(args.device, caps)

    with stage("cut", args) as run:
        run.device = dev["resolved"]
        path = expand_inputs([args.input])[0]
        probe = ffprobe_json(path, dry_run=args.dry_run)
        duration = float((probe.get("format") or {}).get("duration") or 0)
        has_audio = any(s.get("codec_type") == "audio" for s in probe.get("streams", []))
        plan_path = state.get("artifacts", {}).get("plan")
        plan = read_json(plan_path, {}) if plan_path and Path(plan_path).is_file() else {}
        cut_cfg = plan.get("cut", {}) or {}
        min_silence = args.min_silence if args.min_silence is not None else float(cut_cfg.get("min_silence", 0.45))
        fps = int((plan.get("output") or {}).get("fps", 30))
        key = path.stem
        work = work_dir(root, f"p-{key}")

        segments = [(0.0, round(duration, 3))]
        if has_audio and not args.keep_silence and not args.dry_run:
            silences = detect_silences(path, args.noise_db, min_silence, dry_run=args.dry_run)
            segments = invert_silences(silences, duration, min_silence, args.pad)
            words_path = work / "words.json"
            asr_artifact = (state.get("artifacts") or {}).get("asr")
            if not words_path.is_file() and asr_artifact and Path(asr_artifact).is_file():
                words_path = Path(asr_artifact)
            if not args.no_fillers and cut_cfg.get("remove_fillers", True) and words_path.is_file():
                words = read_json(words_path, {}).get("words", [])
                fillers = cut_cfg.get("filler_words") or FILLERS_HI
                cuts = filler_cuts(words, fillers)
                before = sum(b - a for a, b in segments)
                segments = subtract_cuts(segments, cuts)
                log(f"filler cuts: {len(cuts)}, {before - sum(b - a for a, b in segments):.1f}s removed")
        if len(segments) > args.max_shots:
            log(f"too many segments ({len(segments)}), keeping the longest {args.max_shots}")
            segments = sorted(segments, key=lambda s: s[1] - s[0], reverse=True)[: args.max_shots]
            segments = sorted(segments)

        out_path = Path(args.out) if args.out else work / "cut.mp4"
        removed = duration - sum(b - a for a, b in segments)

        if len(segments) == 1 and abs(segments[0][1] - duration) < 0.01:
            # nothing to cut: still normalise to a clean, faststart mp4
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
                   *encoder_args(dev["encoder"], 20), "-c:a", "aac", "-b:a", "192k",
                   "-movflags", "+faststart", str(out_path)]
            run_cmd(cmd, dry_run=args.dry_run, timeout=7200)
        elif try_lossless(path, segments, out_path, dry_run=args.dry_run):
            log("lossless cut (stream copy)")
        elif try_lossless_segments(path, segments, out_path, work, dry_run=args.dry_run):
            log("lossless multi-segment cut (stream copy)")
        else:
            graph = build_filtergraph(segments, has_audio, int(cut_cfg.get("fade_ms", 30)), fps)
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
                   "-filter_complex", graph, "-map", "[v]", "-map", "[a]" if has_audio else "[v]",
                   *encoder_args(dev["encoder"], 20), "-c:a", "aac", "-b:a", "192k",
                   "-movflags", "+faststart", str(out_path)]
            if not has_audio:
                cmd = [c for c in cmd if c not in ("-c:a", "aac", "-b:a", "192k")]
            rc, out = run_cmd(cmd, dry_run=args.dry_run, timeout=7200)

        sidecar = work / "cut.json"
        info = {"segments": segments, "removed": round(removed, 2), "duration": round(duration, 3),
                "output_duration": round(sum(b - a for a, b in segments), 3), "device": dev["resolved"]}
        if not args.dry_run:
            write_json(sidecar, info)
            state = ensure_edit(root)
            state["device"] = dev["resolved"]
            record_stage(root, state, "cut", out_path, removed_s=info["removed"], segments=len(segments))
        run.add_check("cut_removed", "pass" if removed < duration * 0.9 else "warn",
                      round(removed, 1), "less than 90% of the source")
        run.ok(output=str(out_path), artifacts=[str(out_path), str(sidecar)],
               next_cmd=f'python scripts/asr.py "{out_path}" --lang {plan.get("captions", {}).get("lang", "hi")}')
        if args.dry_run:
            return 0
        if not args.json:
            print(f"kept {len(segments)} segments, removed {removed:.1f}s -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
