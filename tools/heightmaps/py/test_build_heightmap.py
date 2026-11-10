"""Tests of the grid arithmetic of build_heightmap.py and maps.cell_m: python -m unittest test_build_heightmap"""

import unittest

import numpy as np

import build_heightmap
import maps

META = {"resolution_m": 1.0, "bounds_m": {"min_x": 10.0, "max_x": 14.0, "min_y": -3.0, "max_y": 1.0}}


class GridShape(unittest.TestCase):
    def test_both_corners_are_samples(self):
        self.assertEqual(build_heightmap.grid_shape(META, 1.0), (5, 5))
        self.assertEqual(build_heightmap.grid_shape(META, 0.5), (9, 9))

    def test_non_square_bounds_give_rows_by_cols(self):
        meta = {**META, "bounds_m": {"min_x": 0.0, "max_x": 6.0, "min_y": 0.0, "max_y": 2.0}}
        self.assertEqual(build_heightmap.grid_shape(meta, 0.5), (5, 13))


class UpsampleSurface(unittest.TestCase):
    def setUp(self):
        self.shape = build_heightmap.grid_shape(META, 0.5)
        # A 45 degree slope rising towards +x: terrain = 0.5 m per fine column
        self.terrain = np.tile(np.arange(self.shape[1]) * 0.5, (self.shape[0], 1))
        self.surface = self.terrain[::2, ::2].copy()

    def test_cell_equal_to_squadheight_returns_the_surface(self):
        surface = np.arange(25.0).reshape(5, 5)
        self.assertIs(build_heightmap.upsample_surface(surface, surface, META, 1.0), surface)

    def test_cell_that_does_not_divide_is_refused(self):
        with self.assertRaises(ValueError):
            build_heightmap.upsample_surface(self.surface, self.terrain, META, 0.3)

    def test_samples_are_kept_and_ground_stays_the_terrain(self):
        fused = build_heightmap.upsample_surface(self.surface, self.terrain, META, 0.5)
        self.assertEqual(fused.shape, self.shape)
        np.testing.assert_allclose(fused, self.terrain)
        np.testing.assert_allclose(fused[::2, ::2], self.surface)

    def test_building_keeps_its_height_above_a_sloping_ground(self):
        self.surface[2, 2] += 4.0
        fused = build_heightmap.upsample_surface(self.surface, self.terrain, META, 0.5)
        np.testing.assert_allclose(fused[4, 4], self.terrain[4, 4] + 4.0)
        # Halfway cells take the sample with the larger coordinate: the building at (2, 2) covers fine rows and
        # columns 3 and 4, each lifted by its own terrain's height, not by the neighbour sample's absolute height
        for row, col in ((3, 3), (3, 4), (4, 3)):
            self.assertAlmostEqual(fused[row, col] - self.terrain[row, col], 4.0)
        self.assertAlmostEqual(fused[5, 5] - self.terrain[5, 5], 0.0)

    def test_cells_without_landscape_follow_the_squadheight_triangles(self):
        terrain = np.full(self.shape, np.nan)
        # Without landscape the slope between two samples is crossed linearly, not in a step
        fused = build_heightmap.upsample_surface(self.surface, terrain, META, 0.5)
        np.testing.assert_allclose(fused, self.terrain)

    def test_triangle_split_follows_the_row_col_diagonal(self):
        terrain = np.full(self.shape, np.nan)
        surface = np.zeros((5, 5))
        surface[1, 1] = 1.0
        fused = build_heightmap.upsample_surface(surface, terrain, META, 0.5)
        # Quad (0, 0) has the peak at its (row + 1, col + 1) corner: min(east, south); quad (0, 1) has it off the diagonal
        self.assertAlmostEqual(fused[1, 1], 0.5)
        self.assertAlmostEqual(fused[1, 3], 0.0)
        self.assertAlmostEqual(fused[2, 2], 1.0)

    def test_covered_cell_next_to_an_uncovered_sample_reads_the_squadheight_grid(self):
        terrain = self.terrain.copy()
        terrain[:, 5:] = np.nan
        surface = self.surface.copy()
        surface[:, 3:] = 100.0
        fused = build_heightmap.upsample_surface(surface, terrain, META, 0.5)
        # Fine column 5 is uncovered, columns 0 to 4 keep their terrain
        np.testing.assert_allclose(fused[:, :5], terrain[:, :5])
        self.assertTrue(np.all(fused[:, 6:] == 100.0))


class Fuse(unittest.TestCase):
    """Flat terrain at 10 m with two objects of SquadHeight: a house 5 m high at rows 2..3, a block 7 m high at rows 6..7."""

    def setUp(self):
        self.terrain = np.full((10, 10), 10.0)
        self.surface = self.terrain.copy()
        self.surface[2:4, 2:6] = 15.0
        self.surface[6:8, 2:6] = 17.0
        self.house = np.zeros((10, 10), bool)
        self.house[2:4, 2:6] = True

    def test_every_object_of_squadheight_is_taken_when_nothing_is_said_of_them(self):
        fused, stats = build_heightmap.fuse(self.terrain, self.surface)
        np.testing.assert_array_equal(fused, self.surface)
        self.assertEqual(stats["sdk_object_cells"], 16)
        self.assertNotIn("sdk_unexplained_cells", stats)

    def test_an_object_that_no_placement_of_the_game_explains_is_left_out(self):
        # Al Basrah: blocks of the SDK's background city over open sand, which neither the server nor the client has
        fused, stats = build_heightmap.fuse(self.terrain, self.surface, explained=self.house)
        np.testing.assert_array_equal(fused[2:4, 2:6], 15.0)
        np.testing.assert_array_equal(fused[6:8, 2:6], 10.0)
        self.assertEqual((stats["sdk_object_cells"], stats["sdk_unexplained_cells"]), (8, 8))

    def test_under_an_unexplained_object_the_games_own_collision_stands(self):
        objects = np.full((10, 10), -np.inf)
        objects[6, 2:6] = 12.0
        fused, stats = build_heightmap.fuse(self.terrain, self.surface, objects, self.house)
        np.testing.assert_array_equal(fused[6, 2:6], 12.0)
        np.testing.assert_array_equal(fused[7, 2:6], 10.0)
        self.assertEqual((stats["game_object_cells"], stats["sdk_only_object_cells"]), (4, 8))

    def test_under_an_unexplained_object_the_water_of_the_game_stands(self):
        # Al Basrah: the block stands in the river, whose bed is the terrain and whose surface is the ocean plane
        below = np.full((10, 10), -np.inf)
        below[6:8, 2:6] = 12.5
        below[2:4, 2:6] = 11.0  # under the house too, which is explained and keeps SquadHeight's height
        fused, _ = build_heightmap.fuse(self.terrain, self.surface, explained=self.house, below=below)
        np.testing.assert_array_equal(fused[6:8, 2:6], 12.5)
        np.testing.assert_array_equal(fused[2:4, 2:6], 15.0)
        np.testing.assert_array_equal(fused[0], 10.0)

    def test_outside_the_landscape_squadheight_is_the_ground_whatever_explains_it(self):
        self.terrain[:, 5:] = np.nan
        fused, stats = build_heightmap.fuse(self.terrain, self.surface, explained=self.house)
        np.testing.assert_array_equal(fused[6:8, 5], 17.0)
        np.testing.assert_array_equal(fused[6:8, 2:5], 10.0)
        self.assertEqual(stats["sdk_unexplained_cells"], 6)

    def test_above_terrain_is_the_points_that_rise_half_a_metre_on_the_landscape(self):
        self.surface[0, 0] = 10.49
        self.surface[0, 1] = 10.5
        self.terrain[9, 9] = np.nan
        rising = build_heightmap.above_terrain(self.terrain, self.surface)
        self.assertEqual((bool(rising[0, 0]), bool(rising[0, 1]), bool(rising[9, 9]), int(rising.sum())), (False, True, False, 17))


class CellSize(unittest.TestCase):
    def test_native_half_metre_maps_and_the_default(self):
        self.assertEqual(maps.cell_m("chora"), 0.5)
        self.assertEqual(maps.cell_m("kokan"), 0.5)
        self.assertEqual(maps.cell_m("fallujah"), 1.0)

    def test_every_cell_divides_squadheights_metre(self):
        for slug in maps.MAPS:
            self.assertAlmostEqual(1.0 / maps.cell_m(slug), round(1.0 / maps.cell_m(slug)))


if __name__ == "__main__":
    unittest.main()
