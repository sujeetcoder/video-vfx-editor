# Remove Hindi fillers (matlab, yaani, toh)

- category: `edit`
- media: monologue with fillers
- expected: fillers gone, sentence intact

## Steps

1. `python install/doctor.py --json` (record failures, do not hide them)
2. run the matching pipeline from `SKILL.md`
3. `python scripts/check.py <output> --json`

## Pass criteria

- fillers gone, sentence intact
- every check has a value and a target
- failures come with a fix, never a bare traceback

## Result

| status | notes |
|---|---|
| not run | record honestly |
