# Style learning

**Read this when** the user says "train skill video-vfx-editor on these links".

## Input

3–5 references: local files or links (links go through `ingest.py` with rights
acknowledgement). Fewer than 3 → say the confidence is low, do not refuse.

## What gets measured (never described)

cut rhythm (cuts/10 s), shot-length distribution, camera-move energy (YDIF),
colour grade signature (YAVG/UV), caption metrics from a sidecar `.srt`
(words/line, max chars, uppercase ratio), audio loudness, duration, fps.

**Unmeasured facets** are listed explicitly in the profile: caption position,
exact font, transitions, b-roll ratio, end card, shot types, hook structure.
Do not invent numbers for them.

## Confidence

<10 samples → low, 10–15 → medium, 15+ → high. Print the tier next to every
number. Two references is "low": still useful, still labelled.

## Outliers

Per-facet z-score > 2 is flagged in `rhythm.outliers` and excluded from the
tolerance. Never silently averaged in.

## Apply + compare

`style.py apply` clamps loudness, caption style and shot length inside the
profile. `check.py` reports deviation: `cut_rhythm 4.6 vs 3.4±0.8 — FAIL`.

## Privacy

Reference files stay in the private study folder, are never re-uploaded, and
music is never copied or redistributed.
