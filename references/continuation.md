# Continuation (model switch mid-job)

**Read this when** you are a fresh model picking up someone else's project.

1. `python scripts/forge.py resume --json` prints and writes `edit/handoff.md`
   (<=1.5k tokens): project, job, style, DONE list, NOW stage, last error, exact
   NEXT command, only the files you need.
2. Read only the files listed. Do not re-read the whole repo.
3. Do not re-ask intake questions: they are in `edit/decisions.md`.
4. Do not hand-edit `plan.json`; re-run `plan.py` with the new answer.
5. Three failures on one stage → stop and ask the user.

## State schema

`edit/state.json` is versioned (`schema: 1`) with stages, artifacts, params,
locks, errors, device and timestamps. An older schema is migrated automatically
with a warning.

## Locks

`edit/.<stage>.lock` breaks after 10 minutes with a warning. Never delete a
fresh lock; another run may be alive.

## Immutability

`edit/out/run-<id>/` is never overwritten. A resumed run writes a new run id, so
hashes can be compared instead of trusting memory.
