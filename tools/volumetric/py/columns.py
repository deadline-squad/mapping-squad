"""Sparse voxel columns: the volumetric collision of a map as occupied (x, y, z) cells.

A voxel is occupied when a collision triangle of the chosen query class has a sample point inside it. Points
are laid on every triangle on a barycentric lattice no coarser than ``SAMPLE_FRACTION`` of the smallest voxel
edge, so thin walls and sheet-like roofs mark the voxels they cross (a heightmap cannot hold them) and
nothing needs a closed or consistently wound mesh. Each sample also records which way its triangle faces
(up: floor-like, normal.z > FLOOR_NORMAL_Z; down: ceiling-like; else wall-like) so floors can be listed.

Voxel key = ((row * width + col) << Z_BITS) | z_index with z_index = floor((z - z_min) / dz), the column
number row * width + col, and the facing kept apart in ``facing_keys``.
"""

import numpy as np

Z_BITS = 12
SAMPLE_FRACTION = 0.45
FLOOR_NORMAL_Z = 0.5
CLIP_DIVISIONS = 1000
CLIP_MARGIN_M = 1e-3
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


def surface_samples(tris, spacing, max_points=4_000_000, box=None):
    """Yield (points [m, 3] float64, facing [m] int8) covering the triangles `tris` [n, 3, 3].

    A triangle whose longest edge is L gets the lattice with n = ceil(L / spacing) divisions per edge
    points (i, j), i <= j, i + j <= n, at a + (i / n) (b - a) + (j / n) (c - a); triangles with equal n are generated
    together.

    `box` = (low, high) corners (see `Grid.box`) limits the work to what can matter: a triangle whose bounding box
    misses the box is skipped, and a triangle with more than CLIP_DIVISIONS divisions yields only the lattice points
    within CLIP_MARGIN_M of the box (the points are the same ones the full lattice has, computed with the same
    arithmetic). Points outside the box are not guaranteed to be absent, so callers still filter them.
    """
    t = tris.astype(np.float64)
    if box is not None:
        low, high = box
        t = t[~np.any((t.max(axis=1) < low - CLIP_MARGIN_M) | (t.min(axis=1) >= high + CLIP_MARGIN_M), axis=1)]
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    normal = np.cross(b - a, c - a)
    length = np.linalg.norm(normal, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        nz = np.where(length > 0, normal[:, 2] / length, 0.0)
    facing = np.where(nz > FLOOR_NORMAL_Z, UP, np.where(nz < -FLOOR_NORMAL_Z, DOWN, WALL)).astype(np.int8)
    longest = np.maximum.reduce([np.linalg.norm(b - a, axis=1), np.linalg.norm(c - b, axis=1), np.linalg.norm(a - c, axis=1)])
    divisions = np.maximum(1, np.ceil(longest / spacing)).astype(np.int64)
    if box is not None:
        for k in np.nonzero(divisions > CLIP_DIVISIONS)[0]:
            yield from _clipped_lattice(a[k], b[k], c[k], divisions[k], facing[k], box, max_points)
        divisions = np.where(divisions > CLIP_DIVISIONS, 0, divisions)
    for n in np.unique(divisions[divisions > 0]):
        index = np.nonzero(divisions == n)[0]
        i, j = np.triu_indices(n + 1)
        keep = i + j <= n
        u, v = (i[keep] / n)[None, :, None], (j[keep] / n)[None, :, None]
        per = u.shape[1]
        step = max(1, max_points // per)
        for start in range(0, len(index), step):
            sel = index[start:start + step]
            p = a[sel][:, None, :] + u * (b[sel] - a[sel])[:, None, :] + v * (c[sel] - a[sel])[:, None, :]
            yield p.reshape(-1, 3), np.repeat(facing[sel], per)


def _clipped_lattice(a, b, c, n, facing, box, max_points):
    """Lattice points a + (i / n) (b - a) + (j / n) (c - a), i <= j, i + j <= n, within CLIP_MARGIN_M of `box`.

    These are the points the unclipped path generates (np.triu_indices keeps i <= j).

    Row j of the lattice is a line, so the i that stay inside the box on each axis form an interval; the rows are
    intersected axis by axis and widened by one step against rounding. Yields chunks of at most `max_points` points
    (a single row is never split).
    """
    low, high = box
    edge_u, edge_v = b - a, c - a
    rows = np.arange(n + 1)
    first, last = np.zeros(n + 1), np.minimum(rows, n - rows).astype(np.float64)
    for axis in range(3):
        start = a[axis] + rows / n * edge_v[axis]
        if edge_u[axis] == 0:
            outside = (start < low[axis] - CLIP_MARGIN_M) | (start >= high[axis] + CLIP_MARGIN_M)
            last = np.where(outside, -1.0, last)
            continue
        ends = np.sort([(low[axis] - CLIP_MARGIN_M - start) / edge_u[axis], (high[axis] + CLIP_MARGIN_M - start) / edge_u[axis]], axis=0)
        first = np.maximum(first, np.floor(ends[0] * n) - 1)
        last = np.minimum(last, np.ceil(ends[1] * n) + 1)
    first = np.clip(first, 0, n + 1).astype(np.int64)
    counts = np.maximum(np.clip(last, -1, n).astype(np.int64) - first + 1, 0)
    cumulative = np.cumsum(counts)
    row = 0
    while row <= n:
        before = cumulative[row - 1] if row else 0
        stop = min(n + 1, max(row + 1, int(np.searchsorted(cumulative, before + max_points, side="right"))))
        span = slice(row, stop)
        row, total = stop, int(counts[span].sum())
        if total == 0:
            continue
        j = np.repeat(rows[span], counts[span])
        offset = np.arange(total) - np.repeat(np.cumsum(counts[span]) - counts[span], counts[span])
        i = np.repeat(first[span], counts[span]) + offset
        yield a + (i / n)[:, None] * edge_u + (j / n)[:, None] * edge_v, np.full(total, facing, np.int8)


def build_keys(tris_iter, grid, chunk=1_000_000):
    """Occupied voxel keys and, aligned by facing, the sorted unique (key, facing) pairs of the triangles.

    `tris_iter` yields float32 [n, 3, 3] arrays. Returns (occupied keys, up-facing keys, down-facing keys),
    each a sorted unique int64 array.
    """
    spacing = SAMPLE_FRACTION * min(grid.cell, grid.dz)
    buckets = {UP: [], DOWN: [], WALL: []}
    for tris in tris_iter:
        for start in range(0, len(tris), chunk):
            for points, facing in surface_samples(tris[start:start + chunk], spacing, box=grid.box()):
                keys, valid = grid.keys(points[:, 0], points[:, 1], points[:, 2])
                for kind in buckets:
                    sel = valid & (facing == kind)
                    if sel.any():
                        buckets[kind].append(np.unique(keys[sel]))
        for kind, parts in buckets.items():
            if len(parts) > 16:
                buckets[kind] = [np.unique(np.concatenate(parts))]
    merged = {kind: (np.unique(np.concatenate(parts)) if parts else np.empty(0, np.int64)) for kind, parts in buckets.items()}
    occupied = np.unique(np.concatenate(list(merged.values())))
    return occupied, merged[UP], merged[DOWN]
