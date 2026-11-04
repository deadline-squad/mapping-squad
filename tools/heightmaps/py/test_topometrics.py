"""Tests of topometrics.py against analytic surfaces: python -m unittest test_topometrics

Plane, paraboloid and sphere patch have exact slope, aspect and curvature; every metric is compared with them to
a relative error below 1e-6 (zero values: absolute below 1e-9).
"""

import json
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

import topometrics

REL = 1e-6


def grid(rows, cols, cell, x0=0.0, y0=0.0):
    """Easting and northing (m) of every sample; row 0 is the northernmost, at northing y0."""
    row, col = np.mgrid[0:rows, 0:cols]
    return x0 + col * cell, y0 - row * cell


def assert_close(test, actual, expected, rel=REL, floor=1e-9):
    error = np.abs(actual - expected)
    allowed = np.maximum(rel * np.abs(expected), floor)
    test.assertTrue(np.all(error <= allowed), f"worst error {error.max()} at expected {expected.flat[error.argmax()]}")


def interior(array):
    return array[1:-1, 1:-1]


class Plane(unittest.TestCase):
    A, B, CELL = 0.37, -0.81, 0.5

    def setUp(self):
        x, y = grid(30, 40, self.CELL)
        self.z = self.A * x + self.B * y + 12.0
        self.metrics = topometrics.block_metrics(self.z, self.CELL, with_sky=False)

    def test_slope_and_aspect(self):
        gradient = np.hypot(self.A, self.B)
        assert_close(self, interior(self.metrics["slope_deg"]), np.full((28, 38), np.degrees(np.arctan(gradient))))
        # downhill direction (-A, -B) = (west-ish, north-ish): bearing atan2(east, north)
        expected = np.degrees(np.arctan2(-self.A, -self.B)) % 360
        assert_close(self, interior(self.metrics["aspect_deg"]), np.full((28, 38), expected))

    def test_no_curvature_no_position(self):
        for name in ("profile_curvature_per_m", "plan_curvature_per_m", "tpi_m"):
            self.assertLess(np.abs(interior(self.metrics[name])).max(), 1e-9, name)

    def test_ruggedness_and_roughness(self):
        # ring offsets (dx, dy) in cells: sum of (a dx + b dy)^2 = 6 (a^2 + b^2), a, b per cell
        a, b = self.A * self.CELL, self.B * self.CELL
        assert_close(self, interior(self.metrics["tri_m"]), np.full((28, 38), np.sqrt(6 * (a * a + b * b))))
        assert_close(self, interior(self.metrics["roughness_m"]), np.full((28, 38), 2 * (abs(a) + abs(b))))

    def test_flat_has_undefined_aspect_and_curvature(self):
        flat = topometrics.block_metrics(np.full((5, 5), 3.0), 1.0, with_sky=False)
        for name in ("aspect_deg", "profile_curvature_per_m", "plan_curvature_per_m"):
            self.assertTrue(np.isnan(flat[name]).all(), name)
        self.assertEqual(flat["slope_deg"].max(), 0.0)

    def test_cardinal_aspects(self):
        x, y = grid(5, 5, 1.0)
        # rises to the north: the surface faces south
        self.assertAlmostEqual(topometrics.block_metrics(y, 1.0, False)["aspect_deg"][2, 2], 180.0)
        # rises to the east: faces west
        self.assertAlmostEqual(topometrics.block_metrics(x, 1.0, False)["aspect_deg"][2, 2], 270.0)


class Paraboloid(unittest.TestCase):
    A, B, C, CELL = 0.002, 0.0005, 0.0007, 1.0

    def setUp(self):
        x, y = grid(61, 61, self.CELL, x0=3.3, y0=40.3)
        self.x, self.y = x, y
        self.z = self.A * x**2 + self.B * y**2 + self.C * x * y
        self.metrics = topometrics.block_metrics(self.z, self.CELL, with_sky=False)
        # exact derivatives
        self.p = 2 * self.A * x + self.C * y
        self.q = 2 * self.B * y + self.C * x
        self.r, self.s, self.t = 2 * self.A, self.C, 2 * self.B

    def test_slope_and_aspect_exact(self):
        assert_close(self, interior(self.metrics["slope_deg"]), interior(np.degrees(np.arctan(np.hypot(self.p, self.q)))))
        assert_close(self, interior(self.metrics["aspect_deg"]), interior(np.degrees(np.arctan2(-self.p, -self.q)) % 360))

    def test_curvatures_exact(self):
        g = self.p**2 + self.q**2
        profile = -(self.p**2 * self.r + 2 * self.p * self.q * self.s + self.q**2 * self.t) / (g * (1 + g) ** 1.5)
        plan = -(self.q**2 * self.r - 2 * self.p * self.q * self.s + self.p**2 * self.t) / g**1.5
        steep = interior(g) > 1.01 * topometrics._MIN_GRADIENT_SQUARED
        self.assertGreater(steep.mean(), 0.9)
        for name, expected in (("profile_curvature_per_m", profile), ("plan_curvature_per_m", plan)):
            found = interior(self.metrics[name])
            assert_close(self, found[steep], interior(expected)[steep])
            self.assertTrue(np.isnan(found[interior(g) < 0.99 * topometrics._MIN_GRADIENT_SQUARED]).all())

    def test_second_derivatives_exact(self):
        r, s, t = topometrics.second_derivatives(self.z, self.CELL)
        for found, expected in ((r, self.r), (s, self.s), (t, self.t)):
            assert_close(self, interior(found), np.full((59, 59), expected))

    def test_tpi_is_minus_a_ring_of_the_curvature(self):
        # ring mean of a quadratic: z5 + cell^2 (6 A + 6 B) / 8
        expected = -(6 * self.A + 6 * self.B) * self.CELL**2 / 8
        assert_close(self, interior(self.metrics["tpi_m"]), np.full((59, 59), expected))

    def test_large_tpi_of_a_quadratic(self):
        radius = round(topometrics.TPI_RADIUS_M / self.CELL)
        offsets = np.arange(-radius, radius + 1) * self.CELL
        dx, dy = np.meshgrid(offsets, offsets)
        count = dx.size
        # mean over the window of z - z5 (centre contributes zero), divided over count - 1 other cells
        window_mean_gain = (self.A * dx**2 + self.B * dy**2 + self.C * dx * dy).sum() / (count - 1)
        found = self.metrics["tpi_10m_m"][radius + 1:-radius - 1, radius + 1:-radius - 1]
        assert_close(self, found, np.full(found.shape, -window_mean_gain))

    def test_convex_is_positive(self):
        dome = topometrics.block_metrics(-(self.x**2 + self.y**2) * 0.001, 1.0, False)
        mask = interior(dome["slope_deg"]) > 1
        self.assertGreater(interior(dome["profile_curvature_per_m"])[mask].min(), 0)
        self.assertGreater(interior(dome["plan_curvature_per_m"])[mask].min(), 0)


class SpherePatch(unittest.TestCase):
    """A patch of a sphere of radius R centred on the origin: slope = asin(rho / R), profile curvature 1 / R (every
    normal section of a sphere), plan curvature 1 / rho (the contour is a circle of radius rho)."""

    R, CELL = 10000.0, 1.0

    def setUp(self):
        x, y = grid(41, 41, self.CELL, x0=3000.0, y0=-2000.0)
        self.rho = np.hypot(x, y)
        self.z = np.sqrt(self.R**2 - x**2 - y**2) - self.R
        self.metrics = topometrics.block_metrics(self.z, self.CELL, with_sky=False)

    def test_slope(self):
        assert_close(self, interior(self.metrics["slope_deg"]), interior(np.degrees(np.arcsin(self.rho / self.R))))

    def test_profile_curvature(self):
        assert_close(self, interior(self.metrics["profile_curvature_per_m"]), np.full((39, 39), 1 / self.R))

    def test_plan_curvature(self):
        assert_close(self, interior(self.metrics["plan_curvature_per_m"]), interior(1 / self.rho))

    def test_aspect_points_away_from_the_centre(self):
        # centre is west and north of the patch... the origin is at (-x, +y) from it: downhill faces away from it
        x, y = grid(41, 41, self.CELL, x0=3000.0, y0=-2000.0)
        expected = np.degrees(np.arctan2(x, y)) % 360
        assert_close(self, interior(self.metrics["aspect_deg"]), interior(expected))


class Summary(unittest.TestCase):
    def test_block_boundaries_do_not_change_metrics(self):
        rng = np.random.default_rng(1)
        z = np.cumsum(np.cumsum(rng.normal(size=(300, 40)), axis=0), axis=1)
        whole = topometrics.block_metrics(z, 1.0, with_sky=False)
        original = topometrics.BLOCK_ROWS
        topometrics.BLOCK_ROWS = 64
        try:
            for start, block in topometrics.iter_blocks(z, 1.0, with_sky=False):
                for name, value in block.items():
                    np.testing.assert_allclose(value, whole[name][start:start + value.shape[0]], rtol=1e-9, atol=1e-9, err_msg=name)
        finally:
            topometrics.BLOCK_ROWS = original

    def test_summary_of_a_known_slope(self):
        x, y = grid(50, 50, 1.0)
        meta = {"map": "plane", "resolution_m": 1.0}
        summary = topometrics.map_summary(x * np.tan(np.radians(20.0)), meta, with_sky=False)
        slope = summary["metrics"]["slope_deg"]
        self.assertAlmostEqual(slope["p50"], 20.0, places=6)
        self.assertGreater(summary["slope_share"]["over_15_deg"], 0.95)  # the edge columns repeat their neighbours
        self.assertEqual(summary["slope_share"]["over_30_deg"], 0.0)
        self.assertEqual(summary["metrics"]["aspect_deg"]["p50"], 270.0)


class Loader(unittest.TestCase):
    def test_round_trip_of_the_rg16_webp(self):
        levels = np.array([[0, 255, 256], [65535, 1000, 40000]], dtype=np.uint32)
        rgb = np.zeros(levels.shape + (3,), dtype=np.uint8)
        rgb[..., 0], rgb[..., 1] = levels >> 8, levels & 255
        meta = {"map": "t", "z_min_m": 1.5, "resolution_m": 1.0,
                "webp": {"file": "heightmap.webp", "z_step_m": 0.01, "levels_sum": int(levels.sum() % 2**32)}}
        with tempfile.TemporaryDirectory() as folder:
            Image.fromarray(rgb).save(os.path.join(folder, "heightmap.webp"), lossless=True)
            with open(os.path.join(folder, "meta.json"), "w") as handle:
                json.dump(meta, handle)
            z, _ = topometrics.load_heightmap(folder)
            np.testing.assert_allclose(z, 1.5 + levels * 0.01, rtol=0, atol=1e-12)
            meta["webp"]["levels_sum"] += 1
            with open(os.path.join(folder, "meta.json"), "w") as handle:
                json.dump(meta, handle)
            with self.assertRaises(ValueError):
                topometrics.load_heightmap(folder)


if __name__ == "__main__":
    unittest.main()
