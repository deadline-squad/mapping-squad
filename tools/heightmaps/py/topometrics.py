"""Topographic metrics of a precise heightmap, per cell, in float64 (tools/heightmaps/topometrics).

Grid and frame: `z[row, col]` metres, `cell` metres between samples (meta.json `resolution_m`), the frame of
the heightmap's grid: east = +col, north = -row. The grid is the landscape's vertices (tools/heightmaps lattice.py): on a
turned landscape (meta.json `yaw_deg`, Skorpo's -2.006 deg) +col points `yaw_deg` clockwise of east, and map_summary turns
the aspect back to a compass bearing. Every metric uses the 3 x 3 window

    z1 z2 z3
    z4 z5 z6        (z2 north of z5, z4 west of z5)
    z7 z8 z9

and the map's edge repeats its outermost sample (`np.pad(mode="edge")`), so every cell has a value.

Gradients (Horn 1981), p = dz/dEast, q = dz/dNorth:

    p = ((z3 + 2 z6 + z9) - (z1 + 2 z4 + z7)) / (8 cell)
    q = ((z1 + 2 z2 + z3) - (z7 + 2 z8 + z9)) / (8 cell)

The central differences of the three rows (columns) are averaged with weights 1-2-1, which is exact for any
quadratic surface. slope = atan(hypot(p, q)); aspect = compass bearing the surface faces (downhill direction),
degrees clockwise from north, NaN on flat cells.

Second derivatives (Zevenbergen and Thorne 1987), exact for any quadratic surface:

    r = d2z/dE2  = (z4 - 2 z5 + z6) / cell^2
    t = d2z/dN2  = (z2 - 2 z5 + z8) / cell^2
    s = d2z/dEdN = (z3 - z1 - z9 + z7) / (4 cell^2)

Curvatures (positive = convex, i.e. a hilltop or ridge; negative = concave, a valley), with g = p^2 + q^2:

    profile = -(p^2 r + 2 p q s + q^2 t) / (g (1 + g)^(3/2))   curvature of the normal section along the slope line
    plan    = -(q^2 r - 2 p q s + p^2 t) / g^(3/2)             curvature of the contour line, 1/m, plan view

Both are NaN where the slope is under CURVATURE_MIN_SLOPE_DEG (0.5 deg): the heights are quantised (the heightmap's
16-bit step, up to 1.6 cm), a gradient that small is rounding, and the curvature of a contour line whose direction is
rounding is meaningless (it grows without bound as g goes to 0). The unit of both is 1/m.

Texture, over the same window (cell = centre z5, ring = the 8 neighbours):

    tpi       = z5 - mean(ring)                       Weiss 2001 topographic position index, m
    tri       = sqrt(sum((ring - z5)^2))              Riley et al. 1999 terrain ruggedness index, m
    roughness = max(window) - min(window)             GDAL's roughness, m
    tpi_10m   = z5 - mean of the other cells of the square window of side 2 * round(10 / cell) + 1, m

Openness and sky-view factor come from RVT (Relief Visualization Toolbox, Kokalj et al.), whose arithmetic is
float32; they are the only metrics not computed in float64.
"""

import json
import os

import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

# Curvatures are undefined on cells flatter than this
CURVATURE_MIN_SLOPE_DEG = 0.5
_MIN_GRADIENT_SQUARED = np.tan(np.radians(CURVATURE_MIN_SLOPE_DEG)) ** 2
# Window radius in metres of the large TPI and of the sky-view factor / openness search
TPI_RADIUS_M = 10.0
SVF_RADIUS_M = 20.0
SVF_DIRECTIONS = 16
# Rows of a block processed at a time; the halo covers the widest window
BLOCK_ROWS = 1024


def load_heightmap(map_dir):
    """Heights of a served heightmap in metres, float64.

    Reads heightmap.webp (level = red * 256 + green, height = z_min_m + level * step, as SquadCalc's
    heightmapWorker.js decodes it) and meta.json of `map_dir`, and checks the levels against meta's `levels_sum`.

    Args:
        map_dir: folder with meta.json and heightmap.webp.

    Returns:
        (z, meta): z of shape (rows, cols), meta the parsed meta.json.

    Raises:
        ValueError: the decoded levels do not match meta.json's checksum.
    """
    with open(os.path.join(map_dir, "meta.json")) as handle:
        meta = json.load(handle)
    pixels = np.asarray(Image.open(os.path.join(map_dir, meta["webp"]["file"])).convert("RGB"))
    levels = pixels[..., 0].astype(np.uint32) * 256 + pixels[..., 1]
    if "levels_sum" in meta["webp"] and int(levels.sum(dtype=np.uint64) % 2**32) != meta["webp"]["levels_sum"]:
        raise ValueError(f"levels_sum mismatch in {map_dir}")
    return meta["z_min_m"] + levels.astype(np.float64) * meta["webp"]["z_step_m"], meta


def _windows(z):
    """The nine shifted views z1..z9 of the edge-padded grid, each of z's shape."""
    padded = np.pad(z, 1, mode="edge")
    rows, cols = z.shape
    return [padded[dr:dr + rows, dc:dc + cols] for dr in range(3) for dc in range(3)]


def gradients(z, cell):
    """Horn gradients (p east, q north) in m/m."""
    z1, z2, z3, z4, _, z6, z7, z8, z9 = _windows(z)
    p = ((z3 + 2 * z6 + z9) - (z1 + 2 * z4 + z7)) / (8 * cell)
    q = ((z1 + 2 * z2 + z3) - (z7 + 2 * z8 + z9)) / (8 * cell)
    return p, q


def second_derivatives(z, cell):
    """Zevenbergen-Thorne second derivatives (r = d2z/dE2, s = d2z/dEdN, t = d2z/dN2) in 1/m."""
    z1, z2, z3, z4, z5, z6, z7, z8, z9 = _windows(z)
    r = (z4 - 2 * z5 + z6) / cell**2
    t = (z2 - 2 * z5 + z8) / cell**2
    s = (z3 - z1 - z9 + z7) / (4 * cell**2)
    return r, s, t


def slope_aspect(p, q):
    """Slope in degrees and aspect in degrees clockwise from north (NaN where flat) from Horn gradients."""
    slope = np.degrees(np.arctan(np.hypot(p, q)))
    aspect = np.degrees(np.arctan2(-p, -q)) % 360.0
    return slope, np.where((p == 0) & (q == 0), np.nan, aspect)


def curvatures(p, q, r, s, t):
    """Profile and plan curvature (1/m, positive convex), NaN where flatter than CURVATURE_MIN_SLOPE_DEG."""
    g = p * p + q * q
    flat = g < _MIN_GRADIENT_SQUARED
    safe = np.where(flat, 1.0, g)
    profile = -(p * p * r + 2 * p * q * s + q * q * t) / (safe * (1 + safe) ** 1.5)
    plan = -(q * q * r - 2 * p * q * s + p * p * t) / safe**1.5
    return np.where(flat, np.nan, profile), np.where(flat, np.nan, plan)


def texture(z, cell):
    """TPI, TRI, roughness (3 x 3) and the large-window TPI, in metres."""
    z1, z2, z3, z4, z5, z6, z7, z8, z9 = _windows(z)
    ring = (z1, z2, z3, z4, z6, z7, z8, z9)
    tpi = z5 - sum(ring) / 8
    tri = np.sqrt(sum((neighbour - z5) ** 2 for neighbour in ring))
    roughness = np.maximum.reduce(ring + (z5,)) - np.minimum.reduce(ring + (z5,))
    radius = max(1, round(TPI_RADIUS_M / cell))
    side = 2 * radius + 1
    window_mean = ndimage.uniform_filter(z, size=side, mode="nearest")
    tpi_large = z5 - (window_mean * side * side - z5) / (side * side - 1)
    return tpi, tri, roughness, tpi_large


def openness_svf(z, cell):
    """Sky-view factor and positive openness (degrees) of RVT, float32 arithmetic.

    Search radius SVF_RADIUS_M, SVF_DIRECTIONS directions. Imported lazily: only this function needs rvt.
    """
    import rvt.vis

    radius = max(1, round(SVF_RADIUS_M / cell))
    out = rvt.vis.sky_view_factor(
        z.astype(np.float32), cell, compute_svf=True, compute_opns=True,
        svf_n_dir=SVF_DIRECTIONS, svf_r_max=radius, svf_noise=0,
    )
    return out["svf"].astype(np.float64), out["opns"].astype(np.float64)


def halo_cells(cell):
    """Rows around a block that its metrics depend on."""
    return max(round(TPI_RADIUS_M / cell), round(SVF_RADIUS_M / cell)) + 2


def block_metrics(z, cell, with_sky=True):
    """All metrics of one block of heights, each an array of z's shape.

    Args:
        z: float64 heights (rows, cols).
        cell: metres between samples.
        with_sky: also compute svf and openness (needs rvt).

    Returns:
        dict name -> array; slope and aspect in degrees, curvatures in 1/m, texture in m, svf 0..1,
        openness in degrees (angle above the horizontal, up to 90 on a flat plane).
    """
    p, q = gradients(z, cell)
    r, s, t = second_derivatives(z, cell)
    slope, aspect = slope_aspect(p, q)
    profile, plan = curvatures(p, q, r, s, t)
    tpi, tri, roughness, tpi_large = texture(z, cell)
    metrics = {
        "elevation_m": z, "slope_deg": slope, "aspect_deg": aspect,
        "profile_curvature_per_m": profile, "plan_curvature_per_m": plan,
        "tpi_m": tpi, "tpi_10m_m": tpi_large, "tri_m": tri, "roughness_m": roughness,
    }
    if with_sky:
        metrics["svf"], metrics["openness_deg"] = openness_svf(z, cell)
    return metrics


def iter_blocks(z, cell, with_sky=True):
    """Yield (first_row, metrics) for consecutive row blocks covering z, halos cropped away."""
    halo = halo_cells(cell)
    for start in range(0, z.shape[0], BLOCK_ROWS):
        stop = min(start + BLOCK_ROWS, z.shape[0])
        lo, hi = max(0, start - halo), min(z.shape[0], stop + halo)
        metrics = block_metrics(z[lo:hi], cell, with_sky)
        yield start, {name: value[start - lo:stop - lo] for name, value in metrics.items()}


PERCENTILES = (1, 5, 25, 50, 75, 95, 99)


def summarize(values):
    """min, max, mean, std and percentiles of the finite values of an array, plus the count of NaN cells."""
    finite = values[np.isfinite(values)]
    stats = {"min": float(finite.min()), "max": float(finite.max()), "mean": float(finite.mean(dtype=np.float64)),
             "std": float(finite.std(dtype=np.float64))}
    for percentile, value in zip(PERCENTILES, np.percentile(finite, PERCENTILES)):
        stats[f"p{percentile}"] = float(value)
    stats["undefined_cells"] = int(values.size - finite.size)
    return stats


def map_summary(z, meta, with_sky=True):
    """The per-map summary table: every metric's statistics, slope class shares.

    Metrics are computed block by block and kept as float32 in memory one metric at a time (a 0.5 m map has
    66 million cells); statistics are taken in float64 over the stored values.
    """
    cell = meta["resolution_m"]
    stores = {}
    for start, metrics in iter_blocks(z, cell, with_sky):
        for name, value in metrics.items():
            store = stores.setdefault(name, np.empty(z.shape, dtype=np.float32))
            store[start:start + value.shape[0]] = value
    # The grid's north (-row) is yaw_deg clockwise of the world's
    yaw = meta.get("yaw_deg", 0.0)
    if yaw:
        stores["aspect_deg"] = (stores["aspect_deg"] + yaw) % 360.0
    slope = stores["slope_deg"]
    summary = {
        "map": meta["map"], "cell_m": cell, "rows": z.shape[0], "cols": z.shape[1],
        "metrics": {name: summarize(store) for name, store in stores.items()},
        "slope_share": {f"over_{limit}_deg": float((slope > limit).mean()) for limit in (15, 30, 45, 60)},
    }
    return summary
