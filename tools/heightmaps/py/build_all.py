"""Build the fused heightmap of every map in maps.MAPS (see build_heightmap.py).

Usage: build_all.py <squadheight root> <extract root> <scene root> <out root> <game build> [map ...]

<extract root>/landscapes holds the landscape levels and <extract root>/statics/<map> the static
meshes of each map (SquadExtract statics); a map without statics is fused without game objects.
<scene root>/<map> is the map's client scene (SquadExtract scene, tools/maprender): with it and the statics, SquadHeight's
surface above the terrain is taken only where a placement of the game explains it (evidence.py); a map without a scene keeps
every object of SquadHeight, and the line printed for it says so.
A map is built on the grid of maps.cell_m(map) metres (1 m, or 0.5 m for Chora and Kokan): the game's terrain
and static meshes are sampled on that grid, SquadHeight's 1 m surface by nearest sample (height above the terrain).
"""

import json
import os
import sys

import numpy as np

import build_heightmap
import evidence
import objects
from maps import MAPS, cell_m


def main(squadheight_root, extract_root, scene_root, out_root, build, *only):
    for slug, (squadheight_name, levels) in MAPS.items():
        if only and slug not in only:
            continue
        cell = cell_m(slug)
        meta, surface = build_heightmap.load_squadheight(os.path.join(squadheight_root, squadheight_name))
        shape = build_heightmap.grid_shape(meta, cell)
        terrain = build_heightmap.game_terrain([os.path.join(extract_root, "landscapes", level) for level in levels], meta, shape, cell)
        surface = build_heightmap.upsample_surface(surface, terrain, meta, cell)
        statics = os.path.join(extract_root, "statics", slug)
        scene = os.path.join(scene_root, slug)
        top = explained = below = None
        if os.path.exists(os.path.join(statics, "instances.ndjson")):
            top, object_stats = objects.object_surface(statics, meta["bounds_m"], cell, shape)
            print(slug, "meshes", json.dumps(object_stats), flush=True)
            if os.path.exists(os.path.join(scene, "instances.ndjson")):
                boxes, surfaces = evidence.scene_placements(scene)
                boxes = np.concatenate([evidence.collision_boxes(statics), boxes])
                rising = build_heightmap.above_terrain(terrain, surface)
                explained = evidence.explained(surface, rising, boxes, meta["bounds_m"], cell, surfaces)
                below = evidence.surface_below(surface, rising & ~explained, surfaces, meta["bounds_m"], cell)
            else:
                print(slug, "no client scene: every object of SquadHeight is kept", flush=True)
        fused, stats = build_heightmap.fuse(terrain, surface, top, explained, below)
        build_heightmap.write(os.path.join(out_root, slug), squadheight_name, fused, meta, stats, build, cell)
        print(slug, json.dumps(stats), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
