#!/usr/bin/env python3
"""Word-level ASR with a backend picker: faster-whisper -> openai-whisper -> whisper.cpp.

Multilingual models only for Hindi (never .en). Cached by audio hash.

    python scripts/asr.py cut.mp4 --lang hi --json
    python scripts/asr.py cut.mp4 --asr cpp --json
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan  # noqa: E402
from _contract import InvalidInput, MissingCapability, add_common, log, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, project_root, read_json,  # noqa: E402
                    record_stage, run_cmd, sha1_file, which, work_dir, write_json)

MODEL_SIZES = ("tiny", "base", "small", "medium", "large-v3")
LANG_MAP = {"hi": "hi", "hinglish": "hi", "en": "en", "auto": None}
PROMPTS = {
    "hi": "यह वीडियो हिंदी में है। हिंदी शब्दों को देवनागरी में लिखें।",
    "hinglish": "Transcribe Hindi speech in Roman Hinglish script, e.g. 'aaj hum baat karenge'.",
    "en": "English transcription, punctuation included.",
}


def extract_audio(path: Path, work: Path, dry_run: bool = False) -> Path:
    wav = work / "asr.wav"
    if wav.is_file() and wav.stat().st_size > 1000:
        return wav
    run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)],
            dry_run=dry_run, timeout=3600, check=not dry_run)
    return wav


def pick_backend(requested: str, caps: dict) -> str:
    backends = caps.get("whisper_backends", {})
    if requested != "auto":
        key = {"faster": "faster", "openai": "openai", "cpp": "cpp"}[requested]
        if not backends.get(key):
            raise MissingCapability(
                f"ASR backend '{requested}' is not installed",
                fix={"faster": "python -m pip install --user faster-whisper",
                     "openai": "python -m pip install --user openai-whisper",
                     "cpp": "build whisper.cpp and put whisper-cli on PATH"}[key],
                doc="references/troubleshooting.md#asr",
            )
        return key
    for key in ("faster", "openai", "cpp"):
        if backends.get(key):
            return key
    raise MissingCapability(
        "no speech recogniser installed",
        fix="python -m pip install --user faster-whisper  (CPU int8 works; CUDA uses float16)",
        doc="references/troubleshooting.md#asr",
    )


def _pyav_compat() -> None:
    """PyAV 19 dropped av.open(metadata_errors=...); faster-whisper 1.2.x still sends it."""
    try:
        import av
    except ImportError:
        return
    if int(str(av.__version__).split(".")[0]) < 19:
        return
    original = av.open

    def open_compat(*args, **kwargs):
        kwargs.pop("metadata_errors", None)
        return original(*args, **kwargs)

    av.open = open_compat


def run_faster(wav: Path, lang: str, size: str, plan: dict) -> dict:
    _pyav_compat()
    from faster_whisper import WhisperModel

    model = WhisperModel(size, device=plan["whisper"]["device"], compute_type=plan["whisper"]["compute_type"])
    segments, info = model.transcribe(
        str(wav),
        language=LANG_MAP.get(lang),
        beam_size=5,
        temperature=0.0,
        word_timestamps=True,
        vad_filter=True,
        initial_prompt=PROMPTS.get(lang),
        condition_on_previous_text=False,
        # Without this guard Hindi at `small` loops on one token: the same clip
        # gave 50 words and a 113-char "word" before, 122 words and none after.
        no_repeat_ngram_size=3,
        repetition_penalty=1.1,
    )
    words, segs = [], []
    for seg in segments:
        segs.append({"s": round(seg.start, 3), "e": round(seg.end, 3), "text": seg.text.strip()})
        for w in seg.words or []:
            words.append({"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3),
                          "p": round(getattr(w, "probability", 0.0) or 0.0, 3)})
    return {"language": getattr(info, "language", lang), "words": words, "segments": segs}


def run_openai(wav: Path, lang: str, size: str, work: Path) -> dict:
    cli = which("whisper") or "whisper"
    model = "small" if size == "small" else size
    cmd = [cli, str(wav), "--model", model, "--output_format", "json",
           "--output_dir", str(work), "--word_timestamps", "True", "--temperature", "0",
           "--beam_size", "5", "--fp16", "False"]
    if LANG_MAP.get(lang):
        cmd += ["--language", LANG_MAP[lang]]
    rc, out = run_cmd(cmd, timeout=14400)
    if rc != 0:
        raise InvalidInput(f"openai-whisper failed: {out[-500:]}", fix="try --asr faster")
    js = work / f"{wav.stem}.json"
    payload = read_json(js, {})
    words, segs = [], []
    for seg in payload.get("segments", []):
        segs.append({"s": seg.get("start"), "e": seg.get("end"), "text": (seg.get("text") or "").strip()})
        for w in seg.get("words", []) or []:
            words.append({"w": w.get("word", "").strip(), "s": w.get("start"), "e": w.get("end"), "p": 0.0})
    return {"language": payload.get("language", lang), "words": words, "segments": segs}


def run_cpp(wav: Path, lang: str, size: str) -> dict:
    cli = which("whisper-cli") or which("main")
    model = os.environ.get("VFE_WHISPER_CPP_MODEL")
    if not model:
        raise MissingCapability(
            "whisper.cpp model not configured",
            fix="export VFE_WHISPER_CPP_MODEL=/path/ggml-small.bin (multilingual, not .en)",
            doc="references/troubleshooting.md#asr",
        )
    prefix = str(wav.with_suffix(""))
    cmd = [cli, "-m", model, "-f", str(wav), "-oj", "-ml", "1", "-of", prefix, "-t", "4"]
    if LANG_MAP.get(lang):
        cmd += ["-l", LANG_MAP[lang]]
    rc, out = run_cmd(cmd, timeout=14400)
    if rc != 0:
        raise InvalidInput(f"whisper.cpp failed: {out[-400:]}", fix="check VFE_WHISPER_CPP_MODEL")
    payload = read_json(Path(prefix + ".json"), {})
    words = []
    for item in payload.get("transcription", []):
        offs = item.get("offsets", {})
        words.append({"w": (item.get("text") or "").strip(),
                      "s": offs.get("from", 0) / 1000.0, "e": offs.get("to", 0) / 1000.0, "p": 0.0})
    return {"language": lang, "words": words, "segments": []}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Word-level transcription")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--lang", default="hi", choices=["hi", "hinglish", "en", "auto"])
    parser.add_argument("--asr", default="auto", choices=["auto", "faster", "openai", "cpp"])
    parser.add_argument("--model", default=os.environ.get("VFE_WHISPER_MODEL", "small"), choices=MODEL_SIZES)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    plan = device_plan(args.device, caps)

    with stage("asr", args) as run:
        run.device = plan["resolved"]
        path = expand_inputs([args.input])[0]
        work = work_dir(root, f"p-{path.stem}")
        out_path = work / "words.json"
        wav = work / "asr.wav"
        if not args.dry_run:
            wav = extract_audio(path, work, dry_run=False)
        digest = sha1_file(wav)[:12] if wav.is_file() else "dry"
        if out_path.is_file() and not args.force and not args.dry_run:
            cached = read_json(out_path, {})
            if cached.get("audio_hash") == digest and cached.get("lang") == args.lang:
                log("using cached transcript")
                run.ok(output=str(out_path), artifacts=[str(out_path)],
                       next_cmd="python scripts/caption.py <cut.mp4>")
                return 0

        if args.dry_run:
            run.ok(output=str(out_path), artifacts=[], next_cmd="python scripts/caption.py <cut.mp4>")
            return 0

        backend = pick_backend(args.asr, caps)
        log(f"asr backend={backend} model={args.model} device={plan['whisper']['device']}")
        try:
            if backend == "faster":
                result = run_faster(wav, args.lang, args.model, plan)
            elif backend == "openai":
                result = run_openai(wav, args.lang, args.model, work)
            else:
                result = run_cpp(wav, args.lang, args.model)
        except MissingCapability:
            raise
        except Exception as exc:  # noqa: BLE001 - GPU OOM must fall back once
            if plan["resolved"] != "cpu":
                log(f"GPU ASR failed ({exc}); retrying once on CPU")
                plan = device_plan("cpu", caps)
                result = run_faster(wav, args.lang, args.model, plan)
            else:
                raise

        result.update({"audio_hash": digest, "lang": args.lang, "backend": backend,
                       "model": args.model, "device": plan["resolved"],
                       "text": " ".join(s["text"] for s in result.get("segments", [])).strip()})
        if not result["words"]:
            raise InvalidInput(
                "transcript has no words (silent audio?)",
                fix="check the audio track; run scripts/probe.py --loudness on the source",
                doc="references/troubleshooting.md#asr",
            )
        write_json(out_path, result)
        state = ensure_edit(root)
        state["device"] = plan["resolved"]
        record_stage(root, state, "asr", out_path, words=len(result["words"]), backend=backend)
        run.add_check("transcript", "pass" if len(result["words"]) > 10 else "warn",
                      len(result["words"]), "> 10 words")
        run.ok(output=str(out_path), artifacts=[str(out_path)],
               next_cmd=f'python scripts/caption.py "{path}" --lang {args.lang}')
        if not args.json:
            print(f"{len(result['words'])} words ({backend}, {plan['resolved']}) -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
