"""What a finer grid changes: terrain + static objects of a map window at 1 m, 0.5 m and 0.25 m.

Usage: compare_resolution.py <extract root> <map> <min_x> <min_y> <size> <out dir> [points]

The window is `size` metres square from the world point (min_x, min_y) in metres. For each grid step the
landscape (the game's triangle surface) and the static meshes' collision (objects.py) are fused with max
into one heightmap of the window, as the pipeline does without the SDK surface. The 0.25 m grid is the
reference: errors of the coarser grids are read with the triangle rule at random points of the window and
split by where the point is: on terrain, on an object (>= 0.5 m above the landscape), or within 2 m of an object.
Each grid is also written to <out dir> as grid_<step>.u16 (little-endian levels above one common z_min, row = world Y) with
grid_<step>.json (width, height, step, z_min, z_step) for the line-of-sight comparison (los_resolution.mjs).
"""

import json
import os
import sys

import numpy as np
from scipy.ndimage import distance_transform_edt

import compare_interpolation
import landscape
import maps
import objects

STEPS = (1.0, 0.5, 0.25)
Z_STEP = 0.002


def fused_grid(actors, statics, bounds, step):
    """Terrain and objects of the window fused: (fused heights, terrain heights), float32 [rows, cols]."""
    terrain = compare_interpolation.grid_nodes(actors, bounds, step, "triangle")
    top, _ = objects.object_surface(statics, bounds, step, terrain.shape)
    return np.fmax(terrain, top.astype(np.float32)), terrain


def main(extract_root, slug, min_x, min_y, size, out_dir, points="500000"):
    min_x, min_y, size = float(min_x), float(min_y), float(size)
    bounds = {"min_x": min_x, "min_y": min_y, "max_x": min_x + size, "max_y": min_y + size}
    actors = []
    for level in maps.MAPS[slug][1]:
        actors += list(landscape.assemble(os.path.join(extract_root, "landscapes", level), transpose=False).values())
    statics = os.path.join(extract_root, "statics", slug)
    os.makedirs(out_dir, exist_ok=True)
    grids = {}
    for step in STEPS:
        grids[step], terrain = fused_grid(actors, statics, bounds, step)
    reference_terrain = terrain
    z_min = float(min(np.nanmin(grid) for grid in grids.values()))
    for step, grid in grids.items():
        levels = np.rint((np.nan_to_num(grid, nan=z_min) - z_min) / Z_STEP).astype("<u2")
        levels.tofile(os.path.join(out_dir, f"grid_{step}.u16"))
        json.dump({"width": levels.shape[1], "height": levels.shape[0], "step": step, "z_min": z_min, "z_step": Z_STEP},
                  open(os.path.join(out_dir, f"grid_{step}.json"), "w"))
    rng = np.random.default_rng(2)
    xs = rng.uniform(min_x + 1, min_x + size - 1, int(points))
    ys = rng.uniform(min_y + 1, min_y + size - 1, int(points))
    truth = compare_interpolation.read(grids[0.25], bounds, 0.25, xs, ys, "triangle")
    ground = compare_interpolation.read(reference_terrain, bounds, 0.25, xs, ys, "triangle")
    on_object = truth - ground >= 0.5
    objects_mask = (grids[0.25] - reference_terrain) >= 0.5
    gap = distance_transform_edt(~objects_mask) * 0.25
    near = ~on_object & (compare_interpolation.read(gap, bounds, 0.25, xs, ys, "nearest") <= 2.0)
    parts = {"all": np.ones_like(on_object), "terrain": ~on_object & ~near, "within 2 m of an object": near, "on an object": on_object}
    print(f"{slug} window {size:.0f} m at ({min_x:.0f}, {min_y:.0f}): {on_object.mean():.1%} of the area is object, {near.mean():.1%} within 2 m of one")
    for step in STEPS[:-1]:
        for mode in ("bilinear", "triangle"):
            error = compare_interpolation.read(grids[step], bounds, step, xs, ys, mode) - truth
            for name, mask in parts.items():
                shown = np.abs(error[mask])
                print(f"  step {step} m {mode:8s} {name:24s} rms {np.sqrt((shown ** 2).mean()):7.3f}  p99 {np.percentile(shown, 99):7.3f}  "
                      f"max {shown.max():7.3f}  share > 0.25 m {np.mean(shown > 0.25):.3%}")


if __name__ == "__main__":
    main(*sys.argv[1:])
