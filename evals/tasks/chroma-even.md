# Key a well-lit green screen

- category: `chroma`
- media: green screen clip
- expected: coverage 65-85%, no green fringe

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- coverage 65-85%, no green fringe
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
