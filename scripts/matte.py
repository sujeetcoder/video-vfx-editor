#!/usr/bin/env python3
"""Person matte without a green screen: rembg / BiRefNet / RVM / SAM2 + temporal smoothing.

CPU falls back to --mask-res 540 --every 2. Device and per-clip ETA are recorded.

    python scripts/matte.py input.mp4 --bg studio.jpg --json
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _caps import capabilities, device_plan, encoder_args  # noqa: E402
from _contract import InvalidInput, MissingCapability, add_common, stage  # noqa: E402
from _paths import (ensure_edit, expand_inputs, ffmpeg_bin, ffprobe_json, project_root,  # noqa: E402
                    record_stage, run_cmd, work_dir, write_json)

BACKEND_FIX = {
    "rembg": "python -m pip install --user rembg onnxruntime",
    "birefnet": "python -m pip install --user transformers torch pillow",
    "rvm": "python -m pip install --user torch torchvision  (then torch.hub downloads RVM)",
    "sam2": "python -m pip install --user 'git+https://github.com/facebookresearch/sam2'",
}


def available_backends() -> dict:
    import importlib.util

    return {
        "rembg": importlib.util.find_spec("rembg") is not None,
        "birefnet": importlib.util.find_spec("transformers") is not None
        and importlib.util.find_spec("torch") is not None,
        "rvm": importlib.util.find_spec("torch") is not None,
        "sam2": importlib.util.find_spec("sam2") is not None,
    }


def pick_backend(requested: str, plan: dict) -> str:
    avail = available_backends()
    if requested != "auto":
        if not avail.get(requested):
            raise MissingCapability(
                f"matte backend '{requested}' is not installed",
                fix=BACKEND_FIX.get(requested, "see references/person-matte.md"),
                doc="references/person-matte.md",
            )
        return requested
    for name in ("birefnet", "rembg", "rvm", "sam2"):
        if avail.get(name):
            return name
    raise MissingCapability(
        "no person-matte backend installed",
        fix="python -m pip install --user rembg onnxruntime   (fastest CPU start)",
        doc="references/person-matte.md",
    )


class Matten:
    def __init__(self, backend: str, device: str):
        self.backend = backend
        self.device = device
        self._model = None

    def alpha(self, image):
        if self.backend == "rembg":
            from rembg import new_session, remove

            if self._model is None:
                # u2net (176 MB) is the CPU default; bria-rmbg is ~1 GB
                self._model = new_session(os.environ.get("VFE_MATTE_MODEL", "u2net"))
            out = remove(image, session=self._model)
            return out.getchannel("A")
        if self.backend == "birefnet":
            import torch
            from torchvision import transforms
            from transformers import AutoModelForImageSegmentation

            if self._model is None:
                self._model = AutoModelForImageSegmentation.from_pretrained(
                    "ZhengPeng7/BiRefNet", trust_remote_code=True)
                self._model.eval()
                if self.device in ("cuda", "mps"):
                    self._model.to(self.device)
            tf = transforms.Compose([
                transforms.Resize((1024, 1024)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ])
            inp = tf(image.convert("RGB")).unsqueeze(0)
            if self.device in ("cuda", "mps"):
                inp = inp.to(self.device)
            with torch.no_grad():
                pred = self._model(inp)[-1].sigmoid().cpu()[0].squeeze()
            import torch as _t

            mask = transforms.ToPILImage()(_t.clamp(pred, 0, 1)).resize(image.size)
            return mask
        raise MissingCapability(
            f"backend {self.backend} needs manual model setup",
            fix=BACKEND_FIX[self.backend],
            doc="references/person-matte.md",
        )


def extract_frames(path: Path, frames_dir: Path, res: int, every: int, dry_run=False) -> int:
    frames_dir.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path),
           "-vf", f"select='not(mod(n\\,{max(every, 1)}))',scale={res}:-2",
           "-fps_mode", "vfr", str(frames_dir / "f_%05d.png")]
    run_cmd(cmd, dry_run=dry_run, timeout=7200, check=not dry_run)
    if dry_run:
        return 0
    return len(list(frames_dir.glob("f_*.png")))


def write_masks(frames: list, matten: Matten, masks_dir: Path, feather: float) -> list:
    import numpy as np
    from PIL import Image, ImageFilter

    alphas = []
    for f in frames:
        img = Image.open(f).convert("RGB")
        alphas.append(np.asarray(matten.alpha(img).convert("L"), dtype=np.uint8))
    masks_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(len(alphas)):
        window = [a.astype(np.float32) / 255.0 for a in alphas[max(0, i - 2): min(len(alphas), i + 3)]]
        alpha = np.median(np.stack(window), axis=0)
        m = Image.fromarray((alpha * 255).astype("uint8"), mode="L")
        if feather:
            m = m.filter(ImageFilter.GaussianBlur(radius=feather))
        p = masks_dir / f"m_{i + 1:05d}.png"
        m.save(p)
        out.append(p)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Person matte + composite")
    add_common(parser)
    parser.add_argument("input")
    parser.add_argument("--backend", default="auto", choices=["auto", "rembg", "birefnet", "rvm", "sam2"])
    parser.add_argument("--bg", default=None, help="background image/video (default: black)")
    parser.add_argument("--every", type=int, default=None)
    parser.add_argument("--mask-res", type=int, default=None)
    parser.add_argument("--feather", type=float, default=0.8)
    parser.add_argument("--out", default=None)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args(argv)
    root = project_root(args.project)
    state = ensure_edit(root)
    caps = capabilities(root)
    plan_dev = device_plan(args.device, caps)

    with stage("matte", args) as run:
        run.device = plan_dev["resolved"]
        path = expand_inputs([args.input])[0]
        backend = pick_backend(args.backend, plan_dev)
        every = args.every if args.every is not None else (1 if plan_dev["resolved"] != "cpu" else 2)
        res = args.mask_res if args.mask_res is not None else plan_dev["mask_res"]
        work = work_dir(root, f"p-{path.stem}")
        frames_dir = work / "matte-frames"
        masks_dir = work / "masks"
        probe = ffprobe_json(path, dry_run=args.dry_run)
        fps = 30.0
        for s in probe.get("streams", []):
            if s.get("codec_type") == "video":
                try:
                    num, den = str(s.get("avg_frame_rate", "30/1")).split("/")
                    fps = float(num) / float(den or 1)
                except (ValueError, ZeroDivisionError):
                    fps = 30.0
        duration = float((probe.get("format") or {}).get("duration") or 0)

        started = time.time()
        n_frames = extract_frames(path, frames_dir, res, every, dry_run=args.dry_run)
        if args.dry_run:
            run.ok(output=str(work / "matte.mp4"), next_cmd="python scripts/matte.py <input> --bg <image>")
            return 0
        if n_frames == 0:
            raise InvalidInput("no frames extracted", fix="check the input file plays")
        matten = Matten(backend, plan_dev["torch_device"])
        frames = sorted(frames_dir.glob("f_*.png"))
        write_masks(frames, matten, masks_dir, args.feather)
        eta = (time.time() - started) / n_frames * (duration * fps / max(every, 1)) if n_frames else 0

        mask_video = work / "mask.mov"
        run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-framerate", f"{fps / max(every, 1):.3f}",
                 "-i", str(masks_dir / "m_%05d.png"), "-c:v", "png", "-pix_fmt", "rgba",
                 str(mask_video)], timeout=3600, check=True)

        out_path = Path(args.out) if args.out else work / "matte.mp4"
        width = int((probe.get("streams") or [{}])[0].get("width") or 1080)
        height = int((probe.get("streams") or [{}])[0].get("height") or 1920)
        if args.bg:
            bg = expand_inputs([args.bg])[0]
            fc = (f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                  f"crop={width}:{height}[bgv];[2:v]scale={width}:{height}[mv];"
                  f"[0:v][mv]alphamerge[fg];[bgv][fg]overlay=shortest=1,format=yuv420p[out]")
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path), "-loop", "1",
                   "-i", str(bg), "-i", str(mask_video), "-filter_complex", fc, "-map", "[out]",
                   "-map", "0:a?", *encoder_args(plan_dev["encoder"], 18), "-c:a", "aac",
                   "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out_path)]
        else:
            fc = (f"[1:v]scale={width}:{height}[mv];[0:v][mv]alphamerge[fg];"
                  f"color=c=black:s={width}x{height}:d={duration:.3f}[bgv];"
                  f"[bgv][fg]overlay=shortest=1,format=yuv420p[out]")
            cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y", "-i", str(path), "-i", str(mask_video),
                   "-filter_complex", fc, "-map", "[out]", "-map", "0:a?",
                   *encoder_args(plan_dev["encoder"], 18), "-c:a", "aac",
                   "-movflags", "+faststart", str(out_path)]
        run_cmd(cmd, timeout=7200, check=True)

        previews = []
        if args.preview:
            at = max(0.0, duration / 3)
            for bg, name in (("white", "matte-white.png"), ("black", "matte-black.png")):
                prev = work / name
                fc = (f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                      f"crop={width}:{height}[bgv];[2:v]scale={width}:{height}[mv];"
                      f"[0:v][mv]alphamerge[fg];[bgv][fg]overlay=shortest=1[out]")
                # seek the OUTPUT: seeking the mask input makes frame 1 have no
                # overlay yet, which yields a plain background card
                run_cmd([ffmpeg_bin(), "-hide_banner", "-nostdin", "-y",
                         "-i", str(path),
                         "-f", "lavfi", "-i", f"color=c={bg}:s={width}x{height}",
                         "-i", str(mask_video),
                         "-filter_complex", fc, "-map", "[out]",
                         "-ss", f"{at:.3f}", "-frames:v", "1", "-update", "1", str(prev)],
                        timeout=300)
                previews.append(str(prev))

        sidecar = {"backend": backend, "device": plan_dev["resolved"], "mask_res": res,
                   "every": every, "masks": n_frames, "eta_seconds": round(eta, 1), "feather": args.feather}
        write_json(work / "matte.json", sidecar)
        state = ensure_edit(root)
        record_stage(root, state, "matte", out_path, backend=backend, device=plan_dev["resolved"])
        run.add_check("matte_frames", "pass" if n_frames > 0 else "fail", n_frames, "> 0")
        run.ok(output=str(out_path), artifacts=[str(out_path), str(mask_video), *previews],
               next_cmd=f'python scripts/check.py "{out_path}" --json')
        if not args.json:
            print(f"{backend} on {plan_dev['resolved']} ({n_frames} masks, ~{eta:.0f}s) -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
