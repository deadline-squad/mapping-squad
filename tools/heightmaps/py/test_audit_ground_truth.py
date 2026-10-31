"""Tests of audit_ground_truth.py and landscape.triangle_surface on synthetic grids (no game data needed).

Run: python -m unittest test_audit_ground_truth   (in tools/heightmaps/py; needs numpy and pillow)
"""

import io
import unittest

import numpy as np

import audit_ground_truth as audit
import landscape

# A 3 x 3 grid of 1 m samples with a 1 m peak in the middle (row 1, col 1); rows run along world Y
PEAK = np.array([[0, 0, 0], [0, 1, 0], [0, 0, 0]], dtype=float)


def grid():
    return audit.HeightGrid(PEAK, min_x=100.0, min_y=-50.0, resolution=1.0)


class HeightGridTest(unittest.TestCase):
    def test_reads_agree_on_the_samples(self):
        for read in (grid().bilinear, grid().nearest, grid().triangle):
            self.assertAlmostEqual(read(101.0, -49.0), 1.0)
            self.assertAlmostEqual(read(100.0, -50.0), 0.0)

    def test_triangle_follows_the_game_diagonal(self):
        # quad (0, 0): the peak is at its (row + 1, col + 1) corner, on the diagonal: z = min(east, south)
        self.assertAlmostEqual(grid().triangle(100.5, -49.5), 0.5)
        self.assertAlmostEqual(grid().bilinear(100.5, -49.5), 0.25)
        # quad (0, 1): the peak is at its (row + 1, col) corner, off the diagonal
        self.assertAlmostEqual(grid().triangle(101.5, -49.5), 0.0)
        self.assertAlmostEqual(grid().triangle(101.75, -49.75), 0.0)
        self.assertAlmostEqual(grid().triangle(101.25, -49.25), 0.5)

    def test_outside_is_nan(self):
        self.assertTrue(np.isnan(grid().triangle(99.0, -50.0)))
        self.assertTrue(np.isnan(grid().bilinear(103.0, -50.0)))

    def test_triangle_surface_is_the_same_rule_on_landscape_grids(self):
        gx = np.array([0.5, 1.5, 1.25, 1.0])
        gy = np.array([0.5, 0.5, 0.75, 1.0])
        np.testing.assert_allclose(landscape.triangle_surface(PEAK, gx, gy), [0.5, 0.0, 0.5, 1.0])
        self.assertTrue(np.isnan(landscape.triangle_surface(PEAK, np.array([-0.1]), np.array([0.0]))[0]))


class PointsTest(unittest.TestCase):
    def test_parses_a_map_in_metres_and_lowers_spawn_points(self):
        lines = io.StringIO("Fallujah_City Deployable:AmmoCrate_USA 10000.5 -2000 3000\n"
                            "Fallujah_City SpawnPoint:Team1SpawnPoint 0 0 188\n"
                            "Goose_Bay Deployable:AmmoCrate_USA 1 2 3\n")
        points = audit.parse_points(lines, "fallujah", "Fallujah")
        self.assertEqual(points[0], ("Deployable:AmmoCrate_USA", 100.005, -20.0, 30.0))
        self.assertEqual(len(points), 2)
        self.assertAlmostEqual(points[1][3], 1.0)

    def test_matches_folders_of_plugin_layers(self):
        self.assertTrue(audit.folder_matches("AlBasrah", "albasrah", "AlBasrah"))
        self.assertTrue(audit.folder_matches("Tallil_Outskirts", "tallil", "Tallil"))
        self.assertTrue(audit.folder_matches("Goose_Bay", "goosebay", "GooseBay"))
        self.assertFalse(audit.folder_matches("Kokan_Valley", "kohat", "Kohat"))

    def test_rejects_a_line_that_could_carry_a_name(self):
        with self.assertRaises(ValueError):
            audit.parse_points(io.StringIO("Fallujah_City BP_MapMarker_POI someone 1 2 3\n"), "fallujah", "Fallujah")
        with self.assertRaises(ValueError):
            audit.parse_points(io.StringIO("Fallujah_City Deployable:Name With Space 1 2 3\n"), "fallujah", "Fallujah")


class VerdictTest(unittest.TestCase):
    def verdict(self, **row):
        base = {"log_z": 10.0, "hm_triangle": 10.0, "terrain": 10.0, "grid_object": False, "object_top": -np.inf}
        return audit.verdict({**base, **row}, 0.15)

    def test_each_cause(self):
        self.assertEqual(self.verdict(), "ok")
        self.assertEqual(self.verdict(log_z=0.0), "no-trace")
        self.assertEqual(self.verdict(hm_triangle=float("nan")), "outside")
        self.assertEqual(self.verdict(hm_triangle=12.0), "sub-cell")
        self.assertEqual(self.verdict(hm_triangle=12.0, grid_object=True), "grid-object")
        self.assertEqual(self.verdict(log_z=14.0, hm_triangle=10.0, terrain=10.0, object_top=14.1), "object")
        self.assertEqual(self.verdict(log_z=14.0, hm_triangle=10.0), "above-terrain")
        self.assertEqual(self.verdict(log_z=5.0, hm_triangle=10.0), "below-terrain")


class AuditTest(unittest.TestCase):
    def test_a_flat_point_is_ok_and_summaries_print(self):
        rows = audit.audit(grid(), [("Deployable:X", 100.5, -49.5, 0.5), ("Deployable:Y", 100.5, -49.5, 0.0)])
        self.assertEqual([r["verdict"] for r in rows], ["ok", "no-trace"])
        self.assertAlmostEqual(rows[0]["hm_bilinear"], 0.25)
        out = io.StringIO()
        audit.report(rows, out)
        self.assertIn("verdicts: ok 1, no-trace 1", out.getvalue())


if __name__ == "__main__":
    unittest.main()
