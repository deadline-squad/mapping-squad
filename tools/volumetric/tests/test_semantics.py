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
import window_demo  # noqa: E402
import materials  # noqa: E402
import primitive_counts  # noqa: E402
import projectile_profiles  # noqa: E402
import static_semantics  # noqa: E402
import structure_damage  # noqa: E402


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


class WindowDemoTest(unittest.TestCase):
    @staticmethod
    def quad(y0, y1):
        a, b, c, d = [0, y0, 0], [0, y1, 0], [0, y1, 2], [0, y0, 2]
        return [[a, b, c], [a, c, d]]

    def test_glass_blocks_and_wall_is_open_behind_it(self):
        walls = self.quad(-3, -1) + self.quad(1, 3)
        glass = self.quad(-1, 1)
        tris = np.array(walls + glass, float) * 100.0
        ranges = [(0, 4, False), (4, 6, True)]
        result = window_demo.run(tris, ranges, None)
        self.assertEqual(result["glass_triangles"], 2)
        self.assertEqual(result["glass_triangles_blocking"], 2)
        self.assertEqual(result["segments_through_open_wall"], 2)
        self.assertEqual(result["segments_with_wall_hit"], 0)

    def test_section_ranges_follow_listed_order(self):
        row = {"sections": [{"MaterialIndex": 1, "NumTriangles": 4, "bEnableCollision": True},
                            {"MaterialIndex": 0, "NumTriangles": 6, "bEnableCollision": True}],
               "materials": [{"physMaterial": "/x/PhysMat_Brick"}, {"physMaterial": "/x/PhysMat_GlassWindow"}]}
        self.assertEqual(window_demo.section_ranges(row), [(0, 4, True), (4, 10, False)])

class StructureDamageTests(unittest.TestCase):
    def test_short_names_a_blueprint_and_a_native_class(self):
        self.assertEqual(structure_damage.short({"ObjectName": "BlueprintGeneratedClass'BP_X_C'", "ObjectPath": "/Game/Gameplay/DamageTypes/BP_X.0"}), "BP_X")
        self.assertEqual(structure_damage.short({"ObjectName": "Class'SQDamageType_Thermite'", "ObjectPath": "/Script/Squad"}), "SQDamageType_Thermite")
        self.assertIsNone(structure_damage.short(None))

    def test_damage_table_keeps_the_multipliers_of_each_type(self):
        entry = {"DamageTypeClass": {"ObjectName": "x", "ObjectPath": "/Game/Gameplay/DamageTypes/BP_Kinetic_DamageType.0"},
                 "Modifier": 0.005, "DirectHitDamageMultiplier": 1.0, "IndirectHitDamageMultiplier": 0.2, "DirectHitRadialDamageMultiplier": 0.0, "Unrelated": 3}
        table = structure_damage.damage_table({"AllowableDamageTypes": [entry]})
        self.assertEqual(table, {"BP_Kinetic_DamageType": {"Modifier": 0.005, "DirectHitDamageMultiplier": 1.0,
                                                            "IndirectHitDamageMultiplier": 0.2, "DirectHitRadialDamageMultiplier": 0.0}})
        self.assertEqual(structure_damage.damage_table({}), {})

    def test_physical_triangles_apply_the_slot_material_then_the_body_material(self):
        mesh = {"sections": [{"MaterialIndex": 0, "NumTriangles": 30}, {"MaterialIndex": 1, "NumTriangles": 10}],
                "materials": [{"physMaterial": "/Game/PhysicalMaterials/PhysMat_Sandbag.PhysMat_Sandbag"}, {"physMaterial": None}],
                "bodyPhysMaterial": "/Game/PhysicalMaterials/PhysMat_Dirt.PhysMat_Dirt"}
        self.assertEqual(dict(structure_damage.physical_triangles("/nonexistent", mesh, [])), {"PhysMat_Sandbag": 30, "PhysMat_Dirt": 10})

    def test_export_groups_structures_with_the_same_table_and_skips_those_without_one(self):
        entry = {"Modifier": 0.5, "DirectHitDamageMultiplier": 1.0, "IndirectHitDamageMultiplier": 1.0, "DirectHitRadialDamageMultiplier": 1.0}
        row = {"max_health": 100.0, "damage_types": {"BP_Fragmentation_DamageType": entry}}
        data = {"deployables": {"A": row, "B": dict(row), "C": {"max_health": 100.0, "damage_types": {}}, "D": {"max_health": None, "damage_types": {}}},
                "projectiles": {"BP_P": {"weapons": ["W"], "damage_type": "BP_Fragmentation_DamageType", "native_defaults_used": [], "ExplosiveBaseDamage": 10.0,
                                         "ExplosiveDamageInnerRadius": 100.0, "ExplosiveDamageOuterRadius": 500.0, "ExplosiveDamageFalloff": 1.0,
                                         "ExplosiveDamageDistanceFromImpactNormal": 8.0, "ImpactDamageToApply": 5.0}}}
        with tempfile.TemporaryDirectory() as tmp:
            source, target = os.path.join(tmp, "in.json"), os.path.join(tmp, "out.js")
            json.dump(data, open(source, "w"))
            structure_damage.export_command(source, target)
            text = open(target, newline="").read()
        self.assertIn('classes: ["A", "B"]', text)
        self.assertNotIn('"C"', text)
        self.assertIn("explosion: { damage: 10, inner: 1, outer: 5, falloff: 1, distanceFromImpact: 0.08 }", text)
        self.assertIn("\r\n", text)


if __name__ == "__main__":
    unittest.main()


class PrimitiveCountsTests(unittest.TestCase):
    """BodySetup primitives weighted by placement."""

    def write_map(self, directory, bodies, instances):
        os.makedirs(os.path.join(directory, "bodies"))
        for mesh, body in bodies.items():
            json.dump({"path": "/Game/" + mesh, "body": body}, open(os.path.join(directory, "bodies", mesh + ".json"), "w"))
        with open(os.path.join(directory, "instances.ndjson"), "w") as handle:
            for item in instances:
                handle.write(json.dumps(item) + "\n")

    def test_counts_are_weighted_by_placements_and_instances(self):
        with tempfile.TemporaryDirectory() as directory:
            body = {"Properties": {"AggGeom": {"BoxElems": [{}, {}], "SphylElems": [{}], "ConvexElems": [{}]}}}
            self.write_map(directory, {"1": body, "2": {"Properties": {}}}, [
                {"mesh": "1", "instances": [{}, {}, {}]},
                {"mesh": "1"},
                {"mesh": "2"},
                {"mesh": "3"},
            ])
            result = primitive_counts.summarize(directory)
        self.assertEqual(result["totals"], {"box": 8, "sphere": 0, "capsule": 4, "convex": 4})
        self.assertEqual([m["mesh"] for m in result["meshes"]], ["1"])
        self.assertEqual(result["meshes"][0]["placements"], 4)
        self.assertEqual([e["mesh"] for e in result["errors"]], ["3"])
