# Platform presets

**Read this when** choosing output specs or a duration limit.

| Preset | Size | FPS | Max | Video | Audio | Loudness |
|---|---|---|---|---|---|---|
| `reels` | 1080×1920 | 30 | 90 s | 6 Mbps | 192k | −14 LUFS |
| `shorts` | 1080×1920 | 30 | 60 s | 8 Mbps | 192k | −14 LUFS |
| `tiktok` | 1080×1920 | 30 | 180 s | 6 Mbps | 192k | −14 LUFS |
| `youtube` | 1920×1080 | 30 | — | 10 Mbps | 192k | −14 LUFS |
| `podcast` | 1920×1080 | 30 | — | 8 Mbps | 192k | −16 LUFS |
| `square` | 1080×1080 | 30 | 120 s | 6 Mbps | 192k | −14 LUFS |
| `feed` | 1080×1350 | 30 | 120 s | 6 Mbps | 192k | −14 LUFS |

Always: H.264 High, `yuv420p`, AAC 48 kHz, `+faststart`, true peak <= −1 dBTP.

## Notes

- Upload limits change; these are safe targets, not platform guarantees.
- 9:16 deliverables: keep captions out of the bottom 18 % (UI overlay).
- Vertical from horizontal always crops. `reframe.py` reports `crop_keep`; below
  0.55 switch to `contain` + blurred pad rather than losing the subject.
- For 4K sources, downscale with `lanczos` in one step; do not chain scalers.
