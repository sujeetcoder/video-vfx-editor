# Burn Hindi captions on a talking-head clip

- category: `edit`
- media: any 30-90 s Hindi talking head
- expected: Devanagari renders, no tofu, <=32 chars/line

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- Devanagari renders, no tofu, <=32 chars/line
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
