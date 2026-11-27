# Sound design

**Read this when** adding whooshes, ticks, impacts, risers or a music bed.

## earshot bridge

`sfx.py suggest|make|place` shells to earshot (CPU by design). Not installed →
`missing_capability`; `--synth` is an explicit, logged FFmpeg fallback, never a
silent one.

## Placement

- whoosh: on a hard cut, −18 dB, 20 ms fades
- tick: on a word accent, −20 dB
- impact: on a section change, −16 dB, once per 10 s max
- riser: 0.6–1.2 s into the hook, ends exactly on the cut

Respect the style budget (`sfx_per_min`, default 2–4). More than that reads as
amateur.

## Music

Bed at −18 dB, ducked 1.5 dB under the voice with `sidechaincompress`. Never
copy the reference track; suggest a licence-clean alternative.

## Mix check

Voice −14 LUFS integrated, true peak <= −1 dBTP, SFX at least 12 dB under the
voice. `check.py` measures the render.
