from caption import (ass_ts, build_ass, caption_font_px, chunk_words, line_width,
                     safe_zone_ok, srt_ts, to_srt, STYLES)
from cut import build_filtergraph, filler_cuts, invert_silences, parse_silences


def words(*pairs):
    return [{"w": w, "s": s, "e": e} for w, s, e in pairs]


def test_caption_font_uses_height_on_vertical():
    assert caption_font_px(1080, 1920, 0.052) == 97
    assert caption_font_px(1920, 1080, 0.052) == 56


# ---------------------------------------------------------------- cut
def test_parse_silences():
    log = ("[silencedetect @ 0x1] silence_start: 1.2\n"
           "[silencedetect @ 0x1] silence_end: 2.8 | silence_duration: 1.6\n")
    assert parse_silences(log) == [(1.2, 2.8)]


def test_invert_silences_removes_long_only():
    keep = invert_silences([(1.0, 3.0), (4.0, 4.1)], duration=6.0, min_silence=0.45, pad=0.1)
    assert keep[0][0] == 0.0
    assert all(end <= 6.0 for _, end in keep)
    assert sum(b - a for a, b in keep) < 6.0


def test_invert_silences_never_empty():
    keep = invert_silences([(0.0, 10.0)], duration=10.0)
    assert keep and keep[0][1] == 10.0


def test_filler_cuts_ignore_long_words():
    w = words(("matlab", 1.0, 1.4), ("somethinglong", 2.0, 4.0))
    cuts = filler_cuts(w, ["matlab", "somethinglong"])
    assert (1.0, 1.4) in cuts


def test_build_filtergraph_golden():
    graph = build_filtergraph([(0.0, 1.0), (2.0, 3.5)], has_audio=True, fade_ms=30, fps=30)
    assert graph.startswith("[0:v]trim=start=0.000:end=1.000,setpts=PTS-STARTPTS,fps=30[v0]")
    assert "afade=t=in:st=0:d=0.030" in graph
    assert "afade=t=out:st=0.970:d=0.030" in graph
    assert "concat=n=2:v=1:a=1[v][a]" in graph
    assert graph.count("atrim") == 2


def test_build_filtergraph_no_audio():
    graph = build_filtergraph([(0.0, 2.0)], has_audio=False)
    assert "concat=n=1:v=1:a=0[v]" in graph
    assert "atrim" not in graph


# ---------------------------------------------------------------- captions
def test_chunk_words_caps_length():
    w = words(*[(f"word{i}", i, i + 0.5) for i in range(12)])
    lines = chunk_words(w, max_chars=32, min_words=2, max_words=4)
    assert all(len(line) <= 4 for line in lines)
    assert all(len(" ".join(x["w"] for x in line)) <= 40 for line in lines)


def test_chunk_words_splits_on_sentence_end():
    w = words(("hello", 0, 0.3), ("there.", 0.3, 0.6), ("new", 0.6, 0.9), ("idea.", 0.9, 1.2))
    lines = chunk_words(w)
    assert lines[0][-1]["w"].endswith(".")


def test_chunk_words_orphan_merge_respects_budget():
    w = words(("one", 0, 0.2), ("two", 0.2, 0.4), ("three", 0.4, 0.6), ("four", 0.6, 0.8), ("five", 0.8, 1.0))
    tight = chunk_words(w, max_chars=10, min_words=2, max_words=2)
    assert all(line_width(line) <= 10 for line in tight)              # budget wins over tidiness
    solo = chunk_words(w, max_chars=20, min_words=1, max_words=1)
    assert all(len(line) == 1 for line in solo)                       # one-word style stays one word


def test_orphan_merge_only_when_the_line_has_room():
    w = words(("hi,", 0, 0.2), ("there", 0.2, 0.4), ("friend", 0.4, 0.6))
    merged = chunk_words(w, max_chars=17, min_words=2, max_words=3)
    assert len(merged) == 1 and len(merged[0]) == 3                   # orphan absorbed into a 2-word line
    capped = chunk_words(w, max_chars=17, min_words=2, max_words=2)
    assert [len(line) for line in capped] == [2, 1]                   # word cap blocks the merge


def test_chunk_words_splits_a_looped_token():
    token = "गें" * 40
    lines = chunk_words(words((token, 0.0, 5.0)), max_chars=17, min_words=2, max_words=4)
    assert all(len(w["w"]) <= 17 for line in lines for w in line)
    assert "".join(w["w"] for line in lines for w in line) == token


def test_timestamps():
    assert srt_ts(0) == "00:00:00,000"
    assert srt_ts(3661.5) == "01:01:01,500"
    assert ass_ts(1.25) == "0:00:01.25"


def test_build_ass_karaoke_and_devanagari_font():
    w = words(("नमस्ते", 0.0, 0.5), ("दोस्त", 0.5, 1.0))
    ass = build_ass([w], 1080, 1920, STYLES["karaoke"], "bottom", "hi")
    assert "PlayResX: 1080" in ass
    assert "Noto Sans Devanagari" in ass
    assert "\\k50" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:01.00" in ass


def test_safe_zone_flags_long_line():
    w = words(*[(f"word{i}", i, i + 0.5) for i in range(8)])
    assert safe_zone_ok([w], max_chars=32, max_words=4)


def test_srt_roundtrip():
    w = words(("a", 0.0, 0.4), ("b", 0.4, 0.9))
    srt = to_srt([w])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:00,900")
    assert "a b" in srt
