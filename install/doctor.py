#!/usr/bin/env python3
"""Capability report: what works, what is missing, and the exact fix per OS.

    python install/doctor.py
    python install/doctor.py --json
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _caps import (capabilities, fonts_dir, python_supported,  # noqa: E402
                   resolve_device, venv_python)
from _contract import add_common, stage  # noqa: E402

FIX = {
    "ffmpeg": "run: python install/ensure.py --install --yes (Windows: portable FFmpeg into ~/.vfe/bin, SHA-256 verified) | macOS: brew install ffmpeg | Linux: sudo apt install ffmpeg",
    "libass": "macOS: brew install ffmpeg-full && export PATH=\"$(brew --prefix ffmpeg-full)/bin:$PATH\" | Windows: python install/ensure.py --install --yes",
    "ffprobe": "ships with FFmpeg; install a full build",
    "python": "run: python install/ensure.py --install --yes (provisions CPython 3.12.16 user-locally, no admin)",
    "node": "run: python install/ensure.py --install --yes (Windows: portable Node 22) | macOS: brew install node@22 | no-admin: nvm install 22",
    "npm": "npm ships with Node; reinstall Node",
    "chrome": "install Chrome/Edge, or npm i -g puppeteer (motion graphics only)",
    "yt_dlp": "python -m pip install --user -U yt-dlp",
    "fonts": "python install/ensure.py --install --fonts",
    "models": "python install/ensure.py --install --models",
    "gpu": "optional: install a CUDA build of torch; CPU editing works without it",
    "zscale": "install a full FFmpeg build with zimg (Gyan full / ffmpeg-full)",
}


def build_report(caps: dict) -> list:
    checks = []

    def add(cid, ok, value, target, fix, required=True):
        checks.append({
            "id": cid,
            "status": "pass" if ok else ("fail" if required else "warn"),
            "value": value,
            "target": target,
            "fix": None if ok else fix,
        })

    ff = caps["ffmpeg"]
    add("ffmpeg", ff["present"], ff["path"] or "missing", "on PATH", FIX["ffmpeg"])
    add("ffmpeg:libass", ff["has_libass"], "subtitles filter", "present", FIX["libass"])
    add("ffmpeg:zscale", ff["has_zscale"], "zscale filter", "present", FIX["zscale"], required=False)
    add("ffprobe", caps["ffprobe"]["present"], caps["ffprobe"]["path"] or "missing", "on PATH", FIX["ffprobe"])
    py = caps["python"]
    add("python", py["ok"] and python_supported(), py["version"], "3.11-3.13 (3.12.16 pinned)", FIX["python"])
    node = caps["node"]
    add("node", node["ok"], node["version"] or "missing", ">= 20 (22 preferred)", FIX["node"], required=False)
    add("npm", caps["npm"]["present"], caps["npm"]["path"] or "missing", "on PATH", FIX["npm"], required=False)
    add("chrome", bool(caps["chrome"]["path"]), caps["chrome"]["path"] or "missing",
        "Chrome/Edge for motion", FIX["chrome"], required=False)
    ytdlp = caps["yt_dlp"]
    add("yt-dlp", ytdlp["present"], ytdlp["path"] or ("python module" if ytdlp["present"] else "missing"),
        "for URL ingest", FIX["yt_dlp"], required=False)
    fonts = caps["fonts"]
    add("fonts:devanagari", fonts["devanagari"], fonts["count"], "Devanagari font installed", FIX["fonts"], required=False)
    models = caps["models"]
    add("models:whisper", models["whisper"], models["entries"][:3], "whisper model cached", FIX["models"], required=False)
    add("models:rvm", models["rvm"], "rvm" if models["rvm"] else "absent", "for person matte",
        "python -m pip install --user rvm-onnx or run scripts/matte.py --backend birefnet", required=False)
    gpu = caps["gpu"]
    add("gpu", gpu["cuda"] or gpu["mps"],
        "cuda" if gpu["cuda"] else ("mps" if gpu["mps"] else "cpu only"),
        "optional acceleration", FIX["gpu"], required=False)
    pkgs = caps["packages"]
    for pkg, target in (("numpy", "numpy"), ("cv2", "opencv-python-headless"), ("PIL", "pillow"),
                        ("faster_whisper", "faster-whisper"), ("rembg", "rembg"), ("onnxruntime", "onnxruntime")):
        add(f"py:{pkg}", bool(pkgs.get(pkg)), "installed" if pkgs.get(pkg) else "missing", target,
            f"python -m pip install --user {target}", required=False)
    return checks


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Report video-vfx-editor capabilities and fixes")
    add_common(parser)
    args = parser.parse_args(argv)
    # Report the runtime the installer provisioned, not the OS default.
    if not python_supported() and venv_python().is_file() and os.environ.get("VFE_BOOTSTRAPPED") != "1":
        env = dict(os.environ, VFE_BOOTSTRAPPED="1")
        return subprocess.run([str(venv_python()), str(Path(__file__).resolve()), *sys.argv[1:]],
                              env=env).returncode
    with stage("doctor", args) as run:
        caps = capabilities()
        checks = build_report(caps)
        for c in checks:
            run.add_check(c["id"], c["status"], c["value"], c["target"])
        run.device = resolve_device(args.device, caps)
        run.output = str(fonts_dir(ROOT))
        if not args.json:
            print(f"video-vfx-editor doctor — {caps['platform']} / python {caps['python']['version']} / device {run.device}")
            print(f"interpreter: {caps['python']['path']}")
            print("-" * 78)
            for c in checks:
                mark = "PASS" if c["status"] == "pass" else ("FAIL" if c["status"] == "fail" else "WARN")
                print(f"{mark:4} {c['id']:<20} {str(c['value'])[:32]:<34} {c['target']}")
                if c["fix"]:
                    print(f"     fix: {c['fix']}")
        run.next_cmd = "python install/ensure.py --check --json"
    return 0


if __name__ == "__main__":
    sys.exit(main())
