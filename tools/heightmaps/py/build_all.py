"""Build the fused heightmap of every map in maps.MAPS (see build_heightmap.py).

Usage: build_all.py <squadheight root> <extract root> <out root> <game build> [map ...]

<extract root>/landscapes holds the landscape levels and <extract root>/statics/<map> the static
meshes of each map (SquadExtract statics); a map without statics is fused without game objects.
"""

import json
import os
import sys

import build_heightmap
import objects
from maps import MAPS


def main(squadheight_root, extract_root, out_root, build, *only):
    for slug, (squadheight_name, levels) in MAPS.items():
        if only and slug not in only:
            continue
        meta, surface = build_heightmap.load_squadheight(os.path.join(squadheight_root, squadheight_name))
        terrain = build_heightmap.game_terrain([os.path.join(extract_root, "landscapes", level) for level in levels], meta, surface.shape)
        statics = os.path.join(extract_root, "statics", slug)
        top = None
        if os.path.exists(os.path.join(statics, "instances.ndjson")):
            top, object_stats = objects.object_surface(statics, meta["bounds_m"], meta["resolution_m"], surface.shape)
            print(slug, "meshes", json.dumps(object_stats), flush=True)
        fused, stats = build_heightmap.fuse(terrain, surface, top)
        build_heightmap.write(os.path.join(out_root, slug), squadheight_name, fused, meta, stats, build)
        print(slug, json.dumps(stats), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
