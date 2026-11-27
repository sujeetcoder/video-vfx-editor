# Place 3 SFX at cut points

- category: `sfx`
- media: any clip
- expected: 3 placed, -18 dB, budget respected

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- 3 placed, -18 dB, budget respected
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
