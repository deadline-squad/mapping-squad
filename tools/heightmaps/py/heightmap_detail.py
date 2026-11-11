"""The detail of a heightmap where objects stand (heightmap.detail.bin next to heightmap.png).

A heightmap's grid is the landscape's vertices, so on bare ground the page's read is the game's collision; next to an object
the 2.5-D surface between two nodes is the triangle rule's plane, metres off at a wall or a roof edge (README "Detail where
objects stand"). The detail stores, on the quads where it matters, the heights of the nodes of the lattice subdivided by
FACTOR (lattice.subdivided) inside the quad, fused like the heightmap (build_detail.py); the page reads such a quad as the
FACTOR x FACTOR quads of those nodes, with the same triangle rule, and every other quad as before.

Layout (gzip of, little endian): magic b"HMD1", uint32 factor, unit, quad columns (width - 1), quad rows (height - 1), quad
count; the bitset of the quads with detail (quad q = row * quad columns + col, bit q % 8 of byte q // 8); then for each of
those quads in the order of q the (factor + 1)^2 - 4 nodes of its sub-grid that are not its corners, row-major, each as the
zigzag LEB128 varint of v: the node's level is the level the triangle rule reads there from the quad's four corners, rounded
half up (``predicted``), plus v * unit. Levels are those of heightmap.png: height above meta.json ``z_min_m`` = level *
``z_step_m``; a node may lie below level 0 or above 65535. The unit is UNIT_M in levels (``unit_levels``): a node of the
detail is at most half of it off, and one the prediction holds to half a level (bare ground between bare corners) is exact.

meta.json announces it: ``detail: {file, encoding, factor, unit, threshold_m, quads, bytes}``. A quad has detail when one of
its sub-grid nodes lies more than ``threshold_m`` from the base read; the build takes the smallest of THRESHOLDS_M whose
file keeps heightmap.webp and the detail within the size of heightmap.png (``choose``), and writes none when no threshold
does.

Usage: heightmap_detail.py <heightmaps dir> <points.json> <map> [map ...]
writes POINTS random world points (metres) in quads with detail of each map and the height the page must read there
(``read`` of heightmap.webp and the detail, plus z_min_m) as {"<map>": [[x, y, z], ...]}, for
tools/browser_check/heightmap_native.mjs --detail.
"""

import gzip
import json
import os
import struct
import sys

import numpy as np

import heightmap_webp
import lattice

FILE = "heightmap.detail.bin"
MAGIC = b"HMD1"
FACTOR = 2
THRESHOLDS_M = (0.25, 0.5, 1.0, 2.0)
POINTS = 1000
# The residuals' unit: a wall's metres take one or two bytes, and the gzip of a map's detail is half the size it has at the
# heightmap's step (Sumari, 0.25 m: 256 against 515 kB)
UNIT_M = 0.05
HEADER = struct.Struct("<4s5I")
ENCODING = ("gzip: magic HMD1, uint32 factor, unit, quad columns, quad rows, quad count; bitset of the quads with detail; "
            "per quad the sub-grid nodes without its corners, row-major, zigzag varints of (level - predicted level) / unit")


def unit_levels(step):
    """The unit of the residuals, in levels of ``step`` metres: UNIT_M rounded, at least one level."""
    return max(1, round(UNIT_M / step))


def inner_nodes(factor):
    """(i, j) sub-grid positions (row, col; 0 .. factor) of a quad's nodes that are not its corners, row-major."""
    return [(i, j) for i in range(factor + 1) for j in range(factor + 1) if not (i in (0, factor) and j in (0, factor))]


def predicted(levels, rows, cols, factor):
    """Int64 [n, len(inner_nodes)]: the levels the triangle rule reads at the sub-grid nodes of quads (rows, cols) of
    ``levels`` [height, width], rounded half up. The upper-right triangle (j >= i) holds the corners (0, 0), (0, 1), (1, 1),
    the other (0, 0), (1, 0), (1, 1), as squadHeightmaps.js getHeight splits a quad."""
    c00 = levels[rows, cols].astype(np.int64)[:, None]
    c01 = levels[rows, cols + 1].astype(np.int64)[:, None]
    c10 = levels[rows + 1, cols].astype(np.int64)[:, None]
    c11 = levels[rows + 1, cols + 1].astype(np.int64)[:, None]
    i, j = (np.array(axis, np.int64)[None] for axis in zip(*inner_nodes(factor)))
    scaled = np.where(j >= i, factor * c00 + j * (c01 - c00) + i * (c11 - c01), factor * c00 + i * (c10 - c00) + j * (c11 - c10))
    return (2 * scaled + factor) // (2 * factor)


def _varints(values):
    """Zigzag LEB128 bytes of int64 ``values`` (each within 32 bits)."""
    zigzag = np.where(values >= 0, 2 * values, -2 * values - 1).astype(np.uint64)
    lengths = np.ones(len(zigzag), np.int64)
    for bits in (7, 14, 21, 28):
        lengths += zigzag >= (1 << bits)
    starts = np.cumsum(lengths) - lengths
    out = np.zeros(int(lengths.sum()), np.uint8)
    for k in range(5):
        has = lengths > k
        byte = (zigzag[has] >> np.uint64(7 * k)) & np.uint64(0x7F)
        more = (lengths[has] > k + 1).astype(np.uint64) << np.uint64(7)
        out[starts[has] + k] = (byte | more).astype(np.uint8)
    return out.tobytes()


def _unvarints(data, count):
    """``count`` int64 values of zigzag LEB128 ``data``."""
    raw = np.frombuffer(data, np.uint8)
    ends = np.flatnonzero(raw < 0x80)
    if len(ends) < count:
        raise ValueError(f"{len(ends)} varints in the detail, {count} expected")
    ends = ends[:count]
    starts = np.concatenate([[0], ends[:-1] + 1])
    zigzag = np.zeros(count, np.uint64)
    for k in range(5):
        has = starts + k <= ends
        zigzag[has] |= (raw[starts[has] + k].astype(np.uint64) & np.uint64(0x7F)) << np.uint64(7 * k)
    zigzag = zigzag.astype(np.int64)
    return np.where(zigzag % 2 == 0, zigzag // 2, -(zigzag + 1) // 2)


def encode(flags, values, factor, unit):
    """The gzip bytes of a detail: ``flags`` bool [quad rows, quad cols], ``values`` int64 [flags.sum(), inner nodes] (the
    residuals in ``unit`` levels) in the order of the flagged quads (row-major)."""
    rows, cols = flags.shape
    head = HEADER.pack(MAGIC, factor, unit, cols, rows, int(flags.sum()))
    bits = np.packbits(flags.reshape(-1), bitorder="little").tobytes()
    return gzip.compress(head + bits + _varints(values.reshape(-1)), 9, mtime=0)


def decode(data):
    """(factor, unit, flags bool [quad rows, quad cols], values int64 [count, inner nodes]) of the gzip bytes of a detail."""
    raw = gzip.decompress(data)
    magic, factor, unit, cols, rows, count = HEADER.unpack_from(raw)
    if magic != MAGIC:
        raise ValueError("not an HMD1 detail")
    size = (rows * cols + 7) // 8
    flags = np.unpackbits(np.frombuffer(raw, np.uint8, size, HEADER.size), count=rows * cols, bitorder="little").astype(bool)
    inner = len(inner_nodes(factor))
    values = _unvarints(raw[HEADER.size + size:], count * inner).reshape(count, inner)
    return factor, unit, flags.reshape(rows, cols), values


def choose(shape, quads, largest, residuals, factor, budget_bytes, step):
    """((threshold_m, flags, data) of the smallest of THRESHOLDS_M whose detail file fits ``budget_bytes``, or None; the
    bytes of the file of each threshold tried). The candidates: ``quads`` the sorted flat indices in the quad grid of
    ``shape`` (quad rows, quad cols), ``largest`` the largest |level - predicted level| of each one's sub-grid nodes,
    ``residuals`` int64 [len(quads), inner nodes] theirs in levels of ``step`` metres; a quad that is not one of them has no
    detail at any threshold. The file holds the residuals in unit_levels(step)."""
    unit = unit_levels(step)
    values = np.rint(residuals / unit).astype(np.int64)
    sizes = {}
    for threshold in THRESHOLDS_M:
        chosen = largest * step > threshold
        flags = np.zeros(shape, bool)
        flags.reshape(-1)[quads[chosen]] = True
        data = encode(flags, values[chosen], factor, unit)
        sizes[threshold] = len(data)
        if len(data) <= budget_bytes:
            return (threshold, flags, data), sizes
    return None, sizes


def meta_entry(threshold, flags, data, factor, unit):
    """The ``detail`` entry of meta.json."""
    return {"file": FILE, "encoding": ENCODING, "factor": factor, "unit": unit, "threshold_m": threshold,
            "quads": int(flags.sum()), "bytes": len(data)}


def load(directory, meta):
    """The detail (decode) a heightmap folder announces, or None."""
    entry = meta.get("detail")
    if not entry:
        return None
    with open(os.path.join(directory, entry["file"]), "rb") as f:
        return decode(f.read())


def in_quads(grid, detail, xs, ys):
    """Bool per world point: it lies in a quad with ``detail`` (decode, or None for none) of a heightmap on ``grid``
    (lattice.Lattice), where ``read`` takes the quad's sub-grid; a point outside the grid counts in its nearest quad."""
    if detail is None:
        return np.zeros(np.shape(xs), bool)
    flags = detail[2]
    col, row = lattice.to_grid(grid, xs, ys)
    r0 = np.clip(np.floor(row), 0, grid.height - 2).astype(np.int64)
    c0 = np.clip(np.floor(col), 0, grid.width - 2).astype(np.int64)
    return flags[r0, c0]


def read(levels, grid, detail, xs, ys):
    """Levels (float) at world points of the heightmap ``levels`` [height, width] on ``grid`` (lattice.Lattice) with its
    ``detail`` (decode, or None), as the page reads them: lattice.read, and in a quad with detail the triangle rule on its
    sub-grid. NaN more than half a node outside the grid."""
    out = lattice.read(levels, grid, xs, ys)
    if detail is None:
        return out
    factor, unit, flags, values = detail
    rows, cols = levels.shape
    col, row = lattice.to_grid(grid, xs, ys)
    col, row = np.clip(col, 0, cols - 1), np.clip(row, 0, rows - 1)
    r0 = np.minimum(np.floor(row), rows - 2).astype(np.int64)
    c0 = np.minimum(np.floor(col), cols - 2).astype(np.int64)
    fine = np.isfinite(out) & flags[r0, c0]
    if not fine.any():
        return out
    r0, c0, row, col = r0[fine], c0[fine], row[fine], col[fine]
    rank = np.cumsum(flags.reshape(-1)) - 1
    quad_values = values[rank[r0 * (cols - 1) + c0]]
    nodes = np.empty((len(r0), factor + 1, factor + 1), np.float64)
    corners = levels.astype(np.float64)
    nodes[:, 0, 0], nodes[:, 0, factor] = corners[r0, c0], corners[r0, c0 + 1]
    nodes[:, factor, 0], nodes[:, factor, factor] = corners[r0 + 1, c0], corners[r0 + 1, c0 + 1]
    inner = predicted(levels, r0, c0, factor) + quad_values * unit
    for k, (i, j) in enumerate(inner_nodes(factor)):
        nodes[:, i, j] = inner[:, k]
    sr, sc = (row - r0) * factor, (col - c0) * factor
    i0 = np.minimum(np.floor(sr), factor - 1).astype(np.int64)
    j0 = np.minimum(np.floor(sc), factor - 1).astype(np.int64)
    rw, cw = sr - i0, sc - j0
    n = np.arange(len(r0))
    corner, right = nodes[n, i0, j0], nodes[n, i0, j0 + 1]
    below, diagonal = nodes[n, i0 + 1, j0], nodes[n, i0 + 1, j0 + 1]
    out[fine] = np.where(cw >= rw, corner + (right - corner) * cw + (diagonal - right) * rw,
                         corner + (below - corner) * rw + (diagonal - below) * cw)
    return out


def points(directory, count, seed=5):
    """[[x, y, z], ...]: ``count`` random world points in the quads with detail of the heightmap folder ``directory`` and the
    height (metres) ``read`` gives there from its heightmap.webp and detail, or [] without detail."""
    with open(os.path.join(directory, "meta.json")) as f:
        meta = json.load(f)
    detail = load(directory, meta)
    if detail is None:
        return []
    levels = heightmap_webp.decode(os.path.join(directory, meta["webp"]["file"]))
    grid = lattice.from_meta(meta)
    rng = np.random.default_rng(seed)
    quads = rng.choice(np.flatnonzero(detail[2]), count)
    rows, cols = np.divmod(quads, grid.width - 1)
    xs, ys = (np.round(v, 4) for v in lattice.to_world(grid, cols + rng.uniform(0, 1, count), rows + rng.uniform(0, 1, count)))
    zs = read(levels, grid, detail, xs, ys) * meta["webp"]["z_step_m"] + meta["z_min_m"]
    return [[float(x), float(y), float(z)] for x, y, z in zip(xs, ys, zs)]


if __name__ == "__main__":
    root, out = sys.argv[1], sys.argv[2]
    found = {slug: points(os.path.join(root, slug), POINTS) for slug in sys.argv[3:]}
    with open(out, "w") as f:
        json.dump(found, f)
    print(json.dumps({slug: len(p) for slug, p in found.items()}))
