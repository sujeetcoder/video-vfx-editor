# Cut a person out without green

- category: `matte`
- media: office interview clip
- expected: no holes, 540p mask on CPU, previews

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- no holes, 540p mask on CPU, previews
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
