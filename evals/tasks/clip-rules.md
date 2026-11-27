# Deterministic --rules top-3

- category: `clip`
- media: long source
- expected: 3 clips, rule-ranked labelled

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- 3 clips, rule-ranked labelled
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
