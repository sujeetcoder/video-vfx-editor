#!/usr/bin/env python3
"""Workflow state machine: init / next / run / resume / status / handoff / approve.

A decision that is not written to a file did not happen: everything lives in
edit/state.json, edit/decisions.md and the stage artifacts.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import (FailedCheck, InvalidInput, MissingCapability, NeedsUserInput,  # noqa: E402
                       SkillError, add_common, log, stage)
from _paths import (Lock, append_decision, edit_dir, ensure_edit, project_root,  # noqa: E402
                    read_json, record_stage, save_state, stage_done, write_json)

EDIT_STAGES = ["ingest", "probe", "intake", "plan", "cut", "asr", "camera", "broll",
               "caption", "audio", "export", "check"]
CLIP_STAGES = ["ingest", "probe", "intake", "asr", "plan", "approve", "clips", "check"]

STAGE_SCRIPT = {
    "ingest": "ingest.py", "probe": "probe.py", "intake": "intake.py", "plan": "plan.py",
    "cut": "cut.py", "scenes": "scenes.py", "asr": "asr.py", "caption": "caption.py",
    "camera": "camera.py", "broll": "broll.py", "assets": "assets.py",
    "audio": "audio.py", "export": "export.py", "check": "check.py", "clips": "clips.py",
    "clipfind": "clipfind.py", "style": "style.py", "graphics": "graphics.py",
}


def stages_for(state: dict) -> list:
    return CLIP_STAGES if state.get("job") == "clip" else EDIT_STAGES


def next_stage(state: dict) -> str | None:
    for name in stages_for(state):
        if not stage_done(state, name):
            return name
    return None


def stage_command(state: dict, name: str) -> str:
    art = state.get("artifacts", {})
    script = STAGE_SCRIPT.get(name)
    base = f"python scripts/{script}"
    src = art.get("ingest") or state.get("source") or "<source>"
    if name == "ingest":
        return f'{base} "{src}"'
    if name == "probe":
        # quick detect gives plan faces/green-screen hints; ASR runs as its own stage
        return f'{base} "{art.get("ingest", src)}" --quick --no-lang-guess'
    if name == "intake":
        return f'{base} --json'
    if name == "plan":
        return f'{base} "{art.get("probe", "")}"'
    if name == "cut":
        return f'{base} "{art.get("ingest", src)}"'
    if name == "asr":
        return f'{base} "{art.get("cut") or art.get("ingest", src)}" --lang {state.get("params", {}).get("lang", "hi")}'
    if name == "camera":
        return f'{base} "{art.get("cut") or art.get("ingest", src)}"'
    if name == "broll":
        return f'{base} "{art.get("camera") or art.get("cut") or art.get("ingest", src)}"'
    if name == "caption":
        # burn in the same pass: the export chain must carry the captions
        return f'{base} "{art.get("broll") or art.get("camera") or art.get("cut") or art.get("ingest", src)}" --burn'
    if name == "audio":
        return f'{base} "{art.get("caption") or art.get("cut") or art.get("ingest", src)}"'
    if name == "export":
        return f'{base} "{art.get("audio") or art.get("cut") or art.get("ingest", src)}"'
    if name == "clips":
        return f'{base} --from-plan'
    if name == "check":
        target = art.get("export") or art.get("clips") or art.get("cut") or art.get("ingest", src)
        return f'{base} "{target}"'
    return base


def final_output(state: dict) -> str | None:
    """The artifact a user should open: the export (or the clip batch when that is the job)."""
    art = state.get("artifacts", {})
    return art.get("export") or art.get("clips")


def brief(state: dict, root: Path) -> str:
    done = [s for s in stages_for(state) if stage_done(state, s)]
    nxt = next_stage(state)
    art = state.get("artifacts", {})
    lines = [
        "# HANDOFF",
        "",
        f"project: {root}",
        f"run: {state.get('run_id')} | job: {state.get('job')} | stage: {state.get('stage')} | device: {state.get('device')}",
        f"source: {state.get('source')}",
        "",
        "## DONE",
        *(f"- {s}" for s in done),
        "",
        *( [f"## FINAL\n{final_output(state)}"] if final_output(state) else [] ),
        "## NOW",
        f"stage: {nxt}" if nxt else "all stages done — run check.py and report",
        f"NEXT: {stage_command(state, nxt) if nxt else 'python scripts/check.py --json'}",
        "",
        "## FILES TO READ",
        *[f"- {k}: {v}" for k, v in sorted(art.items()) if k in (nxt or "", "plan", "intake", "probe")],
        "",
        "## RULES",
        "- don't re-ask intake questions already in edit/decisions.md",
        "- don't edit plan.json by hand; re-run plan.py",
        "- 3 failures on one stage -> ask the user",
    ]
    errs = state.get("errors") or []
    if errs:
        lines += ["", "## LAST ERROR", f"- {errs[-1].get('stage')}: {errs[-1].get('detail')}"]
    brief_text = "\n".join(lines)
    if len(brief_text) > 6000:
        brief_text = brief_text[:6000] + "\n…"
    return brief_text


KIND_MAP = {"missing_capability": MissingCapability, "invalid_input": InvalidInput,
            "needs_user_input": NeedsUserInput, "failed_check": FailedCheck}


def do_run(state: dict, root: Path, args):
    """Run stages until done/until/approval/failure. Returns (state, failure|None)."""
    failure = None
    seq = stages_for(state)
    if args.until and args.until not in seq:
        raise SkillError(
            f"stage '{args.until}' is not part of a {state.get('job', 'edit')} job",
            fix=f"choose one of: {', '.join(seq)}",
        )
    while True:
        name = next_stage(state)
        if name is None:
            break
        seq = stages_for(state)
        if args.until and name != args.until and seq.index(name) > seq.index(args.until):
            break
        argv = [sys.executable, str(Path(__file__).parent / STAGE_SCRIPT[name])]
        rest = stage_command(state, name)
        parts = rest.split(" ", 2)
        after = parts[2] if len(parts) > 2 else ""
        argv += _split_args(after)
        if args.dry_run:
            argv.append("--dry-run")
        argv += ["--json", "--project", str(root)]
        if args.device:
            argv += ["--device", args.device]
        log(f"RUN {name}: {' '.join(argv)}")
        try:
            with Lock(root, f"forge-{name}"):
                proc = subprocess.run(argv, text=True, capture_output=True)
        except SkillError as exc:
            state.setdefault("errors", []).append({"stage": name, "detail": exc.detail})
            save_state(root, state)
            raise
        payload = _parse_json(proc.stdout)
        if proc.returncode not in (0, 2):
            err = (payload or {}).get("error") or {
                "kind": "internal_error", "detail": (proc.stderr or "")[-500:]}
            failure = {"stage": name, **err}
            state = read_json(edit_dir(root) / "state.json", state)
            state.setdefault("errors", []).append({"stage": name, "detail": err.get("detail")})
            save_state(root, state)
            break
        state = read_json(edit_dir(root) / "state.json", state)
        if name == "intake" and not (edit_dir(root) / "work" / "intake.json").is_file():
            # nothing to run on yet: hand the question bank to the user
            state.setdefault("errors", []).append(
                {"stage": "intake", "detail": "no answers yet; ask the user the 8 questions"})
            save_state(root, state)
            break
        if name == "approve" and not state.get("params", {}).get("approved"):
            break
    return state, failure


def _split_args(text: str) -> list:
    import shlex

    try:
        parts = shlex.split(text, posix=False) if os.name == "nt" else shlex.split(text)
    except ValueError:
        parts = text.split()
    # Windows shlex keeps the surrounding quotes; strip them so paths stay valid
    return [p[1:-1] if len(p) > 1 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]


def _parse_json(text: str) -> dict:
    for line in reversed((text or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Common flags are valid before OR after the subcommand.
    pre = argparse.ArgumentParser(add_help=False)
    add_common(pre)
    common, rest = pre.parse_known_args(argv)

    parser = argparse.ArgumentParser(description="video-vfx-editor workflow state machine")
    sub = parser.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init")
    p_init.add_argument("source")
    p_init.add_argument("--job", default="edit", choices=["edit", "clip"])
    p_init.add_argument("--preset", default=None)

    sub.add_parser("next")
    p_run = sub.add_parser("run")
    p_run.add_argument("--until", default=None)
    p_run.add_argument("--yes", action="store_true")
    sub.add_parser("resume")
    sub.add_parser("status")
    sub.add_parser("handoff")
    p_appr = sub.add_parser("approve")
    p_appr.add_argument("ids", nargs="*", help="candidate ids, e.g. 1 4 7")
    p_appr.add_argument("--all", action="store_true")

    args = parser.parse_args(rest)
    for key, value in vars(common).items():
        setattr(args, key, value)
    root = project_root(args.project)

    with stage("forge", args) as run:
        state = ensure_edit(root, job=getattr(args, "job", "edit"), source=getattr(args, "source", None))
        cmd = args.cmd or "status"

        if cmd == "init":
            state["job"] = args.job
            state["source"] = args.source
            state["params"]["preset"] = args.preset
            state["stages"] = {}
            state["artifacts"] = {"ingest": args.source}
            save_state(root, state)
            append_decision(root, f"init job={args.job} source={args.source} preset={args.preset or '-'}")
            run.ok(output=str(edit_dir(root) / "state.json"),
                   artifacts=[str(edit_dir(root) / "state.json")],
                   next_cmd=stage_command(state, "ingest"))

        elif cmd == "next":
            nxt = next_stage(state)
            cmd_line = stage_command(state, nxt) if nxt else None
            run.ok(output=nxt, next_cmd=cmd_line)
            if not args.json:
                print(f"next stage: {nxt or 'done'}")
                if cmd_line:
                    print(cmd_line)

        elif cmd == "run":
            final, failure = do_run(state, root, args)
            nxt = next_stage(final)
            rendered = final_output(final)
            run.ok(output=str(edit_dir(root) / "state.json"),
                   artifacts=[rendered] if rendered else [],
                   next_cmd=stage_command(final, nxt) if nxt else None)
            if failure:
                exc_cls = KIND_MAP.get(failure.get("kind", ""), SkillError)
                run.fail(exc_cls(f"{failure.get('stage')}: {failure.get('detail')}",
                                 fix=failure.get("fix"), doc=failure.get("doc")))

        elif cmd == "status":
            done = [s for s in stages_for(state) if stage_done(state, s)]
            run.device = state.get("device") or run.device
            final = final_output(state)
            run.ok(output=f"{len(done)}/{len(stages_for(state))} stages",
                   artifacts=[str(edit_dir(root) / "state.json")] + ([final] if final else []),
                   next_cmd=stage_command(state, next_stage(state)) if next_stage(state) else None)
            if not args.json:
                print(f"run {state.get('run_id')} job={state.get('job')} stage={state.get('stage')}")
                print(f"final video: {final or '(not rendered yet)'}")
                for s in stages_for(state):
                    mark = "x" if stage_done(state, s) else " "
                    print(f"  [{mark}] {s}")

        elif cmd in ("resume", "handoff"):
            text = brief(state, root)
            path = edit_dir(root) / "handoff.md"
            path.write_text(text, encoding="utf-8", newline="\n")
            run.device = state.get("device") or run.device
            run.ok(output=str(path), artifacts=[str(path)],
                   next_cmd=stage_command(state, next_stage(state)) if next_stage(state) else None)
            if not args.json:
                print(text)

        elif cmd == "approve":
            plan_path = Path(state.get("artifacts", {}).get("plan", ""))
            plan = read_json(plan_path, {}) if plan_path.is_file() else {}
            cands = plan.get("candidates") or []
            if not cands:
                raise SkillError("no candidate clips to approve; run plan.py on a clip job first",
                                 fix="python scripts/plan.py <video> --job clip")
            ids = [int(i) for i in args.ids if str(i).isdigit()]
            if args.all:
                ids = [c["id"] for c in cands]
            approved = [c for c in cands if c["id"] in ids]
            if not approved:
                raise SkillError("no candidate ids matched", fix=f"valid ids: {[c['id'] for c in cands]}")
            plan["approved"] = [c["id"] for c in approved]
            write_json(plan_path, plan)
            state.setdefault("params", {})["approved"] = plan["approved"]
            record_stage(root, state, "approve", plan_path, approved=plan["approved"])
            append_decision(root, f"approved clips: {plan['approved']}")
            run.ok(output=str(plan_path), artifacts=[str(plan_path)],
                   next_cmd="python scripts/clips.py --from-plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
