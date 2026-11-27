# video-vfx-editor — Freebuff edition

**Name:** video-vfx-editor
**Description (<=1024 chars):** Local professional video editing and clipping:
silence and filler cuts, Hindi (Devanagari) captions, chroma key, person matte,
9:16 reframe with a face-tracked virtual camera, highlight clip finding with a
5-signal score, style learning from reference videos, motion graphics, sound
design, and measured quality gates. Use for editing video, clipping podcasts or
streams, subtitles, shorts, reels, removing background, and platform exports. No
API keys, no cloud render, no watermarks.

## Instructions

You are running inside Freebuff on the user's own computer. Work in the user's
project folder; every script writes only under `edit/`.

1. `python install/doctor.py --json` — if a capability is missing, give the
   exact `fix` for the user's OS. Do not install system packages without asking.
2. Follow `SKILL.md` for the core loop and `INSTALL.md` for setup.
3. Prefer the workflow state machine:

```bash
python scripts/forge.py init "<file>" --job edit --json
python scripts/forge.py next --json
python scripts/forge.py run --json
python scripts/forge.py resume --json
```

4. Ask 5–8 intake questions maximum, pre-filled from `probe.py --quick`.
5. For clip jobs, present the candidate table and wait for approval
   (`forge.py approve 1 4 7`) before any render.
6. Finish by running `scripts/check.py` and quoting the measured numbers; state
   clearly what was not tested.

Freebuff-specific notes:

- The Terminal and file tools run on the user's machine, so FFmpeg/Node are
  local. Loopback dev servers are irrelevant here; nothing is served.
- Long renders block the turn: run them as background commands and say you will
  not be notified when they finish.
- Use `--dry-run` first when the user only wants to see the plan.
- Never push a git remote or publish anything without explicit permission.
