# Resume after a model switch

- category: `recovery`
- media: half-finished project
- expected: handoff <=1.5k tokens, correct next

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- handoff <=1.5k tokens, correct next
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
