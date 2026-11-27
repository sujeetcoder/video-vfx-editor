#!/usr/bin/env python3
"""Preflight: check -> ask -> install only what is missing. Never reinstalls.

    python install/ensure.py --check          # read-only table
    python install/ensure.py --install --yes  # install missing, no prompts
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _caps import capabilities, fonts_dir  # noqa: E402
from _contract import add_common, log, stage  # noqa: E402

FONT_URLS = {
    "NotoSansDevanagari.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/notosansdevanagari/NotoSansDevanagari%5Bwdth%2Cwght%5D.ttf",
    "Inter.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
    "NotoSans.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/notosans/NotoSans%5Bwdth%2Cwght%5D.ttf",
}

PIP_PACKAGES = ["numpy", "opencv-python-headless", "pillow", "yt-dlp", "faster-whisper"]


def os_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def plan_actions(caps: dict) -> list:
    osname = os_name()
    actions = []

    ff = caps["ffmpeg"]
    if not ff["present"] or not ff["has_libass"]:
        if osname == "windows":
            cmd = ["winget", "install", "-e", "--id", "Gyan.FFmpeg",
                   "--accept-source-agreements", "--accept-package-agreements"]
        elif osname == "macos":
            cmd = ["brew", "install", "ffmpeg"]
        else:
            cmd = ["apt-get", "install", "-y", "ffmpeg"]
        actions.append({
            "id": "ffmpeg", "system": True, "cmd": cmd,
            "detail": "FFmpeg with libass/zscale is required for captions and HDR-safe scaling",
            "manual": "Linux: run 'sudo apt install ffmpeg' yourself (this tool never uses sudo)",
        })

    node = caps["node"]
    if not node["ok"]:
        if osname == "windows":
            cmd = ["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
                   "--accept-source-agreements", "--accept-package-agreements"]
        elif osname == "macos":
            cmd = ["brew", "install", "node@22"]
        else:
            cmd = ["nvm", "install", "22"]
        actions.append({
            "id": "node", "system": True, "cmd": cmd,
            "detail": "Node >= 20 (22 preferred) runs the HyperFrames motion bridge",
            "manual": "no-admin fallback: install nvm/fnm, then 'nvm install 22'",
        })

    missing_pip = [p for p in PIP_PACKAGES if not _pip_has(p)]
    if missing_pip:
        actions.append({
            "id": "python-packages", "system": False,
            "cmd": [sys.executable, "-m", "pip", "install", "--user", *missing_pip],
            "detail": "user-local pip packages: " + ", ".join(missing_pip),
            "manual": None,
        })

    if not caps["fonts"]["devanagari"]:
        actions.append({
            "id": "fonts", "system": False, "cmd": ["<download>"],
            "detail": "OFL Devanagari + Latin fonts into " + str(fonts_dir(ROOT)),
            "manual": None,
        })
    return actions


def _pip_has(name: str) -> bool:
    import importlib.util

    mod = {"opencv-python-headless": "cv2", "pillow": "PIL", "faster-whisper": "faster_whisper",
           "yt-dlp": "yt_dlp"}.get(name, name.replace("-", "_"))
    return importlib.util.find_spec(mod) is not None


def run_action(action: dict, yes: bool) -> dict:
    aid = action["id"]
    if action["cmd"] == ["<download>"]:
        return download_fonts()
    if action["system"]:
        cmd_base = action["cmd"][0]
        if cmd_base in ("apt-get", "nvm"):
            return {"id": aid, "status": "skipped", "detail": action["manual"] or "manual install required"}
    if shutil.which(action["cmd"][0]) is None:
        return {"id": aid, "status": "skipped", "detail": f"{action['cmd'][0]} not on PATH. {action['manual'] or ''}".strip()}
    if action["system"] and not yes:
        answer = input(f"Install {aid} with: {' '.join(action['cmd'])}\nProceed? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            return {"id": aid, "status": "declined", "detail": "user declined"}
    log("installing " + aid)
    proc = subprocess.run(action["cmd"], text=True)
    return {"id": aid, "status": "installed" if proc.returncode == 0 else "failed",
            "detail": f"exit {proc.returncode}"}


def download_fonts() -> dict:
    target = fonts_dir(ROOT)
    target.mkdir(parents=True, exist_ok=True)
    ok, failed = [], []
    for name, url in FONT_URLS.items():
        dest = target / name
        if dest.is_file() and dest.stat().st_size > 1000:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "video-vfx-editor"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if len(data) < 1000:
                raise ValueError("short download")
            dest.write_bytes(data)
            ok.append(name)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}: {exc}")
    return {"id": "fonts", "status": "installed" if ok else "failed",
            "detail": f"downloaded {ok}" if ok else "; ".join(failed)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install only missing video-vfx-editor capabilities")
    add_common(parser)
    parser.add_argument("--check", action="store_true", help="read-only (default)")
    parser.add_argument("--install", action="store_true", help="install missing items")
    parser.add_argument("--yes", action="store_true", help="non-interactive")
    parser.add_argument("--fonts", action="store_true", help="download fonts only")
    parser.add_argument("--models", action="store_true", help="pre-download whisper model")
    args = parser.parse_args(argv)
    with stage("ensure", args) as run:
        read_only = not (args.install or args.fonts or args.models)
        caps = capabilities(ROOT, refresh=args.refresh, cache_write=not read_only)
        actions = plan_actions(caps)
        results = []
        if args.fonts:
            results.append(download_fonts())
        if args.models:
            results.append(predownload_model())
        if args.install and not args.fonts and not args.models:
            for action in actions:
                results.append(run_action(action, args.yes))
        if not args.json:
            print(f"platform: {os_name()} | ffmpeg: {caps['ffmpeg']['path'] or 'missing'} | node: {caps['node']['version'] or 'missing'}")
            for a in actions:
                print(f"  missing: {a['id']:<16} {a['detail']}")
                print(f"           cmd: {' '.join(a['cmd'])}")
            for r in results:
                print(f"  {r['status']:<9} {r['id']}: {r.get('detail')}")
            if not actions:
                print("everything required is already installed — nothing to do")
        run.add_check("preflight", "pass" if (not actions or args.install) else "warn",
                      f"{len(actions)} missing", "0 missing")
        run.output = ",".join(a["id"] for a in actions) or "none"
        if args.json:
            run.artifacts = []
        run.next_cmd = ("python scripts/intake.py --ask" if not actions
                        else "python install/ensure.py --install --yes")
    return 0


def predownload_model() -> dict:
    code = (
        "from faster_whisper import WhisperModel\n"
        "WhisperModel('small', device='cpu', compute_type='int8')\n"
        "print('ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], text=True)
    return {"id": "whisper-small", "status": "installed" if proc.returncode == 0 else "failed",
            "detail": f"exit {proc.returncode}"}


if __name__ == "__main__":
    sys.exit(main())
