"""Line-of-sight models compared by eval_los.py: the status-quo top-surface heightmap and the voxel columns.

Both march a segment at a fixed step and report whether it is blocked. The landscape is shared (bilinear
1 m grid, holes do not block) so the comparison isolates what objects add.
"""

import numpy as np
from scipy.ndimage import map_coordinates

import columns


class Landscape:
    """Landscape heights z [rows, cols] on a 1 m grid whose [0, 0] is at (min_x, min_y); holes do not block."""

    def __init__(self, z, hole, min_x, min_y):
        self.z, self.hole, self.min_x, self.min_y = z, hole, min_x, min_y

    def height(self, x, y):
        coords = [y - self.min_y, x - self.min_x]
        return map_coordinates(self.z, coords, order=1, mode="nearest")

    def blocks(self, x, y, z):
        near = self.hole[np.clip(np.rint(y - self.min_y).astype(int), 0, self.hole.shape[0] - 1),
                         np.clip(np.rint(x - self.min_x).astype(int), 0, self.hole.shape[1] - 1)]
        return (z < self.height(x, y)) & ~near


def march(p0, p1, step):
    n = max(2, int(np.ceil(np.linalg.norm(np.asarray(p1) - np.asarray(p0)) / step)) + 1)
    t = np.linspace(0, 1, n)[:, None]
    pts = np.asarray(p0, float)[None, :] + t * (np.asarray(p1, float) - np.asarray(p0, float))[None, :]
    return pts[:, 0], pts[:, 1], pts[:, 2]


class HeightmapModel:
    """Status quo: one top-surface height per 1 m cell (nearest cell); blocked when the ray is below it."""

    def __init__(self, top, min_x, min_y, step=0.5):
        self.top, self.min_x, self.min_y, self.step = top, min_x, min_y, step

    def blocked(self, p0, p1):
        x, y, z = march(p0, p1, self.step)
        col = np.clip(np.floor(x - self.min_x).astype(int), 0, self.top.shape[1] - 1)
        row = np.clip(np.floor(y - self.min_y).astype(int), 0, self.top.shape[0] - 1)
        return bool((z < self.top[row, col]).any())


class VoxelModel:
    """Landscape plus occupied voxels (sorted int64 keys, columns.Grid). The ray is sampled every cell/3."""

    def __init__(self, landscape, grid, occupied):
        self.landscape, self.grid, self.occupied = landscape, grid, occupied
        self.step = min(grid.cell, grid.dz) / 3

    def first_block_m(self, p0, p1):
        """Distance along the segment to the first blocked sample, or None when clear."""
        x, y, z = march(p0, p1, self.step)
        hit = self.landscape.blocks(x, y, z)
        keys, valid = self.grid.keys(x, y, z)
        pos = np.minimum(np.searchsorted(self.occupied, keys), len(self.occupied) - 1)
        hit |= valid & (self.occupied[pos] == keys)
        if not hit.any():
            return None
        return float(np.argmax(hit)) / (len(x) - 1) * float(np.linalg.norm(np.asarray(p1) - np.asarray(p0)))

    def blocked(self, p0, p1):
        return self.first_block_m(p0, p1) is not None
