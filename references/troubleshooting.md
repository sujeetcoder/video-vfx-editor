# Troubleshooting

Every error object points at an anchor here.

## ffmpeg
`ffmpeg` missing or ancient. Windows: `winget install Gyan.FFmpeg`. macOS:
`brew install ffmpeg`. Linux: install it with your package manager as
administrator — this tool never elevates privileges.
Verify: `ffmpeg -version` and `ffprobe -version`.

## libass
The `subtitles` filter is missing → captions cannot burn. macOS:
`brew install ffmpeg-full && export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"`.
Windows: use a Gyan full build, not "essentials". Check `ffmpeg -filters` and
look for `subtitles`.

## zscale
HDR-safe scaling is missing in minimal builds. Either install a full build or
let the pipeline use plain `scale` (colours may shift on HDR input).

## node
Node <20 or missing blocks motion graphics. `node -v`, then
`winget install OpenJS.NodeJS.LTS` / `brew install node@22` / `nvm install 22`.
`npm i -g puppeteer` for the renderer. Nothing else in the skill needs Node.

## yt-dlp
URL ingest fails on age/region locks: `pip install --user -U yt-dlp` then
`--cookies-from-browser chrome`. URL jobs require `--acknowledge-rights`.

## asr
No backend → `pip install --user faster-whisper`. PyAV 19 removed the
`metadata_errors` argument that faster-whisper 1.2.x still passes, so a fresh
install can die with `open() got an unexpected keyword argument
'metadata_errors'`; `asr.py` drops that kwarg at runtime (the upstream fix),
and `pip install "av<19"` is the other way out. Model download blocked →
pre-download once, set `VFE_WHISPER_MODEL`. Hindi on noisy field audio: `medium`
is much better than `small` (`VFE_WHISPER_MODEL=medium`). CUDA OOM → the script
retries once on CPU int8. Empty transcript → the source is silent; check
`probe.py --loudness`.

## devices
`--device cuda` on a machine without CUDA is an error, not a silent fallback.
Check `doctor.py`. A GPU that exists but is unusable → the stage logs a warning
and retries once on CPU.

## stale-lock
`stage is locked` → wait, or delete `edit/.<stage>.lock` if you know no run is
alive. Locks auto-break after 10 minutes.

## corrupt-input
`ffprobe cannot read ...` or 0 bytes → the file is broken. Try
`ffmpeg -i in -c copy out.mp4`; if that fails, re-export or re-download.

## rights
URL ingest requires `--acknowledge-rights`: you own the video or have
permission, and YouTube's Terms allow the download. Never scrape playlists.

## timeouts
Long sources: raise the timeout or clip the source first. `--quick` keeps
exploration cheap.

## disk
Renders need about 2x the source size free in `edit/`. Clean `edit/work/` (safe,
regenerable) — never `edit/out/` (immutable results).
