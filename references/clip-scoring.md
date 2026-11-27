# Clip scoring

**Read this when** ranking candidates or explaining a score.

## Five local signals

| Signal | Weight | Measured from |
|---|---|---|
| speech | 0.28 | words per second vs the whole transcript |
| pace | 0.18 | words per second inside the window |
| hook | 0.24 | Hindi + English hook markers in the first lines |
| self_contained | 0.20 | does it open with a conjunction? |
| external | 0.10 | position in the video, duration fit |

`score = sum(signal * weight)`, rounded to 3 decimals. All five values are
stored in the sidecar; never reorder candidates without recording them.

## Agent ranking

The table is <=30 rows (~1.2k tokens): id, in–out, seconds, score, the five
signals, hook line. Rank for the user's goal, not the raw score: a cooking clip
with a strong hook can beat a higher-scored rant.

## Hard pre-filters

- under 15 s or over 90 s → drop
- opening word is a conjunction → penalise
- no speech for >60 % of the window → drop
- duplicate window (<5 s shift) → drop

## `--rules`

Deterministic top-N by score. Use it when the user says "just pick them" or no
agent ranking is available. Label the output as rule-ranked.
