"""build_keys marks every voxel a triangle intersects. Run: python -m unittest discover tests (from tools/volumetric)."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py"))

import columns  # noqa: E402


def grid():
    """40 x 30 m of 0.5 m columns, 0.25 m steps from z = 0 (the z range ends at 4096 * 0.25 m)."""
    return columns.Grid(-20.0, -15.0, 40.0, 30.0, 0.5, 0.25, 0.0)


def overlapping_voxels(triangle, g):
    """Keys of the voxels sharing a point with `triangle` [3, 3]: separating-axis test (Akenine-Moeller) on every
    voxel of the triangle's bounding box inside the grid, independent of columns.py."""
    low = np.floor((triangle.min(axis=0) - [g.min_x, g.min_y, g.z_min]) / [g.cell, g.cell, g.dz]).astype(np.int64)
    high = np.floor((triangle.max(axis=0) - [g.min_x, g.min_y, g.z_min]) / [g.cell, g.cell, g.dz]).astype(np.int64)
    low, high = np.maximum(low, 0), np.minimum(high, [g.width - 1, g.height - 1, (1 << columns.Z_BITS) - 1])
    if np.any(high < low):
        return np.empty(0, np.int64)
    index = np.stack(np.meshgrid(*[np.arange(l, h + 1) for l, h in zip(low, high)], indexing="ij"), -1).reshape(-1, 3)
    half = np.array([g.cell, g.cell, g.dz]) / 2
    centre = np.array([g.min_x, g.min_y, g.z_min]) + (index + 0.5) * [g.cell, g.cell, g.dz]
    v = triangle[None] - centre[:, None]
    slack = 1e-9
    separated = np.zeros(len(index), bool)
    for axis in range(3):
        separated |= (v[:, :, axis].min(axis=1) > half[axis] + slack) | (v[:, :, axis].max(axis=1) < -half[axis] - slack)
    normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
    separated |= np.abs(v[:, 0] @ normal) > half @ np.abs(normal) + slack
    for edge in (triangle[1] - triangle[0], triangle[2] - triangle[1], triangle[0] - triangle[2]):
        for unit in np.eye(3):
            axis = np.cross(edge, unit)
            projected = v @ axis
            reach = half @ np.abs(axis)
            separated |= (projected.min(axis=1) > reach + slack) | (projected.max(axis=1) < -reach - slack)
    index = index[~separated]
    return (((index[:, 1] * g.width + index[:, 0]) << columns.Z_BITS) | index[:, 2])


def random_triangles(count, scale, seed):
    """Triangles of random size and tilt that straddle, cover or miss the grid."""
    rng = np.random.default_rng(seed)
    centre = rng.uniform([-30, -25, -5], [30, 25, 40], (count, 1, 3))
    return (centre + rng.normal(0, scale, (count, 3, 3))).astype(np.float32)


def voxel_set(tris, g):
    return columns.build_keys([np.asarray(tris, np.float32)], g)[0]


class ConservativeVoxelsTest(unittest.TestCase):
    def assert_exact(self, tris):
        g = grid()
        tris = np.asarray(tris, np.float32)
        got = voxel_set(tris, g)
        want = np.unique(np.concatenate([overlapping_voxels(t.astype(np.float64), g) for t in tris]))
        np.testing.assert_array_equal(got, want)

    def test_small_triangles_match_the_exact_overlap_test(self):
        self.assert_exact(random_triangles(300, 3.0, 1))

    def test_large_triangles_match_the_exact_overlap_test(self):
        self.assert_exact(random_triangles(25, 40.0, 2))

    def test_axis_parallel_triangles_match_the_exact_overlap_test(self):
        self.assert_exact([[[-60, -50, 3.1], [70, -40, 3.1], [-10, 60, 3.1]], [[-50, -50.013, 12.3], [50, -50.013, 12.3], [50, 50.217, 12.3]],
                           [[-5.1, -40, -2], [-5.1, 50, -2], [-5.1, 5.013, 30]], [[0.1, -40, 4], [0.1001, 50, 4], [0.1, 5.013, 60]]])

    def test_vertex_in_an_otherwise_untouched_voxel_is_marked(self):
        g = grid()
        # a and c sit in column 40; b pokes 5 mm into column 41 at one height: only b reaches voxel (41, 30, 0).
        tri = [[0.1, 0.1, 0.1], [0.505, 0.25, 0.1], [0.1, 0.4, 0.1]]
        voxels = voxel_set([tri], g)
        b_voxel, _ = g.keys(np.array([0.505]), np.array([0.25]), np.array([0.1]))
        self.assertIn(b_voxel[0], voxels)
        self.assertEqual(len(voxels), 2)
        self.assert_exact([tri])

    def test_every_vertex_voxel_is_marked(self):
        g = grid()
        tris = random_triangles(500, 1.5, 3)
        voxels = set(voxel_set(tris, g))
        for corner in range(3):
            keys, valid = g.keys(*tris[:, corner].astype(np.float64).T)
            self.assertTrue(all(key in voxels for key in keys[valid]))

    def test_voxel_only_the_unsampled_half_of_the_lattice_reaches_is_marked(self):
        # Found by search: the old i <= j half-lattice marks the vertex voxels of this triangle but misses a fifth voxel.
        self.assert_exact([[[2.0957, -1.069, 1.7898], [2.0857, -0.584, 1.9811], [1.2913, -0.5589, 1.9801]]])

    def test_flat_triangle_on_a_voxel_face_belongs_to_the_voxel_above(self):
        g = grid()
        floor = [[1.0, 1.0, 1.0], [3.0, 1.0, 1.0], [1.0, 3.0, 1.0]]
        z_index = np.unique(voxel_set([floor], g) & ((1 << columns.Z_BITS) - 1))
        np.testing.assert_array_equal(z_index, [4])

    def test_wall_on_a_column_boundary_belongs_to_the_column_beside_it(self):
        g = grid()
        wall = [[2.0, 1.0, 0.1], [2.0, 3.0, 0.1], [2.0, 2.0, 0.6]]
        columns_hit = np.unique((voxel_set([wall], g) >> columns.Z_BITS) % g.width)
        np.testing.assert_array_equal(columns_hit, [int((2.0 - g.min_x) / g.cell)])

    def test_up_and_down_facing_are_kept_apart(self):
        g = grid()
        up = [[1.0, 1.0, 1.1], [3.0, 1.0, 1.1], [1.0, 3.0, 1.1]]
        occupied, up_keys, down_keys = columns.build_keys([np.asarray([up, up[::-1]], np.float32)], g)
        np.testing.assert_array_equal(up_keys, occupied)
        np.testing.assert_array_equal(down_keys, occupied)

    def test_triangle_far_outside_the_grid_costs_nothing(self):
        g = grid()
        far = np.array([[[20000, 40000, 5], [24000, 42000, 5], [29000, 41000, 5]]], np.float32)
        self.assertEqual(list(columns.surface_voxels(far, g)), [])

    def test_huge_triangle_covering_the_grid_stays_bounded(self):
        g = grid()
        plane = np.array([[[-3000, -3000, 2], [3000, -3000, 2], [0, 3000, 2]]], np.float32)
        occupied, up, down = columns.build_keys([plane], g)
        self.assertEqual(len(occupied), g.width * g.height)
        np.testing.assert_array_equal(up, occupied)
        self.assertEqual(len(down), 0)
        self.assertLess(max(len(keys) for keys, _ in columns.surface_voxels(plane, g, max_pairs=1000)), 2000)

    def test_triangle_above_the_z_range_is_skipped(self):
        g = grid()
        tall = np.array([[[0, 0, 5000], [3, 0, 5000], [0, 3, 5000]]], np.float32)
        occupied, up, down = columns.build_keys([tall], g)
        self.assertEqual((len(occupied), len(up), len(down)), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
