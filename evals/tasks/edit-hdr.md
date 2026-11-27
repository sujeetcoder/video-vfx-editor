# Edit an HDR clip without washing out

- category: `edit`
- media: HLG clip
- expected: no magenta/green cast, tone mapped

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- no magenta/green cast, tone mapped
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
