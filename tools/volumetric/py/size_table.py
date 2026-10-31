"""Encoded size of coarser variants derived from a built voxel set, and a per-map estimate.

    python size_table.py <cols.npz> <heightmaps dir> <map slug>

Coarsening merges voxels (x, y by `fx`, z by `fz`), exactly what a coarser build would produce. The per-map
estimate scales the encoded bytes per game-object cell of the measured map by every map's ``game_object_cells``
(meta.json of the served heightmaps).
"""

import glob
import json
import os
import sys

import numpy as np

import codec
import columns


def coarsen(occupied, grid, fx, fz):
    mask = (1 << columns.Z_BITS) - 1
    column, z = occupied >> columns.Z_BITS, occupied & mask
    col, row = column % grid.width, column // grid.width
    width = -(-grid.width // fx)
    keys = np.unique((((row // fx) * width + col // fx) << columns.Z_BITS) | (z // fz))
    g = columns.Grid(grid.min_x, grid.min_y, grid.width * grid.cell, grid.height * grid.cell, grid.cell * fx, grid.dz * fz, grid.z_min)
    return keys, g


def main():
    cols_path, hm_dir, slug = sys.argv[1:4]
    d = np.load(cols_path)
    grid = columns.Grid(float(d["min_x"]), float(d["min_y"]), int(d["width"]) * float(d["cell"]), int(d["height"]) * float(d["cell"]), float(d["cell"]), float(d["dz"]), float(d["z_min"]))
    table = []
    for fx, fz in ((1, 1), (1, 2), (2, 1), (2, 2), (4, 2)):
        keys, g = coarsen(d["occupied"], grid, fx, fz)
        blob = codec.encode(keys, g)
        table.append(dict(cell=g.cell, dz=g.dz, voxels=int(len(keys)), gzip_MB=round(len(blob) / 1e6, 2)))
    up_blob = codec.encode(d["up"], grid)
    table.append(dict(cell=grid.cell, dz=grid.dz, kind="floors only (up-facing voxels)", voxels=int(len(d["up"])), gzip_MB=round(len(up_blob) / 1e6, 2)))
    meta = json.load(open(os.path.join(hm_dir, slug, "meta.json")))
    per_cell = table[0]["gzip_MB"] / meta["stats"]["game_object_cells"]
    estimate = {}
    for path in sorted(glob.glob(os.path.join(hm_dir, "*", "meta.json"))):
        m = json.load(open(path))
        cells = m["stats"].get("game_object_cells")
        if cells:
            estimate[os.path.basename(os.path.dirname(path))] = round(cells * per_cell, 2)
    print(json.dumps(dict(variants=table, estimate_MB_per_map_at_1m_025=estimate), indent=1))


if __name__ == "__main__":
    main()
