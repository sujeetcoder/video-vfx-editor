# Shoot folders, camera motion, b-roll

How a folder of assets becomes an edited cut, and which of the reference-reel
effects this skill reproduces itself.

## 1. A folder is a shoot, not a pile of files

Point `forge.py init` (or `assets.py`) at a directory and the files are classified
before anything is rendered:

| file (by name, then extension) | role | used as |
|---|---|---|
| `video.mp4`, `main.*`, `source.*`, `hero.*`, `talk*`, `interview*` | `video` | the talking head cut |
| `background.png`, `bg.jpg`, `backdrop.*`, `wallpaper.*` | `background` | art behind a contained frame (replaces black bars) |
| `background.wav`, `music.*`, `bgm.*`, `bed.*`, `theme.*`, `soundtrack.*` | `music` | bed, side-chain ducked under the voice |
| `b-roll/`, `broll*`, `cutaway*`, `insert*`, other videos/images | `broll` | insert material, local assets used before any download |
| `logo.png`, `watermark.*`, `brandmark.*` | `overlay` | reserved for `graphics.py`; reported, not auto-placed |
| `*.srt`, `*.ass`, `*.vtt`, `captions.*`, `subs.*` | `subtitles` | reported; the pipeline still transcribes with ASR |

Rules that matter:

- **Extension decides the use once the name decides the intent.** `background.wav`
  is a music bed, `background.png` is a backdrop, `background.mp4` is footage (kept
  as b-roll, with a note) — the same word, three different jobs.
- **One video is the subject.** A named video wins; otherwise the longest one does.
  Every other video becomes b-roll rather than being ignored.
- **Nothing is dropped silently.** Unsupported files and extra audio are listed in
  `assets.json` `notes` and printed by `assets.py`.

```bash
python scripts/assets.py "C:/clips/shoot" --json        # table + roles, writes work/assets/assets.json
python scripts/forge.py init "C:/clips/shoot" --job edit # ingests the folder, keeps the roles
```

`probe` → `intake` → `plan` fold the roles in: the bed lands in
`plan.audio.music`, the backdrop sets `plan.layout = "backdrop"` when the source
aspect differs from the deliverable, and the local b-roll list is handed to the
insert stage. `export.py --background art.png` uses the image explicitly.

## 2. Camera motion (`camera.py`)

A `zoompan` on a frame already cropped to the deliverable aspect, so the move ends
in a finished 9:16 shot and `export` does not reframe twice. Bounded to ≤16 % zoom,
so a 1080-wide source never drops below ~930 px.

| preset | move |
|---|---|
| `zoom-in` / `zoom-out` | 1.00 → 1.14 / 1.14 → 1.00 |
| `pan-left` / `pan-right` | constant 1.16 zoom, drift across the frame |
| `tilt-up` / `tilt-down` | constant 1.16 zoom, vertical drift |
| `ken-burns` | 1.05 → 1.16 with a diagonal drift |
| `none` | pass-through copy |

Playbook defaults: `reel`, `ad`, `vlog`, `presenter`, `music`, `wedding`,
`clip-stream` get a move; `youtube`, `tutorial`, `podcast`, `clip-podcast`,
`clip-lecture` stay still. **Long form keeps its frame still on purpose** — a
40-minute tutorial with a drifting camera reads as a mistake, and re-encoding
1612+ frames through `zoompan` costs more than it returns. `--set motion=zoom-in`
still works if a specific long-form cut wants it. Override with
`plan.py ... --set motion=pan-right` (or `motion=none`). The stage records the
measured scale via ORB/affine sampling in `camera.mp4.json`; a move that does not
move is a warning, not a silent pass.

## 3. B-roll from what is being said (`broll.py`)

1. Sentence boundaries come from `words.json`; the hook (first 1.5 s) and the last
   1.5 s are left alone.
2. Local folder assets are consumed first, in order.
3. Then a query is built from that sentence's own keywords (RAKE-style, same
   helper as `stock.py --from-transcript`) and searched on Openverse, Wikimedia
   and NASA — no keys, no accounts.
4. Each insert is 1.5–2.4 s, full-frame, fading over 0.22 s with its own slow zoom
   so a still reads as footage. Credits go to `credits.md`.

Non-commercial and no-derivative licences are never used (`stock.BAD_LICENSES`),
and the stage fails its `licences` check rather than sneaking one in.

**Non-English audio needs an English topic hint.** Devanagari keywords match
Wikimedia file titles loosely (a search for a spoken word can return an unrelated
painting), so pass the subject explicitly:
`plan.py ... --set broll_query="baiga tribe village india"` stores it as
`plan.broll.query`, and every insert then searches that topic. Without a hint the
stage still falls back to per-sentence keywords, whole query first then its two
strongest words.

```bash
python scripts/broll.py camera.mp4 --count 2 --json          # topic queries per sentence
python scripts/broll.py camera.mp4 --query "village market" --json
```

## 4. Captions for short-form

`--style kinetic` (one word, mid-frame, heavy outline) is the look both reference
reels use; `bold-pop` (2–4 words, bottom) stays the default so existing runs do
not change. `plan.json` sets `captions.words_per_line = [1, 1]` and
`captions.position = "middle"` automatically for `kinetic`, and `caption.py`
follows the plan unless `--position` overrides it.

## 5. The two reference reels, measured

`https://youtube.com/shorts/PnISBQvued4` (86 s) and
`https://youtube.com/shorts/q-hw7JQd594` (51 s), 1080×1920 @30 fps. Measured with
`style.measure_ref`: **54 and 51 cuts per minute** — a new shot roughly every
1.1 s — heavy graphic density, one-word captions, slow zoom on the speaker.

| effect in the reels | where it lives here |
|---|---|
| slow breathe / zoom on the speaker | `camera.py` `ken-burns` |
| one-word kinetic captions | `caption.py --style kinetic` |
| full-frame graphic / screen-recording cards | `broll.py` inserts, `packs/motion/*` |
| "STEP 1/4" pills, prompt bar, counter chips | `graphics.py` + `packs/motion` |
| cut-out subject over coloured "paper" | `person_matte` + `background.png` backdrop |
| text behind the subject | `person_matte` + title layer (matte, not fake blur) |
| ~1.1 s cut rhythm | `plan.cut.target_shot_len`, `--energy tight` |

What is *not* replicated: the reels' bespoke motion graphics (each is a hand-built
composition in HyperFrames) and object removal ("ghadi se graphics nikaal"). The
skill matches the edit grammar — rhythm, camera, captions, inserts — not their
custom artwork.
