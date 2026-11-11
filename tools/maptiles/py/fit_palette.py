"""Fit the colours of a style to the upstream basemap of the same map (the game's own colours).

Usage: fit_palette.py <map> [--zoom 4] [--iterations 4] [--workers N] [--out styles/colour_<map>.json] [--resume]

The map is rendered in blocks at about 1 m per pixel (the resolution of the basemap) with the current
style. Every pixel is assigned the class of the layer on top (a building height band, a wall, a tree or
rock class, a road class, water, one of the ground cover materials, or the shadow of an object), and
each class's mean rendered colour is compared with the mean colour of the basemap on the same pixels.
The class colour is multiplied by the ratio of the two means per channel; the render is repeated
until the means agree. Classes with too few pixels get the mean correction of their group. The shadow
factor is corrected the same way, with luminance. The relief strength (SHADE_STRENGTH) is chosen
separately by --relief: the strength at which the luminance contrast of the smoothed relief on bare
ground matches the basemap's. The result is a style file for render.py --style.
"""

import argparse
import json
import math
import os

import numpy as np
from PIL import Image

import features
import render
import worker_pool

MIN_PIXELS = 4000
# Opacity of the canopy colours in the fitted styles: a mostly opaque crown takes its colour from the basemap
# instead of from the ground under it, which a half transparent crown would need to over-correct
FOLIAGE_ALPHA = {"conifer": 0.8, "deciduous": 0.8, "bush": 0.7, "rock": 0.9, "palm": 0.8}
# Share of a crown's opacity that reaches a pixel classed as that crown (crown coverage is above 0.6, mean about 0.85)
CROWN_COVERAGE = 0.85
BLOCK_PX = render.TILE * render.BLOCK_TILES
_basemap = {}


def init(slug, style, zoom, basemap_path):
    if style:
        render.apply_style(style)
    render._data.update(render.load(slug))
    render._data["trace"] = {}
    size = render.TILE * 2 ** zoom
    _basemap["image"] = np.asarray(Image.open(basemap_path).convert("RGB").resize((size, size), Image.LANCZOS)).astype(np.float64)


def classify(d, t, width, height):
    """Class label per pixel: an int index into the list of class names returned with it."""
    names = []
    label = np.full((height, width), -1, np.int64)

    def put(name, mask):
        if name not in names:
            names.append(name)
        label[mask] = names.index(name)

    cover = t["cover"]
    materials = d["meta"]["physical_materials"]
    shadow = t.get("shadow", np.zeros((height, width), np.float32))
    for idx in np.unique(cover):
        name = materials[idx] if idx < len(materials) else "none"
        put(("cover", name), (cover == idx) & (shadow < 0.1))
    put(("shadow",), shadow > 0.6)
    water, deep = t["water"], t.get("deep", np.zeros((height, width), np.float32))
    put(("water", "shallow"), (water > 0.7) & (deep <= 0.5))
    put(("water", "deep"), (water > 0.7) & (deep > 0.5))
    for cls in render.SPLINE_ORDER:
        if cls in t["splines"]:
            put(("spline", cls), (t["splines"][cls] > 0.7) & (water < 0.5))
    for c in render.FOLIAGE_ORDER:
        if c in t["foliage"]:
            put(("foliage", c), (t["foliage"][c] > 0.6) & (water < 0.5))
    if "objects" in t:
        alpha, height_m, cls = t["objects"]
        solid = alpha > 0.7
        stops = np.array([s for s, _ in render.STRUCTURE_RAMP])
        band = np.abs(height_m[..., None] - stops).argmin(-1)
        for k in range(len(stops)):
            put(("ramp", k), solid & (cls == features.STRUCTURE) & (band == k))
        for name, c in render.OBJECT_NAMES.items():
            put(("object", name), solid & (cls == c))
    return label, names


def task(block):
    z, bx, by = block
    d = render._data
    t = d["trace"]
    image = render.render_block(d, z, bx, by)
    del image
    m = render.block_margin(d, z)
    full = render.TILE * 2 ** z
    w = min(BLOCK_PX, full - bx * BLOCK_PX)
    h = min(BLOCK_PX, full - by * BLOCK_PX)
    inner = (slice(m, m + h), slice(m, m + w))
    label, names = classify(d, t, w + 2 * m, h + 2 * m)
    label = label[inner]
    ours = t["rgb"][inner].astype(np.float64)
    theirs = _basemap["image"][by * BLOCK_PX:by * BLOCK_PX + h, bx * BLOCK_PX:bx * BLOCK_PX + w]
    stats = {}
    for i, name in enumerate(names):
        mask = label == i
        n = int(mask.sum())
        if n:
            stats[name] = (n, ours[mask].sum(0), theirs[mask].sum(0))
    return stats


def collect(slug, style, zoom, workers, basemap_path):
    n = math.ceil(2 ** zoom / render.BLOCK_TILES)
    blocks = [(zoom, bx, by) for by in range(n) for bx in range(n)]
    total = {}
    with worker_pool.Pool(workers, init, (slug, style, zoom, basemap_path)) as pool:
        for stats in pool.imap_unordered(task, blocks):
            for name, (count, ours, theirs) in stats.items():
                n0, o0, t0 = total.get(name, (0, 0, 0))
                total[name] = (n0 + count, o0 + ours, t0 + theirs)
    return total


def current_style():
    """The style the render module holds now, as a style file dictionary."""
    return {
        "COVER_RGB": {k: list(v) for k, v in render.COVER_RGB.items()},
        "NO_COVER_RGB": list(render.NO_COVER_RGB),
        "STEEP_RGB": list(render.STEEP_RGB),
        "WATER_RGB": render.WATER_RGB.tolist(),
        "WATER_DEEP_RGB": render.WATER_DEEP_RGB.tolist(),
        "SHORE_RGB": render.SHORE_RGB.tolist(),
        "SPLINE_FILL": {k: list(v[0]) for k, v in render.SPLINE_STYLE.items()},
        "FOLIAGE_RGB": {n: list(render.FOLIAGE_STYLE[c][0]) for n, c in render.FOLIAGE_NAMES.items()},
        "FOLIAGE_ALPHA": dict(FOLIAGE_ALPHA),
        "STRUCTURE_RAMP": [[h, list(c)] for h, c in render.STRUCTURE_RAMP],
        "OBJECT_RGB": {n: list(render.OBJECT_RGB[c]) for n, c in render.OBJECT_NAMES.items()},
        "SHADOW_FACTOR": render.SHADOW_FACTOR,
    }


def luminance(rgb):
    return rgb @ np.array([0.2126, 0.7152, 0.0722])


def update(style, stats):
    """Multiply each class's colour by basemap mean / rendered mean; returns the report per class."""
    report = {}
    gains = {}
    for name, (n, ours, theirs) in stats.items():
        if n < MIN_PIXELS or name[0] == "shadow":
            continue
        gains[name] = np.clip(theirs / np.maximum(ours, 1e-6), 0.4, 2.5)
    group_gain = {}
    for group in ("cover", "ramp", "spline", "foliage", "object", "water"):
        members = [(stats[k][0], g) for k, g in gains.items() if k[0] == group]
        if members:
            weights = np.array([w for w, _ in members], np.float64)
            group_gain[group] = (np.array([g for _, g in members]) * weights[:, None]).sum(0) / weights.sum()

    def gain_of(group, key):
        return gains.get((group,) + key, group_gain.get(group, np.ones(3)))

    def scale(rgb, g):
        return [float(np.clip(c * k, 0, 255)) for c, k in zip(rgb, g)]

    for name in list(style["COVER_RGB"]):
        style["COVER_RGB"][name] = scale(style["COVER_RGB"][name], gain_of("cover", (name,)))
    style["NO_COVER_RGB"] = scale(style["NO_COVER_RGB"], gain_of("cover", ("none",)))
    style["STEEP_RGB"] = scale(style["STEEP_RGB"], group_gain.get("cover", np.ones(3)))
    style["WATER_RGB"] = scale(style["WATER_RGB"], gain_of("water", ("shallow",)))
    style["WATER_DEEP_RGB"] = scale(style["WATER_DEEP_RGB"], gain_of("water", ("deep",)))
    style["SHORE_RGB"] = [c * 0.8 for c in style["WATER_DEEP_RGB"]]
    for cls in style["SPLINE_FILL"]:
        style["SPLINE_FILL"][cls] = scale(style["SPLINE_FILL"][cls], gain_of("spline", (cls,)))
    for name, c in render.FOLIAGE_NAMES.items():
        if ("foliage", c) in gains:
            # Blended over the ground: moving the colour by the error divided by the opacity removes it
            n, ours, theirs = stats[("foliage", c)]
            opacity = style["FOLIAGE_ALPHA"][name] * CROWN_COVERAGE
            style["FOLIAGE_RGB"][name] = [float(np.clip(v + (t - o) / n / opacity, 0, 255))
                                          for v, o, t in zip(style["FOLIAGE_RGB"][name], ours, theirs)]
    for k, (height, rgb) in enumerate(style["STRUCTURE_RAMP"]):
        style["STRUCTURE_RAMP"][k] = [height, scale(rgb, gain_of("ramp", (k,)))]
    for name in style["OBJECT_RGB"]:
        style["OBJECT_RGB"][name] = scale(style["OBJECT_RGB"][name], gain_of("object", (name,)))
    shadow = stats.get(("shadow",))
    if shadow and shadow[0] >= MIN_PIXELS:
        ratio = luminance(shadow[2]) / max(luminance(shadow[1]), 1e-6)
        style["SHADOW_FACTOR"] = float(np.clip(style["SHADOW_FACTOR"] * ratio, 0.3, 1.0))
    for name, (n, ours, theirs) in stats.items():
        report[str(name)] = {"pixels": n, "ours": (ours / n).round(1).tolist(), "basemap": (theirs / n).round(1).tolist()}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("map")
    parser.add_argument("--zoom", type=int, default=4)
    parser.add_argument("--iterations", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--basemaps", default="/basemaps")
    parser.add_argument("--out")
    parser.add_argument("--resume", action="store_true", help="start from the style file that exists instead of the defaults")
    args = parser.parse_args()
    out = args.out or os.path.join(render.STYLES_DIR, f"colour_{args.map}.json")
    basemap_path = os.path.join(args.basemaps, f"{args.map}.webp")
    style_file = None
    for i in range(args.iterations + 1):
        if style_file is None:
            style_file = out
            if not (args.resume and os.path.exists(out)):
                json.dump(current_style(), open(out, "w"), indent=1)
        stats = collect(args.map, style_file, args.zoom, args.workers, basemap_path)
        style = json.load(open(style_file))
        total = sum(n for n, _, _ in stats.values())
        mean_error = sum(np.abs(o - t).sum() / 3 for _, o, t in stats.values()) / total
        print(f"iteration {i}: mean absolute class-mean error per pixel {mean_error:.2f} (of 255)", flush=True)
        if i == args.iterations:
            break
        report = update(style, stats)
        json.dump(style, open(out, "w"), indent=1)
    json.dump(report, open(out.replace(".json", ".fit.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
