#!/usr/bin/env python3
"""Update an installed copy of this skill from GitHub.

    python install/update.py --check --json   # read-only: is anything newer?
    python install/update.py --apply --json   # update this folder in place
    python install/update.py --apply --agent all --global --json

Two install shapes, two mechanisms:

- **git checkout** — `git fetch` + `git merge --ff-only` on the tracked branch.
- **plain copy** (paste/tarball install) — download the branch tarball and
  overwrite the skill files in place, reporting what changed.

`edit/`, `.git`, models and node_modules are never touched, and files deleted
upstream are reported rather than removed. A dirty checkout is refused, because
the user's uncommitted work outranks ours.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _contract import SkillError, add_common, log, stage  # noqa: E402

DEFAULT_REPO = os.environ.get("VFE_REPO", "sujeetcoder/video-vfx-editor")
API = "https://api.github.com/repos"
RAW = "https://raw.githubusercontent.com"
CODELOAD = "https://codeload.github.com"

# Never copied, never counted: user work, VCS data and machine-specific installs.
SKIP_DIRS = {".git", "edit", "node_modules", "__pycache__", ".pytest_cache",
             "models", ".venv", "venv"}
SKIP_NAMES = {".DS_Store", "Thumbs.db"}


# --------------------------------------------------------------------------
# network
# --------------------------------------------------------------------------
def _get(url: str, timeout: int = 60) -> bytes:
    if not url.startswith("https://"):
        raise RuntimeError(f"refusing non-HTTPS request: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "video-vfx-editor-update",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _json(url: str) -> dict:
    return json.loads(_get(url).decode("utf-8", "replace"))


def default_branch(repo: str) -> str:
    if os.environ.get("VFE_BRANCH"):
        return os.environ["VFE_BRANCH"]
    try:
        return str(_json(f"{API}/{repo}").get("default_branch") or "master")
    except Exception:  # noqa: BLE001 - offline or rate-limited; master is the fallback
        return "master"


def remote_sha(repo: str, branch: str, use_git: bool) -> str | None:
    """Branch head: `ls-remote` when this checkout really tracks that repo."""
    if use_git:
        out = _git("ls-remote", "origin", f"refs/heads/{branch}")
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.split()[0]
    return _json(f"{API}/{repo}/commits/{branch}").get("sha")


def remote_version(repo: str, branch: str) -> str | None:
    return parse_version(_get(f"{RAW}/{repo}/{branch}/SKILL.md").decode("utf-8", "replace"))


# --------------------------------------------------------------------------
# local state
# --------------------------------------------------------------------------
def parse_version(text: str) -> str | None:
    match = re.search(r"^  version:\s*([0-9][0-9A-Za-z.\-]*)", text, re.MULTILINE)
    return match.group(1) if match else None


def local_version() -> str | None:
    skill = ROOT / "SKILL.md"
    return parse_version(skill.read_text(encoding="utf-8")) if skill.is_file() else None


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=True, timeout=300)


def git_state() -> dict:
    if not (ROOT / ".git").exists():
        return {}
    return {
        "sha": _git("rev-parse", "HEAD").stdout.strip(),
        "dirty": bool(_git("status", "--porcelain").stdout.strip()),
        "origin": _git("remote", "get-url", "origin").stdout.strip(),
    }


def github_slug(url: str) -> str:
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url.strip())
    return match.group(1).lower() if match else ""


def tracks(repo: str, origin_url: str) -> bool:
    """True when this checkout's origin is the repo we were asked to follow.

    A non-GitHub origin (local mirror, GitLab) is accepted as-is: updating a
    checkout from the remote it was cloned from is what the user asked for.
    """
    slug = github_slug(origin_url)
    return not slug or slug == repo.lower()


# --------------------------------------------------------------------------
# copy-mode apply
# --------------------------------------------------------------------------
def skill_files(root: Path):
    """Relative paths of files that belong to the skill (not user data)."""
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.is_file() and path.name not in SKIP_NAMES:
            yield rel


def _digest(path: Path) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def sync_tree(src: Path, dst: Path) -> dict:
    """Overwrite dst with src, leaving dst's ignored folders (edit/, .git) alone."""
    created = updated = unchanged = 0
    upstream = set()
    for rel in skill_files(src):
        upstream.add(rel.as_posix())
        target = dst / rel
        if target.is_file() and _digest(target) == _digest(src / rel):
            unchanged += 1
            continue
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, target)
        if existed:
            updated += 1
        else:
            created += 1
    leftover = [rel.as_posix() for rel in skill_files(dst) if rel.as_posix() not in upstream]
    return {"files_created": created, "files_updated": updated,
            "unchanged": unchanged, "leftover": leftover}


def apply_copy(repo: str, branch: str) -> dict:
    url = f"{CODELOAD}/{repo}/tar.gz/refs/heads/{branch}"
    log(f"downloading {url}")
    with tempfile.TemporaryDirectory() as td:
        archive = Path(td) / "skill.tar.gz"
        archive.write_bytes(_get(url, timeout=300))
        with tarfile.open(archive) as tf:
            tf.extractall(td, filter="data")
        src = next(p for p in Path(td).iterdir() if p.is_dir())
        return sync_tree(src, ROOT)


# --------------------------------------------------------------------------
# verify + links
# --------------------------------------------------------------------------
def run_json(path: Path, *args: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(path), *args], capture_output=True,
                          text=True, timeout=600)
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError:
        return proc.returncode, {"status": "unknown", "error": {"detail": proc.stderr.strip()[-300:]},
                                 "checks": []}


def doctor_summary() -> dict:
    checks = run_json(ROOT / "install" / "doctor.py", "--json")[1].get("checks", [])
    return {"fails": [c["id"] for c in checks if c["status"] == "fail"],
            "warns": [c["id"] for c in checks if c["status"] == "warn"]}


def relink(agent: str, global_scope: bool) -> int:
    args = ["--agent", agent, "--json"] + (["--global"] if global_scope else [])
    return run_json(ROOT / "install" / "setup.py", *args)[0]


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def check_remote(repo: str, branch: str, as_git: bool) -> str:
    try:
        head = remote_sha(repo, branch, as_git)
    except Exception as exc:  # noqa: BLE001 - every network failure reads the same to the user
        raise SkillError(f"could not reach GitHub for {repo}@{branch}: {exc}",
                         fix="check network or proxy access to github.com, then re-run "
                             "python install/update.py --check --json", retryable=True) from exc
    if not head:
        raise SkillError(f"GitHub returned no head commit for {repo}@{branch}",
                         fix="check the repo name and branch (VFE_REPO / VFE_BRANCH)", retryable=True)
    return head


def apply_git(branch: str, state: dict, run) -> str:
    if state.get("dirty"):
        raise SkillError("working tree has local changes; refusing to overwrite them",
                         fix=f"commit or stash inside {ROOT}, then re-run "
                             "python install/update.py --apply --json")
    if _git("fetch", "--quiet", "origin", branch).returncode != 0:
        raise SkillError(f"git fetch origin {branch} failed",
                         fix="fix the remote/credentials for origin and re-run", retryable=True)
    before = state["sha"]
    merge = _git("merge", "--ff-only", "FETCH_HEAD")
    if merge.returncode != 0:
        raise SkillError(f"git merge --ff-only failed: {merge.stderr.strip()[:300]}",
                         fix=f"reconcile the branch by hand inside {ROOT} (git status)")
    after = _git("rev-parse", "HEAD").stdout.strip()
    ahead = int(_git("rev-list", "--count", f"{before}..{after}").stdout.strip() or 0)
    run.add_check("applied", "pass", f"{before[:7]}..{after[:7]}", "fast-forward")
    return f"{before[:7]} -> {after[:7]} ({ahead} commits)"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Update an installed video-vfx-editor from GitHub")
    add_common(parser)
    parser.add_argument("--check", action="store_true", help="read-only (default)")
    parser.add_argument("--apply", action="store_true", help="fetch and update this folder in place")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"owner/name on GitHub (default {DEFAULT_REPO})")
    parser.add_argument("--agent", default=None, help="also re-link: all|claude-code|codex|opencode|cursor|gemini|copilot")
    parser.add_argument("--global", dest="global_scope", action="store_true", help="with --agent: home scope")
    parser.add_argument("--no-verify", action="store_true", help="skip doctor.py after updating")
    args = parser.parse_args(argv)

    with stage("update", args) as run:
        repo, branch = args.repo, default_branch(args.repo)
        state = git_state()
        as_git = bool(state) and tracks(repo, state.get("origin", ""))
        start_version = local_version()
        log(f"{'git' if as_git else 'copy'} install at {ROOT} — version {start_version}, branch {branch}")

        head = check_remote(repo, branch, as_git)
        if as_git:
            behind = head != state["sha"]
            target = f"{start_version} -> {head[:7]}"
        else:
            latest = remote_version(repo, branch)
            behind = bool(latest and latest != start_version)
            target = f"{start_version} -> {latest or head[:7]}"

        run.add_check("remote", "pass", f"{repo}@{branch}", head[:7])

        if not behind:
            run.add_check("up-to-date", "pass", start_version, target)
            run.output = f"already up to date ({start_version})"
        elif not args.apply or args.dry_run:
            run.add_check("up-to-date", "warn", f"behind {head[:7]}", target)
            run.output = f"update available: {target}"
            run.next_cmd = None if args.dry_run else "python install/update.py --apply --json"
        elif as_git:
            summary = apply_git(branch, state, run)
            new_version = local_version()
            run.output = f"{new_version} — {summary}"
            if start_version != new_version:
                run.add_check("version", "pass", new_version, "declared in SKILL.md")
        else:
            moved = apply_copy(repo, branch)
            run.add_check("applied", "pass" if not moved["leftover"] else "warn",
                          f"{moved['files_created']} new, {moved['files_updated']} changed",
                          "0 leftover files")
            run.output = (f"{local_version()} — {moved['files_created']} new, "
                          f"{moved['files_updated']} changed, {moved['unchanged']} unchanged")
            if moved["leftover"]:
                log("deleted upstream, left in place: " + ", ".join(moved["leftover"][:20]))

        if args.apply and not args.dry_run and behind:
            if not args.no_verify:
                report = doctor_summary()
                if report["warns"]:
                    log("doctor warns, optional only: " + ", ".join(report["warns"]))
                run.add_check("doctor", "fail" if report["fails"] else "pass",
                              f"{len(report['fails'])} FAIL / {len(report['warns'])} WARN", "0 FAIL")
            if args.agent:
                code = relink(args.agent, args.global_scope)
                run.add_check("agent-link", "pass" if code == 0 else "fail", args.agent, "linked")
            log("restart the agent session: skill instructions are loaded at startup")
    return 0


if __name__ == "__main__":
    sys.exit(main())
