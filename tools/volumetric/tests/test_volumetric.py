"""Synthetic scenes with known answers: bridge, thin wall, tunnel roof. Run: python -m unittest discover tests (from tools/volumetric)."""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py"))
sys.path.insert(0, os.environ.get("HEIGHTMAPS_PY", os.path.join(os.path.dirname(__file__), "..", "..", "heightmaps", "py")))

import codec  # noqa: E402
import collision  # noqa: E402
import columns  # noqa: E402
import models  # noqa: E402
import reference  # noqa: E402
import terrain_raster  # noqa: E402

BOX = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7], [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5]])


def box(lo, hi):
    """Outward-wound triangles [12, 3, 3] of an axis-aligned box."""
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
    return corners[BOX][:, ::-1].astype(np.float32)


def scene():
    """Flat ground at z=0, a bridge deck (x 10..30, y 0..6, z 5..6) and a 0.2 m thick wall at x=50."""
    tris = np.concatenate([box((10, 0, 5), (30, 6, 6)), box((49.9, 0, 0), (50.1, 20, 3))])
    grid = columns.Grid(0, 0, 80, 40, 1.0, 0.25, -10.0)
    occupied, up, down = columns.build_keys([tris], grid)
    land = models.Landscape(np.zeros((40, 80)), np.zeros((40, 80), bool), 0.0, 0.0)
    top = np.zeros((40, 80))
    top[0:6, 10:30] = 6.0
    top[0:20, 49:51] = 3.0
    return tris, grid, occupied, up, down, land, top


class VolumetricTests(unittest.TestCase):
    def setUp(self):
        self.tris, self.grid, self.occupied, self.up, self.down, self.land, self.top = scene()
        self.voxels = models.VoxelModel(self.land, self.grid, self.occupied)
        self.heightmap = models.HeightmapModel(self.top, 0.0, 0.0)
        self.index = reference.TriangleIndex(self.tris, np.full(len(self.tris), 7, np.uint8), 0, 0, 80, 40)

    def test_bridge_underpass_is_clear_for_voxels_and_reference_but_not_heightmap(self):
        a, b = (5.0, 3.0, 1.6), (35.0, 3.0, 1.6)
        self.assertFalse(self.index.blocked(a, b, collision.VISIBILITY)[0])
        self.assertFalse(self.voxels.blocked(a, b))
        self.assertTrue(self.heightmap.blocked(a, b))

    def test_ray_through_the_deck_is_blocked_everywhere(self):
        a, b = (20.0, 3.0, 1.6), (20.0, 3.0, 9.0)
        self.assertTrue(self.index.blocked(a, b, collision.VISIBILITY)[0])
        self.assertTrue(self.voxels.blocked(a, b))
        self.assertTrue(self.heightmap.blocked(a, b))

    def test_thin_wall_blocks_even_when_it_misses_the_cell_centre(self):
        a, b = (40.0, 10.3, 1.6), (60.0, 10.3, 1.6)
        self.assertTrue(self.index.blocked(a, b, collision.VISIBILITY)[0])
        self.assertTrue(self.voxels.blocked(a, b))

    def test_over_the_wall_is_clear(self):
        a, b = (40.0, 10.3, 4.0), (60.0, 10.3, 4.0)
        self.assertFalse(self.index.blocked(a, b, collision.VISIBILITY)[0])
        self.assertFalse(self.voxels.blocked(a, b))

    def test_floors_list_ground_and_deck_with_headroom(self):
        floors = self.index.floors(20.0, 3.0, 20.0, -5.0, collision.VISIBILITY)
        self.assertEqual([round(f, 2) for f in floors], [6.0])  # the ground is landscape, not a triangle
        self.assertEqual(len(self.index.floors(20.0, 3.0, 20.0, -5.0, collision.VISIBILITY, headroom_m=0.5)), 1)

    def test_up_and_down_facing_voxels_recorded(self):
        self.assertGreater(len(self.up), 0)
        self.assertGreater(len(self.down), 0)
        x, y, z = self.grid.voxel_center(self.up)
        self.assertAlmostEqual(float(z.max()), 6.0, delta=0.25)

    def test_codec_round_trip(self):
        blob = codec.encode(self.occupied, self.grid)
        keys, header = codec.decode(blob)
        np.testing.assert_array_equal(keys, self.occupied)
        self.assertEqual(header["width"], self.grid.width)

    def test_block_mask_follows_channel_responses(self):
        self.assertEqual(collision.block_mask({"CollisionProfileName": "BlockAll"}, None), 7)
        self.assertEqual(collision.block_mask({"CollisionEnabled": "ECollisionEnabled::NoCollision"}, None), 0)
        ignore_all = {"CollisionResponses": {"ResponseArray": [{"Channel": c, "Response": "ECR_Ignore"} for c in ("Visibility", "Projectile", "Pawn")]}}
        self.assertEqual(collision.block_mask(ignore_all, {"CollisionProfileName": "BlockAll"}), 0)
        overlap_projectile = {"CollisionResponses": {"ResponseArray": [{"Channel": "Projectile", "Response": "ECR_Overlap"}]}}
        self.assertEqual(collision.block_mask(overlap_projectile, None), collision.VISIBILITY | collision.PAWN)

    def test_terrain_raster_round_trip_keeps_heights_holes_and_gaps(self):
        rng = np.random.default_rng(3)
        z = np.cumsum(rng.normal(0, 0.3, (30, 40)), axis=1) + np.cumsum(rng.normal(0, 0.3, (30, 40)), axis=0) - 20.0
        z[4, 5:9] = np.nan
        hole = np.zeros(z.shape, bool)
        hole[10, 3] = hole[29, 39] = True
        out, out_hole, header = terrain_raster.decode(terrain_raster.encode(z, hole, -100.0, 50.0, 0.5))
        self.assertEqual(out.shape, z.shape)
        np.testing.assert_array_equal(np.isnan(out), np.isnan(z))
        self.assertLessEqual(float(np.nanmax(np.abs(out - z))), header["step"] / 2 + 1e-6)
        np.testing.assert_array_equal(out_hole, hole)
        self.assertEqual((header["min_x"], header["min_y"], header["cell"]), (-100.0, 50.0, 0.5))


if __name__ == "__main__":
    unittest.main()
