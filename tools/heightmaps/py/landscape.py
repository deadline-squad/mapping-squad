"""Assemble a Squad landscape from its cooked collision heightfields.

Input is a directory written by ``SquadExtract landscape``: per collision component a
``<name>.json`` (UE properties) and ``<name>.bin`` (cooked Chaos heightfield), plus
``root_<actor>.json`` with the transform of each landscape actor.

Cooked Chaos heightfield layout (Squad, UE 5.7, verified on Skorpo):
    30 bytes header, int32 count, uint16 heights[count],
    float scale[3], double min, double max, uint16 rows, uint16 cols,
    double range, double height_per_unit, ...
A vertex's landscape raw height (signed, 1/128 local units) is min + heights[i] * height_per_unit.
"""

import glob
import json
import math
import os
import struct

import numpy as np

HEIGHTS_OFFSET = 30


def read_heightfield(path):
    """Return (rows, cols, raw heights as float64 [rows, cols]) of one cooked heightfield."""
    data = open(path, "rb").read()
    count = struct.unpack_from("<i", data, HEIGHTS_OFFSET)[0]
    start = HEIGHTS_OFFSET + 4
    heights = np.frombuffer(data, "<u2", count, start).astype(np.float64)
    tail = start + 2 * count
    minimum = struct.unpack_from("<d", data, tail + 12)[0]
    rows, cols = struct.unpack_from("<HH", data, tail + 28)
    per_unit = struct.unpack_from("<d", data, tail + 40)[0]
    if rows * cols != count:
        raise ValueError(f"{path}: {rows}x{cols} != {count}")
    return rows, cols, (minimum + heights * per_unit).reshape(rows, cols)


def load_roots(directory):
    """Map landscape actor name -> (location cm, yaw deg, scale) from root_*.json."""
    roots = {}
    for path in glob.glob(os.path.join(directory, "root_*.json")):
        props = json.load(open(path))["Properties"]
        actor = os.path.basename(path)[len("root_"):].split(".")[0]
        loc = props.get("RelativeLocation", {"X": 0, "Y": 0, "Z": 0})
        rot = props.get("RelativeRotation", {"Yaw": 0, "Pitch": 0, "Roll": 0})
        scale = props.get("RelativeScale3D", {"X": 1, "Y": 1, "Z": 1})
        if rot.get("Pitch", 0) or rot.get("Roll", 0):
            raise ValueError(f"{actor}: pitch/roll not supported")
        roots[actor] = ((loc["X"], loc["Y"], loc["Z"]), rot.get("Yaw", 0.0), (scale["X"], scale["Y"], scale["Z"]))
    return roots


def assemble(directory, transpose):
    """Stitch every component into one local grid per landscape actor.

    Returns {actor: (grid [gy, gx] of raw heights with NaN holes, origin_x, origin_y, root)}, with
    origin the local quad index of grid[0, 0]. ``transpose`` selects whether the heightfield rows
    run along local X (True) or local Y (False).
    """
    roots = load_roots(directory)
    parts = {}
    for path in glob.glob(os.path.join(directory, "*.json")):
        if os.path.basename(path).startswith("root_"):
            continue
        export = json.load(open(path))
        props = export["Properties"]
        actor = export["Outer"]["ObjectName"].split(".")[-1].rstrip("'")
        rows, cols, raw = read_heightfield(path[:-5] + ".bin")
        step = props.get("CollisionScale", 1.0)
        if step != 1.0:
            raise ValueError(f"{path}: CollisionScale {step} not supported")
        if transpose:
            raw = raw.T
        # Position in the actor's local quads (UE omits a zero RelativeLocation). For a Landscape
        # it equals SectionBase; a LandscapeStreamingProxy places components from its own origin.
        location = props.get("RelativeLocation", {})
        base_x = int(round(location.get("X", 0)))
        base_y = int(round(location.get("Y", 0)))
        parts.setdefault(actor, []).append((base_x, base_y, raw))
    result = {}
    for actor, items in parts.items():
        x0 = min(x for x, _, _ in items)
        y0 = min(y for _, y, _ in items)
        x1 = max(x + r.shape[1] for x, _, r in items)
        y1 = max(y + r.shape[0] for _, y, r in items)
        grid = np.full((y1 - y0, x1 - x0), np.nan)
        mismatch = []
        for x, y, raw in items:
            window = grid[y - y0:y - y0 + raw.shape[0], x - x0:x - x0 + raw.shape[1]]
            shared = ~np.isnan(window)
            if shared.any():
                mismatch.append(np.abs(window[shared] - raw[shared]).max())
            window[:] = raw
        result[actor] = (grid, x0, y0, roots[actor], max(mismatch) if mismatch else 0.0)
    return result


def triangle_surface(grid, gx, gy):
    """Height of the game's collision surface at fractional grid positions (NaN outside or over a hole).

    The cooked heightfield splits every quad into two triangles along the diagonal from vertex
    (x, y) to (x + 1, y + 1) in the landscape's local grid axes, the diagonal of Unreal's landscape
    render mesh. It was found with ground truth from the server log (``audit_ground_truth.py``): on
    points where the other diagonal would differ by more than 5 mm, this one is the closer in 79 of 89.
    """
    rows, cols = grid.shape
    i = np.clip(np.floor(gx), -1, cols - 1).astype(np.int64)
    j = np.clip(np.floor(gy), -1, rows - 1).astype(np.int64)
    inside = (gx >= 0) & (gy >= 0) & (gx <= cols - 1) & (gy <= rows - 1)
    i = np.clip(i, 0, cols - 2)
    j = np.clip(j, 0, rows - 2)
    fx = gx - i
    fy = gy - j
    z00 = grid[j, i]
    z10 = grid[j, i + 1]
    z01 = grid[j + 1, i]
    z11 = grid[j + 1, i + 1]
    z = np.where(fx >= fy, z00 + fx * (z10 - z00) + fy * (z11 - z10), z00 + fy * (z01 - z00) + fx * (z11 - z01))
    return np.where(inside, z, np.nan)


def sample_world(actor_grid, xs_cm, ys_cm, method="bilinear"):
    """World Z in cm at world points (arrays in cm), NaN outside the landscape.

    `method` is "bilinear" (how the heightmaps were built before their grid was the landscape's vertices) or "triangle"
    (the game's own collision surface, see triangle_surface).
    """
    grid, x0, y0, (loc, yaw, scale), _ = actor_grid
    dx = xs_cm - loc[0]
    dy = ys_cm - loc[1]
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    gx = (c * dx + s * dy) / scale[0] - x0
    gy = (-s * dx + c * dy) / scale[1] - y0
    if method == "triangle":
        raw = triangle_surface(grid, gx, gy)
    elif method == "bilinear":
        from scipy.ndimage import map_coordinates

        raw = map_coordinates(grid, [gy, gx], order=1, mode="constant", cval=np.nan)
    else:
        raise ValueError(f"unknown method {method!r}")
    return loc[2] + scale[2] * raw / 128.0
