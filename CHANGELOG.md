# Changelog

## 0.1.2 — 2026-11-27

Real-media pass: a Hindi talking-head interview (Wikimedia Commons, 53.8 s,
1920×1080@25) through the whole forged pipeline, with faster-whisper, rembg and
puppeteer actually installed on Windows 11.

### Verified with real speech

| Step | Result |
|---|---|
| ASR | faster-whisper `medium`, CPU int8, **129 Hindi words** in Devanagari from the real audio (Baiga interview, Dindori, 2007) |
| captions | 45 lines, burned, 97 px at 1080×1920 |
| cut | no silence ≥ 0.45 s to remove; 53.8 s kept as one segment |
| gates | 1080×1920, 30 fps, **−14.5 LUFS**, **−1.7 dBTP**, 0 black, 0 freeze → **8/8 pass** |
| matte | rembg u2net, 54 masks at 480 px, white + black previews correct |
| motion | `kinetic-hook` 90 frames via Chrome, energy 1.78, no text overflow |
| tests | 59 passed; pyflakes clean |

### Fixed (found only by running it)

- **faster-whisper × PyAV 19**: `av.open()` lost `metadata_errors`; every decode
  raised `TypeError`. `asr.py` now drops the kwarg at runtime (upstream fix).
- **Audio was AAC-encoded twice** (audio.py → export), drifting loudness to
  −12.9 LUFS and true peak to +0.2 dBTP. audio.py now writes a PCM 24-bit/48 kHz
  intermediate, export encodes AAC once, and loudnorm aims 0.8 dB under the plan
  ceiling. Result: −14.5 LUFS / −1.7 dBTP.
- **Vertical captions were half size**: font came from `min(w,h)` (56 px at
  1080×1920). It now scales with height (97 px) and the chars-per-line budget is
  derived from the width.
- **FFmpeg 9 removed `-vsync`**: matte frame extraction failed. Uses `-fps_mode vfr`.
- **Matte mask size mismatch**: a 480 px mask was fed to `alphamerge` against
  1080p frames. Masks are scaled first.
- **Matte previews were blank**: `-frames:v 1` grabbed the background before the
  seeked mask existed. The output timeline is seeked, with `-update 1`.
- **rembg defaulted to a 1 GB model**; matte now uses u2net (176 MB), overridable
  with `VFE_MATTE_MODEL`.
- **Motion renderer never ran**: nested template literals inside the HTML
  template were a syntax error. Rewritten with string concatenation.
- **Global puppeteer was invisible**: ESM imports ignore `NODE_PATH` and Node was
  an nvm shim. The renderer falls back to CJS resolution and motion.py resolves
  the real `process.execPath`.
- **The forged edit never burned captions**, and its probe skipped quick detect.
  Caption now burns in-stage; probe passes `--quick --no-lang-guess`.

### Not verified

CUDA/MPS, macOS, birefnet/rvm/sam2 matte backends, whisper.cpp/openai-whisper
backends, and install routes C/D/F.

## 0.1.1 — 2026-11-27

Verification pass on a real machine (Windows 11, portable FFmpeg 9.1). Found and
fixed bugs that only appear when the pipeline actually renders.

### Fixed

- **Exit codes** now match the envelope (`0/2/3/4/5/6`). Previously every script
  exited 0 even when it reported `fail`; `forge run` therefore continued past
  failures.
- **forge run** now propagates the failing stage (kind, fix, doc) and exits with
  its code; it also passes `--project` to every stage and is non-interactive for
  intake (stops with the question bank instead of blocking on `input()`).
- **Windows argument dispatch**: `shlex` kept surrounding quotes, so
  `probe.json` reached `plan.py` as a media path. Quotes are stripped now.
- **`--until` validation**: asking for a stage that does not exist in the current
  job's stage list now fails with a clear fix instead of a `ValueError`.
- **clips.py** used a hard-coded 1920×1080 source for the crop; it now uses the
  plan's `source_width`/`source_height` (720p sources were cropping out of range).
- **Chroma coverage probe**: FFmpeg 9 will not negotiate `alphaextract` without
  `format=yuva420p` first. Coverage measured 0 % before; now correct.
- **Infinite composite hang**: `color`/`-loop 1` backgrounds plus
  `overlay=shortest=0` never terminated (chroma, matte, textbehind). They use
  `shortest=1` and an explicit duration.
- **Progress bar**: `drawbox` rejected the unbounded `iw*t/DUR` expression; the
  width is clamped with `min(t/DUR,1)`.
- **Stock licence gate**: non-commercial (`by-nc`) Openverse assets were surfaced
  and could pass the gate. They are filtered out, scored down and counted.
- **Portable FFmpeg**: `~/.vfe/bin/{ffmpeg,ffprobe}` is discovered without PATH
  changes (user-local, no admin).
- `ensure.py --check` is read-only (no capability cache write); caption and cut
  find `words.json` through the state artifact as well as the work folder.

### Verified end to end (real renders)

| Flow | Result |
|---|---|
| edit: ingest → probe → intake → plan → cut | 30 s → 21.1 s, 5 segments, 8.9 s removed |
| captions (Devanagari ASS, burned) | 5 lines, 0 over-length |
| audio + export | 1080×1920, 30 fps, **−14.0 LUFS**, TP −9.5 dBTP |
| gates (`check.py`) | 8/8 pass: duration, resolution, fps, audio, loudness, true peak, black, freeze |
| clips (`plan --job clip` → approve → `clips.py`) | 3 clips, all gates pass, sidecars + manifest + review.html |
| chroma | key `0x01B341`, coverage **70.8 %** (target 65–85 %), white + black previews |
| reframe 16:9 → 9:16 | virtual camera JSON, crop_keep 1.0 |
| graphics | lower-third + progress bar render |
| sfx `--synth` | 2 whooshes placed at −18 dB |
| stock | 6 Openverse/Wikimedia results, 0 non-commercial |
| style learn → compare | profile written; comparison honestly **FAILs** on mismatched rhythm |
| forge run | ingest → probe → intake → plan → cut, handoff brief correct; stops at missing ASR with exit 5 |
| motion | clean `missing_capability` (exit 5) when puppeteer is absent |
| tests | **57 passed** |

### Not verified

- ASR backends (faster-whisper / whisper.cpp) and the matte models
  (rembg / BiRefNet / RVM / SAM2) are not installed here; their paths raise a
  clean `missing_capability` with install fixes.
- Motion graphics with puppeteer, macOS/Apple Silicon, CUDA, and install routes
  C/D/F remain unexercised.

## 0.1.0 — 2026-11-26

First complete implementation of the skill: contracts, install layer, edit
pipeline, chroma/matte, clipping, style learning, motion/SFX/graphics/stock,
14 references, 11 playbooks, 25 eval tasks, 5 recovery scenarios, tests.
