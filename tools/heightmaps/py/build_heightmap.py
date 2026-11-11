"""Build a SquadCalc heightmap by fusing the game's landscape with SquadHeight's surface.

Sources, all in world space on the heightmap's grid: the nodes of the game's landscape vertices that cover the minimap bounds
(lattice.py; row and col along the landscape's own axes, which are world Y and X on every map but Skorpo, turned by -2.006 deg):
    terrain T: landscape collision heightfields from the game paks (landscape.py), exact for the installed game build: every
               node is a vertex of the landscape, so the page's triangle read is the game's collision on bare ground;
    surface S: SquadHeight's top-most trace of the Squad SDK collision (terrain + buildings, rocks, bridges), 1.6 cm steps,
               on a 1 m grid from the minimap's corner: each node takes the height above the terrain of the nearest
               SquadHeight sample on its own terrain (surface_on_lattice).

    objects O: top of the static meshes' collision from the game paks (objects.py), optional.

Fused height where the game has landscape: the highest of T, O, and S where S rises
OBJECT_MIN_M above T (an object the SDK has; below that S is open ground, or old terrain, and T
wins) and a placement of the game explains it (evidence.py: the SDK's map is not the installed
build's, and an object that only the SDK has is no height of the game). Where the game has no
landscape: the highest of S and O.

Output, in <out>/<map>/:
    heightmap.png  16-bit grayscale, height above the map's lowest point = value * z_step_m
    heightmap.webp the same levels as lossless WebP, see heightmap_webp.py
    meta.json      the grid (origin_m, resolution_m, yaw_deg, width, height: lattice.meta_entry), z_step_m, z_min_m, the
                   minimap bounds, the agreement statistics of the two sources, and the WebP's checksum ("webp") with the
                   build time ("generated": the page requests the files with ?v=<generated>, so a rebuild must change it)
"""

import argparse
import datetime
import json
import os

import numpy as np
from PIL import Image

import heightmap_webp
import landscape
import lattice

Image.MAX_IMAGE_PIXELS = None
OBJECT_MIN_M = 0.5
NEAR_M = 1.0


def load_squadheight(directory):
    meta = json.load(open(os.path.join(directory, "meta.json")))
    png = np.asarray(Image.open(os.path.join(directory, "heightmap.png"))).astype(np.float64)
    # Exports from SquadHeight 1.3 name the 16-bit scale png16_meters_per_unit, older ones png_meters_per_unit
    per_unit = meta.get("png16_meters_per_unit", meta.get("png_meters_per_unit"))
    return meta, png * per_unit + meta["z_offset_m"]


def squadheight_lattice(meta, surface):
    """The Lattice of SquadHeight's grid: a sample every resolution_m from the bounds' min corner, along world X and Y."""
    b = meta["bounds_m"]
    return lattice.Lattice(float(b["min_x"]), float(b["min_y"]), float(meta["resolution_m"]), 0.0, surface.shape[1], surface.shape[0])


def map_lattice(actors, bounds):
    """The heightmap's grid of a map: the lattice of its landscape actors over the minimap ``bounds``."""
    return lattice.covering(*lattice.landscape_lattice(actors), bounds)


def landscape_actors(level_dirs):
    """The landscape actors (landscape.assemble values) of a map's landscape levels, in the order of the levels."""
    return [actor for level in level_dirs for actor in landscape.assemble(level, transpose=False).values()]


def landscape_at(actors, xs, ys):
    """The game's landscape collision (m) at world points (m), NaN where no landscape covers them; the first actor
    covering a point wins. Read with the game's triangles (landscape.triangle_surface), exact at the vertices."""
    z = np.full(xs.shape, np.nan)
    for actor in actors:
        z = np.where(np.isnan(z), landscape.sample_world(actor, xs * 100, ys * 100, "triangle") / 100, z)
    return z


def game_terrain(actors, grid):
    """Terrain in metres (float32) at the nodes of the Lattice ``grid``, NaN where no landscape covers a node; on the map's
    own lattice every node is a landscape vertex. Sampled in strips of rows: a 4 km map at 0.5 m holds 66 million nodes, and
    float32 (0.1 mm at 1 km) keeps a map's arrays in a few GB."""
    terrain = np.empty((grid.height, grid.width), np.float32)
    for first, count in lattice.strips(grid):
        xs, ys = lattice.node_rows(grid, first, count)
        terrain[first:first + count] = landscape_at(actors, xs, ys)
    return terrain


def surface_on_lattice(surface, sh_meta, actors, grid, terrain):
    """SquadHeight's surface at the nodes of ``grid``, given the game's ``terrain`` at them.

    Where the landscape covers the node and the nearest SquadHeight sample, the node takes that sample's height above the
    game's terrain at the sample, on top of its own terrain: a building keeps its height above the ground, and the slope
    between a node and the sample does not turn into a bump (nearest-sample absolute heights would rise by up to the slope
    times half a SquadHeight cell). Nodes without landscape (or whose sample has none) read the SquadHeight grid the way
    the page reads a heightmap, along the game's triangles: there SquadHeight is the only ground, and a mountain side must
    not step. A node on a sample keeps it exactly; one halfway between two takes the one with the larger coordinate.
    Beyond the minimap (more than half a SquadHeight cell outside its grid: the grid's last nodes, and on Skorpo the corners
    of the turned lattice) SquadHeight has nothing: a node there is its own terrain, else the nearest edge of SquadHeight's grid.
    """
    sh = squadheight_lattice(sh_meta, surface)
    out = np.empty((grid.height, grid.width), np.float32)
    for first, count in lattice.strips(grid):
        xs, ys = lattice.node_rows(grid, first, count)
        cols, rows = lattice.to_grid(sh, xs, ys)
        beyond = (cols < -0.5) | (cols > sh.width - 0.5) | (rows < -0.5) | (rows > sh.height - 0.5)
        col = np.clip(np.floor(cols + 0.5).astype(np.int64), 0, sh.width - 1)
        row = np.clip(np.floor(rows + 0.5).astype(np.int64), 0, sh.height - 1)
        sx, sy = lattice.to_world(sh, col.astype(np.float64), row.astype(np.float64))
        above = np.where(beyond, 0.0, surface[row, col] - landscape_at(actors, sx, sy))
        own = terrain[first:first + count] + above
        edge_x, edge_y = lattice.to_world(sh, np.clip(cols, 0, sh.width - 1), np.clip(rows, 0, sh.height - 1))
        out[first:first + count] = np.where(np.isnan(own), lattice.read(surface, sh, edge_x, edge_y), own)
    return out


def above_terrain(terrain, surface):
    """Bool grid: the landscape covers the point and SquadHeight's surface rises OBJECT_MIN_M and more above it (an object of the SDK's map)."""
    with np.errstate(invalid="ignore"):
        return surface - terrain >= OBJECT_MIN_M


def fuse(terrain, surface, objects=None, explained=None, below=None):
    """Return (fused heights, statistics) of the sources; `objects` is -inf where no mesh stands.

    `explained`: bool grid of the points of above_terrain where a placement of the game holds SquadHeight's surface
    (evidence.explained). At the other points of above_terrain the surface is an object that only the SDK's map has, and the
    game's own surfaces stand: its terrain, its objects and `below`, the terrain or water of a vast client mesh under SquadHeight's
    surface there (evidence.surface_below, -inf where none). Without `explained` every point of above_terrain takes SquadHeight's
    surface.
    """
    diff = surface - terrain
    covered = ~np.isnan(terrain)
    sdk_objects = above_terrain(terrain, surface)
    unexplained = np.zeros(sdk_objects.shape, bool) if explained is None else sdk_objects & ~explained
    sdk_objects = sdk_objects & ~unexplained
    fused = np.where(covered, np.fmax(terrain, np.where(sdk_objects, surface, -np.inf)), surface)
    if below is not None:
        fused = np.fmax(fused, np.where(unexplained, below, -np.inf))
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
    if explained is not None:
        stats["sdk_unexplained_cells"] = int(unexplained.sum())
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


def write(out_dir, name, fused, grid, meta, stats, build):
    """Write heightmap.png, heightmap.webp (the same levels) and meta.json of ``fused`` [grid.height, grid.width]; ``meta`` is
    SquadHeight's (its bounds are the minimap's, the area the page covers)."""
    os.makedirs(out_dir, exist_ok=True)
    z_min = float(np.nanmin(fused))
    z_max = float(np.nanmax(fused))
    z_step = max((z_max - z_min) / 65535, 0.001)
    values = np.clip(np.rint((np.nan_to_num(fused, nan=z_min) - z_min) / z_step), 0, 65535).astype(np.uint16)
    Image.fromarray(values).save(os.path.join(out_dir, "heightmap.png"), optimize=True)
    webp_path = os.path.join(out_dir, heightmap_webp.FILE)
    heightmap_webp.encode(values, webp_path)
    entry = {
        "map": name,
        "format": heightmap_webp.FORMAT,
        "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "png": "heightmap.png: 16-bit grayscale PNG; height above z_min_m = value * z_step_m",
        "webp": heightmap_webp.meta_entry(values, z_step, webp_path),
        "z_step_m": z_step,
        "z_min_m": round(z_min, 4),
        "z_max_m": round(z_max, 4),
        **lattice.meta_entry(grid),
        "bounds_m": meta["bounds_m"],
        "orientation": "the landscape's vertices: node (col, row) at origin_m + col * resolution_m * (cos yaw, sin yaw) "
                       "+ row * resolution_m * (-sin yaw, cos yaw), yaw = yaw_deg, world X east, Y south",
        "sources": {
            "terrain": f"Squad dedicated server build {build}, landscape collision",
            "objects": f"Squad dedicated server build {build}, static mesh collision"
                       if "game_object_cells" in stats else None,
            "sdk_surface": f"SquadHeight {meta.get('exported_utc', '')} (Squad SDK collision trace)",
            "sdk_objects_kept": f"where a static mesh placement of the server build {build} or a mesh placement of the client scene, "
                                f"Squad client build {os.environ.get('CLIENT_BUILD', 'unknown')}, holds the surface"
                                if "sdk_unexplained_cells" in stats else None,
        },
        "object_min_m": OBJECT_MIN_M,
        "stats": stats,
    }
    with open(os.path.join(out_dir, "meta.json"), "w") as f:
        json.dump(entry, f, indent=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name")
    parser.add_argument("squadheight_dir")
    parser.add_argument("out_dir")
    parser.add_argument("build")
    parser.add_argument("levels", nargs="+", help="directories written by SquadExtract for the map's landscape levels")
    args = parser.parse_args()
    meta, surface = load_squadheight(args.squadheight_dir)
    actors = landscape_actors(args.levels)
    grid = map_lattice(actors, meta["bounds_m"])
    terrain = game_terrain(actors, grid)
    surface = surface_on_lattice(surface, meta, actors, grid, terrain)
    fused, stats = fuse(terrain, surface)
    write(args.out_dir, args.name, fused, grid, meta, stats, args.build)
    print(args.name, json.dumps(stats))


if __name__ == "__main__":
    main()
