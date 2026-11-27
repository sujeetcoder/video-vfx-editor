# Playbook: podcast

**Use when** the source is a talking-head or two-person conversation.

## Spec

- 1920×1080, 30 fps; split layout when there are two speakers
- loudness −16 LUFS (long form), true peak −1 dBTP
- captions `clean`, bottom 8 % safe zone

## Structure

1. Cold open with the best 10–20 s from later in the episode (optional)
2. Keep the conversation order; do not manufacture drama
3. Trim only dead air, fillers, and repeated false starts
4. Chapter cards at topic changes if the user asked for chapters

## Editing

- `min_silence 0.7`, keep breaths (natural energy)
- speech-aware cutting: never cut mid-word; pad 120 ms
- no music under speech unless asked; if asked, −18 dB + ducking
- split layout: active speaker on top, listener small below

## Gates

loudness ±1 LU · no freeze >2 s · captions ≤32 chars · transcript covers >90 %
of speech · sidecar SRT written
