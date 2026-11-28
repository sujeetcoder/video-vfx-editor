# AGENTS.md

This repository is the **video-vfx-editor** skill: local video editing and
clipping with FFmpeg + Python + Node. No API keys, no cloud render.

If you are an agent asked to install or use this skill:

1. Read `INSTALL.md` and follow it exactly. It is written for you, not a human.
2. Verify with `python install/doctor.py --json` before editing anything.
3. Use the workflow in `SKILL.md`; state lives in `edit/state.json`.
4. Resume a job with `python scripts/forge.py resume --json`.
5. When the user says the skill changed on GitHub, update it with
   `python install/update.py --apply --json` (never hand-edit the installed copy)
   and restart the session so `SKILL.md` reloads.

Folder name must stay `video-vfx-editor` (the skill id comes from it).
