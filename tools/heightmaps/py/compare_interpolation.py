"""How far a heightmap grid is from the game's collision surface, by grid step and interpolation.

Usage: compare_interpolation.py <extract root> <heightmaps dir> <map> [points]

The truth is the landscape's triangle surface (landscape.triangle_surface) at random points inside the
map's landscape. Every candidate is a grid of that surface sampled on the heightmap's bounds, read back
with an interpolation; "node" is how its heights were taken from the landscape and "read" how a page
interpolates between them:
    node bilinear, read bilinear  the first heightmaps (a grid from the bounds' corner), read as SquadCalc did then
    node triangle, read triangle  the game surface on the 1 m grid, read along the game's diagonal
    ... and the same on a 0.5 m grid.
Errors are in metres over terrain only (no objects), printed as max / p99 / RMS. The heightmaps are now built on the
landscape's own vertices (lattice.py), where the triangle read is the game's surface; compare_native_vertices.py measures them.
"""

import json
import os
import sys

import numpy as np

import landscape
import maps

CHUNK = 1_000_000


def grid_nodes(actors, bounds, step, method):
    """Terrain heights [rows, cols] in metres on a grid from the bounds' min corner, NaN outside the landscape."""
    xs = np.arange(bounds["min_x"], bounds["max_x"] + step / 2, step)
    ys = np.arange(bounds["min_y"], bounds["max_y"] + step / 2, step)
    grid = np.full((len(ys), len(xs)), np.nan, dtype=np.float32)
    rows_per_chunk = max(1, CHUNK // len(xs))
    for start in range(0, len(ys), rows_per_chunk):
        gx, gy = np.meshgrid(xs * 100, ys[start:start + rows_per_chunk] * 100)
        chunk = np.full(gx.shape, np.nan)
        for actor in actors:
            chunk = np.where(np.isnan(chunk), landscape.sample_world(actor, gx, gy, method) / 100, chunk)
        grid[start:start + rows_per_chunk] = chunk
    return grid


def read(grid, bounds, step, xs, ys, mode):
    """Height at world points (metres) from a grid, interpolated as `mode`: bilinear, triangle or nearest."""
    col = (xs - bounds["min_x"]) / step
    row = (ys - bounds["min_y"]) / step
    if mode == "nearest":
        return grid[np.rint(row).astype(int), np.rint(col).astype(int)].astype(np.float64)
    if mode == "triangle":
        return landscape.triangle_surface(grid.astype(np.float64), col, row)
    c0 = np.floor(col).astype(int)
    r0 = np.floor(row).astype(int)
    fx, fy = col - c0, row - r0
    return (grid[r0, c0] * (1 - fx) * (1 - fy) + grid[r0, c0 + 1] * fx * (1 - fy)
            + grid[r0 + 1, c0] * (1 - fx) * fy + grid[r0 + 1, c0 + 1] * fx * fy)


def summary(error):
    error = np.abs(error[~np.isnan(error)])
    return f"max {error.max():7.3f}  p99 {np.percentile(error, 99):7.3f}  rms {np.sqrt((error ** 2).mean()):7.4f}"


def main(extract_root, heightmaps, slug, points="1000000"):
    meta = json.load(open(os.path.join(heightmaps, slug, "meta.json")))
    bounds = meta["bounds_m"]
    actors = []
    for level in maps.MAPS[slug][1]:
        actors += list(landscape.assemble(os.path.join(extract_root, "landscapes", level), transpose=False).values())
    rng = np.random.default_rng(1)
    xs = rng.uniform(bounds["min_x"] + 2, bounds["max_x"] - 2, int(points))
    ys = rng.uniform(bounds["min_y"] + 2, bounds["max_y"] - 2, int(points))
    truth = np.full(xs.shape, np.nan)
    for actor in actors:
        truth = np.where(np.isnan(truth), landscape.sample_world(actor, xs * 100, ys * 100, "triangle") / 100, truth)
    covered = ~np.isnan(truth)
    print(f"{slug}: {covered.sum()} of {len(xs)} random points on the landscape")
    for step in (1.0, 0.5):
        for node, mode in (("bilinear", "bilinear"), ("triangle", "bilinear"), ("triangle", "triangle"), ("triangle", "nearest")):
            if step == 0.5 and mode == "nearest":
                continue
            grid = grid_nodes(actors, bounds, step, node)
            estimate = read(grid, bounds, step, xs, ys, mode)
            print(f"  step {step} m  node {node:8s} read {mode:8s}  {summary((estimate - truth)[covered])}", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
