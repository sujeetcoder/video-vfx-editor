# Recovery: stale-lock

Create edit/.cut.lock with an old mtime (>10 min). Expected: forge breaks it with a warning and continues; a fresh lock stays and exits 6 with the stale-lock doc.
