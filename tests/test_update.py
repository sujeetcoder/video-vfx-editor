import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_update():
    spec = importlib.util.spec_from_file_location("vfe_update", ROOT / "install" / "update.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


update = load_update()


def test_parse_version_from_skill_frontmatter():
    text = "---\nname: x\nmetadata:\n  version: 1.2.3\n  runtime: python\n---\n"
    assert update.parse_version(text) == "1.2.3"
    assert update.parse_version("no frontmatter here") is None
    assert update.local_version() == update.parse_version((ROOT / "SKILL.md").read_text(encoding="utf-8"))


def test_tracks_only_the_matching_origin():
    assert update.tracks("sujeetcoder/video-vfx-editor",
                         "https://github.com/sujeetcoder/video-vfx-editor.git")
    assert update.tracks("sujeetcoder/video-vfx-editor",
                         "git@github.com:sujeetcoder/video-vfx-editor.git")
    assert not update.tracks("sujeetcoder/other", "https://github.com/sujeetcoder/video-vfx-editor.git")


def test_sync_tree_updates_creates_and_reports_leftovers(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "scripts").mkdir(parents=True)
    (src / "scripts" / "new.py").write_text("new\n", encoding="utf-8")
    (src / "SKILL.md").write_text("v2\n", encoding="utf-8")
    (dst / "scripts").mkdir(parents=True)
    (dst / "SKILL.md").write_text("v1\n", encoding="utf-8")
    (dst / "gone.md").write_text("old\n", encoding="utf-8")

    moved = update.sync_tree(src, dst)

    assert (dst / "SKILL.md").read_text(encoding="utf-8") == "v2\n"
    assert (dst / "scripts" / "new.py").is_file()
    assert moved == {"files_created": 1, "files_updated": 1, "unchanged": 0,
                     "leftover": ["gone.md"]}


def test_sync_tree_never_touches_user_work(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    (src / "SKILL.md").write_text("v2\n", encoding="utf-8")
    (dst / "edit" / "out").mkdir(parents=True)
    (dst / "edit" / "out" / "clip.mp4").write_text("media\n", encoding="utf-8")
    (dst / ".git").mkdir()
    (dst / ".git" / "HEAD").write_text("ref\n", encoding="utf-8")
    (dst / "SKILL.md").write_text("v1\n", encoding="utf-8")

    moved = update.sync_tree(src, dst)

    assert (dst / "edit" / "out" / "clip.mp4").read_text(encoding="utf-8") == "media\n"
    assert (dst / ".git" / "HEAD").read_text(encoding="utf-8") == "ref\n"
    assert moved["files_created"] == 0 and moved["files_updated"] == 1
