# Audio

**Read this when** the voice is noisy, humming, quiet, or the music fights it.

## Chain order (one pass)

`afftdn` (or `arnndn`) → `highpass=f=80` → dehum EQs (50/60 Hz, q=2, −14 dB) →
`deesser` → `loudnorm`.

Denoise before EQ, EQ before loudness. Never normalise first: you would amplify
the noise you are about to remove.

## Loudness

- Reels/Shorts/TikTok: **−14 LUFS**, true peak **<= −1 dBTP**
- Podcast/YouTube long form: **−16 LUFS**
- Two-pass `loudnorm`: measure (`print_format=json`), then apply with
  `measured_I/TP/LRA/thresh` and `linear=true`.
- Single-pass `loudnorm` is acceptable for clips (speed) but `check.py` measures
  the result and fails outside ±1 LU.

## Ducking

`sidechaincompress=threshold=0.05:ratio=8:attack=20:release=400` with the voice
as the sidechain. The music bed sits at −18 dB before ducking; about 1.5 dB of
gain reduction is enough, more sounds pumpy.

## SFX levels

−18 dB under voice, 20 ms fades, never on every cut. Budget from the style
profile (`sfx_per_min`), default 2–4/min.

## Checks

`check.py` measures integrated loudness and true peak on the **rendered** file,
not the filter settings. A failed loudness gate means re-run `audio.py`.
