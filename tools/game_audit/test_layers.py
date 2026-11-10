"""Tests of layers.py on a made-up level (no game data needed).

Run: python3 -m unittest discover -s tools/game_audit
"""
import gzip
import json
import os
import sys
import tempfile
import unittest
import warnings

import layers

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "heightmaps", "py"))

import minimap_corners  # noqa: E402


def reference(index):
    return {"ObjectName": "X'Level:PersistentLevel.Thing'", "ObjectPath": f"/Game/Maps/Level.{index}"}


def scene(name, outer=None, location=None, rotation=None, scale=None, parent=None, kind="SceneComponent", **properties):
    """A component export: relative transform, the actor that owns it and the component it is attached to."""
    values = dict(properties)
    for key, value, axes in (("RelativeLocation", location, "XYZ"), ("RelativeScale3D", scale, "XYZ")):
        if value is not None:
            values[key] = dict(zip(axes, value))
    if rotation is not None:
        values["RelativeRotation"] = dict(zip(("Pitch", "Yaw", "Roll"), rotation))
    if parent is not None:
        values["AttachParent"] = reference(parent)
    return {"Type": kind, "Name": name, "Outer": reference(outer) if outer is not None else None, "Properties": values}


# 0 world settings, 1-2 and 3-4 the two corner actors, 5-8 a capture zone, 9-11 a mirrored protection zone
LEVEL = [
    {"Type": "SQWorldSettings", "Name": "SQWorldSettings", "Properties": {
        "MapTextureCornerZero": reference(1), "MapTextureCornerOne": reference(3),
        "MapTexture": {"ObjectName": "Texture2D'Chora_Minimap'"}, "KillZ": -5000.0}},
    {"Type": "StaticMeshActor", "Name": "Corner0", "Properties": {"RootComponent": reference(2)}},
    scene("Root", outer=1, location=(-246400.0, -266400.0, 0.0), kind="StaticMeshComponent"),
    {"Type": "StaticMeshActor", "Name": "Corner1", "Properties": {"RootComponent": reference(4)}},
    scene("Root", outer=3, location=(159990.0, 140000.0, 0.0), kind="StaticMeshComponent"),
    {"Type": "BP_CaptureZone_C", "Name": "01-Village", "Properties": {"RootComponent": reference(6), "SQCaptureZone": reference(8)}},
    scene("DefaultSceneRoot", outer=5, location=(1000.0, 2000.0, 300.0), rotation=(0.0, 90.0, 0.0), scale=(2.0, 2.0, 1.0)),
    scene("Sphere", outer=5, location=(100.0, 0.0, 0.0), parent=6, kind="SphereComponent", SphereRadius=3000.0),
    {"Type": "SQCaptureZoneComponent", "Name": "SQCaptureZone", "Outer": reference(5), "Properties": {"FlagName": {"SourceString": "Village"}, "InitialTeam": 1}},
    {"Type": "Gameplay_TeamZone_C", "Name": "Team1ProtectionZone", "Properties": {"RootComponent": reference(10), "TeamId": 1}},
    scene("DefaultSceneRoot", outer=9, location=(-150000.0, -170000.0, -20000.0), scale=(-1.5, -1.5, -1.5759)),
    scene("Sphere", outer=9, parent=10, kind="SphereComponent", SphereRadius=15000.0, scale=(-20000.0, -20000.0, 1.0)),
    {"Type": "SQMapBoundary", "Name": "Boundary", "Properties": {"BoundaryMaskData": [0] * 64, "Resolution": 8}},
]


def close(test, actual, expected):
    for a, e in zip(actual, expected):
        test.assertAlmostEqual(a, e, places=6)


class Transforms(unittest.TestCase):
    def test_the_axes_of_a_rotator_follow_the_engine(self):
        close(self, layers.rotation_axes({"Yaw": 90.0})[0], (0.0, 1.0, 0.0))
        # A positive pitch raises the X axis, a positive roll lowers the Y axis
        close(self, layers.rotation_axes({"Pitch": 90.0})[0], (0.0, 0.0, 1.0))
        close(self, layers.rotation_axes({"Roll": 90.0})[1], (0.0, 0.0, -1.0))

    def test_a_point_is_scaled_then_turned_then_moved(self):
        close(self, layers.to_parent([100.0, 0.0, 0.0], [1000.0, 2000.0, 300.0], {"Yaw": 90.0}, [2.0, 2.0, 1.0]), (1000.0, 2200.0, 300.0))

    def test_a_component_is_placed_through_what_it_is_attached_to(self):
        level = layers.Level(LEVEL)
        close(self, level.world(7), (1000.0, 2200.0, 300.0))
        self.assertEqual(level.scale(7), [2.0, 2.0, 1.0])
        self.assertFalse(level.tilted(7))

    def test_an_absolute_location_ignores_the_parents(self):
        exports = [scene("Root", location=(500.0, 0.0, 0.0)), scene("Child", location=(7.0, 8.0, 9.0), parent=0, bAbsoluteLocation=True)]
        close(self, layers.Level(exports).world(1), (7.0, 8.0, 9.0))

    def test_a_pitched_parent_marks_the_shape_as_tilted(self):
        exports = [scene("Root", rotation=(12.0, 0.0, 0.0)), scene("Box", parent=0, kind="BoxComponent")]
        self.assertTrue(layers.Level(exports).tilted(1))

    def test_a_mirrored_sphere_has_the_radius_of_its_smallest_scale(self):
        self.assertAlmostEqual(layers.scaled_radius(15000.0, [31149.57, 31149.57, -1.57585875]), 23637.88, places=1)


class Reduce(unittest.TestCase):
    def setUp(self):
        self.layer = layers.reduce_layer({"path": "SquadGame/Content/Maps/Chora/Gameplay_Layers/Chora_AAS_v1.umap", "exports": LEVEL})

    def test_corners_and_texture_come_from_the_world_settings(self):
        self.assertEqual(self.layer["MapTextureCornerZero"], [-246400.0, -266400.0, 0.0])
        self.assertEqual(self.layer["MapTextureCornerOne"], [159990.0, 140000.0, 0.0])
        self.assertEqual(self.layer["texture"], "Texture2D'Chora_Minimap'")
        self.assertEqual(self.layer["world"], {"KillZ": -5000.0})

    def test_a_capture_zone_has_its_flag_position_and_shapes(self):
        (zone,) = self.layer["zones"]
        self.assertEqual((zone["type"], zone["name"], zone["flag"]), ("BP_CaptureZone_C", "01-Village", "Village"))
        self.assertEqual(zone["loc"], [1000.0, 2000.0, 300.0])
        (sphere,) = zone["shapes"]
        self.assertEqual((sphere["kind"], sphere["radius"], sphere["scale"]), ("SphereComponent", 3000.0, [2.0, 2.0, 1.0]))
        close(self, sphere["loc"], (1000.0, 2200.0, 300.0))

    def test_a_protection_zone_is_kept_apart_with_its_team(self):
        (zone,) = self.layer["protection"]
        self.assertEqual((zone["name"], zone["scalars"]["TeamId"]), ("Team1ProtectionZone", 1))

    def test_the_zone_table_gives_the_radius_in_the_world_and_the_default_lock_distance(self):
        zones = layers.protection_zones({"Chora_AAS_v1": self.layer}, 15000.0)
        self.assertEqual(zones, {"Chora_AAS_v1": {"Team1ProtectionZone": {"sphere_cm": 15000.0, "scale": [30000.0, 30000.0, -1.5759], "radius_cm": 23638.5, "lock_cm": 15000.0}}})

    def test_the_default_lock_distance_is_the_class_default_of_the_zone(self):
        blueprint = [{"Type": "BlueprintGeneratedClass", "Name": "Gameplay_TeamZone_C"},
                     {"Type": "Gameplay_TeamZone_C", "Name": "Default__Gameplay_TeamZone_C", "Properties": {"DeployableLockDistance": 15000.0}}]
        self.assertEqual(layers.default_lock_distance(blueprint), 15000.0)

    def test_the_corner_records_are_what_the_corner_table_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            corners, table = os.path.join(folder, "corners.ndjson"), os.path.join(folder, "game.json")
            with open(corners, "w", encoding="utf-8") as out:
                out.write("".join(json.dumps(record) + "\n" for record in layers.corner_records({"Chora_AAS_v1": self.layer})))
            with warnings.catch_warnings():
                # minimap_corners.py leaves its files to the garbage collector
                warnings.simplefilter("ignore", ResourceWarning)
                minimap_corners.table(corners, table)
            with open(table, encoding="utf-8") as source:
                result = json.load(source)
        self.assertEqual((result["Chora"]["min"], result["Chora"]["max"]), ([-2464.0, -2664.0], [1599.9, 1400.0]))


class Strip(unittest.TestCase):
    def test_the_mask_is_dropped_and_the_rest_kept_under_the_layers_name(self):
        with tempfile.TemporaryDirectory() as folder:
            dump = os.path.join(folder, "dump", "SquadGame", "Content", "Maps", "Chora", "Gameplay_Layers")
            os.makedirs(dump)
            with open(os.path.join(dump, "Chora_AAS_v1.umap.json"), "w", encoding="utf-8") as out:
                json.dump(LEVEL, out)
            self.assertEqual(layers.strip(os.path.join(folder, "dump"), os.path.join(folder, "layers")), 1)
            with gzip.open(os.path.join(folder, "layers", "Chora_AAS_v1.json.gz"), "rt", encoding="utf-8") as source:
                record = json.load(source)
            self.assertEqual(layers.reduce(os.path.join(folder, "layers"), os.path.join(folder, "game_layers.json")), 1)
        self.assertEqual(record["path"], "SquadGame/Content/Maps/Chora/Gameplay_Layers/Chora_AAS_v1.umap")
        boundary = next(export for export in record["exports"] if export["Type"] == "SQMapBoundary")
        self.assertEqual(boundary["Properties"], {"Resolution": 8})
        self.assertEqual(len(record["exports"]), len(LEVEL))


if __name__ == "__main__":
    unittest.main()
