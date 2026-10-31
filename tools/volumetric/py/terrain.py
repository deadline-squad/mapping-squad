"""Game landscape collision with its holes, sampled at world points.

Heights come from tools/heightmaps/py/landscape.py (cooked Chaos heightfield, 1 m quads). The same cooked
blob carries, after the heights, a per-quad uint8 material index array (``int32 count`` + ``count`` bytes,
count = quads^2). Index 0xFF marks a quad the landscape visibility mask cut out: a hole in the collision
(tunnel mouths, building basements, culverts). ``build_heightmap.game_terrain`` ignores them.
"""

import glob
import json
import math
import os
import struct

import numpy as np

import landscape

HOLE = 0xFF


def read_material_indices(path):
    """uint8 [quads, quads] per-quad material indices of one cooked heightfield (rows follow the heights)."""
    data = open(path, "rb").read()
    count = struct.unpack_from("<i", data, landscape.HEIGHTS_OFFSET)[0]
    tail = landscape.HEIGHTS_OFFSET + 4 + 2 * count
    quads = int(round(math.sqrt(count))) - 1
    stored = struct.unpack_from("<i", data, tail + 48)[0]
    if stored != quads * quads:
        raise ValueError(f"{path}: material count {stored} != {quads}^2")
    return np.frombuffer(data, np.uint8, stored, tail + 52).reshape(quads, quads)


def assemble(directory):
    """{actor: (heights [gy, gx] raw with NaN gaps, holes [gy-1, gx-1] bool, x0, y0, root)} of one landscape level."""
    result = landscape.assemble(directory, transpose=False)
    out = {}
    for actor, (grid, x0, y0, root, _) in result.items():
        holes = np.zeros((grid.shape[0] - 1, grid.shape[1] - 1), bool)
        for path in glob.glob(os.path.join(directory, "LandscapeHeightfieldCollisionComponent_*.json")):
            export = json.load(open(path))
            if export["Outer"]["ObjectName"].split(".")[-1].rstrip("'") != actor:
                continue
            location = export["Properties"].get("RelativeLocation", {})
            bx, by = int(round(location.get("X", 0))), int(round(location.get("Y", 0)))
            mats = read_material_indices(path[:-5] + ".bin")
            holes[by - y0:by - y0 + mats.shape[0], bx - x0:bx - x0 + mats.shape[1]] |= mats == HOLE
        out[actor] = (grid, holes, x0, y0, root)
    return out


def sample(actors, xs_m, ys_m):
    """World Z in metres and a hole flag at world points (arrays in metres); Z is NaN outside the landscape.

    Z is bilinear over the heightfield (also across holes, so the surface a hole would have had is known).
    """
    z = np.full(xs_m.shape, np.nan)
    hole = np.zeros(xs_m.shape, bool)
    for grid, holes, x0, y0, (loc, yaw, scale) in actors:
        dx, dy = xs_m * 100 - loc[0], ys_m * 100 - loc[1]
        c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        gx = (c * dx + s * dy) / scale[0] - x0
        gy = (-s * dx + c * dy) / scale[1] - y0
        zi = landscape.sample_world((grid, x0, y0, (loc, yaw, scale), 0), xs_m * 100, ys_m * 100) / 100
        inside = ~np.isnan(zi) & np.isnan(z)
        qx = np.clip(np.floor(gx).astype(int), 0, holes.shape[1] - 1)
        qy = np.clip(np.floor(gy).astype(int), 0, holes.shape[0] - 1)
        z = np.where(inside, zi, z)
        hole = np.where(inside, holes[qy, qx], hole)
    return z, hole
