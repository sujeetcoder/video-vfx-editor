# Clip a YouTube link

- category: `clip`
- media: public 20 min video
- expected: rights acknowledged, 3+ clips

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- rights acknowledged, 3+ clips
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
