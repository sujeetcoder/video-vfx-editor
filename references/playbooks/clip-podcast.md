# Playbook: clips from a podcast

**Use when** a 10 min–3 h conversation must become 3–10 vertical clips.

## Spec

- 1080×1920, 30 fps, 15–90 s clips, loudness −14 LUFS
- layout `split` (speakers top, b-roll/screen below) or `fill`
- captions `bold-pop`, 2–3 words per line

## Selection

- sentence-snapped windows, 15–90 s, 5 s stride
- prefer self-contained stories with a hook in the first line
- reject windows that start with "and", "so", "but", "तो", "और"
- 5-signal table → agent ranks → **user approves**

## Editing per clip

1. tight cut, pad 120 ms
2. reframe to 9:16 with the active speaker centred
3. captions burned, hook line as a top overlay for 2 s
4. loudnorm to −14 LUFS, fades at the head/tail
5. sidecar + thumbnail + manifest entry

## Gates

hook ≤1.5 s · clean sentence start and end · speaker inside crop ·
caption not clipped at the tail · sidecar present · loudness ±1 LU
