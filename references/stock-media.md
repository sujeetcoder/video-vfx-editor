# Stock media (no keys)

**Read this when** a cut needs b-roll, a background, or a texture.

## Sources

| Source | API | Licence reality |
|---|---|---|
| Openverse | `api.openverse.org/v1/images` | filter out `by-nc`, `by-nd` |
| Wikimedia Commons | `commons.wikimedia.org/w/api.php` | check each file page |
| NASA | `images-api.nasa.gov` | public domain (credit NASA) |
| Pixabay | only with `PIXABAY_KEY` | Pixabay content licence |

Never CC-BY-NC. Never a frame with a visible logo, or a recognisable person used
commercially without a release.

## Scoring

`stock.py` scores: resolution >=1080 on the short side, orientation matches the
deliverable, licence usable, creator known. Unknown dimensions are penalised,
not assumed good.

## Credits

Every insert writes `credits.json`:

```json
{"query": "...", "assets": [{"title": "...", "creator": "...", "license": "...", "source": "..."}]}
```

Show credits to the user before publishing. Attribution is not optional for
CC-BY.
