"""Build the fused heightmap of every map in maps.MAPS (see build_heightmap.py).

Usage: build_all.py <squadheight root> <extract root> <scene root> <out root> <game build> [map ...]

<extract root>/landscapes holds the landscape levels and <extract root>/statics/<map> the static
meshes of each map (SquadExtract statics); a map without statics is fused without game objects.
<scene root>/<map> is the map's client scene (SquadExtract scene, tools/maprender): with it and the statics, SquadHeight's
surface above the terrain is taken only where a placement of the game explains it (evidence.py); a map without a scene keeps
every object of SquadHeight, and the line printed for it says so.
A map is built on the nodes of its landscape's vertices (lattice.py, build_heightmap.map_lattice): the game's terrain is
the vertices themselves, the static meshes are sampled at the nodes, SquadHeight's 1 m surface by nearest sample (height above
the terrain).
"""

import json
import os
import sys

import numpy as np

import build_heightmap
import evidence
import objects
from maps import MAPS


def fuse_on(label, grid, sh_meta, sh_surface, actors, statics, scene):
    """(fused heights float32 [grid.height, grid.width], stats) of a map at the nodes of ``grid`` (lattice.Lattice): its
    landscape ``actors`` (build_heightmap.landscape_actors), SquadHeight's surface (``sh_meta``, ``sh_surface`` of
    build_heightmap.load_squadheight), the static meshes of ``statics`` and the client scene ``scene``, as the module
    description says. The meshes' statistics are printed under ``label``."""
    terrain = build_heightmap.game_terrain(actors, grid)
    surface = build_heightmap.surface_on_lattice(sh_surface, sh_meta, actors, grid, terrain)
    top = explained = below = None
    if os.path.exists(os.path.join(statics, "instances.ndjson")):
        top, object_stats = objects.object_surface(statics, grid)
        print(label, "meshes", json.dumps(object_stats), flush=True)
        if os.path.exists(os.path.join(scene, "instances.ndjson")):
            boxes, surfaces = evidence.scene_placements(scene)
            boxes = np.concatenate([evidence.collision_boxes(statics), boxes])
            rising = build_heightmap.above_terrain(terrain, surface)
            explained = evidence.explained(surface, rising, boxes, grid, surfaces)
            below = evidence.surface_below(surface, rising & ~explained, surfaces, grid)
            del boxes, surfaces, rising
        else:
            print(label, "no client scene: every object of SquadHeight is kept", flush=True)
    return build_heightmap.fuse(terrain, surface, top, explained, below)


def sources(squadheight_root, extract_root, scene_root, slug):
    """(SquadHeight's meta, SquadHeight's surface, landscape actors, statics directory, scene directory) of a map."""
    squadheight_name, levels = MAPS[slug]
    meta, surface = build_heightmap.load_squadheight(os.path.join(squadheight_root, squadheight_name))
    actors = build_heightmap.landscape_actors([os.path.join(extract_root, "landscapes", level) for level in levels])
    return meta, surface, actors, os.path.join(extract_root, "statics", slug), os.path.join(scene_root, slug)


def main(squadheight_root, extract_root, scene_root, out_root, build, *only):
    for slug, (squadheight_name, _) in MAPS.items():
        if only and slug not in only:
            continue
        meta, surface, actors, statics, scene = sources(squadheight_root, extract_root, scene_root, slug)
        grid = build_heightmap.map_lattice(actors, meta["bounds_m"])
        fused, stats = fuse_on(slug, grid, meta, surface, actors, statics, scene)
        del surface, actors  # the WebP encoder peaks at 2.8 GB on a 4 km map at 0.5 m
        build_heightmap.write(os.path.join(out_root, slug), squadheight_name, fused, grid, meta, stats, build)
        print(slug, json.dumps(stats), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
