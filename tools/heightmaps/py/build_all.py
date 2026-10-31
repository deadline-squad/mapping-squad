"""Build the fused heightmap of every map in maps.MAPS (see build_heightmap.py).

Usage: build_all.py <squadheight root> <extract root> <out root> <game build> [map ...]

<extract root>/landscapes holds the landscape levels and <extract root>/statics/<map> the static
meshes of each map (SquadExtract statics); a map without statics is fused without game objects.
A map is built on the grid of maps.cell_m(map) metres (1 m, or 0.5 m for Chora and Kokan): the game's terrain
and static meshes are sampled on that grid, SquadHeight's 1 m surface by nearest sample (height above the terrain).
"""

import json
import os
import sys

import build_heightmap
import objects
from maps import MAPS, cell_m


def main(squadheight_root, extract_root, out_root, build, *only):
    for slug, (squadheight_name, levels) in MAPS.items():
        if only and slug not in only:
            continue
        cell = cell_m(slug)
        meta, surface = build_heightmap.load_squadheight(os.path.join(squadheight_root, squadheight_name))
        shape = build_heightmap.grid_shape(meta, cell)
        terrain = build_heightmap.game_terrain([os.path.join(extract_root, "landscapes", level) for level in levels], meta, shape, cell)
        surface = build_heightmap.upsample_surface(surface, terrain, meta, cell)
        statics = os.path.join(extract_root, "statics", slug)
        top = None
        if os.path.exists(os.path.join(statics, "instances.ndjson")):
            top, object_stats = objects.object_surface(statics, meta["bounds_m"], cell, shape)
            print(slug, "meshes", json.dumps(object_stats), flush=True)
        fused, stats = build_heightmap.fuse(terrain, surface, top)
        build_heightmap.write(os.path.join(out_root, slug), squadheight_name, fused, meta, stats, build, cell)
        print(slug, json.dumps(stats), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
