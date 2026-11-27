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

from _caps import capabilities, fonts_dir  # noqa: E402
from _contract import add_common, log, stage  # noqa: E402

PIN_PYTHON = "3.12.16"
PYTHON_RANGE = ((3, 11), (3, 14))  # >= 3.11 and < 3.14; packages ship wheels here

VFE = Path.home() / ".vfe"
VENV = VFE / "venv"
UV_INSTALL_DIR = VFE / "python"
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


def os_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os_name() == "windows" else "bin/python")


def python_supported(version=None) -> bool:
    v = version or sys.version_info
    return PYTHON_RANGE[0] <= (v[0], v[1]) < PYTHON_RANGE[1]


# --------------------------------------------------------------------------
# downloads (HTTPS only, size floor, SHA-256 where the vendor publishes one)
# --------------------------------------------------------------------------
def _download(url: str, dest: Path, timeout: int = 600, min_bytes: int = 4096) -> Path:
    if not url.startswith("https://"):
        raise RuntimeError(f"refusing non-HTTPS download: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "video-vfx-editor"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    if dest.stat().st_size < min_bytes:
        raise RuntimeError(f"download too small: {url}")
    return dest


def _fetch_text(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "video-vfx-editor"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _exec(cmd, env=None, timeout: int = 1800) -> subprocess.CompletedProcess:
    log(" ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], text=True, env=env, timeout=timeout)


# --------------------------------------------------------------------------
# uv + CPython
# --------------------------------------------------------------------------
def uv_url() -> str:
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if os_name() == "windows":
        return UV_RELEASE + ("uv-aarch64-pc-windows-msvc.zip" if arm else "uv-x86_64-pc-windows-msvc.zip")
    if os_name() == "macos":
        return UV_RELEASE + ("uv-aarch64-apple-darwin.tar.gz" if arm else "uv-x86_64-apple-darwin.tar.gz")
    return UV_RELEASE + ("uv-aarch64-unknown-linux-gnu.tar.gz" if arm else "uv-x86_64-unknown-linux-gnu.tar.gz")


def uv_bin() -> Path | None:
    local = VFE / "bin" / ("uv.exe" if os_name() == "windows" else "uv")
    if local.is_file():
        return local
    found = shutil.which("uv")
    return Path(found) if found else None


def ensure_uv() -> Path:
    found = uv_bin()
    if found:
        return found
    (VFE / "bin").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        name = uv_url().rsplit("/", 1)[-1]
        archive = Path(td) / name
        _download(uv_url(), archive)
        if name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(td)
        else:
            import tarfile

            with tarfile.open(archive) as tf:
                tf.extractall(td, filter="data")
        src = next(p for p in Path(td).rglob("uv*") if p.is_file() and p.name in ("uv", "uv.exe"))
        dest = VFE / "bin" / src.name
        shutil.copy2(src, dest)
        dest.chmod(0o755)
    return dest


def bootstrap_python() -> Path:
    """Install CPython 3.12.16 + a seeded venv under ~/.vfe (user-local)."""
    uv = ensure_uv()
    env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(UV_INSTALL_DIR))
    proc = _exec([uv, "python", "install", PIN_PYTHON, "--no-bin"], env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"uv python install failed (exit {proc.returncode})")
    if not venv_python().is_file():
        proc = _exec([uv, "venv", "--python", PIN_PYTHON, "--seed", str(VENV)], env=env)
        if proc.returncode != 0:
            raise RuntimeError(f"uv venv failed (exit {proc.returncode})")
    return venv_python()


# --------------------------------------------------------------------------
# portable tools
# --------------------------------------------------------------------------
def ensure_ffmpeg() -> None:
    """Windows: signed-CDN FFmpeg essentials build, SHA-256 verified, into ~/.vfe/bin."""
    bin_dir = VFE / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / "ffmpeg.zip"
        sums = Path(td) / "ffmpeg.sha256"
        _download(FFMPEG_WIN_URL, archive)
        _download(FFMPEG_WIN_URL + ".sha256", sums, min_bytes=32)
        expected = sums.read_text(encoding="utf-8", errors="replace").split()[0].lower()
        actual = _sha256(archive)
        if expected != actual:
            raise RuntimeError(f"FFmpeg checksum mismatch: expected {expected}, got {actual}")
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(td)
        for name in ("ffmpeg", "ffprobe", "ffplay"):
            src = next(Path(td).rglob(name + ".exe"))
            shutil.copy2(src, bin_dir / (name + ".exe"))


def node_local() -> Path | None:
    exe = VFE / "node" / ("node.exe" if os_name() == "windows" else "bin/node")
    return exe if exe.is_file() else None


def latest_node_lts(major: int = 22) -> str:
    for row in json.loads(_fetch_text(NODE_INDEX)):
        version = str(row.get("version", "")).lstrip("v")
        if version.startswith(f"{major}.") and row.get("lts"):
            return version
    raise RuntimeError(f"no Node {major} LTS release found")


def ensure_node() -> None:
    """Windows: portable Node 22 LTS zip into ~/.vfe/node (no MSI, no admin)."""
    if node_local():
        return
    version = latest_node_lts()
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    url = f"https://nodejs.org/dist/v{version}/node-v{version}-win-{arch}.zip"
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / "node.zip"
        _download(url, archive)
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(td)
        extracted = next(p for p in Path(td).glob("node-v*") if p.is_dir())
        dest = VFE / "node"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(extracted), dest)


def chrome_cached() -> bool:
    cache = Path(os.environ.get("PUPPETEER_CACHE_DIR", Path.home() / ".cache" / "puppeteer"))
    return cache.is_dir() and any(cache.rglob("chrome.exe")) if os_name() == "windows" \
        else cache.is_dir() and any(cache.rglob("chrome"))


def _puppeteer_dir(node: str) -> Path | None:
    base = Path(node).resolve().parent
    try:  # C:\.nodejs may be a shim; ask node where it really lives
        out = subprocess.run([str(node), "-p", "process.execPath"], capture_output=True,
                             text=True, timeout=30).stdout.strip()
        if out:
            base = Path(out).parent
    except (OSError, subprocess.SubprocessError):
        pass
    for cand in (base / "node_modules" / "puppeteer", base.parent / "node_modules" / "puppeteer"):
        if cand.is_dir():
            return cand
    return None


def install_puppeteer(caps: dict) -> None:
    node = caps.get("node", {}).get("path") or (str(node_local()) if node_local() else None)
    if not node:
        raise RuntimeError("Node is missing; cannot install puppeteer")
    base = Path(node).resolve().parent
    npm_cli = next((p for p in (base / "node_modules/npm/bin/npm-cli.js",
                                base / "lib/node_modules/npm/bin/npm-cli.js") if p.is_file()), None)
    cmd = ([node, str(npm_cli)] if npm_cli else [shutil.which("npm") or "npm"])
    # npm >= 12 skips postinstall scripts unless the package is allow-listed, and
    # puppeteer's postinstall is what downloads Chrome.
    proc = _exec([*cmd, "install", "-g", "puppeteer", "--no-audit", "--no-fund",
                  "--allow-scripts=puppeteer"], timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(f"npm install -g puppeteer failed (exit {proc.returncode})")
    if chrome_cached():
        return
    pkg = _puppeteer_dir(node)
    if pkg and (pkg / "install.mjs").is_file():
        proc = _exec([node, str(pkg / "install.mjs")], timeout=1800)
        if proc.returncode != 0:
            raise RuntimeError(f"puppeteer Chrome download failed (exit {proc.returncode})")
    if not chrome_cached():
        raise RuntimeError("puppeteer installed but Chrome is missing; run: npx puppeteer browsers install chrome")


# --------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------
def _pip_has(spec: str) -> bool:
    import importlib.util

    name = spec.split("<")[0].split(">")[0].split("=")[0].split("!")[0].strip()
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
    if not node:
        return False
    return _puppeteer_dir(node) is not None and chrome_cached()


def plan_actions(caps: dict) -> list:
    osname = os_name()
    actions = []

    if not python_supported():
        actions.append({
            "id": "python", "system": False, "cmd": ["uv", "python", "install", PIN_PYTHON],
            "detail": f"Python {sys.version.split()[0]} has no wheels; provisions CPython "
                      f"{PIN_PYTHON} + venv in ~/.vfe (user-local)",
            "manual": None,
        })

    ff = caps["ffmpeg"]
    if not ff["present"] or not ff["has_libass"]:
        if osname == "windows":
            actions.append({
                "id": "ffmpeg-portable", "system": False, "cmd": [FFMPEG_WIN_URL],
                "detail": "portable FFmpeg with libass/zscale into ~/.vfe/bin (SHA-256 verified)",
                "manual": None,
            })
        else:
            cmd = ["brew", "install", "ffmpeg"] if osname == "macos" else ["apt-get", "install", "-y", "ffmpeg"]
            actions.append({
                "id": "ffmpeg", "system": True, "cmd": cmd,
                "detail": "FFmpeg with libass/zscale is required for captions and HDR-safe scaling",
                "manual": "Linux: run 'sudo apt install ffmpeg' yourself (this tool never uses sudo)",
            })

    node = caps["node"]
    if not node["ok"]:
        if osname == "windows":
            actions.append({
                "id": "node-portable", "system": False, "cmd": ["node", "22 LTS"],
                "detail": "portable Node 22 LTS into ~/.vfe/node (no MSI, no admin)",
                "manual": None,
            })
        else:
            cmd = ["brew", "install", "node@22"] if osname == "macos" else ["nvm", "install", "22"]
            actions.append({
                "id": "node", "system": True, "cmd": cmd,
                "detail": "Node >= 20 (22 preferred) runs the HyperFrames motion bridge",
                "manual": "no-admin fallback: install nvm/fnm, then 'nvm install 22'",
            })

    missing_pip = [p for p in PIP_PACKAGES if not _pip_has(p)]
    if missing_pip:
        venv = sys.prefix != sys.base_prefix
        actions.append({
            "id": "python-packages", "system": False,
            "cmd": [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                    "--no-input", *([] if venv else ["--user"]), *missing_pip],
            "detail": ("venv" if venv else "user site") + " pip packages: " + ", ".join(missing_pip),
            "manual": None,
        })

    if (node["ok"] or osname == "windows") and not _puppeteer_installed(caps):
        actions.append({
            "id": "puppeteer", "system": False, "cmd": ["npm", "install", "-g", "puppeteer"],
            "detail": "global puppeteer + bundled Chrome (motion graphics)",
            "manual": None,
        })

    if not caps["fonts"]["devanagari"]:
        actions.append({
            "id": "fonts", "system": False, "cmd": ["<download>"],
            "detail": "OFL Devanagari + Latin fonts into " + str(fonts_dir(ROOT)),
            "manual": None,
        })
    return actions


# --------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------
def run_action(action: dict, yes: bool) -> dict:
    aid = action["id"]
    try:
        if aid == "python":
            py = bootstrap_python()
            return {"id": aid, "status": "installed", "detail": str(py)}
        if aid == "ffmpeg-portable":
            ensure_ffmpeg()
            return {"id": aid, "status": "installed", "detail": str(VFE / "bin")}
        if aid == "node-portable":
            ensure_node()
            return {"id": aid, "status": "installed", "detail": str(VFE / "node")}
        if aid == "puppeteer":
            install_puppeteer(capabilities(ROOT, refresh=True))
            return {"id": aid, "status": "installed", "detail": "npm -g puppeteer"}
        if aid == "fonts":
            return download_fonts()
        if action["system"]:
            if action["cmd"][0] in ("apt-get", "nvm"):
                return {"id": aid, "status": "skipped", "detail": action["manual"] or "manual install required"}
            if shutil.which(action["cmd"][0]) is None:
                return {"id": aid, "status": "skipped",
                        "detail": f"{action['cmd'][0]} not on PATH. {action['manual'] or ''}".strip()}
            if not yes:
                answer = input(f"Install {aid} with: {' '.join(action['cmd'])}\nProceed? [y/N] ").strip().lower()
                if answer not in ("y", "yes"):
                    return {"id": aid, "status": "declined", "detail": "user declined"}
        proc = _exec(action["cmd"])
        return {"id": aid, "status": "installed" if proc.returncode == 0 else "failed",
                "detail": f"exit {proc.returncode}"}
    except Exception as exc:  # noqa: BLE001 - one failed item must not abort the rest
        return {"id": aid, "status": "failed", "detail": str(exc)}


def download_fonts() -> dict:
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
    return {"id": "fonts", "status": "installed" if ok else "failed",
            "detail": f"downloaded {ok}" if ok else "; ".join(failed)}


def predownload_model() -> dict:
    model = os.environ.get("VFE_WHISPER_MODEL", "small")
    code = (
        "import os\n"
        "from faster_whisper import WhisperModel\n"
        f"WhisperModel({model!r}, device='cpu', compute_type='int8')\n"
        "print('ok')\n"
    )
    proc = _exec([sys.executable, "-c", code])
    return {"id": f"whisper-{model}", "status": "installed" if proc.returncode == 0 else "failed",
            "detail": f"exit {proc.returncode}"}


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
        py = venv_python() if venv_python().is_file() else None
        if py is None and args.install:
            try:
                py = bootstrap_python()
            except Exception as exc:  # noqa: BLE001
                print(f"python bootstrap failed: {exc}", file=sys.stderr)
                return 5
        if py is not None:
            log(f"re-running inside {py}")
            env = dict(os.environ, VFE_BOOTSTRAPPED="1")
            return subprocess.run([str(py), str(Path(__file__).resolve()), *sys.argv[1:]], env=env).returncode

    with stage("ensure", args) as run:
        read_only = not (args.install or args.fonts or args.models)
        # Never plan an install from the cache: it may describe a runtime we just removed.
        caps = capabilities(ROOT, refresh=args.install or args.refresh, cache_write=not read_only)
        actions = plan_actions(caps)
        results = []
        if args.fonts:
            results.append(download_fonts())
        if args.models:
            results.append(predownload_model())
        if args.install:
            for action in actions:
                results.append(run_action(action, args.yes))
            caps = capabilities(ROOT, refresh=True)

        failed = [r for r in results if r["status"] == "failed"]
        if failed:
            from _contract import SkillError

            run.fail(SkillError(
                "; ".join(f"{r['id']}: {r['detail']}" for r in failed),
                fix="re-run: python install/ensure.py --install --yes, or install that item manually",
                retryable=True,
            ))
        if not args.json:
            print(f"platform: {os_name()} | ffmpeg: {caps['ffmpeg']['path'] or 'missing'} | "
                  f"node: {caps['node']['version'] or 'missing'} | python: {caps['python']['version']}")
            for a in actions:
                print(f"  planned: {a['id']:<16} {a['detail']}")
                print(f"           cmd: {' '.join(a['cmd'])}")
            for r in results:
                print(f"  {r['status']:<9} {r['id']}: {r.get('detail')}")
            if not actions:
                print("everything required is already installed — nothing to do")
            if venv_python().is_file():
                print(f"interpreter for scripts: {venv_python()}")
        remaining = plan_actions(caps)
        run.add_check("preflight",
                      "pass" if not remaining else ("fail" if failed else "warn"),
                      f"{len(remaining)} missing", "0 missing")
        run.output = ", ".join(r["id"] for r in results) or "none"
        run.next_cmd = (f'"{venv_python()}" scripts/intake.py --ask' if venv_python().is_file()
                        else "python scripts/intake.py --ask")
    return 0


if __name__ == "__main__":
    sys.exit(main())
