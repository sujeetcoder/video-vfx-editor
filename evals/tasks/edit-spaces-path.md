# Edit a file with spaces and Hindi name

- category: `edit`
- media: C:/clips/मेरा वीडियो final.mp4
- expected: completes without quoting errors

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- completes without quoting errors
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
