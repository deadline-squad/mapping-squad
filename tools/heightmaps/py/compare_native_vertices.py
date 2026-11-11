"""Error of built heightmaps against the game landscape's own vertices and its collision between them.

Usage: compare_native_vertices.py <extract root> <map> <heightmaps dir> [<heightmaps dir> ...] [--points-out points.json]

The truth is the raw height of every vertex of the map's landscape (landscape collision heightfield, placed with the actor's
transform) inside the minimap bounds, and between the vertices the game's collision (landscape.triangle_surface) at
CANDIDATES random points of the bounds. Each heightmap directory (heightmap.webp, else heightmap.png, with meta.json) is read
there with the rule of SquadCalc's getHeight (the game's triangles, lattice.read) on its own grid (lattice.from_meta:
meta.json's origin_m, resolution_m and yaw_deg, or the bounds' min corner for a heightmap built before them). Terrain and
objects are fused, so only the points where every given heightmap holds the bare landscape are counted (bare_mask: the four
nodes of the quad around the point within half the heightmap's step of the terrain its build put there), the same points for
every directory. A heightmap on the vertices has its quantisation step (half of it) as its only error there.
Errors over the vertices and over the points between them, printed as RMS / p99 / max. With --points-out, POINTS of those
vertices and POINTS of those points are added to a JSON file {"<map>": [[x, y, z], ...]} (world metres, z the game's
collision) for tools/browser_check/heightmap_native.mjs.
"""

import argparse
import json
import math
import os

import numpy as np
from PIL import Image

import build_heightmap
import heightmap_webp
import landscape
import lattice
import maps

CHUNK = 2_000_000
POINTS = 1000
CANDIDATES = 200_000


def vertex_chunks(level_dirs, bounds):
    """World (x, y, z) in metres (float64 arrays) of the landscape vertices inside the bounds, in chunks of rows of about
    CHUNK vertices. Every actor's own vertices: one that two streaming proxies share comes once for each."""
    for level in level_dirs:
        for grid, x0, y0, (loc, yaw, scale), _ in landscape.assemble(level, transpose=False).values():
            rows, cols = grid.shape
            c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
            per = max(1, CHUNK // cols)
            for first in range(0, rows, per):
                part = grid[first:first + per]
                gy, gx = np.mgrid[first:first + len(part), 0:cols]
                lx, ly = (gx + x0) * scale[0], (gy + y0) * scale[1]
                x = (loc[0] + c * lx - s * ly) / 100
                y = (loc[1] + s * lx + c * ly) / 100
                keep = (~np.isnan(part)) & (x >= bounds["min_x"]) & (x <= bounds["max_x"]) & (y >= bounds["min_y"]) & (y <= bounds["max_y"])
                yield x[keep], y[keep], ((loc[2] + scale[2] * part / 128) / 100)[keep]


def read_chunked(heights, grid, xs, ys):
    """Heights of ``heights`` on ``grid`` at world points with the page's rule, in chunks."""
    out = np.empty(len(xs))
    for first in range(0, len(xs), CHUNK):
        part = slice(first, first + CHUNK)
        out[part] = lattice.read(heights, grid, xs[part], ys[part])
    return out


def load_heightmap(directory):
    """(heights in metres [rows, cols], meta, step) of a built heightmap folder."""
    with open(os.path.join(directory, "meta.json")) as f:
        meta = json.load(f)
    if "webp" in meta and os.path.exists(os.path.join(directory, heightmap_webp.FILE)):
        levels, step = heightmap_webp.decode(os.path.join(directory, heightmap_webp.FILE)), meta["webp"]["z_step_m"]
    else:
        with Image.open(os.path.join(directory, "heightmap.png")) as image:
            levels, step = np.asarray(image), meta["z_step_m"]
    return levels.astype(np.float64) * step + meta["z_min_m"], meta, step


def summary(error):
    error = np.abs(error[~np.isnan(error)])
    return f"rms {np.sqrt((error ** 2).mean()) * 100:8.3f} cm  p99 {np.percentile(error, 99) * 100:8.3f} cm  max {error.max() * 100:9.2f} cm"


def built_terrain(actors, meta, xs, ys):
    """The terrain the build of a heightmap put at world points: the game's triangles on the landscape's vertices
    (meta.json with origin_m), the landscape read bilinearly at the samples of a heightmap built before them."""
    if "origin_m" in meta:
        return build_heightmap.landscape_at(actors, xs, ys)
    z = np.full(xs.shape, np.nan)
    for actor in actors:
        z = np.where(np.isnan(z), landscape.sample_world(actor, xs * 100, ys * 100, "bilinear") / 100, z)
    return z


def bare_mask(actors, built, xs, ys):
    """Bool per world point: the quad around it holds the bare landscape in every heightmap of ``built`` (load_heightmap
    results), its four nodes within half the heightmap's step of the terrain its build put there. In chunks."""
    bare = np.ones(xs.shape, bool)
    for heights, meta, step in built:
        grid = lattice.from_meta(meta)
        for first in range(0, len(xs), CHUNK):
            part = slice(first, first + CHUNK)
            cols, rows = lattice.to_grid(grid, xs[part], ys[part])
            c0 = np.clip(np.floor(cols), 0, grid.width - 2).astype(np.int64)
            r0 = np.clip(np.floor(rows), 0, grid.height - 2).astype(np.int64)
            for dc, dr in ((0, 0), (1, 0), (0, 1), (1, 1)):
                nx, ny = lattice.to_world(grid, (c0 + dc).astype(np.float64), (r0 + dr).astype(np.float64))
                bare[part] &= np.abs(heights[r0 + dr, c0 + dc] - built_terrain(actors, meta, nx, ny)) <= step / 2 + 1e-4
    return bare


def main(extract_root, slug, heightmap_dirs, points_out=None):
    level_dirs = [os.path.join(extract_root, "landscapes", level) for level in maps.MAPS[slug][1]]
    built = [load_heightmap(os.path.join(d, slug)) for d in heightmap_dirs]
    bounds = built[0][1]["bounds_m"]
    actors = build_heightmap.landscape_actors(level_dirs)
    rng = np.random.default_rng(3)
    keys = np.random.default_rng(4)

    # Per heightmap the errors (float32) at the vertices where every heightmap holds the bare landscape; for --points-out the
    # POINTS of them with the smallest random keys
    errors = [[] for _ in built]
    total = 0
    chosen = np.zeros((0, 4))
    for xs, ys, zs in vertex_chunks(level_dirs, bounds):
        total += len(xs)
        bare = bare_mask(actors, built, xs, ys)
        for k, (heights, meta, _) in enumerate(built):
            errors[k].append((read_chunked(heights, lattice.from_meta(meta), xs[bare], ys[bare]) - zs[bare]).astype(np.float32))
        candidates = np.concatenate([chosen, np.stack([keys.random(int(bare.sum())), xs[bare], ys[bare], zs[bare]], 1)])
        chosen = candidates[np.argsort(candidates[:, 0], kind="stable")[:POINTS]]
    errors = [np.concatenate(e) for e in errors]
    print(f"{slug}: {total} landscape vertices inside the bounds")

    rx = rng.uniform(bounds["min_x"], bounds["max_x"], CANDIDATES)
    ry = rng.uniform(bounds["min_y"], bounds["max_y"], CANDIDATES)
    rz = build_heightmap.landscape_at(actors, rx, ry)
    keep = ~np.isnan(rz) & bare_mask(actors, built, rx, ry)
    rx, ry, rz = rx[keep], ry[keep], rz[keep]
    for directory, (heights, meta, _), error in zip(heightmap_dirs, built, errors):
        grid = lattice.from_meta(meta)
        print(f"  {directory} ({meta['resolution_m']} m) {len(error)} vertices on terrain: {summary(error)}", flush=True)
        between = lattice.read(heights, grid, rx, ry) - rz
        print(f"  {directory} ({meta['resolution_m']} m) {len(rx)} points inside quads: {summary(between)}", flush=True)

    if points_out:
        between = rng.choice(len(rx), min(POINTS, len(rx)), replace=False)
        px, py, pz = (np.concatenate([chosen[:, k], w[between]]) for k, w in zip((1, 2, 3), (rx, ry, rz)))
        points = {}
        if os.path.exists(points_out):
            with open(points_out) as f:
                points = json.load(f)
        points[slug] = [[round(float(x), 4), round(float(y), 4), round(float(z), 5)] for x, y, z in zip(px, py, pz)]
        with open(points_out, "w") as f:
            json.dump(points, f)
        print(f"  {len(chosen)} vertices and {len(between)} points inside quads written to {points_out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("extract_root")
    parser.add_argument("slug")
    parser.add_argument("heightmap_dirs", nargs="+")
    parser.add_argument("--points-out")
    args = parser.parse_args()
    main(args.extract_root, args.slug, args.heightmap_dirs, args.points_out)
