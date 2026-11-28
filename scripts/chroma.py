#!/usr/bin/env python3
"""Auto-sampled chroma key: sample -> key -> sweep -> despill -> edge -> composite -> QC.

The 8-step order lives in references/chroma-key.md.

    python scripts/chroma.py green.mp4 --bg background.jpg --json
    python scripts/chroma.py green.mp4 --analyze-only --json
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args  # noqa: E402
from _contract import InvalidInput, add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, ffprobe_json, project_root,  # noqa: E402
                    record_stage, run_cmd, work_dir, write_json)

SIMS = (0.06, 0.10, 0.14, 0.18, 0.24, 0.30)
BLENDS = (0.02, 0.05, 0.08, 0.12)
TARGET_COVERAGE = (0.65, 0.85)


# --------------------------------------------------------------------------
# sampling (pure python, no numpy required)
# --------------------------------------------------------------------------
def kmeans(points, k=3, iterations=12):
    if not points:
        return []
    points = sorted(points)
    step = max(len(points) // k, 1)
    centers = [list(points[min(i * step, len(points) - 1)]) for i in range(k)]
    for _ in range(iterations):
        buckets = [[] for _ in range(k)]
        for p in points:
            idx = min(range(k), key=lambda i: _dist2(p, centers[i]))
            buckets[idx].append(p)
        new = []
        for i, bucket in enumerate(buckets):
            if bucket:
                new.append([sum(b[j] for b in bucket) / len(bucket) for j in range(3)])
            else:
                new.append(centers[i])
        centers = new
    sizes = [sum(1 for p in points if min(range(k), key=lambda i: _dist2(p, centers[i])) == i) for i in range(k)]
    return [{"rgb": [round(c, 1) for c in centers[i]], "share": round(sizes[i] / len(points), 3)}
            for i in range(k)]


def _dist2(a, b):
    return sum((float(x) - float(y)) ** 2 for x, y in zip(a, b))


def greenest(clusters):
    best = None
    for c in clusters:
        r, g, b = c["rgb"]
        score = g - max(r, b)
        if best is None or score > best[0]:
            best = (score, c, (r, g, b))
    if not best or best[0] < 12:
        return None
    r, g, b = best[2]
    return {"hex": f"0x{int(r):02X}{int(g):02X}{int(b):02X}", "rgb": [r, g, b], "share": best[1]["share"]}


def border_sample(path: Path, dry_run: bool = False) -> dict:
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", "1",
           "-i", str(path), "-frames:v", "1",
           "-vf", "crop=iw:ih*0.12:0:0,scale=64:-1,format=rgb24", "-f", "rawvideo", "-"]
    if dry_run:
        return {"clusters": [], "key": None}
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=90)
        raw = proc.stdout or b""
    except Exception:  # noqa: BLE001
        raw = b""
    if not raw:
        raise InvalidInput("could not sample the frame border",
                           fix="check the input plays: ffplay <file>")
    pts = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw) - 2, 3)]
    pts = pts[::4]
    clusters = kmeans(pts, 3)
    return {"clusters": clusters, "key": greenest(clusters)}


def alpha_probe_chain(color_hex: str, similarity: float, blend: float) -> str:
    """Key -> yuva -> alpha -> small gray sample.

    FFmpeg 9 refuses to negotiate a format for ``alphaextract`` unless the key
    output is pinned to yuva420p first.
    """
    return (f"chromakey={color_hex}:{similarity:.2f}:{blend:.2f},"
            "format=yuva420p,alphaextract,scale=96:54,format=gray")


def alpha_coverage(path: Path, color_hex: str, similarity: float, blend: float) -> float:
    """Mean alpha over a 96x54 sample (scale-invariant, fast on 4K).

    FFmpeg 9 refuses to negotiate a format for ``alphaextract`` unless the key
    output is pinned to yuva420p, hence the explicit format filter.
    """
    chain = alpha_probe_chain(color_hex, similarity, blend)
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error",
           "-ss", "1", "-t", "0.4", "-i", str(path), "-vf", chain, "-an",
           "-f", "rawvideo", "-"]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=90)
    except Exception:  # noqa: BLE001
        return 0.0
    data = proc.stdout or b""
    if not data:
        return 0.0
    return sum(data) / (len(data) * 255.0)


def sweep(path: Path, color_hex: str, dry_run: bool = False) -> dict:
    best = None
    table = []
    for sim in SIMS:
        for blend in BLENDS:
            cov = 0.5 if dry_run else alpha_coverage(path, color_hex, sim, blend)
            row = {"similarity": sim, "blend": blend, "coverage": round(cov, 3)}
            table.append(row)
            lo, hi = TARGET_COVERAGE
            penalty = 0 if lo <= cov <= hi else min(abs(cov - lo), abs(cov - hi))
            score = 1.0 - penalty
            if best is None or score > best["score"]:
                best = {"similarity": sim, "blend": blend, "coverage": round(cov, 3), "score": round(score, 3)}
    return {"best": best, "table": table}


def key_graph(color_hex: str, sim: float, blend: float, despill_mix: float = 0.5,
              choke: bool = False, feather: bool = True, garbage: str | None = None) -> str:
    """Deterministic key chain: [garbage] -> chromakey -> despill -> [choke] -> [feather] -> alpha."""
    parts = []
    if garbage:
        parts.append(f"crop={garbage}")
    parts.append(f"chromakey={color_hex}:{sim:.2f}:{blend:.2f}")
    if despill_mix:
        parts.append(f"despill=type=green:mix={despill_mix}")
    if choke:
        parts.append("morpho=mode=erode:planes=1:structure=3x3")
    if feather:
        parts.append("format=yuva420p,gblur=sigma=0.20")
    else:
        parts.append("format=yuva420p")
    return ",".join(parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Auto chroma key with sweep and QC")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--bg", default=None, help="background image/video (default: colour)")
    parser.add_argument("--bg-color", default="0x101010")
    parser.add_argument("--similarity", type=float, default=None)
    parser.add_argument("--blend", type=float, default=None)
    parser.add_argument("--color", default=None, help="override sample colour, e.g. 0x00B140")
    parser.add_argument("--despill", type=float, default=0.5)
    parser.add_argument("--garbage", default=None, help="garbage matte crop, e.g. 1920:1080:0:0")
    parser.add_argument("--choke", action="store_true", help="erode the alpha edge (morpho)")
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    dev = device_plan(args.device, caps)

    with stage("chroma", args) as run:
        run.device = dev["resolved"]
        path = expand_inputs([args.input])[0]
        work = work_dir(root, f"p-{path.stem}")
        if not caps["ffmpeg"]["filters"].get("despill"):
            log("WARN despill filter missing; install a full FFmpeg build for cleaner edges")
        sample = border_sample(path, dry_run=args.dry_run)
        key = sample["key"]
        if args.color:
            key = {"hex": args.color, "rgb": [], "share": 1.0}
        if key is None:
            raise InvalidInput(
                "no dominant green found on the border",
                fix="pass --color 0x00B140 or use scripts/matte.py for a non-green subject",
                doc="references/chroma-key.md",
            )
        sweep_result = sweep(path, key["hex"], dry_run=args.dry_run)
        sim = args.similarity if args.similarity is not None else sweep_result["best"]["similarity"]
        blend = args.blend if args.blend is not None else sweep_result["best"]["blend"]

        analysis = {"key": key, "clusters": sample["clusters"], "sweep": sweep_result,
                    "chosen": {"similarity": sim, "blend": blend}}
        write_json(work / "chroma.json", analysis)
        coverage = sweep_result["best"]["coverage"]
        lo, hi = TARGET_COVERAGE
        run.add_check("matte_coverage", "pass" if lo <= coverage <= hi else "warn", coverage,
                      f"{lo:.0%}–{hi:.0%} alpha")
        run.add_check("key_colour", "pass" if key else "fail", key.get("hex") if key else None,
                      "dominant border colour")

        if args.analyze_only or args.dry_run:
            run.ok(output=str(work / "chroma.json"), artifacts=[str(work / "chroma.json")],
                   next_cmd=f'python scripts/chroma.py "{path}" --bg <image> --json')
            return 0

        out_path = Path(args.out) if args.out else work / "chroma.mp4"
        graph = key_graph(key["hex"], sim, blend, args.despill,
                          choke=args.choke, garbage=args.garbage)
        src_probe = ffprobe_json(path)
        duration = float((src_probe.get("format") or {}).get("duration") or 0) or 1.0
        src_w = int(((src_probe.get("streams") or [{}])[0]).get("width") or 1920)
        src_h = int(((src_probe.get("streams") or [{}])[0]).get("height") or 1080)
        # overlay=shortest=1: the background may be infinite (colour/looped image)
        if args.bg:
            bg = expand_inputs([args.bg])[0]
            fg = "[0:v]" + graph + "[fg]"
            fc = (f"[1:v]scale={src_w}:{src_h}:force_original_aspect_ratio=increase,"
                  f"crop={src_w}:{src_h}[bgv];{fg};[bgv][fg]overlay=shortest=1,format=yuv420p[out]")
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
                   "-loop", "1", "-i", str(bg), "-filter_complex", fc, "-map", "[out]", "-map", "0:a?",
                   *encoder_args(dev["encoder"], 18), "-c:a", "aac", "-t", f"{duration:.3f}",
                   "-movflags", "+faststart", str(out_path)]
        else:
            fc = (f"[0:v]{graph}[fg];color=c={args.bg_color}:s={src_w}x{src_h}:d={duration:.3f}[bgv];"
                  f"[bgv][fg]overlay=shortest=1,format=yuv420p[out]")
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
                   "-filter_complex", fc, "-map", "[out]", "-map", "0:a?",
                   *encoder_args(dev["encoder"], 18), "-c:a", "aac",
                   "-movflags", "+faststart", str(out_path)]
        rc, out = run_cmd(cmd, timeout=7200)

        # QC previews on white and black
        previews = []
        for bg, name in (("white", "chroma-white.png"), ("black", "chroma-black.png")):
            prev = work / name
            fc = (f"[0:v]{graph}[fg];color=c={bg}:s={src_w}x{src_h}:d={duration:.3f}[bgv];"
                  f"[bgv][fg]overlay=shortest=1[out]")
            run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-ss", "1", "-i", str(path),
                     "-filter_complex", fc, "-map", "[out]", "-frames:v", "1", str(prev)], timeout=300)
            previews.append(str(prev))
        state = ensure_edit(root)
        record_stage(root, state, "chroma", out_path, similarity=sim, blend=blend)
        run.ok(output=str(out_path), artifacts=[str(out_path), *previews],
               next_cmd=f'python scripts/check.py "{out_path}" --json')
        if not args.json:
            print(f"key {key['hex']} sim={sim} blend={blend} coverage={coverage:.0%} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
