"""Check that the detailed tiles sit exactly on SquadCalc's map frame.

Usage: check_alignment.py <map> [<map> ...]   (writes /check/<map>.json and overlay PNGs to /check)

Four comparisons per map, each on the building-dense windows of the map:

0. Tiles vs the Standard HD layer (/hd/<map>-hd/, tools/maprender), the gate of the check: the HD layer is a camera render of
   the same client meshes, independent of this pipeline's rasterizer, so the two must coincide wherever there are buildings.
   Windows of HD_WINDOW_M around the largest roofs (at least HD_SPACING_M apart, wholly inside the map: a window over the map's
   edge holds no picture beyond it, e.g. the walls along Gorodok's border) are resampled from both layers' finest
   zooms to HD_PIXEL_M per pixel; the offset is the sub-pixel peak of the cross-correlation of their edge images. Pass: the
   median over at least HD_MIN_WINDOWS measured windows under HD_PASS_M on both axes (the scene raster's cell: the HD
   layer's own pixel is 0.25 m, so its sub-pixel peak resolves a few centimetres). A positive offset means the tiles lie east
   (x) or south (y) of HD. Beside the median: the largest deviation of a measured window from it and how many windows lie
   within HD_PASS_M themselves. Maps without an HD layer fall back to the heightmap gate (1).

1. Tiles vs the precise heightmap SquadCalc serves (/heightmaps/<map>/, tools/heightmaps), from the server's collision: buildings
   in the finest tiles (the edges of their picture, whatever the style) against the heightmap's objects (over 2 m above the bare
   ground), in the windows with the most buildings, the heightmap read at the points of the prepared ground's 1 m grid the way
   SquadCalc reads it (served_on_ground; squadHeightmaps.js getHeight), each pixel taking the nearest point. The offset is the
   peak of their cross-correlation, refined to sub-pixel by a parabola, in pixels of the finest zoom; windows without a clear
   peak are reported but not counted. Pass: the median over at least two windows under 1 px on both axes. Its windows are
   1 m samples, so on the finest zooms (0.07 m per pixel) a correct map can read a pixel off: a gate only where no HD layer
   exists.
2. Height reference: the prepared ground against the served heightmap where they agree within 5 cm
   (open ground; the share is reported): the median difference must be under 1 cm, so contour labels read
   the same heights as SquadCalc's readouts.
3. Tiles vs the upstream SquadCalc images: zoom 5 of our tiles against the upstream basemap tiles
   (https://squadcalc.app/api/img/maps/<map>/basemap_hq/5_x_y.webp) by phase correlation of their
   edge images; reported in metres (the upstream images are drawn from the game's minimap
   texture, so this measures their placement as much as ours).
"""

import io
import json
import os
import sys
import urllib.request

import numpy as np
from PIL import Image
from scipy import ndimage

import compare_crops
import lattice

UPSTREAM = "https://squadcalc.app/api/img/maps/{map}/basemap_hq/5_{x}_{y}.webp"
WINDOW_TILES = 4
WINDOWS = 4
# Share of a window that the served heightmap must show as objects for the window to be measured
MIN_HEIGHTMAP_OBJECTS = 0.01
SEARCH = 12
HD_DIR = "/hd"
HD_WINDOW_M = 76.8
HD_PIXEL_M = 0.1
HD_WINDOWS = 8
HD_SPACING_M = 150.0
HD_SEARCH_PX = 20
HD_MIN_PEAK = 0.2
HD_MIN_WINDOWS = 4
HD_PASS_M = 0.1


def mosaic(tiles_dir, z, x0, y0, n):
    image = np.zeros((256 * n, 256 * n, 3), np.uint8)
    for j in range(n):
        for i in range(n):
            path = os.path.join(tiles_dir, str(z), f"{x0 + i}_{y0 + j}.webp")
            if os.path.exists(path):
                image[256 * j:256 * (j + 1), 256 * i:256 * (i + 1)] = np.asarray(Image.open(path).convert("RGB"))
    return image


def edge_strength(image):
    """Gradient magnitude of the smoothed picture (luminance of an RGB picture, or a mask): where outlines, walls and footprints are."""
    plane = image.astype(np.float32)
    if plane.ndim == 3:
        plane = plane.mean(2)
    smooth = ndimage.gaussian_filter(plane, 1.5)
    return np.hypot(ndimage.sobel(smooth, 0), ndimage.sobel(smooth, 1))


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


def served_on_ground(folder, ground):
    """The served heightmap of ``folder`` (m above its z_min_m) at the points of the prepared ground's 1 m grid.

    The heightmap's samples are the landscape's vertices (tools/heightmaps lattice.py: 0.5 m to 1.2 m apart, off the
    minimap's corner, turned on Skorpo); it is read at the ground's points the way SquadCalc reads it (lattice.on_grid).
    """
    with open(os.path.join(folder, "meta.json")) as handle:
        meta = json.load(handle)
    with Image.open(os.path.join(folder, "heightmap.png")) as image:
        heights = np.asarray(image).astype(np.float32) * np.float32(meta["z_step_m"])
    b = meta["bounds_m"]
    step = (b["max_x"] - b["min_x"]) / (ground.shape[1] - 1)
    if lattice.minimap_shape(b, step) != ground.shape:
        raise ValueError(f"heightmap bounds {b} do not span the ground grid {ground.shape}")
    return lattice.on_grid(heights, lattice.from_meta(meta), b, step)


def hd_window_centres(labels, bounds):
    """Centres (m) of the HD gate's windows: the largest roofs, at least HD_SPACING_M apart, each window wholly inside the map."""
    half = HD_WINDOW_M / 2
    centres = []
    for label in sorted(labels, key=lambda item: -item["area"]):
        if len(centres) == HD_WINDOWS:
            break
        inside = bounds["min_x"] + half <= label["x"] <= bounds["max_x"] - half and bounds["min_y"] + half <= label["y"] <= bounds["max_y"] - half
        if inside and all(np.hypot(label["x"] - x, label["y"] - y) >= HD_SPACING_M for x, y in centres):
            centres.append((label["x"], label["y"]))
    return centres


def hd_alignment(slug, tiles, labels):
    """Report of comparison 0 (see the module docstring), or None when the map has no HD layer."""
    hd = os.path.join(HD_DIR, f"{slug}-hd")
    if not os.path.exists(os.path.join(hd, "meta.json")):
        return None
    size_px = round(HD_WINDOW_M / HD_PIXEL_M)
    centres = hd_window_centres(labels, json.load(open(os.path.join(tiles, "meta.json")))["bounds_m"])
    windows, offsets = [], []
    for x, y in centres:
        ours = np.asarray(compare_crops.window(tiles, (x, y), HD_WINDOW_M, size_px))
        theirs = np.asarray(compare_crops.window(hd, (x, y), HD_WINDOW_M, size_px))
        dx, dy, peak = peak_offset(edge_strength(ours), edge_strength(theirs), HD_SEARCH_PX)
        measured = max(abs(dx), abs(dy)) < HD_SEARCH_PX - 0.5 and peak >= HD_MIN_PEAK
        if measured:
            offsets.append((dx * HD_PIXEL_M, dy * HD_PIXEL_M))
        windows.append({"centre_m": [round(x, 1), round(y, 1)], "dx_m": round(dx * HD_PIXEL_M, 3), "dy_m": round(dy * HD_PIXEL_M, 3),
                        "correlation": round(peak, 3), "measured": measured})
        Image.fromarray(np.concatenate([ours, theirs], axis=1)).save(f"/check/{slug}_hd_{x:.0f}_{y:.0f}.png")
    return {"windows": windows, **hd_verdict(offsets)}


def hd_verdict(offsets):
    """The HD gate over the measured windows' offsets (m): their number, median offset, the largest deviation of one window from
    the median, how many lie within HD_PASS_M, and pass (at least HD_MIN_WINDOWS, the median within HD_PASS_M on both axes)."""
    report = {"measured": len(offsets), "pass": False}
    if offsets:
        dx, dy = float(np.median([o[0] for o in offsets])), float(np.median([o[1] for o in offsets]))
        report["offset_m"] = [round(dx, 3), round(dy, 3)]
        report["max_deviation_m"] = round(max(max(abs(o[0] - dx), abs(o[1] - dy)) for o in offsets), 3)
        report["within_pass_m"] = sum(max(abs(o[0]), abs(o[1])) < HD_PASS_M for o in offsets)
        report["pass"] = abs(dx) < HD_PASS_M and abs(dy) < HD_PASS_M and len(offsets) >= HD_MIN_WINDOWS
    return report


def check(slug):
    prep = os.path.join("/prep", slug)
    tiles = os.path.join("/tiles", slug)
    meta = json.load(open(os.path.join(tiles, "meta.json")))
    b = meta["bounds_m"]
    size_x, size_y = b["max_x"] - b["min_x"], b["max_y"] - b["min_y"]
    z = meta["maxNativeZoom"]
    full = 256 * 2 ** z
    px_x, px_y = size_x / full, size_y / full
    ground = np.load(os.path.join(prep, "ground.npy"))
    hm = served_on_ground(os.path.join("/heightmaps", slug), ground)
    # Objects of the served heightmap: where it rises 2 m above the bare ground
    bumps = (hm - ground > 2.0).astype(np.float32)
    report = {"map": slug, "zoom": z, "m_per_px": round(px_x, 4), "windows": []}

    # The windows with the most buildings: the roof labels of the scene raster that the tiles draw (scene_prep.py), else those of prep.py
    labels_path = os.path.join(prep, "top_labels.json")
    if not os.path.exists(labels_path):
        labels_path = os.path.join(prep, "labels.json")
    n = full // 256 // WINDOW_TILES
    counts = {}
    labels = json.load(open(labels_path))
    for label in labels:
        key = (int((label["x"] - b["min_x"]) / px_x // (256 * WINDOW_TILES)), int((label["y"] - b["min_y"]) / px_y // (256 * WINDOW_TILES)))
        counts[key] = counts.get(key, 0) + label["area"]
    ranked = sorted(((area, wx, wy) for (wx, wy), area in counts.items() if 0 <= wx < n and 0 <= wy < n), reverse=True)

    offsets, picked = [], []
    for area, wx, wy in ranked:
        if len(picked) == WINDOWS:
            break
        x0, y0 = wx * WINDOW_TILES, wy * WINDOW_TILES
        gx = 256 * x0 + np.arange(256 * WINDOW_TILES) + 0.5
        gy = 256 * y0 + np.arange(256 * WINDOW_TILES) + 0.5
        cols = np.clip(np.rint(gx * px_x).astype(int), 0, hm.shape[1] - 1)
        rows = np.clip(np.rint(gy * px_y).astype(int), 0, hm.shape[0] - 1)
        theirs = bumps[np.ix_(rows, cols)]
        # The served heightmap leaves out some buildings of the scene (Blueprint actors on a few maps): a window where it
        # has next to no objects has nothing to correlate with
        if theirs.mean() < MIN_HEIGHTMAP_OBJECTS:
            continue
        picked.append((area, wx, wy))
        rgb = mosaic(tiles, z, x0, y0, WINDOW_TILES)
        dx, dy, peak = peak_offset(edge_strength(rgb), edge_strength(theirs))
        # A peak on the search boundary or a weak one is no measurement (too few buildings in the window)
        measured = max(abs(dx), abs(dy)) < SEARCH - 0.5 and peak >= 0.1
        if measured:
            offsets.append((dx, dy))
        report["windows"].append({"tiles": [z, x0, y0], "dx_px": round(dx, 2), "dy_px": round(dy, 2), "correlation": round(peak, 3), "measured": measured})
        overlay = rgb.astype(np.float32)
        overlay[theirs > 0] = overlay[theirs > 0] * 0.5 + np.array([255, 0, 0]) * 0.5
        Image.fromarray(overlay.astype(np.uint8)).save(f"/check/{slug}_heightmap_{z}_{x0}_{y0}.png")
    report["heightmap_pass"] = False
    if offsets:
        dx = float(np.median([o[0] for o in offsets]))
        dy = float(np.median([o[1] for o in offsets]))
        report["heightmap_offset_px"] = [round(dx, 2), round(dy, 2)]
        report["heightmap_offset_m"] = [round(dx * px_x, 3), round(dy * px_y, 3)]
        report["heightmap_pass"] = abs(dx) < 1 and abs(dy) < 1 and len(offsets) >= 2

    hd = hd_alignment(slug, tiles, labels)
    if hd is not None:
        report["hd"] = hd
    report["alignment_pass"] = hd["pass"] if hd is not None else report["heightmap_pass"]

    open_ground = np.abs(hm - ground) < 0.05
    diff = (ground - hm)[open_ground]
    report["height_reference_median_diff_m"] = round(float(np.median(diff)), 4)
    report["height_reference_open_ground_share"] = round(float(open_ground.mean()), 4)
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
        if not report["alignment_pass"] or not report["height_reference_pass"]:
            failed.append(slug)
    print("FAILED: " + " ".join(failed) if failed else "all aligned", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(sys.argv[1:])
