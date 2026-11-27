"""Path resolution, project layout, FFmpeg invocation and Windows traps.

All scripts resolve their project through this module so that spaces, quotes,
non-ASCII (Hindi) names, drive letters and UNC-ish paths behave identically.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from _contract import InvalidInput, MissingCapability, log

EDIT = "edit"
SCHEMA_VERSION = 1
LOCK_STALE_SECONDS = 600


# --------------------------------------------------------------------------
# roots
# --------------------------------------------------------------------------
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def project_root(explicit=None, start=None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("VFE_PROJECT")
    if env:
        return Path(env).expanduser().resolve()
    cur = Path(start or os.getcwd()).expanduser().resolve()
    for p in [cur, *cur.parents]:
        if (p / EDIT).is_dir():
            return p
        if (p / "SKILL.md").is_file():
            return p
    return cur


def edit_dir(root) -> Path:
    return Path(root) / EDIT


def work_dir(root, key: str | None = None) -> Path:
    base = edit_dir(root) / "work"
    p = base / key if key else base
    p.mkdir(parents=True, exist_ok=True)
    return p


def out_dir(root, run_id: str) -> Path:
    p = edit_dir(root) / "out" / f"run-{run_id}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + sha1_text(str(time.time_ns()))[:4]


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------
def new_state(run_id: str | None = None, source: str | None = None, job: str = "edit") -> dict:
    return {
        "schema": SCHEMA_VERSION,
        "run_id": run_id or new_run_id(),
        "created": now_iso(),
        "updated": now_iso(),
        "job": job,
        "source": source,
        "stage": "init",
        "device": None,
        "stages": {},
        "artifacts": {},
        "params": {},
        "locks": {},
        "errors": [],
    }


def read_json(path, default=None):
    p = Path(path)
    if not p.is_file():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidInput(
            f"{p} is not valid JSON: {exc}",
            fix=f"delete {p.name} and re-run the stage, or restore it from git",
        )


def write_json(path, obj) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return p


def ensure_edit(root, run_id: str | None = None, job: str = "edit", source: str | None = None) -> dict:
    ed = edit_dir(root)
    (ed / "work").mkdir(parents=True, exist_ok=True)
    (ed / "out").mkdir(parents=True, exist_ok=True)
    state_path = ed / "state.json"
    if state_path.is_file():
        state = read_json(state_path, {})
        if state.get("schema") != SCHEMA_VERSION:
            migrated = migrate_state(state)
            write_json(state_path, migrated)
            return migrated
        return state
    state = new_state(run_id, source, job)
    write_json(state_path, state)
    (ed / "decisions.md").touch(exist_ok=True)
    return state


def save_state(root, state: dict) -> Path:
    state["updated"] = now_iso()
    state["schema"] = SCHEMA_VERSION
    return write_json(edit_dir(root) / "state.json", state)


def migrate_state(state: dict) -> dict:
    old = state.get("schema", 0)
    state = dict(state)
    if old < 1:
        state.setdefault("artifacts", {})
        state.setdefault("params", {})
        state.setdefault("errors", [])
        state.setdefault("locks", {})
        state.setdefault("stages", {})
    state["schema"] = SCHEMA_VERSION
    state.setdefault("job", "edit")
    log(f"migrated state.json schema {old} -> {SCHEMA_VERSION}")
    return state


def record_stage(root, state: dict, name: str, artifact=None, status: str = "done", **extra) -> dict:
    entry = {"status": status, "at": now_iso()}
    if artifact:
        entry["artifact"] = str(artifact)
        state.setdefault("artifacts", {})[name] = str(artifact)
    entry.update(extra)
    state.setdefault("stages", {})[name] = entry
    state["stage"] = name
    save_state(root, state)
    return state


def stage_done(state: dict, name: str) -> bool:
    return state.get("stages", {}).get(name, {}).get("status") in ("done", "warn")


def append_decision(root, text: str) -> None:
    p = edit_dir(root) / "decisions.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.is_file():
        p.write_text("# Decisions (append-only)\n\n", encoding="utf-8")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(f"- {stamp} — {text.strip()}\n")


def decided_text(root) -> str:
    p = edit_dir(root) / "decisions.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


# --------------------------------------------------------------------------
# locks
# --------------------------------------------------------------------------
class Lock:
    def __init__(self, root, name: str, stale: int = LOCK_STALE_SECONDS):
        self.path = edit_dir(root) / f".{name}.lock"
        self.name = name
        self.stale = stale

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            age = time.time() - self.path.stat().st_mtime
            if age < self.stale:
                raise InvalidInput(
                    f"stage '{self.name}' is locked ({int(age)}s old)",
                    fix=f"wait, or delete {self.path} if the previous run died",
                    doc="references/troubleshooting.md#stale-lock",
                )
            log(f"breaking stale lock {self.path.name} ({int(age)}s old)")
            self.path.unlink(missing_ok=True)
        self.path.write_text(now_iso(), encoding="utf-8")
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)
        return False


# --------------------------------------------------------------------------
# ffmpeg
# --------------------------------------------------------------------------
def which(cmd: str):
    return shutil.which(cmd)


def local_bin(name: str):
    """Portable tools installed user-locally under ~/.vfe/bin."""
    exe = name + (".exe" if os.name == "nt" else "")
    p = Path.home() / ".vfe" / "bin" / exe
    return str(p) if p.is_file() else None


def ffmpeg_bin() -> str:
    p = os.environ.get("VFE_FFMPEG") or which("ffmpeg") or local_bin("ffmpeg")
    if not p:
        raise MissingCapability(
            "ffmpeg not found on PATH",
            fix="Windows: winget install Gyan.FFmpeg | macOS: brew install ffmpeg | Linux: sudo apt install ffmpeg",
            doc="references/troubleshooting.md#ffmpeg",
        )
    return p


def ffprobe_bin() -> str:
    p = os.environ.get("VFE_FFPROBE") or which("ffprobe") or local_bin("ffprobe")
    if not p:
        raise MissingCapability(
            "ffprobe not found on PATH",
            fix="install a full FFmpeg build (ffprobe ships with it): brew install ffmpeg / winget install Gyan.FFmpeg",
            doc="references/troubleshooting.md#ffmpeg",
        )
    return p


def run_cmd(cmd, dry_run: bool = False, timeout: int | None = 3600, check: bool = False,
            env: dict | None = None):
    """Run an argv list (never shell=True). Returns (returncode, output)."""
    printable = " ".join(str(c) if " " not in str(c) else f'"{c}"' for c in cmd)
    if dry_run:
        log("DRY-RUN " + printable)
        return 0, ""
    log(printable if len(printable) < 400 else printable[:397] + "...")
    try:
        proc = subprocess.run(
            [str(c) for c in cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            errors="replace",
            text=True,
            env=env,
        )
    except FileNotFoundError:
        raise MissingCapability(f"executable not found: {cmd[0]}", fix="run python install/ensure.py --check")
    except subprocess.TimeoutExpired:
        raise MissingCapability(
            f"command timed out after {timeout}s: {cmd[0]}",
            fix="retry with a shorter --limit, or raise the timeout",
            doc="references/troubleshooting.md#timeouts",
        )
    out = proc.stdout or ""
    if check and proc.returncode != 0:
        raise InvalidInput(
            f"{cmd[0]} failed ({proc.returncode}): {out.strip()[-800:]}",
            fix="read the log above; run install/doctor.py to check the build",
        )
    return proc.returncode, out


def ffmpeg(args, dry_run: bool = False, timeout: int | None = 3600):
    return run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", *args], dry_run=dry_run, timeout=timeout)


def ffprobe_json(path, dry_run: bool = False) -> dict:
    cmd = [
        ffprobe_bin(), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", "--", str(path),
    ]
    rc, out = run_cmd(cmd, dry_run=dry_run)
    if dry_run:
        return {}
    if rc != 0:
        raise InvalidInput(
            f"ffprobe cannot read {path}: {out.strip()[-400:]}",
            fix="the file may be corrupt or 0 bytes; re-export it or pick another file",
            doc="references/troubleshooting.md#corrupt-input",
        )
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise InvalidInput(f"ffprobe returned non-JSON for {path}", fix="check the FFmpeg build")


# --------------------------------------------------------------------------
# path escaping
# --------------------------------------------------------------------------
def ff_path(p) -> Path:
    """Absolute path, safe to hand to FFmpeg as a plain argument."""
    return Path(p).expanduser().resolve()


def filter_path(p) -> str:
    """Escape a path for use inside an FFmpeg filtergraph (subtitles=, movie=...)."""
    s = ff_path(p).as_posix()
    s = s.replace("\\", "/")
    # order matters: backslash first, then quote, then the drive colon
    s = s.replace("'", r"\'")
    if len(s) > 1 and s[1] == ":":
        s = s[0] + r"\:" + s[2:]
    return f"'{s}'"



def safe_name(name: str) -> str:
    keep = "-_. "
    cleaned = "".join(ch for ch in str(name) if ch.isalnum() or ch in keep or ord(ch) > 127)
    return cleaned.strip().replace("  ", " ") or "output"


# --------------------------------------------------------------------------
# hashing
# --------------------------------------------------------------------------
def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def sha1_file(path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def input_key(path) -> str:
    p = Path(path)
    st = p.stat()
    return sha1_text(f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}")[:8]


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------
def expand_inputs(items) -> list[Path]:
    """Accept files, folders, globs and drag-dropped quoted paths."""
    out: list[Path] = []
    for raw in items:
        if raw is None:
            continue
        s = str(raw).strip().strip('"').strip("'")
        if not s:
            continue
        p = Path(s).expanduser()
        if p.is_dir():
            for child in sorted(p.iterdir()):
                if child.is_file() and child.suffix.lower() in MEDIA_EXT:
                    out.append(child.resolve())
        elif p.is_file():
            out.append(p.resolve())
        else:
            matches = sorted(Path().glob(s)) if any(c in s for c in "*?[") else []
            out.extend(m.resolve() for m in matches if m.is_file())
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    if not uniq:
        raise InvalidInput(
            "no input media found",
            fix="pass a file path, a folder, or a glob: python scripts/probe.py \"C:/clips/*.mp4\"",
        )
    return uniq


MEDIA_EXT = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts", ".m2ts",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".opus", ".ogg",
}


def is_url(s: str) -> bool:
    return str(s).startswith(("http://", "https://"))


def next_cmd(*parts) -> str:
    rendered = []
    for part in parts:
        s = str(part)
        rendered.append(f'"{s}"' if " " in s else s)
    return " ".join(rendered)
