"""Interior rooms and wall openings of the building meshes of one map, measured on the collision triangles.

Per mesh (mesh space, metres) the collision triangles that ``objects.mesh_triangles`` selects (complex if cooked)
are rasterised into a 0.25 m occupancy grid by dense surface sampling (spacing 0.11 m, so thin walls stay closed)
together with the set of up-facing samples (floors, roof tops).

Room floor cell: an up-facing occupied cell (or the ground level, mesh height 0, where the mesh has no slab) with >= 2 m of free air above, an occupied cell (ceiling or roof)
within 6 m above that, and an occupied cell within 40 m in each of the +x, -x, +y, -y directions at 1.5 m above
the floor. A mesh "has an interior" when its room floor area is >= 4 m^2.

Openings: from up to SAMPLES room cells per mesh, rays are marched (0.1 m steps) over az 0..360 deg step 3 and
elevation -15..+45 deg step 5. Rays that leave the grid are "escaped"; each connected group (az, el) of escaped
rays (gaps of one ray closed) is one opening (groups reaching 45 deg elevation are open sky or roof holes and are dropped), its size is the bounding box of the surface points hit by the blocked rays that surround it
(width = largest horizontal extent, height = vertical extent), its sill is the lowest of those points above the
floor. Sill <= 0.4 m is a door-like opening, otherwise a window-like one. Sizes are quantised by the 0.25 m grid.

Usage: building_interiors.py <statics dir> <kinds.json> <path regex> <out.json>
"""
import json
import os
import re
import sys

import numpy as np
from scipy import ndimage

import objects

CELL = 0.25
SPACING = 0.11
SAMPLES = 3
AZ_STEP, EL_MIN, EL_MAX, EL_STEP = 3, -15, 45, 5


def surface_samples(tris):
    """Points on the triangles (lattice of ~SPACING) and a bool array: sample comes from an up-facing triangle."""
    points, up = [], []
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    normal = np.cross(b - a, c - a)
    length = np.linalg.norm(normal, axis=1)
    facing_up = normal[:, 2] > 0.5 * np.maximum(length, 1e-12)
    edge = np.maximum.reduce([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)])
    counts = np.clip(np.ceil(edge / SPACING).astype(int), 1, 400)
    for n in np.unique(counts):
        sel = np.nonzero(counts == n)[0]
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1))
        keep = i + j <= n
        u, v = (i[keep] / n)[None, :, None], (j[keep] / n)[None, :, None]
        p = a[sel][:, None, :] + u * (b[sel] - a[sel])[:, None, :] + v * (c[sel] - a[sel])[:, None, :]
        points.append(p.reshape(-1, 3))
        up.append(np.repeat(facing_up[sel], p.shape[1]))
    return np.concatenate(points), np.concatenate(up)


def first_blocked(occ, direction, origin_idx, limit):
    """Per-origin distance (cells) to the first occupied cell along an axis direction, inf if none within limit."""
    result = np.full(len(origin_idx), np.inf)
    shape = np.array(occ.shape)
    for step in range(1, limit + 1):
        idx = origin_idx + direction * step
        inside = np.all((idx >= 0) & (idx < shape), axis=1)
        hit = np.zeros(len(idx), bool)
        hit[inside] = occ[tuple(idx[inside].T)]
        newly = hit & np.isinf(result)
        result[newly] = step
    return result


def room_floor_cells(occ, up, ground_k):
    """Indices [n, 3] of room floor cells (see module docstring).

    Besides the up-facing mesh cells, every column is also tried with a virtual floor just below mesh height 0
    (``ground_k``): many buildings have no floor slab and stand on the landscape.
    """
    nx, ny, nz = occ.shape
    cells = np.argwhere(up & occ)
    if 1 <= ground_k < nz:
        columns = np.argwhere(~occ[:, :, ground_k])
        cells = np.concatenate([cells, np.column_stack([columns, np.full(len(columns), ground_k - 1)])])
    if len(cells) == 0:
        return cells
    above_free = np.ones(len(cells), bool)
    for dz in range(1, 9):
        above_free &= ~occ[cells[:, 0], cells[:, 1], np.minimum(cells[:, 2] + dz, nz - 1)]
    cells = cells[above_free]
    ceiling = np.zeros(len(cells), bool)
    for dz in range(9, 25):
        k = np.minimum(cells[:, 2] + dz, nz - 1)
        ceiling |= occ[cells[:, 0], cells[:, 1], k]
    cells = cells[ceiling]
    eye = cells + np.array([0, 0, 6])
    eye[:, 2] = np.minimum(eye[:, 2], nz - 1)
    enclosed = np.ones(len(cells), bool)
    for direction in ([1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]):
        enclosed &= np.isfinite(first_blocked(occ, np.array(direction), eye, 160))
    return cells[enclosed]


def fan_openings(occ, origin, floor_z):
    """Openings seen from one world-grid point: list of dicts (width, height, sill, distance) in metres."""
    az = np.deg2rad(np.arange(0, 360, AZ_STEP))
    el = np.deg2rad(np.arange(EL_MIN, EL_MAX + 1, EL_STEP))
    A, E = np.meshgrid(az, el, indexing="ij")
    dirs = np.stack([np.cos(E) * np.cos(A), np.cos(E) * np.sin(A), np.sin(E)], axis=-1).reshape(-1, 3)
    steps = np.arange(0.1, 60.0, 0.1)
    shape = np.array(occ.shape)
    hit_t = np.full(len(dirs), np.inf)
    for t in steps:
        idx = np.floor((origin + dirs * t) / CELL).astype(int)
        inside = np.all((idx >= 0) & (idx < shape), axis=1)
        undecided = np.isinf(hit_t)
        hit = np.zeros(len(dirs), bool)
        probe = inside & undecided
        hit[probe] = occ[tuple(idx[probe].T)]
        hit_t[hit] = t
        left = undecided & ~inside
        hit_t[left] = -1.0
        if not np.isinf(hit_t).any():
            break
    escaped = (hit_t < 0).reshape(len(az), len(el))
    closed = ndimage.binary_closing(escaped, structure=np.ones((3, 3)), border_value=0) | escaped
    points = (origin + dirs * np.where(hit_t > 0, hit_t, 0)[:, None]).reshape(len(az), len(el), 3)
    blocked_columns = np.nonzero(~closed.any(axis=1))[0]
    if len(blocked_columns) == 0:
        return []
    shift = -int(blocked_columns[0])
    escaped, closed, points = (np.roll(a, shift, axis=0) for a in (escaped, closed, points))
    labels, count = ndimage.label(closed, structure=np.ones((3, 3)))
    found = []
    for label in range(1, count + 1):
        member = labels == label
        ring = ndimage.binary_dilation(member, structure=np.ones((3, 3)), iterations=1, border_value=0) & ~closed
        pts = points[ring]
        if len(pts) < 4 or np.rad2deg(el[np.nonzero(member.any(axis=0))[0].max()]) > 40:
            continue
        horizontal = np.hypot(np.ptp(pts[:, 0]), np.ptp(pts[:, 1]))
        height = np.ptp(pts[:, 2])
        distance = float(np.median(np.linalg.norm(pts - origin, axis=1)))
        found.append({"width": round(float(horizontal), 2), "height": round(float(height), 2),
                      "sill": round(float(pts[:, 2].min() - floor_z), 2), "distance": round(distance, 2),
                      "elevation_max_deg": float(np.rad2deg(el[np.nonzero(member.any(axis=0))[0].max()]))})
    return found


def analyse_mesh(prefix, rng):
    found = objects.mesh_triangles(prefix)
    if found is None:
        return None
    tris = found[0] / 100.0
    low = tris.reshape(-1, 3).min(0) - 1.0
    size = tris.reshape(-1, 3).max(0) + 1.0 - low
    if np.prod(size / CELL) > 4e7:
        return {"skipped": "grid too large"}
    points, up = surface_samples(tris - low)
    idx = np.floor(points / CELL).astype(int)
    occ = np.zeros(np.ceil(size / CELL).astype(int) + 1, bool)
    upgrid = np.zeros_like(occ)
    occ[tuple(idx.T)] = True
    upgrid[tuple(idx[up].T)] = True
    cells = room_floor_cells(occ, upgrid, int(np.ceil(-low[2] / CELL)))
    result = {"source": found[2], "triangles": int(len(tris)), "size_m": [round(float(x), 1) for x in size],
              "room_floor_area_m2": round(len(cells) * CELL * CELL, 1), "openings": []}
    if len(cells) < 64:
        return result
    for cell in cells[rng.choice(len(cells), min(SAMPLES, len(cells)), replace=False)]:
        origin = (cell + np.array([0.5, 0.5, 6.5])) * CELL
        floor_z = (cell[2] + 1) * CELL
        for opening in fan_openings(occ, origin, floor_z):
            opening["sample_local_m"] = [round(float(x), 2) for x in (origin + low)]
            result["openings"].append(opening)
    return result


def main(directory, kinds_file, pattern, out):
    rng = np.random.default_rng(1)
    rows = []
    for mesh in json.load(open(kinds_file))["meshes"]:
        if not mesh.get("path") or not re.search(pattern, mesh["path"]):
            continue
        try:
            row = analyse_mesh(os.path.join(directory, "bodies", mesh["mesh"]), rng)
        except Exception as error:
            row = {"error": f"{type(error).__name__}: {error}"}
        if row is not None:
            rows.append({"mesh": mesh["mesh"], "path": mesh["path"], "placements": mesh["placements"], **row})
    json.dump(rows, open(out, "w"), indent=1)
    print(len(rows), "meshes analysed;", sum(1 for r in rows if r.get("room_floor_area_m2", 0) >= 4), "with an interior")


if __name__ == "__main__":
    main(*sys.argv[1:5])
