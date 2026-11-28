#!/usr/bin/env python3
"""OS detect, deps, models, agent skill links. Idempotent.

    python install/setup.py --agent all
    python install/setup.py --agent claude-code --global --install --yes
    python install/setup.py --list
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _caps import os_name  # noqa: E402
from _contract import log  # noqa: E402

AGENT_DIRS = {
    "claude-code": (".claude/skills", ".claude/skills"),
    "codex": (".agents/skills", ".agents/skills"),
    "opencode": (".opencode/skills", ".config/opencode/skills"),
    "cursor": (".cursor/skills", ".cursor/skills"),
    "gemini": (".agents/skills", ".gemini/skills"),
    "copilot": (".agents/skills", ".copilot/skills"),
}

SKIP = {"__pycache__", "edit", "node_modules", ".git", "models", ".pytest_cache"}


def link_skill(agent: str, global_scope: bool, target_root: Path, copy: bool) -> dict:
    if agent not in AGENT_DIRS:
        return {"agent": agent, "status": "unknown-agent"}
    project_rel, global_rel = AGENT_DIRS[agent]
    base = Path.home() / global_rel if global_scope else target_root / project_rel
    dest = base / "video-vfx-editor"
    if dest.exists() or dest.is_symlink():
        if dest.resolve() == ROOT.resolve():
            return {"agent": agent, "status": "already-linked", "path": str(dest)}
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    base.mkdir(parents=True, exist_ok=True)
    if not copy:
        try:
            os.symlink(ROOT, dest, target_is_directory=True)
            return {"agent": agent, "status": "linked", "path": str(dest)}
        except (OSError, NotImplementedError) as exc:
            log(f"symlink failed for {agent} ({exc}); copying instead")
    shutil.copytree(ROOT, dest, ignore=shutil.ignore_patterns(*SKIP), dirs_exist_ok=True)
    return {"agent": agent, "status": "copied", "path": str(dest)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Set up video-vfx-editor for agent CLIs")
    parser.add_argument("--agent", default="all",
                        help="all | claude-code | codex | opencode | cursor | gemini | copilot (comma-separated)")
    parser.add_argument("--global", dest="global_scope", action="store_true", help="install into home skill dirs")
    parser.add_argument("--copy", action="store_true", help="copy instead of symlink")
    parser.add_argument("--target", default=".", help="project root for project-scope links")
    parser.add_argument("--install", action="store_true", help="also install missing capabilities")
    parser.add_argument("--yes", action="store_true", help="non-interactive installs")
    parser.add_argument("--list", action="store_true", help="list agent paths and exit")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.list:
        for agent, (proj, glob) in AGENT_DIRS.items():
            print(f"{agent:<12} project: {proj:<18} global: ~/{glob}")
        return 0

    agents = list(AGENT_DIRS) if args.agent == "all" else [a.strip() for a in args.agent.split(",")]
    results = [link_skill(a, args.global_scope, Path(args.target).resolve(), args.copy) for a in agents]

    if args.install:
        proc = [sys.executable, str(ROOT / "install" / "ensure.py"), "--install"]
        if args.yes:
            proc.append("--yes")
        import subprocess

        subprocess.run(proc, text=True)

    if args.json:
        import json

        print(json.dumps({"platform": os_name(), "root": str(ROOT), "links": results}, indent=2))
    else:
        print(f"video-vfx-editor -> {ROOT}")
        print(f"platform: {os_name()} | python: {sys.version.split()[0]}")
        for r in results:
            print(f"  {r['agent']:<12} {r['status']:<15} {r['path']}")
        print("next: python install/doctor.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
