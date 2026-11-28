# Changelog

## 0.1.5 — 2026-11-28

Update path: an installed copy can now follow the repository. Tell an agent
*"update the video-vfx-editor skill"* and it runs `install/update.py` instead of
hand-editing the installed folder.

### Added

- **`install/update.py`** — `--check` compares the installed copy with GitHub's
  branch head and exits **2** when there is something newer; `--apply` updates in
  place and re-runs `doctor.py`. Git checkouts fast-forward (`git fetch` +
  `git merge --ff-only`); paste/tarball copies are refreshed from the branch
  tarball, reporting created, changed, unchanged and `leftover` files. `edit/`,
  `.git`, models and node_modules are never touched, upstream deletions are
  reported rather than removed, and a dirty checkout is refused with a fix.
  `--agent all --global` re-links the agent folders afterwards.
- `tests/test_update.py` — version parsing, origin matching, and `sync_tree`
  (create/update/leftover, `edit/` and `.git` preserved).
- Docs name the trigger and the command: `SKILL.md` §11, `INSTALL.md` §5,
  `AGENTS.md`, `README.md`, `install/freebuff.md`.

### Verified

- `doctor.py`: **17 PASS, 0 FAIL**, only the optional RVM-model and CPU WARNs.
- **63 tests pass** (59 before), pyflakes clean, `agent-paste.md` regenerated.
- `--check` on this checkout: `already up to date (0.1.5)`, exit 0.
- Copy mode on a stale tree (`c9b3895`, no `.git`): check reports the update and
  exits 2, apply reports the changed files and lands on 0.1.5.
- Git mode on a stale clone: fetch + `--ff-only` moves it to the new head.

## 0.1.4 — 2026-11-27

Simplification pass over the installer added in 0.1.3. Same capabilities, less
code: `install/ensure.py`, `install/doctor.py`, the wrappers and
`scripts/_caps.py` went from **1010 to 913 lines**.

### Removed

- **The capability cache** (`edit/caps.json`, `CAPS_VERSION`, `--refresh`). Every
  call now probes fresh; the cache caused two of the 0.1.3 bugs (stale FFmpeg,
  stale yt-dlp) and cost about a second per stage to avoid.
- **Duplicated version/venv logic**: `os_name()`, `python_supported()` and
  `venv_python()` existed in three places. They live in `_caps.py` now, and
  `install/setup.py` imports `os_name()`.
- **The per-id if-chain in `run_action`**: local steps are handlers in the action
  dict, system steps keep the consent path. The fake `cmd` strings that existed
  only for printing are gone, along with the second `cmd` print line.
- **Redundant doctor work**: the repeated interpreter check,
  `_provisioned_python()` and the duplicated `next` assignment.
- **Download scaffolding**: the `min_bytes` parameter and the temp checksum file.
  The checksum is fetched as text and files are hashed with
  `hashlib.file_digest`.
- **Wrapper venv detection**: `doctor.py` already delegates to the provisioned
  interpreter, so `install.ps1`/`install.sh` no longer look for it.
- Dead bits: `_models._hint`, a second `fonts_dir()` lookup, an unused `import os`
  in the model pre-download snippet, and the `probe_all` wrapper (now
  `capabilities`).

### Verified after the rewrite

- `doctor.py`: same 17 PASS, 0 required failures, optional WARNs only (RVM
  matte model, CPU-only).
- `ensure.py --install --yes` into a throwaway `USERPROFILE` prefix: CPython
  **3.12.16** venv, SHA-256-verified FFmpeg 9.1, rembg + onnxruntime, puppeteer +
  Chrome; the second run reports **0 missing**.
- Motion smoke on that prefix (`kinetic-hook`): energy 2.09, no text overflow.
- **59 tests pass**, pyflakes clean, paste file current.

## 0.1.3 — 2026-11-27

Install-flow pass on a **cleaned machine**: every user-level artefact from the
0.1.2 run was removed (Python 3.12.10, portable FFmpeg, whisper/rembg/puppeteer
caches, global npm puppeteer, the PATH entries and PEP 514 registrations), then
the installer was run from scratch the way a new user would.

### Installer

- **CPython 3.12.16, user-local** — `ensure.py` provisions it with uv into
  `~/.vfe` when the default interpreter is outside 3.11–3.13, then re-runs
  itself inside that venv. No admin, no sudo, no PATH edits. This replaces the
  manual 3.12.10 install.
- **Windows FFmpeg without admin** — portable gyan.dev essentials build,
  downloaded over HTTPS, **SHA-256 verified**, unpacked to `~/.vfe/bin`.
- **Portable Node 22 LTS** in `~/.vfe/node` when Node is missing or too old;
  `_caps.py` and `doctor.py` find it without PATH changes.
- **The requirements it was missing are now installed**: `rembg` + `onnxruntime`
  (matte) and global `puppeteer` (motion) come with `--install`; `--models`
  pre-downloads the whisper model named by `VFE_WHISPER_MODEL`.
- **`ensure.py` and `doctor.py` delegate** to the provisioned venv when the
  default Python is unsupported, so both report the runtime scripts actually run
  on.
- **OpenCV pinned `<5`**: 5.x removed `cv2.CascadeClassifier`, used by `probe.py`
  and `reframe.py`; a fresh install broke face detection until pinned.

### Fixed by running the clean install

- The planner trusted `edit/caps.json` and **skipped FFmpeg entirely** after the
  runtime had been deleted; `--install` now always re-probes.
- **npm ≥ 12 skips postinstall scripts**, so `npm i -g puppeteer` installed the
  package without Chrome. The installer passes `--allow-scripts=puppeteer` and
  falls back to the package's `install.mjs`.
- The FFmpeg checksum file was rejected by the “4 KB minimum” download guard.
- `yt-dlp` was reported missing because only its console script was probed;
  module presence now counts.

### Verified end to end after the cleanup

| Step | Result |
|---|---|
| fresh `ensure.py --install --yes` | CPython 3.12.16 venv, FFmpeg 9.1, 7 pip packages, puppeteer 25 + Chrome 158, fonts → `preflight 0 missing` |
| pipeline (`forge run`, defaults) | ingest → probe → intake(reel, hi) → plan → cut → asr → caption(burn) → audio → export → check in **210 s** |
| ASR | faster-whisper `small`, CPU int8, **50 Devanagari words** from the real audio |
| captions | 19 lines burned |
| gates | **8/8 pass**: 1080×1920, 30 fps, **−14.5 LUFS**, **−1.7 dBTP**, 0 black, 0 freeze |
| matte | rembg u2net, 45 masks @480 px, 87 s, white + black previews |
| motion | `kinetic-hook` via puppeteer, energy 2.03, no text overflow |
| tests | 59 passed, pyflakes clean |

The `small` model keeps only 50 of the words the earlier `medium` run caught
(129); `VFE_WHISPER_MODEL=medium` remains the accurate choice for Hindi.

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
