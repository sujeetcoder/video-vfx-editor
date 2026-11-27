# Fonts

Fonts are **downloaded at install time**, never committed (binary weight).

| File | Licence | Use |
|---|---|---|
| NotoSansDevanagari.ttf | SIL OFL 1.1 | Hindi captions (default) |
| Inter.ttf | SIL OFL 1.1 | Latin captions, graphics |
| NotoSans.ttf | SIL OFL 1.1 | fallback |

`python install/ensure.py --install --fonts` writes them here, or to
`~/.vfe/fonts/` when the repo is read-only. `caption.py` passes `fontsdir`
explicitly so libass finds them without a system install.
