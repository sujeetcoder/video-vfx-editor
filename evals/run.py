#!/usr/bin/env python3
"""Eval runner: lists tasks, dry-runs the pipeline, scores gates/validity/style.

    python evals/run.py --list
    python evals/run.py --task edit-hindi-captions --media clip.mp4 --json
    python evals/run.py --all --media clip.mp4 --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "evals" / "tasks"


def parse_task(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta = {"slug": path.stem, "category": "", "media": "", "expected": ""}
    for line in text.splitlines():
        if line.startswith("- category:"):
            meta["category"] = line.split(":", 1)[1].strip().strip("`")
        elif line.startswith("- media:"):
            meta["media"] = line.split(":", 1)[1].strip()
        elif line.startswith("- expected:"):
            meta["expected"] = line.split(":", 1)[1].strip()
    meta["path"] = str(path)
    return meta


def list_tasks() -> list:
    return [parse_task(p) for p in sorted(TASKS.glob("*.md"))]


def run_task(task: dict, media: str | None, dry: bool) -> dict:
    result = {"slug": task["slug"], "category": task["category"], "status": "not_run",
              "gates": [], "validity": False, "style_match": None, "note": ""}
    if not media:
        result["note"] = "no --media supplied: structure-only check"
        return result
    doctor = subprocess.run([sys.executable, str(ROOT / "install" / "doctor.py"), "--json"],
                            text=True, capture_output=True)
    if doctor.returncode not in (0, 2):
        result["note"] = "doctor failed: fix capabilities first"
        return result
    cmd = [sys.executable, str(ROOT / "scripts" / "probe.py"), media, "--quick", "--json"]
    if dry:
        cmd.append("--dry-run")
    probe = subprocess.run(cmd, text=True, capture_output=True)
    payload = {}
    for line in reversed(probe.stdout.strip().splitlines()):
        if line.startswith("{"):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    result["status"] = payload.get("status", "fail")
    result["validity"] = bool(payload.get("output"))
    result["gates"] = payload.get("checks", [])
    result["note"] = "probe only; stage-level gates need the full pipeline"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the eval suite")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--task", default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--media", default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true", default=True)
    args = parser.parse_args(argv)
    tasks = list_tasks()
    if args.list:
        for t in tasks:
            print(f"{t['slug']:<26} {t['category']:<8} {t['expected']}")
        return 0
    selected = tasks if args.all else [t for t in tasks if t["slug"] == args.task]
    if not selected:
        print("pick --list, --task <slug> or --all", file=sys.stderr)
        return 6
    results = [run_task(t, args.media, args.dry_run) for t in selected]
    passed = sum(1 for r in results if r["gates"] and all(g["status"] == "pass" for g in r["gates"]))
    out = {"tasks": len(results), "gates_passed": passed, "results": results}
    (ROOT / "evals" / "results.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"{'task':<26} {'status':<8} gates")
        for r in results:
            print(f"{r['slug']:<26} {r['status']:<8} {len(r['gates'])}")
        print(f"\npassed {passed}/{len(results)} (structure-only unless --media was supplied)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
