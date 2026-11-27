import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ALLOWED = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def frontmatter():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    block = text.split("---", 2)[1]
    data, key = {}, None
    for line in block.splitlines():
        if not line.strip():
            continue
        if line.startswith("  ") and key:
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip()
    return data, text


def test_only_allowed_frontmatter_keys():
    data, _ = frontmatter()
    assert set(data) <= ALLOWED, set(data) - ALLOWED


def test_name_matches_folder():
    data, _ = frontmatter()
    assert data["name"] == ROOT.name == "video-vfx-editor"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", data["name"])


def test_description_length_and_triggers():
    data, _ = frontmatter()
    assert len(data["description"]) <= 1024
    lowered = data["description"].lower()
    for trigger in ("edit video", "clip", "captions", "shorts", "reel", "chroma"):
        assert trigger in lowered, trigger


def test_skill_under_400_lines():
    _, text = frontmatter()
    assert text.count("\n") < 400


def test_repo_size_and_file_limits():
    files = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    assert len(files) < 1000
    total = sum(p.stat().st_size for p in files)
    assert total < 25 * 1024 * 1024


def test_no_committed_media_or_weights():
    bad = {".mp4", ".mov", ".mkv", ".wav", ".ttf", ".otf", ".onnx", ".pt", ".bin"}
    offenders = [str(p) for p in ROOT.rglob("*")
                 if p.is_file() and p.suffix.lower() in bad and ".git" not in p.parts
                 and "edit" not in p.parts]
    assert offenders == []


def test_text_files_use_lf():
    binary = {".png", ".jpg", ".pyc", ".zip", ".gz"}
    offenders = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts:
            continue
        if ".pytest_cache" in p.parts or "edit" in p.parts or "node_modules" in p.parts:
            continue
        if p.suffix.lower() in binary:
            continue
        if p.stat().st_size > 400_000:
            continue
        data = p.read_bytes()
        if b"\r\n" in data:
            offenders.append(str(p.relative_to(ROOT)))
    assert offenders == []


def test_marketplace_manifest():
    import json

    data = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert data["plugins"][0]["name"] == "video-vfx-editor"
    assert data["plugins"][0]["source"] == "./"


def test_every_script_has_argparse_and_json_flag():
    offenders = []
    for script in (ROOT / "scripts").glob("*.py"):
        if script.name.startswith("_"):
            continue
        text = script.read_text(encoding="utf-8")
        # every script gets --json through _contract.add_common
        if "argparse" not in text or not ("--json" in text or "add_common" in text):
            offenders.append(script.name)
    assert offenders == []


def test_evals_present():
    assert len(list((ROOT / "evals" / "tasks").glob("*.md"))) >= 25
    assert len(list((ROOT / "evals" / "recovery").glob("*.md"))) >= 5
    assert len(list((ROOT / "references" / "playbooks").glob("*.md"))) >= 11
