"""Tests of heightmap_detail.py and the indexing of build_detail.py: python -m unittest test_heightmap_detail"""

import gzip
import unittest

import numpy as np

import build_detail
import heightmap_detail
import lattice


class Predicted(unittest.TestCase):
    def test_is_the_triangle_read_rounded_half_up(self):
        rng = np.random.default_rng(1)
        levels = rng.integers(0, 65536, (6, 7)).astype(np.uint16)
        rows, cols = np.meshgrid(np.arange(5), np.arange(6), indexing="ij")
        for factor in (2, 3, 4):
            grid = lattice.Lattice(0.0, 0.0, 1.0, 0.0, 7, 6)
            got = heightmap_detail.predicted(levels, rows.ravel(), cols.ravel(), factor)
            for k, (i, j) in enumerate(heightmap_detail.inner_nodes(factor)):
                read = lattice.read(levels, grid, cols.ravel() + j / factor, rows.ravel() + i / factor)
                np.testing.assert_array_equal(got[:, k], np.floor(read + 0.5 + 1e-9).astype(np.int64), err_msg=f"factor {factor}")

    def test_inner_nodes_leave_out_the_corners(self):
        self.assertEqual(heightmap_detail.inner_nodes(2), [(0, 1), (1, 0), (1, 1), (1, 2), (2, 1)])
        self.assertEqual(len(heightmap_detail.inner_nodes(3)), 12)


class Encoding(unittest.TestCase):
    def test_round_trip_keeps_flags_and_residuals_of_any_size(self):
        rng = np.random.default_rng(2)
        flags = rng.random((40, 37)) < 0.2
        residuals = rng.integers(-3, 4, (flags.sum(), 5))
        residuals[0] = [0, -1, 2 ** 20, -(2 ** 27), 65535 * 2]
        factor, unit, got_flags, got = heightmap_detail.decode(heightmap_detail.encode(flags, residuals, 2, 7))
        self.assertEqual((factor, unit), (2, 7))
        np.testing.assert_array_equal(got_flags, flags)
        np.testing.assert_array_equal(got, residuals)

    def test_a_detail_without_quads(self):
        flags = np.zeros((3, 4), bool)
        _, _, got_flags, got = heightmap_detail.decode(heightmap_detail.encode(flags, np.zeros((0, 5), np.int64), 2, 1))
        self.assertFalse(got_flags.any())
        self.assertEqual(got.shape, (0, 5))

    def test_another_magic_is_refused(self):
        with self.assertRaises(ValueError):
            heightmap_detail.decode(gzip.compress(b"TER2" + bytes(20)))


class Read(unittest.TestCase):
    def setUp(self):
        # A turned 1.2 m lattice (Skorpo) and the levels of its nodes subdivided by 2: the base is every other fine node
        rng = np.random.default_rng(3)
        self.grid = lattice.Lattice(-31.1, 52.7, 1.2, -2.006195, 9, 8)
        self.fine_grid = lattice.subdivided(self.grid, 2)
        self.fine = rng.integers(1000, 3000, (self.fine_grid.height, self.fine_grid.width)).astype(np.int64)
        self.base = self.fine[::2, ::2].astype(np.uint16)

    def detail(self, flags):
        rows, cols = np.nonzero(flags)
        inner = np.stack([self.fine[rows * 2 + i, cols * 2 + j] for i, j in heightmap_detail.inner_nodes(2)], 1)
        residuals = inner - heightmap_detail.predicted(self.base, rows, cols, 2)
        return heightmap_detail.decode(heightmap_detail.encode(flags, residuals, 2, 1))

    def points(self, count, seed):
        rng = np.random.default_rng(seed)
        return lattice.to_world(self.grid, rng.uniform(0, self.grid.width - 1, count), rng.uniform(0, self.grid.height - 1, count))

    def test_a_quad_with_detail_reads_the_sub_grid_with_the_triangle_rule(self):
        xs, ys = self.points(3000, 4)
        got = heightmap_detail.read(self.base, self.grid, self.detail(np.ones((7, 8), bool)), xs, ys)
        np.testing.assert_allclose(got, lattice.read(self.fine, self.fine_grid, xs, ys), atol=1e-9)

    def test_a_quad_without_detail_reads_its_corners(self):
        flags = np.zeros((7, 8), bool)
        flags[2:5, 3:6] = True
        xs, ys = self.points(3000, 5)
        cols, rows = lattice.to_grid(self.grid, xs, ys)
        inside = flags[np.floor(rows).astype(int), np.floor(cols).astype(int)]
        got = heightmap_detail.read(self.base, self.grid, self.detail(flags), xs, ys)
        np.testing.assert_allclose(got[inside], lattice.read(self.fine, self.fine_grid, xs[inside], ys[inside]), atol=1e-9)
        np.testing.assert_allclose(got[~inside], lattice.read(self.base, self.grid, xs[~inside], ys[~inside]), atol=1e-9)

    def test_a_unit_of_several_levels_keeps_every_node_within_half_of_it_and_the_predicted_ones_exact(self):
        # Nodes of a plane (bare ground: between bare corners the prediction holds them to half a level) and a 6.037 m wall
        rows, cols = np.mgrid[0:self.fine_grid.height, 0:self.fine_grid.width]
        self.fine = 2000 + 3 * rows + 5 * cols
        self.fine[4:7, 6:9] += 6037
        self.base = self.fine[::2, ::2].astype(np.uint16)
        r, c = np.nonzero(np.ones((7, 8), bool))
        inner = np.stack([self.fine[r * 2 + i, c * 2 + j] for i, j in heightmap_detail.inner_nodes(2)], 1)
        residuals = inner - heightmap_detail.predicted(self.base, r, c, 2)
        unit = heightmap_detail.unit_levels(0.001)
        self.assertEqual(unit, 50)
        values = np.rint(residuals / unit).astype(np.int64)
        detail = heightmap_detail.decode(heightmap_detail.encode(np.ones((7, 8), bool), values, 2, unit))
        x, y = lattice.to_world(self.grid, c[:, None] + np.array([j for _, j in heightmap_detail.inner_nodes(2)]) / 2,
                                r[:, None] + np.array([i for i, _ in heightmap_detail.inner_nodes(2)]) / 2)
        error = np.abs(heightmap_detail.read(self.base, self.grid, detail, x, y) - inner)
        predicted = np.abs(residuals) <= 0.5
        self.assertTrue(predicted.any() and (~predicted).any())
        self.assertLessEqual(error[predicted].max(), 0.5 + 1e-9)
        self.assertLessEqual(error[~predicted].max(), unit / 2)

    def test_in_quads_is_where_read_takes_the_sub_grid(self):
        flags = np.zeros((7, 8), bool)
        flags[2:5, 3:6] = True
        xs, ys = self.points(3000, 6)
        detail = self.detail(flags)
        inside = heightmap_detail.in_quads(self.grid, detail, xs, ys)
        cols, rows = lattice.to_grid(self.grid, xs, ys)
        np.testing.assert_array_equal(inside, flags[np.floor(rows).astype(int), np.floor(cols).astype(int)])
        self.assertTrue(inside.any() and (~inside).any())
        base = lattice.read(self.base, self.grid, xs, ys)
        moved = heightmap_detail.read(self.base, self.grid, detail, xs, ys) != base
        self.assertFalse((moved & ~inside).any())
        self.assertFalse(heightmap_detail.in_quads(self.grid, None, xs, ys).any())

    def test_outside_the_grid_is_nan_and_no_detail_is_the_base(self):
        x, y = lattice.to_world(self.grid, np.array([-0.6, 3.5]), np.array([1.0, 2.5]))
        got = heightmap_detail.read(self.base, self.grid, self.detail(np.ones((7, 8), bool)), x, y)
        self.assertTrue(np.isnan(got[0]))
        np.testing.assert_allclose(heightmap_detail.read(self.base, self.grid, None, x, y), lattice.read(self.base, self.grid, x, y))


class Choose(unittest.TestCase):
    def test_the_smallest_threshold_whose_file_fits_the_budget(self):
        rng = np.random.default_rng(6)
        quads = np.sort(rng.choice(200 * 200, 4000, replace=False))
        largest = rng.choice([300, 600, 1200, 2400], 4000)  # levels of 1 mm: 0.3, 0.6, 1.2 and 2.4 m
        residuals = rng.integers(-2400, 2400, (4000, 5))
        nothing, all_sizes = heightmap_detail.choose((200, 200), quads, largest, residuals, 2, 0, 0.001)
        self.assertIsNone(nothing)
        self.assertEqual(list(all_sizes), list(heightmap_detail.THRESHOLDS_M))
        self.assertTrue(all_sizes[0.25] > all_sizes[0.5] > all_sizes[1.0] > all_sizes[2.0])
        (threshold, flags, data), _ = heightmap_detail.choose((200, 200), quads, largest, residuals, 2, all_sizes[1.0], 0.001)
        self.assertEqual(threshold, 1.0)
        self.assertEqual(flags.sum(), (largest > 1000).sum())
        self.assertEqual(len(data), all_sizes[1.0])
        self.assertIsNone(heightmap_detail.choose((200, 200), quads, largest, residuals, 2, all_sizes[2.0] - 1, 0.001)[0])


class Builder(unittest.TestCase):
    def test_a_band_holds_the_rows_of_the_fine_lattice(self):
        fine = lattice.subdivided(lattice.Lattice(-31.1, 52.7, 1.2, -2.006195, 9, 8), 2)
        part = build_detail.band(fine, 6, 5)
        x, y = lattice.node_rows(part, 0, part.height)
        fx, fy = lattice.node_rows(fine, 6, 5)
        np.testing.assert_allclose(x, fx, atol=1e-9)
        np.testing.assert_allclose(y, fy, atol=1e-9)

    def test_sub_grid_levels_are_the_inner_fine_nodes_of_each_quad(self):
        # Fine nodes of a band of 3 quad rows x 4 quad cols, each node's level its own index: z_min 0, step 1
        fused = np.arange(7 * 9, dtype=np.float32).reshape(7, 9)
        got = build_detail.sub_grid_levels(fused, {"z_min_m": 0.0, "z_step_m": 1.0}, 1, 2, 2)
        self.assertEqual(got.shape, (2, 4, 5))
        # Quad row 2 (the band's second), quad col 3: fine rows 4 to 6, cols 6 to 8
        np.testing.assert_array_equal(got[1, 3], [fused[4, 7], fused[5, 6], fused[5, 7], fused[5, 8], fused[6, 7]])


if __name__ == "__main__":
    unittest.main()
