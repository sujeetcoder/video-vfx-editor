# INSTALL — instructions for an AI agent

You are installing **video-vfx-editor** for the user. Do these steps in order.
Do not skip the check step, and do not install anything that already exists.

## 1. Check the machine (read-only, safe)

```bash
python install/ensure.py --check --json
python install/doctor.py --json
```

Both print one JSON object. `doctor.py` gives a `checks` list; every failed or
warned check has a `fix`. Report the table to the user, then continue.

Required: Python **3.11–3.13** (CPython **3.12.16** is provisioned for you when
the default interpreter is outside that range), FFmpeg with `libass` + `ffprobe`,
Node **20+** (22 preferred). Optional: Chrome/Edge (motion graphics), `yt-dlp`
(URL ingest). The installer also adds faster-whisper (captions), rembg +
onnxruntime (person matte) and puppeteer (motion). Everything it adds is
**user-local: no admin, no sudo, no PATH edits**.

## 2. Install only what is missing

```bash
python install/ensure.py --install --yes     # non-interactive
python install/ensure.py --install           # asks before system-wide installs
```

Rules this tool follows (and you must too):

- user-local first: `pip --user`, `~/.local/bin`, nvm/fnm
- ask before anything system-wide; **never** run sudo/doas/pkexec yourself
- idempotent: running it three times changes nothing
- on Linux, if `apt-get` is needed, print the command for the user to run

What `--install` provisions, and where (all under your home directory):

| Component | Location | How |
|---|---|---|
| CPython 3.12.16 + venv | `~/.vfe/python`, `~/.vfe/venv` | `uv python install 3.12.16` |
| FFmpeg 9 (libass, zscale) | `~/.vfe/bin` | gyan.dev build, **SHA-256 verified** |
| Node 22 LTS | `~/.vfe/node` | nodejs.org zip (no MSI, no admin) |
| pip packages | inside `~/.vfe/venv` | numpy, OpenCV, Pillow, yt-dlp, faster-whisper, rembg, onnxruntime |
| puppeteer + Chrome | global npm, `~/.cache/puppeteer` | `npm install -g puppeteer` |
| OFL fonts | `assets/fonts` or `~/.vfe/fonts` | Google Fonts |

If a venv was provisioned, run the skill scripts with **its** interpreter.
`ensure.py` prints the exact path:

```text
Windows:  %USERPROFILE%\.vfe\venv\Scripts\python.exe
macOS/Linux:  ~/.vfe/venv/bin/python
```

The bootstrap only triggers for unsupported interpreters (for example Python
3.15, which has no wheels for numpy/onnxruntime/ctranslate2). On Python
3.11–3.13 the tool uses the interpreter you already have and installs packages
with `--user`.

OS fallbacks when a package manager is unavailable:

| Tool | Windows | macOS | Linux |
|---|---|---|---|
| FFmpeg | automatic portable build in `~/.vfe/bin` (SHA-256 verified); or `winget install Gyan.FFmpeg` | `brew install ffmpeg` (full build for libass) | `sudo apt install ffmpeg` (user runs it) |
| Node | automatic portable Node 22 in `~/.vfe/node`; or `winget install OpenJS.NodeJS.LTS` | `brew install node@22` | `nvm install 22` |
| yt-dlp | `python -m pip install --user -U yt-dlp` | same | same |

macOS libass: `brew install ffmpeg-full` then
`export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"`.

No package manager, or a locked-down machine? A portable FFmpeg/ffprobe placed in
`~/.vfe/bin/` is detected automatically (no PATH edit, no admin rights): unzip a
static build there and run `python install/doctor.py` again.

## 3. Fonts (Devanagari is the default caption language)

```bash
python install/ensure.py --install --fonts
```

Downloads OFL Noto Sans Devanagari + Inter into `assets/fonts/` (or
`~/.vfe/fonts/`). If the download is blocked, install any Devanagari font
system-wide (Windows: Nirmala UI ships with the OS) and note it in the report.

## 4. Link the skill into the agent(s)

```bash
python install/setup.py --agent all            # project scope
python install/setup.py --agent all --global   # home scope
python install/setup.py --list                 # where each agent looks
```

| Agent | Project path | Global path |
|---|---|---|
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| Codex | `.agents/skills/` | `~/.agents/skills/` |
| OpenCode | `.opencode/skills/`, `.claude/skills/`, `.agents/skills/` | `~/.config/opencode/skills/` |
| Cursor | `.agents/skills/`, `.cursor/skills/` | `~/.cursor/skills/` |
| Gemini CLI | `.agents/skills/` | `~/.gemini/skills/` |
| Copilot CLI | `.agents/skills/` | `~/.copilot/skills/` |

Windows without Developer Mode cannot symlink; `setup.py` copies instead and
says so. The folder name must be exactly `video-vfx-editor`.

## 5. Updating an installed copy

When the repo changes on GitHub, an agent can be told *"update the
video-vfx-editor skill"* and should run:

```bash
python install/update.py --check --json    # read-only; exit 2 = newer commit
python install/update.py --apply --json    # update this folder, then doctor
```

`edit/` work, `.git`, models and `~/.vfe` are never touched, a dirty checkout is
refused, and upstream deletions are reported as `leftover` rather than removed.
Add `--agent all --global` to re-link the agent folders. `SKILL.md` §11 is the
canonical description; restart the agent so it reloads `SKILL.md`.

## 6. The six install routes

| Route | Command | Tested here |
|---|---|---|
| A. Agent reads this file | "Install github.com/sujeetcoder/video-vfx-editor, read INSTALL.md and follow it" | yes (this file) |
| B. Paste/upload | copy `install/agent-paste.md` into a skills UI (Freebuff) | yes (file generated) |
| C. skills CLI | `npx -y skills add sujeetcoder/video-vfx-editor -a claude-code -g -y` | yes: all 130 files copied to `~/.claude/skills/video-vfx-editor`; **`-y` is required** — without it the prompt blocks a non-interactive shell and the command exits 0 having installed nothing |
| D. Plugin marketplace | `/plugin marketplace add sujeetcoder/video-vfx-editor` then `/plugin install video-vfx-editor@video-vfx-editor` | not run |
| E. Manual | `git clone` then `python install/setup.py --agent all` | yes |
| F. OpenCode | `npx -y skills add ... -a opencode -g -y`, or copy to `.opencode/skills/video-vfx-editor` | not run (the CLI itself is exercised by route C) |

Mark honestly in your report which routes you exercised. Do not claim "works"
for a route you did not run.

## 7. Verify before the first job

```bash
python install/doctor.py --json
python scripts/probe.py --help
python scripts/forge.py init "test.mp4" --job edit --json
```

Acceptance: `doctor` exits 0 (or lists exact FAIL fixes) with Python
`3.11–3.13` (3.12.16 when provisioned), `scripts/*.py --help` all work, and
`edit/state.json` is created. Then start with `SKILL.md`.

## 8. Locked decisions (do not change without asking)

1. Repo/skill name `video-vfx-editor`; folder name identical.
2. 100k+ context models only — no small-model or "safe" mode.
3. Python 3.11–3.13 (3.12.16 when the installer provisions it), FFmpeg and Node 22
   are all required.
4. `--device auto`: CUDA → MPS → CPU, one CPU retry on OOM.
5. Check first, install only what is missing, never reinstall, ask for system installs.
6. Captions default Hindi (Devanagari); Hinglish and English optional.
7. Stock: no-key sources only (Openverse, Wikimedia, NASA); Pixabay only with a user key.
8. Six install routes; only the tested ones are marked tested.
9. Zero paid APIs, zero cloud render, zero telemetry, no watermarks.

## 9. Uninstall

Delete the linked folder (`<skills dir>/video-vfx-editor`). To reclaim disk,
the user-local runtime can go too — nothing here was installed system-wide and
the installer never runs sudo:

```text
~/.vfe            CPython 3.12.16 + venv, portable FFmpeg, Node, fonts
~/.rembg          u2net matte model
~/.cache/huggingface   whisper models
~/.cache/puppeteer     Chrome for motion graphics
```
