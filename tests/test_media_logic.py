from audio import build_chain, parse_loudnorm
from chroma import alpha_probe_chain, greenest, kmeans, key_graph
from graphics import progress_filter
from clipfind import build_windows, candidate_table, score_window
from export import fit_filter
from intake import PRESETS, QUESTIONS, detected_defaults
from plan import PLAYBOOKS, apply_style, auto_playbook, build_plan
from reframe import build_crop_expression, crop_keep_ratio, keyframes_from_faces
from stock import keywords, score as stock_score


def test_audio_chain_order():
    chain = build_chain(denoise=True, dehum=True, deess=True, loudness=-14)
    assert chain.index("afftdn") < chain.index("highpass") < chain.index("loudnorm")
    assert "loudnorm=I=-14" in chain


def test_audio_two_pass_includes_measured():
    chain = build_chain(measured={"input_i": -22.1, "input_tp": -3.0,
                                  "input_lra": 6.0, "input_thresh": -32.0, "target_offset": 0.1})
    assert "measured_I=-22.1" in chain
    assert "linear=true" in chain


def test_parse_loudnorm_block():
    text = '{"input_i" : "-23.4", "input_tp" : "-2.1", "input_lra" : "7.0", "input_thresh" : "-33.0", "target_offset" : "0.0"}'
    data = parse_loudnorm(text)
    assert data["input_i"] == -23.4
    assert data["target_offset"] == 0.0


def test_fit_filter_modes():
    fill = fit_filter(1080, 1920, 30, "fill")
    assert "force_original_aspect_ratio=increase" in fill and "crop=1080:1920" in fill
    contain = fit_filter(1080, 1920, 30, "contain")
    assert "pad=1080:1920" in contain and "fps=30" in contain


def test_kmeans_and_greenest():
    pts = [(10, 200, 20)] * 30 + [(180, 40, 30)] * 10
    clusters = kmeans(pts, 2)
    assert len(clusters) == 2
    key = greenest(clusters)
    assert key is not None
    assert key["hex"].startswith("0x")


def test_greenest_rejects_grey():
    pts = [(128, 128, 128)] * 20
    assert greenest(kmeans(pts, 3)) is None


def test_pyav19_shim_drops_removed_kwarg(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("av")
    fake.__version__ = "19.0.2"
    seen = {}

    def fake_open(*args, **kwargs):
        seen.update(kwargs)
        return object()

    fake.open = fake_open
    monkeypatch.setitem(sys.modules, "av", fake)
    from asr import _pyav_compat

    _pyav_compat()
    fake.open("x.wav", mode="r", metadata_errors="ignore")
    assert "metadata_errors" not in seen


def test_alpha_probe_pins_yuva_before_alphaextract():
    chain = alpha_probe_chain("0x00B140", 0.14, 0.05)
    assert chain.index("format=yuva420p") < chain.index("alphaextract")
    assert chain.endswith("scale=96:54,format=gray")


def test_progress_bar_expression_is_clamped():
    expr = progress_filter(21.5)
    assert "min(t/21.500,1)" in expr
    assert "t=fill" in expr


def test_key_graph_golden():
    g = key_graph("0x00B140", 0.14, 0.05, 0.5)
    assert g.startswith("chromakey=0x00B140:0.14:0.05")
    assert "despill=type=green:mix=0.5" in g
    assert g.endswith("format=yuva420p,gblur=sigma=0.20")


def test_crop_expression_constants():
    kfs = [{"t": 0, "center": [0.5, 0.5], "zoom": 1.0},
           {"t": 2, "center": [0.6, 0.5], "zoom": 1.1}]
    cam = build_crop_expression(kfs, 1920, 1080, 1080, 1920)
    assert cam["crop_w"] % 2 == 0 and cam["crop_h"] % 2 == 0
    assert isinstance(cam["x"], str) and "t" in cam["x"]


def test_crop_keep_ratio():
    centred = [{"t": 0, "center": [0.5, 0.5]}] * 4
    assert crop_keep_ratio(centred, 1920, 1080) == 1.0
    edge = [{"t": 0, "center": [0.05, 0.5]}] * 4
    assert crop_keep_ratio(edge, 1920, 1080) == 0.0


def test_keyframes_median_smooths_spike():
    faces = [(0.0, 0.50, 0.5, 0.2), (1.0, 0.90, 0.5, 0.2), (2.0, 0.50, 0.5, 0.2),
             (3.0, 0.50, 0.5, 0.2), (4.0, 0.50, 0.5, 0.2)]
    kfs = keyframes_from_faces(faces, 30.0, 1920, 1080, "9:16")
    assert abs(kfs[1]["center"][0] - 0.5) < 0.2


def test_playbooks_and_presets_consistent():
    for preset, answers in PRESETS.items():
        assert answers["playbook"] in PLAYBOOKS, preset
        for key, value in answers.items():
            q = next((q for q in QUESTIONS if q["id"] == key), None)
            if q is not None:
                assert value in [o["label"] for o in q["options"]], (preset, key, value)


def test_detected_defaults_long_source():
    out = detected_defaults({"duration": 1800, "aspect": 1.77, "quick": {"faces": 1}})
    assert out["answers"]["job"] == "clip"
    assert out["answers"]["aspect"] == "16:9"
    assert "job" in out["reasons"]


def test_auto_playbook():
    assert auto_playbook({"duration": 40}, {"job": "edit"}) == "reel"
    assert auto_playbook({"duration": 3600}, {"job": "clip"}) == "clip-lecture"


def test_build_plan_clamps_and_has_gates():
    probe = {"path": "x.mp4", "duration": 100, "aspect": 0.56}
    answers = {"job": "edit", "aspect": "9:16", "lang": "hi", "energy": "tight",
               "audio": "clean", "effects": "auto", "caption_style": "bold-pop"}
    caps = {"gpu": {"cuda": False, "mps": False}, "ffmpeg": {"encoders": ["libx264"]}}
    plan = build_plan(probe, answers, "reel", caps, "cpu")
    assert plan["output"]["width"] == 1080
    assert plan["output"]["loudness"] == -14.0
    assert plan["captions"]["lang"] == "hi"
    assert "loudness_tolerance" in plan["gates"]
    assert plan["clip"] is None


def test_apply_style_clamps():
    plan = {"output": {"loudness": -14}, "captions": {"style": "bold-pop"},
            "cut": {"target_shot_len": [1, 3]}, "style": {}}
    style = {"name": "s", "audio": {"loudness": -16}, "captions": {"style": "clean"},
             "rhythm": {"median_shot": 2.4, "cut_rhythm": 3.0}}
    out = apply_style(plan, style)
    assert out["output"]["loudness"] == -16.0
    assert out["captions"]["style"] == "clean"
    assert out["style"]["name"] == "s"


def test_clip_windows_sentence_snapped():
    transcript = {"words": [], "segments": [
        {"s": 0, "e": 20, "text": "one"}, {"s": 20, "e": 40, "text": "two"},
        {"s": 40, "e": 60, "text": "three"}]}
    wins = build_windows(transcript, 60, (15, 90))
    assert wins and all(w["out"] - w["in"] >= 15 for w in wins)


def test_score_window_bounds():
    transcript = {"words": [{"w": "secret", "s": 1, "e": 1.4}] * 5}
    scored = score_window({"in": 0, "out": 20}, transcript, 60, 3.0)
    assert 0 <= scored["score"] <= 1
    assert set(scored["signals"]) == {"speech", "pace", "hook", "self_contained", "external"}


def test_stock_keywords_drops_stopwords():
    query = keywords("the city at night is beautiful, city lights and night sky with people")
    assert "city" in query.split()
    assert "the" not in query.split()
    assert len(query.split()) <= 6


def test_stock_score_prefers_orientation_and_resolution():
    portrait = stock_score({"width": 1080, "height": 1920, "license": "cc-by", "creator": "x"}, "9:16")
    landscape = stock_score({"width": 1920, "height": 1080, "license": "cc-by", "creator": "x"}, "9:16")
    assert portrait["score"] > landscape["score"]


def test_stock_rejects_nc_licence():
    asset = stock_score({"width": 1080, "height": 1920, "license": "by-nc", "creator": "x"}, "9:16")
    assert any("licence not usable" in note for note in asset["notes"])


def test_candidate_table_header():
    payload = {"candidates": [{"id": 1, "in": 0, "out": 20, "score": 0.8,
                               "signals": {"speech": .9, "pace": .8, "hook": .7,
                                           "self_contained": .9, "external": .6},
                               "hook_line": "secret"}]}
    table = candidate_table(payload)
    assert table.startswith("| id |")
    assert "secret" in table
