from _paths import expand_inputs, filter_path, safe_name, sha1_text


def test_filter_path_escapes_windows_drive_colon(tmp_path):
    p = tmp_path / "my video.ass"
    p.write_text("x")
    escaped = filter_path(p)
    assert escaped.startswith("'")
    assert escaped.endswith("'")
    assert "my video.ass" in escaped
    if len(str(p.resolve())) > 1 and str(p.resolve())[1] == ":":
        assert "\\:" in escaped


def test_filter_path_uses_forward_slashes(tmp_path):
    p = tmp_path / "a b" / "c.ass"
    p.parent.mkdir()
    p.write_text("x")
    assert "\\" not in filter_path(p).replace("\\:", "").replace("\\'", "")


def test_safe_name_keeps_unicode(tmp_path):
    assert safe_name("मेरा वीडियो final") == "मेरा वीडियो final"
    assert "/" not in safe_name("a/b:c")


def test_expand_inputs_folder(tmp_path):
    (tmp_path / "a.mp4").write_text("1")
    (tmp_path / "b.mov").write_text("2")
    (tmp_path / "notes.txt").write_text("x")
    found = expand_inputs([str(tmp_path)])
    assert [p.name for p in found] == ["a.mp4", "b.mov"]


def test_expand_inputs_strips_quotes(tmp_path):
    p = tmp_path / "clip one.mp4"
    p.write_text("1")
    found = expand_inputs([f'"{p}"'])
    assert len(found) == 1


def test_sha1_text_stable():
    assert sha1_text("a") == sha1_text("a")
    assert sha1_text("a") != sha1_text("b")
