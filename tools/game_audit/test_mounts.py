"""Tests of mounts.py on small made-up dumps, and of the committed data/mount_limits.json against its own rules.

Run: python3 -m unittest discover -s tools/game_audit
"""
import json
import math
import os
import re
import tempfile
import unittest

import mounts

HERE = os.path.dirname(os.path.abspath(__file__))


def blueprint(name, parent=None, exports=()):
    """Exports of a dumped Blueprint class ``name`` deriving from the Blueprint asset ``parent`` (None: a native class)."""
    super_path = f"/Game/{parent}.0" if parent else "/Script/Squad"
    return [{"Type": "BlueprintGeneratedClass", "Name": name + "_C", "Super": {"ObjectName": "Class'X'", "ObjectPath": super_path}}, *exports]


def movement(name, pitch=None, **properties):
    constraints = {"RotationConstraints": {"PitchInterval": {"X": pitch[0], "Y": pitch[1]}}} if pitch else {}
    return {"Type": "SQTurretMovementComponent", "Name": name + "_GEN_VARIABLE", "Properties": {**constraints, **properties}}


def component(name, pitch=None):
    properties = {"RelativeRotation": {"Pitch": pitch, "Yaw": 0.0, "Roll": 0.0}} if pitch is not None else {"RelativeLocation": {"X": 1.0}}
    return {"Type": "CameraComponent", "Name": name + "_GEN_VARIABLE", "Properties": properties}


def pitched(degrees):
    """Quaternion of a rotation that raises the X axis by ``degrees``, in the engine's convention."""
    half = math.radians(degrees) / 2
    return {"X": 0.0, "Y": -math.sin(half), "Z": 0.0, "W": math.cos(half)}


def skeleton(socket_rotation=None):
    socket = {"SocketName": "Attach_Muzzle", "BoneName": "pitch_swivel"}
    if socket_rotation:
        socket["RelativeRotation"] = socket_rotation
    return [
        {"Type": "SkeletalMeshSocket", "Name": "SkeletalMeshSocket_0", "Properties": socket},
        {"Type": "Skeleton", "Name": "SKEL", "ReferenceSkeleton": {
            "FinalRefBoneInfo": [{"Name": "root", "ParentIndex": -1}, {"Name": "pitch_swivel", "ParentIndex": 0}, {"Name": "arm", "ParentIndex": 1}],
            "FinalRefBonePose": [{"Rotation": pitched(14.2)}, {"Rotation": pitched(0.0)}, {"Rotation": pitched(30.0)}]}},
    ]


class Dump:
    """A temporary dump root holding the given assets."""

    def __init__(self, assets):
        self.folder = tempfile.TemporaryDirectory()
        for asset, exports in assets.items():
            path = os.path.join(self.folder.name, mounts.CONTENT + asset + ".uasset.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as out:
                json.dump(exports, out)

    def __enter__(self):
        return self.folder.name

    def __exit__(self, *error):
        self.folder.cleanup()


class PitchInterval(unittest.TestCase):
    def test_a_class_without_a_range_keeps_its_parents(self):
        with Dump({"V/Tripod": blueprint("Tripod", "V/Generic", [movement("SQTurretMovement", MaxPitchSpeed=10.0)]),
                   "V/Generic": blueprint("Generic", None, [movement("SQTurretMovement", (-25.0, 35.0))])}) as root:
            pitch, asset, found = mounts.pitch_interval(root, "V/Tripod")
        self.assertEqual((pitch, asset, found["Name"]), ([-25.0, 35.0], "V/Generic", "SQTurretMovement_GEN_VARIABLE"))

    def test_a_class_that_sets_a_range_overrides_its_parent_and_the_parent_need_not_be_dumped(self):
        with Dump({"V/Turret": blueprint("Turret", "V/NotDumped", [movement("PitchMovement", (0.0, 40.8)), movement("YawMovement")])}) as root:
            self.assertEqual(mounts.pitch_interval(root, "V/Turret")[0], [0.0, 40.8])

    def test_a_parent_the_dump_lacks_is_named(self):
        with Dump({"V/Turret": blueprint("Turret", "V/Generic")}) as root:
            with self.assertRaisesRegex(FileNotFoundError, "V/Generic"):
                mounts.pitch_interval(root, "V/Turret")

    def test_a_native_parent_ends_the_search_with_an_error(self):
        with Dump({"V/Turret": blueprint("Turret")}) as root:
            with self.assertRaisesRegex(ValueError, "no PitchInterval"):
                mounts.pitch_interval(root, "V/Turret")

    def test_two_ranges_in_one_class_are_not_guessed_between(self):
        with Dump({"V/Turret": blueprint("Turret", None, [movement("A", (0.0, 1.0)), movement("B", (0.0, 2.0))])}) as root:
            with self.assertRaisesRegex(ValueError, "2 components"):
                mounts.pitch_interval(root, "V/Turret")


class Sight(unittest.TestCase):
    def test_a_component_overridden_without_a_rotation_keeps_the_parents_pitch(self):
        with Dump({"V/BTR4": blueprint("BTR4", "V/BMP1TS", [component("FirstPersonCamera")]),
                   "V/BMP1TS": blueprint("BMP1TS", None, [component("FirstPersonCamera", 0.1)])}) as root:
            self.assertEqual(mounts.component_pitch(root, "V/BTR4", "FirstPersonCamera"), (0.1, "V/BMP1TS"))

    def test_the_rest_pitch_of_a_bone_is_composed_from_the_root_down(self):
        degrees, bone = mounts.bone_pitch(skeleton(), "Attach_Muzzle")
        self.assertEqual(bone, "pitch_swivel")
        self.assertAlmostEqual(degrees, 14.2, places=9)

    def test_a_socket_turned_on_its_bone_is_refused(self):
        with self.assertRaisesRegex(ValueError, "turned on its bone"):
            mounts.bone_pitch(skeleton({"Pitch": 3.0, "Yaw": 0.0, "Roll": 0.0}), "Attach_Muzzle")

    def test_a_missing_socket_is_named(self):
        with self.assertRaisesRegex(ValueError, "Muzzle2"):
            mounts.bone_pitch(skeleton(), "Muzzle2")

    def test_a_statement_a_widget_lost_fails_the_evidence(self):
        widget = [{"Type": "Function", "Name": "Show", "ScriptBytecode": [{"Token": "EX_Return", "Expression": {"Token": "EX_Nothing"}}]}]
        with Dump({"W/Reticle": widget}) as root:
            mounts.check_evidence(root, [("W/Reticle", "Show", "return none")])
            with self.assertRaisesRegex(ValueError, "no longer contains"):
                mounts.check_evidence(root, [("W/Reticle", "Show", "BreakRotator(Camera Rotation)")])

    def test_yaw_curves_are_read_where_the_range_is(self):
        curve = [{"Type": "CurveFloat", "Name": "FC", "Properties": {"FloatCurve": {"Keys": [{"Time": -130.0, "Value": 9.5e-07}, {"Time": 140.0, "Value": 15.0}]}}}]
        with Dump({"V/Curves/FC_YawToMinPitch": curve}) as root:
            properties = {"ParentYawToMinPitch": {"ObjectName": "CurveFloat'FC'", "ObjectPath": "/Game/V/Curves/FC_YawToMinPitch.0"}}
            self.assertEqual(mounts.yaw_curves(root, properties), {"min": [[-130.0, 0.0], [140.0, 15.0]]})
            self.assertIsNone(mounts.yaw_curves(root, {}))


class Assets(unittest.TestCase):
    def test_the_regex_takes_the_named_assets_and_the_pitch_curves_of_the_turrets_only(self):
        pattern = re.compile(mounts.assets_regex(), re.IGNORECASE)
        for asset in mounts.assets():
            self.assertTrue(pattern.search(mounts.CONTENT + asset + ".uasset"), asset)
        self.assertTrue(pattern.search("SquadGame/Content/Vehicles/M1064A3/Curves/FC_M1064A3_YawToMinPitch.uasset"))
        self.assertFalse(pattern.search("SquadGame/Content/Vehicles/BTR4/Curves/FC_WaterAlphaDrag_BTR4.uasset"))
        self.assertFalse(pattern.search("SquadGame/Content/Vehicles/BP_GenericDeployableMortarVehicle_Old.uasset"))
        self.assertFalse(pattern.search("SquadGame/Content/Vehicles/M1064A3/Turrets/BP_M1064A3_MortarTurret.umap"))

    def test_every_listed_parent_is_part_of_the_dump(self):
        named = mounts.assets()
        for mount in mounts.MOUNTS.values():
            for parent in mount["blueprints"]:
                self.assertIn(parent, named)


class CommittedData(unittest.TestCase):
    """data/mount_limits.json is what ``read`` writes: every weapon of MOUNTS, the reading = pitch + sight offset."""

    def setUp(self):
        with open(os.path.join(HERE, "data", "mount_limits.json"), encoding="utf-8") as source:
            self.data = json.load(source)

    def test_every_mount_is_in_the_file(self):
        self.assertEqual(list(self.data), list(mounts.MOUNTS))

    def test_the_reading_is_the_pitch_plus_the_parts_of_the_sight(self):
        for weapon, mount in self.data.items():
            offset = sum(part["degrees"] for part in mount["sight"])
            self.assertAlmostEqual(mount["sight_offset"], offset, places=3, msg=weapon)
            for end in (0, 1):
                self.assertAlmostEqual(mount["reading"][end], mount["pitch"][end] + offset, places=3, msg=weapon)


if __name__ == "__main__":
    unittest.main()
