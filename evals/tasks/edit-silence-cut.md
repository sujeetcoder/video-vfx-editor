# Remove silences from a 3 min monologue

- category: `edit`
- media: 3 min monologue with pauses
- expected: cut >=20% shorter, no clipped words

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- cut >=20% shorter, no clipped words
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
