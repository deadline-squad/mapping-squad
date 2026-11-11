"""Tests of build_heightmap.py: python -m unittest test_build_heightmap"""

import json
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

import build_heightmap
import heightmap_webp
import landscape
import lattice
from test_lattice import actor, twisted

BOUNDS = {"min_x": 0.0, "max_x": 8.0, "min_y": 0.0, "max_y": 8.0}
SQUADHEIGHT = {"resolution_m": 1.0, "bounds_m": BOUNDS}


def sloping(location_cm=(-170.0, -150.0, 0.0)):
    """A 14 x 14 landscape of 1 m quads, z = 0.5 x + 0.25 y (m) about its first vertex: planar, so its triangles are exact
    anywhere. At the default location its vertices are at x = -1.7 + i, y = -1.5 + j, and the map's grid covering BOUNDS at
    x = -0.7 .. 8.3, y = -0.5 .. 8.5 (10 x 10 nodes)."""
    j, i = np.mgrid[0:14, 0:14].astype(np.float64)
    return actor((0.5 * i + 0.25 * j) * 128, location_cm)


def squadheight_of(actors):
    """SquadHeight's surface of bare ground: the game's terrain at its samples (a 1 m grid from BOUNDS' min corner)."""
    ys, xs = np.mgrid[0:9, 0:9].astype(np.float64)
    return build_heightmap.landscape_at(actors, xs, ys)


def read_build(out):
    """(meta, PNG levels) of a heightmap written to ``out``."""
    with open(os.path.join(out, "meta.json")) as f:
        meta = json.load(f)
    with Image.open(os.path.join(out, "heightmap.png")) as image:
        return meta, np.asarray(image)


class MapLattice(unittest.TestCase):
    def test_the_grid_is_the_landscapes_vertices_over_the_minimap(self):
        grid = build_heightmap.map_lattice([sloping()], BOUNDS)
        np.testing.assert_allclose(grid[:4], (-0.7, -0.5, 1.0, 0.0), atol=1e-9)
        self.assertEqual((grid.width, grid.height), (10, 10))

    def test_every_node_of_a_turned_map_is_a_vertex(self):
        # Skorpo: 1.2 m quads turned by -2.006195 degrees
        heights = twisted(14, 14)
        land = actor(heights, (-311.0, -527.0, 1500.0), -2.006195, 120.0, (1, 2))
        grid = build_heightmap.map_lattice([land], {"min_x": 0.0, "max_x": 10.0, "min_y": 0.0, "max_y": 10.0})
        terrain = build_heightmap.game_terrain([land], grid)
        xs, ys = lattice.node_rows(grid, 0, grid.height)
        cols, rows = lattice.to_grid(lattice.Lattice(*lattice.landscape_lattice([land]), 0, 0), xs, ys)
        np.testing.assert_allclose(cols, np.rint(cols), atol=1e-6)
        np.testing.assert_allclose(rows, np.rint(rows), atol=1e-6)
        vertex = 15.0 + heights[np.rint(rows).astype(int), np.rint(cols).astype(int)] / 128
        self.assertFalse(np.isnan(terrain).any())
        np.testing.assert_allclose(terrain, vertex, atol=1e-9)


class SurfaceOnLattice(unittest.TestCase):
    def setUp(self):
        self.actors = [sloping()]
        self.grid = build_heightmap.map_lattice(self.actors, BOUNDS)
        self.terrain = build_heightmap.game_terrain(self.actors, self.grid)
        self.surface = squadheight_of(self.actors)

    def on_lattice(self, actors=None, terrain=None):
        actors = self.actors if actors is None else actors
        terrain = self.terrain if terrain is None else terrain
        return build_heightmap.surface_on_lattice(self.surface, SQUADHEIGHT, actors, self.grid, terrain)

    def test_bare_ground_stays_the_games_terrain(self):
        np.testing.assert_allclose(self.on_lattice(), self.terrain, atol=1e-12)

    def test_a_building_keeps_its_height_above_a_sloping_ground(self):
        self.surface[4, 4] += 4.0
        lifted = self.on_lattice() - self.terrain
        # Node (x 4.3, y 3.5) is the only one whose nearest sample is (4, 4); y 3.5 is halfway and takes the larger coordinate.
        # Its own terrain is 0.4 m below the sample's, which the sample's absolute height would add as a bump
        expected = np.zeros(lifted.shape)
        expected[4, 5] = 4.0
        np.testing.assert_allclose(lifted, expected, atol=1e-12)

    def test_beyond_the_minimap_a_node_is_its_own_terrain(self):
        # Column x = -0.7 is more than half a SquadHeight cell outside its grid: SquadHeight has nothing there
        self.surface[:, 0] += 4.0
        lifted = self.on_lattice() - self.terrain
        np.testing.assert_allclose(lifted[:, 0], 0.0, atol=1e-12)
        np.testing.assert_allclose(lifted[:, 1], 4.0, atol=1e-12)

    def test_nodes_without_landscape_read_squadheight_along_the_games_triangles(self):
        self.surface = np.zeros((9, 9))
        self.surface[1, 1] = 1.0
        out = self.on_lattice(actors=[], terrain=np.full(self.terrain.shape, np.nan))
        # Nodes (x 0.3, y 0.5), (x 1.3, y 0.5) and (x 1.3, y 1.5) are below the diagonals of quads (0, 0), (0, 1) and (1, 1)
        # (column part 0.3 < row part 0.5); the -0.7 column reads SquadHeight's edge
        self.assertAlmostEqual(out[1, 1], 0.3)
        self.assertAlmostEqual(out[1, 2], 0.5 - 0.3)
        self.assertAlmostEqual(out[2, 2], 1.0 - 0.5)
        self.assertAlmostEqual(out[2, 0], 0.0)


class Build(unittest.TestCase):
    def test_the_heightmap_read_like_the_page_is_the_games_collision_on_bare_ground(self):
        # Landscape vertices 0.43 m and 0.25 m off the minimap's corner (Goose Bay), every quad twisted
        heights = twisted(14, 14, seed=5)
        land = actor(heights, (-143.0, -125.0, 0.0))
        grid = build_heightmap.map_lattice([land], BOUNDS)
        terrain = build_heightmap.game_terrain([land], grid)
        surface = build_heightmap.surface_on_lattice(squadheight_of([land]), SQUADHEIGHT, [land], grid, terrain)
        fused, stats = build_heightmap.fuse(terrain, surface)
        with tempfile.TemporaryDirectory() as out:
            build_heightmap.write(out, "Test", fused, grid, SQUADHEIGHT, stats, "1")
            meta, png = read_build(out)
        levels = png.astype(np.float64)
        heightmap = meta["z_min_m"] + levels * meta["z_step_m"]
        rng = np.random.default_rng(11)
        xs, ys = rng.uniform(0, 8, 20000), rng.uniform(0, 8, 20000)
        game = landscape.sample_world(land, xs * 100, ys * 100, "triangle") / 100
        error = np.abs(lattice.read(heightmap, lattice.from_meta(meta), xs, ys) - game)
        self.assertLess(error.max(), meta["z_step_m"] / 2 + 1e-4)

    def test_png_and_webp_hold_the_same_levels_and_step(self):
        grid = lattice.Lattice(-0.43, -0.25, 1.0, 0.0, 10, 10)
        fused = np.random.default_rng(2).uniform(0.0, 30.0, (10, 10))
        with tempfile.TemporaryDirectory() as out:
            build_heightmap.write(out, "Test", fused, grid, SQUADHEIGHT, {}, "1")
            meta, png = read_build(out)
            webp = heightmap_webp.decode(os.path.join(out, heightmap_webp.FILE))
        np.testing.assert_array_equal(webp, png)
        self.assertEqual(meta["webp"]["z_step_m"], meta["z_step_m"])
        self.assertEqual(meta["webp"]["levels_sum"], heightmap_webp.levels_sum(png))
        self.assertEqual(lattice.from_meta(meta), grid)
        self.assertEqual(meta["bounds_m"], BOUNDS)


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


if __name__ == "__main__":
    unittest.main()
