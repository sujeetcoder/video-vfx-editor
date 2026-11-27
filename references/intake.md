# Intake

**Read this when** asking the user questions or adding a preset.

## The bank (max 8 per round)

| id | default | why it exists |
|---|---|---|
| `job` | edit (clip if source >=10 min) | two different pipelines |
| `playbook` | auto | format recipe |
| `aspect` | from source / 9:16 | determines reframe + safe zones |
| `lang` | hi | captions (Devanagari) |
| `caption_style` | bold-pop | legibility + brand |
| `energy` | tight | silence/filler thresholds |
| `audio` | clean | denoise + loudnorm chain |
| `effects` | auto | chroma/matte/lower-third |

Every question carries `{id, header (<=12 chars), question, options[{label,
description, recommended}], default}` and is pre-filled from
`probe.py --quick` with a reason in `reasons`.

## Asking

`intake.py --json` returns the bank + detected answers. Present a numbered list,
mark the default with `*`, accept "ok". Never ask a second round unless the
first answer creates a genuine fork (e.g. `clip` with no transcript).

## Presets

`reel`, `podcast`, `tutorial`, `ad`, `clip`, `wedding`, `vlog` — see
`PRESETS` in `scripts/intake.py`. A preset is a starting point, not a lock.

## Never re-ask

`intake.py` reads `edit/decisions.md` and the existing `intake.json`. If a
question is already answered on disk, it is answered.
