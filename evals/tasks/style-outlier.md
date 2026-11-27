# Flag an outlier reference

- category: `style`
- media: 3 refs, 1 different
- expected: outlier flagged, not averaged

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- outlier flagged, not averaged
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
