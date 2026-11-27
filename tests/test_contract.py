import argparse
import json

from _contract import (EXIT_FAILED_CHECK, EXIT_MISSING_CAP, EXIT_OK, EXIT_WARN,
                       MissingCapability, SkillError, StageRun)


def make(stage_name, **kw):
    args = argparse.Namespace(json=True, dry_run=False, device="auto", **kw)
    return StageRun(stage_name, args)


def test_envelope_has_every_key():
    run = make("probe")
    run.ok(output="a.mp4", artifacts=["a.mp4"])
    env = run.envelope()
    for key in ("status", "stage", "output", "artifacts", "checks", "next",
                "error", "device", "duration_ms"):
        assert key in env
    assert env["status"] == "ok"
    assert run.exit_code == EXIT_OK
    json.dumps(env)


def test_warn_check_sets_warn_exit():
    run = make("cut")
    run.add_check("broll", "warn", 0, ">= 1")
    assert run.envelope()["status"] == "warn"
    assert run.exit_code == EXIT_WARN


def test_fail_check_creates_error_object():
    run = make("check")
    run.add_check("loudness", "fail", -9.0, "-14±1")
    env = run.envelope()
    assert env["status"] == "fail"
    assert env["error"]["kind"] == "failed_check"
    assert run.exit_code == EXIT_FAILED_CHECK


def test_missing_capability_exit_code():
    run = make("caption")
    run.fail(MissingCapability("no libass", fix="brew install ffmpeg-full"))
    assert run.exit_code == EXIT_MISSING_CAP
    assert run.envelope()["error"]["fix"].startswith("brew")


def test_error_dict_always_has_doc():
    err = SkillError("boom").as_dict()
    assert err["doc"] == "references/troubleshooting.md"
    assert err["retryable"] is False
