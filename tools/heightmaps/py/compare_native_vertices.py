"""Error of a heightmap grid against the game landscape's own vertices, for maps whose landscape is finer than 1 m.

Usage: compare_native_vertices.py <extract root> <map> <heightmaps dir> [<heightmaps dir> ...] [--points-out points.json]

The truth is the raw height of every vertex of the map's landscape (landscape collision heightfield, placed with
the actor's transform) inside the minimap bounds. Each candidate is read at the vertex's world position with the
rule of SquadCalc's getHeight (the game's triangles, landscape.triangle_surface):
    terrain grids   the pipeline's terrain on a grid of 1 m and of the map's maps.cell_m (build_heightmap.game_terrain);
    heightmap dirs  built heightmaps (heightmap.webp, else heightmap.png, with meta.json): terrain and objects fused,
                    so only the vertices where the finest given heightmap shows the landscape (within TERRAIN_TOLERANCE_M
                    of the vertex: no building, rock or wall there) are counted, the same set for every directory.
                    The finest heightmap sits on the vertices, so its own error there is its quantisation step.
Errors in metres over the same vertices, printed as RMS / p99 / max. With --points-out, 2000 random vertices on terrain are added to a JSON file {"<map>": [[x, y, z], ...]} (world metres) for tools/browser_check/heightmap_native.mjs.
"""

import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image

import build_heightmap
import compare_interpolation
import heightmap_webp
import landscape
import maps

CHUNK = 2_000_000
TERRAIN_TOLERANCE_M = 0.02


def vertices(level_dirs, bounds):
    """World (x, y, z) in metres of every landscape vertex inside the bounds, as float64 arrays (first actor wins)."""
    xs, ys, zs = [], [], []
    for level in level_dirs:
        for grid, x0, y0, (loc, yaw, scale), _ in landscape.assemble(level, transpose=False).values():
            rows, cols = grid.shape
            gy, gx = np.mgrid[0:rows, 0:cols]
            lx, ly = (gx + x0) * scale[0], (gy + y0) * scale[1]
            c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
            x = (loc[0] + c * lx - s * ly) / 100
            y = (loc[1] + s * lx + c * ly) / 100
            keep = (~np.isnan(grid)) & (x >= bounds["min_x"]) & (x <= bounds["max_x"]) & (y >= bounds["min_y"]) & (y <= bounds["max_y"])
            xs.append(x[keep])
            ys.append(y[keep])
            zs.append(((loc[2] + scale[2] * grid / 128) / 100)[keep])
    return np.concatenate(xs), np.concatenate(ys), np.concatenate(zs)


def read_chunked(grid, bounds, step, xs, ys):
    """Heights of `grid` at world points with the triangle rule, in chunks."""
    out = np.empty(len(xs))
    for first in range(0, len(xs), CHUNK):
        part = slice(first, first + CHUNK)
        out[part] = compare_interpolation.read(grid, bounds, step, xs[part], ys[part], "triangle")
    return out


def load_heightmap(directory):
    """(heights in metres [rows, cols], meta) of a built heightmap folder."""
    meta = json.load(open(os.path.join(directory, "meta.json")))
    if "webp" in meta and os.path.exists(os.path.join(directory, "heightmap.webp")):
        levels, step = heightmap_webp.decode(os.path.join(directory, "heightmap.webp")), meta["webp"]["z_step_m"]
    else:
        levels, step = np.asarray(Image.open(os.path.join(directory, "heightmap.png"))), meta["z_step_m"]
    return levels.astype(np.float64) * step + meta["z_min_m"], meta


def summary(error):
    error = np.abs(error[~np.isnan(error)])
    return f"rms {np.sqrt((error ** 2).mean()) * 100:8.3f} cm  p99 {np.percentile(error, 99) * 100:8.3f} cm  max {error.max() * 100:9.2f} cm"


def main(extract_root, slug, heightmap_dirs, points_out=None):
    levels = maps.MAPS[slug][1]
    level_dirs = [os.path.join(extract_root, "landscapes", level) for level in levels]
    built = [load_heightmap(os.path.join(d, slug)) for d in heightmap_dirs]
    bounds = built[0][1]["bounds_m"]
    xs, ys, zs = vertices(level_dirs, bounds)
    print(f"{slug}: {len(xs)} landscape vertices inside the bounds")

    candidates = {}
    for cell in sorted({1.0, maps.cell_m(slug)}, reverse=True):
        meta = {"bounds_m": bounds, "resolution_m": cell}
        terrain = build_heightmap.game_terrain(level_dirs, meta, build_heightmap.grid_shape(meta, cell), cell)
        candidates[f"terrain grid {cell} m"] = read_chunked(terrain, bounds, cell, xs, ys)
        del terrain
    reads = {}
    for directory, (grid, meta) in zip(heightmap_dirs, built):
        reads[directory] = read_chunked(grid, bounds, meta["resolution_m"], xs, ys)
        candidates[f"heightmap {directory} ({meta['resolution_m']} m)"] = reads[directory]

    finest = min(range(len(built)), key=lambda i: built[i][1]["resolution_m"])
    on_terrain = np.abs(reads[heightmap_dirs[finest]] - zs) <= TERRAIN_TOLERANCE_M
    for name, estimate in candidates.items():
        error = estimate - zs
        if name.startswith("heightmap"):
            print(f"  {name:48s} {on_terrain.sum()} vertices on terrain: {summary(error[on_terrain])}", flush=True)
        else:
            print(f"  {name:48s} {int((~np.isnan(error)).sum())} vertices read: {summary(error)}", flush=True)

    if points_out:
        # Vertices the heightmap holds to its quantisation (half a step): the page must read them back to the same
        step = built[finest][1].get("webp", {}).get("z_step_m", built[finest][1]["z_step_m"])
        exact = np.abs(reads[heightmap_dirs[finest]] - zs) <= step / 2 + 1e-4
        chosen = np.random.default_rng(3).choice(np.flatnonzero(exact), 2000, replace=False)
        points = json.load(open(points_out)) if os.path.exists(points_out) else {}
        points[slug] = [[round(float(xs[i]), 3), round(float(ys[i]), 3), round(float(zs[i]), 5)] for i in chosen]
        json.dump(points, open(points_out, "w"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("extract_root")
    parser.add_argument("slug")
    parser.add_argument("heightmap_dirs", nargs="+")
    parser.add_argument("--points-out")
    args = parser.parse_args()
    main(args.extract_root, args.slug, args.heightmap_dirs, args.points_out)
