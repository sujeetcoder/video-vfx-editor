# Clipping

**Read this when** turning a long video into shorts.

## Flow

1. `ingest.py <url|file> --acknowledge-rights` (YouTube ToS; no playlists)
2. `probe.py --quick`
3. `intake.py --preset clip`
4. `asr.py --lang hi` (word-level)
5. `plan.py --job clip` → sentence-snapped windows + `candidates.json`
6. **Agent ranks the table, user approves** (`forge.py approve 1 4 7`)
7. `clips.py --from-plan` → renders + sidecars + manifest + review.html

## Windowing

Sentences, not timestamps. 15–90 s, 5 s stride, pre-filtered to 20–40
candidates. A clip must start on a sentence and end on a sentence — never
mid-word.

## Layouts

- `fill`: crop to 9:16, speaker centred (default)
- `split`: speaker on top, b-roll/screen below
- `stream`: gameplay/screen with the face cam inset

## Sidecar (never optional)

`clip_NN.json` contains score, all five signals, hook line, one-line reason,
source in/out, transcript, device, credits. `manifest.json` aggregates them.

## Honesty

The score measures clip strength. It is **not** a virality prediction. Say that
in the report and in the manifest note.

## Refusals

`clips.py` will not render without `intake.json`, and will not render
unapproved candidates unless `--allow-unapproved`. Keep it that way.
