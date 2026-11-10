"""Tests of the map's symbology rules (render.py, features.py), the palette's contrast (palette_contrast.py) and the accuracy
measures (measure_accuracy.py): python -m unittest test_cartography (PYTHONPATH with tools/heightmaps/py)."""

import json
import os
import shutil
import tempfile
import unittest

import numpy as np
from scipy import ndimage

import features
import measure_accuracy as ma
import palette_contrast
import render
import scene_prep as sp
from test_scene import BOUNDS, synthetic_map

IDENTITY = {"l": {"X": 0.0, "Y": 0.0, "Z": 100.0}, "r": {"Pitch": 0.0, "Yaw": 0.0, "Roll": 0.0}, "s": {"X": 1.0, "Y": 1.0, "Z": 1.0}}


def loaded_map(test, edit=None, **kwargs):
    """render.load of a synthetic map (test_scene.synthetic_map) after ``edit(prep folder)`` changed its files."""
    directory = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, directory)
    slug = synthetic_map(directory, **kwargs)
    if edit:
        edit(os.path.join(directory, "prep", slug))
    saved = render.PREP_DIR
    render.PREP_DIR = os.path.join(directory, "prep")
    test.addCleanup(setattr, render, "PREP_DIR", saved)
    return render.load(slug)


def hill(base, height=12.0, at=(30, 30), sigma=8.0):
    """Write a round hill of a height into the map's ground files."""
    rows, cols = np.mgrid[:61, :61]
    ground = (height * np.exp(-((rows - at[0]) ** 2 + (cols - at[1]) ** 2) / (2 * sigma ** 2))).astype(np.float32)
    for name in ("ground.npy", "top_ground.npy", "top_ground_base.npy"):
        np.save(os.path.join(base, name), ground)


class WaterPlanes(unittest.TestCase):
    def test_a_water_mesh_bent_along_a_spline_is_no_plane(self):
        # Goose Bay: 346 SM_env_riverfast spline meshes, each 30 x 30 m undeformed, drew its 3 m streams as lakes
        with tempfile.TemporaryDirectory() as directory:
            os.makedirs(os.path.join(directory, "bodies"))
            body = {"path": "/Game/Env/SM_env_riverfast.SM_env_riverfast", "bounds": {"Origin": {"X": 0, "Y": 0, "Z": 0}, "BoxExtent": {"X": 1500, "Y": 1500, "Z": 10}}}
            json.dump(body, open(os.path.join(directory, "bodies", "s1.json"), "w"))
            with open(os.path.join(directory, "instances.ndjson"), "w") as out:
                for kind in ("SplineMeshComponent", "StaticMeshComponent"):
                    out.write(json.dumps({"type": kind, "mesh": "s1", "chain": [IDENTITY], "instances": None}) + "\n")
            planes = features.water_planes(directory)
        self.assertEqual(len(planes), 1)
        self.assertAlmostEqual(planes[0]["z"], 1.1, places=3)


class ObjectClasses(unittest.TestCase):
    def test_a_power_plant_is_no_plant(self):
        for name in ("SM_PowerPlant_Silo_02", "SM_Powerplant_Silo_Base_01a", "SM_PowerPlant_CoollingTower_Base_01", "Metal_hedgehog"):
            self.assertEqual(features.object_class(name), features.STRUCTURE, name)
        self.assertEqual(features.object_class("SM_PowerPlant_Fence_4m_01a"), features.WALL)
        for name in ("SM_PlanterBox_01", "SM_Olivetree_02", "Hedge_01", "SM_Reeds02"):
            self.assertEqual(features.object_class(name), features.VEGETATION, name)

    def test_decks_and_paved_surfaces_are_the_deck_class(self):
        for name in ("SM_EastAsia_Dock_01b", "SM_EastAsia_Prop_Dock_Deck_01", "SM_Pier_Straight", "SM_SubPen_Wharf_01", "bridge_8m_section",
                     "SM_ME_Pavement_Main_1000_00", "SM_Road_edgelineLeft02", "SM_Airfield_Pavement_12x12_1"):
            self.assertEqual(features.object_class(name), features.BRIDGE, name)
        self.assertEqual(features.object_class("SM_EastAsia_Dock_SeaWall_01b"), features.WALL)
        for name in ("SM_PhotoCopier", "SM_EastAsia_Dock_Stairs_01b", "SM_EastAsia_Prop_DockCurb_02", "SM_SubPen_Wharf_01_Piling_01"):
            self.assertEqual(features.object_class(name), features.STRUCTURE, name)


class Summits(unittest.TestCase):
    def test_a_hill_has_one_summit_at_its_top(self):
        rows, cols = np.mgrid[:201, :201]
        ground = (12.0 * np.exp(-((rows - 80) ** 2 + (cols - 120) ** 2) / (2 * 15.0 ** 2))).astype(np.float32)
        found = render.summits(ground, np.zeros(ground.shape, np.uint8), None)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0]["u"], found[0]["v"]), (120.0, 80.0))
        self.assertAlmostEqual(found[0]["h"], 12.0, places=3)

    def test_no_summit_on_a_plain_a_slope_the_sea_or_beyond_the_landscape(self):
        rows, cols = np.mgrid[:201, :201]
        slope = (cols * 0.3).astype(np.float32)
        self.assertEqual(render.summits(slope, np.zeros(slope.shape, np.uint8), None), [])
        ground = (12.0 * np.exp(-((rows - 80) ** 2 + (cols - 120) ** 2) / (2 * 15.0 ** 2))).astype(np.float32)
        self.assertEqual(len(render.summits(ground, np.zeros(ground.shape, np.uint8), 11.0)), 1)
        self.assertEqual(render.summits(ground, np.full(ground.shape, features.NO_COVER, np.uint8), None), [])
        self.assertEqual(render.summits(ground, np.zeros(ground.shape, np.uint8), 12.0), [])

    def test_the_summit_is_drawn_with_its_height_and_the_tiles_do_not_depend_on_the_blocks(self):
        d = loaded_map(self, hill, empty=True)
        self.assertEqual([(s["u"], s["v"], round(s["h"])) for s in d["summits"]], [(30.0, 30.0, 12)])
        frame = render.block_frame(d, 2, 0, 0)
        placed, boxes = render.summits_of(d, frame)
        self.assertEqual([text for _, _, text in placed], ["12"])
        tiles = {}
        for block_tiles in (2, 1):
            saved = render.BLOCK_TILES
            render.BLOCK_TILES = block_tiles
            try:
                d["summit_cache"].clear()
                n = 4 // block_tiles
                rows = [np.concatenate([np.asarray(render.render_block(d, 2, bx, by))[m:-m, m:-m] for bx in range(n)], 1)
                        for by in range(n) for m in [render.block_margin(d, 2)]]
                tiles[block_tiles] = np.concatenate(rows, 0)
            finally:
                render.BLOCK_TILES = saved
        self.assertTrue((tiles[1] == tiles[2]).all())
        x, y = (int(v) for v in placed[0][:2])
        self.assertLess(tiles[2][y, x].astype(int).sum(), 3 * 120)  # the dot is dark

    def test_no_summit_on_a_lake_bed(self):
        def lake(base):
            hill(base)
            json.dump({"planes": [{"polygon": [[0, 0], [60, 0], [60, 60], [0, 60]], "z": 20.0}]}, open(os.path.join(base, "top_water.json"), "w"))
        self.assertEqual(loaded_map(self, lake, empty=True)["summits"], [])


class LabelsOnWater(unittest.TestCase):
    def steep(self, base, lake):
        ground = np.tile(np.linspace(0, 25, 61, dtype=np.float32), (61, 1))
        for name in ("ground.npy", "top_ground.npy", "top_ground_base.npy"):
            np.save(os.path.join(base, name), ground)
        if lake:
            json.dump({"planes": [{"polygon": [[-20, -20], [40, -20], [40, 80], [-20, 80]], "z": 30.0}]}, open(os.path.join(base, "top_water.json"), "w"))

    def labels(self, lake):
        d = loaded_map(self, lambda base: self.steep(base, lake), empty=True)
        frame = render.block_frame(d, 0, 0, 0)
        return [(round((x + frame.gx0) * frame.px_x), text) for x, _, _, text, _ in render.contour_labels(d, frame, *render.contour_intervals(d, frame.px))]

    def test_contour_labels_keep_off_a_lake(self):
        self.assertIn((24, "10"), self.labels(lake=False))
        on_lake = self.labels(lake=True)
        self.assertTrue(on_lake)
        self.assertTrue(all(x > 40 for x, _ in on_lake), on_lake)

    def test_points_under_a_plane_or_the_sea_are_under_water(self):
        d = loaded_map(self, lambda base: self.steep(base, True), empty=True, sea_level=2.0)
        x, y = np.array([BOUNDS["min_x"] + 10.0, BOUNDS["min_x"] + 50.0, BOUNDS["min_x"] + 50.0]), np.full(3, BOUNDS["min_y"] + 30.0)
        self.assertEqual(render.under_water(d, x, y, np.array([4.0, 21.0, 1.0])).tolist(), [True, False, True])


class BeyondTheLandscape(unittest.TestCase):
    def test_no_contours_and_a_quiet_ground_beyond_the_landscape(self):
        def edit(base):
            ground = np.tile(np.linspace(0, 25, 61, dtype=np.float32)[:, None], (1, 61))
            for name in ("ground.npy", "top_ground.npy", "top_ground_base.npy"):
                np.save(os.path.join(base, name), ground)
            cover = np.zeros((61, 61), np.uint8)
            cover[:, 30:] = features.NO_COVER
            np.save(os.path.join(base, "cover.npy"), cover)
        d = loaded_map(self, edit, empty=True)
        self.assertEqual(render.outside_landscape(d, np.array([10.0, 50.0]), np.array([30.0, 30.0])).tolist(), [False, True])
        margin = render.block_margin(d, 0)
        picture = np.asarray(render.render_block(d, 0, 0, 0), np.float32)[margin:-margin, margin:-margin]
        inside, outside = picture[20:236, 20:100] @ render.LUMA, picture[20:236, 156:236] @ render.LUMA
        self.assertGreater(inside.std(), 6.0)   # contour lines every metre
        self.assertLess(outside.std(), 1.5)
        frame = render.block_frame(d, 0, 0, 0)
        labels = render.contour_labels(d, frame, *render.contour_intervals(d, frame.px))
        self.assertTrue(all((x + frame.gx0) * frame.px_x < 30 for x, *_ in labels))


class WaterDepthAndShore(unittest.TestCase):
    def water(self, depths):
        d = {"planes": [{"polygon": [[0, 0], [60, 0], [60, 60], [0, 60]], "z": 10.0, "box": (0, 0, 60, 60)}], "sea": None, "fields": {},
             "water_top": np.full((61, 61), sp.NO_WATER_SURFACE, np.float32), "min_x": 0.0, "min_y": 0.0, "size_x": 60.0, "size_y": 60.0}
        frame = render.Frame(d, 1, 0, 0, 512, 512)
        h = np.tile(10.0 - np.interp(np.arange(512), [0, 511], depths).astype(np.float32), (512, 1))
        rgb = np.full((512, 512, 3), 200.0, np.float32)
        return render.draw_water(d, frame, h, rgb), rgb

    def test_a_ford_and_a_channel_differ_in_colour(self):
        _, rgb = self.water((0.5, 3.0))
        self.assertGreater(np.abs(rgb[256, 10] - rgb[256, 500]).sum(), 30.0)  # the linear ramp over 12 m: 25
        _, rgb = self.water((12.0, 40.0))
        np.testing.assert_allclose(rgb[256, 10], render.WATER_DEEP_RGB, atol=1.0)
        np.testing.assert_allclose(rgb[256, 500], render.WATER_DEEP_RGB, atol=1.0)

    def test_the_shore_is_a_dark_line_whatever_the_width_of_the_edge(self):
        water, rgb = self.water((-2.0, 2.0))
        row = rgb[256] @ render.LUMA
        shore = int(np.argmin(np.abs(water[256] - 0.5)))
        self.assertLess(row[shore], row[shore + 12] - 12)   # darker than the water beside it
        self.assertLess(row[shore], row[shore - 12] - 12)   # and than the land
        self.assertLess(np.count_nonzero(render.shore_line(water)[256] > 0.5), 4)


class RiverMeshes(unittest.TestCase):
    def river(self, base):
        # ground falling to a bed along column 30; the river mesh's top is 1 m over the bed, 10 m wide
        ground = np.tile(np.abs(np.arange(61, dtype=np.float32) - 30) * 0.5, (61, 1))
        for name in ("ground.npy", "top_ground.npy", "top_ground_base.npy"):
            np.save(os.path.join(base, name), ground)
        top = np.full((61, 61), -np.inf, np.float32)
        top[:, 25:36] = 1.0
        np.save(os.path.join(base, "top_water_surface.npy"), sp.river_surface(top, 0.0))

    def test_water_lies_where_the_ground_is_below_the_river_mesh(self):
        d = loaded_map(self, self.river, empty=True)
        for z, tolerance in ((0, 0.6), (2, 0.2)):
            frame = render.block_frame(d, z, 0, 0)
            h = render.sample_grid(d["ground"], frame.u, frame.v, frame.px, 3, separable=True).astype(np.float32)
            water = render.draw_water(d, frame, h, np.zeros(h.shape + (3,), np.float32))
            row = water[frame.height // 2]
            wet = frame.u[row > 0.5]
            self.assertAlmostEqual(wet.min(), 28.0, delta=tolerance)   # the bed is under 1 m from 28 to 32 m
            self.assertAlmostEqual(wet.max(), 32.0, delta=tolerance)
        self.assertEqual(render.under_water(d, np.array([30.0, 26.0, 50.0]), np.full(3, 30.0), np.array([0.0, 2.0, 0.5])).tolist(), [True, False, False])

    def test_a_stream_on_open_ground_keeps_its_width(self):
        # no bank rises above the mesh: its own edge is the shore, and smoothing the shore must not eat a 3 m stream
        def stream(base):
            top = np.full((61, 61), -np.inf, np.float32)
            top[:, 29:32] = 0.2
            np.save(os.path.join(base, "top_water_surface.npy"), sp.river_surface(top, 0.0))
        d = loaded_map(self, stream, empty=True)
        frame = render.block_frame(d, 2, 0, 0)
        water = render.draw_water(d, frame, np.zeros((frame.height, frame.width), np.float32), np.zeros((frame.height, frame.width, 3), np.float32))
        wet = frame.u[water[frame.height // 2] > 0.5]
        self.assertAlmostEqual(wet.max() - wet.min(), 3.0, delta=0.4)

    def test_the_surface_is_the_meshes_top_above_the_lowest_point(self):
        top = np.array([[105.0, -np.inf]], np.float32)
        np.testing.assert_array_equal(sp.river_surface(top, 100.0), np.array([[5.0, sp.NO_WATER_SURFACE]], np.float32))


class RoadsAndRails(unittest.TestCase):
    def frame(self):
        d = {"min_x": 0.0, "min_y": 0.0, "size_x": 128.0, "size_y": 128.0, "fields": {}}
        return d, render.Frame(d, 1, 0, 0, 512, 512)

    def line(self, cls, half):
        xs = np.linspace(0, 128, 9)
        line = {"cls": cls, "left": np.stack([xs, np.full(9, 64.0 - half)], 1), "right": np.stack([xs, np.full(9, 64.0 + half)], 1),
                "center": np.stack([xs, np.full(9, 64.0), np.zeros(9)], 1)}
        line["box"] = (0.0, 64.0 - half, 128.0, 64.0 + half)
        return line

    def test_a_dirt_road_has_a_casing_darker_than_the_road_and_the_grass(self):
        d, frame = self.frame()
        d["lines"] = [self.line("dirt", 2.0)]
        grass = np.array(render.COVER_RGB["PhysMat_Grass"], np.float32)
        rgb = np.tile(grass, (512, 512, 1))
        render.draw_splines(d, frame, rgb, np.zeros((512, 512), np.float32))
        column = rgb[:, 256] @ render.LUMA
        road, ground = column[256], column[100]
        self.assertLess(column[240:249].min(), min(road, ground) - 12)

    def test_a_railway_has_cross_ties(self):
        d, frame = self.frame()
        lines = [self.line("rail", 0.8)]
        ties = render.rail_ties(frame, lines, frame.world_box(8), render.SPLINE_STYLE["rail"][2])
        beside = ties[int((64 - 2.0) / frame.px)] > 0.5   # 2 m from the centre line: beyond the track, inside the ties
        _, count = ndimage.label(beside)
        self.assertEqual(count, 32)   # a tie every 4 m of 128 m
        self.assertFalse((ties[int((64 - 4.0) / frame.px)] > 0).any())


class PavedSurfaces(unittest.TestCase):
    def test_a_pavement_on_the_ground_is_flat_and_a_deck_has_a_rim(self):
        def scene(height_cm):
            def edit(base):
                for k in range(8):
                    shape = np.load(os.path.join(base, f"top_h{k}.npy")).shape
                    h, c, v = np.zeros(shape, np.uint16), np.zeros(shape, np.uint8), np.zeros(shape, np.uint8)
                    lo, hi = shape[0] // 4, 3 * shape[0] // 4
                    h[lo:hi, lo:hi], c[lo:hi, lo:hi], v[lo:hi, lo:hi] = height_cm, features.BRIDGE, 255
                    for name, array in (("h", h), ("c", c), ("v", v)):
                        np.save(os.path.join(base, f"top_{name}{k}.npy"), array)
            d = loaded_map(self, edit, empty=True)
            margin = render.block_margin(d, 0)
            return np.asarray(render.render_block(d, 0, 0, 0), np.float32)[margin:-margin, margin:-margin] @ render.LUMA
        paved, deck = scene(40), scene(400)
        edge = slice(60, 68)   # the object's edge is at pixel 64 of 256
        ground = float(paved[128, 20])   # flat ground at height 0 lies on a contour level: the contour colour, luma 118
        self.assertGreater(paved[128, edge].min(), ground - 3)
        self.assertLess(deck[128, edge].min(), ground - 30)
        self.assertAlmostEqual(float(paved[128, 128]), float(np.dot(render.SPLINE_STYLE["pavement"][0], render.LUMA)), delta=3)


class Palette(unittest.TestCase):
    def test_the_structure_ramp_is_one_hue_in_falling_lightness(self):
        colours = palette_contrast.lab(np.array([c for _, c in render.STRUCTURE_RAMP], np.float64))
        self.assertTrue((np.diff(colours[:, 0]) < -7).all(), colours[:, 0])
        hue = np.degrees(np.arctan2(colours[:, 2], colours[:, 1])) % 360
        self.assertTrue(((hue > 270) & (hue < 300)).all(), hue)

    def test_classes_that_meet_are_distinct_under_every_colour_vision(self):
        report = palette_contrast.report()
        for pair in ("building 5 m | conifer", "building 5 m | deciduous", "building 5 m | rock", "building 5 m | shadow", "wall | conifer",
                     "dirt road | contour major", "rock | asphalt road"):
            _, lowest = palette_contrast.lowest(report["pairs"][pair])
            self.assertGreaterEqual(min(lowest[kind] for kind in palette_contrast.MACHADO), palette_contrast.DISTINCT, (pair, lowest))
        for name in ("building 2 m", "building outline", "wall", "water shallow", "water deep", "contour major", "rail", "trench"):
            _, lowest = palette_contrast.lowest(report["vs_ground"][name])
            self.assertGreaterEqual(min(lowest[kind] for kind in palette_contrast.MACHADO), palette_contrast.DISTINCT, (name, lowest))
        # a dirt road's fill is the ground's hue for a red-green deficiency: its casing carries it on every ground but its own
        for ground, value in report["vs_ground"]["dirt road casing"].items():
            if ground not in ("dirt", "mud"):
                self.assertGreaterEqual(min(value[kind] for kind in palette_contrast.MACHADO), palette_contrast.DISTINCT, ground)
        self.assertTrue(all(ratio >= 4.5 for ratio in report["labels"].values()), report["labels"])

    def test_colour_difference_and_deficiency_against_published_values(self):
        # Sharma, Wu & Dalal (2005), table 1, pair 1: Lab (50, 2.6772, -79.7751) and (50, 0, -82.7485) differ by 2.0425
        def lab_to_rgb(l, a, b):
            fy = (l + 16) / 116
            f = np.array([fy + a / 500, fy, fy - b / 200])
            xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) * 27 / 24389) * np.array([0.95047, 1.0, 1.08883])
            m = np.linalg.inv(np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]))
            linear = m @ xyz
            return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.abs(linear) ** (1 / 2.4) - 0.055) * 255
        self.assertAlmostEqual(palette_contrast.delta_e2000(lab_to_rgb(50, 2.6772, -79.7751), lab_to_rgb(50, 0, -82.7485)), 2.0425, places=2)
        # a red and a green of one luminance are one colour to a deuteranope, a blue and a yellow are not
        red, green = np.array([200.0, 80.0, 60.0]), np.array([110.0, 130.0, 50.0])
        self.assertLess(palette_contrast.delta_e2000(palette_contrast.simulate(red, "deuteranopia"), palette_contrast.simulate(green, "deuteranopia")),
                        0.5 * palette_contrast.delta_e2000(red, green))
        self.assertAlmostEqual(palette_contrast.wcag_contrast((0, 0, 0), (255, 255, 255)), 21.0, places=2)


class Legend(unittest.TestCase):
    def test_the_legend_carries_the_palette_that_is_drawn(self):
        entries = {e["key"]: e for e in render.legend()}
        self.assertEqual(len(entries), len(render.legend()))
        self.assertEqual(entries["building_tall"]["rgb"], list(dict(render.STRUCTURE_RAMP)[20.0]))
        self.assertEqual(entries["road_dirt"]["outline"], list(render.SPLINE_STYLE["dirt"][1]))
        self.assertEqual(entries["water_deep"]["rgb"], [int(c) for c in render.WATER_DEEP_RGB])
        self.assertNotIn("outline", entries["contour"])
        self.assertTrue(all(e["kind"] in ("area", "line", "point") and len(e["rgb"]) == 3 for e in entries.values()))
        json.dumps(render.legend())


class AccuracyMeasures(unittest.TestCase):
    def test_bootstrap_interval_holds_the_median(self):
        values = np.random.default_rng(1).normal(5.0, 1.0, 400)
        low, high = ma.bootstrap_ci(values)
        self.assertLess(low, 5.0)
        self.assertGreater(high, 5.0)
        self.assertLess(high - low, 0.5)
        self.assertIsNone(ma.bootstrap_ci([1.0, 2.0]))

    def road(self, cls="asphalt"):
        xs = np.arange(0.0, 201.0, 10.0)
        return {"cls": cls, "center": np.stack([xs, np.zeros(len(xs)), np.zeros(len(xs))], 1).tolist(),
                "left": np.stack([xs, np.full(len(xs), -3.0)], 1).tolist(), "right": np.stack([xs, np.full(len(xs), 3.0)], 1).tolist()}

    def test_stations_lie_on_straight_lone_roads(self):
        stations = ma.road_stations([self.road()])
        self.assertEqual(len(stations), 10)
        cls, x, y, tx, ty, half = stations[0]
        self.assertEqual((cls, y, round(tx, 6), round(ty, 6), half), ("asphalt", 0.0, 1.0, 0.0, 3.0))
        crossing = self.road()
        crossing["center"] = [[100.0, y, 0.0] for y in np.arange(-100.0, 101.0, 10.0)]
        near = [s[1] for s in ma.road_stations([self.road(), crossing]) if s[2] == 0.0]
        self.assertTrue(near and all(abs(x - 100.0) > 3.0 + ma.ROAD_CLEAR_M - 1.0 for x in near), near)
        self.assertEqual(ma.road_stations([self.road("wall")]), [])

    def profile(self, centre, half, road=(120.0, 120.0, 120.0), ground=(90.0, 140.0, 70.0)):
        across = np.arange(-9.0, 9.0 + ma.PROFILE_STEP_M / 2, ma.PROFILE_STEP_M)
        inside = ndimage.gaussian_filter1d((np.abs(across - centre) < half).astype(np.float64), 2.0)
        return inside[:, None] * np.array(road) + (1 - inside[:, None]) * np.array(ground), across

    def test_profile_shift_and_width(self):
        ours, across = self.profile(0.35, 3.0)
        theirs, _ = self.profile(0.0, 3.0)
        shift, peak = ma.profile_shift(ours, theirs)
        self.assertAlmostEqual(shift, 0.35, delta=0.02)
        self.assertGreater(peak, 0.9)
        self.assertAlmostEqual(ma.profile_width(theirs, across, 3.0), 6.0, delta=0.06)
        self.assertAlmostEqual(ma.profile_width(self.profile(0.0, 2.5)[0], across, 3.0), 5.0, delta=0.06)
        self.assertIsNone(ma.profile_width(self.profile(0.0, 3.0, road=(92.0, 141.0, 71.0))[0], across, 3.0))

    def test_water_against_a_reference_of_other_colours(self):
        rng = np.random.default_rng(0)
        ours = np.zeros((200, 200), bool)
        ours[50:150, 40:140] = True
        truth = np.roll(ours, 4, axis=1)
        hd = np.where(truth[..., None], (20, 60, 70), (120, 110, 60)).astype(np.uint8) + rng.integers(0, 3, (200, 200, 3)).astype(np.uint8)
        valid = np.ones((200, 200), bool)
        lookup = ma.hd_water_lookup(hd, ours, valid)
        theirs = lookup[ma.colour_bins(hd)]
        self.assertTrue((theirs == truth).all())
        report = ma.water_agreement(ours, theirs, valid, 2.0)
        self.assertAlmostEqual(report["iou"], 96 / 104, places=3)
        self.assertEqual(report["shore_distance_m"]["p90_abs"], 8.0)
        colours = np.zeros((2, 2, 3), np.uint8) + np.array(render.WATER_RGB, np.uint8)
        colours[0, 0] = render.COVER_RGB["PhysMat_Grass"]
        self.assertEqual(ma.tile_water(colours).tolist(), [[False, True], [True, True]])

    def test_roof_heights_against_the_heightmap(self):
        ground = np.zeros((100, 100))
        heightmap = ground.copy()
        heightmap[20:30, 20:40] = 6.0
        heightmap[60:70, 20:40] = 9.0
        heightmap[60:70, 39:60] = 3.0   # a second roof joined to it
        bounds = {"min_x": 0.0, "min_y": 0.0}
        labels = [{"x": 30.5, "y": 25.5, "h": 6.2, "depth": 4.0}, {"x": 30.5, "y": 65.5, "h": 9.0, "depth": 4.0}, {"x": 50.5, "y": 65.5, "h": 3.0, "depth": 4.0},
                  {"x": 80.5, "y": 80.5, "h": 5.0, "depth": 4.0}, {"x": 22.5, "y": 22.5, "h": 6.0, "depth": 1.0}]
        self.assertEqual(ma.roof_height_pairs(labels, heightmap, ground, bounds), [(6.2, 6.0)])

    def test_contour_pixels_and_their_interval(self):
        grass = np.array(render.COVER_RGB["PhysMat_Grass"], np.float32)
        picture = np.tile(grass, (128, 128, 1))
        picture[:, 40] = grass * 0.3 + np.asarray(render.CONTOUR_RGB) * 0.7
        picture[:, 90] = 30.0   # a dark wall is no contour
        found = ma.contour_pixels(picture.astype(np.uint8))
        self.assertTrue(found[20:100, 40].all())
        self.assertFalse(found[:, 90].any())
        self.assertEqual(int(found.sum()), int(found[:, 40].sum()))
        rng = np.random.default_rng(0)
        slopes = rng.uniform(0.05, 0.5, 5000)
        heights = rng.integers(1, 40, 5000) * 5.0 + rng.normal(0, 0.02, 5000)
        fit = ma.contour_fit(heights, slopes, 0.25)
        self.assertEqual(fit["interval_m"], 5)
        self.assertLess(fit["distance_m"]["median"], 0.2)
        self.assertNotEqual(ma.contour_fit(rng.uniform(0, 200, 5000), slopes, 0.25)["random_ratio"] < 0.5, True)

    def test_crown_centroid(self):
        n = 100   # a window of 10 m
        rows, cols = np.mgrid[:n, :n]
        picture = np.where(np.hypot(cols + 0.5 - 56, rows + 0.5 - 50) <= 20, 60.0, 0.0)   # a crown of 2 m radius, 0.6 m east of the pivot
        dx, dy, share = ma.crown_centroid(picture, 3.0)
        self.assertAlmostEqual(dx, 0.6, delta=0.02)
        self.assertAlmostEqual(dy, 0.0, delta=0.02)
        self.assertAlmostEqual(share, (2 / 3) ** 2, delta=0.02)
        self.assertIsNone(ma.crown_centroid(np.zeros((n, n)), 3.0))


if __name__ == "__main__":
    unittest.main()
