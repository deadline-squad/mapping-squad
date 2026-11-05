"""Sparse voxel columns: the volumetric collision of a map as occupied (x, y, z) cells.

A voxel is occupied when a collision triangle of the chosen query class intersects it (conservative surface
voxelisation: every voxel the triangle passes through is marked, however small the part of the triangle inside
it, vertices and edges included), so thin walls and sheet-like roofs mark the voxels they cross (a heightmap
cannot hold them) and nothing needs a closed or consistently wound mesh. A voxel is the half-open box
[low, high) on every axis, the same cell ``Grid.keys`` assigns a point to, so a triangle lying exactly on a
voxel face belongs to the voxel above/beside it only. Each triangle also records which way it faces
(up: floor-like, normal.z > FLOOR_NORMAL_Z; down: ceiling-like; else wall-like) so floors can be listed.

Voxel key = ((row * width + col) << Z_BITS) | z_index with z_index = floor((z - z_min) / dz), the column
number row * width + col, and the facing kept apart in ``facing_keys``.
"""

import numpy as np

Z_BITS = 12
FLOOR_NORMAL_Z = 0.5
HIGH_EDGE_M = 1e-9
TOLERANCE = 1e-11
UP, DOWN, WALL = 1, 2, 0


class Grid:
    """Geometry of the voxel grid: origin in metres, horizontal cell edge, vertical step, columns and rows."""

    def __init__(self, min_x, min_y, width_m, height_m, cell, dz, z_min):
        self.min_x, self.min_y, self.cell, self.dz, self.z_min = min_x, min_y, cell, dz, z_min
        self.width = int(np.ceil(width_m / cell))
        self.height = int(np.ceil(height_m / cell))

    def box(self):
        """(low, high) corners in metres of the region where `keys` is valid: low <= point < high on every axis."""
        low = np.array([self.min_x, self.min_y, self.z_min], np.float64)
        return low, low + np.array([self.width * self.cell, self.height * self.cell, (1 << Z_BITS) * self.dz])

    def keys(self, x, y, z):
        """Voxel keys of world points (metres) and a validity mask (inside the grid)."""
        col = np.floor((x - self.min_x) / self.cell).astype(np.int64)
        row = np.floor((y - self.min_y) / self.cell).astype(np.int64)
        zi = np.floor((z - self.z_min) / self.dz).astype(np.int64)
        valid = (col >= 0) & (col < self.width) & (row >= 0) & (row < self.height) & (zi >= 0) & (zi < (1 << Z_BITS))
        return ((row * self.width + col) << Z_BITS) | np.clip(zi, 0, (1 << Z_BITS) - 1), valid

    def voxel_center(self, keys):
        """World (x, y, z) of the centres of voxel keys."""
        zi = keys & ((1 << Z_BITS) - 1)
        column = keys >> Z_BITS
        return ((column % self.width + 0.5) * self.cell + self.min_x,
                (column // self.width + 0.5) * self.cell + self.min_y,
                (zi + 0.5) * self.dz + self.z_min)


def _edge_cut(p, q, axis, value):
    """Where the segment p -> q crosses the plane coordinate[axis] == value: (t in [0, 1] clamped, crosses mask)."""
    delta = q[:, axis] - p[:, axis]
    moving = delta != 0
    t = np.where(moving, (value - p[:, axis]) / np.where(moving, delta, 1.0), -1.0)
    return np.clip(t, 0.0, 1.0), moving & (t >= -TOLERANCE) & (t <= 1 + TOLERANCE)


def _extent(a, b, c, bounds, report):
    """Range of coordinate `report` over the part of triangle (a, b, c) inside the slab or rectangle `bounds`.

    `bounds` maps an axis (0: x, 1: y) to its (low, high) limits; the triangle is cut by those limits and the extreme
    values are searched among the vertices of the cut polygon: triangle vertices inside, intersections of the edges
    with the limits, and (for a rectangle, two axes) the rectangle corners inside the triangle's projection. Returns (low, high, hit); where hit is
    False the triangle misses the region and low/high are meaningless.
    """
    n = len(a)
    low, high = np.full(n, np.inf), np.full(n, -np.inf)
    verts = (a, b, c)

    def inside(points):
        ok = np.ones(len(points), bool)
        for axis, (lo, hi) in bounds.items():
            ok &= (points[:, axis] >= lo - TOLERANCE) & (points[:, axis] <= hi + TOLERANCE)
        return ok

    def take(values, ok):
        np.minimum(low, np.where(ok, values, np.inf), out=low)
        np.maximum(high, np.where(ok, values, -np.inf), out=high)

    for v in verts:
        take(v[:, report], inside(v))
    for p, q in ((a, b), (b, c), (c, a)):
        for axis, limits in bounds.items():
            for limit in limits:
                t, crosses = _edge_cut(p, q, axis, limit)
                point = p + t[:, None] * (q - p)
                point[:, axis] = limit
                take(point[:, report], crosses & inside(point))
    if len(bounds) == 2:
        e1, e2 = (b - a)[:, :2], (c - a)[:, :2]
        d = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
        scale = np.linalg.norm(e1, axis=1) * np.linalg.norm(e2, axis=1)
        usable = np.abs(d) > 1e-10 * scale
        safe = np.where(usable, d, 1.0)
        for x in bounds[0]:
            for y in bounds[1]:
                w = np.stack([x - a[:, 0], y - a[:, 1]], axis=1)
                u = (w[:, 0] * e2[:, 1] - w[:, 1] * e2[:, 0]) / safe
                v = (e1[:, 0] * w[:, 1] - e1[:, 1] * w[:, 0]) / safe
                covered = usable & (u >= -1e-12) & (v >= -1e-12) & (u + v <= 1 + 1e-12)
                take(a[:, 2] + u * (b - a)[:, 2] + v * (c - a)[:, 2], covered)
    return low, high, low <= high


def surface_voxels(tris, grid, max_pairs=1_000_000):
    """Yield (keys [m] int64, facing [m] int8) of every voxel of `grid` that a triangle of `tris` [n, 3, 3] intersects.

    Exact, so conservative: a voxel is listed when the triangle and the half-open voxel box share a point (the
    high faces are pulled in by HIGH_EDGE_M). Per triangle: (1) every grid row its y-extent touches; (2) in each
    row, the columns between the x-extent of the triangle cut by that row's slab (a superset of the touched cells,
    narrow even for a huge diagonal triangle); (3) per candidate cell, the z-range of the triangle cut by the cell's
    rectangle (the cut polygon is convex, so every z step inside the range is crossed). Work follows the voxels
    produced: a triangle outside the grid costs nothing and one covering the grid costs one pass over its cells.
    Keys may repeat across and within chunks; no chunk holds more than about `max_pairs` (triangle, cell) pairs or
    keys.
    """
    low, high = grid.box()
    t = tris.astype(np.float64)
    t = t[~np.any((t.max(axis=1) < low) | (t.min(axis=1) >= high), axis=1)]
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    normal = np.cross(b - a, c - a)
    length = np.linalg.norm(normal, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        nz = np.where(length > 0, normal[:, 2] / length, 0.0)
    facing = np.where(nz > FLOOR_NORMAL_Z, UP, np.where(nz < -FLOOR_NORMAL_Z, DOWN, WALL)).astype(np.int8)
    row_first = np.clip(np.floor((t[:, :, 1].min(axis=1) - grid.min_y) / grid.cell), 0, grid.height - 1).astype(np.int64)
    row_last = np.clip(np.floor((t[:, :, 1].max(axis=1) - grid.min_y) / grid.cell), 0, grid.height - 1).astype(np.int64)
    row_count = row_last - row_first + 1
    row_end = np.cumsum(row_count)
    start = 0
    while start < len(t):
        before = row_end[start - 1] if start else 0
        stop = max(start + 1, int(np.searchsorted(row_end, before + max_pairs, side="right")))
        tri = np.repeat(np.arange(start, stop), row_count[start:stop])
        row = row_first[tri] + np.arange(len(tri)) - np.repeat(np.cumsum(row_count[start:stop]) - row_count[start:stop], row_count[start:stop])
        start = stop
        y_low = grid.min_y + row * grid.cell
        x_low, x_high, hit = _extent(a[tri], b[tri], c[tri], {1: (y_low, y_low + grid.cell - HIGH_EDGE_M)}, 0)
        hit &= (x_high >= grid.min_x) & (x_low < grid.min_x + grid.width * grid.cell)
        tri, row, x_low, x_high = tri[hit], row[hit], x_low[hit], x_high[hit]
        col_first = np.clip(np.floor((x_low - grid.min_x) / grid.cell), 0, grid.width - 1).astype(np.int64)
        col_last = np.clip(np.floor((x_high - grid.min_x) / grid.cell), 0, grid.width - 1).astype(np.int64)
        col_count = col_last - col_first + 1
        col_end = np.cumsum(col_count)
        first = 0
        while first < len(tri):
            before = col_end[first - 1] if first else 0
            last = max(first + 1, int(np.searchsorted(col_end, before + max_pairs, side="right")))
            yield from _cell_voxels(grid, a, b, c, facing, tri[first:last], row[first:last], col_first[first:last], col_count[first:last], max_pairs)
            first = last


def _cell_voxels(grid, a, b, c, facing, tri, row, col_first, col_count, max_pairs):
    """Voxels of the cells (row, col_first .. col_first + col_count - 1) that triangles `tri` intersect: see `surface_voxels`."""
    ends = np.cumsum(col_count)
    pair_tri = np.repeat(tri, col_count)
    pair_row = np.repeat(row, col_count)
    col = np.repeat(col_first, col_count) + np.arange(ends[-1]) - np.repeat(ends - col_count, col_count)
    x_low, y_low = grid.min_x + col * grid.cell, grid.min_y + pair_row * grid.cell
    bounds = {0: (x_low, x_low + grid.cell - HIGH_EDGE_M), 1: (y_low, y_low + grid.cell - HIGH_EDGE_M)}
    z_low, z_high, hit = _extent(a[pair_tri], b[pair_tri], c[pair_tri], bounds, 2)
    z_first = np.floor((z_low[hit] - grid.z_min) / grid.dz).astype(np.int64)
    z_last = np.floor((z_high[hit] - grid.z_min) / grid.dz).astype(np.int64)
    z_first, z_last = np.maximum(z_first, 0), np.minimum(z_last, (1 << Z_BITS) - 1)
    count = np.maximum(z_last - z_first + 1, 0)
    column = (pair_row[hit] * grid.width + col[hit]) << Z_BITS
    kind = facing[pair_tri[hit]]
    cumulative = np.cumsum(count)
    start = 0
    while start < len(count):
        before = cumulative[start - 1] if start else 0
        stop = max(start + 1, int(np.searchsorted(cumulative, before + max_pairs, side="right")))
        span = count[start:stop]
        offset = np.arange(span.sum()) - np.repeat(np.cumsum(span) - span, span)
        yield column[start:stop].repeat(span) | (z_first[start:stop].repeat(span) + offset), kind[start:stop].repeat(span)
        start = stop


FACING_BITS = 2
MERGE_MIN_KEYS = 8_000_000


def _union(known, fresh):
    """Sorted unique union of two sorted unique int64 arrays, built with one copy of `known` (no concatenate and re-sort)."""
    if len(known) == 0:
        return fresh
    at = np.searchsorted(known, fresh)
    new = known[np.minimum(at, len(known) - 1)] != fresh
    return np.insert(known, at[new], fresh[new])


def build_keys(tris_iter, grid, chunk=1_000_000, keep=None):
    """Occupied voxel keys and the voxel keys of the up- and down-facing triangles.

    `tris_iter` yields float32 [n, 3, 3] arrays. Returns (occupied keys, up-facing keys, down-facing keys),
    each a sorted unique int64 array.

    `keep`, when given, maps an array of voxel keys to a boolean mask of the voxels to retain. It is applied to each
    block as it arrives, so voxels it rejects (for example those under the terrain, which on a large map are most of
    them) never take part in the accumulation. It must depend on the key alone: the result then equals filtering the
    returned arrays afterwards.

    Memory is bounded by the number of distinct voxels, not by the voxels yielded (a map has hundreds of millions of
    duplicates): every (key, facing) pair is packed into one int64, ``key << FACING_BITS | facing``, deduplicated per
    block, collected until about max(MERGE_MIN_KEYS, a quarter of the known pairs) are pending, and only then merged
    into the sorted unique array of known pairs.
    """
    known = np.empty(0, np.int64)
    pending, pending_keys = [], 0
    for tris in tris_iter:
        for start in range(0, len(tris), chunk):
            for keys, facing in surface_voxels(tris[start:start + chunk], grid):
                packed = np.unique((keys << FACING_BITS) | facing)
                if keep is not None:
                    packed = packed[keep(packed >> FACING_BITS)]
                pending.append(packed)
                pending_keys += len(packed)
                if pending_keys >= max(MERGE_MIN_KEYS, len(known) // 4):
                    known = _union(known, np.unique(np.concatenate(pending)))
                    pending, pending_keys = [], 0
    if pending:
        known = _union(known, np.unique(np.concatenate(pending)))
    keys, facing = known >> FACING_BITS, known & ((1 << FACING_BITS) - 1)
    first_of_key = np.ones(len(keys), bool)
    first_of_key[1:] = keys[1:] != keys[:-1]
    return keys[first_of_key], keys[facing == UP], keys[facing == DOWN]
