# Normalise to -14 LUFS

- category: `edit`
- media: any voice clip
- expected: measured -14 ±1 LUFS, TP <= -1 dBTP

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- measured -14 ±1 LUFS, TP <= -1 dBTP
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
