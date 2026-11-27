# Edit a VFR phone video

- category: `edit`
- media: iPhone HEVC VFR clip
- expected: fps normalised, no A/V drift

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- fps normalised, no A/V drift
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
