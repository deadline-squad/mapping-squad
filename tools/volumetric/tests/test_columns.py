"""build_keys clips triangles to the grid: same voxels as the full lattice, none of the work outside. Run: python -m unittest discover tests (from tools/volumetric)."""

import os
import sys
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py"))

import columns  # noqa: E402


def grid():
    """40 x 30 m of 0.5 m columns, 0.25 m steps from z = 0 (the z range ends at 4096 * 0.25 m)."""
    return columns.Grid(-20.0, -15.0, 40.0, 30.0, 0.5, 0.25, 0.0)


def dense_keys(tris, g):
    """The unclipped lattice of every triangle (no box), reduced the way build_keys does."""
    spacing = columns.SAMPLE_FRACTION * min(g.cell, g.dz)
    parts = {columns.UP: [], columns.DOWN: [], columns.WALL: []}
    for points, facing in columns.surface_samples(tris, spacing):
        keys, valid = g.keys(points[:, 0], points[:, 1], points[:, 2])
        for kind, found in parts.items():
            found.append(keys[valid & (facing == kind)])
    merged = {kind: np.unique(np.concatenate(found)) for kind, found in parts.items()}
    return np.unique(np.concatenate(list(merged.values()))), merged[columns.UP], merged[columns.DOWN]


def random_triangles(count, scale, seed):
    """Triangles of random size and tilt that straddle, cover or miss the grid."""
    rng = np.random.default_rng(seed)
    centre = rng.uniform([-30, -25, -5], [30, 25, 40], (count, 1, 3))
    return (centre + rng.normal(0, scale, (count, 3, 3))).astype(np.float32)


class ClippedKeysTest(unittest.TestCase):
    def assert_same_as_dense(self, tris):
        g = grid()
        for got, want in zip(columns.build_keys([tris], g), dense_keys(tris, g)):
            np.testing.assert_array_equal(got, want)

    def test_small_triangles_match_the_full_lattice(self):
        self.assert_same_as_dense(random_triangles(300, 3.0, 1))

    def test_clipped_large_triangles_match_the_full_lattice(self):
        tris = random_triangles(25, 40.0, 2)
        longest = max(np.linalg.norm(t[i] - t[(i + 1) % 3]) for t in tris for i in range(3))
        self.assertGreater(longest / (columns.SAMPLE_FRACTION * 0.25), columns.CLIP_DIVISIONS)
        self.assert_same_as_dense(tris)

    def test_axis_parallel_large_triangles_match_the_full_lattice(self):
        floor = np.array([[[-60, -50, 3], [70, -40, 3], [-10, 60, 3]], [[-50, -50, 12.5], [50, -50, 12.5], [50, 50, 12.5]]], np.float32)
        wall = np.array([[[-5, -40, -2], [-5, 50, -2], [-5, 5, 30]], [[0, -40, 4], [0.0001, 50, 4], [0, 5, 60]]], np.float32)
        self.assert_same_as_dense(floor)
        self.assert_same_as_dense(wall)

    def test_triangle_far_outside_the_grid_costs_no_samples(self):
        g = grid()
        inside = np.array([[[0, 0, 1], [3, 0, 1], [0, 3, 1]]], np.float32)
        far = np.array([[[20000, 40000, 5], [24000, 42000, 5], [29000, 41000, 5]]], np.float32)
        with mock.patch.object(g, "keys", wraps=g.keys) as keys:
            got = columns.build_keys([np.concatenate([inside, far])], g)
        for found, want in zip(got, columns.build_keys([inside], g)):
            np.testing.assert_array_equal(found, want)
        self.assertLess(sum(len(call.args[0]) for call in keys.call_args_list), 100_000)

    def test_huge_triangle_covering_the_grid_stays_bounded(self):
        g = grid()
        plane = np.array([[[-3000, -3000, 2], [3000, -3000, 2], [0, 3000, 2]]], np.float32)
        with mock.patch.object(g, "keys", wraps=g.keys) as keys:
            occupied, up, down = columns.build_keys([plane], g)
        self.assertEqual(len(occupied), g.width * g.height)
        np.testing.assert_array_equal(up, occupied)
        self.assertEqual(len(down), 0)
        self.assertLess(max(len(call.args[0]) for call in keys.call_args_list), 5_000_000)

    def test_triangle_above_the_z_range_is_skipped(self):
        g = grid()
        tall = np.array([[[0, 0, 5000], [3, 0, 5000], [0, 3, 5000]]], np.float32)
        occupied, up, down = columns.build_keys([tall], g)
        self.assertEqual((len(occupied), len(up), len(down)), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
