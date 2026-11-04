"""RTRI1 region files and their selection of triangles. Run: python -m unittest discover tests (from tools/volumetric).

The fixture of the engine's tests (`engine/tests/data/wall.rtri`) is written by `write_fixture`:
    python -c "import sys; sys.path.insert(0, 'tests'); import test_region; test_region.write_fixture(sys.argv[1])" <path>
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py"))

import build_region  # noqa: E402
import columns  # noqa: E402

WALL = np.array([[[-10, 299.8, -10], [10, 299.8, -10], [0, 299.8, 400]]], np.float32)
SQUARE = (-20.0, 250.0, 20.0, 350.0)


def write_fixture(path):
    """The wall of the engine's CLI test: one triangle across the line of fire at y = 299.8."""
    open(path, "wb").write(build_region.encode(WALL, SQUARE, 0.6))


def grid():
    """0.5 m x 0.25 m columns over 100 x 100 m starting at the origin, z from 0."""
    return columns.Grid(0, 0, 100, 100, 0.5, 0.25, 0.0)


def key(g, x, y, z):
    keys, _ = g.keys(np.array([x]), np.array([y]), np.array([z]))
    return int(keys[0])


class RegionFileTest(unittest.TestCase):
    def test_round_trip_is_within_the_quantisation(self):
        rng = np.random.default_rng(3)
        tris = (rng.uniform(-150, 150, (500, 3, 3)) + [1000.0, -2000.0, 40.0]).astype(np.float32)
        back, bounds, margin = build_region.decode(build_region.encode(tris, (850, -2150, 1150, -1850), 0.6))
        self.assertEqual(bounds, [850.0, -2150.0, 1150.0, -1850.0])
        self.assertAlmostEqual(margin, 0.6, places=6)
        self.assertEqual(back.shape, tris.shape)
        # order is kept, every corner within half a quantum plus the float32 rounding of the position
        self.assertLess(np.abs(back.astype(np.float64) - tris).max(), build_region.QUANT / 2 + 1e-3)

    def test_shared_corners_repeated_and_degenerate_triangles_are_stored_once_or_not_at_all(self):
        quad = np.array([[[0, 0, 0], [1, 0, 0], [1, 1, 0]], [[0, 0, 0], [1, 1, 0], [0, 1, 0]]], np.float32)
        degenerate = np.array([[[5, 5, 5], [5, 5, 5], [6, 5, 5]]], np.float32)
        tris = np.concatenate([quad, quad[:1], degenerate])
        back, _, _ = build_region.decode(build_region.encode(tris, (-1, -1, 2, 2), 0.6))
        self.assertEqual(len(back), 2)
        self.assertTrue(np.allclose(back, quad, atol=1e-4))

    def test_an_empty_region_is_a_valid_file(self):
        back, bounds, _ = build_region.decode(build_region.encode(np.zeros((0, 3, 3), np.float32), SQUARE, 0.6))
        self.assertEqual(len(back), 0)
        self.assertEqual(bounds, list(SQUARE))


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.grid = grid()
        # one occupied voxel at (50.25, 50.25, 5.125)
        self.occupied = np.array([key(self.grid, 50.25, 50.25, 5.125)], np.int64)
        self.near = build_region.Occupancy(self.occupied, self.grid, (40, 40, 60, 60), 0.6)

    def tri(self, x, y, z):
        return np.array([[x, y, z], [x + 1, y, z], [x, y + 1, z]], np.float32)

    def test_a_triangle_within_the_margin_of_a_voxel_is_kept(self):
        # 0.6 m margin = 2 columns and 3 heights: the box of the triangle reaches the voxel
        kept = self.near.near(np.stack([self.tri(51.0, 50.0, 5.1), self.tri(48.6, 50.0, 5.1), self.tri(50.0, 50.0, 6.0)]))
        self.assertEqual(kept.tolist(), [True, True, True])

    def test_a_triangle_far_from_every_voxel_is_dropped(self):
        far_xy = self.tri(56.0, 50.0, 5.1)
        far_z = self.tri(50.0, 50.0, 9.0)
        self.assertEqual(self.near.near(np.stack([far_xy, far_z])).tolist(), [False, False])

    def test_a_wider_margin_keeps_everything_a_narrower_one_keeps(self):
        rng = np.random.default_rng(5)
        tris = (rng.uniform(0, 3, (400, 3, 3)) + [49.0, 49.0, 4.0]).astype(np.float32)
        narrow = build_region.Occupancy(self.occupied, self.grid, (40, 40, 60, 60), 0.0).near(tris)
        wide = self.near.near(tris)
        self.assertTrue(narrow.any())
        self.assertFalse((narrow & ~wide).any())

    def test_select_keeps_visibility_triangles_of_the_square_only(self):
        import collision
        import tempfile

        inside = self.tri(51.0, 50.0, 5.1)
        outside = self.tri(80.0, 80.0, 5.1)
        invisible = self.tri(51.0, 50.0, 5.2)
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "shard.npz")
            np.savez(path, tris=np.stack([inside, outside, invisible]),
                     mask=np.array([collision.VISIBILITY, collision.VISIBILITY, collision.PROJECTILE], np.uint8))
            kept, met = build_region.select([path], [self.near], [(40, 40, 60, 60)])
        self.assertEqual(met, [1])
        self.assertEqual(kept[0].shape, (1, 3, 3))
        self.assertTrue(np.array_equal(kept[0][0], inside))


if __name__ == "__main__":
    unittest.main()
