#!/usr/bin/env python3
"""HyperFrames bridge: HTML/CSS motion rendered with Node + Chrome, composited by FFmpeg.

    python scripts/motion.py list --json
    python scripts/motion.py render kinetic-hook --text "3 mistakes" --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args  # noqa: E402
from _contract import InvalidInput, MissingCapability, add_common, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, project_root,  # noqa: E402
                    record_stage, run_cmd, work_dir, write_json)

RECIPES_DIR = Path(__file__).resolve().parent.parent / "packs" / "motion"


def recipes() -> list:
    if not RECIPES_DIR.is_dir():
        return []
    out = []
    for p in sorted(RECIPES_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        data["file"] = str(p)
        out.append(data)
    return out


def node_env(caps: dict) -> dict:
    """NODE_PATH for a global puppeteer install, resolving nvm/shim node paths."""
    env = os.environ.copy()
    # node may be a shim (nvm), so ask it where it really lives
    rc, real = run_cmd([caps["node"]["path"], "-p", "process.execPath"], timeout=30)
    base = Path(real.strip() or caps["node"]["path"]).resolve().parent
    roots = [env.get("NODE_PATH"), str(base / "node_modules"), str(base.parent / "lib" / "node_modules")]
    env["NODE_PATH"] = os.pathsep.join(r for r in roots if r and Path(r).is_dir())
    return env


def node_ready(caps: dict) -> tuple:
    node = caps.get("node", {})
    if not node.get("present"):
        return False, "Node is not installed"
    if not caps.get("npm", {}).get("present"):
        return False, "npm is not installed"
    rc, out = run_cmd([node["path"], "-e", "require.resolve('puppeteer')"],
                      timeout=30, env=node_env(caps))
    if rc != 0:
        return False, "puppeteer is not installed (npm i -g puppeteer)"
    return True, "ok"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Motion graphics via the HyperFrames bridge")
    add_common(parser)
    parser.add_argument("command", nargs="?", default="list", choices=["list", "render", "gates"])
    parser.add_argument("recipe", nargs="?", default=None)
    parser.add_argument("--text", default="")
    parser.add_argument("--subtitle", default="")
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--video", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    dev = device_plan(args.device, caps)

    with stage("motion", args) as run:
        run.device = dev["resolved"]
        if args.command == "list":
            items = recipes()
            run.ok(output=RECIPES_DIR if RECIPES_DIR.exists() else None,
                   artifacts=[r["file"] for r in items],
                   next_cmd="python scripts/motion.py render kinetic-hook --text \"...\"")
            if not args.json:
                for r in items:
                    print(f"{r.get('id', Path(r['file']).stem):<20} {r.get('description', '')}")
            return 0

        if not args.recipe:
            raise InvalidInput("name a recipe", fix="python scripts/motion.py list")
        match = next((r for r in recipes() if r.get("id") == args.recipe or Path(r["file"]).stem == args.recipe), None)
        if match is None:
            raise InvalidInput(f"unknown recipe '{args.recipe}'",
                               fix="python scripts/motion.py list", doc="references/motion-graphics.md")
        ok, why = node_ready(caps)
        if not ok:
            raise MissingCapability(
                f"motion graphics need Node + puppeteer ({why})",
                fix="winget install OpenJS.NodeJS.LTS | brew install node@22, then: npm i -g puppeteer",
                doc="references/troubleshooting.md#node",
            )

        work = work_dir(root, f"motion-{args.recipe}")
        spec = work / "spec.json"
        write_json(spec, {"recipe": match, "text": args.text, "subtitle": args.subtitle,
                          "duration": args.duration, "fps": 30,
                          "width": 1080, "height": 1920})
        frames = work / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        rc, out = run_cmd([caps["node"]["path"], str(RECIPES_DIR / "render.mjs"),
                           "--spec", str(spec), "--out", str(frames)],
                          dry_run=args.dry_run, timeout=1800, env=node_env(caps))
        if args.dry_run:
            run.ok(output=str(work / f"{args.recipe}.mp4"), next_cmd="rerun without --dry-run")
            return 0
        if rc != 0:
            raise InvalidInput(f"motion render failed: {out[-500:]}",
                               fix="npm i -g puppeteer, or run with --dry-run to inspect the spec")

        seq = work / f"{args.recipe}.mov"
        run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-framerate", "30",
                 "-i", str(frames / "f_%04d.png"), "-c:v", "qtrle", "-pix_fmt", "argb", str(seq)],
                timeout=1800, check=True)
        out_path = Path(args.out) if args.out else work / f"{args.recipe}.mp4"
        if args.video:
            base = expand_inputs([args.video])[0]
            fc = "[0:v][1:v]overlay=shortest=1[out]"
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(base), "-i", str(seq),
                   "-filter_complex", fc, "-map", "[out]", "-map", "0:a?",
                   *encoder_args(dev["encoder"], 19), "-c:a", "copy", str(out_path)]
        else:
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(seq),
                   *encoder_args(dev["encoder"], 19), "-pix_fmt", "yuv420p", str(out_path)]
        run_cmd(cmd, timeout=1800, check=True)

        energy = frame_diff_energy(out_path)
        run.add_check("motion_energy", "pass" if energy > 0.5 else "warn", round(energy, 2), "> 0.5")
        run.add_check("text_overflow", "pass" if len(args.text) <= 60 else "warn", len(args.text), "<= 60 chars")
        sidecar = work / "motion.json"
        write_json(sidecar, {"recipe": args.recipe, "energy": round(energy, 2), "text": args.text})
        state = ensure_edit(root)
        record_stage(root, state, "motion", out_path, recipe=args.recipe)
        run.ok(output=str(out_path), artifacts=[str(out_path)], next_cmd="python scripts/check.py <out>")
        if not args.json:
            print(f"motion {args.recipe} energy={energy:.2f} -> {out_path}")
    return 0


def frame_diff_energy(path: Path) -> float:
    import re

    rc, out = run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(path),
                       "-vf", "tblend=all_mode=difference,signalstats,metadata=mode=print",
                       "-an", "-f", "null", "-"], timeout=600)
    vals = [float(v) for v in re.findall(r"YAVG=([\d.]+)", out)]
    return sum(vals) / len(vals) if vals else 0.0


if __name__ == "__main__":
    sys.exit(main())
