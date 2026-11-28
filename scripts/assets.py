#!/usr/bin/env python3
"""Classify the files in a folder into asset roles before any editing.

    python scripts/assets.py "C:/clips/my-shoot" --json

A folder is a shoot, not a pile of files. Name hints beat extensions:
`background.png` is a backdrop, `background.wav` is a music bed, `video.mp4` is
the talking head, `b-roll/` or `cutaway*` files are inserts, `logo.png` is an
overlay, `*.srt` is an existing caption track.

Roles: video, background (image behind a contain layout), music (bed to duck
under the voice), broll, overlay, subtitles. Everything recognised but unused is
reported, never dropped silently.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import InvalidInput, add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, ffprobe_json, project_root, record_stage, work_dir,  # noqa: E402
                    write_json)

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".mts"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg", ".opus"}
SUB_EXT = {".srt", ".ass", ".vtt"}
SKIP_NAMES = {"thumbs.db", "desktop.ini", ".ds_store"}

# Token sets, matched against the name split on non-alphanumerics.
NAME_ROLES = {
    "video": {"video", "main", "source", "hero", "primary", "talking", "talk", "interview",
              "presenter", "a_roll", "aroll"},
    "background": {"background", "backdrop", "wallpaper", "bg", "bgimage", "bgi"},
    "music": {"music", "bgm", "bed", "song", "soundtrack", "theme", "audio"},
    "broll": {"broll", "cutaway", "insert", "extra", "supplemental", "b_roll"},
    "overlay": {"logo", "watermark", "brandmark", "sting"},
    "subtitles": {"subtitles", "subs", "captions", "caption", "srt"},
}


def kind_of(suffix: str) -> str | None:
    ext = suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in SUB_EXT:
        return "subtitles"
    return None


def tokens(path: Path) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", path.stem.lower()) if t}


def role_for(path: Path) -> tuple[str | None, str]:
    """(role, why) for one file. 'name' when a hint decided it, 'kind' otherwise."""
    kind = kind_of(path.suffix)
    if kind is None:
        return None, "unsupported extension"
    named = next((role for role, names in NAME_ROLES.items() if tokens(path) & names), None)
    if named == "subtitles" or kind == "subtitles":
        return "subtitles", "name" if named == "subtitles" else "kind"
    if named == "background":
        # background.wav is a bed, background.mp4 is footage: extension decides the use
        return {"image": "background", "audio": "music", "video": "broll"}[kind], "name"
    if named == "video":
        return ("video", "name") if kind == "video" else ("broll", "name")
    if named == "music":
        return ("music", "name") if kind == "audio" else ("broll", "name")
    if named in ("broll", "overlay"):
        return ("overlay", "name") if named == "overlay" and kind == "image" else ("broll", "name")
    if kind == "video":
        return "video", "kind"
    if kind == "image":
        return "broll", "kind"
    if kind == "audio":
        return "music", "kind"
    return None, "no role"


def probe_asset(path: Path) -> dict:
    entry = {"path": str(path), "name": path.name, "kind": kind_of(path.suffix),
             "bytes": path.stat().st_size}
    if entry["kind"] in ("video", "audio", "image"):
        try:
            info = ffprobe_json(path)
        except Exception:  # noqa: BLE001 - an unreadable asset must not kill the scan
            log(f"WARN could not probe {path.name}")
            return entry
        fmt, stream = info.get("format") or {}, {}
        for s in info.get("streams") or []:
            if s.get("codec_type") == "video":
                stream = s
                break
        entry["duration"] = round(float(fmt.get("duration") or 0), 3)
        entry["width"] = stream.get("width")
        entry["height"] = stream.get("height")
    return entry


def scan(folder: Path, limit: int = 500) -> dict:
    """Every file under `folder` with its role; the main video is resolved last."""
    if not folder.is_dir():
        raise InvalidInput(f"not a folder: {folder}", fix="pass the directory holding the shoot")
    files = [p for p in sorted(folder.rglob("*"))
             if p.is_file() and p.name.lower() not in SKIP_NAMES and not p.name.startswith(".")]
    if len(files) > limit:
        raise InvalidInput(f"{len(files)} files in {folder.name}",
                           fix=f"keep the folder under {limit} assets or pass the video itself")
    assets, notes = [], []
    for path in files:
        role, why = role_for(path)
        if role is None:
            notes.append(f"ignored {path.name} ({why})")
            continue
        entry = probe_asset(path)
        entry.update({"role": role, "decided_by": why})
        assets.append(entry)

    videos = [a for a in assets if a["role"] == "video"]
    named = [a for a in videos if a["decided_by"] == "name"]
    main = None
    if named:
        main = max(named, key=lambda a: a.get("duration") or 0)
    elif videos:
        main = max(videos, key=lambda a: a.get("duration") or 0)
    for a in videos:
        if a is not main:
            a["role"] = "broll"  # extra footage is insert material

    background = next((a for a in assets if a["role"] == "background" and a["kind"] == "image"), None)
    music = next((a for a in assets if a["role"] == "music" and a["kind"] == "audio"), None)
    for a in assets:
        if a["role"] == "music" and a is not music and a["kind"] == "audio":
            notes.append(f"extra audio {a['name']} kept as b-roll material")
            a["role"] = "broll"
    roles = {
        "video": main["path"] if main else None,
        "background": background["path"] if background else None,
        "music": music["path"] if music else None,
        "broll": [a["path"] for a in assets if a["role"] == "broll"],
        "overlays": [a["path"] for a in assets if a["role"] == "overlay"],
        "subtitles": next((a["path"] for a in assets if a["role"] == "subtitles"), None),
    }
    if not main:
        raise InvalidInput(
            f"no video in {folder}",
            fix="put the talking-head clip in the folder (video.mp4 / main.mp4 / source.mp4)",
            doc="references/assets-and-motion.md",
        )
    if len([a for a in assets if a["role"] == "video"]) > 1:
        notes.append("several video files: the longest named one is the main video, the rest are b-roll")
    return {"folder": str(folder), "roles": roles, "assets": assets, "notes": notes}


def role_table(manifest: dict) -> str:
    lines = [f"{'role':<12} {'kind':<9} {'duration':>8}  asset"]
    for a in manifest.get("assets", []):
        dur = a.get("duration")
        lines.append(f"{a['role']:<12} {a['kind'] or '-':<9} "
                     f"{(f'{dur:.2f}s' if dur else '-'):>8}  {a['name']}  [{a['decided_by']}]")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Classify a folder's assets into roles")
    add_common(parser)
    parser.add_argument("folder")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    root = project_root(args.project)
    ensure_edit(root)

    with stage("assets", args) as run:
        manifest = scan(Path(str(args.folder).strip('"\'')))
        out = Path(args.out) if args.out else work_dir(root, "assets") / "assets.json"
        if not args.dry_run:
            write_json(out, manifest)
            state = ensure_edit(root)
            record_stage(root, state, "assets", out,
                         video=manifest["roles"]["video"], broll=len(manifest["roles"]["broll"]))
        roles = manifest["roles"]
        run.add_check("main_video", "pass" if roles["video"] else "fail",
                      Path(roles["video"]).name if roles["video"] else "-", "one talking head")
        run.add_check("side_assets", "pass" if any(roles[k] for k in ("background", "music")) else "warn",
                      sum(1 for k in ("background", "music") if roles[k]), "background/music optional")
        run.ok(output=str(out), artifacts=[str(out)] + [p for p in roles["broll"] if p],
               next_cmd=f'python scripts/forge.py init "{roles["video"]}" --job edit')
        if not args.json:
            print(role_table(manifest))
            for note in manifest.get("notes", []):
                print(f"note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
