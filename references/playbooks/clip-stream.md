# Playbook: clips from a stream

**Use when** the source is gameplay, IRL or a livestream VOD.

## Spec

- 1080×1920, 30 fps, 15–60 s clips
- layout `stream`: gameplay full-frame with the face cam inset, or `fill` for IRL
- loudness −14 LUFS, captions `bold-pop`

## Selection

- look for reaction peaks, clutch moments, punchlines, rage/quads
- sentence windows are unreliable here: also use scene cuts and audio energy
- reject clips that need the previous 30 s of context
- 6 clips is a good default; ask before exceeding 8

## Editing

1. start 0.4 s before the peak, end 1 s after the reaction settles
2. inset the face cam top-left with a 2 px border, never covering the HUD
3. game audio at −6 dB under the voice, ducked
4. captions on the voice only, not on game callouts

## Gates

peak inside the clip · face cam not covering critical HUD · clean start/end ·
loudness ±1 LU · no copyrighted music from the stream if the user cannot license it
