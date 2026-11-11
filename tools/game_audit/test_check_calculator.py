"""Tests of the comparison rules of check_calculator.py on made-up calculator and game data.

Run: python3 -m unittest discover -s tools/game_audit
"""
import contextlib
import io
import json
import os
import tempfile
import unittest

import check_calculator as check

MOUNTS = {"Mortar": {"reading": [45.0, 88.8]}, "UB-32": {"reading": [-25.0, 35.0]}, "Tech.Mortar": {"reading": [40.0, 83.8]}, "BM-21Grad": {"reading": [14.2, 55.0]}}


def weapon(name, limits, angle_type, min_distance, low_stop, high_stop, offset=0, reach=2000.0, longest=2000.0):
    shell = {"name": "default", "minDistance": min_distance, "atLowStop": low_stop, "atHighStop": high_stop, "reach": reach, "maxRange": longest}
    return {"name": name, "minElevation": limits, "angleOffset": offset, "angleType": angle_type, "shells": [shell]}


def game_map(name, origin=(-2040.01, -2040.0), size=(4081, 4081), scale=(1.0, 1.0, 1.0), radius=400, corners=((-2000.0, -2000.0), (2000.0, 2000.0)), game=None):
    low, high = (list(corner) for corner in corners)
    return {"name": name, "radiusExclusion": radius, "heightmap": {"origin": list(origin), "size": list(size), "scale": list(scale)},
            "minimap": {"corner0": low, "corner1": high, "game": game or {"min": low, "max": high}}}


class Limits(unittest.TestCase):
    def test_limits_equal_to_the_reading_of_the_mount_pass(self):
        self.assertEqual(check.limit_differences([weapon("Mortar", [45, 88.8], "high", 51.8, 1236.9, 51.77)], MOUNTS), [])

    def test_the_old_mortar_top_is_a_difference(self):
        (difference,) = check.limit_differences([weapon("Mortar", [45, 88.875], "high", 51.0, 1236.9, 51.77)], MOUNTS)
        self.assertEqual(difference[:2], ("limits", "Mortar"))
        self.assertIn("88.875", difference[2])


class MinimumDistance(unittest.TestCase):
    def test_which_mounts_stop_the_barrel_short_of_the_near_ground(self):
        self.assertTrue(check.stopped_by_mount("high", 45.0, 88.8))
        self.assertFalse(check.stopped_by_mount("high", 10.0, 90.0))
        self.assertTrue(check.stopped_by_mount("low", 14.2, 55.0))
        self.assertTrue(check.stopped_by_mount("low", 0.0, 50.0))
        self.assertFalse(check.stopped_by_mount("low", -25.0, 35.0))

    def test_a_high_arc_weapon_takes_the_range_at_its_top_and_a_low_arc_one_at_its_bottom(self):
        weapons = [weapon("Mortar", [45, 88.8], "high", 51.8, 1236.9, 51.77), weapon("BM-21Grad", [14.2, 55], "low", 985.1, 985.09, 1921.8)]
        self.assertEqual(check.min_distance_differences(weapons, MOUNTS), [])

    def test_the_scale_offset_is_part_of_the_barrels_elevation(self):
        # 83.8 on the scale is 88.8 on the barrel, short of the vertical; a barrel 6.2 above the scale would reach it
        stopped = weapon("Tech.Mortar", [40, 83.8], "high", 51.8, 1238.1, 51.76, offset=5)
        self.assertEqual(check.min_distance_differences([stopped], MOUNTS), [])
        vertical = weapon("Tech.Mortar", [40, 83.8], "high", 51.8, 1238.1, 51.76, offset=6.2)
        (difference,) = check.min_distance_differences([vertical], MOUNTS)
        self.assertIn("does not stop it", difference[2])

    def test_a_minimum_that_is_not_the_range_at_the_stop_is_a_difference(self):
        (difference,) = check.min_distance_differences([weapon("Mortar", [45, 88.8], "high", 51.0, 1236.9, 51.77)], MOUNTS)
        self.assertEqual(difference[:2], ("min distance", "Mortar"))
        self.assertIn("51.77 m at the mount's stop 88.8 degrees", difference[2])

    def test_a_mount_that_reaches_the_ground_in_front_of_it_has_no_minimum(self):
        self.assertEqual(check.min_distance_differences([weapon("UB-32", [-25, 35], "low", 0, 3.4, 2082.4)], MOUNTS), [])
        (difference,) = check.min_distance_differences([weapon("UB-32", [-25, 35], "low", 10, 3.4, 2082.4)], MOUNTS)
        self.assertIn("the mount does not stop it: 0", difference[2])


class Ranges(unittest.TestCase):
    def test_a_longest_shot_beyond_the_mounts_reach_is_reported(self):
        (difference,) = check.reach_differences([weapon("UB-32", [-25, 35], "low", 0, 3.4, 2082.4, reach=2082.44, longest=2184.33)])
        self.assertEqual(difference, ("reach", "UB-32", "longest shot 2184 m, 2082 m with the mount's pitch range"))
        self.assertEqual(check.reach_differences([weapon("Mortar", [45, 88.8], "high", 51.8, 1236.9, 51.77, reach=1236.94, longest=1236.94)]), [])

    def test_a_marker_circle_is_the_longest_shot_in_whole_metres(self):
        circles = {"Mortar": {"radius": 1237, "maxRange": 1236.94}, "HellCannon": {"radius": 923, "maxRange": 924.43}}
        self.assertEqual(check.circle_differences(circles), [("circle", "HellCannon", "range circle 923 m, longest shot 924.43 m")])


class Landscapes(unittest.TestCase):
    GAME = {"AlBasrah": {"origin_m": [-2040.01, -2040.0], "size_vertices": [4081, 4081], "scale_m": [1.0, 1.0, 1.0]}}

    def test_an_origin_to_the_millimetre_passes_and_one_a_centimetre_off_is_reported(self):
        self.assertEqual(check.landscape_differences([game_map("AlBasrah")], self.GAME), [])
        (difference,) = check.landscape_differences([game_map("AlBasrah", origin=(-2040.0, -2040.0))], self.GAME)
        self.assertIn("origin [-2040.0, -2040.0]", difference[2])

    def test_origin_size_and_scale_are_each_reported(self):
        (difference,) = check.landscape_differences([game_map("AlBasrah", origin=(-2040, -2802), size=(4080, 4081), scale=(1, 1, 1.2))], self.GAME)
        for part in ("origin [-2040, -2802]", "size [4080, 4081]", "scale [1, 1, 1.2]"):
            self.assertIn(part, difference[2])

    def test_a_map_the_game_data_lacks_is_reported(self):
        self.assertEqual(check.landscape_differences([game_map("Belaya")], self.GAME)[0][:2], ("landscape", "Belaya"))


class Corners(unittest.TestCase):
    GAME = {"BlackCoast": {"min": [-2300.0, -2127.47], "max": [2299.98, 2472.51]}}

    def test_image_corners_within_a_metre_and_exact_game_corners_pass(self):
        entry = game_map("BlackCoast", corners=((-2299, -2127), (2299, 2472)), game=self.GAME["BlackCoast"])
        self.assertEqual(check.corner_differences([entry], self.GAME), [])

    def test_game_corners_off_by_a_centimetre_and_an_image_ten_metres_off_are_two_differences(self):
        entry = game_map("BlackCoast", corners=((-2310, -2127), (2299, 2472)), game={"min": [-2300.0, -2127.48], "max": [2299.98, 2472.51]})
        self.assertEqual([difference[0] for difference in check.corner_differences([entry], self.GAME)], ["game corners", "image corners"])

    def test_swapped_image_corners_are_the_same_rectangle(self):
        entry = game_map("BlackCoast", corners=((2299, 2472), (-2299, -2127)), game=self.GAME["BlackCoast"])
        self.assertEqual(check.corner_differences([entry], self.GAME), [])


class FobRadius(unittest.TestCase):
    FOB = {"rows": {"01_Small": {"exclusion_m": 300.0}, "02_Medium": {"exclusion_m": 400.0}},
           "layers": {"AlBasrah_RAAS_v1": "02_Medium", "AlBasrah_RAAS_v3": "01_Small", "Chora_AAS_v1": "01_Small", "Tutorial_Infantry": "01_Small"}}
    MAPS = [game_map("AlBasrah", radius=400), game_map("Chora", radius=300)]

    def test_the_layers_radius_is_the_small_one_when_listed_and_the_maps_otherwise(self):
        self.assertEqual(check.fob_differences(self.MAPS, ["AlBasrah_RAAS_v3"], self.FOB), [])

    def test_a_small_layer_that_is_not_listed_draws_the_maps_radius(self):
        self.assertEqual(check.fob_differences(self.MAPS, [], self.FOB), [("fob radius", "AlBasrah_RAAS_v3", "exclusion radius 400 m, the game's 300 m (row 01_Small)")])

    def test_a_listed_layer_the_game_does_not_have_is_reported(self):
        self.assertIn(("fob radius", "AlBasrah_Seed_v9", "listed in SMALL_FOB_LAYERS, not a layer of the game"), check.fob_differences(self.MAPS, ["AlBasrah_RAAS_v3", "AlBasrah_Seed_v9"], self.FOB))

    def test_a_layer_of_a_map_the_calculator_lacks_is_not_compared(self):
        self.assertIsNone(check.map_of("Tutorial_Infantry", ["AlBasrah", "Chora"]))
        self.assertEqual(check.map_of("AlBasrah_RAAS_v3", ["AlBasrah", "Chora"]), "AlBasrah")


class ExitStatus(unittest.TestCase):
    def run_check(self, calculator):
        data = {"source": {"squad_dedicated_server_build": "26005357"}, "mount_limits": MOUNTS, "landscapes": Landscapes.GAME,
                "minimap_corners": {"AlBasrah": {"min": [-2000.0, -2000.0], "max": [2000.0, 2000.0]}}, "fob_radius": FobRadius.FOB}
        with tempfile.TemporaryDirectory() as folder:
            for name, content in data.items():
                with open(os.path.join(folder, name + ".json"), "w", encoding="utf-8") as out:
                    json.dump(content, out)
            with open(os.path.join(folder, "calculator.json"), "w", encoding="utf-8") as out:
                json.dump(calculator, out)
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                status = check.main(["check_calculator.py", os.path.join(folder, "calculator.json"), folder])
        return status, printed.getvalue()

    def calculator(self, **changes):
        return {"version": "45.40.0", "circles": {"Mortar": {"radius": 1237, "maxRange": 1236.94}}, "maps": [game_map("AlBasrah")], "smallFobLayers": ["AlBasrah_RAAS_v3"],
                "weapons": [weapon("UB-32", [-25, 35], "low", 0, 3.4, 2082.4, reach=2082.44, longest=2184.33)], **changes}

    def test_a_known_difference_is_printed_and_does_not_fail(self):
        status, printed = self.run_check(self.calculator())
        self.assertEqual(status, 0)
        self.assertIn("KNOWN reach: UB-32", printed)
        self.assertIn("0 differences, 1 known", printed)

    def test_an_unexplained_difference_fails(self):
        status, printed = self.run_check(self.calculator(smallFobLayers=[]))
        self.assertEqual(status, 1)
        self.assertIn("DIFFERS fob radius: AlBasrah_RAAS_v3", printed)
        self.assertIn("1 differences, 1 known", printed)


if __name__ == "__main__":
    unittest.main()
