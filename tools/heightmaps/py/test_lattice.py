"""Tests of lattice.py, the heightmap's grid on the landscape's vertices: python -m unittest test_lattice"""

import math
import unittest

import numpy as np

import landscape
import lattice


def actor(heights, location_cm=(0.0, 0.0, 0.0), yaw=0.0, scale_cm=100.0, first_quad=(0, 0)):
    """A landscape actor as landscape.assemble gives it: raw heights (1/128 of the Z scale), so z = raw / 128 m at scale 100."""
    return (np.asarray(heights, np.float64), first_quad[0], first_quad[1], (location_cm, yaw, (scale_cm, scale_cm, 100.0)), 0.0)


def twisted(rows, cols, seed=1):
    """Raw heights of a rough landscape: every quad twisted, so the triangle split matters everywhere."""
    return np.random.default_rng(seed).uniform(-500.0, 500.0, (rows, cols)) * 128


class LandscapeLattice(unittest.TestCase):
    def test_the_first_vertex_is_the_actors_location_plus_its_first_quad(self):
        found = lattice.landscape_lattice([actor(np.zeros((3, 3)), (-204001.0, -204000.0, 0.0), first_quad=(2, 3), scale_cm=75.0)])
        self.assertEqual(found[2:], (0.75, 0.0))
        self.assertAlmostEqual(found[0], -2040.01 + 2 * 0.75)
        self.assertAlmostEqual(found[1], -2040.0 + 3 * 0.75)

    def test_a_turned_actor_turns_its_first_quad(self):
        # Skorpo: the landscape is turned by -2.006195 degrees about the actor's location
        yaw = -2.006195
        x, y, resolution, found_yaw = lattice.landscape_lattice([actor(np.zeros((2, 2)), (-481127.25, -394791.78, 0.0), yaw, 120.0, (508, 1524))])
        c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        self.assertAlmostEqual(x, -4811.2725 + 1.2 * (c * 508 - s * 1524))
        self.assertAlmostEqual(y, -3947.9178 + 1.2 * (s * 508 + c * 1524))
        self.assertEqual((resolution, found_yaw), (1.2, yaw))

    def test_proxies_on_the_same_lattice_are_accepted_and_others_refused(self):
        # Fallujah: streaming proxies that share their edge vertices
        first = actor(np.zeros((3, 3)), (-204000.0, -204000.0, 0.0))
        second = actor(np.zeros((3, 3)), (-204000.0, -204000.0, 0.0), first_quad=(510, 0))
        self.assertEqual(lattice.landscape_lattice([first, second])[:2], (-2040.0, -2040.0))
        shifted = actor(np.zeros((3, 3)), (-203950.0, -204000.0, 0.0))
        with self.assertRaises(ValueError):
            lattice.landscape_lattice([first, shifted])
        with self.assertRaises(ValueError):
            lattice.landscape_lattice([first, actor(np.zeros((3, 3)), (-204000.0, -204000.0, 0.0), scale_cm=50.0)])


class Covering(unittest.TestCase):
    BOUNDS = {"min_x": -10.0, "max_x": 10.0, "min_y": -5.0, "max_y": 15.0}

    def test_nodes_on_the_bounds_corners_give_no_extra_row(self):
        grid = lattice.covering(-40.0, -40.0, 1.0, 0.0, self.BOUNDS)
        self.assertEqual(grid, lattice.Lattice(-10.0, -5.0, 1.0, 0.0, 21, 21))

    def test_a_lattice_off_the_corners_reaches_past_them(self):
        # Goose Bay: vertices 0.43 and 0.25 m off the minimap's corner
        grid = lattice.covering(-40.43, -40.25, 1.0, 0.0, self.BOUNDS)
        self.assertAlmostEqual(grid.origin_x, -10.43)
        self.assertAlmostEqual(grid.origin_y, -5.25)
        self.assertEqual((grid.width, grid.height), (22, 22))
        # Anvil: 0.75 m vertices from the corner, 20 m = 26.67 spacings
        grid = lattice.covering(-10.0, -5.0, 0.75, 0.0, self.BOUNDS)
        self.assertEqual((grid.origin_x, grid.origin_y, grid.width, grid.height), (-10.0, -5.0, 28, 28))

    def test_every_point_of_the_bounds_lies_in_a_quad_of_a_turned_lattice(self):
        grid = lattice.covering(3.3, -7.1, 1.2, -2.006195, self.BOUNDS)
        xs, ys = np.meshgrid(np.linspace(-10, 10, 41), np.linspace(-5, 15, 41))
        cols, rows = lattice.to_grid(grid, xs, ys)
        self.assertTrue((cols >= 0).all() and (cols <= grid.width - 1).all() and (rows >= 0).all() and (rows <= grid.height - 1).all())

    def test_world_and_grid_positions_are_inverse(self):
        grid = lattice.covering(3.3, -7.1, 1.2, -2.006195, self.BOUNDS)
        cols, rows = lattice.to_grid(grid, *lattice.to_world(grid, np.array([0.0, 2.5, 7.25]), np.array([1.0, 0.0, 9.5])))
        np.testing.assert_allclose(cols, [0.0, 2.5, 7.25], atol=1e-9)
        np.testing.assert_allclose(rows, [1.0, 0.0, 9.5], atol=1e-9)


class Read(unittest.TestCase):
    def test_the_page_rule_on_the_landscapes_vertices_is_the_games_collision(self):
        # A turned landscape with 1.2 m quads: its vertices as the grid, read at random points, give the game's triangles
        yaw, heights = -2.006195, twisted(12, 14)
        land = actor(heights, (-311.0, 527.0, 1500.0), yaw, 120.0, (3, 5))
        grid = lattice.Lattice(*lattice.landscape_lattice([land]), 14, 12)
        nodes = 15.0 + heights / 128
        rng = np.random.default_rng(7)
        cols, rows = rng.uniform(0, 13, 5000), rng.uniform(0, 11, 5000)
        xs, ys = lattice.to_world(grid, cols, rows)
        game = landscape.sample_world(land, xs * 100, ys * 100, "triangle") / 100
        np.testing.assert_allclose(lattice.read(nodes, grid, xs, ys), game, atol=1e-9)

    def test_a_subdivided_lattice_reads_the_landscape_as_exactly(self):
        # Every quad of the subdivision lies on one side of the game's diagonal or on it, so the triangles stay exact
        heights = twisted(6, 6, seed=3)
        land = actor(heights, scale_cm=100.0)
        base = lattice.Lattice(0.0, 0.0, 1.0, 0.0, 6, 6)
        for factor in (2, 3, 4, 5):
            fine = lattice.subdivided(base, factor)
            nx, ny = lattice.node_rows(fine, 0, fine.height)
            nodes = landscape.sample_world(land, nx * 100, ny * 100, "triangle") / 100
            rng = np.random.default_rng(factor)
            xs, ys = rng.uniform(0, 5, 4000), rng.uniform(0, 5, 4000)
            game = landscape.sample_world(land, xs * 100, ys * 100, "triangle") / 100
            np.testing.assert_allclose(lattice.read(nodes, fine, xs, ys), game, atol=1e-9, err_msg=f"factor {factor}")

    def test_outside_by_more_than_half_a_node_is_nan_and_within_it_the_edge(self):
        grid = lattice.Lattice(0.0, 0.0, 1.0, 0.0, 2, 2)
        nodes = np.array([[1.0, 2.0], [3.0, 4.0]])
        z = lattice.read(nodes, grid, np.array([-0.4, 1.4, -0.6, 0.5]), np.array([0.0, 1.0, 0.0, 1.6]))
        np.testing.assert_allclose(z[:2], [1.0, 4.0])
        self.assertTrue(np.isnan(z[2:]).all())

    def test_on_grid_reads_at_the_minimap_points(self):
        grid = lattice.Lattice(-0.5, -0.5, 1.0, 0.0, 4, 4)
        nodes = np.add.outer(np.arange(4.0) * 2, np.arange(4.0))  # z = 2 * row + col: a plane
        bounds = {"min_x": 0.0, "max_x": 2.0, "min_y": 0.0, "max_y": 2.0}
        out = lattice.on_grid(nodes, grid, bounds, 1.0)
        self.assertEqual(out.shape, lattice.minimap_shape(bounds, 1.0))
        np.testing.assert_allclose(out, np.add.outer((np.arange(3.0) + 0.5) * 2, np.arange(3.0) + 0.5))

    def test_meta_round_trip(self):
        grid = lattice.Lattice(-3851.481, -3285.1115, 1.2, -2.006195, 5906, 5922)
        self.assertEqual(lattice.from_meta(lattice.meta_entry(grid)), grid)
        # A heightmap built before: its grid starts at the bounds' corner
        old = {"bounds_m": {"min_x": -2000.0, "max_x": 2000.0, "min_y": -1000.0, "max_y": 3000.0}, "resolution_m": 0.5, "width": 8001, "height": 8001}
        self.assertEqual(lattice.from_meta(old), lattice.Lattice(-2000.0, -1000.0, 0.5, 0.0, 8001, 8001))
        self.assertEqual(lattice.minimap_step({"resolution_m": 0.5}), 0.5)
        self.assertEqual(lattice.minimap_step({"resolution_m": 0.75}), 1.0)


if __name__ == "__main__":
    unittest.main()
