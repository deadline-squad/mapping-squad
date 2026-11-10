"""Relief strength and light direction of a style, measured against the upstream basemap.

Usage: fit_relief.py <map> [--zoom 4] [--workers N] [--style styles/colour_<map>.json] [--write]

On bare ground (ground cover pixels that no object, tree, road, water or shadow covers) the luminance of
the smoothed relief, relative to the local mean, is regressed on the terrain slope: L_rel ~ a * dz/dx + b * dz/dy
over the 2-8 pixel band (about 2-8 m), for the render with the style and for the basemap. The regression
vector of the render points where the style's light is, its length is the style's SHADE_STRENGTH times
the cover's contrast; the basemap's vector gives the strength that matches (SHADE_STRENGTH scaled by the
ratio of the lengths) and the direction the game lights the ground from. Prints both; --write stores the
strength and the light direction (LIGHT_FROM) in the style.
"""

import argparse
import json
import math
import multiprocessing
import os

import numpy as np
from scipy import ndimage

import fit_palette
import render

SMALL, LARGE = 2.0, 8.0


def band_relative(values, mask):
    """Band-pass (SMALL..LARGE gaussians) of values over the mask, divided by the local mean: normalised convolution."""
    m = mask.astype(np.float64)
    small = ndimage.gaussian_filter(values * m, SMALL) / np.maximum(ndimage.gaussian_filter(m, SMALL), 1e-6)
    large = ndimage.gaussian_filter(values * m, LARGE) / np.maximum(ndimage.gaussian_filter(m, LARGE), 1e-6)
    return (small - large) / np.maximum(large, 1.0)


def band_plain(values, mask):
    m = mask.astype(np.float64)
    small = ndimage.gaussian_filter(values * m, SMALL) / np.maximum(ndimage.gaussian_filter(m, SMALL), 1e-6)
    large = ndimage.gaussian_filter(values * m, LARGE) / np.maximum(ndimage.gaussian_filter(m, LARGE), 1e-6)
    return small - large


def task(block):
    z, bx, by = block
    d = render._data
    t = d["trace"]
    render.render_block(d, z, bx, by)
    m = render.block_margin(d, z)
    full = render.TILE * 2 ** z
    w = min(fit_palette.BLOCK_PX, full - bx * fit_palette.BLOCK_PX)
    h = min(fit_palette.BLOCK_PX, full - by * fit_palette.BLOCK_PX)
    label, names = fit_palette.classify(d, t, w + 2 * m, h + 2 * m)
    bare = np.array([name[0] == "cover" for name in names] + [False])[label]
    # Pixels a few pixels away from anything else, so the smoothing does not mix classes
    bare = ndimage.binary_erosion(bare, iterations=3)
    if bare.sum() < 2000:
        return None
    rows = slice(by * fit_palette.BLOCK_PX - m, by * fit_palette.BLOCK_PX + h + m)
    cols = slice(bx * fit_palette.BLOCK_PX - m, bx * fit_palette.BLOCK_PX + w + m)
    size = fit_palette._basemap["image"].shape[0]
    pad_r = (max(0, -rows.start), max(0, rows.stop - size))
    pad_c = (max(0, -cols.start), max(0, cols.stop - size))
    theirs = np.pad(fit_palette._basemap["image"], (pad_r, pad_c, (0, 0)), mode="edge")[rows.start + pad_r[0]:rows.stop + pad_r[0], cols.start + pad_c[0]:cols.stop + pad_c[0]]
    shadow_sums = np.zeros((16, 2))
    if "objects" in t:
        alpha, height_m, _ = t["objects"]
        tall = ndimage.binary_dilation(alpha > 0.7, iterations=1) & (height_m > 3)
        solid = alpha > 0.3
        ground = np.array([name[0] == "cover" for name in names] + [False])[label]
        lum_base = fit_palette.luminance(theirs)
        for k in range(16):
            angle = 2 * math.pi * k / 16
            dy, dx = int(round(5 * math.sin(angle))), int(round(5 * math.cos(angle)))
            moved = np.roll(tall, (dy, dx), axis=(0, 1)) & ~solid & ground
            shadow_sums[k] = (lum_base[moved].sum(), moved.sum())
    sx, sy = band_plain(t["slope_x"], bare), band_plain(t["slope_y"], bare)
    inner = (slice(m, m + h), slice(m, m + w))
    out = {}
    for name, rgb in (("ours", t["rgb"].astype(np.float64)), ("basemap", theirs)):
        lum = fit_palette.luminance(rgb)
        rel = band_relative(lum, bare)
        k = bare[inner]
        x, y, v = sx[inner][k], sy[inner][k], rel[inner][k]
        out[name] = np.array([x @ x, x @ y, y @ y, x @ v, y @ v, v @ v, k.sum()])
    out["shadow"] = shadow_sums
    return out


def init(slug, style, zoom, basemap_path):
    fit_palette.init(slug, style, zoom, basemap_path)


def solve(sums):
    sxx, sxy, syy, sxv, syv, svv, n = sums
    a, b = np.linalg.solve([[sxx, sxy], [sxy, syy]], [sxv, syv])
    explained = (a * sxv + b * syv) / svv
    return a, b, explained


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("map")
    parser.add_argument("--zoom", type=int, default=4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--style")
    parser.add_argument("--basemaps", default="/basemaps")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    style_file = args.style or os.path.join(render.STYLES_DIR, f"colour_{args.map}.json")
    style = json.load(open(style_file))
    n = math.ceil(2 ** args.zoom / render.BLOCK_TILES)
    blocks = [(args.zoom, bx, by) for by in range(n) for bx in range(n)]
    total = {"ours": np.zeros(7), "basemap": np.zeros(7), "shadow": np.zeros((16, 2))}
    with multiprocessing.Pool(args.workers, init, (args.map, style_file, args.zoom, os.path.join(args.basemaps, f"{args.map}.webp"))) as pool:
        for result in pool.imap_unordered(task, blocks):
            if result:
                for key in total:
                    total[key] += result[key]
    ours, theirs = solve(total["ours"]), solve(total["basemap"])
    report = {"bare_pixels": int(total["ours"][6])}
    # Mean basemap luminance of the ground 5 px from tall objects, by direction (degrees, image axes: 0 east, 90 south)
    report["luminance_by_direction_of_tall_objects"] = {str(int(360 * k / 16)): round(float(total["shadow"][k, 0] / max(total["shadow"][k, 1], 1)), 1) for k in range(16)}
    for name, (a, b, explained) in (("ours", ours), ("basemap", theirs)):
        report[name] = {"length": float(math.hypot(a, b)), "toward_light_deg": round(math.degrees(math.atan2(-b, -a)), 1), "explained_variance": round(float(explained), 3)}
    ratio = report["basemap"]["length"] / report["ours"]["length"]
    report["shade_strength_now"] = style.get("SHADE_STRENGTH", render.SHADE_STRENGTH)
    report["shade_strength_matching"] = round(report["shade_strength_now"] * ratio, 3)
    print(json.dumps(report))
    if args.write:
        style["SHADE_STRENGTH"] = report["shade_strength_matching"]
        style["LIGHT_FROM"] = report["basemap"]["toward_light_deg"]
        json.dump(style, open(style_file, "w"), indent=1)


if __name__ == "__main__":
    main()
