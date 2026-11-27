# Captions

**Read this when** captions are missing, shaped wrong, overflowing, or the user
wants a different look.

## Pipeline

`asr.py` → `words.json` (`{w, s, e, p}`) → `caption.py` → `.srt` + `.ass` →
`export.py`, or `caption.py --burn` burns them with libass.

## Rules

- 2–4 words per line, **<=32 characters**, never a single orphan word.
- Lines break at punctuation when possible; `.` / `!` / `?` / `।` close a line.
- Safe zone: bottom 18 % of a 9:16 frame, 8 % of 16:9. Never put text under the
  platform UI strip.
- Devanagari needs libass + a Devanagari font (`Noto Sans Devanagari`, OFL).
  `fontsdir` is passed explicitly, so a missing system font is not fatal.
- Karaoke uses a `\k` tag with centiseconds per word inside one Dialogue line.

## Styles

| Name | Look | Use |
|---|---|---|
| `bold-pop` | uppercase, heavy outline, yellow highlight | reels/shorts |
| `clean` | sentence case, thin outline | podcasts, tutorials |
| `karaoke` | one word highlighted as spoken | music, teaching |

Colours are ASS `&HAABBGGRR`. Keep the outline >=4 at 1080p for legibility.

## Hindi / Hinglish

- Always a **multilingual** whisper model. A `.en` model cannot output Hindi.
- Default language `hi` → Devanagari output.
- `hinglish` transcribes Hindi and asks for Roman script; Whisper may still
  emit Devanagari. Convert explicitly and review before burning; do not pretend
  the conversion is automatic.
- `initial_prompt` is set per language in `asr.py`; keep it short.

## Verification

`caption.py` reports line count and over-length lines. `check.py` re-checks the
rendered file: max chars, last caption ending inside the video, and that the
sidecar `.srt` exists.
