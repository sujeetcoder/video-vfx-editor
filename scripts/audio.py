#!/usr/bin/env python3
"""Denoise, dehum, deess, duck music, 2-pass loudnorm (-14 / -16 LUFS, TP <= -1 dBTP).

    python scripts/audio.py cut.mp4 --json
    python scripts/audio.py cut.mp4 --music bed.wav --json
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan  # noqa: E402
from _contract import add_common, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, project_root, read_json,  # noqa: E402
                    record_stage, run_cmd, work_dir)

DEHUM_FREQS = (50, 60, 100, 120)


def loudnorm_filter(loudness: float, true_peak: float, measured: dict | None = None) -> str:
    ln = f"loudnorm=I={loudness}:TP={true_peak}:LRA=11"
    if measured:
        ln += (f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
               f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
               f":offset={measured.get('target_offset', 0)}:linear=true")
    return ln


def mix_graph(voice_chain: str, music_db: float, tail: str) -> str:
    """Duck the bed under the voice, mix without amix's level halving, then normalise the MIX.

    `normalize=0` keeps the voice at its own target; the loudnorm in `tail` is what
    holds the result at the target once the bed is added (amix default + dynaudnorm
    used to drag a -14 delivery to -19).
    """
    return (f"[0:a]{voice_chain}[voice];"
            f"[1:a]volume={music_db}dB,aloop=loop=-1:size=2e9[bed];"
            f"[bed][voice]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400:makeup=1[duck];"
            f"[voice][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            f"alimiter=limit=0.9{tail}[a]")


def build_chain(denoise: bool = True, dehum: bool = True, deess: bool = True,
                highpass: int = 80, normalize: bool = True, loudness: float = -14.0,
                true_peak: float = -1.0, measured: dict | None = None) -> str:
    """Deterministic voice chain. Order: denoise -> highpass -> dehum -> deess -> loudnorm."""
    parts = []
    if denoise:
        parts.append("afftdn=nr=12:nf=-30:tn=1")
    if highpass:
        parts.append(f"highpass=f={int(highpass)}")
    if dehum:
        for f in (50, 60):
            parts.append(f"equalizer=f={f}:width_type=q:width=2:g=-14")
    if deess:
        parts.append("deesser=i=0.4")
    if normalize:
        parts.append(loudnorm_filter(loudness, true_peak, measured))
    return ",".join(parts)


def parse_loudnorm(out: str) -> dict:
    block = out.rsplit("{", 1)[-1]
    data = {}
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        m = re.search(rf'"{key}"\s*:\s*"?(-?[\d.]+)"?', block)
        if m:
            data[key] = float(m.group(1))
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Clean and normalise audio")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--loudness", type=float, default=None, help="-14 reel, -16 podcast")
    parser.add_argument("--music", default=None, help="music bed file to duck under the voice")
    parser.add_argument("--music-db", type=float, default=-18.0)
    parser.add_argument("--duck-db", type=float, default=1.5)
    parser.add_argument("--no-denoise", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    dev = device_plan(args.device, caps)

    with stage("audio", args) as run:
        run.device = dev["resolved"]
        path = expand_inputs([args.input])[0]
        plan_path = state.get("artifacts", {}).get("plan")
        plan = read_json(plan_path, {}) if plan_path and Path(plan_path).is_file() else {}
        target = args.loudness if args.loudness is not None else float(
            (plan.get("output") or {}).get("loudness", -14.0))
        work = work_dir(root, f"p-{path.stem}")
        # PCM intermediate: export is the only lossy audio encode, so loudnorm's
        # TP target only needs headroom for AAC's own overshoot.
        out_path = Path(args.out) if args.out else work / "audio.mov"
        tp = float((plan.get("output") or {}).get("true_peak", -1.0)) - 0.8
        chain = build_chain(denoise=not args.no_denoise, dehum=True, deess=True,
                            highpass=int((plan.get("audio") or {}).get("highpass", 80)),
                            loudness=target, true_peak=tp)

        # pass 1: measure through the same chain
        rc, measured_out = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(path),
                                    "-map", "0:a:0", "-af", chain + ":print_format=json",
                                    "-f", "null", "-"], dry_run=args.dry_run, timeout=3600)
        measured = {} if args.dry_run else parse_loudnorm(measured_out)
        chain2 = build_chain(denoise=not args.no_denoise, dehum=True, deess=True,
                             highpass=int((plan.get("audio") or {}).get("highpass", 80)),
                             loudness=target, true_peak=tp, measured=measured)

        music = args.music or (plan.get("audio") or {}).get("music")
        if music:
            bed = expand_inputs([music])[0]
            # pass 2: measure the mix itself, so the bed cannot drag the delivery off target
            rc, mix_out = run_cmd(
                [ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(path), "-stream_loop", "-1",
                 "-i", str(bed), "-filter_complex",
                 mix_graph(chain2, args.music_db, f",{loudnorm_filter(target, tp)}:print_format=json"),
                 "-map", "[a]", "-f", "null", "-"], dry_run=args.dry_run, timeout=3600)
            mix_measured = {} if args.dry_run else parse_loudnorm(mix_out)
            graph = mix_graph(chain2, args.music_db,
                              f",{loudnorm_filter(target, tp, mix_measured)}" if mix_measured else "")
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path), "-stream_loop", "-1",
                   "-i", str(bed), "-filter_complex", graph, "-map", "0:v?", "-map", "[a]",
                   "-c:v", "copy", "-c:a", "pcm_s24le", "-ar", "48000",
                   "-shortest", str(out_path)]
        else:
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
                   "-map", "0:v?", "-map", "0:a:0", "-af", chain2,
                   "-c:v", "copy", "-c:a", "pcm_s24le", "-ar", "48000",
                   str(out_path)]
        run_cmd(cmd, dry_run=args.dry_run, timeout=7200)

        if not args.dry_run:
            state = ensure_edit(root)
            record_stage(root, state, "audio", out_path, target_lufs=target)
        run.add_check("loudness_target", "pass", target, f"{target}±1 LUFS")
        run.ok(output=str(out_path), artifacts=[str(out_path)],
               next_cmd=f'python scripts/export.py "{out_path}" --json')
        if not args.json:
            print(f"audio chain applied (target {target} LUFS) -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
