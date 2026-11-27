# Person matte (no green screen)

**Read this when** the subject must be cut out of a normal background, or text
must sit behind them.

## Backends

| Backend | Quality | Speed | Install |
|---|---|---|---|
| `rembg` (u2net) | good | fast on CPU | `pip install --user rembg onnxruntime` |
| `birefnet` | best edges/hair | slow | `pip install --user transformers torch` |
| `rvm` | best temporal | medium, needs VRAM | torch.hub |
| `sam2` | crowds | slow | sam2 package |

`auto` picks birefnet → rembg → rvm → sam2.

## Device policy

- CUDA/MPS: `--mask-res 1080 --every 1`
- CPU: `--mask-res 540 --every 2` and say the ETA out loud
- OOM: retry once at half resolution, log the fallback

## Temporal smoothing

3–5 frame median on the alpha (not on RGB), then a 0.5–0.8 px feather. Without
the median you get crawl on every frame; without the feather you get jaggies.

## Compositing

`alphamerge` the person with the mask, overlay onto the background, then apply
captions/graphics to the **background plate** when text must sit behind the
person.

## Verify

Always preview on white and black (`--preview`). Holes in the subject are a
model problem; halos are a feather/key problem. Record backend, device, mask
resolution, frame count and ETA in `matte.json`.
