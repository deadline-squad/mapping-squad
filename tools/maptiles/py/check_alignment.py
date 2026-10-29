"""Check that the detailed tiles sit exactly on SquadCalc's map frame.

Usage: check_alignment.py <map> [<map> ...]   (writes /check/<map>.json and overlay PNGs to /check)

Three independent comparisons per map, each on the building-dense windows of the map:

1. Tiles vs the precise heightmap SquadCalc serves (/heightmaps/<map>/, tools/heightmaps): buildings
   in the finest tiles (low-saturation pixels) against the heightmap's bumps (cells over 2.5 m above the
   21 m median), the heightmap placed with SquadCalc's grid convention (whole metres from corner0,
   squadHeightmaps.js getHeight). The offset is the peak of their cross-correlation, refined to
   sub-pixel by a parabola, in pixels of the finest zoom. Pass: under 1 px on both axes.
2. Height reference: the prepared ground against the served heightmap on open ground (cells within
   0.05 m of the 21 m median): the median difference must be under 1 cm, so contour labels read
   the same heights as SquadCalc's readouts.
3. Tiles vs the upstream SquadCalc images: zoom 5 of our tiles against the upstream basemap tiles
   (https://squadcalc.app/api/img/maps/<map>/basemap_hq/5_x_y.webp) by phase correlation of their
   edge images; reported in metres (the upstream images are drawn from the game's minimap
   texture, so this measures their placement as much as ours).
"""

import io
import json
import math
import os
import sys
import urllib.request

import numpy as np
from PIL import Image
from scipy import ndimage

UPSTREAM = "https://squadcalc.app/api/img/maps/{map}/basemap_hq/5_{x}_{y}.webp"
WINDOW_TILES = 4
WINDOWS = 4
SEARCH = 12


def mosaic(tiles_dir, z, x0, y0, n):
    image = np.zeros((256 * n, 256 * n, 3), np.uint8)
    for j in range(n):
        for i in range(n):
            path = os.path.join(tiles_dir, str(z), f"{x0 + i}_{y0 + j}.webp")
            if os.path.exists(path):
                image[256 * j:256 * (j + 1), 256 * i:256 * (i + 1)] = np.asarray(Image.open(path).convert("RGB"))
    return image


def objectness(rgb):
    """Buildings in the tiles: grey (low saturation) pixels that are neither white nor black."""
    f = rgb.astype(np.float32) / 255
    high, low = f.max(2), f.min(2)
    saturation = (high - low) / np.maximum(high, 1e-3)
    return ((saturation < 0.12) & (high > 0.2) & (high < 0.92)).astype(np.float32)


def peak_offset(a, b, search=SEARCH):
    """Shift (dx, dy) in pixels that best moves b onto a: argmax of their cross-correlation, sub-pixel."""
    a = ndimage.gaussian_filter(a - a.mean(), 2)
    b = ndimage.gaussian_filter(b - b.mean(), 2)
    corr = np.real(np.fft.ifft2(np.fft.fft2(a) * np.conj(np.fft.fft2(b))))
    corr = np.fft.fftshift(corr)
    cy, cx = corr.shape[0] // 2, corr.shape[1] // 2
    window = corr[cy - search:cy + search + 1, cx - search:cx + search + 1]
    j, i = np.unravel_index(window.argmax(), window.shape)

    def refine(m, p, n):
        return 0.0 if m == n else 0.5 * (m - n) / (m - 2 * p + n)
    dy = j - search + (refine(window[j - 1, i], window[j, i], window[j + 1, i]) if 0 < j < 2 * search else 0)
    dx = i - search + (refine(window[j, i - 1], window[j, i], window[j, i + 1]) if 0 < i < 2 * search else 0)
    peak = float(window[j, i] / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-9))
    return float(dx), float(dy), peak


def check(slug):
    prep = os.path.join("/prep", slug)
    tiles = os.path.join("/tiles", slug)
    meta = json.load(open(os.path.join(tiles, "meta.json")))
    hm_meta = json.load(open(os.path.join("/heightmaps", slug, "meta.json")))
    hm = np.asarray(Image.open(os.path.join("/heightmaps", slug, "heightmap.png"))).astype(np.float64) * hm_meta["z_step_m"]
    b = meta["bounds_m"]
    size_x, size_y = b["max_x"] - b["min_x"], b["max_y"] - b["min_y"]
    z = meta["maxNativeZoom"]
    full = 256 * 2 ** z
    px_x, px_y = size_x / full, size_y / full
    median = ndimage.median_filter(hm, size=21)
    bumps = (hm - median > 2.5).astype(np.float32)
    report = {"map": slug, "zoom": z, "m_per_px": round(px_x, 4), "windows": []}

    # Building-dense windows from the heightmap itself
    n = full // 256 // WINDOW_TILES
    counts = []
    for wy in range(n):
        for wx in range(n):
            u0, u1 = int(wx * WINDOW_TILES * 256 * px_x), int((wx + 1) * WINDOW_TILES * 256 * px_x)
            v0, v1 = int(wy * WINDOW_TILES * 256 * px_y), int((wy + 1) * WINDOW_TILES * 256 * px_y)
            counts.append((float(bumps[v0:v1, u0:u1].sum()), wx, wy))
    counts.sort(reverse=True)
    picked = [c for c in counts[:WINDOWS] if c[0] > 50]

    offsets = []
    for _, wx, wy in picked:
        x0, y0 = wx * WINDOW_TILES, wy * WINDOW_TILES
        rgb = mosaic(tiles, z, x0, y0, WINDOW_TILES)
        ours = objectness(rgb)
        gx = 256 * x0 + np.arange(256 * WINDOW_TILES) + 0.5
        gy = 256 * y0 + np.arange(256 * WINDOW_TILES) + 0.5
        cols = np.clip(np.rint(gx * px_x).astype(int), 0, hm.shape[1] - 1)
        rows = np.clip(np.rint(gy * px_y).astype(int), 0, hm.shape[0] - 1)
        theirs = bumps[np.ix_(rows, cols)]
        dx, dy, peak = peak_offset(ours, theirs)
        offsets.append((dx, dy))
        report["windows"].append({"tiles": [z, x0, y0], "dx_px": round(dx, 2), "dy_px": round(dy, 2), "correlation": round(peak, 3)})
        overlay = rgb.astype(np.float32)
        overlay[theirs > 0] = overlay[theirs > 0] * 0.5 + np.array([255, 0, 0]) * 0.5
        Image.fromarray(overlay.astype(np.uint8)).save(f"/check/{slug}_heightmap_{z}_{x0}_{y0}.png")
    if offsets:
        dx = float(np.median([o[0] for o in offsets]))
        dy = float(np.median([o[1] for o in offsets]))
        report["heightmap_offset_px"] = [round(dx, 2), round(dy, 2)]
        report["heightmap_offset_m"] = [round(dx * px_x, 3), round(dy * px_y, 3)]
        report["heightmap_pass"] = abs(dx) < 1 and abs(dy) < 1

    ground = np.load(os.path.join(prep, "ground.npy"))
    open_ground = np.abs(hm - median) < 0.05
    diff = (ground - hm)[open_ground]
    report["height_reference_median_diff_m"] = round(float(np.median(diff)), 4)
    report["height_reference_pass"] = abs(float(np.median(diff))) < 0.01

    # Upstream basemap at zoom 5
    up = []
    scale = 2 ** (z - 5)
    for _, wx, wy in picked[:2]:
        x5, y5 = (wx * WINDOW_TILES) // scale, (wy * WINDOW_TILES) // scale
        n5 = 2
        x5, y5 = min(x5, 32 - n5), min(y5, 32 - n5)
        try:
            theirs = np.zeros((256 * n5, 256 * n5, 3), np.uint8)
            for j in range(n5):
                for i in range(n5):
                    url = UPSTREAM.format(map=slug, x=x5 + i, y=y5 + j)
                    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "maptiles-check"}), timeout=30).read()
                    theirs[256 * j:256 * (j + 1), 256 * i:256 * (i + 1)] = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
        except Exception as e:
            report["upstream_error"] = str(e)
            break
        ours = mosaic(tiles, 5, x5, y5, n5)

        def edges(rgb):
            grey = ndimage.gaussian_filter(rgb.astype(np.float32).mean(2), 1.0)
            return np.hypot(ndimage.sobel(grey, 0), ndimage.sobel(grey, 1))
        dx, dy, peak = peak_offset(edges(ours), edges(theirs), 8)
        m5x, m5y = size_x / (256 * 32), size_y / (256 * 32)
        up.append({"tiles": [5, x5, y5], "dx_px": round(dx, 2), "dy_px": round(dy, 2), "dx_m": round(dx * m5x, 2), "dy_m": round(dy * m5y, 2), "correlation": round(peak, 3)})
        side = np.concatenate([ours, theirs], axis=1)
        Image.fromarray(side).save(f"/check/{slug}_upstream_5_{x5}_{y5}.png")
        blend = (ours.astype(np.float32) * 0.5 + theirs.astype(np.float32) * 0.5).astype(np.uint8)
        Image.fromarray(blend).save(f"/check/{slug}_upstream_blend_5_{x5}_{y5}.png")
    report["upstream"] = up
    json.dump(report, open(f"/check/{slug}.json", "w"), indent=1)
    print(json.dumps(report), flush=True)
    return report


def main(maps):
    failed = []
    for slug in maps:
        if not os.path.exists(os.path.join("/tiles", slug, "meta.json")):
            print(f"{slug}: no tiles", flush=True)
            failed.append(slug)
            continue
        report = check(slug)
        if not report.get("heightmap_pass", True) or not report["height_reference_pass"]:
            failed.append(slug)
    print("FAILED: " + " ".join(failed) if failed else "all aligned", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
