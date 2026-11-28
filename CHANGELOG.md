# Changelog

## 0.2.1 — 2026-11-28

Cleanup of the 0.2.0 surface; no behaviour change, one real render re-verified.

### Cut

- `plan.motion.amount` and `apply_assets`'s `overlays`/`subtitles` plan fields:
  nothing read them (camera presets and the export path do not consult them); the
  roles stay in `work/assets/assets.json` where they are reported.
- `stage_command(state, name, root)`'s unused `root` parameter and its seven call
  sites.
- `plan_job_is_clip()`, a one-line wrapper called once.
- Two `answers.setdefault(key, None)` no-ops in `plan.py`.
- `broll.py`'s transcript fallback to `artifacts["cut"]`, a video path fed to
  `read_json` — unreachable while ASR runs, a crash if it ever were.

### Simplified

- `broll.build_graph()` rebuilt the canvas + `zoompan` chain by hand (its own
  `1.6` constant, its own zoom expression). It now calls `camera.motion_filter()`,
  so stills and footage share one move and one canvas factor.
- Tightened two weak test assertions (`2 <= len(slots) <= 4` → `== 4`; the b-roll
  graph must use the shared zoom expression) and documented the
  `--set broll_query=...` / `plan.broll.query` topic hint that Hindi inserts need.

### Verified

16:9 tutorial render on the Hindi clip (`~/.vfe/proj-long2`, 4 m 11 s): **10/10
gates** — 53.768 s, 1920×1080 @30, −16.1 LUFS, −1.7 dBTP, 0 black, 0 freezes,
clean bottom captions (28 chars), 3 b-roll inserts, `motion=none`, `medium` ASR,
and `forge.py status` printing `final video: …`. 88 tests pass, doctor 17 PASS.

## 0.2.0 — 2026-11-28

A folder is now a shoot, not a single file: asset roles are classified, the
camera moves, topic b-roll is cut in, and `medium` is the ASR default. Verified
on the Hindi clip through both a 9:16 reel and a 16:9 long-form run.

### Folder inputs (`assets.py`, `ingest.py`, `plan.py`)

`forge.py init "<folder>"` (or `assets.py "<folder>"`) classifies every file:
`video` (talking head), `background` (art for a framed layout), `music` (bed),
`broll`, `overlay`, `subtitles`. The name decides the intent, the extension
decides the use — `background.wav` is a bed, `background.png` is art,
`background.mp4` is footage. Extra videos become b-roll instead of being
ignored, and unrecognised files are reported in `notes`. `plan` then folds the
roles in: bed under the voice, `layout = backdrop`, local inserts first.

### Camera motion (`camera.py`)

`zoom-in`, `zoom-out`, `pan-left`, `pan-right`, `tilt-up`, `tilt-down`,
`ken-burns`, `none` — a `zoompan` over a frame already cropped to the
deliverable aspect, bounded to ≤16 % zoom. On by default for short-form
playbooks, `none` for long-form (`--set motion=...` overrides). Measured on the
real run: ORB/affine median scale **1.070** with **23.8 px** drift per sample.

### Topic b-roll (`broll.py`)

Inserts land on sentence boundaries (hook and tail reserved), 1.5–2.4 s with
0.22 s alpha fades and their own slow zoom. Local folder assets are used first,
then Openverse/Wikimedia/NASA; credits go to `credits.md`; a non-commercial
licence fails the stage check. Two inserts landed at 12.09 s (local) and
40.39 s (Wikimedia, *Natives of northern India*, no restrictions).

### Medium is the default ASR

`asr.py --model` and `ensure.py --models` now default to `medium` (3/5 proper
nouns on the reference clip vs 1/5 for `small`); `--model small` and
`VFE_WHISPER_MODEL=small` remain the fast path. Install pre-downloads medium.

### Short-form look + final-path rule

- `caption.py --style kinetic`: one word, mid-frame, heavy outline, with
  `plan.captions.position` now respected (it was hard-wired to the CLI default).
- Every `forge.py run/status` reports the finished file, and `SKILL.md` requires
  every reply to end with `final video: <path>`.

### Bugs this pass found and fixed

1. **Camera shortened the video**: `zoompan` emits one frame per *input* frame,
   so a 25 fps source reached 30 fps by re-timing — 53.8 s became 44.8 s and the
   caption-tail gate failed. `fps=` now runs before `zoompan`.
2. **Music bed dragged loudness to −18.9 LUFS**: `amix` halved the voice after
   loudnorm and `dynaudnorm` compounded it. The mix now uses `normalize=0`, is
   measured as a mix, then normalised with those measurements (−14.4 measured).
3. **B-roll inserted nothing**: slot picking read `start`/`end` while transcripts
   emit `s`/`e`. Also added single-keyword and explicit-topic fallbacks, because
   multi-word Devanagari queries match Wikimedia titles poorly.
4. **Orphan merge ignored `max_words`**, re-joining one-word `kinetic` lines into
   2–5 words. Merge now respects both the width and word budgets.
5. **Backdrop was invisible**: the camera stage had already cropped to the
   deliverable, so a full-size contain covered the art. The shot is inset 8 %
   (6 % at 16:9) so `background.png` actually frames it.

### Verified

- **9:16 reel, folder input** (`~/.vfe/proj-demo2`, all 12 stages): **10/10
gates** — 53.768 s, 1080×1920 @30, −14.4 LUFS, −1.7 dBTP, 0 black, 0 freezes,
111 kinetic caption lines (max 17 chars), tail 53.05 s. 8 m 48 s end to end.
- **16:9 long-form** (`~/.vfe/proj-long`, tutorial playbook): **10/10 gates** —
1920×1080 @30, −16.1 LUFS, 0 black, 0 freezes, clean bottom captions (28 chars
max), `motion=none`, 3 inserts. 5 m 17 s.
- 88 tests pass, pyflakes clean, doctor 17 PASS / 0 FAIL.

### Known limits

- Hindi topic search needs an English hint (`plan.broll.query`, `--query`); the
  keyword path alone returns loose matches for Devanagari transcripts.
- Long-form camera motion stays off by default: it costs a re-encode per frame
  and reads as drift on a 40-minute talk.

## 0.1.8 — 2026-11-28

Simplification pass over what 0.1.6/0.1.7 added. No pipeline output changed: the
post-review run's SRT, ASS and transcript are byte-identical to the pre-review
run, with the same ten gates.

### Simplified

- **`scripts/caption.py`**: the width of a caption line was computed three ways —
  a nested `width()` inside `chunk_words`, an inline `len(" ".join(...))` in the
  orphan-merge condition, and the same join again in `safe_zone_ok`. One module
  helper, `line_width()`, now serves all three, and `safe_zone_ok()` collapsed
  from a loop into comprehension form.
- **`scripts/check.py`**: `find_captions()` listed every state artifact twice
  (`with_suffix(".srt")` and the identical `parent / (stem + ".srt")`).
  `caption_report()` no longer re-derives `.srt` from a path it was handed, and
  measures widest line, line count and last cue in **one pass** instead of
  reading the file twice. The `captions_missing` guard now tests
  `captions.enabled` instead of `lang not in ("none", None)`.
- **`tests/test_cut_caption.py`**: the merge and no-overflow tests used the same
  five-word fixture verbatim; they are one test asserting both directions.

Line counts: `caption.py` 258 → **254**, `check.py` 245 → **243**,
`tests/test_cut_caption.py` 113 → **108**; suite 65 → 64 (two tests merged).

### Left alone, deliberately

- `chunk_words()`'s over-long-token post-pass and the merge budget rule, the
  `no_repeat_ngram_size`/`repetition_penalty` options and the model-keyed
  transcript cache in `asr.py`: these are the behaviour the caption gates and
  the cache-correctness fix depend on.
- `plan.json`'s `captions.max_chars`: `clips.py` reads it for clip sidecars while
  `caption.py` derives its own budget from frame width. Unifying them would
  change clip caption widths — a behaviour change, not a simplification.
- `install/update.py --check`: inert (read-only is the default) but it is the
  documented spelling of that path in five documents.
- The 8-line HTTPS helpers duplicated between `ensure.py` and `update.py`: a
  shared module would add a file to save nothing.

### Verified

Fresh project (`~/.vfe/proj-final`) on the same clip with the shipped default
model (`small`): **10/10 gates**, 3 m 35 s, 1080×1920 @30, −14.5 LUFS,
−1.7 dBTP, 0 black runs, 0 freezes, captions 17 chars max, last cue 52.87 s.
Transcript text, `cut.srt` and `cut.ass` **byte-identical** to the pre-review
run; ASR 122 words / 11 segments; `caption_report` identical
(`max_chars 17, lines 41, last_end 52.87`). **64 tests pass**, pyflakes clean,
`agent-paste.md` current, doctor 17 PASS / 0 FAIL.

## 0.1.7 — 2026-11-28

`faster-whisper medium` downloaded and the same Hindi clip run through the whole
pipeline with it, then both models run again on identical code for a fair
comparison.

### medium vs small (same clip, `reel` preset, same code)

| | small | medium |
|---|---|---|
| model on disk | 484 MB | **1,528 MB** (fetched once, 97 s) |
| ASR stage | 50 s | 136 s |
| full run | 3 m 31 s | 5 m 06 s |
| words / segments | 122 / 11 | 118 / 14 |
| mean word probability | 0.617 | **0.697** |
| longest token | 9 chars | 14 chars |
| truth nouns recovered | **1/5** | **3/5** (बैगा, डिंडोरी, जाति) |
| caption lines | 41, max 17 chars | 43, max 17 chars |
| gates | 10/10 pass | 10/10 pass |
| loudness / true peak | −14.5 LUFS / −1.7 dBTP | −14.5 LUFS / −1.7 dBTP |

**medium is the better transcript.** It hears the speaker's name as
"लक्हुनाल" (small: "लखम्लाल"), gets डिंडोरी and जाति, and recovers the year —
"2007 से जुड़े हुए" — where small emitted "2 சாಲ" with a stray Tamil glyph. Its
word confidences are ~13 % higher and it produces no repetition loops (neither
model does now). It costs 86 s more ASR and ~1.5 min more per run. Both still
miss "लखनलाल" exactly: this is a 2007 field recording with dialect speech.

Transcript similarity between the two is low (difflib 0.112, token Jaccard
0.176), so the two models are not making the same mistakes — medium's extra
confidence is doing real work rather than re-phrasing the same confusion.

Captions from medium are transcribed, not written: `words.json` carries the
SHA-1 of the WAV cut from the clip, and the burn shows **6,766–12,163 changed
pixels** in the caption band at 8 of 9 sampled timestamps (the ninth is a gap
between lines).

### Fixed

- **The orphan merge could break the length budget**: `chunk_words()` appended a
  trailing single word to the previous line regardless of width, so medium's
  longer words produced a **37-char caption line** and the run failed the
  `captions <= 32` gate. It now merges only when the line still fits; a lone
  short word stays alone instead. Tests cover both directions.
- **The transcript cache ignored the model**: `asr.py` keyed `words.json` on
  audio hash + language, so re-running a project with `--model medium` silently
  reused the `small` transcript. The model is part of the key now. Verified
  both ways: with a medium transcript cached, `--model small` re-transcribed
  (42.7 s, 122 words, model recorded as `small`); repeating it hit the cache in
  0 ms.

### Verified

- Both runs: **10/10 gates**, caption lines max **17 chars**, 95 % of the spoken
  span captioned, 0 black runs and 0 freezes.
- **65 tests pass**, pyflakes clean, doctor 17 PASS / 0 FAIL, `agent-paste.md`
  current.

## 0.1.6 — 2026-11-28

Real-media re-verification at 0.1.5, then the simplification review. Same
Wikimedia Hindi interview as 0.1.2 (53.803 s, 1920×1080@25, vorbis 48 kHz), with
the models already on disk: faster-whisper `small`, rembg u2net, puppeteer
Chrome. Nothing was re-downloaded except the clip itself (the earlier work
directory had been cleaned).

### Measured (project `~/.vfe/proj-v15c`, `forge.py run`, defaults + `reel` preset)

| Stage | Result |
|---|---|
| ingest → probe | 4.6 s combined; 1080p25, no VFR/HDR, audio 2ch/48k |
| intake / plan | `reel`, hi, 9:16, bold-pop, tight, clean audio; 1080×1920 @30 |
| cut | 37 s; no silence ≥ 0.45 s, 53.8 s kept as one segment |
| asr | 50 s; faster-whisper 1.2.1, `small`, CPU int8, lang `hi`, **122 words / 11 segments**, 1.01–52.87 s, mean word prob 0.617, all Devanagari |
| caption | 34 s; **40 lines**, 8–25 chars, 3.05 words/line, 97 % of the spoken span captioned |
| audio | 11 s; PCM 24-bit/48 k intermediate, one AAC encode |
| export | 73 s; 1080×1920, 30 fps, 53.80 s, 42.2 MB, 6 278 kbps, AAC 48 kHz |
| check | 14 s; **10/10 gates pass** |
| total | 223 s for the whole forged run |

Gate values: duration 53.8 s, resolution 1080×1920, fps 30.0, audio 1 stream,
loudness **−14.5 LUFS** (target −14±1), true peak **−1.7 dBTP** (≤ −1), black
runs 0, freezes 0, caption max 25 chars (≤ 32), caption tail 52.87 s (inside
the video).

Captions are transcribed, not written: `words.json` carries the SHA-1 of the
WAV extracted from the clip's own audio, and all 40 caption lines start inside
detected speech (median and minimum overlap with `silencedetect` speech regions
= **1.000**, 0/40 starting in silence). The burn is in the pixels: comparing the
captioned file against the pre-burn cut at 12 timestamps shows 4 816–14 048
changed pixels (max diff 242–255) in the caption band every time.

Matte: rembg u2net, 42 masks at 480 px over a 10 s excerpt, 44.5 s, white and
black previews written. Motion: `kinetic-hook`, energy 0.69 (> 0.5), 6-char
text, no overflow, 14 s.

### Fixed by running it

- **Whisper looped on Hindi at `small`**: one segment repeated a token until it
  became a 113-character "word", which shipped as a 134-char caption line.
  `asr.py` now passes `no_repeat_ngram_size=3` + `repetition_penalty=1.1`:
  the same clip went from **50 words** (mean prob 0.632) to **122 words** with a
  9-char longest token; ASR costs ~35 s more (47 → 82 s standalone).
- **`check.py` never measured captions on a forged edit**: it looked for the SRT
  beside the *render*, while `caption.py` writes it beside the *cut*, so both
  caption gates silently disappeared — the 0.1.5 run reported 8 checks, all
  passing, with a 134-char line in the file. It now finds the sidecar through
  the state artifacts and reports `captions_missing` instead of skipping.
- **`caption.py` had no guard for one over-long token**: `chunk_words()` now
  splits any token wider than the budget, so the ≤32-char gate holds even when
  the recogniser produces garbage. Covered by a test.

### Cut

- `install/update.py`: dropped `commits_between()` (an extra GitHub compare call
  whose failure was swallowed, feeding only a cosmetic count), the second value
  of `apply_git()`'s tuple (never used), and `doctor_summary()`'s unused `exit`.
- `scripts/forge.py`: unreachable duplicate `plan` branch.
- `scripts/intake.py`: unused `json_mode` parameter on `_ask()`.
- Unused helpers: `_contract.emit_json`, `_paths.input_key`, `reframe._lerp`,
  `sheet.sheet_filter`, and the `math` import left behind in `sheet.py`.
- `INSTALL.md` §5 points at `SKILL.md` §11 for update behaviour instead of
  repeating it a second time.
- Kept deliberately: `update.py --check` (documented name for the default
  read-only mode), `--no-verify`, and the 8-line HTTPS helpers duplicated between
  `ensure.py` and `update.py` — a shared module for them would add a file to
  save nothing.

### Verified after the cuts

- `doctor.py`: 17 PASS, 0 FAIL (optional RVM/GPU WARNs only).
- **64 tests pass**, pyflakes clean, `agent-paste.md` current.
- Full forged pipeline re-run on the edited tree: **10/10 gates**, same numbers.

### Known limits

Hindi accuracy at `small` is still visibly wrong on proper nouns
("मेरा नां लखम्लाल, अगर्याल जाती बैगा…" for *मेरा नाम लखनलाल, अगिर्याल जाति बैगा*).
`medium` was materially better in 0.1.2 (129 words) but is not cached here, so it
was not re-downloaded.

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
- Copy mode on a **0.1.4 copy without `.git`**: `--check` reports
  `0.1.4 -> 0.1.5` and exits 2; `--apply` rewrites 3 files (127 unchanged)
  and the copy lands on 0.1.5 with its `edit/` work intact.
- Git mode on a clone one commit behind its origin: `--apply` fetches and
  fast-forwards to the new head; with a dirty tree it refuses (exit 3) and gives
  the fix instead of overwriting.
- **Route C** (`npx -y skills add sujeetcoder/video-vfx-editor -a claude-code -g -y`):
  copies all **130 tracked files** to `~/.claude/skills/video-vfx-editor`
  (667 KB, no `.git`, version 0.1.5), and that copy's own `update.py --check`
  reports up to date. Without `-y` the prompt stalls a non-interactive shell and
  the CLI exits 0 having installed nothing — `-y` is part of the command now.

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
