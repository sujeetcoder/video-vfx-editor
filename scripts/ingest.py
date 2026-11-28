#!/usr/bin/env python3
"""Ingest a local file / folder / URL into the project cache.

    python scripts/ingest.py "C:/clips/my video.mp4" --json
    python scripts/ingest.py "https://youtu.be/xyz" --acknowledge-rights --json
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import InvalidInput, MissingCapability, add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffprobe_json, is_url, project_root,  # noqa: E402
                    record_stage, run_cmd, sha1_file, which, work_dir, write_json)

COOKIE_BROWSERS = ("chrome", "firefox", "edge", "safari", "brave")


def ingest_local(src: Path, root) -> dict:
    if not src.is_file():
        raise InvalidInput(f"not a file: {src}", fix="pass an existing media file")
    if src.stat().st_size == 0:
        raise InvalidInput(f"{src.name} is 0 bytes",
                           fix="re-export or re-download the file",
                           doc="references/troubleshooting.md#corrupt-input")
    key = sha1_file(src)[:8]
    work = work_dir(root, f"i-{key}")
    meta = work / "ingest.json"
    if meta.is_file():
        log(f"cached ingest for {src.name} ({key})")
        return _load(meta)
    probe = ffprobe_json(src)
    if not probe.get("streams"):
        raise InvalidInput(f"{src.name} has no readable streams",
                           fix="the container may be corrupt; try remuxing with ffmpeg -i in -c copy out")
    data = {
        "kind": "local",
        "source": str(src),
        "path": str(src),
        "key": key,
        "bytes": src.stat().st_size,
        "duration": float((probe.get("format") or {}).get("duration") or 0),
        "cached": False,
    }
    write_json(meta, data)
    return data


def _load(meta: Path) -> dict:
    import json

    return json.loads(meta.read_text(encoding="utf-8"))


def ingest_url(url: str, root, cookies: str | None, max_height: int, dry_run: bool) -> dict:
    ytdlp = which("yt-dlp")
    if not ytdlp:
        raise MissingCapability(
            "yt-dlp is required for URL ingest",
            fix="python -m pip install --user -U yt-dlp",
            doc="references/troubleshooting.md#yt-dlp",
        )
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    work = work_dir(root, f"i-{key}")
    meta = work / "ingest.json"
    if meta.is_file() and Path(_load(meta).get("path", "")).is_file():
        log(f"cached download for {url}")
        return _load(meta)
    template = str(work / "source.%(ext)s")
    cmd = [ytdlp, "--no-playlist", "-f",
           f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b",
           "--merge-output-format", "mp4", "-o", template, "--restrict-filenames", "--", url]
    if cookies:
        cmd[1:1] = ["--cookies-from-browser", cookies]
    rc, out = run_cmd(cmd, dry_run=dry_run, timeout=7200)
    if dry_run:
        return {"kind": "url", "source": url, "path": str(work / "source.mp4"), "key": key, "dry_run": True}
    if rc != 0:
        raise InvalidInput(
            f"yt-dlp failed for {url}: {out.strip()[-500:]}",
            fix="check the link, or pass --cookies-from-browser chrome for age-restricted videos",
            doc="references/troubleshooting.md#yt-dlp",
        )
    candidates = sorted(work.glob("source.*"))
    if not candidates:
        raise InvalidInput("yt-dlp produced no file", fix="retry with --cookies-from-browser or a direct MP4 link")
    final = candidates[0]
    data = {"kind": "url", "source": url, "path": str(final), "key": key,
            "bytes": final.stat().st_size, "cached": True}
    write_json(meta, data)
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ingest local media or a URL")
    add_common(parser)
    parser.add_argument("inputs", nargs="+", help="file, folder, glob or URL")
    parser.add_argument("--acknowledge-rights", action="store_true",
                        help="required for URL clip jobs: you have the right to reuse this media")
    parser.add_argument("--cookies-from-browser", default=None, choices=COOKIE_BROWSERS)
    parser.add_argument("--max-height", type=int, default=1080)
    parser.add_argument("--copy-to-project", action="store_true", help="copy local media into edit/work")
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)

    with stage("ingest", args) as run:
        first = args.inputs[0]
        folder = None if is_url(first) else Path(str(first).strip('"\'')).expanduser()
        if folder is not None and folder.is_dir():
            # A folder is a shoot: classify its assets, then ingest the main video.
            from assets import scan

            manifest = scan(folder)
            write_json(work_dir(root, "assets") / "assets.json", manifest)
            data = ingest_local(Path(manifest["roles"]["video"]), root)
            data["assets"] = manifest["roles"]
            log(f"folder: {len(manifest['assets'])} assets, main video {Path(data['path']).name}")
        elif is_url(first):
            if len(args.inputs) > 1:
                raise InvalidInput("ingest one URL at a time", fix="run ingest.py once per link")
            if not args.acknowledge_rights and not args.dry_run:
                raise InvalidInput(
                    "URL editing needs explicit rights acknowledgement",
                    fix="re-run with --acknowledge-rights if you own the video or have permission "
                        "(YouTube's Terms require it; this tool never downloads playlists silently)",
                    doc="references/troubleshooting.md#rights",
                )
            data = ingest_url(first, root, args.cookies_from_browser, args.max_height, args.dry_run)
        else:
            files = expand_inputs(args.inputs)
            data = ingest_local(Path(files[0]), root)
            if len(files) > 1:
                data["extra_inputs"] = [str(p) for p in files[1:]]
            if args.copy_to_project and not args.dry_run:
                work = work_dir(root, f"i-{data['key']}")
                dest = work / Path(data["path"]).name
                if not dest.exists():
                    shutil.copy2(data["path"], dest)
                data["path"] = str(dest)
        if not args.dry_run:
            state = ensure_edit(root)
            state["source"] = data["path"]
            record_stage(root, state, "ingest", data.get("path"), source=data["source"], key=data.get("key"))
        run.ok(output=data.get("path"), artifacts=[data.get("path")] if data.get("path") else [],
               next_cmd=f'python scripts/probe.py "{data.get("path")}" --quick')
        if not args.json:
            print(f"ingested {data.get('kind')} -> {data.get('path')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
