"""The lossless WebP form of a precise heightmap (heightmap.webp next to heightmap.png).

A WebP of the same grid as heightmap.png: an RGB image whose red channel holds the high byte and the
green channel the low byte of a 16-bit level (blue is 0), so height above the map's lowest point =
level * meta["webp"]["z_step_m"]. SquadCalc's worker (src/js/heightmapWorker.js in the deployment
repository) decodes it with the browser's own WebP decoder, which takes about half the time of the PNG
in JavaScript, and the file is 20 to 50 % smaller.

The step is coarsened to MIN_STEP_M (1 cm: finer than the game's own collision, and the noise under it
is what makes the file big) except for the maps in KEEP_STEP, where it only gets bigger. A step
already coarser than 1 cm is kept: the level range of a map as high as Skorpo's (1064 m) does not fit
16 bits at 1 cm. meta.json keeps `z_step_m` for heightmap.png (a bundle that only knows the PNG still
reads it), the WebP has its own entry:

    "format": "webp-rg16", "generated": "<UTC>", "webp": {"file", "encoding", "z_step_m", "levels_sum"}

`levels_sum` is the sum of all levels modulo 2**32: the browser compares it to the decoded levels, so a
browser that alters canvas pixels (anti-fingerprinting noise) falls back to the PNG instead of
showing wrong heights.
"""

import os

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
FORMAT = "webp-rg16"
FILE = "heightmap.webp"
MIN_STEP_M = 0.01
# Re-quantising these to 1 cm makes their file bigger (audit of 2026-10-30)
KEEP_STEP = {"Chora"}


def step_for(map_name, png_step):
    """Step in metres of the WebP of a map whose PNG has `png_step`."""
    return png_step if map_name in KEEP_STEP else max(png_step, MIN_STEP_M)


def levels_sum(levels):
    """Sum of all levels modulo 2**32 (what the worker checks after decoding)."""
    return int(levels.astype(np.uint64).sum() % (1 << 32))


def encode(levels, path):
    """Write 16-bit `levels` (2-D uint16) as a lossless WebP, high byte in R and low byte in G."""
    rgb = np.zeros(levels.shape + (3,), dtype=np.uint8)
    rgb[..., 0] = levels >> 8
    rgb[..., 1] = levels & 0xFF
    Image.fromarray(rgb, "RGB").save(path, "WEBP", lossless=True, quality=100, method=6)


def decode(path):
    """Levels of a heightmap.webp as 2-D uint16."""
    rgb = np.asarray(Image.open(path).convert("RGB"))
    return (rgb[..., 0].astype(np.uint16) << 8) | rgb[..., 1]


def meta_entry(levels, step, path):
    """The `webp` entry of meta.json for the WebP written at `path`."""
    return {
        "file": os.path.basename(path),
        "encoding": "lossless WebP, RGB: level = R * 256 + G, B = 0; height above z_min_m = level * z_step_m",
        "z_step_m": step,
        "levels_sum": levels_sum(levels),
    }
