#!/usr/bin/env python3
"""Sound design: suggest / make / place / mix, via the earshot bridge.

    python scripts/sfx.py suggest --at 2.4 --type whoosh --json
    python scripts/sfx.py make "soft whoosh" --json
    python scripts/sfx.py place video.mp4 --at 2.4,8.1 --type whoosh --json
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args  # noqa: E402
from _contract import InvalidInput, MissingCapability, add_common, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, project_root, read_json,  # noqa: E402
                    run_cmd, work_dir, write_json)

TYPES = ("whoosh", "tick", "impact", "riser")


def earshot_available() -> bool:
    return importlib.util.find_spec("earshot") is not None or shutil.which("earshot") is not None


def synth(path: Path, kind: str, duration: float = 1.0, sr: int = 48000) -> Path:
    """Deterministic FFmpeg synthesis. Used only behind --synth (earshot is the real bridge)."""
    src = {
        "whoosh": f"anoisesrc=color=pink:duration={duration}:amplitude=0.5,"
                  f"highpass=f=300,lowpass=f=6000,afade=t=in:st=0:d={duration * 0.3:.2f},"
                  f"afade=t=out:st={duration * 0.6:.2f}:d={duration * 0.4:.2f}",
        "tick": "sine=f=1800:duration=0.05,afade=t=out:st=0:d=0.05",
        "impact": f"sine=f=70:duration={min(duration, 0.8)}:afade=t=out:st=0:d={min(duration, 0.8)}",
        "riser": f"sine=f=200:duration={duration},asetrate=48000,atempo=1.0,"
                 f"afade=t=in:st=0:d=0.2,volume=0.6",
    }[kind]
    path.parent.mkdir(parents=True, exist_ok=True)
    run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-f", "lavfi", "-i", src,
             "-ar", str(sr), "-ac", "1", "-c:a", "pcm_s16le", str(path)], timeout=120, check=True)
    return path


def suggest(at: float, kind: str) -> dict:
    return {"at": round(at, 3), "type": kind, "gain_db": -18.0, "fade_ms": 20,
            "reason": {"whoosh": "covers a cut", "tick": "accent on a word",
                       "impact": "lands a hard cut", "riser": "builds into the hook"}[kind]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Suggest, make and place SFX")
    add_common(parser)
    parser.add_argument("command", choices=["suggest", "make", "place"])
    parser.add_argument("target", nargs="?", default=None, help="words for make / video for place")
    parser.add_argument("--at", default=None, help="seconds, comma-separated")
    parser.add_argument("--type", default="whoosh", choices=TYPES)
    parser.add_argument("--gain", type=float, default=-18.0)
    parser.add_argument("--synth", action="store_true", help="explicit FFmpeg synth fallback (no earshot)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    dev = device_plan(args.device, caps)

    with stage("sfx", args) as run:
        run.device = "cpu"  # earshot is CPU by design
        work = work_dir(root, "sfx")
        if args.command == "suggest":
            times = [float(x) for x in (args.at or "0").split(",") if x.strip()]
            items = [suggest(t, args.type) for t in times]
            out_path = work / "suggestions.json"
            if not args.dry_run:
                write_json(out_path, {"sfx": items})
            run.ok(output=str(out_path), artifacts=[str(out_path)],
                   next_cmd="python scripts/sfx.py place <video> --at ... --type whoosh")
            if not args.json:
                for it in items:
                    print(f"{it['at']}s {it['type']} {it['gain_db']}dB — {it['reason']}")
            return 0

        if not earshot_available() and not args.synth:
            raise MissingCapability(
                "earshot is not installed",
                fix="python -m pip install --user earshot  (or pass --synth for a plain FFmpeg fallback)",
                doc="references/sound-design.md",
            )
        if not earshot_available() and args.synth:
            run.warn("using the FFmpeg synth fallback, not earshot")

        if args.command == "make":
            words = args.target or "whoosh"
            out = Path(args.out) if args.out else work / f"{words.replace(' ', '-')}.wav"
            if earshot_available():
                rc, txt = run_cmd([sys.executable, "-m", "earshot", "make", words, "-o", str(out)],
                                  dry_run=args.dry_run, timeout=600)
                if rc != 0:
                    raise InvalidInput(f"earshot failed: {txt[-400:]}", fix="pass --synth")
            else:
                synth(out, args.type if args.type else "whoosh")
            run.ok(output=str(out), artifacts=[str(out)], next_cmd="python scripts/sfx.py place <video> --at 2.4")
            return 0

        # place
        if not args.target:
            raise InvalidInput("place needs a video", fix="python scripts/sfx.py place video.mp4 --at 2.4")
        path = expand_inputs([args.target])[0]
        times = [float(x) for x in (args.at or "1.0").split(",") if x.strip()]
        clip = work / f"{args.type}.wav"
        if not clip.is_file():
            if earshot_available():
                run_cmd([sys.executable, "-m", "earshot", "make", args.type, "-o", str(clip)],
                        dry_run=args.dry_run, timeout=600)
            else:
                synth(clip, args.type)
        plan = read_json(state.get("artifacts", {}).get("plan"), {}) or {}
        sfx_per_min = ((plan.get("style") or {}).get("sfx_per_min")
                       or (plan.get("audio") or {}).get("sfx_per_min") or 4.0)
        if len(times) / max(float(plan.get("output", {}).get("target_duration") or 60) / 60, 0.1) > sfx_per_min:
            run.warn(f"{len(times)} SFX exceeds the style budget of {sfx_per_min}/min")

        out_path = Path(args.out) if args.out else work / f"{path.stem}-sfx.mp4"
        filters, labels = [], ["[0:a]"]
        for i, t in enumerate(times):
            delay = int(t * 1000)
            filters.append(f"[1:a]volume={args.gain}dB,afade=t=in:st=0:d=0.02,"
                           f"afade=t=out:st=0.15:d=0.02,adelay={delay}|{delay}[s{i}]")
            labels.append(f"[s{i}]")
        filters.append("".join(labels) + f"amix=inputs={len(times) + 1}:duration=first:dropout_transition=0[a]")
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path), "-i", str(clip),
               "-filter_complex", ";".join(filters), "-map", "0:v?", "-map", "[a]",
               *encoder_args(dev["encoder"], 20), "-c:a", "aac", "-b:a", "192k",
               "-movflags", "+faststart", "-shortest", str(out_path)]
        run_cmd(cmd, dry_run=args.dry_run, timeout=3600, check=not args.dry_run)
        sidecar = work / "sfx.json"
        if not args.dry_run:
            write_json(sidecar, {"type": args.type, "at": times, "gain_db": args.gain})
        run.add_check("sfx_placed", "pass" if times else "warn", len(times), ">= 1")
        run.ok(output=str(out_path), artifacts=[str(out_path)], next_cmd="python scripts/check.py <out>")
        if not args.json:
            print(f"{len(times)} {args.type} placed at -18 dB -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
