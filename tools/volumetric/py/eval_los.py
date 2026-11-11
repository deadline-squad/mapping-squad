"""Judge the top-surface heightmap and the voxel columns against exact triangle ray tests on one map window.

    python eval_los.py <tris.npz (or shard base name)> <cols.npz> <heightmap dir> <terrain.npz> <out dir> [pairs] [window_m] [seed]

Standable points (floors with 1.9 m headroom, found by vertical reference rays) are drawn in the densest
window of the map; pairs 10-60 m apart get eye-level segments (floor + 1.6 m); the reference decides
blocked/clear (landscape sampled every 0.1 m, objects by Moller-Trumbore); both models are scored against it.
Writes metrics.json and cases.csv (pairs where the heightmap is wrong) to the output directory.
"""

import csv
import glob
import json
import os
import struct
import sys
import zipfile

import numpy as np
from PIL import Image

import collision
import columns
import lattice
import models
import reference

EYE_M = 1.6


def load_heightmap(directory):
    """(heights m, bounds) of a served heightmap at the points of the 1 m grid from its bounds' corner, the grid the models
    index; its own samples are the landscape's vertices, read at those points as SquadCalc reads them (lattice.on_grid)."""
    with open(os.path.join(directory, "meta.json")) as handle:
        meta = json.load(handle)
    with Image.open(os.path.join(directory, "heightmap.png")) as image:
        heights = np.asarray(image).astype(np.float32) * np.float32(meta["z_step_m"]) + np.float32(meta["z_min_m"])
    return lattice.on_grid(heights, lattice.from_meta(meta), meta["bounds_m"], 1.0), meta["bounds_m"]


GRAZE_M = 0.25


def is_grazing(index, land, p0, p1, truth, bit):
    """Whether the reference answer flips when the segment shifts by GRAZE_M up, down or sideways (ambiguous)."""
    d = p1 - p0
    side = np.array([-d[1], d[0], 0.0])
    side = side / max(np.linalg.norm(side), 1e-9) * GRAZE_M
    answers = []
    for shift in (np.array([0, 0, GRAZE_M]), np.array([0, 0, -GRAZE_M]), side, -side):
        x, y, z = models.march(p0 + shift, p1 + shift, 0.1)
        answers.append(bool(land.blocks(x, y, z).any()) or index.blocked(p0 + shift, p1 + shift, bit)[0])
    return any(a != truth for a in answers)


def npz_memmaps(path):
    """{name: memmap} of the arrays of an uncompressed npz (np.savez), without reading them."""
    arrays = {}
    with zipfile.ZipFile(path) as zf, open(path, "rb") as raw:
        for info in zf.infolist():
            raw.seek(info.header_offset)
            name_len, extra_len = struct.unpack("<HH", raw.read(30)[26:30])
            raw.seek(info.header_offset + 30 + name_len + extra_len)
            version = np.lib.format.read_magic(raw)
            shape, _, dtype = np.lib.format.read_array_header_1_0(raw) if version == (1, 0) else np.lib.format.read_array_header_2_0(raw)
            arrays[info.filename[:-4]] = np.memmap(path, dtype=dtype, mode="r", offset=raw.tell(), shape=shape)
    return arrays


def shard_paths(path):
    """[path] when it exists, else the shards ``<path minus .npz>.<i>.npz`` written by world_tris.py with a shard size."""
    if os.path.exists(path):
        return [path]
    base = path[:-len(".npz")]
    return sorted(glob.glob(f"{base}.*.npz"), key=lambda p: int(p[len(base) + 1:-len(".npz")]))


def load_window(path, x0, y0, size, margin=10.0, chunk=2_000_000):
    """(tris, mask, part) of the triangles whose bounding box touches the window, read in chunks.

    ``path`` is an uncompressed npz or the base name of its shards (shard part indices are offset so that they stay unique).
    """
    out = {"tris": [], "mask": [], "part": []}
    part_offset = 0
    for shard in shard_paths(path):
        arrays = npz_memmaps(shard)
        for start in range(0, len(arrays["tris"]), chunk):
            t = np.asarray(arrays["tris"][start:start + chunk])
            lo, hi = t.min(axis=1), t.max(axis=1)
            keep = (hi[:, 0] >= x0 - margin) & (lo[:, 0] <= x0 + size + margin) & (hi[:, 1] >= y0 - margin) & (lo[:, 1] <= y0 + size + margin)
            out["tris"].append(t[keep])
            out["mask"].append(np.asarray(arrays["mask"][start:start + chunk])[keep])
            out["part"].append(np.asarray(arrays["part"][start:start + chunk])[keep] + part_offset)
        part_offset += len(arrays["parts"])
    return [np.concatenate(out[k]) for k in ("tris", "mask", "part")]



def densest_window(occupied, grid, size_m):
    """(x0, y0) of the size_m window holding the most occupied columns, on a 100 m lattice."""
    column = np.unique(occupied >> columns.Z_BITS)
    cx = (column % grid.width) * grid.cell + grid.min_x
    cy = (column // grid.width) * grid.cell + grid.min_y
    bins = 100.0
    nx, ny = int(grid.width * grid.cell / bins) + 1, int(grid.height * grid.cell / bins) + 1
    hist = np.zeros((ny, nx))
    np.add.at(hist, (((cy - grid.min_y) // bins).astype(int), ((cx - grid.min_x) // bins).astype(int)), 1)
    k = int(size_m / bins)
    csum = hist.cumsum(0).cumsum(1)
    best, at = -1, (0, 0)
    for j in range(0, ny - k):
        for i in range(0, nx - k):
            s = csum[j + k, i + k] - csum[j, i + k] - csum[j + k, i] + csum[j, i]
            if s > best:
                best, at = s, (i, j)
    return grid.min_x + at[0] * bins, grid.min_y + at[1] * bins


def main():
    tris_path, cols_path, hm_dir, terrain_path, out_dir = sys.argv[1:6]
    pairs_n = int(sys.argv[6]) if len(sys.argv) > 6 else 3000
    window = float(sys.argv[7]) if len(sys.argv) > 7 else 600.0
    rng = np.random.default_rng(int(sys.argv[8]) if len(sys.argv) > 8 else 7)
    os.makedirs(out_dir, exist_ok=True)

    cols = np.load(cols_path)
    grid = columns.Grid(float(cols["min_x"]), float(cols["min_y"]), int(cols["width"]) * float(cols["cell"]),
                        int(cols["height"]) * float(cols["cell"]), float(cols["cell"]), float(cols["dz"]), float(cols["z_min"]))
    occupied = cols["occupied"]
    top, bounds = load_heightmap(hm_dir)
    ter = np.load(terrain_path)
    land = models.Landscape(ter["z"].astype(np.float64), ter["hole"], bounds["min_x"], bounds["min_y"])

    wx, wy = densest_window(occupied, grid, window)
    print("window", wx, wy, window, flush=True)
    tris, mask, part = load_window(tris_path, wx, wy, window)
    print("triangles in window", len(tris), flush=True)
    index = reference.TriangleIndex(tris, mask, wx - 10, wy - 10, window + 20, window + 20)

    vis = collision.VISIBILITY
    in_window = (occupied >> columns.Z_BITS)
    col_x = (in_window % grid.width) * grid.cell + grid.min_x
    col_y = (in_window // grid.width) * grid.cell + grid.min_y
    sel = (col_x >= wx) & (col_x < wx + window) & (col_y >= wy) & (col_y < wy + window)
    object_xy = np.unique(np.stack([col_x[sel], col_y[sel]], 1), axis=0)

    points = []
    while len(points) < 2 * pairs_n:
        if rng.random() < 0.8:
            x, y = object_xy[rng.integers(len(object_xy))] + rng.uniform(-3, 3, 2)
        else:
            x, y = wx + rng.uniform(0, window), wy + rng.uniform(0, window)
        c = int(np.clip(np.floor(x - bounds["min_x"]), 0, top.shape[1] - 1))
        r = int(np.clip(np.floor(y - bounds["min_y"]), 0, top.shape[0] - 1))
        ground = float(land.height(np.array([x]), np.array([y]))[0])
        floors = index.floors(x, y, top[r, c] + 3, ground - 3, vis)
        if not floors:
            continue
        k = rng.integers(len(floors))
        points.append((x, y, floors[k], len(floors), floors[k] < top[r, c] - 0.5))
    pts = np.array(points, float)
    print("standable points", len(pts), "covered (floor below top surface)", int(pts[:, 4].sum()), flush=True)

    heightmap = models.HeightmapModel(top, bounds["min_x"], bounds["min_y"])
    voxels = models.VoxelModel(land, grid, occupied)
    rows, tally = [], {}
    for _ in range(pairs_n):
        a = pts[rng.integers(len(pts))]
        near = np.nonzero((np.hypot(pts[:, 0] - a[0], pts[:, 1] - a[1]) > 10) & (np.hypot(pts[:, 0] - a[0], pts[:, 1] - a[1]) < 60))[0]
        if len(near) == 0:
            continue
        b = pts[rng.choice(near)]
        p0, p1 = np.array([a[0], a[1], a[2] + EYE_M]), np.array([b[0], b[1], b[2] + EYE_M])
        x, y, z = models.march(p0, p1, 0.1)
        land_hit = bool(land.blocks(x, y, z).any())
        obj_hit, tri_ids = index.blocked(p0, p1, vis)
        truth = land_hit or obj_hit
        h = heightmap.blocked(p0, p1)
        v = voxels.blocked(p0, p1)
        covered = bool(a[4] or b[4])
        graze = is_grazing(index, land, p0, p1, truth, vis) if (h != truth or v != truth) else False
        for name, got in (("heightmap", h), ("voxels", v)):
            for group in ("all", "covered" if covered else "open"):
                t = tally.setdefault((name, group), np.zeros(5, int))
                t[(2 if truth else 0) + (1 if got else 0)] += 1  # [clear/clear, clear/blocked, blocked/clear, blocked/blocked]
                t[4] += int(got != truth and graze)
        if h != truth or v != truth:
            first = voxels.first_block_m(p0, p1)
            ref_t, _, _ = index.hits(p0, p1, vis)
            rows.append(dict(grazing=int(graze), ax=a[0], ay=a[1], az=a[2], bx=b[0], by=b[1], bz=b[2], truth=int(truth), heightmap=int(h),
                             voxels=int(v), covered=int(covered), landscape=int(land_hit),
                             blocker_part=int(part[tri_ids[0]]) if len(tri_ids) else -1,
                             length=round(float(np.linalg.norm(p1 - p0)), 2), voxel_first_m=-1 if first is None else round(first, 2),
                             truth_first_m=round(float(ref_t[0]) * float(np.linalg.norm(p1 - p0)), 2) if len(ref_t) else -1))
    metrics = {}
    for (name, group), t in sorted(tally.items()):
        n = int(t[:4].sum())
        metrics.setdefault(group, {})[name] = dict(
            pairs=n, wrong=int(t[1] + t[2]), wrong_pct=round(100 * (t[1] + t[2]) / n, 2),
            wrong_not_grazing=int(t[1] + t[2] - t[4]), wrong_not_grazing_pct=round(100 * (t[1] + t[2] - t[4]) / n, 2),
            false_blocked=int(t[1]), false_clear=int(t[2]), truth_blocked=int(t[2] + t[3]))
    metrics["window"] = dict(x=wx, y=wy, size=window, triangles=int(len(tris)), points=int(len(pts)), covered_points=int(pts[:, 4].sum()))
    metrics["voxels"] = dict(cell=grid.cell, dz=grid.dz, occupied=int(len(occupied)))
    json.dump(metrics, open(os.path.join(out_dir, "metrics.json"), "w"), indent=1)
    with open(os.path.join(out_dir, "cases.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["none"])
        w.writeheader()
        w.writerows(rows)
    print(json.dumps(metrics, indent=1))


if __name__ == "__main__":
    main()
