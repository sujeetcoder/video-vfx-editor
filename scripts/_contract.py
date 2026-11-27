"""JSON envelope, exit codes and error objects for every video-vfx-editor script.

Contract (BUILD-PROMPT 4.1 / 4.2): every script accepts ``--json`` and prints
exactly one JSON object on stdout. Human logs go to stderr only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

EXIT_OK = 0
EXIT_WARN = 2
EXIT_FAILED_CHECK = 3
EXIT_NEEDS_INPUT = 4
EXIT_MISSING_CAP = 5
EXIT_INVALID_INPUT = 6

TROUBLESHOOTING = "references/troubleshooting.md"


class SkillError(Exception):
    """Base class for every error that reaches the user."""

    kind = "internal_error"
    exit_code = EXIT_FAILED_CHECK
    retryable = False
    doc = TROUBLESHOOTING

    def __init__(self, detail, fix=None, doc=None, retryable=None):
        super().__init__(detail)
        self.detail = str(detail)
        self.fix = fix
        if doc is not None:
            self.doc = doc
        if retryable is not None:
            self.retryable = retryable

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "detail": self.detail,
            "fix": self.fix,
            "doc": self.doc,
            "retryable": self.retryable,
        }


class MissingCapability(SkillError):
    kind = "missing_capability"
    exit_code = EXIT_MISSING_CAP


class InvalidInput(SkillError):
    kind = "invalid_input"
    exit_code = EXIT_INVALID_INPUT


class FailedCheck(SkillError):
    kind = "failed_check"
    exit_code = EXIT_FAILED_CHECK


class NeedsUserInput(SkillError):
    kind = "needs_user_input"
    exit_code = EXIT_NEEDS_INPUT


def log(msg: str) -> None:
    """Human-readable log line, always on stderr."""
    print(f"[vfe] {msg}", file=sys.stderr, flush=True)


def add_common(parser: argparse.ArgumentParser, device: bool = True) -> None:
    parser.add_argument("--json", action="store_true", help="emit one JSON object on stdout")
    parser.add_argument("--dry-run", action="store_true", help="print commands, render nothing")
    parser.add_argument("--project", default=None, help="project root (default: auto-detect)")
    parser.add_argument("--refresh", action="store_true", help="re-probe capability cache")
    if device:
        parser.add_argument(
            "--device",
            default=os.environ.get("VFE_DEVICE", "auto"),
            choices=["auto", "cpu", "cuda", "mps"],
            help="compute device policy (default: auto)",
        )


def _stringify(value):
    if isinstance(value, dict):
        return {k: _stringify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify(v) for v in value]
    return value


class StageRun:
    """Context manager that owns the envelope and the process exit code."""

    def __init__(self, stage_name: str, args=None):
        self.stage_name = stage_name
        self.args = args
        self.json_mode = bool(getattr(args, "json", False))
        self.dry_run = bool(getattr(args, "dry_run", False))
        pref = getattr(args, "device", None) or os.environ.get("VFE_DEVICE", "auto")
        self.device = "auto" if pref == "auto" else pref
        self.status = "ok"
        self.output = None
        self.artifacts = []
        self.checks = []
        self.next_cmd = None
        self.error = None
        self.quiet = False
        self._started = time.time()
        self._explicit = False

    # --- checks -----------------------------------------------------
    def add_check(self, cid: str, status: str, value=None, target=None) -> None:
        if status not in ("pass", "warn", "fail"):
            raise ValueError(f"bad check status {status!r}")
        self.checks.append(
            {"id": cid, "status": status, "value": value, "target": target}
        )
        if status == "fail":
            self.status = "fail"
        elif status == "warn" and self.status == "ok":
            self.status = "warn"

    # --- results ----------------------------------------------------
    def ok(self, output=None, artifacts=None, next_cmd=None, checks=None) -> "StageRun":
        self.output = output
        if artifacts is not None:
            self.artifacts = list(artifacts)
        if next_cmd is not None:
            self.next_cmd = next_cmd
        if checks:
            for c in checks:
                self.add_check(c["id"], c["status"], c.get("value"), c.get("target"))
        self._explicit = True
        return self

    def warn(self, msg: str) -> None:
        log("WARN " + msg)
        if self.status == "ok":
            self.status = "warn"

    def fail(self, error: SkillError):
        self.error = error
        self.status = "fail" if error.kind != "needs_user_input" else "needs_user_input"
        self._explicit = True
        return self

    @property
    def exit_code(self) -> int:
        if self.error is not None:
            return self.error.exit_code
        if self.status == "warn":
            return EXIT_WARN
        if self.status == "fail":
            return EXIT_FAILED_CHECK
        return EXIT_OK

    def envelope(self) -> dict:
        err = self.error.as_dict() if self.error else None
        if err is None and self.status == "fail" and self.checks:
            bad = [c for c in self.checks if c["status"] == "fail"]
            if bad:
                err = {
                    "kind": "failed_check",
                    "detail": f"{bad[0]['id']} failed (value={bad[0]['value']!r}, target={bad[0]['target']!r})",
                    "fix": f"run python scripts/check.py <file> --json and read {TROUBLESHOOTING}",
                    "doc": TROUBLESHOOTING,
                    "retryable": True,
                }
        return _stringify(
            {
                "status": self.status,
                "stage": self.stage_name,
                "output": self.output,
                "artifacts": self.artifacts,
                "checks": self.checks,
                "next": self.next_cmd,
                "error": err,
                "device": self.device,
                "duration_ms": int((time.time() - self._started) * 1000),
            }
        )

    def _print(self) -> None:
        env = self.envelope()
        if self.json_mode:
            sys.stdout.write(json.dumps(env, ensure_ascii=False) + "\n")
        else:
            head = f"{env['status'].upper()} {env['stage']}"
            if env["output"]:
                head += f" -> {env['output']}"
            print(head)
            for c in env["checks"]:
                print(f"  {c['status'].upper():4} {c['id']}: {c['value']} (target {c['target']})")
            if env["error"]:
                print(f"  error: {env['error']['detail']}")
                if env["error"].get("fix"):
                    print(f"  fix:   {env['error']['fix']}")
            if env["next"]:
                print(f"  next:  {env['next']}")
        sys.stdout.flush()

    def __enter__(self) -> "StageRun":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            if isinstance(exc, SkillError):
                self.error = exc
                self.status = "fail" if exc.kind != "needs_user_input" else "needs_user_input"
            elif isinstance(exc, (KeyboardInterrupt, SystemExit)):
                return False
            else:
                log("".join(traceback.format_exception(exc_type, exc, tb)))
                self.error = SkillError(
                    f"{exc_type.__name__}: {exc}",
                    fix="re-run with --json and attach the stderr log",
                    retryable=True,
                )
                self.status = "fail"
        if not self.quiet:
            self._print()
        # Swallow the exception (the envelope carries it) but keep the exit code honest.
        if self.exit_code:
            raise SystemExit(self.exit_code)
        return True


def stage(name: str, args=None) -> StageRun:
    return StageRun(name, args)


def need(value, message: str, fix: str | None = None):
    """Raise InvalidInput when a required value is missing."""
    if value is None or value == "":
        raise InvalidInput(message, fix=fix)
    return value


def emit_json(obj: dict) -> None:
    sys.stdout.write(json.dumps(_stringify(obj), ensure_ascii=False) + "\n")
    sys.stdout.flush()
