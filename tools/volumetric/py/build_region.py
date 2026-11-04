"""Exact-triangle files ("RTRI1") for the precision pass of the engine: the collision triangles around a target.

The voxel layer (VCOL1) decides the segments that stay away from geometry. A segment that passes within ``margin``
of an occupied voxel is re-checked against the triangles of the region, which is what this file holds
(`engine/src/precision.rs` is the reader). One file per target: the square ``centre +- radius`` metres, the
Visibility-blocking triangles of ``world_tris.py`` shards whose box meets it, and only those that a re-checked
segment can hit: a triangle is dropped when no occupied voxel lies within ``margin`` of its box (rounded up to whole
voxels, as the engine dilates), which removes everything buried under the landscape and everything far from a voxel.

    python build_region.py <map.vcol> <out dir> --centre X Y [--centre X Y ...] [--radius 150] [--margin 0.6]
        <tris.npz> [<tris.npz> ...]

writes ``<out dir>/region_<x>_<y>.rtri`` per centre and prints one JSON line per file. Positions are in the frame of the
voxel file (Unreal: metres, X east, Y south).

Layout (little endian), before gzip:
    magic "RTRI1\\0\\0\\0", float32 min_x, min_y, max_x, max_y (the square), float32 margin, float32 origin x, y, z,
    uint32 n_vertices, uint32 n_triangles
    then n_vertices x 3 varints: zigzag of the difference to the previous vertex, in units of QUANT metres, from the
    vertex position relative to the origin; then n_triangles x 3 varints: zigzag of the vertex index difference to the
    previously written index (0 before the first). Vertices are shared between triangles (equal after quantisation)
    and numbered in the order of first use.
"""

import argparse
import gzip
import json
import os
import struct

import numpy as np

import codec
import collision
import columns

MAGIC = b"RTRI1\0\0\0"
HEADER = "<8s8f2I"
HEADER_BYTES = struct.calcsize(HEADER)
QUANT = 1e-4
COARSE_XY = 4
COARSE_Z = 4


def _zigzag_varints(values):
    """Bytes of the zigzag varints of an int64 array."""
    zigzag = ((values << 1) ^ (values >> 63)).astype(np.uint64)
    out = bytearray()
    for v in zigzag.tolist():
        while v >= 0x80:
            out.append((v & 0x7F) | 0x80)
            v >>= 7
        out.append(v)
    return bytes(out)


def encode(tris, bounds, margin):
    """gzip bytes of the RTRI1 file for float32 triangles `tris` [n, 3, 3] and the square `bounds` (min_x, min_y, max_x, max_y)."""
    origin = np.array([(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2, tris[..., 2].min() if len(tris) else 0.0], np.float32)
    if len(tris) == 0:
        return gzip.compress(struct.pack(HEADER, MAGIC, *[float(b) for b in bounds], float(margin), *[float(o) for o in origin], 0, 0), 9)
    quantised = np.rint((tris.reshape(-1, 3).astype(np.float64) - origin.astype(np.float64)) / QUANT).astype(np.int64)
    _, inverse = np.unique(quantised, axis=0, return_inverse=True)
    corners = inverse.reshape(-1, 3)
    # a triangle with a repeated corner cannot be hit; a repeated triangle (the same mesh placed twice) is stored once
    proper = (corners[:, 0] != corners[:, 1]) & (corners[:, 1] != corners[:, 2]) & (corners[:, 0] != corners[:, 2])
    _, first_triangle = np.unique(np.sort(corners[proper], axis=1), axis=0, return_index=True)
    kept = np.nonzero(proper)[0][np.sort(first_triangle)]
    tris = tris[kept]
    unique, first, inverse = np.unique(quantised.reshape(-1, 3, 3)[kept].reshape(-1, 3), axis=0, return_index=True, return_inverse=True)
    inverse = inverse.reshape(-1)
    order = np.argsort(first, kind="stable")
    rank = np.empty(len(order), np.int64)
    rank[order] = np.arange(len(order))
    vertices = unique[order]
    indices = rank[inverse]
    vertex_deltas = np.diff(vertices, axis=0, prepend=np.zeros((1, 3), np.int64)) if len(vertices) else vertices
    index_deltas = np.diff(indices, prepend=0)
    head = struct.pack(HEADER, MAGIC, *[float(b) for b in bounds], float(margin), *[float(o) for o in origin], len(vertices), len(tris))
    return gzip.compress(head + _zigzag_varints(vertex_deltas.reshape(-1)) + _zigzag_varints(index_deltas), 9)


def decode(blob):
    """(float32 triangles [n, 3, 3], bounds, margin) of an RTRI1 file (the reference reader, used by the tests)."""
    raw = gzip.decompress(blob)
    magic, *fields, n_vertices, n_triangles = struct.unpack_from(HEADER, raw)
    assert magic == MAGIC
    bounds, margin, origin = fields[:4], fields[4], np.array(fields[5:8], np.float32)
    position = HEADER_BYTES

    def varints(count):
        nonlocal position
        out = []
        for _ in range(count):
            value, shift = 0, 0
            while True:
                byte = raw[position]
                position += 1
                value |= (byte & 0x7F) << shift
                shift += 7
                if byte < 0x80:
                    break
            out.append((value >> 1) ^ -(value & 1))
        return np.array(out, np.int64)

    vertices = np.cumsum(varints(3 * n_vertices).reshape(-1, 3), axis=0) if n_vertices else np.zeros((0, 3), np.int64)
    indices = np.cumsum(varints(3 * n_triangles))
    world = vertices.astype(np.float64) * QUANT + origin.astype(np.float64)
    return world[indices].astype(np.float32).reshape(-1, 3, 3), bounds, margin


class Occupancy:
    """Coarse prefix-sum grid of the occupied voxels of one square, to ask "is any voxel within `margin` of this box"."""

    def __init__(self, occupied, grid, bounds, margin):
        self.grid, self.margin = grid, margin
        self.radius_xy = int(np.ceil(margin / grid.cell - 1e-9))
        self.radius_z = int(np.ceil(margin / grid.dz - 1e-9))
        mask = (1 << columns.Z_BITS) - 1
        column = occupied >> columns.Z_BITS
        col, row, z = column % grid.width, column // grid.width, occupied & mask
        # a voxel within `radius` voxels of a box that meets the square can lie outside it
        pad = self.radius_xy + 1
        self.lo_col = int((bounds[0] - grid.min_x) / grid.cell) - pad
        self.lo_row = int((bounds[1] - grid.min_y) / grid.cell) - pad
        hi_col = int((bounds[2] - grid.min_x) / grid.cell) + pad
        hi_row = int((bounds[3] - grid.min_y) / grid.cell) + pad
        keep = (col >= self.lo_col) & (col <= hi_col) & (row >= self.lo_row) & (row <= hi_row)
        col, row, z = col[keep], row[keep], z[keep]
        self.lo_z = int(z.min()) if len(z) else 0
        nx = (hi_col - self.lo_col) // COARSE_XY + 2
        ny = (hi_row - self.lo_row) // COARSE_XY + 2
        nz = ((int(z.max()) - self.lo_z) // COARSE_Z + 2) if len(z) else 1
        blocks = np.zeros((nx, ny, nz), np.int32)
        blocks[(col - self.lo_col) // COARSE_XY, (row - self.lo_row) // COARSE_XY, (z - self.lo_z) // COARSE_Z] = 1
        # summed-volume table with a zero plane in front
        self.sums = np.zeros((nx + 1, ny + 1, nz + 1), np.int64)
        self.sums[1:, 1:, 1:] = blocks.cumsum(0).cumsum(1).cumsum(2)

    def near(self, tris):
        """bool [n]: an occupied voxel lies in the box of each triangle widened by the margin (to a coarse block, so a superset)."""
        g = self.grid
        low, high = tris.min(axis=1).astype(np.float64), tris.max(axis=1).astype(np.float64)
        lo = np.stack([np.floor((low[:, 0] - g.min_x) / g.cell) - self.radius_xy - self.lo_col,
                       np.floor((low[:, 1] - g.min_y) / g.cell) - self.radius_xy - self.lo_row,
                       np.floor((low[:, 2] - g.z_min) / g.dz) - self.radius_z - self.lo_z], 1)
        hi = np.stack([np.floor((high[:, 0] - g.min_x) / g.cell) + self.radius_xy - self.lo_col,
                       np.floor((high[:, 1] - g.min_y) / g.cell) + self.radius_xy - self.lo_row,
                       np.floor((high[:, 2] - g.z_min) / g.dz) + self.radius_z - self.lo_z], 1)
        size = np.array(COARSE_XY), np.array(COARSE_XY), np.array(COARSE_Z)
        shape = np.array(self.sums.shape) - 1
        a = np.stack([np.clip(np.floor_divide(lo[:, k], size[k]), 0, shape[k]) for k in range(3)], 1).astype(np.int64)
        b = np.stack([np.clip(np.floor_divide(hi[:, k], size[k]) + 1, 0, shape[k]) for k in range(3)], 1).astype(np.int64)
        s = self.sums

        def at(i, j, k):
            return s[i, j, k]

        total = (at(b[:, 0], b[:, 1], b[:, 2]) - at(a[:, 0], b[:, 1], b[:, 2]) - at(b[:, 0], a[:, 1], b[:, 2]) - at(b[:, 0], b[:, 1], a[:, 2])
                 + at(a[:, 0], a[:, 1], b[:, 2]) + at(a[:, 0], b[:, 1], a[:, 2]) + at(b[:, 0], a[:, 1], a[:, 2]) - at(a[:, 0], a[:, 1], a[:, 2]))
        return total > 0


def select(shard_paths, occupancies, bounds_list):
    """Per square: the Visibility-blocking, near-voxel triangles of the shards whose box meets it, and how many met the box."""
    kept = [[] for _ in bounds_list]
    met = [0] * len(bounds_list)
    for path in shard_paths:
        data = np.load(path)
        tris, mask = data["tris"], data["mask"]
        low, high = tris.min(axis=1), tris.max(axis=1)
        visible = mask & collision.VISIBILITY != 0
        for i, b in enumerate(bounds_list):
            meets = visible & (high[:, 0] >= b[0]) & (low[:, 0] <= b[2]) & (high[:, 1] >= b[1]) & (low[:, 1] <= b[3])
            candidates = tris[meets]
            met[i] += len(candidates)
            kept[i].append(candidates[occupancies[i].near(candidates)])
        del data, tris, mask, low, high
    return [np.concatenate(k) if k else np.zeros((0, 3, 3), np.float32) for k in kept], met


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("vcol")
    parser.add_argument("out")
    parser.add_argument("tris", nargs="+")
    parser.add_argument("--centre", nargs=2, type=float, action="append", required=True, metavar=("X", "Y"))
    parser.add_argument("--radius", type=float, default=150.0)
    parser.add_argument("--margin", type=float, default=0.6)
    args = parser.parse_args()

    occupied, header = codec.decode(open(args.vcol, "rb").read())
    grid = columns.Grid(header["min_x"], header["min_y"], header["width"] * header["cell"], header["height"] * header["cell"],
                        header["cell"], header["dz"], header["z_min"])
    bounds_list = [(x - args.radius, y - args.radius, x + args.radius, y + args.radius) for x, y in args.centre]
    occupancies = [Occupancy(occupied, grid, b, args.margin) for b in bounds_list]
    selected, met = select(args.tris, occupancies, bounds_list)
    os.makedirs(args.out, exist_ok=True)
    for (x, y), b, tris, in_box in zip(args.centre, bounds_list, selected, met):
        blob = encode(tris, b, args.margin)
        name = os.path.join(args.out, f"region_{x:.0f}_{y:.0f}.rtri")
        open(name, "wb").write(blob)
        print(json.dumps(dict(file=name, centre=[x, y], radius=args.radius, margin=args.margin, triangles_in_box=in_box,
                              triangles_kept=int(len(tris)), bytes=len(blob))), flush=True)


if __name__ == "__main__":
    main()
