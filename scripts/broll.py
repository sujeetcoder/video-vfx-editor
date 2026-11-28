#!/usr/bin/env python3
"""Cut b-roll in over the words that describe it: folder assets first, then free stock.

    python scripts/broll.py camera.mp4 --json
    python scripts/broll.py camera.mp4 --count 3 --query "village market" --json

Each insert lands on a sentence boundary, fades in/out over 0.22 s and carries its
own slow zoom, so a still photo reads as footage. Licences are recorded in
``credits.md``; non-commercial sources are never used.
"""
from __future__ import annotations

import argparse
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args  # noqa: E402
from _contract import add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, ffprobe_json, project_root,  # noqa: E402
                    read_json, record_stage, run_cmd, work_dir, write_json)
from stock import UA, keywords, score, search  # noqa: E402

# `--query` / plan.broll.query overrides the per-sentence keywords for every insert.
FADE = 0.22
INSERT_LEN = (1.5, 2.4)
GUARD = 1.5  # keep the hook and the last beat for the speaker


def span(seg: dict) -> tuple:
    """words.json segments carry short keys (s/e); accept long ones too."""
    return float(seg.get("s", seg.get("start", 0))), float(seg.get("e", seg.get("end", 0)))


def pick_slots(segments: list, duration: float, count: int) -> list:
    """Evenly spread insert windows over whole sentences, avoiding the ends."""
    eligible = [s for s in segments
                if span(s)[0] >= GUARD and span(s)[1] <= duration - GUARD
                and span(s)[1] - span(s)[0] >= 0.6]
    if not eligible or count <= 0:
        return []
    if count >= len(eligible):
        picks = eligible
    else:
        step = (len(eligible) - 1) / (count - 1) if count > 1 else 0
        picks = [eligible[round(i * step)] for i in range(count)]
    slots = []
    for seg in picks:
        start, seg_end = span(seg)
        end = min(seg_end, start + INSERT_LEN[1])
        slots.append({"start": round(start, 3),
                      "dur": round(max(min(end - start, INSERT_LEN[1]), INSERT_LEN[0]), 3),
                      "text": str(seg.get("text") or "")})
    return slots


def build_graph(inserts: list, width: int, height: int, fps: int) -> tuple[str, str]:
    """filter_complex plus the output label; inputs are 1..n after the base video."""
    cw, ch = int(width * 1.6) // 2 * 2, int(height * 1.6) // 2 * 2
    parts, prev = [], "0:v"
    for i, ins in enumerate(inserts, 1):
        dur, frames = float(ins["dur"]), max(int(float(ins["dur"]) * fps), 2)
        fade = min(FADE, dur / 4)
        parts.append(
            f"[{i}:v]scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},setsar=1,"
            f"fps={fps},zoompan=z='1+0.10*on/{frames}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
            f"d=1:s={width}x{height},trim=duration={dur},setpts=PTS-STARTPTS,format=rgba,"
            f"fade=t=in:st=0:d={fade}:alpha=1,fade=t=out:st={dur - fade:.3f}:d={fade}:alpha=1,"
            f"setpts=PTS+{float(ins['start']):.3f}/TB[o{i}]")
        parts.append(f"[{prev}][o{i}]overlay=enable='between(t,{float(ins['start']):.3f},"
                     f"{float(ins['start']) + dur:.3f})':eof_action=pass[v{i}]")
        prev = f"v{i}"
    return ";".join(parts), prev


def download(asset: dict, dest_dir: Path, index: int) -> Path | None:
    url = asset.get("url")
    if not url:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower() or ".jpg"
    if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
        suffix = ".jpg"
    dest = dest_dir / f"broll_{index:02d}{suffix}"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as resp:
            dest.write_bytes(resp.read())
        return dest
    except Exception as exc:  # noqa: BLE001 - one dead URL must not stop the edit
        log(f"WARN b-roll download failed: {exc}")
        return None


def resolve_asset(slot: dict, local: list, aspect: str, index: int, dl_dir: Path,
                  query: str | None) -> dict | None:
    """A still/video for one slot: a local folder asset, else the best free-stock hit."""
    if local:
        path = Path(local.pop(0))
        return {"path": str(path), "kind": "video" if path.suffix.lower() in
                (".mp4", ".mov", ".mkv", ".webm") else "image",
                "title": path.name, "creator": "local folder", "license": "user-provided",
                "source": str(path)}
    text = (query or slot.get("text") or "").strip()
    term = keywords(text, 4) if text else ""
    if not term:
        return None
    # Wikimedia indexes Hindi filenames, but a multi-word Devanagari query matches
    # poorly: try the sentence's keywords whole, then its strongest single word.
    for attempt in [term, *term.split()[:2]]:
        hits = [score(a, aspect) for a in search(attempt, 6)]
        hits = [a for a in hits if a.get("url") and a.get("score", 0) >= 0.6]
        hits.sort(key=lambda a: a["score"], reverse=True)
        for hit in hits:
            path = download(hit, dl_dir, index)
            if path:
                return {"path": str(path), "kind": "image", "title": hit.get("title"),
                        "creator": hit.get("creator"), "license": hit.get("license"),
                        "source": hit.get("source"), "query": attempt}
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Insert topic-matched b-roll")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--count", type=int, default=None)
    parser.add_argument("--query", default=None, help="force one search query")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    dev = device_plan(args.device, caps)

    with stage("broll", args) as run:
        run.device = dev["resolved"]
        path = expand_inputs([args.input])[0]
        plan_path = state.get("artifacts", {}).get("plan")
        plan = read_json(plan_path, {}) if plan_path and Path(plan_path).is_file() else {}
        cfg = plan.get("broll") or {}
        count = args.count if args.count is not None else int(cfg.get("count") or 0)
        words_path = state.get("artifacts", {}).get("asr") or (state.get("artifacts", {}).get("cut"))
        work = work_dir(root, f"p-{path.stem}")
        out_path = Path(args.out) if args.out else work / "broll.mp4"
        info = ffprobe_json(path, dry_run=args.dry_run)
        duration = float((info.get("format") or {}).get("duration") or 0)
        width = int((plan.get("output") or {}).get("width") or 1080)
        height = int((plan.get("output") or {}).get("height") or 1920)
        fps = int((plan.get("output") or {}).get("fps") or 30)

        transcript = read_json(words_path, {}) if words_path else {}
        slots = pick_slots(transcript.get("segments") or [], duration, count)
        local = list((plan.get("assets") or {}).get("broll") or [])
        inserts = []
        # An explicit topic hint (plan.broll.query) is what makes non-English audio
        # searchable: Hindi keywords alone match Wikimedia file titles very loosely.
        topic = args.query or cfg.get("query")
        for i, slot in enumerate(slots, 1):
            asset = resolve_asset(slot, local, (plan.get("output") or {}).get("aspect", "9:16"),
                                  i, work / "dl", topic)
            if asset:
                inserts.append({**slot, **asset})
        if slots and not inserts:
            log("WARN no b-roll asset could be resolved; the shot is unchanged")

        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path)]
        if inserts:
            for ins in inserts:
                if ins["kind"] == "video":
                    cmd += ["-t", str(ins["dur"]), "-i", ins["path"]]
                else:
                    cmd += ["-loop", "1", "-framerate", str(fps), "-t", str(ins["dur"]), "-i", ins["path"]]
            graph, label = build_graph(inserts, width, height, fps)
            cmd += ["-filter_complex", graph, "-map", f"[{label}]", "-map", "0:a?"]
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a?"]
        cmd += [*encoder_args(dev["encoder"], 18), "-c:a", "copy", "-t", f"{duration:.3f}",
                "-movflags", "+faststart", str(out_path)]
        run_cmd(cmd, dry_run=args.dry_run, timeout=7200)

        manifest = work / "broll.json"
        if not args.dry_run:
            write_json(manifest, {"slots": slots, "inserts": inserts, "count": len(inserts)})
            if inserts:
                lines = ["# B-roll credits", ""]
                for ins in inserts:
                    lines.append(f"- {ins.get('title')} — {ins.get('creator') or 'unknown'} "
                                 f"({ins.get('license')}) {ins.get('source')}")
                (work / "credits.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            state = ensure_edit(root)
            record_stage(root, state, "broll", out_path, count=len(inserts))
        run.add_check("broll", "pass" if inserts else "warn", len(inserts),
                      f"{count} requested")
        run.add_check("licences", "pass" if all(
            "nc" not in str(i.get("license", "")).lower() for i in inserts) else "fail",
            len(inserts), "no non-commercial assets")
        run.ok(output=str(out_path), artifacts=[str(out_path), str(manifest)],
               next_cmd=f'python scripts/caption.py "{out_path}" --burn')
        if not args.json:
            print(f"b-roll inserts: {len(inserts)} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
