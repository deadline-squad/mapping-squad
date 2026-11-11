"""The lossless WebP form of a precise heightmap (heightmap.webp next to heightmap.png).

A WebP of the same grid as heightmap.png: an RGB image whose red channel holds the high byte and the
green channel the low byte of a 16-bit level (blue is 0), so height above the map's lowest point =
level * meta["webp"]["z_step_m"]. SquadCalc's worker (src/js/heightmapWorker.js in the deployment
repository) decodes it with the browser's own WebP decoder, which takes about half the time of the PNG
in JavaScript, and at the same levels the file is 15 to 32 % smaller (the 25 maps built on 2026-11-10).

It holds the PNG's own levels and step: one step of the game's collision heightfield is at most 0.3 to 6.4 mm on
each map (cooked Chaos heightfields of build 26005357), and a step coarsened to 1 cm was up to 0.5 cm off on bare ground
(README "WebP form"). meta.json keeps `z_step_m` for heightmap.png, and the WebP has its own entry with the same step:

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
