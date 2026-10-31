"""Build the sparse voxel columns of one map from world triangles (world_tris.py) and the landscape.

    python build_columns.py <tris.npz> <heightmap meta.json> <out prefix> <cell m> <dz m> <channel> [slug]

slug (default fallujah) picks the landscape levels from tools/heightmaps/py/maps.py under /data/squad-extract/landscapes.

channel is visibility, projectile or pawn (collision.py). Voxels that lie entirely at or below the landscape
(+ LAND_MARGIN_M) are dropped: the terrain layer already blocks there.
Writes <out>.npz with sorted int64 arrays ``occupied``, ``up``, ``down`` and the grid parameters.
"""

import json
import sys

import numpy as np

import collision
import columns
import maps
import terrain

LAND_MARGIN_M = 0.1
LANDSCAPE_ROOT = "/data/squad-extract/landscapes"


def load_terrain(level_dirs):
    return [(g, h, x0, y0, root) for level in level_dirs for g, h, x0, y0, root in terrain.assemble(level).values()]


def triangle_chunks(path, channel_bit, chunk=2_000_000):
    data = np.load(path)
    mask = data["mask"]
    tris = data["tris"]
    for start in range(0, len(tris), chunk):
        sel = (mask[start:start + chunk] & channel_bit) != 0
        yield tris[start:start + chunk][sel]


def main():
    tris_path, meta_path, out, cell, dz, channel = sys.argv[1:7]
    slug = sys.argv[7] if len(sys.argv) > 7 else "fallujah"
    cell, dz = float(cell), float(dz)
    meta = json.load(open(meta_path))
    b = meta["bounds_m"]
    grid = columns.Grid(b["min_x"], b["min_y"], b["max_x"] - b["min_x"], b["max_y"] - b["min_y"], cell, dz, -60.0)
    occupied, up, down = columns.build_keys(triangle_chunks(tris_path, collision.CHANNELS[channel.capitalize()]), grid)
    print("voxels before ground filter", len(occupied), "up", len(up), "down", len(down), flush=True)
    actors = load_terrain([f"{LANDSCAPE_ROOT}/{level}" for level in maps.MAPS[slug][1]])

    def above_ground(keys):
        x, y, z = grid.voxel_center(keys)
        ground, hole = terrain.sample(actors, x, y)
        top = z + grid.dz / 2
        return np.isnan(ground) | hole | (top > ground + LAND_MARGIN_M)

    keep = np.concatenate([above_ground(occupied[i:i + 5_000_000]) for i in range(0, len(occupied), 5_000_000)])
    occupied = occupied[keep]
    up = up[np.isin(up, occupied)]
    down = down[np.isin(down, occupied)]
    print("voxels", len(occupied), "up", len(up), "down", len(down))
    np.savez(out, occupied=occupied, up=up, down=down, min_x=grid.min_x, min_y=grid.min_y, cell=cell, dz=dz,
             z_min=grid.z_min, width=grid.width, height=grid.height)


if __name__ == "__main__":
    main()
