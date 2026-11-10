"""Tests of the scene rasterizer, the crown stamps and the tiles' seams on a small scene with a known answer.

    docker run --rm -v tools/maptiles/py:/py:ro -v tools/heightmaps/py:/hmpy:ro -e PYTHONPATH=/py:/hmpy -w /py squadcalc-maptiles-py \
        python -m unittest test_scene
"""

import json
import math
import os
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np
from scipy import ndimage

import check_alignment
import crowns
import features
import landscape_paths
import outline_accuracy
import prep
import render
import road_width as rw
import scene_objects as so
import scene_prep as sp

BOUNDS = {"min_x": 0.0, "min_y": 0.0, "max_x": 60.0, "max_y": 60.0}
BOUNDS_40 = {"min_x": 0.0, "min_y": 0.0, "max_x": 40.0, "max_y": 40.0}
OPAQUE = "/Game/M/Opaque.Opaque"
GLASS = "/Game/M/Glass.Glass"
VOLUME = "/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"
WATER = "/Game/M/Ocean.Ocean"


def box_mesh(x0, y0, z0, x1, y1, z1):
    """Vertices [8, 8] and triangle indices of a box (cm) in the mesh file layout."""
    corners = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    vertices = np.array([c + (0, 0, 1, 0, 0) for c in corners], np.float32)
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    indices = np.array([i for a, b, c, d in faces for i in (a, b, c, a, c, d)], np.uint32)
    return vertices, indices


def chain(x, y, z=0.0, yaw=0.0, scale=1.0):
    """Attach chain (cm) of one component."""
    return [{"l": {"X": x * 100, "Y": y * 100, "Z": z * 100}, "r": {"Pitch": 0.0, "Yaw": yaw, "Roll": 0.0}, "s": {"X": scale, "Y": scale, "Z": scale}}]


class Scene:
    """A scene directory written to disk piece by piece."""

    def __init__(self, directory):
        self.directory = directory
        os.makedirs(os.path.join(directory, "meshes"))
        self.meshes, self.items = {}, []
        self.materials = {OPAQUE: {"blend": "BLEND_Opaque"}, GLASS: {"blend": "BLEND_Translucent"}, VOLUME: {"blend": "BLEND_Opaque"},
                          WATER: {"blend": "BLEND_Opaque"}}

    def add_mesh(self, name, parts):
        """parts: [(box corners cm, material)]; one section per part."""
        mesh_id = len(self.meshes)
        vertices, indices, sections = [], [], []
        for box, material in parts:
            v, i = box_mesh(*box)
            sections.append({"material": len(sections), "first": sum(len(x) for x in indices), "triangles": len(i) // 3})
            indices.append(i + sum(len(x) for x in vertices))
            vertices.append(v)
        v, i = np.concatenate(vertices), np.concatenate(indices)
        with open(os.path.join(self.directory, "meshes", f"{mesh_id}.bin"), "wb") as handle:
            handle.write(v.tobytes())
            handle.write(i.tobytes())
        self.meshes[f"/Game/M/{name}.{name}"] = {"id": mesh_id, "materials": [m for _, m in parts], "lod": 0, "vertices": len(v), "indices": len(i), "sections": sections}
        return mesh_id

    def place(self, mesh_id, at, level="SquadGame/Content/Maps/T/L_Art.umap", hidden=False, kind="StaticMeshComponent", overrides=(), instances=None):
        self.items.append({"level": level, "name": "c", "type": kind, "owner": "o", "mesh": mesh_id, "hidden": hidden, "cull": [0, 0, 0, 0],
                           "overrides": list(overrides), "chain": chain(*at), "instances": instances, "spline": None})

    def write(self):
        json.dump(self.meshes, open(os.path.join(self.directory, "meshes.json"), "w"))
        json.dump(self.materials, open(os.path.join(self.directory, "materials.json"), "w"))
        with open(os.path.join(self.directory, "instances.ndjson"), "w") as handle:
            handle.write("\n".join(json.dumps(item) for item in self.items))


class Statics:
    """A directory of the server's static meshes (SquadExtract statics) written piece by piece: placements and their bounds."""

    def __init__(self, directory):
        self.directory = directory
        os.makedirs(os.path.join(directory, "bodies"))
        self.items = []

    def add_mesh(self, name, box):
        """box: the mesh's corners (cm)."""
        mesh = str(len(os.listdir(os.path.join(self.directory, "bodies"))))
        low, high = np.array(box[:3], float), np.array(box[3:], float)
        bounds = {"Origin": dict(zip("XYZ", ((low + high) / 2).tolist())), "BoxExtent": dict(zip("XYZ", ((high - low) / 2).tolist()))}
        json.dump({"path": f"/Game/M/{name}.{name}", "bounds": bounds}, open(os.path.join(self.directory, "bodies", f"{mesh}.json"), "w"))
        return mesh

    def place(self, mesh, at, collision=None):
        self.items.append({"level": "SquadGame/Content/Maps/T/L_Art.umap", "type": "StaticMeshComponent", "mesh": mesh, "chain": chain(*at), "collision": collision, "instances": None})

    def write(self):
        with open(os.path.join(self.directory, "instances.ndjson"), "w") as handle:
            handle.write("\n".join(json.dumps(item) for item in self.items))


def flat_ground(size=61):
    return np.zeros((size, size), np.float32)


class SceneRaster(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        s = Scene(self.dir)
        # A 10 x 6 m house, 5 m to the eaves with a 2 m higher part of 4 x 6 m, placed with its corner at (20.05, 20)
        house = s.add_mesh("House", [((0, 0, 0, 1000, 600, 500), OPAQUE), ((0, 0, 500, 400, 600, 700), OPAQUE),
                                     ((0, 0, 2000, 1000, 600, 2010), GLASS), ((-1000, -1000, 0, 5000, 5000, 4000), VOLUME)])
        cable = s.add_mesh("PowerCable", [((0, 0, 600, 2000, 5, 605), OPAQUE)])
        wall = s.add_mesh("Wall_Fence", [((0, 0, 0, 1500, 10, 150), OPAQUE)])
        pole = s.add_mesh("Pole", [((0, 0, 0, 35, 35, 800), OPAQUE)])
        water = s.add_mesh("OceanPlane", [((0, 0, 0, 2000, 2000, 300), OPAQUE)])
        sky = s.add_mesh("SkySphere", [((0, 0, 3000, 200000, 200000, 3100), OPAQUE)])
        s.place(sky, (0, 0))
        s.place(house, (20.05, 20))
        s.place(house, (40, 40), hidden=True)
        s.place(house, (40, 10), level="SquadGame/Content/Maps/T/Coop/L_Art.umap")
        s.place(house, (5, 30), level="SquadGame/Content/Maps/T/Levels/T_Editor_Only.umap")
        s.place(cable, (5, 50))
        s.place(wall, (5, 5))
        s.place(pole, (50, 50))
        s.place(water, (0, 0))
        s.write()
        self.scene = so.SceneObjects(self.dir)
        self.ground = flat_ground()

    def raster(self, r0=0, r1=600, c0=0, c1=600):
        return so.raster_block(self.scene, self.ground, 0.0, BOUNDS, r0, r1, c0, c1)

    def test_house_footprint_and_heights(self):
        height, cls, cover = self.raster()
        self.assertEqual(int(height[230, 250]), 500)
        self.assertEqual(int(height[230, 210]), 700)
        self.assertEqual(int(height[100, 100]), 0)
        self.assertAlmostEqual(float((cover[190:270, 190:310] > 127).sum()) * so.CELL_M ** 2, 60.0, delta=1.0)
        self.assertTrue((cls[220:240, 230:290] == features.STRUCTURE).all())

    def test_edge_coverage_is_anti_aliased(self):
        _, _, cover = self.raster()
        # The house's west wall is at x = 20.05 m: cell 200 (20.0 to 20.1 m) is half covered
        self.assertTrue(100 <= int(cover[230, 200]) <= 156, int(cover[230, 200]))
        self.assertEqual(int(cover[230, 210]), 255)
        self.assertEqual(int(cover[230, 190]), 0)

    def test_hidden_skipped_level_glass_and_developer_volumes_are_not_drawn(self):
        height, _, _ = self.raster()
        # hidden (40, 40), in a Coop level (40, 10), in an editor-only level (5, 30), the glass 20 m up and the 40 m volume around the house
        self.assertEqual(int(height[430:470, 430:470].max()), 0)
        self.assertEqual(int(height[130:170, 430:470].max()), 0)
        self.assertEqual(int(height[310:350, 60:140].max()), 0)
        self.assertEqual(int(height[:480].max()), 700)  # nothing taller than the house above the pole's row

    def test_meshes_wider_than_the_map_are_scenery_not_objects(self):
        self.assertEqual(self.scene.scenery, {"SkySphere.SkySphere": 1})
        height, _, _ = self.raster()
        self.assertEqual(int(height[0, 0]), 0)

    def test_water_planes_of_visible_water_meshes_come_from_the_scene(self):
        s = Scene(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, s.directory)
        lake = s.add_mesh("SM_env_river", [((0, 0, 0, 3000, 2000, 600), OPAQUE)])
        ocean = s.add_mesh("SM_OceanPlane", [((0, 0, 0, 3000, 2000, 600), OPAQUE)])
        wet = s.add_mesh("waterplane_still", [((0, 0, 0, 3000, 2000, 600), WATER)])
        s.place(lake, (10, 20))
        s.place(ocean, (0, 0))
        s.place(wet, (0, 0))
        s.write()
        planes = so.water_planes(s.directory, 1.0)
        self.assertEqual(len(planes), 1)
        self.assertEqual(planes[0]["z"], 5.0)
        self.assertEqual(sorted(planes[0]["polygon"])[0], [10.0, 20.0])
        self.assertEqual(max(x for x, _ in planes[0]["polygon"]), 40.0)

    def test_a_lake_with_a_material_named_after_its_water_level_is_a_water_plane(self):
        s = Scene(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, s.directory)
        instance = "/Game/Maps/T/WeatherLayer/WL_T_Water.WL_T_Water:PersistentLevel.BP_Lake_Squad3.Lake.MID_MI_LakeMaster_T_1"
        foam = "/Game/Maps/T/WeatherLayer/WL_T_Water.WL_T_Water:PersistentLevel.BP_Lake_Squad4.Lake.MID_MI_LakeFoam_T_1"
        s.materials[instance] = {"blend": "BLEND_Opaque"}
        s.materials[foam] = {"blend": "BLEND_Translucent"}
        lake = s.add_mesh("SM_env_river", [((-1500, -1500, 0, 1500, 1500, 0), OPAQUE)])
        s.place(lake, (100, 200, 7, 0, 4), overrides=(instance,))
        s.place(lake, (500, 600, 7, 0, 4), overrides=(foam,))
        s.write()
        planes = so.water_planes(s.directory, 2.0)
        self.assertEqual(len(planes), 1)
        self.assertEqual(planes[0]["z"], 5.0)
        corners = sorted(planes[0]["polygon"])
        self.assertEqual(corners[0], [40.0, 140.0])
        self.assertEqual(corners[-1], [160.0, 260.0])

    def test_overrides_hide_a_developer_material_of_a_component(self):
        s = Scene(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, s.directory)
        mesh = s.add_mesh("Marker", [((0, 0, 0, 1000, 1000, 300), OPAQUE)])
        s.place(mesh, (10, 10), overrides=(VOLUME,))
        s.place(mesh, (30, 10))
        s.write()
        scene = so.SceneObjects(s.directory)
        height, _, _ = so.raster_block(scene, self.ground, 0.0, BOUNDS, 0, 600, 0, 600)
        self.assertEqual(int(height[150, 150]), 0)
        self.assertEqual(int(height[150, 350]), 300)

    def test_cables_and_water_go_but_walls_and_poles_stay(self):
        height, cls, cover = self.raster()
        self.assertEqual(int(height[500, 100:250].max()), 0)  # the cable at y = 50 m
        self.assertGreater(int(height[50, 100]), 0)  # the fence at y = 5 m, 10 cm thick
        self.assertEqual(int(cls[50, 100]), features.WALL)
        self.assertEqual(int(height[500, 500]), 800)  # the pole 35 cm across
        self.assertEqual(int(height[0, 0]), 0)  # the ocean plane

    def test_height_is_above_the_ground(self):
        self.ground = flat_ground() + 2.0
        height, _, _ = so.raster_block(self.scene, self.ground, -2.0, BOUNDS, 0, 600, 0, 600)
        self.assertEqual(int(height[230, 250]), 500)

    def test_blocks_join_without_seams_and_runs_repeat_exactly(self):
        whole = self.raster(0, 600, 0, 600)
        parts = [self.raster(r, r + 300, c, c + 300) for r in (0, 300) for c in (0, 300)]
        for k, name in enumerate(("height", "class", "cover")):
            joined = np.block([[parts[0][k], parts[1][k]], [parts[2][k], parts[3][k]]])
            self.assertTrue(np.array_equal(joined, whole[k]), name)
        again = self.raster(0, 600, 0, 600)
        self.assertTrue(all(a.tobytes() == b.tobytes() for a, b in zip(whole, again)))
        cut_across_the_house = self.raster(0, 600, 0, 215)[0]
        self.assertTrue(np.array_equal(cut_across_the_house, whole[0][:, :215]))


class SamplesAndCells(unittest.TestCase):
    def test_ground_on_grid_is_map_coordinates_in_and_beyond_the_grid(self):
        ground = np.random.default_rng(3).normal(size=(40, 50)).astype(np.float32) * 20
        rows = np.arange(-40, 900) * 0.05 - 0.7
        cols = np.arange(-30, 1100) * 0.05 + 0.013
        expected = ndimage.map_coordinates(ground, np.meshgrid(rows, cols, indexing="ij"), order=1, mode="nearest") + 7.5
        got = so.ground_on_grid(ground, 7.5, rows, cols)
        self.assertEqual(got.dtype, expected.dtype)
        np.testing.assert_allclose(got, expected, rtol=0, atol=4e-6)

    def test_raster_block_is_its_samples_and_their_cells(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        s = Scene(directory)
        s.place(s.add_mesh("House", [((0, 0, 0, 1000, 600, 500), OPAQUE)]), (20.05, 20))
        s.write()
        scene, ground = so.SceneObjects(directory), flat_ground()
        whole = so.raster_block(scene, ground, 0.0, BOUNDS, 0, 600, 0, 600)
        samples = so.block_samples(scene, BOUNDS, 0, 600, 0, 600, so.sample_tops)
        for a, b in zip(whole, so.block_cells(samples, ground, 0.0, BOUNDS, 0, 600, 0, 600)):
            self.assertEqual(a.tobytes(), b.tobytes())
        self.assertIsNone(so.block_samples(scene, BOUNDS, 0, 50, 0, 50, so.sample_tops))
        empty = so.block_cells(None, ground, 0.0, BOUNDS, 0, 50, 0, 50)
        self.assertEqual([a.shape for a in empty], [(50, 50)] * 3)
        self.assertFalse(any(a.any() for a in empty))


class MaterialRules(unittest.TestCase):
    def test_hidden_materials(self):
        materials = {OPAQUE: {"blend": "BLEND_Opaque"}, GLASS: {"blend": "BLEND_Translucent"}, "/Game/M/Glow.Glow": {"blend": "BLEND_Additive"}}
        self.assertFalse(so.hidden_material(OPAQUE, materials))
        self.assertTrue(so.hidden_material(GLASS, materials))
        self.assertTrue(so.hidden_material("/Game/M/Glow.Glow", materials))
        self.assertTrue(so.hidden_material(VOLUME, materials))
        self.assertTrue(so.hidden_material("/Game/M/Ocean_Surface.Ocean_Surface", materials))
        self.assertTrue(so.hidden_material("/Engine/EngineMaterials/WorldGridMaterial.WorldGridMaterial", materials))
        self.assertTrue(so.hidden_material("/Game/Blockout/MI_Blue_Transparent.MI_Blue_Transparent", materials))
        self.assertTrue(so.hidden_material("/Game/Gameplay/GameplayBorder/M_MapBorder.M_MapBorder", materials))
        self.assertFalse(so.hidden_material("/Game/Blockout/MI_Concrete.MI_Concrete", materials))

    def test_water_surface_meshes_are_not_objects(self):
        self.assertTrue(so.is_water_mesh("/Game/Env/Water/SM_env_river.SM_env_river"))
        self.assertTrue(so.is_water_mesh("/Game/Env/Water/waterplane_muddy_still.waterplane_muddy_still"))
        self.assertFalse(so.is_water_mesh("/Game/Env/Props/SM_Water_Tower.SM_Water_Tower"))
        self.assertFalse(so.is_water_mesh("/Game/Env/Props/SM_Pond_Pump_Tank.SM_Pond_Pump_Tank"))

    def test_water_tanks_towers_and_cubes_are_objects(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        s = Scene(directory)
        for index, name in enumerate(("WaterTower", "CAF_WaterTank", "WaterCube_3", "waterplane_still")):
            s.place(s.add_mesh(name, [((0, 0, 0, 300, 300, 400), OPAQUE)]), (5 + 10 * index, 5))
        s.write()
        names = sorted(group["name"].rsplit(".", 1)[-1] for group in so.SceneObjects(directory).groups)
        self.assertEqual(names, ["CAF_WaterTank", "WaterCube_3", "WaterTower"])

    def test_object_class_is_decided_by_the_asset_name(self):
        self.assertEqual(features.object_class("SM_ME_Street_Light_01"), features.STRUCTURE)
        self.assertEqual(features.object_class("SM_Olivetree_02"), features.VEGETATION)
        self.assertEqual(features.object_class("SM_Bridge_Deck_20m"), features.BRIDGE)
        self.assertEqual(features.object_class("SM_Wall_E_1000"), features.WALL)


def cross_crown():
    """Two crossing 6 m x 1 m slabs 8 m high with leaf-card gaps: a plus-shaped crown (vertices, indices)."""
    a, i1 = box_mesh(-300, -50, 700, 300, 50, 800)
    b, i2 = box_mesh(-50, -300, 600, 50, 300, 700)
    return np.concatenate([a, b]), np.concatenate([i1, i2 + 8])


class CrownStamps(unittest.TestCase):

    def test_stamp_is_the_outline_of_the_mesh_seen_from_above(self):
        vertices, indices = cross_crown()
        stamp = crowns.silhouette(vertices, indices, [(0, len(indices))])
        n = crowns.STAMP_PX
        cover, relief = stamp[..., 0], stamp[..., 1]
        self.assertGreater(cover[n // 2, n // 2], 250)
        self.assertGreater(cover[n // 2, 2], 200)  # the arm's tip
        self.assertLess(cover[2, 2], 20)  # the empty corner
        self.assertGreater(relief[n // 2, n // 2], relief[2, n // 2])  # the crossing is higher than the tip of the lower arm

    def test_stamp_is_the_same_on_every_run(self):
        vertices, indices = cross_crown()
        a = crowns.silhouette(vertices, indices, [(0, len(indices))])
        b = crowns.silhouette(vertices, indices, [(0, len(indices))])
        self.assertEqual(a.tobytes(), b.tobytes())

    def test_scene_crowns_scale_turn_and_flag_trunks(self):
        directory, features_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        self.addCleanup(shutil.rmtree, features_dir)
        s = Scene(directory)
        tree = s.add_mesh("SM_OliveTree", [((-300, -300, 0, 300, 300, 800), OPAQUE)])
        flower = s.add_mesh("SM_flower01", [((-30, -30, 0, 30, 30, 50), OPAQUE)])
        corn = s.add_mesh("Corn_Tall_Unified", [((-100, -100, 0, 100, 100, 170), OPAQUE)])
        instances = [{"q": [0, 0, 0.7071068, 0.7071068], "t": [1000, 2000, 0], "s": [2, 2, 2]}]
        s.place(tree, (0, 0), kind=so.FOLIAGE_TYPE, instances=instances)
        s.place(flower, (0, 0), kind=so.FOLIAGE_TYPE, instances=instances)
        s.place(corn, (0, 0), kind=so.FOLIAGE_TYPE, instances=instances)
        s.write()
        with open(os.path.join(features_dir, "foliage.ndjson"), "w") as handle:
            handle.write(json.dumps({"mesh": "/Game/M/SM_OliveTree.SM_OliveTree", "info": {"collision": True}, "collision": None}))
        arrays, names, stamps = crowns.scene_crowns(directory, features_dir)
        self.assertEqual(len(arrays["x"]), 1)
        self.assertEqual(names, ["/Game/M/SM_OliveTree.SM_OliveTree"])
        self.assertAlmostEqual(float(arrays["radius"][0]), 6.0, places=3)
        self.assertAlmostEqual(float(arrays["x"][0]), 10.0, places=3)
        self.assertAlmostEqual(float(arrays["yaw"][0]), 90.0, places=2)
        self.assertEqual(int(arrays["cls"][0]), features.DECIDUOUS)
        self.assertTrue(bool(arrays["collision"][0]))
        self.assertGreater(int(stamps[0][..., 0].max()), 200)


class CropFields(unittest.TestCase):
    """Crops are fields with their height, wild flowers are not crops, and the fields are drawn by height with a hatch."""

    def test_crop_fields_cover_the_plants_and_keep_their_height(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        s = Scene(directory)
        maize = s.add_mesh("Corn_Tall_Unified", [((-50, -50, 0, 50, 50, 220), OPAQUE)])
        wheat = s.add_mesh("SM_Wheatcrops01", [((-50, -50, 0, 50, 50, 80), OPAQUE)])
        flower = s.add_mesh("SM_Flower_FieldFlowers_Poppy", [((-50, -50, 0, 50, 50, 50), OPAQUE)])
        rows = lambda x0: [{"q": [0, 0, 0, 1], "t": [(x0 + i) * 100, (10 + j) * 100, 0], "s": [1, 1, 1]} for i in range(10) for j in range(10)]
        s.place(maize, (0, 0), kind=so.FOLIAGE_TYPE, instances=rows(5))
        s.place(wheat, (0, 0), kind=so.FOLIAGE_TYPE, instances=rows(25))
        s.place(flower, (0, 0), kind=so.FOLIAGE_TYPE, instances=rows(45))
        s.write()
        fields = crowns.crop_fields(directory, BOUNDS, (61, 61))
        # Plants of 0.5 m reach on a 1 m grid cover pi / 4 of the ground
        self.assertAlmostEqual(int(fields[15, 10, 0]), round(255 * np.pi / 4), delta=3)
        self.assertAlmostEqual(fields[15, 10, 1] / 10, 2.2, delta=0.1)
        self.assertAlmostEqual(int(fields[15, 30, 0]), round(255 * np.pi / 4), delta=3)
        self.assertAlmostEqual(fields[15, 30, 1] / 10, 0.8, delta=0.1)
        self.assertEqual(int(fields[10:20, 47:53, 0].max()), 0)
        self.assertEqual(int(fields[40:, :, 0].max()), 0)

    def draw(self, height_m, px):
        n = 200
        d = {"size_x": n * px, "size_y": n * px, "min_x": 0.0, "min_y": 0.0, "fields": {}}
        frame = render.Frame(d, 0, 0, 0, n, n)
        frame.px = frame.px_x = frame.px_y = px
        frame.u = (np.arange(n) + 0.5) * px
        frame.v = (np.arange(n) + 0.5) * px
        cells = int(n * px) + 2
        crops = np.zeros((cells, cells, 2), np.uint8)
        crops[:, : cells // 2] = (255, int(height_m * 10))
        d["crops"] = crops
        rgb = np.full((n, n, 3), 230.0, np.float32)
        render.draw_crops(d, frame, rgb, np.zeros((n, n), np.float32))
        return rgb

    def test_tall_crops_are_drawn_darker_than_low_ones_and_bare_ground_is_left_alone(self):
        tall, low = self.draw(2.2, 2.0), self.draw(0.7, 2.0)
        self.assertLess(float(tall[:, :40].mean()), float(low[:, :40].mean()) - 10)
        # The crops cover the western 201 m, pixels 0 to 100 at 2 m per pixel
        self.assertEqual(float(np.abs(tall[:, 110:] - 230).max()), 0.0)

    def test_the_hatch_is_drawn_at_the_finer_zooms_only(self):
        fine, coarse = self.draw(0.7, 0.1)[:, :80].mean(2), self.draw(0.7, 2.0)[:, :40].mean(2)
        self.assertGreater(float(fine.max() - fine.min()), 15)
        self.assertLess(float(coarse.max() - coarse.min()), 1)


class LegacyOutlines(unittest.TestCase):
    """The old raster's 0.25 m squares are painted with smooth outlines: same area and heights, no staircase."""

    def test_a_staircase_becomes_an_anti_aliased_edge_of_the_same_area(self):
        old_h = np.zeros((80, 80), np.uint16)
        for row in range(10, 70):
            old_h[row, 10:row] = 600  # a triangle whose hypotenuse is a staircase of 0.25 m steps
        old_h[60:70, 60:70] = 900
        old_c = np.zeros_like(old_h, np.uint8)
        rows, cols = np.arange(200), np.arange(200)
        h, c, v, source_r, source_c = sp.legacy_cells(old_h, old_c, rows, cols)
        solid_area = float((old_h > 0).sum()) * sp.LEGACY_STEP_M ** 2
        self.assertAlmostEqual(float(v.sum()) / 255 * so.CELL_M ** 2, solid_area, delta=solid_area * 0.01)
        diagonal = v[100, 95:110]
        self.assertTrue(((diagonal > 0) & (diagonal < 255)).any(), diagonal)
        self.assertEqual(set(np.unique(h[v > 0])), {600, 900})
        np.testing.assert_array_equal(h, old_h[source_r, source_c])
        # Inside the square both rasters agree exactly, and a straight edge stays where it was
        self.assertEqual(int(v[160:170, 160:170].min()), 255)
        self.assertEqual(int(v[160, 175]), 0)

    def test_nothing_to_paint(self):
        h, _, v, _, _ = sp.legacy_cells(np.zeros((8, 8), np.uint16), np.zeros((8, 8), np.uint8), np.arange(20), np.arange(20))
        self.assertFalse(h.any() or v.any())


class CrownSprites(unittest.TestCase):
    def setUp(self):
        vertices, indices = cross_crown()
        stamp = crowns.silhouette(vertices, indices, [(0, len(indices))])
        self.d = {"stamps": {0: stamp}}

    def test_a_small_crown_is_the_exact_stamp_at_the_nearest_steps(self):
        cover, shade, rim = render.crown_sprite(self.d, 0, 5.1, 31.0, 3.6, True)
        exact_cover, relief = render.crown_stamp_image(self.d["stamps"][0], 5.0, 30.0)
        exact_shade, exact_rim = render.crown_light(exact_cover, relief, 3.5, True)
        for a, b in ((cover, exact_cover), (shade, exact_shade), (rim, exact_rim)):
            self.assertEqual(a.tobytes(), b.tobytes())

    def test_nearby_crowns_share_one_sprite_and_a_turn_wraps_around(self):
        first = render.crown_sprite(self.d, 0, 4.0, 1.0, 2.0, False)
        self.assertIs(render.crown_sprite(self.d, 0, 4.05, -2.0, 2.1, False), first)
        self.assertIs(render.crown_sprite(self.d, 0, 4.0, 359.0, 2.0, False), first)
        self.assertEqual(len(self.d["crown_sprites"]), 1)
        self.assertIsNot(render.crown_sprite(self.d, 0, 4.0, 1.0, 2.0, True), first)

    def test_the_cache_is_emptied_when_full(self):
        with mock.patch.object(render, "CROWN_SPRITE_CACHE", 3):
            for size in range(4):
                render.crown_sprite(self.d, 0, 2.0 + size, 0.0, 1.0, False)
        self.assertEqual(len(self.d["crown_sprites"]), 1)


class OldRasterMerge(unittest.TestCase):
    """Objects only the old collision raster holds stay; its halos around scene objects and invisible walls do not."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        n = 40  # a 40 x 40 m map: 400 cells of 0.1 m, 160 of 0.25 m
        top_h = np.zeros((n * 10, n * 10), np.uint16)
        top_h[100:200, 100:200] = 500  # the scene's house, 10 x 10 m at 10..20 m
        np.save(os.path.join(self.dir, "top_h0.npy"), top_h)
        np.save(os.path.join(self.dir, "top_c0.npy"), np.zeros_like(top_h, np.uint8))
        np.save(os.path.join(self.dir, "top_v0.npy"), np.where(top_h > 0, 255, 0).astype(np.uint8))
        old_h = np.zeros((n * 4, n * 4), np.uint16)
        old_h[36:84, 36:84] = 500  # the collision of the house, 1 m wider on every side
        old_h[120:140, 20:40] = 800  # a Blueprint building at x 5..10, y 30..35
        old_h[20:100, 150:155] = 300  # an invisible wall at x 37.5..38.75, y 5..25
        old_h[120:150, 100:130] = 900  # background terrain at x 25..32.5, y 30..37.5 (a rock of the old raster)
        np.save(os.path.join(self.dir, "obj_h0.npy"), old_h)
        old_c = np.zeros_like(old_h, np.uint8)
        old_c[120:150, 100:130] = features.ROCK_OBJECT
        np.save(os.path.join(self.dir, "obj_c0.npy"), old_c)
        np.save(os.path.join(self.dir, "obj_h2.npy"), old_h[::4, ::4][:n, :n])
        np.save(os.path.join(self.dir, "obj_c2.npy"), old_c[::4, ::4][:n, :n])

    def merge(self, seen=None):
        """``seen``: what the scene shows before its thin objects are taken out; by default all that is asked about."""
        new_h1, _ = sp.pool_metres(self.dir)
        service = np.zeros(new_h1.shape, bool)
        service[3:28, 36:40] = True
        return sp.merge_old(self.dir, new_h1, new_h1.shape, service, np.zeros(new_h1.shape, bool), lambda wanted: wanted if seen is None else seen)

    def test_blueprint_is_kept_halo_and_service_wall_are_not(self):
        old, keep, old_only = self.merge()
        h0 = np.load(os.path.join(self.dir, "top_h0.npy"))
        self.assertEqual(int(h0[320:350, 60:90].min()), 800)  # the Blueprint building
        self.assertEqual(int(h0[100:200, 100:200].min()), 500)  # the house is the scene's
        self.assertEqual(int(h0[95, 150]), 0)  # the collision's halo of the house
        self.assertEqual(int(h0[100:250, 370:390].max()), 0)  # the invisible wall
        self.assertEqual(int(h0[300:380, 250:330].max()), 0)  # the old raster's rock
        self.assertGreater(int(old_only.sum()), 0)
        self.assertEqual(int(keep.sum()), 25)

    def test_a_run_the_scene_shows_nothing_of_is_not_kept(self):
        # Manicouagan: the dam meshes' collision stands 2 to 3 m above the reservoir, where the game shows water
        old, keep, _ = self.merge(seen=np.zeros((40, 40), bool))
        h0 = np.load(os.path.join(self.dir, "top_h0.npy"))
        self.assertEqual(int(h0[300:360, 40:110].max()), 0)
        self.assertEqual(int(keep.sum()), 0)
        self.assertTrue(old[30:35, 5:10].all())

    def test_runs_the_scene_shows_stay_whole_and_the_others_go(self):
        keep = np.zeros((30, 30), bool)
        keep[2:4, 2:12] = True  # a tent frame: seen along its whole run
        keep[8, 2:12] = True  # a fence whose mesh stands a metre beside its collision
        keep[14:18, 2:12] = True  # a block of collision with a pole at one corner
        keep[22:26, 2:12] = True  # collision over water
        seen = np.zeros((30, 30), bool)
        seen[2:4, 2:11] = True
        seen[9, 2:12] = True
        seen[14, 2] = True
        kept = sp.shown_runs(keep, seen)
        self.assertTrue(kept[2:4, 2:12].all() and kept[8, 2:12].all())
        self.assertFalse(kept[14:18, 2:12].any() or kept[22:26, 2:12].any())
        np.testing.assert_array_equal(sp.shown_runs(np.zeros((5, 5), bool), np.ones((5, 5), bool)), np.zeros((5, 5), bool))

    def test_the_unthinned_raster_sees_what_the_tiles_raster_drops_as_thin(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        s = Scene(directory)
        s.place(s.add_mesh("TentFrame", [((0, 0, 0, 600, 10, 300), OPAQUE)]), (10, 10))  # a bar 6 m long, 0.1 m wide and 3 m high
        s.place(s.add_mesh("Hut", [((0, 0, 0, 300, 300, 250), OPAQUE)]), (40, 40))
        s.write()
        scene = so.SceneObjects(directory)
        ground = flat_ground()
        tiles_raster, _, _ = so.raster_block(scene, ground, 0.0, BOUNDS, 80, 130, 80, 180)
        self.assertEqual(int(tiles_raster.max()), 0)  # the bar is thinner than THIN_WIDTH_M
        wanted = np.zeros((60, 60), bool)
        wanted[10, 10:16] = True  # the collision of the bar
        wanted[30, 30] = True  # collision with nothing of the scene near it
        seen = sp.unthinned_objects(scene, ground, 0.0, BOUNDS, wanted)
        self.assertTrue(seen[10, 10:16].all())
        self.assertFalse(seen[30, 30] or seen[12, 10:16].any())
        self.assertFalse(seen[40:43, 40:43].any())  # the hut's tile holds nothing wanted and is not drawn
        self.assertTrue(sp.unthinned_objects(scene, ground, 0.0, BOUNDS, np.ones((60, 60), bool))[40:43, 40:43].all())

    def test_a_wire_between_the_rasters_points_is_seen_by_its_edges(self):
        # A wire 1 cm thick along the grid, between two rows of points 5 cm apart, and a fence of one upright sheet: no point of
        # the raster falls in either, and the server's collision of both is a run of the old raster
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        s = Scene(directory)
        s.place(s.add_mesh("Wire", [((0, 3, 800, 2000, 4, 801), OPAQUE)]), (10, 10))
        s.place(s.add_mesh("FenceSheet", [((0, 0, 0, 1000, 0, 200), OPAQUE)]), (10, 30.02))
        s.place(s.add_mesh("Kerb", [((0, 0, 0, 1000, 0, 20), OPAQUE)]), (10, 40.02))  # too low to be an object
        s.write()
        scene = so.SceneObjects(directory)
        ground = flat_ground()
        raster, _, _ = so.raster_block(scene, ground, 0.0, BOUNDS, 80, 320, 80, 320)
        self.assertEqual(int(raster.max()), 0)
        wanted = np.zeros((60, 60), bool)
        wanted[10, 10:30] = wanted[30, 10:20] = wanted[40, 10:20] = True
        seen = sp.unthinned_objects(scene, ground, 0.0, BOUNDS, wanted)
        self.assertTrue(seen[10, 10:30].all() and seen[30, 10:20].all())
        self.assertFalse(seen[40, 10:20].any() or seen[20, 10:30].any())

    def test_points_along_the_edges_of_a_triangle(self):
        points = sp.edge_points(np.array([[[0.0, 0.0, 7.0], [1.0, 0.0, 7.0], [1.0, 2.0, 7.0]]]), 0.5)
        self.assertEqual(sorted(map(tuple, points[:, :2].round(3).tolist())), sorted([(0.0, 0.0), (0.5, 0.0), (1.0, 0.0), (1.0, 0.5), (1.0, 1.0), (1.0, 1.5),
                                                                                   (1.0, 2.0), (0.8, 1.6), (0.6, 1.2), (0.4, 0.8), (0.2, 0.4)]))
        np.testing.assert_array_equal(points[:, 2], 7.0)

    def test_the_ground_under_scattered_points_is_that_of_the_grid(self):
        ground = np.arange(36, dtype=np.float32).reshape(6, 6)
        rows, cols = np.array([0.0, 1.5, 4.25, 9.0]), np.array([0.0, 2.5, 0.75, 9.0])
        np.testing.assert_allclose(so.ground_points(ground, 10.0, rows, cols), [10.0, 10 + 1.5 * 6 + 2.5, 10 + 4.25 * 6 + 0.75, 10 + 35.0])
        np.testing.assert_allclose(so.ground_points(ground, 10.0, rows[1:3], cols[1:3]), np.diag(so.ground_on_grid(ground, 10.0, rows[1:3], cols[1:3])))

    def test_lake_surface_of_the_old_raster_is_found(self):
        ground = np.zeros((40, 40), np.float32)
        ground[10:30, 10:30] = -4.0  # a basin whose water plane lies at 2 m
        plane = {"polygon": [[5.0, 5.0], [35.0, 5.0], [35.0, 35.0], [5.0, 35.0]], "z": 2.0}
        old_height = np.zeros((40, 40), np.uint16)
        old_height[10:30, 10:30] = 600  # the lake surface 6 m over the floor
        old_height[12:16, 12:16] = 900  # a pier of 9 m: above the surface
        surface = sp.legacy_water_surface([plane], BOUNDS_40, (40, 40), ground, old_height)
        self.assertTrue(surface[20, 20])
        self.assertFalse(surface[13, 13])
        self.assertFalse(surface[2, 2])

    def test_runs_in_service_volumes(self):
        keep = np.zeros((10, 10), bool)
        keep[1:3, 1:3] = True
        keep[6:8, 6:9] = True
        service = np.zeros((10, 10), bool)
        service[0:4, 0:4] = True
        kept = sp.without_service_runs(keep, service)
        self.assertFalse(kept[1:3, 1:3].any())
        self.assertTrue(kept[6:8, 6:9].all())

    def test_small_runs_are_dropped(self):
        mask = np.zeros((20, 20), bool)
        mask[1:3, 1:3] = True
        mask[8:16, 8:16] = True
        self.assertFalse(sp.small_runs_removed(mask, 10)[1:3, 1:3].any())
        self.assertTrue(sp.small_runs_removed(mask, 10)[8:16, 8:16].all())


def synthetic_map(directory, sea_level=None, empty=False):
    """A 60 x 60 m map's prepared data with a house, a wall, a tree and a hedge: renders at zoom 2 (0.06 m per pixel).

    ``sea_level`` (m above the ground's zero) adds a sea; ``empty``: flat ground and nothing on it (no objects, track or crowns).
    """
    slug = "toy"
    base = os.path.join(directory, "prep", slug)
    os.makedirs(base)
    s = Scene(os.path.join(directory, "scene"))
    house = s.add_mesh("House", [((0, 0, 0, 1000, 600, 500), OPAQUE), ((0, 0, 500, 400, 600, 700), OPAQUE)])
    tall = s.add_mesh("Tower", [((0, 0, 0, 400, 400, 1800), OPAQUE)])
    hedge = s.add_mesh("Hedge_01", [((0, 0, 0, 2000, 100, 150), OPAQUE)])
    if not empty:
        s.place(house, (14.5, 14.5))
        s.place(tall, (29.0, 31.0))
        s.place(hedge, (10, 45))
    s.write()
    scene = so.SceneObjects(s.directory)
    cells = int(60 / so.CELL_M)
    height, cls, cover = so.raster_block(scene, flat_ground(), 0.0, BOUNDS, 0, cells, 0, cells)
    for name, array in (("h", height), ("c", cls), ("v", cover)):
        np.save(os.path.join(base, f"top_{name}0.npy"), array)
    prep.build_pyramid(base, 7, prefix="top", coverage_exists=True)
    ground = np.add.outer(np.linspace(0, 1.5, 61), np.linspace(0, 0.5, 61)).astype(np.float32) * (0 if empty else 1)
    np.save(os.path.join(base, "ground.npy"), ground)
    np.save(os.path.join(base, "cover.npy"), np.zeros((61, 61), np.uint8))
    np.save(os.path.join(base, "top_ground.npy"), ground)
    np.save(os.path.join(base, "top_ground_base.npy"), sp.ground_base(ground))
    paths = np.zeros((61, 61), np.uint8)
    paths[30:33, :] = 0 if empty else 255
    np.save(os.path.join(base, "top_paths.npy"), paths)
    np.save(os.path.join(base, "top_water_surface.npy"), sp.river_surface(np.full((61, 61), -np.inf, np.float32), 0.0))
    crops = np.zeros((61, 61, 2), np.uint8)
    if not empty:
        crops[5:15, 40:55] = (255, 20)
    np.save(os.path.join(base, "top_crops.npy"), crops)
    json.dump({"bounds_m": BOUNDS, "sea_level_m": sea_level, "z_min_m": 0.0, "physical_materials": features.PHYSICAL_MATERIALS},
              open(os.path.join(base, "meta.json"), "w"))
    json.dump({"pyramid_levels": 7}, open(os.path.join(base, "top_meta.json"), "w"))
    json.dump([], open(os.path.join(base, "top_lines.json"), "w"))
    json.dump({"planes": []}, open(os.path.join(base, "water.json"), "w"))
    json.dump({"planes": []}, open(os.path.join(base, "top_water.json"), "w"))
    json.dump([] if empty else [{"x": 19.5, "y": 17.5, "h": 7.0, "area": 60, "depth": 2.4}], open(os.path.join(base, "top_labels.json"), "w"))
    crown = {"x": [40.0, 41.0], "y": [20.0, 40.0], "z": [0, 0], "radius": [4.0, 0.05], "half_x": [4.0, 0.05], "half_y": [4.0, 0.05], "yaw": [30.0, 0.0],
             "height": [7.0, 0.3], "cls": [features.DECIDUOUS, features.BUSH], "collision": [True, False], "mesh": [0, 0]}
    if empty:
        crown = {key: [] for key in crown}
    dtypes = {"cls": np.uint8, "collision": bool, "mesh": np.uint16}
    np.savez(os.path.join(base, "crowns.npz"), **{k: np.array(v, dtypes.get(k, np.float32)) for k, v in crown.items()})
    stamp = np.zeros((crowns.STAMP_PX, crowns.STAMP_PX, 2), np.uint8)
    yy, xx = np.mgrid[:crowns.STAMP_PX, :crowns.STAMP_PX]
    disc = (xx - 31.5) ** 2 + (yy - 31.5) ** 2 <= 30 ** 2
    stamp[..., 0] = np.where(disc, 255, 0)
    stamp[..., 1] = np.where(disc, 255 - 5 * np.hypot(xx - 31.5, yy - 31.5), 0)
    np.save(os.path.join(base, "crowns_stamps.npy"), stamp[None])
    json.dump(["/Game/M/SM_OliveTree.SM_OliveTree"], open(os.path.join(base, "crowns.json"), "w"))
    return slug


class FoliageNames(unittest.TestCase):
    def test_a_palm_is_a_palm_not_a_broadleaf_tree(self):
        for name in ("SM_PalmTree_01", "Palm_Date_Tall"):
            self.assertEqual(features._classify(name, features._FOLIAGE_RULES, None), features.PALM, name)
        self.assertEqual(features._classify("SM_OliveTree", features._FOLIAGE_RULES, None), features.DECIDUOUS)


class SceneLakes(unittest.TestCase):
    def test_the_scene_lakes_are_water_of_the_render(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        slug = synthetic_map(directory)
        lake = {"polygon": [[5.0, 5.0], [25.0, 5.0], [25.0, 25.0], [5.0, 25.0]], "z": 1.0}
        json.dump({"planes": [lake]}, open(os.path.join(directory, "prep", slug, "top_water.json"), "w"))
        with mock.patch.object(render, "PREP_DIR", os.path.join(directory, "prep")):
            self.assertIn(lake["polygon"], [plane["polygon"] for plane in render.load(slug)["planes"]])


class VegetationAndGroundCover(unittest.TestCase):
    """Meshes the asset name leaves plain are classed by their materials; names only drop what really is ground cover."""

    FOLIAGE = {"blend": "BLEND_Masked", "shading": "MSM_TwoSidedFoliage"}

    def classes_of(self, parts_by_mesh, materials):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        s = Scene(directory)
        s.materials.update(materials)
        for index, (name, parts) in enumerate(parts_by_mesh.items()):
            s.place(s.add_mesh(name, parts), (5 + 10 * index, 5))
        s.write()
        return {group["name"].rsplit("/", 1)[-1].split(".")[0]: group["cls"] for group in so.SceneObjects(directory).groups}

    def test_a_road_surface_painting_the_virtual_texture_is_a_bridge(self):
        rvt = "/Game/M/MI_Road_Dirt_RVT.MI_Road_Dirt_RVT"
        classes = self.classes_of({
            "SM_Road_R_4_01b": [((0, 0, 0, 500, 500, 5), rvt)],
            "SM_Road_Plain_Mesh": [((0, 0, 0, 500, 500, 5), OPAQUE)],
            "SM_RoadSign_01": [((0, 0, 0, 50, 50, 300), rvt)],
        }, {rvt: {"blend": "BLEND_Opaque", "shading": "MSM_Unlit"}})
        self.assertEqual(classes, {"SM_Road_R_4_01b": features.BRIDGE, "SM_Road_Plain_Mesh": features.STRUCTURE, "SM_RoadSign_01": features.STRUCTURE})

    def test_foliage_shaded_plant_materials_make_vegetation_whatever_the_mesh_is_called(self):
        leaf, tent, moss, bark = "/Game/M/MI_Boxwood_Leaves.MI_Boxwood_Leaves", "/Game/M/M_LargeTent_Tiling_Olive.M_LargeTent_Tiling_Olive", "/Game/M/MI_Rock_Mossy.MI_Rock_Mossy", "/Game/M/MI_Trunk.MI_Trunk"
        materials = {leaf: self.FOLIAGE, tent: self.FOLIAGE, moss: {"blend": "BLEND_Opaque", "shading": "MSM_Unlit"}, bark: {"blend": "BLEND_Opaque", "shading": "MSM_Unlit"}}
        box = (0, 0, 0, 300, 100, 150)
        classes = self.classes_of({
            "SM_Boxwood_Row_01": [(box, leaf)],
            "SM_Boxwood_Cut": [(box, leaf), (box, bark)],
            "SM_Canvas_Tent_03": [(box, tent)],
            "EU_RockLarge_Mossy": [(box, moss)],
            "SM_Hedge_Short": [(box, OPAQUE)],
            "SM_Mostly_Trunk": [(box, leaf), (box, bark), (box, bark)],
        }, materials)
        self.assertEqual(classes["SM_Boxwood_Row_01"], features.VEGETATION)
        self.assertEqual(classes["SM_Boxwood_Cut"], features.VEGETATION)
        self.assertEqual(classes["SM_Hedge_Short"], features.VEGETATION)
        self.assertEqual(classes["SM_Canvas_Tent_03"], features.STRUCTURE)
        self.assertEqual(classes["EU_RockLarge_Mossy"], features.ROCK_OBJECT)
        self.assertEqual(classes["SM_Mostly_Trunk"], features.STRUCTURE)

    def test_rocks_and_walls_keep_their_class_even_with_leaf_materials(self):
        leaf = "/Game/M/MI_Ivy_Leaves.MI_Ivy_Leaves"
        classes = self.classes_of({"EU_Rock_Overgrown": [((0, 0, 0, 300, 100, 150), leaf)], "SM_Wall_Overgrown": [((0, 0, 0, 300, 100, 150), leaf)]},
                                  {leaf: self.FOLIAGE})
        self.assertEqual(classes["EU_Rock_Overgrown"], features.ROCK_OBJECT)
        self.assertEqual(classes["SM_Wall_Overgrown"], features.WALL)

    def test_ground_cover_is_dropped_but_corners_and_other_parts_stay(self):
        classes = self.classes_of({
            "SM_Wall_Corner_01": [((0, 0, 0, 300, 100, 150), OPAQUE)],
            "afg_wall2_corn_v2": [((0, 0, 0, 300, 100, 150), OPAQUE)],
            "SM_Crop_Wheat_Dry_Cluster": [((0, 0, 0, 300, 100, 150), OPAQUE)],
            "Corn_Tall_Unified": [((0, 0, 0, 300, 100, 150), OPAQUE)],
            "SM_Fol_Ivy_14": [((0, 0, 0, 300, 100, 150), OPAQUE)],
            "SM_Fieldgrass_med01": [((0, 0, 0, 300, 100, 150), OPAQUE)],
        }, {})
        self.assertEqual(sorted(classes), ["SM_Wall_Corner_01", "afg_wall2_corn_v2"])


class ShadowsAndLabels(unittest.TestCase):
    """A shadow needs a visible object, and labels stay at least as large on screen as those of the first Detailed layer."""

    OLD_PT = {"contour": 11, "roof": 10}

    def column(self, width_px):
        alpha = np.zeros((120, 120), np.float32)
        alpha[50:50 + width_px, 50:50 + width_px] = 1
        return np.where(alpha > 0, 6.0, 0.0).astype(np.float32), alpha

    def test_an_object_thinner_than_a_visible_pixel_casts_no_shadow(self):
        height, alpha = self.column(1)
        self.assertEqual(float(render.cast_shadow(height, alpha, 0.09, (0, 0)).max()), 0.0)

    def test_a_visible_post_casts_its_shadow_to_the_south_east(self):
        height, alpha = self.column(4)
        shadow = render.cast_shadow(height, alpha, 0.09, (0, 0)) * (1 - alpha)
        self.assertGreater(float(shadow.max()), 0.5)
        self.assertGreater(float(shadow[56:70, 56:70].sum()), float(shadow[30:44, 30:44].sum()))

    def labelled(self, z, legacy_finest=6):
        d = {"legacy_finest": legacy_finest, "fonts": {}, "roof_cache": {}, "min_x": 0.0, "min_y": 0.0, "size_x": 2000.0, "size_y": 2000.0}
        d["labels"] = [{"x": 30.0 + 11.0 * i, "y": 40.0 + 9.0 * (i % 3), "h": float(5 + i), "depth": 12.0} for i in range(40)]
        return d, render.Frame(d, z, 0, 0, 1024, 1024)

    def test_label_sizes_never_fall_below_the_first_layers_on_screen(self):
        d = {"legacy_finest": 6, "fonts": {}}
        for z in range(5, 10):
            scale = render.label_scale(d, z)
            for kind, old_pt in self.OLD_PT.items():
                self.assertGreaterEqual(render.label_font(d, kind, scale).size, old_pt * 2 ** max(0, z - 6), (kind, z))
        self.assertEqual([render.label_scale(d, z) for z in (4, 6, 7, 8)], [1, 1, 2, 4])

    def test_roof_labels_never_touch_at_any_label_scale(self):
        for z in (6, 7, 8):
            d, frame = self.labelled(z)
            placed, boxes = render.roof_labels_of(d, frame)
            self.assertTrue(placed)
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    self.assertFalse(a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1], (z, a, b))

    def test_the_same_roofs_are_labelled_from_the_first_layers_finest_zoom_on(self):
        counts = []
        for z in (6, 7, 8):
            d, frame = self.labelled(z)
            counts.append(len(render.roof_labels_of(d, frame)[0]))
        self.assertTrue(counts[0] > 0 and counts[0] == counts[1] == counts[2], counts)


class RoofRelief(unittest.TestCase):
    """Roofs are shaded and outlined by their top, and coloured by their height over the smoothed ground: the edge of a jetty
    under a pier's deck does not show on the deck."""

    def deck(self, step_m):
        """Grey level [H, W] of a flat deck 4 m above the ground's zero, 20 x 20 m, over ground that rises by step_m in the middle."""
        size, px = 60.0, 0.1
        n = int(size / px)
        d = {"size_x": size, "size_y": size, "min_x": 0.0, "min_y": 0.0, "levels": 0, "fields": {}}
        frame = render.Frame(d, 0, 0, 0, n, n)
        frame.px = frame.px_x = frame.px_y = px
        frame.u = (np.arange(n) + 0.5) * px
        frame.v = (np.arange(n) + 0.5) * px
        grid = np.where(np.arange(61) >= 30, step_m, 0.0).astype(np.float32)[None, :].repeat(61, 0)
        d["ground"] = grid
        d["ground_base"] = sp.ground_base(grid)
        d["ground_luma_level"] = 0
        d["ground_luma"] = np.full((n, n), 200.0, np.float32)
        ground = np.broadcast_to(np.interp(frame.u, np.arange(61), grid[0]), (n, n)).astype(np.float32)
        footprint = np.zeros((n, n), bool)
        footprint[200:400, 200:400] = True
        d["obj"] = {("h", 0): np.where(footprint, np.rint((4.0 - ground) * 100), 0).astype(np.uint16),
                    ("c", 0): np.where(footprint, features.STRUCTURE, 0).astype(np.uint8),
                    ("v", 0): np.where(footprint, 255, 0).astype(np.uint8)}
        rgb = np.full((n, n, 3), 200.0, np.float32)
        render.draw_objects(d, frame, rgb, np.zeros((n, n), np.float32))
        return rgb[210:390, 210:390].mean(2)

    def test_a_step_of_the_ground_under_a_deck_leaves_no_line_on_it(self):
        # Over the 1 m the step rises in, the heights' whole centimetres leave the top a ripple of a few millimetres: about 1 % of grey
        # at most, where shading the height over the ground drew the step as a jump of 44 grey levels
        deck = self.deck(1.5)
        self.assertLess(float(np.abs(np.diff(deck, axis=1)).max()), 3.0)

    def test_a_deck_over_flat_ground_is_one_colour(self):
        deck = self.deck(0.0)
        self.assertLess(float(deck.max() - deck.min()), 0.5)


class ObjectLegibility(unittest.TestCase):
    """Roofs hold a contrast against the ground, and objects keep an outline and a minimum visible size at every zoom."""

    SNOW = float(np.dot(render.COVER_RGB["PhysMat_Snow"], render.LUMA))
    GRASS = float(np.dot(render.COVER_RGB["PhysMat_Grass"], render.LUMA))

    def roofs(self, ground_luma):
        heights = np.array([0.3, 2.0, 3.5, 5.0, 10.0, 20.0, 40.0])
        luma = render.roof_contrast(render.structure_colour(heights), np.full(heights.shape, ground_luma, np.float32)) @ render.LUMA
        return luma

    def test_the_lightest_roof_is_below_snow_and_grass_by_the_contrast(self):
        for ground in (self.SNOW, self.GRASS):
            self.assertLessEqual(float(self.roofs(ground).max()), ground - render.ROOF_CONTRAST + 0.5, ground)

    def test_the_squeezed_ramp_still_orders_roofs_by_height(self):
        for ground in (self.SNOW, self.GRASS, 120.0):
            self.assertTrue(np.all(np.diff(self.roofs(ground)) < 0), ground)

    def test_a_roof_on_ground_light_enough_is_left_as_it_is(self):
        heights = np.array([0.3, 2.0, 5.0, 40.0])
        colour = render.structure_colour(heights)
        light = float((colour @ render.LUMA).max()) + render.ROOF_CONTRAST + 1
        np.testing.assert_allclose(render.roof_contrast(colour, np.full(4, light, np.float32)), colour, atol=1e-3)

    def test_dark_ground_keeps_part_of_the_ramp(self):
        luma = self.roofs(0.0)
        full = self.roofs(300.0)
        self.assertGreaterEqual(float((luma.max() - luma.min()) / (full.max() - full.min())), render.ROOF_MIN_SCALE - 1e-3)

    def test_the_ground_luma_under_a_large_roof_is_that_of_the_ground_around_it(self):
        names = ["PhysMat_Snow", "PhysMat_Asphalt"]
        palette = np.zeros((256, 3), np.float32)
        palette[0], palette[1] = render.COVER_RGB[names[0]], render.COVER_RGB[names[1]]
        cover = np.zeros((64, 64), np.uint8)
        cover[24:40, 24:40] = 1  # the cover under the roof, which is not the ground's
        covered = np.zeros((16, 16), np.uint16)
        covered[6:10, 6:10] = 300
        luma = render.ground_luma_map(cover, palette, covered, np.where(covered > 0, 255, 0).astype(np.uint8), 4.0)
        self.assertEqual(luma.shape, (16, 16))
        self.assertAlmostEqual(float(luma[8, 8]), self.SNOW, delta=1.0)
        self.assertAlmostEqual(float(luma[0, 0]), self.SNOW, delta=1.0)

    def test_the_coverage_of_a_fine_pixel_is_left_alone_and_a_coarse_one_shows_what_it_holds(self):
        alpha = np.array([0.0, 0.1, 0.5, 1.0], np.float32)
        np.testing.assert_array_equal(render.visible_coverage(alpha, render.OBJECT_SOLID_PX_M), alpha)
        np.testing.assert_array_equal(render.visible_coverage(alpha, 0.12), alpha)
        coarse = render.visible_coverage(alpha, 8.0)
        self.assertEqual((float(coarse[0]), float(coarse[3])), (0.0, 1.0))
        self.assertGreater(float(coarse[1]), 0.55)
        self.assertTrue(np.all(np.diff(coarse) > 0) and float(coarse.max()) <= 1.0)

    def overview(self, px, side_cells, footprint):
        """Grey level [H, W] of 16 x 16 pixels of px metres holding one object, whose cells (the pyramid level px belongs to) are
        given by footprint(rows, cols) -> coverage 0..1, over ground of luma 200."""
        level = int(math.floor(math.log2(px / render.OBJECT_CELL_M)))
        cell = render.OBJECT_CELL_M * 2 ** level
        n = side_cells
        d = {"size_x": n * cell, "size_y": n * cell, "min_x": 0.0, "min_y": 0.0, "levels": level, "fields": {}}
        coverage = footprint(np.arange(n)[:, None], np.arange(n)[None, :]).astype(np.float32)
        d["obj"] = {(name, level): array for name, array in (
            ("h", np.where(coverage > 0, 400, 0).astype(np.uint16)), ("c", np.zeros((n, n), np.uint8)),
            ("v", np.rint(coverage * 255).astype(np.uint8)))}
        grid = np.zeros((int(n * cell) + 2, int(n * cell) + 2), np.float32)
        d["ground"], d["ground_base"] = grid, grid
        d["ground_luma_level"] = level
        d["ground_luma"] = np.full((n, n), 200.0, np.float32)
        frame = render.Frame(d, 0, 0, 0, n, n)
        frame.px = frame.px_x = frame.px_y = cell
        frame.u = (np.arange(n) + 0.5) * cell
        frame.v = (np.arange(n) + 0.5) * cell
        rgb = np.full((n, n, 3), 200.0, np.float32)
        render.draw_objects(d, frame, rgb, np.zeros((n, n), np.float32))
        return rgb @ render.LUMA

    def test_a_car_at_an_overview_zoom_is_not_faint(self):
        # A 2 x 5 m car in a 6.4 m cell covers about a quarter of it
        luma = self.overview(6.4, 16, lambda r, c: np.where((r == 8) & (c == 8), 0.25, 0.0))
        self.assertLess(float(luma[8, 8]), 200 - 60)

    def test_a_roof_has_an_outline_at_an_overview_zoom(self):
        luma = self.overview(1.6, 32, lambda r, c: np.where((r >= 8) & (r < 24) & (c >= 8) & (c < 24), 1.0, 0.0))
        rim, inside = float(luma[8:24, 8:24][0, 8]), float(luma[14:18, 14:18].mean())
        self.assertLess(rim, inside - 30)


class TileSeams(unittest.TestCase):
    """The tiles are the same whatever the blocks are cut: 2 x 2 tiles per block against 1 x 1."""

    def render_tiles(self, slug, directory, block_tiles):
        out = os.path.join(directory, f"out{block_tiles}")
        saved = render.BLOCK_TILES
        render.BLOCK_TILES = block_tiles
        try:
            render._data.clear()
            render._data.update(render.load(slug))
            render._data["out"] = out
            for task in render.tasks_for([2]):
                render._render(task)
        finally:
            render.BLOCK_TILES = saved
        return out

    def test_tiles_do_not_depend_on_the_block_size(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        slug = synthetic_map(directory)
        saved = render.PREP_DIR
        render.PREP_DIR = os.path.join(directory, "prep")
        self.addCleanup(setattr, render, "PREP_DIR", saved)
        big, small = self.render_tiles(slug, directory, 2), self.render_tiles(slug, directory, 1)
        names = sorted(os.listdir(os.path.join(big, "2")))
        self.assertEqual(len(names), 16)
        for name in names:
            self.assertEqual(open(os.path.join(big, "2", name), "rb").read(), open(os.path.join(small, "2", name), "rb").read(), name)

    def test_two_runs_give_the_same_bytes(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        slug = synthetic_map(directory)
        saved = render.PREP_DIR
        render.PREP_DIR = os.path.join(directory, "prep")
        self.addCleanup(setattr, render, "PREP_DIR", saved)
        first, second = self.render_tiles(slug, directory, 2), self.render_tiles(slug, directory, 2)
        for name in os.listdir(os.path.join(first, "2")):
            self.assertEqual(open(os.path.join(first, "2", name), "rb").read(), open(os.path.join(second, "2", name), "rb").read(), name)


class UniformBlocks(unittest.TestCase):
    """Blocks of open sea are not drawn: their tiles link one tile of the colour the drawing gives."""

    def tiles(self, sea_level, empty, draw_everything=False, directory=None):
        if directory is None:
            directory = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, directory)
            synthetic_map(directory, sea_level=sea_level, empty=empty)
        slug, = os.listdir(os.path.join(directory, "prep"))
        with mock.patch.object(render, "PREP_DIR", os.path.join(directory, "prep")), mock.patch.object(render, "BLOCK_TILES", 1):
            render._data.clear()
            render._data.update(render.load(slug))
            render._data["out"] = os.path.join(directory, "out")
            uniform = [render.uniform_block_colour(render._data, render.block_frame(render._data, 2, bx, by)) for _, bx, by in render.tasks_for([2])]
            with mock.patch.object(render, "uniform_block_colour", (lambda d, frame: None) if draw_everything else render.uniform_block_colour):
                for task in render.tasks_for([2]):
                    render._render(task)
        folder = os.path.join(directory, "out", "2")
        return uniform, {name: open(os.path.join(folder, name), "rb").read() for name in os.listdir(folder)}, folder

    def test_open_sea_is_linked_and_has_the_bytes_of_the_drawing(self):
        uniform, linked, folder = self.tiles(20.0, empty=True)
        self.assertEqual(set(uniform), {tuple(int(c) for c in render.WATER_DEEP_RGB)})
        self.assertTrue(all(os.stat(os.path.join(folder, name)).st_nlink == 16 for name in linked))
        _, drawn, _ = self.tiles(20.0, empty=True, draw_everything=True)
        self.assertEqual(linked, drawn)

    def test_a_render_into_a_folder_with_tiles_replaces_them(self):
        # The recovery render (--out <the .tmp folder>) writes over linked tiles: every tile is replaced, none changes its twins
        _, linked, folder = self.tiles(20.0, empty=True)
        directory = os.path.dirname(os.path.dirname(folder))
        _, again, _ = self.tiles(20.0, empty=True, directory=directory)
        self.assertEqual(again, linked)
        _, drawn, _ = self.tiles(20.0, empty=True, draw_everything=True, directory=directory)
        self.assertEqual(drawn, linked)
        self.assertTrue(all(os.stat(os.path.join(folder, name)).st_nlink == 1 for name in drawn))

    def test_shallow_sea_land_and_anything_on_the_water_are_drawn(self):
        self.assertEqual(set(self.tiles(10.0, empty=True)[0]), {None})
        self.assertEqual(set(self.tiles(None, empty=True)[0]), {None})
        self.assertEqual(set(self.tiles(20.0, empty=False)[0]), {None})


class GroundLight(unittest.TestCase):
    def test_flat_ground_gets_the_lights_height(self):
        flat = np.zeros((3, 3))
        np.testing.assert_allclose(render.ground_light(flat, flat), render.LIGHT[2])
        with mock.patch.object(render, "MULTIDIRECTIONAL_RELIEF", False):
            np.testing.assert_allclose(render.ground_light(flat, flat), render.LIGHT[2])

    def test_mdow_is_the_published_formula_of_slope_and_aspect(self):
        rng = np.random.default_rng(5)
        sx, sy = rng.normal(0, 0.7, (2, 200))
        elevation = math.asin(render.LIGHT[2])
        slope = np.arctan(np.hypot(sx, sy))
        aspect = np.arctan2(-sx, sy)  # bearing of the downhill direction (image y points south)
        shades, weights = [], []
        for azimuth in np.radians(render.RELIEF_AZIMUTHS):
            shades.append(np.maximum(np.sin(elevation) * np.cos(slope) + np.cos(elevation) * np.sin(slope) * np.cos(azimuth - aspect), 0))
            weights.append(np.sin(aspect - azimuth) ** 2)
        expected = sum(w * h for w, h in zip(weights, shades)) / sum(weights)
        np.testing.assert_allclose(render.ground_light(sx, sy), expected, atol=1e-12)

    def test_a_slope_turned_to_the_light_is_brighter(self):
        towards, away = (np.full((1, 1), 0.6), np.full((1, 1), 0.6)), (np.full((1, 1), -0.6), np.full((1, 1), -0.6))
        self.assertGreater(float(render.ground_light(*towards)[0, 0]), float(render.ground_light(*away)[0, 0]))
        with mock.patch.object(render, "MULTIDIRECTIONAL_RELIEF", False):
            self.assertGreater(float(render.ground_light(*towards)[0, 0]), float(render.ground_light(*away)[0, 0]))


class TerrainAndWaterMeshes(unittest.TestCase):
    """Meshes the scene has as terrain or water: the ground beyond the landscape where the server has none, and no objects."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        s = Scene(self.dir)
        mountain = s.add_mesh("MountainLow", [((0, 0, 0, 100000, 100000, 2500), OPAQUE)])
        sky = s.add_mesh("SkySphere", [((-100000, -100000, 3000, 100000, 100000, 3100), OPAQUE)])
        vista = s.add_mesh("FinalMesh", [((0, 0, 0, 1000, 1000, 1200), OPAQUE)])
        river = s.add_mesh("SM_env_river", [((0, 0, 0, 1000, 6000, 200), WATER)])
        house = s.add_mesh("House", [((0, 0, 0, 1000, 600, 500), OPAQUE)])
        copy = s.add_mesh("SM_T_LOD1", [((0, 0, 0, 100000, 100000, 50), OPAQUE)])
        s.place(copy, (-981, -990))  # the landscape copy reaches x = 19 m
        s.place(mountain, (40, 0))
        s.place(sky, (0, 0))
        s.place(vista, (0, 45), level="SquadGame/Content/Maps/T/L_080_Vista_T.umap")
        s.place(river, (25, 0))
        s.place(house, (5, 5))
        s.write()
        self.scene = so.SceneObjects(self.dir)
        self.land, self.water = so.surface_groups(self.dir)
        # The landscape covers x < 20 m at 5 m; east of it the server's floor, the served minimum up to the rounding of z_min
        self.ground = np.full((61, 61), 0.0001, np.float32)
        self.ground[:, :20] = 5.0
        self.cover = np.full((61, 61), features.NO_COVER, np.uint8)
        self.cover[:, :20] = 0
        self.no_terrain = np.zeros((61, 61), bool)

    def test_terrain_is_the_scenery_and_the_vista_but_not_the_sky_and_water_the_water_meshes(self):
        self.assertEqual(sorted(g["name"].rsplit(".", 1)[-1] for g in self.land), ["FinalMesh", "MountainLow", "SM_T_LOD1"])
        self.assertEqual([g["name"].rsplit(".", 1)[-1] for g in self.water], ["SM_env_river"])

    def test_a_void_takes_the_top_of_the_scenery(self):
        top = sp.surface_top(self.scene, self.land, self.ground.shape, BOUNDS)
        filled, count, _ = sp.scenery_ground(self.ground, self.cover, top, 0.0, self.no_terrain)
        self.assertEqual(float(filled[30, 50]), 25.0)
        self.assertEqual(count, 61 * 21)

    def test_a_void_without_scenery_keeps_its_floor(self):
        top = sp.surface_top(self.scene, self.land, self.ground.shape, BOUNDS)
        filled, _, _ = sp.scenery_ground(self.ground, self.cover, top, 0.0, self.no_terrain)
        self.assertAlmostEqual(float(filled[30, 30]), 0.0001, places=6)

    def test_the_landscape_and_small_voids_keep_their_ground(self):
        self.ground[:, 20:] = 7.0
        self.ground[10:13, 50:53] = 0.0
        top = sp.surface_top(self.scene, self.land, self.ground.shape, BOUNDS)
        filled, count, raised = sp.scenery_ground(self.ground, self.cover, top, 0.0, self.no_terrain)
        self.assertEqual(float(filled[30, 10]), 5.0)
        self.assertEqual(float(filled[11, 51]), 0.0)
        self.assertEqual(float(filled[30, 50]), 7.0)
        self.assertEqual((count, raised), (0, 0))

    def test_old_collision_of_terrain_and_water_meshes_is_no_object(self):
        ground = np.zeros((61, 61), np.float32)
        land_top, water_top = sp.surface_top(self.scene, self.land, ground.shape, BOUNDS), sp.surface_top(self.scene, self.water, ground.shape, BOUNDS)
        old = np.zeros((61, 61), np.uint16)
        old[28:33, 48:53] = 2500  # the mountain's collision
        old[30, 26] = 200  # the river mesh's
        old[50, 5] = 1200  # the Vista mesh's
        old[8, 8] = 500  # a house only the server has
        old[30, 58] = 3000  # a mast on the mountain, 5 m above it
        old[20, 10] = 120  # a wall on the low-poly copy of the landscape, a metre above it
        surfaces = sp.legacy_terrain(land_top, ground, 0.0, old, (61, 61)) | sp.legacy_water(water_top, ground, 0.0, old, (61, 61))
        self.assertTrue(surfaces[28:33, 48:53].all())
        self.assertFalse(surfaces[30, 58])
        self.assertTrue(surfaces[30, 26])
        self.assertTrue(surfaces[50, 5])
        self.assertFalse(surfaces[8, 8])
        self.assertFalse(surfaces[20, 10])


class ScenerySurface(unittest.TestCase):
    """The old raster's cells on a scenery mesh over ground that lies below it: the server traced the mesh, the scene has it as ground."""

    def surfaces(self, mesh_top_cm, old_cells):
        """legacy_terrain over flat ground at 0 m with one scenery mesh covering the grid, its top at mesh_top_cm; old_cells: [(rows, cols, cm)]."""
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        s = Scene(directory)
        s.place(s.add_mesh("EdgeMountain", [((0, 0, 0, 100000, 100000, mesh_top_cm), OPAQUE)]), (-500, -500))
        s.write()
        scene = so.SceneObjects(directory)
        land, _ = so.surface_groups(directory)
        ground = flat_ground()
        old = np.zeros(ground.shape, np.uint16)
        for rows, cols, height_cm in old_cells:
            old[rows, cols] = height_cm
        self.land_top = sp.surface_top(scene, land, ground.shape, BOUNDS)
        return sp.legacy_terrain(self.land_top, ground, 0.0, old, ground.shape)

    def test_a_mesh_a_little_above_the_ground_is_the_surface_the_old_raster_holds(self):
        # Gorodok's east edge: the landscape lies flat at 19.9 m, the mesh over it rises from 0.4 to 2.3 m, the old raster holds that rise
        old = [(slice(20, 40), slice(20, 40), 60), (50, 50, 560), (5, 5, 100)]
        surfaces = self.surfaces(60, old)
        self.assertTrue(surfaces[20:40, 20:40].all())
        self.assertFalse(surfaces[50, 50])  # a mast 5 m above the mesh
        self.assertFalse(surfaces[5, 5])  # a wall 0.4 m above it

    def test_objects_beside_a_mountain_do_not_make_it_an_object(self):
        # Gorodok's west edge: the collision of a mountain and of what stands beside it are one run of the old raster
        old = [(slice(20, 25), slice(20, 25), 2500), (slice(25, 33), slice(20, 25), 500)]
        surfaces = self.surfaces(2500, old)
        self.assertTrue(surfaces[20:25, 20:25].all())
        self.assertFalse(surfaces[25:33, 20:25].any())

    def test_the_landscape_under_a_mesh_the_server_collides_with_takes_the_meshs_height(self):
        # Gorodok's east edge: the landscape falls away under the Vista mesh, its last metres repeating one height per row
        self.surfaces(60, [])
        ground = np.full((61, 61), 1.0, np.float32)
        ground[:, 40:] = -2.0 - np.arange(61, dtype=np.float32)[:, None] * 0.1
        ground[10:20, 10:20] = -1.0  # a hollow under the mesh that the server holds nothing over
        old = np.zeros(ground.shape, np.uint16)
        old[:, 40:] = np.rint((0.6 - ground[:, 40:]) * 100)
        terrain = sp.legacy_terrain(self.land_top, ground, 0.0, old, ground.shape)
        filled, voids, raised = sp.scenery_ground(ground, np.zeros(ground.shape, np.uint8), self.land_top, 0.0, terrain)
        self.assertTrue(np.allclose(filled[:, 40:], 0.6))
        self.assertTrue(np.array_equal(filled[:, :40], ground[:, :40]))
        self.assertEqual((voids, raised), (0, 61 * 21))

    def test_a_block_standing_on_the_ground_is_no_hill(self):
        # Vista buildings with collision: the server holds their roofs, but lifted to them the ground would be a cliff all around
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        s = Scene(directory)
        s.place(s.add_mesh("VistaBlock", [((0, 0, 0, 1000, 1000, 1200), OPAQUE)]), (20, 20), level="SquadGame/Content/Maps/T/L_080_Vista_T.umap")
        s.write()
        land_top = sp.surface_top(so.SceneObjects(directory), so.surface_groups(directory)[0], (61, 61), BOUNDS)
        ground = flat_ground()
        old = np.zeros(ground.shape, np.uint16)
        old[20:31, 20:31] = 1200
        terrain = sp.legacy_terrain(land_top, ground, 0.0, old, ground.shape)
        self.assertTrue(terrain[20:31, 20:31].all())
        filled, _, raised = sp.scenery_ground(ground, np.zeros(ground.shape, np.uint8), land_top, 0.0, terrain)
        self.assertTrue(np.array_equal(filled, ground))
        self.assertEqual(raised, 0)

    def test_the_rim_of_an_area_and_its_steps(self):
        area = np.zeros((5, 5), bool)
        area[1:4, 1:5] = True
        ground = np.zeros((5, 5), np.float32)
        ground[0] = 3.0
        rim, step = sp.rim_steps(area, np.full((5, 5), 1.0, np.float32), ground)
        self.assertFalse(rim[2, 2] or rim[2, 4])  # inside, and at the grid's edge
        self.assertEqual((float(step[1, 2]), float(step[3, 2]), float(step[2, 1])), (2.0, 1.0, 1.0))

    def test_scenery_the_server_has_no_collision_for_is_not_the_ground(self):
        # Al Basrah: the Vista city's blocks stand over the landscape, and only SquadHeight holds them
        ground = flat_ground()
        self.surfaces(1200, [])
        filled, _, raised = sp.scenery_ground(ground, np.zeros(ground.shape, np.uint8), self.land_top, 0.0, np.zeros(ground.shape, bool))
        self.assertTrue(np.array_equal(filled, ground))
        self.assertEqual(raised, 0)


class SplineRoll(unittest.TestCase):
    """A spline mesh is turned about its spline by the component's roll, as the engine bends it."""

    def bent(self, roll):
        """A slab 10 m long (Y, its forward axis), 4 m wide (X) and 0.5 m thick (Z) along a straight spline that runs east."""
        vertices, _ = box_mesh(-200, 0, 0, 200, 1000, 50)
        positions = vertices[:, :3].astype(np.float64)
        end = {"X": 1000.0, "Y": 0.0, "Z": 0.0}
        spline = {"p": {"StartPos": {"X": 0.0, "Y": 0.0, "Z": 0.0}, "StartTangent": end, "StartRoll": roll, "EndPos": end, "EndTangent": end, "EndRoll": roll},
                  "axis": "Y", "up": {"X": 0.0, "Y": 0.0, "Z": 1.0}}
        return so.bend_along_spline(positions, spline, (positions.min(0), positions.max(0)))

    def test_a_quarter_turn_stands_a_mesh_that_runs_along_y_up(self):
        # Manicouagan's pipeline, crash barriers, railway tracks: the landscape splines give every such mesh this roll
        bent = self.bent(-math.pi / 2)
        np.testing.assert_allclose(bent.min(0), (0, -200, 0), atol=1e-6)
        np.testing.assert_allclose(bent.max(0), (1000, 200, 50), atol=1e-6)

    def test_without_a_roll_its_x_axis_is_up(self):
        bent = self.bent(0.0)
        np.testing.assert_allclose(bent.min(0), (0, 0, -200), atol=1e-6)
        np.testing.assert_allclose(bent.max(0), (1000, 50, 200), atol=1e-6)


class OldRasterNonObjects(unittest.TestCase):
    """What the old raster holds and the game does not show as an object is not kept: sheets, ground cover, SquadHeight's own, cells off the landscape."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        s = Scene(os.path.join(self.dir, "scene"))
        ice = s.add_mesh("Plane", [((0, 0, 0, 2000, 2000, 0), GLASS)])
        deck = s.add_mesh("Deck", [((0, 0, 0, 800, 800, 0), OPAQUE)])
        zone = s.add_mesh("Cube", [((0, 0, 0, 800, 800, 600), VOLUME)])
        s.place(ice, (5, 5, 3.0))  # translucent ice over a pond at x, y 5..25 m, 3 m up
        s.place(deck, (30, 5, 3.0))  # a deck the game shows
        s.place(deck, (30, 20, 3.0), hidden=True)  # the same sheet, hidden
        s.place(deck, (45, 30, 0.0), hidden=True)  # and one that lies on the ground
        s.place(zone, (45, 5))  # a volume the game does not show: no sheet
        s.write()
        statics = Statics(os.path.join(self.dir, "statics"))
        wall = statics.add_mesh("Wall", (0, 0, 0, 800, 50, 200))
        maize = statics.add_mesh("SM_Crop_Corn_Maize_A", (-60, -60, 0, 60, 60, 240))
        statics.place(wall, (30, 40))
        statics.place(maize, (10, 50))
        statics.place(maize, (20, 50), collision={"CollisionProfileName": "NoCollision"})
        statics.write()
        self.scene = so.SceneObjects(s.directory)
        self.statics = statics.directory
        self.ground = flat_ground()
        self.ground[5:26, 5:26] = -2.0  # the pond's bed
        self.cover = np.zeros(self.ground.shape, np.uint8)
        self.cover[:, 0] = features.NO_COVER

    def masks(self, old_cells):
        old = np.zeros(self.ground.shape, np.uint16)
        for rows, cols, height_cm in old_cells:
            old[rows, cols] = height_cm
        edges = {"left": [[5.0, 55.0], [25.0, 55.0]], "right": [[5.0, 57.6], [25.0, 57.6]], "center": [[5.0, 56.3, 0.0], [25.0, 56.3, 0.0]], "meshes": []}
        lines = [{"cls": "rail", **edges}, {"cls": "dirt", **{k: [[x + 25.0, *rest] for x, *rest in v] for k, v in edges.items() if k != "meshes"}, "meshes": []}]
        return sp.old_non_objects(self.scene, self.statics, [], lines, self.ground, self.cover, 0.0, old, BOUNDS, (60, 60))[0]

    def test_sheets_are_the_flat_meshes_the_game_does_not_show(self):
        sheets = so.sheet_groups(self.scene.directory)
        self.assertEqual([(g["name"].rsplit(".", 1)[-1], len(g["matrices"])) for g in sheets], [("Plane", 1), ("Deck", 1), ("Deck", 1)])
        self.assertEqual([float(g["matrices"][0][3, 1]) for g in sheets[1:]], [2000.0, 3000.0])  # the hidden decks

    def test_the_collision_of_an_ice_sheet_is_no_object(self):
        # Goose Bay: the server holds the ice over a pond as an object that stands at the sheet's height over the bed
        old = [(slice(5, 25), slice(5, 25), 500), (slice(12, 15), slice(12, 15), 900), (slice(8, 12), slice(32, 36), 300), (slice(22, 26), slice(32, 36), 300),
               (slice(31, 35), slice(46, 52), 80)]
        sheets = self.masks(old)["sheets"]
        self.assertTrue(sheets[5:12, 5:25].all())  # the ice, up to the pond's bank: the height is over the lowest ground of the metre
        self.assertFalse(sheets[12:15, 12:15].any())  # a hut on the ice, 4 m above it
        self.assertFalse(sheets[8:12, 32:36].any())  # what the server holds at the height of the deck the game shows
        self.assertTrue(sheets[22:26, 32:36].all())  # and of the hidden one
        self.assertFalse(sheets[31:35, 46:52].any())  # Harju: a crash barrier beside a sheet that lies on the ground

    def test_the_lowest_ground_of_a_metre_is_that_of_the_old_rasters_points(self):
        ground = np.array([[0.0, 4.0, 4.0], [0.0, 4.0, 0.0]], np.float32)
        lowest = sp.lowest_ground(ground, (2, 2))
        # the points reach three quarters of the way to the next node: towards a corner 4 m lower, and along the grid's last row
        self.assertEqual(lowest.tolist(), [[0.0, 1.75], [0.0, 1.0]])

    def test_the_collision_of_ground_cover_is_no_object(self):
        # Yehorivka: maize plants set by hand block; the plants of a field do not, and a wall beside them stays
        masks = self.masks([])
        self.assertTrue(masks["ground_cover"][50, 10])
        self.assertFalse(masks["ground_cover"][50, 20])
        self.assertFalse(masks["ground_cover"][40, 34])

    def test_what_no_static_mesh_explains_is_squadheights_and_no_object(self):
        # Al Basrah: SquadHeight holds blocks of a Vista city that the game build does not have
        masks = self.masks([])
        self.assertTrue(masks["without_collision"][30, 30])
        self.assertFalse(masks["without_collision"][40, 34])  # the server's wall
        self.assertFalse(masks["without_collision"][50, 10])  # ground cover has collision: its own mask takes it

    def test_the_collision_of_a_railway_track_is_no_object(self):
        # Manicouagan: the tracks' collision is 0.3 to 0.45 m high; the tiles draw the railway from its spline
        masks = self.masks([])
        self.assertTrue(masks["railway"][55:58, 5:26].all())
        self.assertFalse(masks["railway"][53, 15] or masks["railway"][59, 15])
        self.assertFalse(masks["railway"][55:58, 30:51].any())  # a dirt road's segment

    def test_cells_off_the_landscape_are_no_objects(self):
        # Gorodok: the first column lies on SquadHeight's surface, 15 m above the landscape's first node
        masks = self.masks([])
        self.assertTrue(masks["off_landscape"][:, 0].all())
        self.assertFalse(masks["off_landscape"][:, 1:].any())


class RoadWidth(unittest.TestCase):
    """The visible width of road meshes from their materials: a road mesh 4 m wide (local Y -200..200 cm, U across it) on a small scene."""

    ROAD = "/Game/M/Road.Road"
    DIRT = "/Game/M/MI_Dirt.MI_Dirt"
    MASKED = "/Game/M/MI_Masked.MI_Masked"
    ROAD_MASKS = "/Game/M/MI_Roads.MI_Roads"
    RVT_ROAD = "/Game/M/MI_Road_RVT.MI_Road_RVT"
    DECAL = "/Game/M/MI_Decal.MI_Decal"

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory)
        os.makedirs(os.path.join(self.directory, "meshes"))
        os.makedirs(os.path.join(self.directory, "textures"))
        self.textures, self.items = {}, []
        self.materials = {
            OPAQUE: {"blend": "BLEND_Opaque"},
            self.DIRT: {"blend": "BLEND_Masked", "textures": {"PM_Diffuse": "/T/Diffuse.Diffuse"}},
            self.MASKED: {"blend": "BLEND_Masked", "textures": {"Albedo": "/T/Fringe.Fringe"}},
            self.ROAD_MASKS: {"blend": "BLEND_Masked", "textures": {"Masks": "/T/Masks.Masks", "Road_texture_01_A": "/T/Opaque.Opaque"}},
            self.RVT_ROAD: {"blend": "BLEND_Opaque"},
            self.DECAL: {"blend": "BLEND_Translucent", "textures": {"Albedo": "/T/Fringe.Fringe"}},
        }
        # Eight columns across U (the texture repeats, so a visible first column needs a visible last one next to it): the alpha of the colour
        # texture of a plain road, one with a wide transparent left fringe and a narrow right one, one without any
        self.texture("/T/Diffuse.Diffuse", alpha=[0, 255, 255, 255, 255, 255, 255, 0])
        self.texture("/T/Fringe.Fringe", alpha=[0, 0, 255, 255, 255, 255, 255, 0])
        self.texture("/T/Opaque.Opaque", alpha=[255] * 8)
        self.texture("/T/Masks.Masks", alpha=[255] * 8, green=[0, 0, 0, 255, 255, 255, 255, 0])
        self.mesh_id = 0
        self.meshes = {}

    def texture(self, path, alpha, green=None):
        index = len(self.textures)
        pixels = np.zeros((2, len(alpha), 4), np.uint8)
        pixels[..., 1] = 255 if green is None else green
        pixels[..., 3] = alpha
        pixels.tofile(os.path.join(self.directory, "textures", f"{index}.bin"))
        self.textures[path] = {"file": str(index), "format": "PF_R8G8B8A8", "width": len(alpha), "height": 2}

    def road_mesh(self, name, materials, flip_u=False, sections=1, along_y=False):
        """A mesh 900 cm long and 400 cm wide with U across it (increasing with Y, or decreasing with ``flip_u``), cut into ``sections`` strips across.

        ``along_y``: the mesh runs along its Y axis and is 400 cm wide in X, with U increasing with X.
        """
        ys = np.linspace(-200, 200, sections + 1)
        vertices = []
        for y in ys:
            u = 0.5 - y / 400 if flip_u else 0.5 + y / 400
            for x, v in ((-450, 0.0), (450, 1.0)):
                vertices.append((y, x, 0, 0, 0, 1, u, v) if along_y else (x, y, 0, 0, 0, 1, u, v))
        indices, info = [], []
        for k in range(sections):
            a = 2 * k
            info.append({"material": k, "first": len(indices), "triangles": 2})
            indices += [a, a + 1, a + 2, a + 1, a + 3, a + 2]
        mesh_id = self.mesh_id
        self.mesh_id += 1
        with open(os.path.join(self.directory, "meshes", f"{mesh_id}.bin"), "wb") as handle:
            handle.write(np.array(vertices, np.float32).tobytes())
            handle.write(np.array(indices, np.uint32).tobytes())
        path = f"/Game/M/{name}.{name}"
        self.meshes[path] = {"id": mesh_id, "materials": list(materials), "lod": 0, "vertices": len(vertices), "indices": len(indices), "sections": info}
        return path

    def spline(self, flip=False, axis="X", roll=0.0):
        """A straight spline 9 m east; ``flip``: the scale of the frame's X vector is negative."""
        side = -1.0 if flip else 1.0
        return {"p": {"StartPos": {"X": -450.0, "Y": 0.0, "Z": 0.0}, "StartTangent": {"X": 900.0, "Y": 0.0, "Z": 0.0}, "StartScale": {"X": side, "Y": 1.0},
                      "StartRoll": roll, "EndPos": {"X": 450.0, "Y": 0.0, "Z": 0.0}, "EndTangent": {"X": 900.0, "Y": 0.0, "Z": 0.0},
                      "EndScale": {"X": side, "Y": 1.0}, "EndRoll": roll},
                "axis": axis, "up": {"X": 0.0, "Y": 0.0, "Z": 1.0}}

    def lay(self, mesh_path, x, y, overrides=(), owner="Landscape", **spline):
        """A spline mesh component laid straight along X with its middle at world (x, y) metres (``spline``: the arguments of self.spline)."""
        mesh = self.meshes[mesh_path]
        self.items.append({"level": "SquadGame/Content/Maps/T/L.umap", "name": "SplineMeshComponent_0", "type": "SplineMeshComponent", "owner": owner,
                           "mesh": mesh["id"], "hidden": False, "cull": [0, 0, 0, 0], "overrides": list(overrides), "chain": chain(x, y), "instances": None,
                           "spline": self.spline(**spline)})

    def write(self):
        json.dump(self.meshes, open(os.path.join(self.directory, "meshes.json"), "w"))
        json.dump(self.materials, open(os.path.join(self.directory, "materials.json"), "w"))
        json.dump(self.textures, open(os.path.join(self.directory, "textures.json"), "w"))
        with open(os.path.join(self.directory, "instances.ndjson"), "w") as handle:
            handle.write("\n".join(json.dumps(item) for item in self.items))

    def span_of(self, mesh_path, materials=None, side=1):
        self.write()
        info = self.meshes[mesh_path]
        vertices, indices = so.read_mesh(self.directory, info)
        return rw.mesh_span(vertices, indices, info, materials or info["materials"], self.materials, rw.Textures(self.directory), side)

    def test_an_opaque_material_shows_the_whole_width(self):
        span, sources = self.span_of(self.road_mesh("Opaque", [OPAQUE]))
        self.assertEqual(span, (0.0, 1.0))
        self.assertEqual(sources, {rw.OPAQUE})

    def test_a_masked_material_loses_the_fringes_below_the_alpha_clip(self):
        span, sources = self.span_of(self.road_mesh("Dirt", [self.DIRT]))
        # alpha 0 at the centre of the first column (u = 1/16), 1 at the next (3/16): 0.33 is reached a third of the way
        self.assertAlmostEqual(span[0], 1 / 16 + rw.OPACITY_CLIP * 2 / 16, delta=0.01)
        self.assertAlmostEqual(span[1], 1 - span[0], delta=0.01)
        self.assertEqual(sources, {rw.ALPHA})

    def test_a_fringe_on_one_side_gives_an_asymmetric_span(self):
        span, _ = self.span_of(self.road_mesh("Fringe", [self.MASKED]))
        # alpha 0 up to the centre of the second column (3/16), 1 at the third (5/16); 1 at the seventh (13/16), 0 at the last (15/16)
        self.assertAlmostEqual(span[0], 3 / 16 + rw.OPACITY_CLIP * 2 / 16, delta=0.01)
        self.assertAlmostEqual(span[1], 13 / 16 + (1 - rw.OPACITY_CLIP) * 2 / 16, delta=0.01)

    def test_the_texture_coordinate_running_against_the_side_axis_is_followed(self):
        span, _ = self.span_of(self.road_mesh("FringeFlipped", [self.MASKED], flip_u=True))
        self.assertAlmostEqual(span[0], 1 - (13 / 16 + (1 - rw.OPACITY_CLIP) * 2 / 16), delta=0.01)
        self.assertAlmostEqual(span[1], 1 - (3 / 16 + rw.OPACITY_CLIP * 2 / 16), delta=0.01)

    def test_road_layers_take_their_opacity_from_the_green_channel_of_the_masks(self):
        span, sources = self.span_of(self.road_mesh("Roads", [self.ROAD_MASKS]))
        # green 0 up to the centre of the third column (5/16), 1 at the fourth (7/16)
        self.assertAlmostEqual(span[0], 5 / 16 + rw.OPACITY_CLIP * 2 / 16, delta=0.01)
        self.assertAlmostEqual(span[1], 13 / 16 + (1 - rw.OPACITY_CLIP) * 2 / 16, delta=0.01)
        self.assertEqual(sources, {rw.MASK})

    def test_a_road_painting_the_virtual_texture_ramps_in_over_a_fifth_of_each_side(self):
        span, sources = self.span_of(self.road_mesh("Rvt", [self.RVT_ROAD]))
        self.assertAlmostEqual(span[0], 0.07, delta=0.01)
        self.assertAlmostEqual(span[1], 0.93, delta=0.01)
        self.assertEqual(sources, {rw.SOFT})

    def test_the_components_material_slots_override_the_meshs(self):
        mesh = self.road_mesh("Slots", [OPAQUE])
        self.assertEqual(self.span_of(mesh)[0], (0.0, 1.0))
        self.assertGreater(self.span_of(mesh, [self.DIRT])[0][0], 0.05)

    def test_sections_add_up_and_a_hidden_section_adds_nothing(self):
        mesh = self.road_mesh("Strips", [self.MASKED, OPAQUE, self.DECAL], sections=3)
        span, sources = self.span_of(mesh)
        # the strips are 1/3 wide: the first (the fringe's left part) loses its start, the opaque middle one is whole, the decal is not drawn
        self.assertAlmostEqual(span[0], 3 / 16 + rw.OPACITY_CLIP * 2 / 16, delta=0.01)
        self.assertAlmostEqual(span[1], 2 / 3, delta=0.01)
        self.assertEqual(sources, {rw.ALPHA, rw.OPAQUE, rw.HIDDEN})

    def test_a_mesh_with_nothing_shown_has_no_span(self):
        self.assertIsNone(self.span_of(self.road_mesh("Decal", [self.DECAL]))[0])

    def line(self, y, cls="dirt", meshes=(), x0=0.0, x1=60.0):
        """A straight segment from x0 to x1 east at y, 4 m wide: left (north) edge y - 2, right (south) edge y + 2."""
        return {"cls": cls, "meshes": list(meshes), "left": [[x0, y - 2], [x1, y - 2]], "right": [[x0, y + 2], [x1, y + 2]],
                "center": [[x0, y, 10.0], [x1, y, 10.0]]}

    def test_segments_take_the_span_of_the_variant_laid_along_them(self):
        dirt, opaque = self.road_mesh("Dirt", [OPAQUE]), self.road_mesh("Opaque", [OPAQUE])
        self.lay(dirt, 30, 10, overrides=[self.DIRT])
        self.lay(dirt, 30, 20)
        self.lay(opaque, 30, 30)
        self.write()
        lines = [self.line(10, meshes=[dirt]), self.line(20, meshes=[dirt]), self.line(30, meshes=[opaque]), self.line(40, meshes=[dirt]),
                 self.line(10, cls="river", meshes=[dirt])]
        narrowed = rw.narrowed_lines(self.directory, lines)
        self.assertIn("span", narrowed[0])
        self.assertNotIn("span", narrowed[1])
        self.assertNotIn("span", narrowed[2])
        self.assertNotIn("span", narrowed[3])
        self.assertEqual(narrowed[4], lines[4])

    def test_edges_move_in_and_the_centre_line_follows(self):
        mesh = self.road_mesh("Fringe", [self.MASKED])
        self.lay(mesh, 30, 10)
        self.write()
        (line,) = rw.narrowed_lines(self.directory, [self.line(10, meshes=[mesh])])
        lo, hi = line["span"]
        self.assertAlmostEqual(line["left"][0][1], 8 + 4 * lo, places=2)
        self.assertAlmostEqual(line["right"][1][1], 8 + 4 * hi, places=2)
        self.assertAlmostEqual(line["center"][0][1], 8 + 2 * (lo + hi), places=2)
        self.assertEqual(line["center"][0][2], 10.0)
        self.assertEqual(line["left"][0][0], 0.0)

    def test_a_mirrored_component_swaps_the_sides(self):
        mesh = self.road_mesh("Fringe", [self.MASKED])
        self.lay(mesh, 30, 10)
        self.lay(mesh, 30, 20, flip=True)
        self.write()
        straight, mirrored = rw.narrowed_lines(self.directory, [self.line(10, meshes=[mesh]), self.line(20, meshes=[mesh])])
        self.assertAlmostEqual(mirrored["span"][0], 1 - straight["span"][1], places=3)
        self.assertAlmostEqual(mirrored["span"][1], 1 - straight["span"][0], places=3)

    def test_a_mesh_that_runs_along_y_is_measured_across_the_axis_its_roll_lays_level(self):
        # Al Basrah's and Fallujah's pavements, the rail crossings of Narva and Harju: road meshes modelled along Y, which the
        # landscape spline rolls by -90 degrees to stand them up
        mesh = self.road_mesh("FringeAlongY", [self.MASKED], along_y=True)
        across_x, _ = self.span_of(mesh, side=0)
        self.assertAlmostEqual(across_x[0], 3 / 16 + rw.OPACITY_CLIP * 2 / 16, delta=0.01)
        self.assertAlmostEqual(across_x[1], 13 / 16 + (1 - rw.OPACITY_CLIP) * 2 / 16, delta=0.01)
        # Z, the side axis of the bend without the roll, is the mesh's height: it has no width to show a part of
        self.assertIsNone(self.span_of(mesh, side=2)[0])

    def test_a_rolled_mesh_narrows_its_segment_on_the_side_the_roll_turns_it_to(self):
        mesh = self.road_mesh("FringeAlongY", [self.MASKED], along_y=True)
        self.lay(mesh, 30, 10, axis="Y", roll=-math.pi / 2)
        self.write()
        (line,) = rw.narrowed_lines(self.directory, [self.line(10, meshes=[mesh])])
        # The wide transparent fringe is at the mesh's -X edge, which the bend lays south of the spline, the segment's right
        vertices, _ = so.read_mesh(self.directory, self.meshes[mesh])
        bent = so.bend_along_spline(vertices.astype(np.float64), self.spline(axis="Y", roll=-math.pi / 2), (vertices[:, :3].min(0), vertices[:, :3].max(0)))
        np.testing.assert_allclose(bent[vertices[:, 0] < 0, 1], 200.0, atol=1e-6)
        self.assertIn("span", line, "the segment keeps its whole width")
        self.assertAlmostEqual(line["span"][0], 1 - (13 / 16 + (1 - rw.OPACITY_CLIP) * 2 / 16), delta=0.01)
        self.assertAlmostEqual(line["span"][1], 1 - (3 / 16 + rw.OPACITY_CLIP * 2 / 16), delta=0.01)
        self.assertAlmostEqual(line["right"][0][1], 8 + 4 * line["span"][1], places=2)

    def test_a_quarter_turn_the_other_way_keeps_the_sides_of_the_mesh(self):
        mesh = self.road_mesh("FringeAlongY", [self.MASKED], along_y=True)
        self.lay(mesh, 30, 10, axis="Y", roll=math.pi / 2)
        self.write()
        (line,) = rw.narrowed_lines(self.directory, [self.line(10, meshes=[mesh])])
        self.assertIn("span", line, "the segment keeps its whole width")
        self.assertAlmostEqual(line["span"][0], 3 / 16 + rw.OPACITY_CLIP * 2 / 16, delta=0.01)

    def test_components_that_are_not_the_landscapes_are_ignored(self):
        mesh = self.road_mesh("Dirt", [self.DIRT])
        self.lay(mesh, 30, 10, owner="BP_Prop_C")
        self.write()
        (line,) = rw.narrowed_lines(self.directory, [self.line(10, meshes=[mesh])])
        self.assertNotIn("span", line)

    def test_a_narrowed_road_is_drawn_at_its_visible_width(self):
        mesh = self.road_mesh("Fringe", [self.MASKED])
        self.lay(mesh, 30, 30)
        self.write()
        lines = [self.line(30, meshes=[mesh])]
        narrowed = rw.narrowed_lines(self.directory, lines)
        widths = {}
        for tag, drawn in (("full", lines), ("narrowed", narrowed)):
            directory = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, directory)
            slug = synthetic_map(directory, empty=True)
            json.dump(drawn, open(os.path.join(directory, "prep", slug, "top_lines.json"), "w"))
            saved = render.PREP_DIR
            render.PREP_DIR = os.path.join(directory, "prep")
            self.addCleanup(setattr, render, "PREP_DIR", saved)
            d = render.load(slug)
            frame = render.block_frame(d, 2, 0, 0)
            mask = render.polygon_mask(frame, d["lines"], frame.world_box(8), 0.0)
            column = mask[:, int(frame.to_px(30.0, 30.0)[0])]
            widths[tag] = float(column.sum()) * frame.px_y
        self.assertAlmostEqual(widths["full"], 4.0, delta=0.1)
        self.assertAlmostEqual(widths["narrowed"], 4.0 * (narrowed[0]["span"][1] - narrowed[0]["span"][0]), delta=0.1)


class PaintedTracks(unittest.TestCase):
    """The weight of the path layers of the landscape on the 1 m grid, from a small scene written to a temporary folder."""

    def write_component(self, directory, level, layers, relative=(0.0, 0.0)):
        """A 2 x 2 quad component at the world origin in `level`: weight 200 in the first channel, 55 in the second, `layers` naming
        them [(name, channel)]."""
        folder = os.path.join(directory, "landscape", level, "wm")
        os.makedirs(folder)
        pixels = np.zeros((4, 4, 4), np.uint8)
        pixels[..., landscape_paths.CHANNEL_BYTE[0]] = 200
        pixels[..., landscape_paths.CHANNEL_BYTE[1]] = 55
        open(os.path.join(folder, "Texture2D_0.bin"), "wb").write(pixels.tobytes())
        component = {"location": [0.0, 0.0, 0.0], "scale": [100.0, 100.0, 100.0], "yaw": 0.0, "relative": list(relative),
                     "componentSizeQuads": 2, "subsectionSizeQuads": 1, "numSubsections": 2, "weightmapTextures": ["Texture2D_0"],
                     "layers": [{"layer": name, "texture": 0, "channel": channel} for name, channel in layers]}
        json.dump([component], open(os.path.join(directory, "landscape", level, "components.json"), "w"))

    def test_the_path_layer_weight_on_the_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_component(directory, "L_Landscape", [("Path_LayerInfo", 0), ("Sand_LayerInfo", 1)])
            weights = landscape_paths.path_weights(directory, {"min_x": 0.0, "min_y": 0.0}, (4, 4))
        self.assertEqual(int(weights[1, 1]), 200)
        self.assertEqual(int(weights[3, 3]), 0)

    def test_names_of_path_layers(self):
        for name in ("Path_LayerInfo", "mat05_path_LayerInfo", "mat06_rockpath_LayerInfo", "Grusvei_LayerInfo"):
            self.assertTrue(landscape_paths.PATH_LAYER.search(name), name)
        for name in ("Grass_LayerInfo", "Asphalt_PhysMat_LayerInfo", "Pathway_Grass", "SandRocks_LayerInfo"):
            self.assertFalse(landscape_paths.PATH_LAYER.search(name), name)

    def test_a_repeated_component_without_paint_keeps_the_painted_one(self):
        with tempfile.TemporaryDirectory() as directory:
            self.write_component(directory, "L_Landscape", [("Path_LayerInfo", 0)])
            self.write_component(directory, "L_Landscape_WP", [("Path_LayerInfo", 2)])
            weights = landscape_paths.path_weights(directory, {"min_x": 0.0, "min_y": 0.0}, (3, 3))
        self.assertEqual(int(weights.min()), 200)

    def test_a_map_without_a_landscape_folder_has_no_tracks(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(int(landscape_paths.path_weights(directory, {"min_x": 0.0, "min_y": 0.0}, (3, 3)).max()), 0)


class HdWindows(unittest.TestCase):
    def test_windows_lie_wholly_inside_the_map(self):
        # Gorodok's largest "roofs" are the walls along its border, 0.5 m from the edge: a window there is half empty
        bounds = {"min_x": -2032.0, "max_x": 2032.0, "min_y": -2032.0, "max_y": 2032.0}
        labels = [{"x": 2031.5, "y": 333.5, "area": 900}, {"x": 764.5, "y": -1427.5, "area": 500}, {"x": -1993.6, "y": 0.0, "area": 400},
                  {"x": 800.0, "y": -1400.0, "area": 300}, {"x": -311.5, "y": -1431.5, "area": 200}]
        self.assertEqual(check_alignment.hd_window_centres(labels, bounds), [(764.5, -1427.5), (-1993.6, 0.0), (-311.5, -1431.5)])

    def test_the_gate_passes_on_the_median_of_enough_windows(self):
        offsets = [(0.04, -0.02), (0.06, 0.0), (0.05, -0.01), (0.30, 0.10)]
        report = check_alignment.hd_verdict(offsets)
        self.assertTrue(report["pass"])
        self.assertEqual(report["offset_m"], [0.055, -0.005])
        self.assertEqual(report["max_deviation_m"], 0.245)
        self.assertEqual(report["within_pass_m"], 3)

    def test_the_gate_fails_on_too_few_windows_or_a_median_beyond_the_limit(self):
        self.assertFalse(check_alignment.hd_verdict([(0.0, 0.0)] * (check_alignment.HD_MIN_WINDOWS - 1))["pass"])
        self.assertFalse(check_alignment.hd_verdict([(0.0, 0.12)] * check_alignment.HD_MIN_WINDOWS)["pass"])
        self.assertEqual(check_alignment.hd_verdict([]), {"measured": 0, "pass": False})


class HeightmapGridTest(unittest.TestCase):
    def test_a_half_metre_heightmap_is_sampled_on_the_ground_metres(self):
        ground = np.arange(16, dtype=np.float64).reshape(4, 4)
        fine = np.full((7, 7), -1.0)
        fine[::2, ::2] = ground
        self.assertTrue(np.array_equal(check_alignment.on_ground_grid(fine, ground), ground))

    def test_a_heightmap_on_the_ground_grid_is_kept(self):
        ground = np.ones((5, 5))
        self.assertIs(check_alignment.on_ground_grid(ground, ground), ground)

    def test_a_grid_that_does_not_refine_the_ground_is_refused(self):
        with self.assertRaises(ValueError):
            check_alignment.on_ground_grid(np.ones((8, 8)), np.ones((4, 4)))


class OutlineEvaluator(unittest.TestCase):
    def test_tiles_are_resampled_with_each_axis_scale(self):
        # A 100 x 200 m map, one 256 px tile whose red channel is its pixel row: y = 100 m is row 128 (the x scale gives row 256)
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(os.path.join(directory, "0"))
            rows = np.repeat(np.arange(256, dtype=np.uint8)[:, None], 256, 1)
            render.Image.fromarray(np.stack([rows, rows, rows], -1)).save(os.path.join(directory, "0", "0_0.webp"), lossless=True)
            picture = outline_accuracy.mosaic_on_grid(directory, 0, (0.0, 0.0, 100.0, 200.0), (0.0, 100.0), (1.0, 1.0), (4, 4))
        self.assertLess(abs(float(picture[0, 0, 0]) - (100.5 / 200 * 256 - 0.5)), 1.0)

    def test_tile_edges_match_the_truth_count_in_the_region(self):
        rng = np.random.default_rng(1)
        magnitude = rng.random((40, 40))
        region = np.zeros((40, 40), bool)
        region[10:30, 10:30] = True
        self.assertEqual(int((outline_accuracy.strongest(magnitude, 57, region) & region).sum()), 57)

    def test_a_clear_peak_gives_the_shift_and_noise_none(self):
        # 60 random building outlines on 256 px, searched over 40 px (the pairs' 0.49 m step searches 61 px)
        rng = np.random.default_rng(3)
        truth = np.zeros((256, 256), bool)
        for _ in range(60):
            (y, x), (h, w) = rng.integers(5, 230, 2), rng.integers(5, 20, 2)
            truth[[y, y + h], x:x + w] = True
            truth[y:y + h, [x, x + w]] = True
        shifted = np.roll(truth, (-3, 2), (0, 1))
        shift, measured, _ = outline_accuracy.best_shift(outline_accuracy.correlation(truth, shifted), 40)
        self.assertEqual((shift, measured), ((3, -2), True))
        noise = rng.random((256, 256)) > 0.9
        shift, measured, _ = outline_accuracy.best_shift(outline_accuracy.correlation(truth, noise), 40)
        self.assertEqual((shift, measured), ((0, 0), False))


class SeaLevel(unittest.TestCase):
    def test_only_the_ocean_blueprints_set_the_sea(self):
        # Manicouagan: an ocean at 38 m and the shore's ambient sound splines along the reservoir up to 117 m
        def actor(name, z_cm):
            return json.dumps({"actor": name, "chain": [{"l": {"X": 0.0, "Y": 0.0, "Z": z_cm}, "r": {"Pitch": 0.0, "Yaw": 0.0, "Roll": 0.0},
                                                          "s": {"X": 1.0, "Y": 1.0, "Z": 1.0}}]})
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "water.ndjson"), "w") as out:
                for name, z in [("BP_Ocean_Squad_C", 3800.0), ("BP_OceanVertexAnim_Manager_C", 0.0), ("BP_VolumetricOceanFog_C", 9000.0)] +                         [("BP_SoundSpline_ambience_ocean_calm_01_C", 11700.0)] * 3:
                    out.write(actor(name, z) + "\n")
            self.assertAlmostEqual(features.sea_level(directory), 38.0, places=3)
            with open(os.path.join(directory, "water.ndjson"), "w") as out:
                out.write(actor("BP_SoundSpline_ambience_ocean_calm_01_C", 8000.0) + "\n")
            self.assertIsNone(features.sea_level(directory))


if __name__ == "__main__":
    unittest.main()
