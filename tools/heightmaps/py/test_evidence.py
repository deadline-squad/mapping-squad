"""Tests of evidence.py, the placements of the game that explain SquadHeight's objects: python -m unittest test_evidence

The grids have a point every metre from (0, 0); a block of SquadHeight's surface stands 8 m above flat ground at 10 m on the
points 10..14 east and south.
"""

import json
import math
import os
import shutil
import tempfile
import unittest

import numpy as np

import evidence

BOUNDS = {"min_x": 0.0, "min_y": 0.0, "max_x": 39.0, "max_y": 39.0}
IDENTITY = {"r": {"Pitch": 0.0, "Yaw": 0.0, "Roll": 0.0}, "s": {"X": 1.0, "Y": 1.0, "Z": 1.0}}


def link(x=0.0, y=0.0, z=0.0, yaw=0.0, scale=1.0):
    """One link of an attach chain: a placement at (x, y, z) metres."""
    return {"l": {"X": x * 100, "Y": y * 100, "Z": z * 100}, "r": {"Pitch": 0.0, "Yaw": yaw, "Roll": 0.0}, "s": {"X": scale, "Y": scale, "Z": scale}}


class Explained(unittest.TestCase):
    def setUp(self):
        self.surface = np.full((40, 40), 10.0)
        self.surface[10:15, 10:15] = 18.0
        self.wanted = self.surface > 10.0

    def explained(self, *boxes, step=1.0, surfaces=()):
        return evidence.explained(self.surface, self.wanted, np.array(boxes, np.float64).reshape(-1, 6), BOUNDS, step, surfaces)

    @staticmethod
    def sheet(height, x0=-71000.0, y0=-71000.0, x1=71000.0, y1=71000.0, slope=0.0):
        """Two triangles [2, 3, 3] of a rectangle at ``height`` metres at x0, rising ``slope`` metres per metre east."""
        corner = lambda x, y: (x, y, height + slope * (x - x0))
        return np.array([[corner(x0, y0), corner(x1, y0), corner(x1, y1)], [corner(x0, y0), corner(x1, y1), corner(x0, y1)]])

    def test_a_box_that_holds_the_surface_explains_the_points_under_it(self):
        np.testing.assert_array_equal(self.explained((10, 10, 10, 14, 14, 18)), self.wanted)

    def test_the_margin_reaches_a_metre_around_and_beyond_the_box(self):
        # A roof whose mesh ends a metre inside the collision that SquadHeight traced, and half a metre below it
        np.testing.assert_array_equal(self.explained((11, 11, 10, 13, 13, 17.5)), self.wanted)
        short = self.explained((12.5, 12.5, 10, 13, 13, 18))
        self.assertTrue(short[12:15, 12:15].all())
        self.assertFalse(short[10, 10] or short[11, 14])

    def test_a_box_below_or_above_the_surface_explains_nothing(self):
        # A road mesh under the block, a cable over it
        self.assertFalse(self.explained((0, 0, 9.9, 39, 39, 10.2), (0, 0, 25, 39, 39, 30)).any())

    def test_a_box_is_vast_when_it_is_both_wide_and_long(self):
        boxes = np.array([(-5000, -5000, 0, 5000, 5000, 300), (-1500, 9, 10, 1500, 15, 18), (0, 0, 0, 800, 800, 5), (0, 0, 0, 801, 801, 5)], np.float64)
        self.assertEqual(evidence.is_vast(boxes).tolist(), [True, False, False, True])

    def test_the_mesh_of_a_vast_placement_explains_the_surface_it_passes_through(self):
        # The ocean plane: SquadHeight's trace stops on the water, and a block above it is no water
        self.surface[30:35, 0:40] = 12.0
        self.wanted = self.surface > 10.0
        sea = self.explained(surfaces=[self.sheet(12.0)])
        self.assertTrue(sea[30:35].all())
        self.assertFalse(sea[10:15, 10:15].any())

    def test_a_mountain_mesh_explains_the_points_that_follow_it(self):
        # Kamdesh: the background mountains' foot stands on the landscape, and SquadHeight follows the mesh
        slope = self.sheet(10.0, x0=0.0, y0=20.0, x1=39.0, y1=39.0, slope=1.0)
        self.surface[20:40] = 10.0 + np.arange(40.0)
        self.surface[25, 5] += 0.9
        self.surface[26, 6] -= 0.9
        self.surface[30, 30] += 6.0
        self.wanted = self.surface > 10.0
        mountain = self.explained(surfaces=[slope])
        self.assertTrue(mountain[20:40, 1:][np.arange(20) != 10][:, np.arange(39) != 29].all())
        self.assertTrue(mountain[25, 5] and mountain[26, 6])  # within the margin above and below the mesh
        self.assertFalse(mountain[30, 30])  # a block standing on the mountain
        self.assertFalse(mountain[:20].any())  # nothing of the mesh over the block on the plain

    def test_a_mesh_far_above_and_below_explains_nothing(self):
        # A sky sphere around the map
        self.assertFalse(self.explained(surfaces=[self.sheet(5000.0), self.sheet(-5000.0)]).any())

    def test_under_an_unexplained_block_the_vast_meshes_below_it_are_found(self):
        # Al Basrah: a block of the SDK's map standing in the river, the ocean plane 6 m under its top, a sky sphere far above
        below = evidence.surface_below(self.surface, self.wanted, [self.sheet(12.0), self.sheet(11.0), self.sheet(5000.0)], BOUNDS, 1.0)
        np.testing.assert_allclose(below[10:15, 10:15], 12.0, atol=1e-9)
        self.assertTrue(np.isneginf(below[~self.wanted]).all())
        self.assertTrue(np.isneginf(evidence.surface_below(self.surface, self.wanted, [self.sheet(18.5)], BOUNDS, 1.0)).all())

    def test_boxes_and_meshes_add_up(self):
        self.surface[30:35, 0:40] = 12.0
        self.wanted = self.surface > 10.0
        np.testing.assert_array_equal(self.explained((10, 10, 10, 14, 14, 18), surfaces=[self.sheet(12.0)]), self.wanted)

    def test_only_wanted_points_are_explained(self):
        explained = self.explained((0, 0, 0, 39, 39, 30))
        np.testing.assert_array_equal(explained, self.wanted)

    def test_a_finer_grid_is_addressed_by_its_step(self):
        # The same array read as a 0.5 m grid: the block stands at 5..7 m
        self.assertTrue(self.explained((5, 5, 10, 7, 7, 18), step=0.5).all(where=self.wanted))
        self.assertFalse(self.explained((12, 12, 10, 16, 16, 18), step=0.5).any())

    def test_no_boxes_explain_nothing(self):
        self.assertFalse(self.explained().any())


class CollisionBoxes(unittest.TestCase):
    """The server's static mesh placements that collide: a mesh 4 x 2 x 3 m with its pivot at the middle of its floor."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory)
        os.makedirs(os.path.join(self.directory, "bodies"))
        bounds = {"Origin": {"X": 0.0, "Y": 0.0, "Z": 150.0}, "BoxExtent": {"X": 200.0, "Y": 100.0, "Z": 150.0}}
        json.dump({"path": "/Game/M/House.House", "bounds": bounds}, open(os.path.join(self.directory, "bodies", "0.json"), "w"))
        json.dump({"path": "/Game/M/Unread.Unread", "bounds": None}, open(os.path.join(self.directory, "bodies", "1.json"), "w"))
        self.items = []

    def place(self, mesh="0", level="SquadGame/Content/Maps/T/L_Art.umap", collision=None, instances=None, **at):
        self.items.append({"level": level, "type": "StaticMeshComponent", "mesh": mesh, "chain": [link(**at)], "collision": collision, "instances": instances})

    def boxes(self):
        with open(os.path.join(self.directory, "instances.ndjson"), "w") as handle:
            handle.write("\n".join(json.dumps(item) for item in self.items))
        return evidence.collision_boxes(self.directory)

    def test_a_placement_has_the_box_of_its_collision(self):
        self.place(x=100, y=50, z=20)
        # objects.collision_bounds: the render bounds and a tenth of them and 10 cm more on every side
        np.testing.assert_allclose(self.boxes(), [[100 - 2.3, 50 - 1.2, 20 - 0.25, 100 + 2.3, 50 + 1.2, 20 + 3.25]], atol=1e-9)

    def test_placements_without_collision_and_of_skipped_levels_have_none(self):
        self.place(collision={"CollisionProfileName": "NoCollision"})
        self.place(level="SquadGame/Content/Maps/T/Coop/L_Coop.umap")
        self.place(mesh="1")
        self.assertEqual(self.boxes().shape, (0, 6))

    def test_a_spline_mesh_has_the_box_of_its_bent_collision(self):
        # A road segment 10 m long: its body holds the bent collision, a slab 10 x 1 x 0.8 m, and its bounds are the unbent mesh's
        zero = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        slab = {"X": 1000.0, "Y": 100.0, "Z": 80.0, "Center": {"X": 500.0, "Y": 0.0, "Z": 40.0}}
        spline = {"StartPos": zero, "StartTangent": {"X": 1000.0, "Y": 0.0, "Z": 0.0}, "EndPos": {"X": 1000.0, "Y": 0.0, "Z": 0.0}, "EndTangent": {"X": 1000.0, "Y": 0.0, "Z": 0.0}}
        bounds = {"Origin": zero, "BoxExtent": {"X": 500.0, "Y": 50.0, "Z": 40.0}}
        json.dump({"path": "/Game/M/Road.Road", "bounds": bounds, "spline": spline, "body": {"Properties": {"AggGeom": {"BoxElems": [slab]}}}},
                  open(os.path.join(self.directory, "bodies", "s0.json"), "w"))
        json.dump({"path": "/Game/M/Road.Road", "bounds": bounds, "spline": spline, "body": {"Properties": {}}}, open(os.path.join(self.directory, "bodies", "s1.json"), "w"))
        self.place(mesh="s0", x=100, y=50, z=20)
        self.place(mesh="s1", x=300)
        np.testing.assert_allclose(self.boxes(), [[100, 49.5, 20, 110, 50.5, 20.8]], atol=1e-9)

    def test_a_vast_placement_has_no_box(self):
        # A mountain range with collision, 2 km by 1 km: what of it can be read is in the object surface already
        self.place(scale=500.0)
        self.place(x=100)
        self.assertEqual(len(self.boxes()), 1)

    def test_every_instance_has_its_box(self):
        instance = lambda x: {"q": {"X": 0.0, "Y": 0.0, "Z": 0.0, "W": 1.0}, "t": {"X": x * 100, "Y": 0.0, "Z": 0.0}, "s": {"X": 1.0, "Y": 1.0, "Z": 1.0}}
        self.place(instances=[instance(10), instance(30)], x=100)
        np.testing.assert_allclose(self.boxes()[:, 0], [110 - 2.3, 130 - 2.3], atol=1e-9)


class SceneBoxes(unittest.TestCase):
    """The mesh placements a client scene shows: a block 4 x 2 x 3 m with its pivot at a corner of its floor, and a slab that runs along Y."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory)
        os.makedirs(os.path.join(self.directory, "meshes"))
        self.meshes = {"/Game/M/Unread.Unread": {"id": 9, "error": "no such file"}}
        self.block = self.mesh("Block", (0, 0, 0), (400, 200, 300))
        self.slab = self.mesh("Slab", (-200, 0, 0), (200, 1000, 50))
        self.items = []

    def mesh(self, name, lo, hi):
        corners = np.array([[x, y, z, 0, 0, 1, 0, 0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], np.float32)
        mesh = len(self.meshes)
        with open(os.path.join(self.directory, "meshes", f"{mesh}.bin"), "wb") as handle:
            handle.write(corners.tobytes())
            handle.write(np.arange(6, dtype=np.uint32).tobytes())
        self.meshes[f"/Game/M/{name}.{name}"] = {"id": mesh, "vertices": len(corners), "indices": 6, "materials": [], "sections": []}
        return mesh

    def place(self, mesh, level="SquadGame/Content/Maps/T/L_Art.umap", hidden=False, kind="StaticMeshComponent", instances=None, spline=None, **at):
        self.items.append({"level": level, "name": "Component", "type": kind, "owner": "Actor", "mesh": mesh, "hidden": hidden, "cull": [0, 0, 0, 0],
                           "overrides": [], "chain": [link(**at)], "instances": instances, "spline": spline})

    def placements(self):
        json.dump(self.meshes, open(os.path.join(self.directory, "meshes.json"), "w"))
        with open(os.path.join(self.directory, "instances.ndjson"), "w") as handle:
            handle.write("\n".join(json.dumps(item) for item in self.items))
        return evidence.scene_placements(self.directory)

    def boxes(self):
        boxes, surfaces = self.placements()
        self.assertEqual(surfaces, [])
        return boxes

    def test_a_vast_placement_has_its_triangles_and_no_box(self):
        # The block scaled to 1200 x 600 x 900 m is long but not vast; scaled to 2000 x 1000 x 1500 m it is
        self.place(self.block, x=100, scale=300.0)
        self.place(self.block, x=100, y=50, z=20, scale=500.0)
        boxes, surfaces = self.placements()
        np.testing.assert_allclose(boxes, [[100, 0, 0, 1300, 600, 900]], atol=1e-6)
        self.assertEqual([s.shape for s in surfaces], [(2, 3, 3)])
        np.testing.assert_allclose(surfaces[0].reshape(-1, 3).min(0), (100, 50, 20), atol=1e-6)
        np.testing.assert_allclose(surfaces[0].reshape(-1, 3).max(0), (2100, 1050, 1520), atol=1e-6)

    def test_a_placement_has_the_box_of_its_mesh(self):
        self.place(self.block, x=100, y=50, z=20)
        np.testing.assert_allclose(self.boxes(), [[100, 50, 20, 104, 52, 23]], atol=1e-9)

    def test_a_turned_placement_has_the_box_around_the_turned_mesh(self):
        self.place(self.block, x=100, y=50, yaw=90.0, scale=2.0)
        # Yaw turns +X to +Y: the block reaches 8 m south and 4 m west of its pivot, 6 m up
        np.testing.assert_allclose(self.boxes(), [[96, 50, 0, 100, 58, 6]], atol=1e-6)

    def test_what_the_game_does_not_show_has_no_box(self):
        self.place(self.block, hidden=True)
        self.place(self.block, level="SquadGame/Content/Maps/T/L_080_Vista_T.umap")
        self.place(self.block, level="SquadGame/Content/Maps/T/Coop/L_Coop.umap")
        self.place(9)
        self.place(self.block, kind="InstancedStaticMeshComponent", instances=[])
        self.assertEqual(self.boxes().shape, (0, 6))

    def test_every_instance_of_foliage_has_its_box(self):
        half = math.sqrt(0.5)
        instances = [{"q": [0.0, 0.0, 0.0, 1.0], "t": [1000.0, 0.0, 0.0], "s": [1.0, 1.0, 1.0]},
                     {"q": [0.0, 0.0, half, half], "t": [3000.0, 0.0, 500.0], "s": [0.5, 0.5, 2.0]}]
        self.place(self.block, kind="FoliageInstancedStaticMeshComponent", instances=instances, x=100)
        np.testing.assert_allclose(self.boxes(), [[110, 0, 0, 114, 2, 3], [129, 0, 5, 130, 2, 11]], atol=1e-6)

    def test_a_spline_mesh_has_the_box_of_the_mesh_bent_with_its_roll(self):
        east = {"X": 1000.0, "Y": 0.0, "Z": 0.0}
        spline = {"p": {"StartPos": {"X": 0.0, "Y": 0.0, "Z": 0.0}, "StartTangent": east, "StartRoll": -math.pi / 2, "EndPos": east, "EndTangent": east, "EndRoll": -math.pi / 2},
                  "axis": "Y", "up": {"X": 0.0, "Y": 0.0, "Z": 1.0}}
        self.place(self.slab, kind="SplineMeshComponent", spline=spline, x=100, y=50)
        np.testing.assert_allclose(self.boxes(), [[100, 48, 0, 110, 52, 0.5]], atol=1e-6)


if __name__ == "__main__":
    unittest.main()
