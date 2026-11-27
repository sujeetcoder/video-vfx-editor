# 5 clips from a 1 h Hindi podcast

- category: `clip`
- media: 1 h podcast
- expected: 5 clips, sidecars, hook <=1.5 s

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- 5 clips, sidecars, hook <=1.5 s
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
