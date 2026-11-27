# video-vfx-editor

One agent skill that does **professional video editing and clipping** end to
end, on your own machine. Point your agent at a video and get either one
polished edit or 3–10 ready-to-post vertical clips — with measured quality
gates, Hindi captions by default, and no keys, no cloud render, no watermarks.

Works with Claude Code, Codex, OpenCode, Cursor, Gemini CLI, GitHub Copilot CLI
and Freebuff. Built for 100k+ context models.

## One-command start

```bash
python install/setup.py --agent all --install --yes
python install/doctor.py
```

Then tell your agent:

> Edit ./raw/podcast.mp4 — Hindi captions, 9:16, tight cut.
> Or: Clip this 1-hour podcast into 5 vertical shorts.

The agent asks 5–8 pre-filled questions and runs the pipeline.

## What it actually does

- **Cut**: removes silences and Hindi/English fillers, lossless-first, 30 ms fades
- **Captions**: word-level ASR → SRT + ASS, Devanagari shaping, 2–4 words/line, karaoke
- **Audio**: RNNoise/afftdn denoise, dehum, deess, ducking, 2-pass loudnorm (−14/−16 LUFS)
- **Chroma**: samples the real green, sweeps similarity × blend, despills, white/black QC
- **Matte**: person cutout without green screen (rembg / BiRefNet / RVM / SAM2)
- **Reframe**: 16:9 → 9:16 with face-tracked virtual camera and crop-loss guard
- **Clips**: sentence-snapped windows, 5-signal scoring table, agent ranks, you approve
- **Style**: learns 12+ facets from 3–5 references, then enforces tolerance
- **Motion/SFX**: HyperFrames bridge (Node) and earshot, both gated
- **Gates**: loudness, black/freeze, caption overflow, platform specs, contact sheets

## Requirements

Python 3.11+, FFmpeg with libass, Node 20+ (22 preferred). GPU optional:
CUDA and Apple MPS are used when present, CPU otherwise.

## Layout

```
SKILL.md          the agent-facing core loop
INSTALL.md        install instructions written for an agent
scripts/          one script per stage, every one speaks --json
references/       deep notes + 11 playbooks
install/          check-first installer, doctor, paste file
evals/            task suite and recovery tests
tests/            pytest for pure logic and golden filtergraphs
```

## Honesty notes

- Clip scores measure hook, pace and self-containedness — **not virality**.
- Style learning measures what it can see; unmeasured facets are labelled.
- URL ingest requires `--acknowledge-rights` and never touches playlists.

MIT (code) + CC-BY-4.0 (prose). See `LICENSE`.
