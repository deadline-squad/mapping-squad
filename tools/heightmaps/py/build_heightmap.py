"""Build a SquadCalc heightmap by fusing the game's landscape with SquadHeight's surface.

Sources, all in world space on SquadHeight's grid (minimap bounds, 1 m, row = world Y min->max,
col = world X min->max, the same grid as SquadCalc's heightmap.png):
    terrain T: landscape collision heightfields from the game paks (landscape.py), exact for
               the installed game build;
    surface S: SquadHeight's top-most trace of the Squad SDK collision (terrain + buildings,
               rocks, bridges), 1.6 cm steps.

    objects O: top of the static meshes' collision from the game paks (objects.py), optional.

Fused height where the game has landscape: the highest of T, O, and S where S rises
OBJECT_MIN_M above T (an object the SDK has; below that S is open ground, or old terrain, and T
wins). Where the game has no landscape: the highest of S and O.

Output, in <out>/<map>/:
    heightmap.png  16-bit grayscale, height above the map's lowest point = value * z_step_m
    meta.json      z_step_m, z_min_m, grid and the agreement statistics of the two sources
"""

import argparse
import json
import os

import numpy as np
from PIL import Image

import landscape

Image.MAX_IMAGE_PIXELS = None
OBJECT_MIN_M = 0.5
NEAR_M = 1.0


def load_squadheight(directory):
    meta = json.load(open(os.path.join(directory, "meta.json")))
    png = np.asarray(Image.open(os.path.join(directory, "heightmap.png"))).astype(np.float64)
    # Exports from SquadHeight 1.3 name the 16-bit scale png16_meters_per_unit, older ones png_meters_per_unit
    per_unit = meta.get("png16_meters_per_unit", meta.get("png_meters_per_unit"))
    return meta, png * per_unit + meta["z_offset_m"]


def game_terrain(level_dirs, meta, shape):
    """Terrain in metres on the SquadHeight grid, NaN where no landscape covers a cell."""
    b = meta["bounds_m"]
    step = meta["resolution_m"]
    xs = (b["min_x"] + np.arange(shape[1]) * step) * 100
    ys = (b["min_y"] + np.arange(shape[0]) * step) * 100
    gx, gy = np.meshgrid(xs, ys)
    terrain = np.full(shape, np.nan)
    for level in level_dirs:
        for actor in landscape.assemble(level, transpose=False).values():
            z = landscape.sample_world(actor, gx, gy) / 100
            terrain = np.where(np.isnan(terrain), z, terrain)
    return terrain


def fuse(terrain, surface, objects=None):
    """Return (fused heights, statistics) of the sources; `objects` is -inf where no mesh stands."""
    diff = surface - terrain
    covered = ~np.isnan(terrain)
    sdk_objects = covered & (diff >= OBJECT_MIN_M)
    fused = np.where(covered, np.fmax(terrain, np.where(sdk_objects, surface, -np.inf)), surface)
    d = diff[covered]
    near = np.abs(d) < NEAR_M
    stats = {
        "landscape_coverage": round(float(covered.mean()), 4),
        "terrain_agreement_within_1m": round(float(near.mean()), 4) if d.size else None,
        "terrain_median_diff_m": round(float(np.median(d[near])), 4) if near.any() else None,
        "terrain_rms_diff_m": round(float(np.sqrt((d[near] ** 2).mean())), 4) if near.any() else None,
        "sdk_object_cells": int(sdk_objects.sum()),
        "terrain_above_sdk_cells": int((covered & (diff <= -OBJECT_MIN_M)).sum()),
    }
    if objects is not None:
        ground = np.where(covered, terrain, surface)
        game_objects = objects - ground >= OBJECT_MIN_M
        fused = np.fmax(fused, objects)
        both = game_objects & sdk_objects
        stats.update({
            "game_object_cells": int(game_objects.sum()),
            "game_only_object_cells": int((game_objects & ~sdk_objects).sum()),
            "sdk_only_object_cells": int((sdk_objects & ~game_objects).sum()),
            "objects_agree_within_0_5m": round(float((np.abs(objects - surface)[both] < 0.5).mean()), 4) if both.any() else None,
        })
    return fused, stats


def write(out_dir, name, fused, meta, stats, build):
    os.makedirs(out_dir, exist_ok=True)
    z_min = float(np.nanmin(fused))
    z_max = float(np.nanmax(fused))
    z_step = max((z_max - z_min) / 65535, 0.001)
    values = np.clip(np.rint((np.nan_to_num(fused, nan=z_min) - z_min) / z_step), 0, 65535).astype(np.uint16)
    Image.fromarray(values).save(os.path.join(out_dir, "heightmap.png"), optimize=True)
    json.dump({
        "map": name,
        "format": "16-bit grayscale PNG; height above z_min_m = value * z_step_m",
        "z_step_m": z_step,
        "z_min_m": round(z_min, 4),
        "z_max_m": round(z_max, 4),
        "width": int(values.shape[1]),
        "height": int(values.shape[0]),
        "resolution_m": meta["resolution_m"],
        "bounds_m": meta["bounds_m"],
        "orientation": "row = world Y min->max, col = world X min->max",
        "sources": {
            "terrain": f"Squad dedicated server build {build}, landscape collision",
            "objects": f"SquadHeight {meta.get('exported_utc', '')} (Squad SDK collision trace)",
        },
        "object_min_m": OBJECT_MIN_M,
        "stats": stats,
    }, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name")
    parser.add_argument("squadheight_dir")
    parser.add_argument("out_dir")
    parser.add_argument("build")
    parser.add_argument("levels", nargs="+", help="directories written by SquadExtract for the map's landscape levels")
    args = parser.parse_args()
    meta, surface = load_squadheight(args.squadheight_dir)
    terrain = game_terrain(args.levels, meta, surface.shape)
    fused, stats = fuse(terrain, surface)
    write(args.out_dir, args.name, fused, meta, stats, args.build)
    print(args.name, json.dumps(stats))


if __name__ == "__main__":
    main()
