"""Colour distance between a tile layer and the upstream basemap of the same map.

Usage: colour_distance.py <map> <tiles folder> [--zoom Z] [--cell-m 64] [--write-grade <style file>]

Both images are brought to 256 * 2**Z pixels over the map bounds (the basemap spans the same bounds as
the tiles, see check_alignment.py), averaged over square cells of about --cell-m metres, and the mean
colours of each cell compared in CIELAB: mean CIE76 and CIEDE2000 over the cells. Also reports the CIE76 the
best per-channel linear colour grade of the layer would give, to judge whether a global grade is worth adding.
Prints one JSON line.
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image


def mosaic(folder, z):
    """RGB image [H, W, 3] of all tiles of zoom z in folder."""
    n = 2 ** z
    out = np.zeros((256 * n, 256 * n, 3), np.uint8)
    for y in range(n):
        for x in range(n):
            out[y * 256:(y + 1) * 256, x * 256:(x + 1) * 256] = np.asarray(Image.open(os.path.join(folder, str(z), f"{x}_{y}.webp")).convert("RGB"))
    return out


def basemap(path, size):
    """Upstream basemap resampled to size x size pixels."""
    return np.asarray(Image.open(path).convert("RGB").resize((size, size), Image.LANCZOS))


def to_lab(rgb):
    """sRGB [..., 3] (0..255) to CIELAB, D65."""
    c = rgb.astype(np.float64) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def delta_e2000(a, b):
    """CIEDE2000 between Lab arrays [..., 3] (Sharma, Wu, Dalal 2005, kL = kC = kH = 1)."""
    l1, a1, b1 = a[..., 0], a[..., 1], a[..., 2]
    l2, a2, b2 = b[..., 0], b[..., 1], b[..., 2]
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cbar7 = ((c1 + c2) / 2) ** 7
    g = 0.5 * (1 - np.sqrt(cbar7 / (cbar7 + 25 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dlp, dcp = l2 - l1, c2p - c1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(c1p * c2p == 0, 0, dh)
    dhp = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh) / 2)
    lbar, cbar = (l1 + l2) / 2, (c1p + c2p) / 2
    hsum = h1p + h2p
    hbar = np.where(np.abs(h1p - h2p) > 180, (hsum + 360) / 2, hsum / 2)
    hbar = np.where(c1p * c2p == 0, hsum, hbar)
    t = (1 - 0.17 * np.cos(np.radians(hbar - 30)) + 0.24 * np.cos(np.radians(2 * hbar)) + 0.32 * np.cos(np.radians(3 * hbar + 6))
         - 0.20 * np.cos(np.radians(4 * hbar - 63)))
    sl = 1 + 0.015 * (lbar - 50) ** 2 / np.sqrt(20 + (lbar - 50) ** 2)
    sc, sh = 1 + 0.045 * cbar, 1 + 0.015 * cbar * t
    rt = -2 * np.sqrt(cbar ** 7 / (cbar ** 7 + 25 ** 7)) * np.sin(np.radians(60 * np.exp(-(((hbar - 275) / 25) ** 2))))
    return np.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dhp / sh) ** 2 + rt * (dcp / sc) * (dhp / sh))


def cell_means(image, cell):
    """Mean colour of cell x cell pixel blocks (the edge remainder is dropped): [H // cell, W // cell, 3]."""
    h, w = image.shape[0] // cell * cell, image.shape[1] // cell * cell
    return image[:h, :w].astype(np.float64).reshape(h // cell, cell, w // cell, cell, 3).mean(axis=(1, 3))


def distances(ours, theirs, m_per_px, cell_m=64.0):
    """Mean CIE76 and CIEDE2000 between the cell mean colours of two RGB images of the same size."""
    cell = max(1, round(cell_m / m_per_px))
    a, b = to_lab(cell_means(ours, cell)), to_lab(cell_means(theirs, cell))
    ours_rgb, theirs_rgb = cell_means(ours, cell).reshape(-1, 3), cell_means(theirs, cell).reshape(-1, 3)
    gain, offset = np.zeros(3), np.zeros(3)
    for c in range(3):
        gain[c], offset[c] = np.polyfit(ours_rgb[:, c], theirs_rgb[:, c], 1)
    graded = to_lab(np.clip(ours_rgb * gain + offset, 0, 255).reshape(a.shape))
    return {"grade_gain": gain.round(4).tolist(), "grade_offset": offset.round(2).tolist(),
            "de76_with_best_grade": float(np.linalg.norm(graded - b, axis=-1).mean()), "cell_px": cell, "cell_m": round(cell * m_per_px, 1), "cells": int(a.shape[0] * a.shape[1]),
            "de76": float(np.linalg.norm(a - b, axis=-1).mean()), "de2000": float(delta_e2000(a, b).mean()),
            "mean_L_ours": float(a[..., 0].mean()), "mean_L_basemap": float(b[..., 0].mean())}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("map")
    parser.add_argument("tiles")
    parser.add_argument("--zoom", type=int, default=4)
    parser.add_argument("--cell-m", type=float, default=64.0)
    parser.add_argument("--basemaps", default="/basemaps")
    parser.add_argument("--write-grade", help="store the best per-channel grade in this style file as GRADE (render.py applies it)")
    args = parser.parse_args()
    meta = json.load(open(os.path.join(args.tiles, "meta.json")))
    b = meta["bounds_m"]
    size = 256 * 2 ** args.zoom
    m_per_px = (b["max_x"] - b["min_x"]) / size
    ours = mosaic(args.tiles, args.zoom)
    theirs = basemap(os.path.join(args.basemaps, f"{args.map}.webp"), size)
    result = {"map": args.map, "tiles": os.path.basename(args.tiles.rstrip("/")), "zoom": args.zoom, "m_per_px": round(m_per_px, 3)}
    result.update(distances(ours, theirs, m_per_px, args.cell_m))
    print(json.dumps(result))
    if args.write_grade:
        style = json.load(open(args.write_grade))
        style["GRADE"] = {"gain": result["grade_gain"], "offset": result["grade_offset"]}
        json.dump(style, open(args.write_grade, "w"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
