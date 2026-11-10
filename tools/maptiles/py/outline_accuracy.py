"""How well the building outlines of the detailed tiles agree with the game's own minimap texture of a layer.

Usage: outline_accuracy.py <map> <pairs.json> <pair tag> <pair file .npz> <tile folder> [<tile folder> ...]

Seed and Skirmish layers ship a minimap texture of the game that shows the buildings as the game draws them
(squad-map-restoration: scripts/evaluate_render.py, mapsr.data.build_pair). The pair file holds that texture
(`truth`) and the play-area mask (`mask`) on a grid whose corner is the layer's lower corner of `pairs.json` and whose steps are
the layer's extent over the texture's size, per axis (a layer is not always square: Skorpo's x and y steps differ by 0.3 %).
Every tile folder is resampled onto that grid from its first zoom at least as fine as the step (at most its finest) and compared
with the texture where the buildings are: the footprints of the prepared object rasters (the scene's and the old collision
raster's, structures 3 m and taller), grown by BUILDING_ZONE_M, inside the play area.

Edges: the gradient magnitude of the smoothed luminance. The texture's edges are its strongest EDGE_SHARE percent, as in
evaluate_render.py; a tile picture's edges are its strongest pixels in the same number inside the zone as the texture has there,
so a picture that draws more lines (contours, forest texture) is not scored on its line density but on where its strongest lines
lie. The densities the global threshold would give are reported beside (`edge_density_zone`).

Shift: the texture's offset from the map frame is a property of the layer, not of a tile folder (the folders are placed in one
frame, check_alignment's HD gate), so one shift is found for the pair from the edge correlation summed over all folders. It is
used only when its peak is clear (MIN_PEAK_Z standard deviations above the correlation over the search window) and not at the
window's border; otherwise the pair is scored unshifted and `shift_measured` is false. Sign: a positive shift means the
texture lies east (x) or south (y, map y grows to the south) of the tiles. Then the F1 of the edges at 1, 2 and 3 px tolerance.
LPIPS and SSIM are not used: the style of the tiles is a map, not a photograph.

Container paths: /prep/<map>, tile folders as given.
"""

import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

BUILDING_ZONE_M = 4.0
EDGE_SHARE = 10
SEARCH_M = 30.0
MIN_HEIGHT_CM = 300
MIN_PEAK_Z = 5.0


def gradient(rgb):
    """Gradient magnitude of the smoothed luminance."""
    smooth = ndimage.gaussian_filter(rgb.astype(np.float32).mean(-1), 0.8)
    return np.hypot(ndimage.sobel(smooth, 1), ndimage.sobel(smooth, 0))


def strongest(magnitude, count, region):
    """The `count` strongest pixels of `magnitude` inside `region` (ties at the threshold included), and the same threshold outside."""
    inside = np.sort(magnitude[region])
    if count <= 0 or inside.size == 0:
        return np.zeros(magnitude.shape, bool)
    return magnitude >= inside[max(inside.size - count, 0)]


def correlation(truth_edges, edges):
    """Circular cross-correlation of the smoothed, centred edge maps: entry (dy, dx) is the agreement with `edges` rolled by it."""
    a, b = truth_edges.astype(np.float32), edges.astype(np.float32)
    a, b = ndimage.gaussian_filter(a - a.mean(), 1.5), ndimage.gaussian_filter(b - b.mean(), 1.5)
    return np.fft.irfft2(np.fft.rfft2(a) * np.conj(np.fft.rfft2(b)), a.shape)


def best_shift(product, search):
    """(dy, dx) px of the correlation's peak within `search` px, whether it is measured (clear and inside the window), its z-score."""
    rows, columns = product.shape
    window = np.fft.fftshift(product)[rows // 2 - search:rows // 2 + search + 1, columns // 2 - search:columns // 2 + search + 1]
    row, column = np.unravel_index(np.argmax(window), window.shape)
    z = float((window[row, column] - window.mean()) / max(float(window.std()), 1e-12))
    interior = 1 < row < window.shape[0] - 2 and 1 < column < window.shape[1] - 2
    measured = bool(interior and z >= MIN_PEAK_Z)
    return (int(row - search), int(column - search)) if measured else (0, 0), measured, z


def mosaic_on_grid(tiles_dir, zoom, frame, origin, step, size):
    """The tiles of a folder at a zoom resampled (bilinear box) onto the grid of `size` (w, h) at `origin` (m) with `step` (x, y) m."""
    min_x, min_y, size_x, size_y = frame
    pixels = 256 * 2 ** zoom
    x1, y1 = origin[0] + size[0] * step[0], origin[1] + size[1] * step[1]
    tx0, tx1 = int((origin[0] - min_x) / size_x * pixels // 256), int((x1 - min_x) / size_x * pixels // 256)
    ty0, ty1 = int((origin[1] - min_y) / size_y * pixels // 256), int((y1 - min_y) / size_y * pixels // 256)
    mosaic = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256, 3), np.uint8)
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            path = os.path.join(tiles_dir, str(zoom), f"{tx}_{ty}.webp")
            if os.path.exists(path):
                mosaic[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = np.asarray(Image.open(path).convert("RGB"))
    m_x, m_y = size_x / pixels, size_y / pixels
    left, top = min_x + tx0 * 256 * m_x, min_y + ty0 * 256 * m_y
    box = ((origin[0] - left) / m_x, (origin[1] - top) / m_y, (x1 - left) / m_x, (y1 - top) / m_y)
    return np.asarray(Image.fromarray(mosaic).resize(size, Image.BILINEAR, box=box))


def building_zone(prep_dir, origin, step, size):
    """Bool [h, w] on the grid: within BUILDING_ZONE_M of a structure 3 m or taller in the scene raster or the old collision raster."""
    zone = np.zeros((size[1], size[0]), bool)
    meta = json.load(open(os.path.join(prep_dir, "meta.json")))["bounds_m"]
    for prefix, level, cell in (("top", 3, 0.8), ("obj", 2, 1.0)):
        h = np.load(os.path.join(prep_dir, f"{prefix}_h{level}.npy"), mmap_mode="r")
        c = np.load(os.path.join(prep_dir, f"{prefix}_c{level}.npy"), mmap_mode="r")
        c0, c1 = int(max(0, (origin[0] - meta["min_x"]) / cell)), int(min(h.shape[1], (origin[0] + size[0] * step[0] - meta["min_x"]) / cell + 1))
        r0, r1 = int(max(0, (origin[1] - meta["min_y"]) / cell)), int(min(h.shape[0], (origin[1] + size[1] * step[1] - meta["min_y"]) / cell + 1))
        mask = (np.asarray(h[r0:r1, c0:c1]) >= MIN_HEIGHT_CM) & (np.asarray(c[r0:r1, c0:c1]) == 0)
        ys = origin[1] + (np.arange(size[1]) + 0.5) * step[1] - meta["min_y"]
        xs = origin[0] + (np.arange(size[0]) + 0.5) * step[0] - meta["min_x"]
        rows = np.clip(np.floor(ys / cell).astype(int) - r0, 0, mask.shape[0] - 1)
        cols = np.clip(np.floor(xs / cell).astype(int) - c0, 0, mask.shape[1] - 1)
        inside_rows = (ys / cell >= r0) & (ys / cell < r1)
        inside_cols = (xs / cell >= c0) & (xs / cell < c1)
        zone |= mask[np.ix_(rows, cols)] & inside_rows[:, None] & inside_cols[None, :]
    return ndimage.distance_transform_edt(~zone, sampling=(step[1], step[0])) <= BUILDING_ZONE_M


def scores(truth_edges, tile_edges, region):
    """Precision, recall and F1 of the tile edges against the truth edges over the region at 1, 2 and 3 px."""
    result = {"f1": [], "precision": [], "recall": []}
    for tolerance in (1, 2, 3):
        near_tile = ndimage.binary_dilation(tile_edges, iterations=tolerance)
        near_truth = ndimage.binary_dilation(truth_edges, iterations=tolerance)
        precision = (tile_edges & near_truth & region).sum() / max((tile_edges & region).sum(), 1)
        recall = (truth_edges & near_tile & region).sum() / max((truth_edges & region).sum(), 1)
        result["precision"].append(round(float(precision), 3))
        result["recall"].append(round(float(recall), 3))
        result["f1"].append(round(float(2 * precision * recall / max(precision + recall, 1e-9)), 3))
    return result


def evaluate(truth, pictures, region, step):
    """The pair's shift and, per tile picture, the edge F1 against the truth over the region (see the module's docstring)."""
    truth_magnitude = gradient(truth)
    truth_edges = truth_magnitude > np.percentile(truth_magnitude, 100 - EDGE_SHARE)
    count = int((truth_edges & region).sum())
    magnitudes = [gradient(p) for p in pictures]
    edges = [strongest(m, count, region) for m in magnitudes]
    search = int(round(SEARCH_M / min(step)))
    (dy, dx), measured, z = best_shift(sum(correlation(truth_edges, e) for e in edges), search)
    shift = {"shift_m": [round(dx * step[0], 2), round(dy * step[1], 2)], "shift_measured": measured, "shift_peak_z": round(z, 1)}
    zone = max(int(region.sum()), 1)
    results = []
    for magnitude, tile_edges in zip(magnitudes, edges):
        global_edges = magnitude > np.percentile(magnitude, 100 - EDGE_SHARE)
        results.append({"edge_density_zone": {"truth": round(count / zone, 3), "global_threshold": round(float((global_edges & region).sum()) / zone, 3)},
                        **scores(truth_edges, np.roll(tile_edges, (dy, dx), (0, 1)), region)})
    return shift, results


def main():
    slug, pairs_path, tag, pair_file = sys.argv[1:5]
    spec = next(p for p in json.load(open(pairs_path)) if p["tag"] == tag)
    meta = json.load(open(os.path.join("/prep", slug, "meta.json")))["bounds_m"]
    frame = (meta["min_x"], meta["min_y"], meta["max_x"] - meta["min_x"], meta["max_y"] - meta["min_y"])
    pair = np.load(pair_file)
    truth, mask = pair["truth"], pair["mask"]
    size = (truth.shape[1], truth.shape[0])
    c = spec["corners_cm"]
    origin = (min(c[0], c[2]) / 100, min(c[1], c[3]) / 100)
    step = (abs(c[2] - c[0]) / 100 / size[0], abs(c[3] - c[1]) / 100 / size[1])
    region = building_zone(os.path.join("/prep", slug), origin, step, size) & mask
    zooms, pictures = [], []
    for folder in sys.argv[5:]:
        finest = json.load(open(os.path.join(folder, "meta.json")))["maxNativeZoom"]
        zooms.append(next((z for z in range(finest + 1) if frame[2] / (256 * 2 ** z) <= step[0]), finest))
        pictures.append(mosaic_on_grid(folder, zooms[-1], frame, origin, step, size))
    shift, results = evaluate(truth, pictures, region, step)
    report = {"map": slug, "pair": tag, "step_m": [round(s, 5) for s in step], "building_zone_px": int(region.sum()), **shift,
              "folders": {folder: {"zoom": zoom, **result} for folder, zoom, result in zip(sys.argv[5:], zooms, results)}}
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
