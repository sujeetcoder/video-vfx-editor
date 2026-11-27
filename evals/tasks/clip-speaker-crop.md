# Keep the speaker inside 9:16

- category: `clip`
- media: wide two-person podcast
- expected: crop_keep >=0.55

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- crop_keep >=0.55
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
