"""Folder roles, camera-move math and b-roll slotting — the new surface, pinned."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import assets  # noqa: E402
import camera  # noqa: E402
from broll import build_graph, pick_slots  # noqa: E402


@pytest.mark.parametrize("name,role", [
    ("video.mp4", "video"), ("main.mov", "video"), ("hero.webm", "video"),
    ("background.png", "background"), ("background.wav", "music"),
    ("background.mp4", "broll"), ("music.mp3", "music"), ("bgm.wav", "music"),
    ("b-roll-1.jpg", "broll"), ("cutaway_town.png", "broll"), ("logo.png", "overlay"),
    ("captions.srt", "subtitles"), ("notes.txt", None),
])
def test_role_for_names_and_kinds(name, role):
    assert assets.role_for(Path(name))[0] == role


def _write(folder: Path, name: str, size: int = 4) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_scan_picks_the_named_video_and_keeps_the_rest_as_broll(tmp_path, monkeypatch):
    for name in ("video.mp4", "extra.mp4", "background.png", "background.wav", "logo.png"):
        _write(tmp_path, name)
    monkeypatch.setattr(assets, "probe_asset", lambda p: {"path": str(p), "name": p.name,
                                                          "kind": assets.kind_of(p.suffix),
                                                          "bytes": 4, "duration": 10.0})
    manifest = assets.scan(tmp_path)
    roles = manifest["roles"]
    assert Path(roles["video"]).name == "video.mp4"
    assert Path(roles["background"]).name == "background.png"
    assert Path(roles["music"]).name == "background.wav"
    assert [Path(p).name for p in roles["broll"]] == ["extra.mp4"]
    assert [Path(p).name for p in roles["overlays"]] == ["logo.png"]


def test_scan_refuses_a_folder_without_video(tmp_path, monkeypatch):
    _write(tmp_path, "background.wav")
    monkeypatch.setattr(assets, "probe_asset", lambda p: {"path": str(p), "name": p.name,
                                                          "kind": "audio", "bytes": 4})
    with pytest.raises(Exception, match="no video"):
        assets.scan(tmp_path)


def test_zoom_expression_starts_and_ends_where_the_preset_says():
    assert camera.zoom_expr(1.0, 1.14, 100).split("+")[0] == "1.0000"
    expr = camera.zoom_expr(1.14, 1.0, 100)
    assert expr.startswith("1.1400+(-0.1400)")
    assert camera.zoom_expr(1.16, 1.16, 100) == "1.1600"


def test_motion_filter_targets_the_deliverable_and_crops_to_canvas():
    vf = camera.motion_filter("ken-burns", 1612, 1080, 1920, 30)
    assert "s=1080x1920" in vf
    assert "zoompan=z='1.0500+" in vf
    assert "scale=1728:3072" in vf                       # 1.6 canvas, rounded even
    assert vf.endswith("format=yuv420p")


def test_motion_filter_pans_stay_inside_the_frame():
    left = camera.motion_filter("pan-left", 900, 1080, 1920, 30)
    right = camera.motion_filter("pan-right", 900, 1080, 1920, 30)
    assert "x='(iw-iw/zoom)*(1-on/900)'" in left
    assert "x='(iw-iw/zoom)*on/900'" in right
    assert "z='1.1600'" in left                          # constant zoom while panning


def test_unknown_preset_is_rejected():
    with pytest.raises(Exception, match="unknown motion preset"):
        camera.motion_filter("wipe", 100, 1080, 1920, 30)


SEGMENTS = [
    {"start": 0.0, "end": 2.0, "text": "hook"},
    {"start": 2.0, "end": 4.0, "text": "one"},
    {"start": 5.0, "end": 6.0, "text": "too short"},
    {"start": 8.0, "end": 11.0, "text": "two"},
    {"start": 14.0, "end": 18.0, "text": "three"},
    {"start": 19.5, "end": 21.0, "text": "tail"},
]


def test_pick_slots_avoids_the_hook_and_the_tail():
    slots = pick_slots(SEGMENTS, duration=22.0, count=2)
    assert [s["text"] for s in slots] == ["one", "three"]
    assert all(1.5 <= s["start"] <= 20.5 for s in slots)


def test_pick_slots_clamps_length_and_respects_count():
    slots = pick_slots(SEGMENTS, duration=22.0, count=9)
    assert len(slots) == 4                      # every eligible sentence, none invented
    assert all(1.5 <= s["dur"] <= 2.4 for s in slots)


def test_pick_slots_is_empty_without_count_or_transcript():
    assert pick_slots(SEGMENTS, 22.0, 0) == []
    assert pick_slots([], 22.0, 3) == []


def test_build_graph_opens_and_closes_every_window():
    inserts = [{"start": 3.0, "dur": 2.0}, {"start": 9.0, "dur": 1.5}]
    graph, label = build_graph(inserts, 1080, 1920, 30)
    assert label == "v2"
    assert "overlay=enable='between(t,3.000,5.000)'" in graph
    assert "overlay=enable='between(t,9.000,10.500)'" in graph
    assert graph.count("format=rgba") == 2               # alpha is what makes the fade work
    assert "[v1][o2]overlay" in graph                    # second insert stacks on the first
    assert graph.count("zoompan=z='1.0000+") == 2        # inserts reuse camera.py's move, not a copy
