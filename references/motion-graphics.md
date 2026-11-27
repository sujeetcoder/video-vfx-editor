# Motion graphics

**Read this when** the user wants kinetic type, lower-thirds, animated hooks or
a 3D sting.

## Bridge

`motion.py` runs `packs/motion/render.mjs` with Node + Chrome (puppeteer),
writes PNG frames, encodes a qtrle alpha movie, and composites with FFmpeg.

Missing Node or puppeteer → `missing_capability` with
`winget install OpenJS.NodeJS.LTS` / `brew install node@22` + `npm i -g puppeteer`.
Never silently skip the effect.

## Recipes

12 JSON recipes in `packs/motion/`: kinetic hook, word pop, lower third, stat
counter, progress bar, logo sting, chapter card, ticker, quote card, arrow
callout, number countdown, end card. Each recipe declares its own text limit and
duration window.

## Timing rules

- hook motion starts within 0.3 s
- text stays on screen >=1.2 s and <=3 s
- safe zone: 8 % margins, bottom 18 % on 9:16
- ease out, 180–320 ms; never bounce more than once

## Gates

frame-diff energy > 0.5, text within the recipe limit, no overflow, motion
continuity (no frozen span > 0.5 s). `motion.py` measures energy from the
rendered file, not from the spec.

## 3D

`packs/3d/` holds a three.js logo-sting recipe, rendered through the same bridge
and composited as an alpha layer. No native 3D app required.
