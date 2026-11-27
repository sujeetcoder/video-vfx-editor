# PROGRESS

Last update: 2026-11-27 (v0.1.3, clean-machine install re-verified on Windows 11)

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

## Clean-machine install (v0.1.3)

Removed every user-level artefact from the 0.1.2 run, then installed as a new
user with the machine's default Python 3.15:

| Step | Measured |
|---|---|
| `ensure.py --install --yes` | bootstraps CPython **3.12.16** + venv via uv, portable FFmpeg 9.1 (SHA-256 verified), 7 pip packages, puppeteer 25 + Chrome 158, fonts; re-run → `0 missing` |
| `python install/doctor.py` (default 3.15) | delegates to the venv; `PASS python 3.12.16`, `PASS ffmpeg`, `PASS py:cv2` … |
| `forge run` (defaults) | ingest → probe → intake(reel, hi) → plan → cut → asr → caption(burn) → audio → export → check, **210 s** |
| ASR | faster-whisper `small`, CPU int8, **50 Devanagari words** (medium caught 129 earlier) |
| gates | **8/8 pass**: 1080×1920, 30 fps, **−14.5 LUFS**, **−1.7 dBTP**, 0 black, 0 freeze |
| matte | rembg u2net, 45 masks @480 px, 87 s, white/black previews |
| motion | `kinetic-hook`, energy 2.03, 16-char text, no overflow |
| tests | 59 passed, pyflakes clean |

Install bugs found only on a clean machine (all fixed): stale `caps.json` skipped
FFmpeg, npm 12 skipped puppeteer's postinstall so Chrome never downloaded, the
checksum file tripped the download size floor, `yt-dlp` was probed only as a
executable, and OpenCV 5 removed `cv2.CascadeClassifier`.

## Environment

- CPython **3.12.16** + venv at `~/.vfe/venv`, provisioned user-locally by
  `install/ensure.py` through uv. Python 3.15 is rejected: numpy, onnxruntime and
  ctranslate2 have no wheels for it.
- `~/.vfe/bin` portable FFmpeg 9.1 (SHA-256 verified download); `~/.vfe/fonts`
  OFL fonts; `~/.vfe/node` portable Node 22 when the machine has none.
- faster-whisper models in `~/.cache/huggingface`; rembg u2net in `~/.rembg`;
  puppeteer Chrome in `~/.cache/puppeteer`.
- Windows Smart App Control can block unsigned builds; downloads are HTTPS-only
  and checksum-verified when the vendor publishes one (FFmpeg does).

## Not verified

CUDA / Apple Silicon, macOS, birefnet / rvm / sam2 backends, whisper.cpp and
openai-whisper backends, install routes C/D/F.

## Next

```bash
export VFE_WHISPER_MODEL=medium
python scripts/forge.py init "<talking-head.mp4>" --job edit --json
python scripts/forge.py run --json
```
