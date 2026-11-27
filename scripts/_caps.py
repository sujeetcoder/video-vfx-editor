"""Cached capability and device detection — the single source of truth.

`capabilities()` never raises for a missing tool; it reports what exists so
`doctor.py` can print PASS/FAIL with a fix, and `ensure.py` can install only
what is missing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from _contract import log
from _paths import edit_dir, local_bin, read_json, repo_root, which, write_json

CAPS_VERSION = 5

REQUIRED_FILTERS = ("subtitles", "drawtext", "zscale", "loudnorm", "chromakey", "scdet")
NICE_FILTERS = ("despill", "alphaextract", "sidechaincompress", "afftdn", "arnndn", "freezedetect")

PY_PACKAGES = {
    "numpy": "numpy",
    "cv2": "opencv-python-headless",
    "PIL": "pillow",
    "faster_whisper": "faster-whisper",
    "torch": "torch",
    "rembg": "rembg",
    "scipy": "scipy",
    "yt_dlp": "yt-dlp",
    "earshot": "earshot",
    "onnxruntime": "onnxruntime",
}


def _run(cmd, timeout: int = 25):
    try:
        proc = subprocess.run(
            [str(c) for c in cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            errors="replace",
            text=True,
        )
        return proc.returncode, proc.stdout or ""
    except Exception as exc:  # noqa: BLE001 - detection must never raise
        return 127, str(exc)


def _python_packages() -> dict:
    code = (
        "import importlib,json\n"
        f"names={sorted(PY_PACKAGES)!r}\n"
        "out={}\n"
        "for n in names:\n"
        "    try:\n"
        "        importlib.import_module(n)\n"
        "        out[n]=True\n"
        "    except Exception:\n"
        "        out[n]=False\n"
        "print(json.dumps(out))\n"
    )
    rc, out = _run([sys.executable, "-c", code], timeout=60)
    if rc != 0:
        return {name: False for name in PY_PACKAGES}
    try:
        return json.loads(out.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return {name: False for name in PY_PACKAGES}


def _ffmpeg_filters(ffmpeg: str | None) -> dict:
    if not ffmpeg:
        return {}
    rc, out = _run([ffmpeg, "-hide_banner", "-filters"])
    filters = {}
    if rc != 0:
        return filters
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and "->" in line:
            flags, name = parts[0], parts[1]
            filters[name] = {"flags": flags}
    return filters


def _ffmpeg_encoders(ffmpeg: str | None) -> list:
    if not ffmpeg:
        return []
    rc, out = _run([ffmpeg, "-hide_banner", "-encoders"])
    encoders = []
    if rc != 0:
        return encoders
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("V") or (len(parts) >= 2 and parts[0].startswith("A")):
            encoders.append(parts[1])
    return encoders


def _gpu() -> dict:
    info = {"nvidia_smi": False, "cuda": False, "mps": False, "devices": []}
    if which("nvidia-smi"):
        rc, out = _run(["nvidia-smi", "-L"])
        if rc == 0 and "GPU" in out:
            info["nvidia_smi"] = True
            info["devices"] = [ln.strip() for ln in out.splitlines() if ln.strip()]
    code = (
        "import json\n"
        "r={'torch':False,'cuda':False,'mps':False}\n"
        "try:\n"
        "    import torch\n"
        "    r['torch']=True\n"
        "    r['cuda']=bool(torch.cuda.is_available())\n"
        "    r['mps']=bool(getattr(torch.backends,'mps',None) and torch.backends.mps.is_available())\n"
        "except Exception:\n"
        "    pass\n"
        "print(json.dumps(r))\n"
    )
    rc, out = _run([sys.executable, "-c", code], timeout=60)
    if rc == 0:
        try:
            torch_info = json.loads(out.strip().splitlines()[-1])
            info["cuda"] = info["cuda"] or torch_info.get("cuda", False)
            info["mps"] = bool(torch_info.get("mps"))
            info["torch"] = bool(torch_info.get("torch"))
        except Exception:  # noqa: BLE001
            info["torch"] = False
    return info


def fonts_dir(root=None) -> Path:
    root = Path(root or repo_root())
    local = root / "assets" / "fonts"
    if local.is_dir() and any(p.suffix.lower() in (".ttf", ".otf") for p in local.iterdir()):
        return local
    home = Path.home() / ".vfe" / "fonts"
    home.mkdir(parents=True, exist_ok=True)
    return home


def _fonts(root) -> dict:
    names = []
    for d in (fonts_dir(root), Path("/usr/share/fonts"), Path.home() / "Library" / "Fonts",
              Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"):
        if not d or not Path(d).is_dir():
            continue
        try:
            names.extend(p.name for p in Path(d).iterdir() if p.suffix.lower() in (".ttf", ".otf"))
        except OSError:
            continue
    devanagari = any("devanagari" in n.lower() or "mangal" in n.lower() or "nirmala" in n.lower()
                     for n in names)
    return {"dir": str(fonts_dir(root)), "count": len(names), "devanagari": devanagari}


def _models(root) -> dict:
    roots = [Path(root) / "models", Path.home() / ".vfe" / "models",
             Path.home() / ".cache" / "huggingface" / "hub"]
    found = []
    for base in roots:
        if not base.is_dir():
            continue
        try:
            for child in sorted(base.iterdir()):
                if child.is_dir():
                    found.append(child.name)
        except OSError:
            continue
    lowered = " ".join(found).lower()
    return {
        "dirs": [str(p) for p in roots],
        "entries": found[:40],
        "whisper": any("whisper" in n for n in found),
        "rvm": any("rvm" in n.lower() for n in found),
        "birefnet": any("birefnet" in n.lower() for n in found),
        "sam2": any("sam2" in n.lower() or "sam-2" in n.lower() for n in found),
        "_hint": lowered[:200],
    }


def _chrome() -> str | None:
    candidates = [
        which("chrome"), which("google-chrome"), which("chromium"), which("msedge"),
        r"C:/Program Files/Google/Chrome/Application/chrome.exe",
        r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return str(c)
    return None


def probe_all(root=None) -> dict:
    root = Path(root or repo_root())
    ffmpeg = os.environ.get("VFE_FFMPEG") or which("ffmpeg") or local_bin("ffmpeg")
    ffprobe = os.environ.get("VFE_FFPROBE") or which("ffprobe") or local_bin("ffprobe")
    filters = _ffmpeg_filters(ffmpeg)
    encoders = _ffmpeg_encoders(ffmpeg)
    node = which("node") or _local_tool("node")
    npm = which("npm") or _local_tool("npm")
    yt_dlp = which("yt-dlp")
    node_version = ""
    if node:
        _, out = _run([node, "-v"])
        node_version = out.strip().lstrip("v")
    packages = _python_packages()
    python_ok = sys.version_info >= (3, 11)
    return {
        "caps_version": CAPS_VERSION,
        "platform": sys.platform,
        "python": {"path": sys.executable, "version": sys.version.split()[0], "ok": python_ok},
        "ffmpeg": {
            "path": ffmpeg,
            "present": bool(ffmpeg),
            "filters": {k: v for k, v in filters.items() if k in REQUIRED_FILTERS or k in NICE_FILTERS},
            "missing_filters": [f for f in REQUIRED_FILTERS if f not in filters],
            "has_libass": "subtitles" in filters,
            "has_zscale": "zscale" in filters,
            "encoders": [e for e in encoders if e in
                         ("libx264", "libx265", "h264_nvenc", "hevc_nvenc", "h264_videotoolbox",
                          "hevc_videotoolbox", "aac", "libopus")],
            "has_faststart": True,
        },
        "ffprobe": {"path": ffprobe, "present": bool(ffprobe)},
        "node": {"path": node, "present": bool(node), "version": node_version,
                 "ok": bool(node) and _major(node_version) >= 20,
                 "preferred": bool(node) and _major(node_version) >= 22},
        "npm": {"path": npm, "present": bool(npm)},
        "npx": {"path": which("npx"), "present": bool(which("npx"))},
        "chrome": {"path": _chrome()},
        "yt_dlp": {"path": yt_dlp, "present": bool(yt_dlp or packages.get("yt_dlp"))},
        "packages": packages,
        "gpu": _gpu(),
        "fonts": _fonts(root),
        "models": _models(root),
        "whisper_backends": _whisper_backends(),
    }


def _local_tool(name: str):
    """User-local portable Node under ~/.vfe/node (installed by ensure.py)."""
    candidates = [Path.home() / ".vfe" / "node" / name,
                  Path.home() / ".vfe" / "node" / (name + ".cmd"),
                  Path.home() / ".vfe" / "node" / "bin" / name]
    for p in candidates:
        if p.is_file():
            return str(p)
    return None


def _major(version: str) -> int:
    try:
        return int(str(version).split(".")[0])
    except (ValueError, AttributeError):
        return 0


def _whisper_backends() -> dict:
    pkgs = None
    code = (
        "import importlib,json\n"
        "r={}\n"
        "for n in ['faster_whisper','whisper']:\n"
        "    try:\n"
        "        importlib.import_module(n); r[n]=True\n"
        "    except Exception:\n"
        "        r[n]=False\n"
        "print(json.dumps(r))\n"
    )
    rc, out = _run([sys.executable, "-c", code], timeout=60)
    if rc == 0:
        try:
            pkgs = json.loads(out.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            pkgs = None
    pkgs = pkgs or {"faster_whisper": False, "whisper": False}
    return {
        "faster": bool(pkgs.get("faster_whisper")),
        "openai": bool(pkgs.get("whisper")),
        "cpp": bool(which("whisper-cli") or which("main")),
    }


def capabilities(root=None, refresh: bool = False, cache_write: bool = True) -> dict:
    """Probe (cached). ``cache_write=False`` keeps read-only callers read-only."""
    root = Path(root or repo_root())
    cache = edit_dir(root) / "caps.json"
    if not refresh and cache.is_file():
        data = read_json(cache, {})
        if data.get("caps_version") == CAPS_VERSION:
            return data
    data = probe_all(root)
    if cache_write:
        try:
            write_json(cache, data)
        except OSError as exc:  # read-only project still usable
            log(f"cannot cache capabilities: {exc}")
    return data


def resolve_device(pref: str, caps: dict) -> str:
    pref = (pref or "auto").lower()
    gpu = caps.get("gpu", {})
    if pref == "cpu":
        return "cpu"
    if pref == "cuda":
        if not gpu.get("cuda"):
            raise _device_error("cuda requested but torch CUDA is unavailable",
                                "run install/ensure.py --install --yes (CUDA torch build), or use --device cpu")
        return "cuda"
    if pref == "mps":
        if not gpu.get("mps"):
            raise _device_error("mps requested but Apple MPS is unavailable",
                                "macOS 12.3+ on Apple Silicon, torch>=2.1; or use --device cpu")
        return "mps"
    if gpu.get("cuda"):
        return "cuda"
    if gpu.get("mps"):
        return "mps"
    return "cpu"


def _device_error(detail, fix):
    from _contract import MissingCapability

    return MissingCapability(detail, fix=fix, doc="references/troubleshooting.md#devices")


def device_plan(pref: str, caps: dict) -> dict:
    resolved = resolve_device(pref, caps)
    encoders = caps.get("ffmpeg", {}).get("encoders", [])
    if resolved == "cuda" and "h264_nvenc" in encoders:
        encoder = "h264_nvenc"
    elif resolved == "mps" and "h264_videotoolbox" in encoders:
        encoder = "h264_videotoolbox"
    else:
        encoder = "libx264"
    return {
        "requested": pref or "auto",
        "resolved": resolved,
        "encoder": encoder,
        "torch_device": resolved if resolved in ("cuda", "mps") else "cpu",
        "whisper": {"device": "cuda", "compute_type": "float16"} if resolved == "cuda"
        else {"device": "cpu", "compute_type": "int8"},
        "onnx_providers": {
            "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
            "mps": ["CoreMLExecutionProvider", "CPUExecutionProvider"],
            "cpu": ["CPUExecutionProvider"],
        }[resolved],
        "mask_res": 540 if resolved == "cpu" else 1080,
    }


def encoder_args(encoder: str, crf: int = 20) -> list:
    if encoder.endswith("nvenc"):
        return ["-c:v", encoder, "-preset", "p5", "-cq", str(crf), "-rc", "vbr", "-b:v", "0"]
    if encoder.endswith("videotoolbox"):
        return ["-c:v", encoder, "-b:v", "6M", "-allow_sw", "1"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]
