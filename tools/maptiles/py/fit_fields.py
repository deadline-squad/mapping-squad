"""Colour fields of a style from the upstream basemap: the game's regional colours for the ground, water, roads,
buildings and trees of one map.

Usage: fit_fields.py <map> [--zoom 4] [--workers N] [--style styles/colour_<map>.json]

A fitted class colour (fit_palette.py) is one colour for the whole map, but the game's sand, rock, rivers and
roofs differ from region to region. Here the map is rendered in blocks at about 1 m per pixel with the style
and every pixel is assigned its top class (fit_palette.classify). For each colour group the basemap pixels of
its classes are averaged under a Gaussian (normalised convolution, so only the group's own pixels count) and
the gaps, under buildings, trees or far from the group, are filled from a wider Gaussian, up to 64 times as wide.
Ground pixels clearly darker than their surroundings (the game's own baked shadows, which render.py draws
itself) are left out. The result of each group is stored in prep/<map>/colour_field_<group>.npy (RGB uint8
on a grid of 1 m for the ground, 2 m for the rest, cell i centred (i + 0.5) cells from the map's minimum) and
listed under "FIELDS" in the style, which render.py then samples instead of the class colour.
"""

import argparse
import json
import math
import os

import numpy as np
from PIL import Image
from scipy import ndimage

import features
import fit_palette
import render
import worker_pool

# Group: (classes of fit_palette.classify, Gaussian sigma in pixels at the fitting zoom, grid cell in metres)
GROUPS = {
    "ground": (lambda name: name[0] == "cover", 2.5, 1),
    "water": (lambda name: name[0] == "water", 3.0, 2),
    "road": (lambda name: name[0] == "spline" and name[1] in ("asphalt", "pavement", "dirt"), 2.0, 2),
    "object": (lambda name: name[0] in ("ramp", "object"), 2.0, 2),
    "conifer": (lambda name: name == ("foliage", features.CONIFER), 2.5, 2),
    "deciduous": (lambda name: name == ("foliage", features.DECIDUOUS), 2.5, 2),
    "bush": (lambda name: name == ("foliage", features.BUSH), 2.5, 2),
}
# A group's weight under a Gaussian below which the next wider one fills the pixel
MIN_WEIGHT = 0.04
DARK_SHARE = 0.8
FILL_SCALES = (1, 4, 16, 64)
_maps = {}


def init(slug, style, zoom, basemap_path, work):
    fit_palette.init(slug, style, zoom, basemap_path)
    for group in GROUPS:
        _maps[group] = (np.load(os.path.join(work, f"{group}_sum.npy"), mmap_mode="r+"), np.load(os.path.join(work, f"{group}_weight.npy"), mmap_mode="r+"))


def task(block):
    z, bx, by = block
    d = render._data
    t = d["trace"]
    render.render_block(d, z, bx, by)
    m = render.MARGIN
    full = render.TILE * 2 ** z
    w = min(fit_palette.BLOCK_PX, full - bx * fit_palette.BLOCK_PX)
    h = min(fit_palette.BLOCK_PX, full - by * fit_palette.BLOCK_PX)
    label, names = fit_palette.classify(d, t, w + 2 * m, h + 2 * m)
    label = label[m:m + h, m:m + w]
    y0, x0 = by * fit_palette.BLOCK_PX, bx * fit_palette.BLOCK_PX
    theirs = fit_palette._basemap["image"][y0:y0 + h, x0:x0 + w].astype(np.float32)
    for group, (member, _, _) in GROUPS.items():
        indices = [i for i, name in enumerate(names) if member(name)]
        mask = np.isin(label, indices)
        sums, weights = _maps[group]
        sums[y0:y0 + h, x0:x0 + w] = theirs * mask[..., None]
        weights[y0:y0 + h, x0:x0 + w] = mask
    return block


def gaussian(array, sigma):
    """Gaussian filter of [H, W] (or [H, W, 3]) for any sigma: wide ones are done on a block-averaged copy, then interpolated back."""
    factor = max(1, int(sigma // 5))
    if factor == 1:
        return ndimage.gaussian_filter(array, (sigma, sigma) + (0,) * (array.ndim - 2))
    h, w = array.shape[0] // factor * factor, array.shape[1] // factor * factor
    small = array[:h, :w].reshape((h // factor, factor, w // factor, factor) + array.shape[2:]).mean(axis=(1, 3))
    small = ndimage.gaussian_filter(small, (sigma / factor, sigma / factor) + (0,) * (array.ndim - 2))
    zoom = (array.shape[0] / small.shape[0], array.shape[1] / small.shape[1]) + (1,) * (array.ndim - 2)
    return ndimage.zoom(small, zoom, order=1, mode="nearest")[:array.shape[0], :array.shape[1]]


def smooth(sums, weights, sigma):
    """Colour field: Gaussian average of the group's pixels, wider Gaussians where it has too few; NaN where none."""
    field = np.full(sums.shape, np.nan, np.float32)
    for scale in FILL_SCALES:
        weight = gaussian(weights, sigma * scale)
        gaps = np.isnan(field[..., 0]) & (weight >= MIN_WEIGHT * (1 if scale == 1 else 0.25))
        if not gaps.any():
            continue
        colour = gaussian(sums, sigma * scale)
        field[gaps] = colour[gaps] / weight[gaps][:, None]
    return field


def build(slug, style_file, zoom, workers, basemap_path):
    base = os.path.join("/prep", slug)
    work = os.path.join(base, "colour_field_work")
    os.makedirs(work, exist_ok=True)
    size = render.TILE * 2 ** zoom
    for group in GROUPS:
        np.lib.format.open_memmap(os.path.join(work, f"{group}_sum.npy"), "w+", np.float32, (size, size, 3)).flush()
        np.lib.format.open_memmap(os.path.join(work, f"{group}_weight.npy"), "w+", np.float32, (size, size)).flush()
    n = math.ceil(2 ** zoom / render.BLOCK_TILES)
    blocks = [(zoom, bx, by) for by in range(n) for bx in range(n)]
    with worker_pool.Pool(workers, init, (slug, style_file, zoom, basemap_path, work)) as pool:
        for _ in pool.imap_unordered(task, blocks):
            pass
    meta = json.load(open(os.path.join(base, "meta.json")))
    b = meta["bounds_m"]
    fields = {}
    for group, (_, sigma, cell) in GROUPS.items():
        sums = np.load(os.path.join(work, f"{group}_sum.npy"))
        weights = np.load(os.path.join(work, f"{group}_weight.npy"))
        if group == "ground":
            lum = fit_palette.luminance(sums / np.maximum(weights, 1)[..., None])
            local = gaussian(lum * weights, 6) / np.maximum(gaussian(weights, 6), 1e-6)
            keep = (weights > 0) & (lum >= DARK_SHARE * local)
            sums, weights = sums * keep[..., None], weights * keep
        field = smooth(sums, weights, sigma)
        if np.isnan(field[..., 0]).all():
            continue
        width, height = math.ceil((b["max_x"] - b["min_x"]) / cell), math.ceil((b["max_y"] - b["min_y"]) / cell)
        field = np.where(np.isnan(field), np.nanmean(field, axis=(0, 1)), field)
        image = np.stack([np.asarray(Image.fromarray(field[..., c]).resize((width, height), Image.BILINEAR)) for c in range(3)], -1)
        name = f"colour_field_{group}.npy"
        np.save(os.path.join(base, name), np.clip(np.rint(image), 0, 255).astype(np.uint8))
        fields[group] = {"file": name, "cell_m": cell}
    for name in os.listdir(work):
        os.remove(os.path.join(work, name))
    os.rmdir(work)
    return fields


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("map")
    parser.add_argument("--zoom", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--style")
    parser.add_argument("--basemaps", default="/basemaps")
    args = parser.parse_args()
    style_file = args.style or os.path.join(render.STYLES_DIR, f"colour_{args.map}.json")
    style = json.load(open(style_file))
    # The classes are those of the style without fields: the style's own fields would only recolour them
    style.pop("FIELDS", None)
    json.dump(style, open(style_file, "w"), indent=1)
    style["FIELDS"] = build(args.map, style_file, args.zoom, args.workers, os.path.join(args.basemaps, f"{args.map}.webp"))
    json.dump(style, open(style_file, "w"), indent=1)
    print(json.dumps({group: spec["file"] for group, spec in style["FIELDS"].items()}))


if __name__ == "__main__":
    main()
