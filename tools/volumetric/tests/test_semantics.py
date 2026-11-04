"""Tests of tools/volumetric/semantics on synthetic inputs. Run: python -m unittest discover tests (from tools/volumetric)."""

import json
import os
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "semantics"))
sys.path.insert(0, os.path.join(HERE, "..", "py"))
sys.path.insert(0, os.environ.get("HEIGHTMAPS_PY", os.path.join(HERE, "..", "..", "heightmaps", "py")))

import building_interiors  # noqa: E402
import class_table  # noqa: E402
import materials  # noqa: E402
import projectile_profiles  # noqa: E402
import static_semantics  # noqa: E402


def response(channel, value):
    return {"CollisionResponses": {"ResponseArray": [{"Channel": channel, "Response": "ECR_" + value}]}}


class StaticSemanticsTest(unittest.TestCase):
    def test_unlisted_channel_blocks(self):
        self.assertEqual(static_semantics.effective({"CollisionProfileName": "BlockAll"}, None, "Projectile"), "Block")

    def test_component_override_beats_mesh_default(self):
        default = response("Projectile", "Ignore")
        self.assertEqual(static_semantics.effective(None, default, "Projectile"), "Ignore")
        self.assertEqual(static_semantics.effective(response("Projectile", "Overlap"), default, "Projectile"), "Overlap")

    def test_no_collision_ignores_everything(self):
        self.assertEqual(static_semantics.effective({"CollisionEnabled": "ECollisionEnabled::NoCollision"}, None, "Projectile"), "Ignore")
        self.assertEqual(static_semantics.effective({"CollisionProfileName": "NoCollision"}, None, "Pawn"), "Ignore")

    def test_shapes_names(self):
        body = {"Properties": {"AggGeom": {"ConvexElems": [1], "BoxElems": [1], "SphereElems": []}}}
        self.assertEqual(static_semantics.shapes(body), "convex+box")
        self.assertEqual(static_semantics.shapes(None), "none")


class ProjectileProfilesTest(unittest.TestCase):
    def blueprints(self):
        return {
            "/Game/A": ("Class'SQProjectile'", "/Script/Squad", None),
            "/Game/B": ("BP_A_C'Default__BP_A_C'", "/Game/A", {"CollisionProfileName": "Custom"}),
            "/Game/C": ("BP_B_C'Default__BP_B_C'", "/Game/B", None),
            "/Game/G": ("Class'SQGrenadeProjectile'", "/Script/Squad", None),
            "/Game/Other": ("Class'SQWeapon'", "/Script/Squad", None),
        }

    def test_native_default_and_override(self):
        rows = {r["bp"]: r for r in projectile_profiles.resolve(self.blueprints())}
        self.assertEqual(rows["/Game/A"]["profile"], "Projectile")
        self.assertEqual(rows["/Game/B"]["profile"], "Custom")
        self.assertEqual(rows["/Game/C"]["profile"], "Custom")
        self.assertEqual(rows["/Game/G"]["profile"], "Throwable")
        self.assertNotIn("/Game/Other", rows)


class MaterialsTest(unittest.TestCase):
    def test_missing_modifiers_stay_null_and_properties_map(self):
        with tempfile.TemporaryDirectory() as dump:
            folder = os.path.join(dump, "SquadGame", "Content", "Environments", "PhysicalMaterials")
            os.makedirs(folder)
            export = {"Type": "SQPhysicalMaterial", "Name": "PhysMat_X", "Package": "/Game/X",
                      "Properties": {"DamageAbsorbed": 20.0, "SurfaceType": "SurfaceType5"}}
            json.dump([export], open(os.path.join(folder, "PhysMat_X.uasset.json"), "w"))
            found = materials.physical_materials(dump)
        self.assertEqual(found["PhysMat_X"]["damage_absorbed"], 20.0)
        self.assertIsNone(found["PhysMat_X"]["lethality_modifier"])
        self.assertIsNone(found["PhysMat_X"]["splash_radius_modifier"])
        self.assertNotIn("armor_thickness_mm", found["PhysMat_X"])


def room(window):
    """A 6 x 6 x 3 m room (0.2 m walls, floor slab, flat roof) as a triangle soup; optional 1 x 1 m window in the +x wall."""
    from test_volumetric import box
    parts = [box((0, 0, 0), (6, 6, 0.2)), box((0, 0, 3), (6, 6, 3.2)), box((0, 0, 0.2), (0.2, 6, 3)),
             box((0, 0, 0.2), (6, 0.2, 3)), box((0, 5.8, 0.2), (6, 6, 3))]
    if not window:
        return np.concatenate(parts + [box((5.8, 0, 0.2), (6, 6, 3))])
    return np.concatenate(parts + [box((5.8, 0, 0.2), (6, 2.5, 3)), box((5.8, 3.5, 0.2), (6, 6, 3)),
                                   box((5.8, 2.5, 0.2), (6, 3.5, 1.2)), box((5.8, 2.5, 2.2), (6, 3.5, 3))])


def occupancy(tris):
    points, up = building_interiors.surface_samples(tris.astype(float))
    idx = np.floor((points + 1.0) / building_interiors.CELL).astype(int)
    occ = np.zeros(idx.max(0) + 2, bool)
    upgrid = np.zeros_like(occ)
    occ[tuple(idx.T)] = True
    upgrid[tuple(idx[up].T)] = True
    return occ, upgrid


class BuildingInteriorsTest(unittest.TestCase):
    def test_sealed_room_has_floor_area_and_no_opening(self):
        occ, up = occupancy(room(window=False))
        cells = building_interiors.room_floor_cells(occ, up, 0)
        area = len(cells) * building_interiors.CELL ** 2
        self.assertGreater(area, 20)
        self.assertLess(area, 36)
        self.assertEqual(building_interiors.fan_openings(occ, np.array([4.0, 4.0, 1.7]), 1.2), [])

    def test_window_is_found_with_its_size(self):
        occ, up = occupancy(room(window=True))
        found = building_interiors.fan_openings(occ, np.array([1.0 + 3.0, 1.0 + 3.0, 1.0 + 1.7]), 1.0 + 0.2)
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0]["width"], 1.0, delta=0.4)
        self.assertAlmostEqual(found[0]["height"], 1.0, delta=0.4)
        self.assertAlmostEqual(found[0]["sill"], 1.0, delta=0.4)


class ClassTableTest(unittest.TestCase):
    def test_classify_and_weighting(self):
        self.assertEqual(class_table.classify("/Game/Environments/MiddleEast/Buildings/A/SM_X.SM_X"), "buildings")
        self.assertEqual(class_table.classify("/Game/Environments/Roads/Meshes/R.R"), "roads_and_pavements")
        self.assertEqual(class_table.classify("/Game/Unknown/Q.Q"), "other")
        kinds = {"meshes": [
            {"path": "/Game/Environments/MiddleEast/Buildings/A.A", "trace_flag": "UseDefault",
             "complex_triangles": 10, "simple_triangles": 2, "placements": 3},
            {"path": "/Game/Environments/MiddleEast/Buildings/B.B", "trace_flag": "UseComplexAsSimple",
             "complex_triangles": 5, "simple_triangles": 0, "placements": 1}]}
        row = class_table.build(kinds)["buildings"]
        self.assertEqual((row["meshes"], row["placements"]), (2, 4))
        self.assertEqual((row["complex_triangles_placed"], row["simple_triangles_placed"]), (35, 6))
        self.assertEqual(row["flag_UseDefault"], 1)


if __name__ == "__main__":
    unittest.main()
