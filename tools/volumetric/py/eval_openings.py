"""Windows, doorways and interiors: judge the heightmap and the voxel columns against the exact tracer inside buildings.

    python eval_openings.py <slug> <tris.npz> <statics.npz> <vcol> <heightmap dir> <out.json> [per_category] [window_m] [seed]

Finds enterable spaces by vertical reference rays (a standable floor with a ceiling within CEILING_M above it and the
served top surface above it is *inside*; one with open sky is *outside*), draws eye-level segments between them and lets the
exact triangle tracer (reference.py, landscape sampled every 0.1 m) decide. The categories are
  opening            inside -> outside, truth clear (the line passes a window, a doorway or a gap)
  wall               inside -> outside, truth blocked
  room_clear         inside -> inside of the same roof, truth clear
  room_partition     inside -> inside of the same roof, same storey (floor within STOREY_M), truth blocked
  room_floor         inside -> inside of the same roof, another storey, truth blocked
For every case the margins say how robust the truth is: the largest shift (0.1, 0.25, 0.5 m, up/down/sideways) after which the
answer is the same; an opening with margin 0.25 is at least 0.5 m wide and 0.5 m high where the line crosses it.
The 1 m heightmap (nearest-cell top surface, as models.HeightmapModel) and the python voxel model of the VCOL1 file are scored
too, so that the page's JavaScript can be compared to both. Writes the cases with their answers as JSON.
"""

import json
import os
import struct
import sys
import zipfile

import numpy as np

import codec
import collision
import columns
import eval_los
import maps
import models
import reference
import terrain
import terrain_raster

EYE_M = 1.6
CEILING_M = 6.0
STOREY_M = 1.5
SHIFTS_M = (0.1, 0.25, 0.5)
LANDSCAPE_ROOT = "/data/squad-extract/landscapes"


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


def load_window(path, x0, y0, size, margin=10.0, chunk=2_000_000):
    """(tris, mask, part) of the triangles whose bounding box touches the window, read in chunks."""
    arrays = npz_memmaps(path)
    out = {"tris": [], "mask": [], "part": []}
    for start in range(0, len(arrays["tris"]), chunk):
        t = np.asarray(arrays["tris"][start:start + chunk])
        lo, hi = t.min(axis=1), t.max(axis=1)
        keep = (hi[:, 0] >= x0 - margin) & (lo[:, 0] <= x0 + size + margin) & (hi[:, 1] >= y0 - margin) & (lo[:, 1] <= y0 + size + margin)
        out["tris"].append(t[keep])
        out["mask"].append(np.asarray(arrays["mask"][start:start + chunk])[keep])
        out["part"].append(np.asarray(arrays["part"][start:start + chunk])[keep])
    return [np.concatenate(out[k]) for k in ("tris", "mask", "part")]


def landscape(slug, meta):
    """models.Landscape of the map on its heightmap grid (landscape collision, holes marked)."""
    b = meta["bounds_m"]
    cell = float(meta.get("resolution_m", 1.0))
    width = int(round((b["max_x"] - b["min_x"]) / cell)) + 1
    height = int(round((b["max_y"] - b["min_y"]) / cell)) + 1
    actors = [(g, h, x0, y0, root) for level in maps.MAPS[slug][1] for g, h, x0, y0, root in terrain.assemble(f"{LANDSCAPE_ROOT}/{level}").values()]
    z, hole = terrain_raster.sample_grid(actors, b["min_x"], b["min_y"], cell, width, height)
    return models.Landscape(z, hole, b["min_x"], b["min_y"])


def margins(index, land, p0, p1, truth):
    """Largest shift in SHIFTS_M (0 when none) after which all four shifted segments (up, down, left, right) give `truth` again."""
    d = p1 - p0
    side = np.array([-d[1], d[0], 0.0])
    side = side / max(np.linalg.norm(side), 1e-9)
    best = 0.0
    for s in SHIFTS_M:
        same = True
        for shift in (np.array([0, 0, s]), np.array([0, 0, -s]), side * s, -side * s):
            x, y, z = models.march(p0 + shift, p1 + shift, 0.1)
            answer = bool(land.blocks(x, y, z).any()) or index.blocked(p0 + shift, p1 + shift, collision.VISIBILITY)[0]
            same &= answer == truth
        if not same:
            break
        best = s
    return best


def main():
    slug, tris_path, statics_path, vcol_path, hm_dir, out_path = sys.argv[1:7]
    per_category = int(sys.argv[7]) if len(sys.argv) > 7 else 120
    window = float(sys.argv[8]) if len(sys.argv) > 8 else 600.0
    rng = np.random.default_rng(int(sys.argv[9]) if len(sys.argv) > 9 else 11)
    vis = collision.VISIBILITY

    meta = json.load(open(os.path.join(hm_dir, "meta.json")))
    top, bounds = eval_los.load_heightmap(hm_dir)
    land = landscape(slug, meta)
    statics = np.load(statics_path)
    grid = columns.Grid(float(statics["min_x"]), float(statics["min_y"]), int(statics["width"]) * float(statics["cell"]),
                        int(statics["height"]) * float(statics["cell"]), float(statics["cell"]), float(statics["dz"]), float(statics["z_min"]))
    wx, wy = eval_los.densest_window(statics["occupied"], grid, window)
    print("window", wx, wy, flush=True)
    tris, mask, part = load_window(tris_path, wx, wy, window)
    print("triangles in window", len(tris), flush=True)
    index = reference.TriangleIndex(tris, mask, wx - 10, wy - 10, window + 20, window + 20)

    keys, header = codec.decode(open(vcol_path, "rb").read())
    vgrid = columns.Grid(header["min_x"], header["min_y"], header["width"] * header["cell"], header["height"] * header["cell"], header["cell"], header["dz"], header["z_min"])
    voxels = models.VoxelModel(land, vgrid, keys)
    heightmap = models.HeightmapModel(top, bounds["min_x"], bounds["min_y"])

    column = keys >> columns.Z_BITS
    cx = (column % vgrid.width) * vgrid.cell + vgrid.min_x
    cy = (column // vgrid.width) * vgrid.cell + vgrid.min_y
    sel = (cx >= wx) & (cx < wx + window) & (cy >= wy) & (cy < wy + window)
    object_xy = np.unique(np.stack([cx[sel], cy[sel]], 1), axis=0)

    inside, outside = [], []
    attempts = 0
    while (len(inside) < 600 or len(outside) < 600) and attempts < 400_000:
        attempts += 1
        x, y = object_xy[rng.integers(len(object_xy))] + rng.uniform(-6, 6, 2)
        c = int(np.clip(np.floor(x - bounds["min_x"]), 0, top.shape[1] - 1))
        r = int(np.clip(np.floor(y - bounds["min_y"]), 0, top.shape[0] - 1))
        ground = float(land.height(np.array([x]), np.array([y]))[0])
        for f in index.floors(x, y, top[r, c] + 3, ground - 3, vis):
            up, ids, nz = index.hits([x, y, f + 1.95], [x, y, f + CEILING_M], vis)
            if len(ids) and nz[0] < -0.5 and top[r, c] > f + 1.0:
                inside.append((x, y, f, int(part[ids[0]])))
            elif not len(index.hits([x, y, f + 1.95], [x, y, f + 40.0], vis)[1]):
                outside.append((x, y, f, -1))
    print("inside points", len(inside), "outside points", len(outside), flush=True)

    cases, counts = [], {}

    def record(category, a, b, eye_a=EYE_M, eye_b=EYE_M):
        p0, p1 = np.array([a[0], a[1], a[2] + eye_a]), np.array([b[0], b[1], b[2] + eye_b])
        x, y, z = models.march(p0, p1, 0.1)
        truth = bool(land.blocks(x, y, z).any()) or index.blocked(p0, p1, vis)[0]
        wanted = {"opening": False, "wall": True, "room_clear": False, "room_partition": True, "room_floor": True}[category]
        if truth != wanted or counts.get(category, 0) >= per_category:
            return
        counts[category] = counts.get(category, 0) + 1
        cases.append(dict(category=category, roof_part=int(a[3]), a=[round(float(v), 3) for v in p0], b=[round(float(v), 3) for v in p1],
                          truth_blocked=int(truth), margin=margins(index, land, p0, p1, truth), length=round(float(np.linalg.norm(p1 - p0)), 2),
                          heightmap_blocked=int(heightmap.blocked(p0, p1)), voxel_blocked=int(voxels.blocked(p0, p1))))

    tries = 0
    while tries < 200_000 and any(counts.get(c, 0) < per_category for c in ("opening", "wall", "room_clear", "room_partition", "room_floor")):
        tries += 1
        a = inside[rng.integers(len(inside))]
        eye = EYE_M if rng.random() < 0.75 else 0.7
        if rng.random() < 0.5 and outside:
            b = outside[rng.integers(len(outside))]
            d = np.hypot(a[0] - b[0], a[1] - b[1])
            if 3 < d < 40:
                record("opening", a, b, eye, EYE_M)
                record("wall", a, b, eye, EYE_M)
        else:
            b = inside[rng.integers(len(inside))]
            d = np.hypot(a[0] - b[0], a[1] - b[1])
            if a[3] != b[3] or not 2 < d < 25:
                continue
            if abs(a[2] - b[2]) > STOREY_M:
                record("room_floor", a, b, eye, eye)
            else:
                record("room_clear", a, b, eye, eye)
                record("room_partition", a, b, eye, eye)
    json.dump(dict(map=slug, window=[wx, wy, window], origin=[bounds["min_x"], bounds["min_y"]], z_offset=meta["z_min_m"], counts=counts, cases=cases), open(out_path, "w"))
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
