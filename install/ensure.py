#!/usr/bin/env python3
"""Preflight: check -> provision -> install only what is missing.

    python install/ensure.py --check          # read-only table
    python install/ensure.py --install --yes  # install missing, no prompts
    python install/ensure.py --fonts          # fonts only
    python install/ensure.py --models         # pre-download the whisper model

Everything this installs is user-local (~/.vfe): no admin, no sudo, no PATH edits.
If the running Python is outside 3.11-3.13 it provisions CPython 3.12.16 with uv
and re-runs itself inside that environment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _caps import (VFE, capabilities, fonts_dir, os_name,  # noqa: E402
                   python_supported, venv_python)
from _contract import SkillError, add_common, log, stage  # noqa: E402

PIN_PYTHON = "3.12.16"
FFMPEG_WIN_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
NODE_INDEX = "https://nodejs.org/dist/index.json"
UV_RELEASE = "https://github.com/astral-sh/uv/releases/latest/download/"

FONT_URLS = {
    "NotoSansDevanagari.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/notosansdevanagari/NotoSansDevanagari%5Bwdth%2Cwght%5D.ttf",
    "Inter.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
    "NotoSans.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/notosans/NotoSans%5Bwdth%2Cwght%5D.ttf",
}

PIP_PACKAGES = [
    "numpy", "opencv-python-headless<5", "pillow", "yt-dlp",  # cv2 5 dropped CascadeClassifier
    "faster-whisper",          # ASR
    "rembg", "onnxruntime",    # person matte
]


# --------------------------------------------------------------------------
# downloads
# --------------------------------------------------------------------------
def _download(url: str, dest: Path, timeout: int = 600) -> Path:
    if not url.startswith("https://"):
        raise RuntimeError(f"refusing non-HTTPS download: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "video-vfx-editor"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    if dest.stat().st_size < 4096:
        raise RuntimeError(f"download too small: {url}")
    return dest


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "video-vfx-editor"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def _sha256(path: Path) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _exec(cmd, *extra, timeout: int = 1800, env: dict | None = None) -> int:
    argv = [*cmd, *extra]
    log(" ".join(str(c) for c in argv))
    return subprocess.run([str(c) for c in argv], text=True, timeout=timeout, env=env).returncode


# --------------------------------------------------------------------------
# uv + CPython
# --------------------------------------------------------------------------
def uv_url() -> str:
    arm = platform.machine().lower() in ("arm64", "aarch64")
    if os_name() == "windows":
        return UV_RELEASE + ("uv-aarch64-pc-windows-msvc.zip" if arm else "uv-x86_64-pc-windows-msvc.zip")
    if os_name() == "macos":
        return UV_RELEASE + ("uv-aarch64-apple-darwin.tar.gz" if arm else "uv-x86_64-apple-darwin.tar.gz")
    return UV_RELEASE + ("uv-aarch64-unknown-linux-gnu.tar.gz" if arm else "uv-x86_64-unknown-linux-gnu.tar.gz")


def ensure_uv() -> Path:
    dest = VFE / "bin" / ("uv.exe" if os_name() == "windows" else "uv")
    if dest.is_file():
        return dest
    if shutil.which("uv"):
        return Path(shutil.which("uv"))
    url = uv_url()
    with tempfile.TemporaryDirectory() as td:
        archive = _download(url, Path(td) / url.rsplit("/", 1)[-1])
        if archive.suffix == ".zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(td)
        else:
            import tarfile

            with tarfile.open(archive) as tf:
                tf.extractall(td, filter="data")
        src = next(p for p in Path(td).rglob("uv*") if p.is_file() and p.name in ("uv", "uv.exe"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        dest.chmod(0o755)
    return dest


def bootstrap_python() -> Path:
    """Install CPython 3.12.16 + a seeded venv under ~/.vfe (user-local)."""
    uv = ensure_uv()
    env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(VFE / "python"))
    rc = _exec([uv, "python", "install", PIN_PYTHON, "--no-bin"], env=env)
    if rc == 0 and not venv_python().is_file():
        rc = _exec([uv, "venv", "--python", PIN_PYTHON, "--seed", str(VFE / "venv")], env=env)
    if rc != 0:
        raise RuntimeError(f"uv could not provision CPython {PIN_PYTHON} (exit {rc})")
    return venv_python()


# --------------------------------------------------------------------------
# portable tools
# --------------------------------------------------------------------------
def ensure_ffmpeg() -> Path:
    """Windows: portable FFmpeg essentials build, SHA-256 verified, into ~/.vfe/bin."""
    bin_dir = VFE / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    expected = _fetch_text(FFMPEG_WIN_URL + ".sha256").split()[0].lower()
    with tempfile.TemporaryDirectory() as td:
        archive = _download(FFMPEG_WIN_URL, Path(td) / "ffmpeg.zip")
        actual = _sha256(archive)
        if actual != expected:
            raise RuntimeError(f"FFmpeg checksum mismatch: expected {expected}, got {actual}")
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(td)
        for name in ("ffmpeg", "ffprobe", "ffplay"):
            shutil.copy2(next(Path(td).rglob(name + ".exe")), bin_dir / (name + ".exe"))
    return bin_dir


def node_local() -> Path | None:
    exe = VFE / "node" / ("node.exe" if os_name() == "windows" else "bin/node")
    return exe if exe.is_file() else None


def latest_node_lts() -> str:
    for row in json.loads(_fetch_text(NODE_INDEX)):
        version = str(row.get("version", "")).lstrip("v")
        if version.startswith("22.") and row.get("lts"):
            return version
    raise RuntimeError("no Node 22 LTS release found")


def ensure_node() -> Path:
    """Windows: portable Node 22 LTS zip into ~/.vfe/node (no MSI, no admin)."""
    if node_local():
        return node_local()
    version = latest_node_lts()
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    dest = VFE / "node"
    with tempfile.TemporaryDirectory() as td:
        archive = _download(f"https://nodejs.org/dist/v{version}/node-v{version}-win-{arch}.zip",
                            Path(td) / "node.zip")
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(td)
        shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(next(p for p in Path(td).glob("node-v*") if p.is_dir())), dest)
    return dest


def chrome_cached() -> bool:
    cache = Path(os.environ.get("PUPPETEER_CACHE_DIR") or Path.home() / ".cache" / "puppeteer")
    exe = "chrome.exe" if os_name() == "windows" else "chrome"
    return cache.is_dir() and next(cache.rglob(exe), None) is not None


def _puppeteer_dir(node: str) -> Path | None:
    # C:\.nodejs may be a shim; ask node where it really lives
    out = subprocess.run([str(node), "-p", "process.execPath"], capture_output=True,
                         text=True, timeout=30).stdout.strip()
    pkg = Path(out or node).resolve().parent / "node_modules" / "puppeteer"
    return pkg if pkg.is_dir() else None


def install_puppeteer(caps: dict) -> str:
    node = caps.get("node", {}).get("path") or (str(node_local()) if node_local() else None)
    if not node:
        raise RuntimeError("Node is missing; cannot install puppeteer")
    base = Path(node).resolve().parent
    npm_cli = next((p for p in (base / "node_modules/npm/bin/npm-cli.js",
                                base / "lib/node_modules/npm/bin/npm-cli.js") if p.is_file()), None)
    npm = [node, str(npm_cli)] if npm_cli else [shutil.which("npm") or "npm"]
    # npm >= 12 skips postinstall scripts unless allow-listed, and puppeteer's
    # postinstall is what downloads Chrome.
    rc = _exec(npm, "install", "-g", "puppeteer", "--no-audit", "--no-fund", "--allow-scripts=puppeteer")
    if rc != 0:
        raise RuntimeError(f"npm install -g puppeteer failed (exit {rc})")
    pkg = _puppeteer_dir(node)
    if not chrome_cached() and pkg and (pkg / "install.mjs").is_file():
        rc = _exec([node, str(pkg / "install.mjs")])
        if rc != 0:
            raise RuntimeError(f"puppeteer Chrome download failed (exit {rc})")
    if not chrome_cached():
        raise RuntimeError("puppeteer installed but Chrome is missing; run: npx puppeteer browsers install chrome")
    return "npm -g puppeteer"


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------
def _pip_has(spec: str) -> bool:
    import importlib.util

    name = spec.split("<")[0].strip()
    mod = {"opencv-python-headless": "cv2", "pillow": "PIL", "faster-whisper": "faster_whisper",
           "yt-dlp": "yt_dlp"}.get(name, name.replace("-", "_"))
    if importlib.util.find_spec(mod) is None:
        return False
    if "<5" in spec:
        import cv2

        return int(cv2.__version__.split(".")[0]) < 5
    return True


def _puppeteer_installed(caps: dict) -> bool:
    node = caps.get("node", {}).get("path")
    return bool(node and _puppeteer_dir(node) and chrome_cached())


def _local(aid: str, detail: str, handler) -> dict:
    return {"id": aid, "detail": detail, "handler": handler}


def _system(aid: str, detail: str, cmd: list, manual: str | None = None) -> dict:
    return {"id": aid, "detail": detail, "cmd": cmd, "system": True, "manual": manual}


def plan_actions(caps: dict) -> list:
    osname = os_name()
    actions = []
    if not python_supported():
        actions.append(_local("python", f"Python {sys.version.split()[0]} has no wheels; provisions "
                                        f"CPython {PIN_PYTHON} + venv in ~/.vfe (user-local)", bootstrap_python))

    ff = caps["ffmpeg"]
    if not ff["present"] or not ff["has_libass"]:
        if osname == "windows":
            actions.append(_local("ffmpeg-portable", "portable FFmpeg with libass/zscale into "
                                                     "~/.vfe/bin (SHA-256 verified)", ensure_ffmpeg))
        else:
            actions.append(_system("ffmpeg", "FFmpeg with libass/zscale is required for captions and HDR-safe scaling",
                                   ["brew", "install", "ffmpeg"] if osname == "macos"
                                   else ["apt-get", "install", "-y", "ffmpeg"],
                                   "Linux: run 'sudo apt install ffmpeg' yourself (this tool never uses sudo)"))

    node = caps["node"]
    if not node["ok"]:
        if osname == "windows":
            actions.append(_local("node-portable", "portable Node 22 LTS into ~/.vfe/node (no MSI, no admin)",
                                  ensure_node))
        else:
            actions.append(_system("node", "Node >= 20 (22 preferred) runs the HyperFrames motion bridge",
                                   ["brew", "install", "node@22"] if osname == "macos" else ["nvm", "install", "22"],
                                   "no-admin fallback: install nvm/fnm, then 'nvm install 22'"))

    missing_pip = [p for p in PIP_PACKAGES if not _pip_has(p)]
    if missing_pip:
        venv = sys.prefix != sys.base_prefix
        actions.append({
            "id": "python-packages",
            "detail": ("venv" if venv else "user site") + " pip packages: " + ", ".join(missing_pip),
            "cmd": [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                    "--no-input", *([] if venv else ["--user"]), *missing_pip],
        })

    if (node["ok"] or osname == "windows") and not _puppeteer_installed(caps):
        actions.append(_local("puppeteer", "global puppeteer + bundled Chrome (motion graphics)",
                              lambda: install_puppeteer(caps)))

    if not caps["fonts"]["devanagari"]:
        actions.append(_local("fonts", "OFL Devanagari + Latin fonts into " + str(fonts_dir(ROOT)),
                              download_fonts))
    return actions


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
def run_action(action: dict, yes: bool) -> dict:
    aid = action["id"]
    try:
        if "handler" in action:
            return {"id": aid, "status": "installed", "detail": str(action["handler"]())}
        cmd = action["cmd"]
        if action.get("system"):
            if cmd[0] in ("apt-get", "nvm") or shutil.which(cmd[0]) is None:
                return {"id": aid, "status": "skipped",
                        "detail": (action.get("manual") or f"{cmd[0]} is not on PATH").strip()}
            if not yes and input(f"Install {aid} with: {' '.join(cmd)}\nProceed? [y/N] ").lower() not in ("y", "yes"):
                return {"id": aid, "status": "declined", "detail": "user declined"}
        rc = _exec(cmd)
        return {"id": aid, "status": "installed" if rc == 0 else "failed", "detail": f"exit {rc}"}
    except Exception as exc:  # noqa: BLE001 - one failed item must not abort the rest
        return {"id": aid, "status": "failed", "detail": str(exc)}


def download_fonts() -> str:
    target = fonts_dir(ROOT)
    target.mkdir(parents=True, exist_ok=True)
    ok, failed = [], []
    for name, url in FONT_URLS.items():
        dest = target / name
        if dest.is_file() and dest.stat().st_size > 1000:
            continue
        try:
            _download(url, dest, timeout=60)
            ok.append(name)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{name}: {exc}")
    if failed and not ok:
        raise RuntimeError("; ".join(failed))
    return f"downloaded {ok}" if ok else "already present"


def predownload_model() -> str:
    model = os.environ.get("VFE_WHISPER_MODEL", "small")
    code = ("from faster_whisper import WhisperModel\n"
            f"WhisperModel({model!r}, device='cpu', compute_type='int8')\n"
            "print('ok')\n")
    rc = _exec([sys.executable, "-c", code])
    if rc != 0:
        raise RuntimeError(f"whisper model download failed (exit {rc})")
    return f"{model} cached"


def _result(aid: str, fn) -> dict:
    try:
        return {"id": aid, "status": "installed", "detail": fn()}
    except Exception as exc:  # noqa: BLE001
        return {"id": aid, "status": "failed", "detail": str(exc)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install only missing video-vfx-editor capabilities")
    add_common(parser)
    parser.add_argument("--check", action="store_true", help="read-only (default)")
    parser.add_argument("--install", action="store_true", help="install missing items")
    parser.add_argument("--yes", action="store_true", help="non-interactive")
    parser.add_argument("--fonts", action="store_true", help="download fonts only")
    parser.add_argument("--models", action="store_true", help="pre-download whisper model")
    args = parser.parse_args(argv)

    if not python_supported() and os.environ.get("VFE_BOOTSTRAPPED") != "1":
        try:
            py = venv_python() if venv_python().is_file() or not args.install else bootstrap_python()
        except Exception as exc:  # noqa: BLE001
            print(f"python bootstrap failed: {exc}", file=sys.stderr)
            return 5
        if py.is_file():
            log(f"re-running inside {py}")
            return subprocess.run([str(py), str(Path(__file__).resolve()), *sys.argv[1:]],
                                  env=dict(os.environ, VFE_BOOTSTRAPPED="1")).returncode

    with stage("ensure", args) as run:
        caps = capabilities()
        actions = plan_actions(caps)
        results = []
        if args.fonts:
            results.append(_result("fonts", download_fonts))
        if args.models:
            results.append(_result("whisper", predownload_model))
        if args.install:
            results.extend(run_action(a, args.yes) for a in actions)
            caps = capabilities()

        if not args.json:
            print(f"platform: {os_name()} | ffmpeg: {caps['ffmpeg']['path'] or 'missing'} | "
                  f"node: {caps['node']['version'] or 'missing'} | python: {caps['python']['version']}")
            for a in actions:
                print(f"  planned: {a['id']:<16} {a['detail']}")
            for r in results:
                print(f"  {r['status']:<9} {r['id']}: {r['detail']}")
            if not actions:
                print("everything required is already installed — nothing to do")
            if venv_python().is_file():
                print(f"interpreter for scripts: {venv_python()}")

        failed = [r for r in results if r["status"] == "failed"]
        if failed:
            run.fail(SkillError("; ".join(f"{r['id']}: {r['detail']}" for r in failed),
                                fix="re-run: python install/ensure.py --install --yes, or install that item manually",
                                retryable=True))
        remaining = plan_actions(caps)
        run.add_check("preflight", "fail" if failed else ("pass" if not remaining else "warn"),
                      f"{len(remaining)} missing", "0 missing")
        run.output = ", ".join(r["id"] for r in results) or "none"
        run.next_cmd = (f'"{venv_python()}" scripts/intake.py --ask' if venv_python().is_file()
                        else "python scripts/intake.py --ask")
    return 0


if __name__ == "__main__":
    sys.exit(main())
