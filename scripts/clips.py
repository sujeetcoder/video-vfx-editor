#!/usr/bin/env python3
"""Batch render approved clips: cut -> reframe -> captions -> hook -> -14 LUFS -> gates.

Writes clip_NN.mp4 + .srt + .jpg + .json per clip, manifest.json and review.html.

    python scripts/clips.py --from-plan --json
    python scripts/clips.py --from-plan --only 1,4 --json
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan  # noqa: E402
from _contract import InvalidInput, add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, filter_path, out_dir,  # noqa: E402
                    project_root, read_json, record_stage, run_cmd, work_dir, write_json)
from caption import STYLES, build_ass, chunk_words, to_srt  # noqa: E402
from reframe import ASPECTS, build_crop_expression, keyframes_from_faces  # noqa: E402


def clip_words(transcript: dict, start: float, end: float) -> list:
    words = []
    for w in transcript.get("words", []):
        s, e = float(w.get("s", 0)), float(w.get("e", 0))
        if s >= start - 0.05 and e <= end + 0.05:
            words.append({"w": w["w"], "s": round(s - start, 3), "e": round(e - start, 3)})
    return words


def hook_ass(text: str, width: int, height: int, duration: float, work: Path) -> Path:
    style = dict(STYLES["bold-pop"])
    style["size_pct"] = 0.060
    words = [{"w": w, "s": 0.0, "e": min(2.2, duration)} for w in text.split()[:12]]
    lines = chunk_words(words, max_chars=22, min_words=1, max_words=3)
    path = work / "hook.ass"
    path.write_text(build_ass(lines, width, height, style, "top", "en"), encoding="utf-8", newline="\n")
    return path


def render_clip(src: Path, cand: dict, transcript: dict, plan: dict, dev: dict, root,
                source_id: str, force: bool = False) -> dict:
    out = out_dir(root, f"{root_ts(root)}")
    idx = cand["id"]
    width, height = ASPECTS.get((plan.get("output") or {}).get("aspect", "9:16"), (1080, 1920))
    start, end = float(cand["in"]), float(cand["out"])
    dur = max(end - start, 0.5)
    work = work_dir(root, f"clip-{idx}")
    work.mkdir(parents=True, exist_ok=True)
    existing = out / f"clip_{idx:02d}.json"
    if not force and existing.is_file():
        prev = read_json(existing, {})
        clip_meta = prev.get("clip") or {}
        files = [out / f"clip_{idx:02d}.mp4", out / f"clip_{idx:02d}.srt", out / f"clip_{idx:02d}.jpg"]
        if (abs(float(clip_meta.get("source_in", -1)) - start) < 0.01
                and abs(float(clip_meta.get("source_out", -1)) - end) < 0.01
                and all(f.is_file() for f in files)):
            log(f"clip {idx} already rendered for this window; reusing")
            return {"id": idx, "path": str(files[0]), "srt": str(files[1]), "thumb": str(files[2]),
                    "sidecar": str(existing), "score": cand.get("score"), "in": start, "out": end,
                    "duration": round(dur, 2), "reused": True}

    words = clip_words(transcript, start, end)
    cap_cfg = plan.get("captions") or {}
    lines = chunk_words(words, cap_cfg.get("max_chars", 32), 2, 4)
    ass = work / f"clip_{idx:02d}.ass"
    ass.write_text(build_ass(lines, width, height, STYLES.get(cap_cfg.get("style", "bold-pop"), STYLES["bold-pop"]),
                             cap_cfg.get("position", "bottom"), cap_cfg.get("lang", "hi")),
                   encoding="utf-8", newline="\n")
    srt = out / f"clip_{idx:02d}.srt"
    srt.parent.mkdir(parents=True, exist_ok=True)
    srt.write_text(to_srt(lines), encoding="utf-8", newline="\n")

    src_w = int(plan.get("source_width") or 1920)
    src_h = int(plan.get("source_height") or 1080)
    kfs = keyframes_from_faces([], 30.0, src_w, src_h, "9:16")
    cam = build_crop_expression(kfs, src_w, src_h, width, height)
    vf = (f"crop={cam['w']}:{cam['h']}:x='{cam['x']}':y='{cam['y']}',"
          f"scale={width}:{height}:flags=lanczos,setsar=1,"
          f"subtitles={filter_path(ass)}")
    hook = ""
    if cand.get("hook_line"):
        hook = cand["hook_line"]
        ha = hook_ass(hook, width, height, dur, work)
        vf += f",subtitles={filter_path(ha)}"

    clip_path = out / f"clip_{idx:02d}.mp4"
    loud = float((plan.get("output") or {}).get("loudness", -14.0))
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
           "-i", str(src), "-vf", vf,
           "-af", f"loudnorm=I={loud}:TP=-1:LRA=11,afade=t=in:st=0:d=0.03,"
                  f"afade=t=out:st={max(dur - 0.05, 0):.3f}:d=0.05",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", "-r", str((plan.get("output") or {}).get("fps", 30)),
           str(clip_path)]
    rc, output = run_cmd(cmd, timeout=7200)
    if rc != 0:
        raise InvalidInput(f"clip {idx} render failed: {output[-600:]}",
                           fix="re-run with --only to isolate the clip", doc="references/clipping.md")

    thumb = out / f"clip_{idx:02d}.jpg"
    run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-ss", "1", "-i", str(clip_path),
             "-frames:v", "1", "-q:v", "3", str(thumb)], timeout=300)

    sidecar = {
        "clip": {
            "id": idx, "score": cand.get("score"), "signals": cand.get("signals"),
            "hook_line": hook, "reason": cand.get("reason"),
            "source_in": start, "source_out": end, "starts_clean": cand.get("starts_clean", True),
            "crop_keep": 1.0, "hook_offset": 0.0,
        },
        "transcript": " ".join(w["w"] for w in words)[:4000],
        "device": dev["resolved"],
        "credits": [],
        "source": source_id,
    }
    write_json(out / f"clip_{idx:02d}.json", sidecar)
    return {"id": idx, "path": str(clip_path), "srt": str(srt), "thumb": str(thumb),
            "sidecar": str(out / f"clip_{idx:02d}.json"), "score": cand.get("score"),
            "in": start, "out": end, "duration": round(dur, 2)}


def root_ts(root) -> str:
    state = read_json(Path(root) / "edit" / "state.json", {}) or {}
    return str(state.get("run_id", "run")).replace("/", "-")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Render approved clips")
    add_common(parser)
    parser.add_argument("--from-plan", action="store_true")
    parser.add_argument("--only", default=None, help="comma-separated candidate ids")
    parser.add_argument("--allow-unapproved", action="store_true")
    parser.add_argument("--force", action="store_true", help="re-render clips that already exist")
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root, refresh=args.refresh)
    dev = device_plan(args.device, caps)

    with stage("clips", args) as run:
        run.device = dev["resolved"]
        plan_path = state.get("artifacts", {}).get("plan")
        if not plan_path or not Path(plan_path).is_file():
            raise InvalidInput("no plan.json for this project",
                               fix="python scripts/plan.py <video> --job clip")
        plan = read_json(plan_path, {})
        intake_path = work_dir(root) / "intake.json"
        if not intake_path.is_file():
            raise InvalidInput("refusing to render clips without intake.json",
                               fix="python scripts/intake.py --preset clip")
        cands = plan.get("candidates") or []
        approved = plan.get("approved") or []
        if not approved and not args.allow_unapproved:
            raise InvalidInput(
                "no clips approved yet",
                fix="review candidates.json, then: python scripts/forge.py approve 1 4 7",
                doc="references/clipping.md",
            )
        if args.only:
            wanted = {int(x) for x in args.only.split(",") if x.strip().isdigit()}
        else:
            wanted = set(approved) if approved and not args.allow_unapproved else {c["id"] for c in cands}
        selected = [c for c in cands if c["id"] in wanted]
        if not selected:
            raise InvalidInput("no candidates matched", fix=f"valid ids: {[c['id'] for c in cands]}")

        src = expand_inputs([plan.get("source") or state.get("source")])[0]
        transcript_path = None
        for cand in (state.get("artifacts", {}).get("asr"),
                     work_dir(root, f"p-{src.stem}") / "words.json"):
            if cand and Path(cand).is_file():
                transcript_path = Path(cand)
                break
        if transcript_path is None:
            raise InvalidInput("no transcript; captions need words.json",
                               fix=f'python scripts/asr.py "{src}" --lang hi --json')
        transcript = read_json(transcript_path, {})

        rendered = []
        for cand in selected:
            log(f"rendering clip {cand['id']} ({cand['in']:.1f}–{cand['out']:.1f})")
            rendered.append(render_clip(src, cand, transcript, plan, dev, root, str(src),
                                        force=args.force))
            run.add_check(f"clip_{cand['id']}", "pass", cand.get("score"), "rendered")

        out = Path(rendered[0]["path"]).parent
        manifest = {"source": str(src), "clips": rendered, "count": len(rendered),
                    "device": dev["resolved"], "plan": str(plan_path),
                    "note": "clip strength, not a virality prediction"}
        write_json(out / "manifest.json", manifest)
        (out / "review.html").write_text(review_html(manifest), encoding="utf-8", newline="\n")
        state = ensure_edit(root)
        record_stage(root, state, "clips", out / "manifest.json", count=len(rendered))
        run.ok(output=str(out / "manifest.json"),
               artifacts=[r["path"] for r in rendered] + [str(out / "manifest.json")],
               next_cmd=f'python scripts/check.py "{out}" --json')
        if not args.json:
            for r in rendered:
                print(f"clip {r['id']}: {r['duration']}s score {r['score']} -> {r['path']}")
    return 0


def review_html(manifest: dict) -> str:
    cards = []
    for c in manifest["clips"]:
        rel_mp4 = Path(c["path"]).name
        rel_srt = Path(c["srt"]).name
        cards.append(
            f'<section><h2>clip {c["id"]:02d} — score {c["score"]}</h2>'
            f'<video controls src="{html.escape(rel_mp4)}"></video>'
            f'<p><a href="{html.escape(rel_srt)}">subtitles</a> · '
            f'{c["in"]:.1f}–{c["out"]:.1f}s · {c["duration"]}s</p></section>'
        )
    return ("<!doctype html><meta charset='utf-8'><title>clip review</title>"
            "<style>body{background:#111;color:#eee;font:16px system-ui;margin:24px}"
            "section{display:inline-block;vertical-align:top;margin:12px}"
            "video{height:420px;border-radius:12px}</style>"
            f"<h1>{manifest['count']} clips</h1>{''.join(cards)}</html>")


if __name__ == "__main__":
    sys.exit(main())
