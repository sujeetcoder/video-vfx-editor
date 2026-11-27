# PROGRESS

Last update: 2026-11-27 (v0.1.2, verified on Windows 11 with portable FFmpeg 9.1)

## Real-media run (this machine)

Source: Wikimedia Commons Hindi talking-head interview
("Interview of a Baiga tribe named Lakhan Lal in Hindi Language"), 53.803 s,
1920×1080 @25, vorbis 48 kHz. Project: `~/.vfe/proj-real` via `forge.py`.

```
python -m compileall -q scripts install evals      → OK
python -m pyflakes scripts install evals tests     → 0 findings
python -m pytest -q                                → 59 passed
python install/build_paste.py --check              → current
```

| Step | Measured |
|---|---|
| probe | 1080p25, no VFR, no HDR, audio 2ch/48k |
| cut | no silence ≥ 0.45 s; 53.8 s kept as one segment |
| asr | faster-whisper medium, CPU int8, **129 Devanagari words** from real speech |
| caption | 45 lines burned, 97 px at 1080×1920, safe zone pass |
| audio | PCM intermediate → single AAC encode, −14.5 LUFS, −1.7 dBTP |
| export | 1080×1920, 30 fps, libx264, 41 MiB |
| gates | **8/8 pass** (duration, resolution, fps, audio, loudness, true peak, black, freeze) |
| matte | rembg u2net, 54 masks @480 px, white/black previews correct |
| motion | `kinetic-hook`, 90 frames, energy 1.78, 11-char text |

## Bugs found by running (all fixed)

faster-whisper × PyAV 19 `metadata_errors`; double AAC encode with true-peak
overshoot; half-size vertical captions; FFmpeg 9 `-vsync` removal; matte mask
resolution mismatch; blank matte previews; rembg 1 GB default model; motion
renderer syntax error (nested template literals); global puppeteer invisible to
ESM/nvm shims; forged pipeline skipped caption burn and quick detect.

## Environment

- Python 3.12.10 at `~/.vfe/py312` (user-local; Python 3.15 has no wheels for
  numpy/onnxruntime/ctranslate2).
- `~/.vfe/bin` portable FFmpeg 9.1; `~/.vfe/fonts` OFL fonts.
- faster-whisper models in `~/.cache/huggingface` (small 0.5 GB, medium 1.5 GB);
  rembg u2net in `~/.rembg/models`; puppeteer Chrome in `~/.cache/puppeteer`.
- Windows Smart App Control blocks some unsigned builds (uv-managed Python,
  PyAV 18 wheels); the signed python.org installer works.

## Not verified

CUDA / Apple Silicon, macOS, birefnet / rvm / sam2 backends, whisper.cpp and
openai-whisper backends, install routes C/D/F.

## Next

```bash
export VFE_WHISPER_MODEL=medium
python scripts/forge.py init "<talking-head.mp4>" --job edit --json
python scripts/forge.py run --json
```
