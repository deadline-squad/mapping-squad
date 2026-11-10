"""Tests of landscapes.py on made-up landscape extractions (no game data needed).

Run: python3 -m unittest discover -s tools/game_audit
"""
import json
import os
import tempfile
import unittest

import landscapes


def write_level(directory, actor, location, scale, quads, offsets, yaw=None):
    """One extracted level: the actor's root component and a collision component at each offset (in quads)."""
    os.makedirs(directory, exist_ok=True)
    outer = {"ObjectName": f"Landscape'Level:PersistentLevel.{actor}'"}
    root = {"RelativeLocation": dict(zip("XYZ", location)), "RelativeScale3D": dict(zip("XYZ", scale))}
    if yaw is not None:
        root["RelativeRotation"] = {"Pitch": 0.0, "Yaw": yaw, "Roll": 0.0}
    with open(os.path.join(directory, f"root_{actor}.RootComponent0.json"), "w", encoding="utf-8") as out:
        json.dump({"Type": "SceneComponent", "Outer": outer, "Properties": root}, out)
    for index, (x, y) in enumerate(offsets):
        properties = {"CollisionSizeQuads": quads, "RelativeLocation": {"X": float(x), "Y": float(y), "Z": 0.0}}
        with open(os.path.join(directory, f"LandscapeHeightfieldCollisionComponent_{actor}_{index}.json"), "w", encoding="utf-8") as out:
            json.dump({"Type": "LandscapeHeightfieldCollisionComponent", "Outer": outer, "Properties": properties}, out)


class Actor(unittest.TestCase):
    def read(self, **level):
        with tempfile.TemporaryDirectory() as folder:
            write_level(folder, "Landscape_0", **level)
            (actor,) = landscapes.read_level(folder).values()
        return actor

    def test_components_that_start_south_of_the_actor_move_the_origin(self):
        # Chora: the actor at -2664 m, the first component 1524 quads of 0.5 m further south
        actor = self.read(location=(-246400.0, -266400.0, 100.0), scale=(50.0, 50.0, 400.0), quads=254, offsets=[(0, 1524), (254, 1524), (0, 1778)])
        described = landscapes.describe("Chora", "Landscape_0", actor)
        self.assertEqual(described["origin_m"], [-2464.0, -1902.0])
        self.assertEqual(described["location_m"], [-2464.0, -2664.0, 1.0])
        self.assertEqual((described["first_quad"], described["size_vertices"], described["components"]), ([0, 1524], [509, 509], 3))
        self.assertEqual(described["scale_m"], [0.5, 0.5, 4.0])

    def test_a_turned_actor_turns_the_offset_of_its_first_component(self):
        # Skorpo: 508 x 1524 quads of 1.2 m from the actor, turned by -2.006195 degrees
        actor = self.read(location=(-481127.25, -394791.78, 39300.0), scale=(120.0, 120.0, 350.0), quads=127, offsets=[(508, 1524)], yaw=-2.006195)
        origin = landscapes.describe("Skorpo_Baselayer", "Uskedal", actor)["origin_m"]
        self.assertAlmostEqual(origin[0], -4138.02, places=2)
        self.assertAlmostEqual(origin[1], -2141.58, places=2)

    def test_an_actor_without_components_is_not_a_landscape(self):
        with tempfile.TemporaryDirectory() as folder:
            write_level(folder, "Landscape_0", location=(0.0, 0.0, 0.0), scale=(100.0, 100.0, 100.0), quads=63, offsets=[])
            self.assertEqual(landscapes.read_level(folder), {})


class Join(unittest.TestCase):
    PROXIES = [
        {"origin_m": [-2040.0, -2040.0], "size_vertices": [2041, 4081], "scale_m": [1.0, 1.0, 1.0], "yaw": 0.0},
        {"origin_m": [0.0, -2040.0], "size_vertices": [2041, 4081], "scale_m": [1.0, 1.0, 1.0], "yaw": 0.0},
        {"origin_m": [-510.0, 0.0], "size_vertices": [511, 511], "scale_m": [1.0, 1.0, 1.0], "yaw": 0.0},
    ]

    def test_one_actor_is_the_landscape(self):
        self.assertEqual(landscapes.landscape(self.PROXIES[:1]), self.PROXIES[0])

    def test_streaming_proxies_are_joined_into_the_rectangle_they_cover(self):
        self.assertEqual(landscapes.landscape(self.PROXIES), {"origin_m": [-2040.0, -2040.0], "size_vertices": [4081, 4081], "scale_m": [1.0, 1.0, 1.0], "yaw": 0.0})

    def test_actors_of_different_scales_or_a_turned_one_are_not_joined(self):
        with self.assertRaises(ValueError):
            landscapes.landscape([self.PROXIES[0], {**self.PROXIES[1], "scale_m": [0.5, 0.5, 1.0]}])
        with self.assertRaises(ValueError):
            landscapes.landscape([self.PROXIES[0], {**self.PROXIES[1], "yaw": 2.0}])


class Maps(unittest.TestCase):
    def test_a_map_without_an_extracted_landscape_is_an_error(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(FileNotFoundError):
                landscapes.read(folder)


if __name__ == "__main__":
    unittest.main()
