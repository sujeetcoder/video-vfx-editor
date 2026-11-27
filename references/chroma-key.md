# Chroma key

**Read this when** the source has a green/blue screen, uneven lighting, or the
key looks crunchy.

## The 8 steps (never reorder)

1. **Sample** the real background from border pixels (top strip, 64 px wide,
   k-means k=3). Use the cluster that is greenest: `g - max(r,b) >= 12`.
2. **Key** with `chromakey=0xRRGGBB:similarity:blend`. Start from the sweep,
   never from a remembered number.
3. **Sweep** similarity 0.06–0.30 × blend 0.02–0.12 on a 0.6 s sample. Measure
   mean alpha with `alphaextract,signalstats`. Aim for **65–85 %** coverage:
   below 65 % the subject becomes transparent, above 85 % green survives.
4. **Despill AFTER the key**: `despill=type=green:mix=0.5`. Doing it before
   contaminates the key colour.
5. **Choke / feather** the edge: `morpho=mode=erode:planes=1:structure=3x3`
   then a 0.2 sigma blur on the alpha.
6. **Garbage matte** with a crop when lights/stands intrude.
7. **Composite background first**, person second: `[bgv][fg]overlay`.
   Never the other way round.
8. **QC** on white **and** black. Green fringe hides on black, halos hide on
   white. `chroma.py` writes both previews automatically.

## Uneven light

- Use wider similarity or pre-level the plate.
- If the floor bounces green onto the subject, raise despill mix to 0.6–0.7 and
  accept slightly desaturated skin; do not key harder to fix bounce.

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| subject see-through | similarity too high | lower similarity by 0.04 |
| green halo | despill missing or too low | `--despill 0.6` |
| jagged edge | source is 8-bit 4:2:0 | 2 px alpha blur, or shoot 4:2:2 |
| key flickers | auto-gain / rolling shutter | sample per scene, or use matte.py |
| hair disappears | blur too strong | keep feather <=0.2 sigma at 1080p |

If the shot has no clean green, `scripts/matte.py` is the right tool.
