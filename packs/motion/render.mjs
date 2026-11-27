#!/usr/bin/env node
// HyperFrames bridge: render a recipe + spec to PNG frames with Puppeteer.
// Usage: node packs/motion/render.mjs --spec spec.json --out frames/
// Requires: node >= 20, puppeteer (npm i -g puppeteer or local).
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

function arg(name, fallback = null) {
  const i = process.argv.indexOf(name);
  return i > -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

const specPath = arg('--spec');
const outDir = arg('--out', 'frames');
if (!specPath) {
  console.error('render.mjs: --spec is required');
  process.exit(2);
}

let puppeteer;
try {
  puppeteer = (await import('puppeteer')).default;
} catch (err) {
  // ESM ignores NODE_PATH; resolve a global install through CJS instead.
  try {
    const require = createRequire(import.meta.url);
    const resolved = require.resolve('puppeteer');
    puppeteer = (await import(pathToFileURL(resolved).href)).default;
  } catch (err2) {
    console.error('render.mjs: puppeteer is not installed. Run: npm i -g puppeteer');
    process.exit(5);
  }
}

const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
const recipe = spec.recipe || {};
const width = spec.width || 1080;
const height = spec.height || 1920;
const fps = spec.fps || 30;
const duration = spec.duration || recipe.duration || 3;
const frames = Math.max(Math.round(duration * fps), 2);
fs.mkdirSync(outDir, { recursive: true });

const text = (spec.text || '').replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
const subtitle = (spec.subtitle || '').replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
const anim = recipe.animation || 'fadeUp';
const sz = Math.round(Math.min(width, height) * 0.09);

const html = `<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;padding:0;background:transparent;width:${width}px;height:${height}px;overflow:hidden}
  .stage{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
         font-family:Inter,"Noto Sans",system-ui,sans-serif;text-align:center}
  .box{max-width:${Math.round(width * 0.84)}px;color:${recipe.color || '#fff'};
       font-size:${sz}px;line-height:1.05;font-weight:${recipe.weight === 'bold' ? 800 : 500};
       letter-spacing:-0.02em;text-shadow:0 6px 24px rgba(0,0,0,.45)}
  .accent{height:10px;width:120px;margin:28px auto 0;border-radius:5px;background:${recipe.accent || '#FF3B30'}}
  .sub{margin-top:26px;font-size:${Math.round(sz * 0.34)}px;font-weight:500;opacity:.85}
  .ticker{position:absolute;bottom:${Math.round(height * 0.18)}px;left:0;white-space:nowrap;
          font-size:${Math.round(sz * 0.4)}px;font-weight:700;background:${recipe.accent || '#D7263D'};
          color:#fff;padding:18px 40px}
  .bar{position:absolute;top:0;left:0;height:12px;background:${recipe.accent || '#FF3B30'}}
  .count{font-size:${sz * 2}px;font-weight:900;color:${recipe.color || '#fff'}}
</style></head><body>
<div class="stage"><div class="box" id="box">
  <div id="text">${text}</div><div class="accent" id="accent"></div>
  <div class="sub" id="sub">${subtitle}</div>
</div></div>
<div class="ticker" id="ticker">${text}</div>
<div class="bar" id="bar"></div>
<script>
const anim = ${JSON.stringify(anim)};
const dur = ${duration};
const easeOut = (x) => 1 - Math.pow(1 - Math.min(Math.max(x, 0), 1), 3);
window.renderFrame = (t) => {
  const p = Math.min(Math.max(t / Math.max(dur * 0.35, 0.2), 0), 1);
  const e = easeOut(p);
  const box = document.getElementById('box');
  const accent = document.getElementById('accent');
  const ticker = document.getElementById('ticker');
  const bar = document.getElementById('bar');
  const out = Math.max(0, (t - (dur - 0.25)) / 0.25);
  let opacity = 1 - out;
  let transform = '';
  if (anim === 'slideUp') transform = 'translateY(' + (1 - e) * 80 + 'px)';
  else if (anim === 'slideLeft') transform = 'translateX(' + (1 - e) * -120 + 'px)';
  else if (anim === 'slideRight') transform = 'translateX(' + (1 - e) * 120 + 'px)';
  else if (anim === 'scaleIn') transform = 'scale(' + (0.6 + 0.4 * e) + ')';
  else if (anim === 'pop') transform = 'scale(' + (1 + 0.12 * Math.sin(Math.PI * e)) + ')';
  else if (anim === 'fade') opacity = e * (1 - out);
  else if (anim === 'fadeUp') transform = 'translateY(' + (1 - e) * 40 + 'px)';
  box.style.opacity = opacity;
  box.style.transform = transform;
  accent.style.width = (120 * e) + 'px';
  accent.style.opacity = opacity;
  if (anim === 'ticker') {
    box.style.opacity = 0;
    ticker.style.transform = 'translateX(' + (width - (width + 600) * Math.min(t / dur, 1)) + 'px)';
  } else { ticker.style.display = 'none'; }
  if (anim === 'bar') {
    box.style.opacity = 0;
    bar.style.width = (width * Math.min(t / dur, 1)) + 'px';
  }
};
window.renderFrame(0);
</script></body></html>`;

const browser = await puppeteer.launch({
  headless: 'new',
  args: ['--no-sandbox', '--disable-setuid-sandbox', '--hide-scrollbars'],
});
const page = await browser.newPage();
await page.setViewport({ width, height, deviceScaleFactor: 1 });
await page.setContent(html, { waitUntil: 'load' });
await page.evaluate(() => document.fonts && document.fonts.ready);

for (let i = 0; i < frames; i += 1) {
  const t = i / fps;
  await page.evaluate((time) => window.renderFrame(time), t);
  const file = path.join(outDir, `f_${String(i + 1).padStart(4, '0')}.png`);
  await page.screenshot({ path: file, omitBackground: true });
}

await browser.close();
console.log(`render.mjs: ${frames} frames -> ${outDir}`);
