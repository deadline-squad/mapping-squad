"""Build a SquadCalc heightmap by fusing the game's landscape with SquadHeight's surface.

Sources, all in world space on the heightmap's grid (minimap bounds, `cell` metres per sample, 1 m unless
maps.CELL_M says otherwise, row = world Y min->max, col = world X min->max, the same grid as SquadCalc's
heightmap.png; samples sit on the bounds' min corner and every `cell` from it, the max corner included):
    terrain T: landscape collision heightfields from the game paks (landscape.py), exact for
               the installed game build;
    surface S: SquadHeight's top-most trace of the Squad SDK collision (terrain + buildings,
               rocks, bridges), 1.6 cm steps, always on a 1 m grid: on a finer heightmap each cell
               takes the nearest SquadHeight sample's height above the terrain (upsample_surface).

    objects O: top of the static meshes' collision from the game paks (objects.py), optional.

Fused height where the game has landscape: the highest of T, O, and S where S rises
OBJECT_MIN_M above T (an object the SDK has; below that S is open ground, or old terrain, and T
wins). Where the game has no landscape: the highest of S and O.

Output, in <out>/<map>/:
    heightmap.png  16-bit grayscale, height above the map's lowest point = value * z_step_m
    heightmap.webp the same grid as lossless WebP at a coarser step, see heightmap_webp.py
    meta.json      z_step_m, z_min_m, grid, the agreement statistics of the two sources, and the
                   WebP's step and checksum ("webp") with the build time ("generated": the page
                   requests the files with ?v=<generated>, so a rebuild must change it)
"""

import argparse
import datetime
import json
import os

import numpy as np
from PIL import Image

import heightmap_webp
import landscape

Image.MAX_IMAGE_PIXELS = None
OBJECT_MIN_M = 0.5
NEAR_M = 1.0
STRIP_CELLS = 2_000_000


def load_squadheight(directory):
    meta = json.load(open(os.path.join(directory, "meta.json")))
    png = np.asarray(Image.open(os.path.join(directory, "heightmap.png"))).astype(np.float64)
    # Exports from SquadHeight 1.3 name the 16-bit scale png16_meters_per_unit, older ones png_meters_per_unit
    per_unit = meta.get("png16_meters_per_unit", meta.get("png_meters_per_unit"))
    return meta, png * per_unit + meta["z_offset_m"]


def grid_shape(meta, cell):
    """(rows, cols) of the grid of `cell` metres from the bounds' min corner to its max corner, both included."""
    b = meta["bounds_m"]
    return (round((b["max_y"] - b["min_y"]) / cell) + 1, round((b["max_x"] - b["min_x"]) / cell) + 1)


def upsample_surface(surface, terrain, meta, cell):
    """SquadHeight's surface on the grid of `cell` metres, given the game's `terrain` on that grid.

    Where the landscape covers the cell, each cell takes the height above the terrain (surface - terrain at the
    SquadHeight sample) of the nearest SquadHeight sample, on top of its own terrain: a building keeps its height
    above the ground, and the slope between two samples does not turn into a bump (nearest-sample absolute heights
    would rise by up to the slope times half a SquadHeight cell). Cells without landscape (or whose sample has
    none) read the SquadHeight grid the way the page reads a 1 m heightmap, along the game's triangles
    (landscape.triangle_surface): there SquadHeight is the only ground, and a mountain side must not step.
    A cell on a SquadHeight sample keeps it exactly; one halfway between two takes the one with the larger
    coordinate in the first case. `cell` must divide SquadHeight's resolution.
    """
    ratio = round(meta["resolution_m"] / cell)
    if abs(ratio * cell - meta["resolution_m"]) > 1e-9:
        raise ValueError(f"cell {cell} m does not divide SquadHeight's {meta['resolution_m']} m")
    if ratio == 1:
        return surface
    nearest = lambda count, size: np.minimum((np.arange(count) + ratio // 2) // ratio, size - 1)
    rows, cols = np.ix_(nearest(terrain.shape[0], surface.shape[0]), nearest(terrain.shape[1], surface.shape[1]))
    above = (surface - terrain[::ratio, ::ratio])[rows, cols]
    fused = np.where(np.isnan(terrain) | np.isnan(above), np.nan, terrain + above)
    cols_at = np.arange(terrain.shape[1]) / ratio
    rows_per_strip = max(1, STRIP_CELLS // terrain.shape[1])
    for first in range(0, terrain.shape[0], rows_per_strip):
        strip = fused[first:first + rows_per_strip]
        gx, gy = np.meshgrid(cols_at, np.arange(first, first + strip.shape[0]) / ratio)
        strip[:] = np.where(np.isnan(strip), landscape.triangle_surface(surface, gx, gy), strip)
    return fused


def game_terrain(level_dirs, meta, shape, cell=None):
    """Terrain in metres on the grid of `cell` metres (SquadHeight's by default), NaN where no landscape covers a cell.

    Sampled in strips of rows: a 0.5 m grid of a 4 km map holds 66 million cells.
    """
    b = meta["bounds_m"]
    step = cell or meta["resolution_m"]
    xs = (b["min_x"] + np.arange(shape[1]) * step) * 100
    ys = (b["min_y"] + np.arange(shape[0]) * step) * 100
    terrain = np.full(shape, np.nan)
    actors = [actor for level in level_dirs for actor in landscape.assemble(level, transpose=False).values()]
    rows_per_strip = max(1, STRIP_CELLS // shape[1])
    for first in range(0, shape[0], rows_per_strip):
        gx, gy = np.meshgrid(xs, ys[first:first + rows_per_strip])
        strip = terrain[first:first + rows_per_strip]
        for actor in actors:
            z = landscape.sample_world(actor, gx, gy) / 100
            strip[:] = np.where(np.isnan(strip), z, strip)
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


def write(out_dir, name, fused, meta, stats, build, cell=None, sources=None, provenance=None):
    """Write heightmap.png, heightmap.webp and meta.json of a map.

    `sources` replaces the game-package sources of meta.json and `provenance` adds a free-text label of where the
    heights come from (both for a map not built from the server package, see build_squadheight_only.py).
    """
    os.makedirs(out_dir, exist_ok=True)
    z_min = float(np.nanmin(fused))
    z_max = float(np.nanmax(fused))
    z_step = max((z_max - z_min) / 65535, 0.001)
    values = np.clip(np.rint((np.nan_to_num(fused, nan=z_min) - z_min) / z_step), 0, 65535).astype(np.uint16)
    Image.fromarray(values).save(os.path.join(out_dir, "heightmap.png"), optimize=True)
    webp_step = heightmap_webp.step_for(name, z_step)
    webp_values = np.clip(np.rint((np.nan_to_num(fused, nan=z_min) - z_min) / webp_step), 0, 65535).astype(np.uint16)
    webp_path = os.path.join(out_dir, heightmap_webp.FILE)
    heightmap_webp.encode(webp_values, webp_path)
    json.dump({
        "map": name,
        "format": heightmap_webp.FORMAT,
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "png": "heightmap.png: 16-bit grayscale PNG; height above z_min_m = value * z_step_m",
        "webp": heightmap_webp.meta_entry(webp_values, webp_step, webp_path),
        "z_step_m": z_step,
        "z_min_m": round(z_min, 4),
        "z_max_m": round(z_max, 4),
        "width": int(values.shape[1]),
        "height": int(values.shape[0]),
        "resolution_m": cell or meta["resolution_m"],
        "bounds_m": meta["bounds_m"],
        "orientation": "row = world Y min->max, col = world X min->max",
        "sources": sources or {
            "terrain": f"Squad dedicated server build {build}, landscape collision",
            "objects": f"Squad dedicated server build {build}, static mesh collision"
                       if "game_object_cells" in stats else None,
            "sdk_surface": f"SquadHeight {meta.get('exported_utc', '')} (Squad SDK collision trace)",
        },
        **({"provenance": provenance} if provenance else {"object_min_m": OBJECT_MIN_M}),
        "stats": stats,
    }, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name")
    parser.add_argument("squadheight_dir")
    parser.add_argument("out_dir")
    parser.add_argument("build")
    parser.add_argument("--cell", type=float, help="heightmap cell size in metres (SquadHeight's resolution by default)")
    parser.add_argument("levels", nargs="+", help="directories written by SquadExtract for the map's landscape levels")
    args = parser.parse_args()
    meta, surface = load_squadheight(args.squadheight_dir)
    cell = args.cell or meta["resolution_m"]
    terrain = game_terrain(args.levels, meta, grid_shape(meta, cell), cell)
    surface = upsample_surface(surface, terrain, meta, cell)
    fused, stats = fuse(terrain, surface)
    write(args.out_dir, args.name, fused, meta, stats, args.build, cell)
    print(args.name, json.dumps(stats))


if __name__ == "__main__":
    main()
