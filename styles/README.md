# Styles

Learned profiles land here as `styles/<name>/style.json` +
`style.md` + `refs.md` + `frames/`.

```bash
python scripts/style.py learn ref1.mp4 ref2.mp4 ref3.mp4 --name kiki
```

Profiles are data: commit them if the user wants to share the look, but never
commit the reference media itself.
