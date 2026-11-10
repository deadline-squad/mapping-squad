"""Tests of the map render: python -m unittest test_maprender (the venv of maprender.sh).

Everything that decides a colour or what is drawn is tested on small arrays and small scenes written to a temporary folder. The class
RealSceneTest renders a scene of the game client on the GPU and needs MAPRENDER_SCENE=<slug> with its texture name in MAPRENDER_TEXTURE.
"""
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy import ndimage

import ground_fit
import registration
import render_map
import scene_render


class ColourTexturePathTest(unittest.TestCase):
    def test_known_names_come_first(self):
        names = {"PM_Diffuse": "/a/T_Mask.T_Mask", "Base_Diffuse": "/a/T_Wall_A.T_Wall_A"}
        self.assertEqual(scene_render.colour_texture_path(names), "/a/T_Wall_A.T_Wall_A")

    def test_a_mask_behind_a_colour_name_is_no_colour(self):
        names = {"Base_Color": "/a/T_Tent_m.T_Tent_m", "Normal": "/a/T_Tent_n.T_Tent_n"}
        self.assertIsNone(scene_render.colour_texture_path(names))

    def test_names_of_the_assets_with_their_spelling(self):
        for parameter in ("Colormap Albido", "DetailAlbido", "Layer01_difuse", "Dif", "Grass_A", "Main_A"):
            with self.subTest(parameter):
                names = {parameter: "/a/Something.Something", "PM_Normals": "/a/N.N", "Roughness": "/a/R.R"}
                self.assertEqual(scene_render.colour_texture_path(names), "/a/Something.Something")

    def test_a_texture_named_like_a_colour(self):
        names = {"MaterialExpressionTextureSampleParameter2D_0": "/a/T_Wood_planks_A.T_Wood_planks_A"}
        self.assertEqual(scene_render.colour_texture_path(names), "/a/T_Wood_planks_A.T_Wood_planks_A")

    def test_only_technical_textures_mean_no_colour(self):
        names = {"PM_Normals": "/a/bag_normals.bag_normals", "Reflection": "/a/T_perlin_roughness.T_perlin_roughness", "BlendMap": "/a/rock_blend.rock_blend"}
        self.assertIsNone(scene_render.colour_texture_path(names))


class CrownDomeTest(unittest.TestCase):
    LO, HI = np.array([-300.0, -200.0, 0.0]), np.array([300.0, 200.0, 1000.0])

    def test_indices_are_valid_and_triangles_complete(self):
        vertices, indices = scene_render.crown_dome(self.LO, self.HI, 3)
        self.assertEqual(vertices.shape[1], 8)
        self.assertEqual(len(indices) % 3, 0)
        self.assertLess(indices.max(), len(vertices))

    def test_stays_about_the_size_of_the_tree(self):
        vertices, _ = scene_render.crown_dome(self.LO, self.HI, 3)
        self.assertLessEqual(vertices[:, 0].max(), 300.0 * 1.25)
        self.assertGreaterEqual(vertices[:, 1].min(), -200.0 * 1.25)
        self.assertAlmostEqual(float(vertices[:, 2].max()), 1000.0, delta=1.0)
        self.assertGreater(vertices[:, 2].min(), 0.0)

    def test_the_same_seed_gives_the_same_shape_and_another_seed_another(self):
        first, _ = scene_render.crown_dome(self.LO, self.HI, 3)
        again, _ = scene_render.crown_dome(self.LO, self.HI, 3)
        other, _ = scene_render.crown_dome(self.LO, self.HI, 4)
        np.testing.assert_array_equal(first, again)
        self.assertFalse(np.array_equal(first, other))


class FitLayerColoursTest(unittest.TestCase):
    def setUp(self):
        self.weights = np.zeros((2, 200, 200), np.uint8)
        self.weights[0, :, :100] = 255
        self.weights[1, :, 100:] = 255
        self.reference = np.zeros((200, 200, 3))
        self.reference[:, :100] = (200, 180, 120)
        self.reference[:, 100:] = (60, 90, 40)

    def test_recovers_the_colour_of_each_layer(self):
        colours = ground_fit.fit_layer_colours(self.weights, self.reference)
        np.testing.assert_allclose(colours, [(200, 180, 120), (60, 90, 40)], atol=2.0)

    def test_cells_outside_the_mask_do_not_count(self):
        # Forest over most of the first layer: without the mask its colour is that of the forest
        dark = self.reference.copy()
        dark[:150, :100] = (20, 25, 15)
        mask = np.ones((200, 200), bool)
        mask[:150, :100] = False
        np.testing.assert_allclose(ground_fit.fit_layer_colours(self.weights, dark, mask)[0], (200, 180, 120), atol=3.0)
        self.assertLess(ground_fit.fit_layer_colours(self.weights, dark)[0, 0], 100)

    def test_a_layer_on_a_few_cells_keeps_to_the_median_colour(self):
        weights = np.zeros((2, 200, 200), np.uint8)
        weights[0] = 255
        weights[0, :3, :3] = 0
        weights[1, :3, :3] = 255
        reference = np.full((200, 200, 3), (150.0, 130.0, 100.0))
        reference[:3, :3] = (0, 0, 255)
        colours = ground_fit.fit_layer_colours(weights, reference)
        self.assertGreater(colours[1, 0], 90)
        self.assertLess(colours[1, 2], 170)


class LeafColourTest(unittest.TestCase):
    def test_darkest_pixels_show_the_leaves_not_the_sand(self):
        leaves, sand = np.full((25, 3), (40.0, 50.0, 30.0)), np.full((75, 3), (200.0, 170.0, 120.0))
        np.testing.assert_allclose(ground_fit.darkest_mean(np.vstack([sand, leaves]), 0.25), (40, 50, 30))


class Bc1Test(unittest.TestCase):
    def test_a_block_with_its_two_end_colours(self):
        white, black = 0xFFFF, 0x0000
        # Colour 0 in the top row, colour 1 in the second, the 2:1 and 1:2 mixes below
        indices = 0b00000000 | (0b01010101 << 8) | (0b10101010 << 16) | (0b11111111 << 24)
        raw = white.to_bytes(2, "little") + black.to_bytes(2, "little") + indices.to_bytes(4, "little")
        image = render_map.decode_bc1(raw, 4, 4)
        self.assertEqual(image[0, 0].tolist(), [255, 255, 255])
        self.assertEqual(image[1, 3].tolist(), [0, 0, 0])
        self.assertEqual(image[2, 0].tolist(), [170, 170, 170])
        self.assertEqual(image[3, 0].tolist(), [85, 85, 85])


class SquareTextureTest(unittest.TestCase):
    def test_a_square_frame_keeps_the_texture(self):
        texture = np.zeros((64, 64, 3), np.uint8)
        self.assertIs(render_map.square_texture(texture, {"w": 100.0, "h": 100.0}), texture)

    def test_a_rectangular_frame_fills_the_square_from_its_origin(self):
        texture = np.zeros((64, 64, 3), np.uint8)
        texture[:, 32:] = 200
        square = render_map.square_texture(texture, {"w": 50.0, "h": 100.0})
        self.assertEqual(square.shape, (64, 64, 3))
        # The texture now spans the first half of the columns, and its edge repeats beyond it
        self.assertEqual(square[10, 5, 0], 0)
        self.assertEqual(square[10, 25, 0], 200)
        self.assertEqual(square[10, 60, 0], 200)


class FinestZoomTest(unittest.TestCase):
    def test_first_zoom_at_or_below_a_third_of_a_metre(self):
        self.assertEqual(render_map.finest_zoom(2755.0), 6)
        self.assertEqual(render_map.finest_zoom(4000.0), 6)
        self.assertEqual(render_map.finest_zoom(5500.0), 7)
        self.assertEqual(render_map.finest_zoom(80.0), 0)


class ToneTest(unittest.TestCase):
    FRAME = {"x": 0.0, "y": 0.0, "w": 100.0, "h": 100.0}

    def test_each_pixel_takes_the_field_at_its_place(self):
        field = np.ones((101, 101, 3), np.float32)
        field[:, 51:] = 1.5
        image = np.full((10, 10, 3), 100, np.uint8)
        left = render_map.apply_tone(image, field, 10.0, 10.0, (1.0, 1.0), self.FRAME, 1.0)
        right = render_map.apply_tone(image, field, 80.0, 10.0, (1.0, 1.0), self.FRAME, 1.0)
        self.assertEqual(left[5, 5].tolist(), [100, 100, 100])
        self.assertEqual(right[5, 5].tolist(), [150, 150, 150])

    def test_a_light_roof_is_not_burnt_out(self):
        field = np.full((101, 101, 3), 1.8, np.float32)
        image = np.full((4, 4, 3), 225, np.uint8)
        self.assertEqual(render_map.apply_tone(image, field, 10.0, 10.0, (1.0, 1.0), self.FRAME, 1.0)[0, 0].tolist(), [225, 225, 225])


class LoadWeightsTest(unittest.TestCase):
    """Layer weights of landscape components on the map's grid, from a small scene written to a temporary folder."""

    def scene_with_component(self, directory, relative, section_base, level="L_Landscape", named_channel=0):
        """A scene folder with a 2 x 2 quad component at the world origin in `level`: layer "Sand" at weight 200 in the first channel
        of its weightmap, named as `named_channel` in the component's layer list."""
        folder = os.path.join(directory, "landscape", level, "wm")
        os.makedirs(folder)
        pixels = np.zeros((4, 4, 4), np.uint8)
        pixels[..., 2] = 200
        Path(folder, "Texture2D_0.bin").write_bytes(pixels.tobytes())
        component = {"location": [0.0, 0.0, 0.0], "scale": [100.0, 100.0, 100.0], "yaw": 0.0, "relative": relative,
                     "sectionBaseX": section_base[0], "sectionBaseY": section_base[1], "componentSizeQuads": 2, "subsectionSizeQuads": 1,
                     "numSubsections": 2, "weightmapTextures": ["Texture2D_0"], "layers": [{"layer": "Sand", "texture": 0, "channel": named_channel}]}
        Path(directory, "landscape", level, "components.json").write_text(json.dumps([component]))
        scene = scene_render.Scene.__new__(scene_render.Scene)
        scene.directory = directory
        return scene

    def test_the_first_component_of_a_streaming_proxy_stays_at_the_proxy(self):
        # Fallujah: the origin component of a proxy has the relative position (0, 0) and a section base counted from the whole landscape
        with tempfile.TemporaryDirectory() as directory:
            scene = self.scene_with_component(directory, [0.0, 0.0], (1530, 2040))
            names, weights = scene.load_weights(0.0, 0.0, 1.0, 4)
        self.assertEqual(names[0], "Sand")
        self.assertEqual(int(weights[0, 1, 1]), 200)

    def test_a_component_is_placed_by_its_relative_position(self):
        with tempfile.TemporaryDirectory() as directory:
            scene = self.scene_with_component(directory, [2.0, 0.0], (2, 0))
            names, weights = scene.load_weights(0.0, 0.0, 1.0, 4)
        self.assertEqual(int(weights[0, 0, 3]), 200)
        self.assertEqual(int(weights[0, 0, 0]), 0)

    def test_cells_past_the_landscape_get_the_uncovered_layer(self):
        # Sanxian: the map frame reaches past the landscape; without a layer those cells render black
        with tempfile.TemporaryDirectory() as directory:
            scene = self.scene_with_component(directory, [0.0, 0.0], (0, 0))
            names, weights = scene.load_weights(0.0, 0.0, 1.0, 5)
        self.assertEqual(names, ["Sand", scene_render.UNCOVERED_LAYER])
        self.assertEqual(weights[:, 1, 1].tolist(), [200, 0])
        self.assertEqual(weights[:, 4, 4].tolist(), [0, 255])

    def test_no_uncovered_layer_when_the_landscape_covers_the_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            scene = self.scene_with_component(directory, [0.0, 0.0], (0, 0))
            names, weights = scene.load_weights(0.0, 0.0, 1.0, 3)
        self.assertEqual(names, ["Sand"])
        self.assertEqual(int(weights.min()), 200)

    def test_a_repeated_component_with_empty_weights_keeps_the_painted_one(self):
        # Yehorivka: the World Partition proxies repeat the landscape actor's components, and some name a channel that holds nothing
        with tempfile.TemporaryDirectory() as directory:
            scene = self.scene_with_component(directory, [0.0, 0.0], (0, 0), level="L_Landscape")
            self.scene_with_component(directory, [0.0, 0.0], (0, 0), level="L_Landscape_WP", named_channel=1)
            names, weights = scene.load_weights(0.0, 0.0, 1.0, 3)
        self.assertEqual(names, ["Sand"])
        self.assertEqual(int(weights.min()), 200)


class FoliageNamesTest(unittest.TestCase):
    def test_what_counts_as_leaves(self):
        scene = scene_render.Scene.__new__(scene_render.Scene)
        scene.materials = {
            "/a/MI_Tamarix_B.MI_Tamarix_B": {"blend": "BLEND_Opaque", "shading": "MSM_Unlit"},
            "/a/MI_Oak.MI_Oak": {"blend": "BLEND_Opaque", "shading": "MSM_TwoSidedFoliage"},
            "/a/MI_SalixPurpurea_Trunk.MI_SalixPurpurea_Trunk": {"blend": "BLEND_Opaque", "shading": "MSM_TwoSidedFoliage"},
            "/a/MI_European_Rock.MI_European_Rock": {"blend": "BLEND_Opaque", "shading": "MSM_Subsurface"},
            "/a/mat_brick.mat_brick": {"blend": "BLEND_Opaque", "shading": "MSM_Unlit"},
            "/a/MI_Frond.MI_Frond": {"blend": "BLEND_Masked", "shading": "MSM_Subsurface"},
        }
        leaves = {path.rsplit(".", 1)[-1] for path in scene.materials if scene.is_leaf_material(path)}
        self.assertEqual(leaves, {"MI_Tamarix_B", "MI_Oak"})

    def test_crops_palms_and_trees_under_snow_are_no_crowns(self):
        for name in ("M_Corn_Tall_Unified", "SM_EastAsia_Rice_Growing", "MI_Poppies_white_unified", "MI_plaingrass", "MI_Palm_Frond", "MI_ScotsPine_snowy"):
            self.assertTrue(scene_render.KEEPS_ITS_SHAPE.search(name), name)
        for name in ("MI_Tamarix", "MI_NorwaySpruce_Needles", "MI_Lombardy_poplarleaf_01"):
            self.assertFalse(scene_render.KEEPS_ITS_SHAPE.search(name), name)

    def test_developer_volumes_are_not_drawn_but_blockout_art_is(self):
        scene = scene_render.Scene.__new__(scene_render.Scene)
        scene.materials = {}
        scene.white = "white"
        for path in ("/Game/Environments/MaterialInstances/Blockout/MI_Sunburst_Yellow_Transparent.MI_Sunburst_Yellow_Transparent",
                     "/Game/Environments/MaterialInstances/Blockout/MI_Transparent_red.MI_Transparent_red",
                     "/Game/Gameplay/GameModes/TC/HexGrid/TransparentWhite.TransparentWhite",
                     "/Game/Environments/Tools/POI_Reference_Marker/M_POI_Reference_Grey.M_POI_Reference_Grey",
                     "/Game/Gameplay/GameplayBorder/M_MapBorder.M_MapBorder",
                     "/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial",
                     "/Engine/EngineMaterials/WorldGridMaterial.WorldGridMaterial"):
            self.assertTrue(scene.material_state(path)[3], path)
        for path in ("/Game/Environments/MaterialInstances/Blockout/MI_Metal_3.MI_Metal_3",
                     "/Game/Environments/MaterialInstances/Blockout/Military_Paint_Green_Pattern_01.Military_Paint_Green_Pattern_01",
                     "/Game/Environments/MaterialInstances/Fallujah/MI_ME_Ceiling_01.MI_ME_Ceiling_01"):
            self.assertFalse(scene_render.DEVELOPER_MATERIAL.search(path), path)


class FlatRender:
    """Stands in for Scene in tone_field and open_ground: a uniform render and a given material raster."""

    def __init__(self, colour, materials=None, paths=None):
        self.colour, self.materials_raster, self.paths = colour, materials, paths or {}

    def render(self, x0, y0, x1, y1, width, height, ssaa=2):
        return np.full((height, width, 3), self.colour, np.uint8)

    def render_ids(self, x0, y0, x1, y1, width, height, ids):
        ids.update(self.paths)
        i0, j0 = int(round(x0)), int(round(y0))
        return self.materials_raster[j0:j0 + height, i0:i0 + width]


class RegistrationTest(unittest.TestCase):
    STEP = 1.0

    def picture(self):
        """Rectangles in a 1000 px image: edges in every patch."""
        rng = np.random.default_rng(5)
        image = np.full((1000, 1000, 3), 120, np.uint8)
        for _ in range(900):
            x, y = rng.integers(0, 980, 2)
            image[y:y + rng.integers(4, 18), x:x + rng.integers(4, 18)] = rng.integers(0, 255)
        return image

    def warp_of(self, rendered, texture):
        return registration.fit_warp(registration.patch_shifts(rendered, texture, self.STEP), self.STEP)

    def test_a_texture_on_the_render_is_not_warped(self):
        image = self.picture()
        self.assertIsNone(self.warp_of(image, image))

    def test_a_shift_is_measured_and_undone(self):
        rendered = self.picture()
        # The texture holds everything 7 px to the left and 4 px lower than the render
        texture = np.roll(rendered, (4, -7), (0, 1))
        warp = self.warp_of(rendered, texture)
        np.testing.assert_allclose(warp, (-7, 0, 4, 0), atol=0.3)
        back = registration.warp_texture(texture, warp, 1000.0)
        self.assertLess(np.abs(back[50:950, 50:950].astype(int) - rendered[50:950, 50:950]).mean(), 3)

    def test_a_scale_is_measured(self):
        rendered = self.picture()
        # Content 4 px to the left in the west, 12 px in the east
        columns = np.arange(1000) + 4 + 8 * np.arange(1000) / 1000
        texture = np.dstack([ndimage.map_coordinates(rendered[..., c], np.meshgrid(np.arange(1000.0), columns, indexing="ij"), order=1, mode="nearest") for c in range(3)])
        warp = self.warp_of(rendered, texture)
        self.assertAlmostEqual(warp[0], -4, delta=1.2)
        self.assertAlmostEqual(warp[1], -8, delta=2.0)
        self.assertLess(abs(warp[2]), 1.0)

    def test_a_featureless_map_is_not_warped(self):
        self.assertIsNone(self.warp_of(np.full((1000, 1000, 3), 90, np.uint8), np.full((1000, 1000, 3), 90, np.uint8)))

    def test_a_shift_below_the_threshold_is_ignored(self):
        rendered = self.picture()
        self.assertIsNone(self.warp_of(rendered, np.roll(rendered, 1, 1)))


class ToneFieldTest(unittest.TestCase):
    FRAME = {"x": 0.0, "y": 0.0, "w": 200.0, "h": 200.0}

    def test_open_ground_carries_the_capture_over_the_render(self):
        reference = np.full((200, 200, 3), 120, np.uint8)
        reference[:, 100:] = 60
        field = render_map.tone_field(FlatRender((100, 100, 100)), self.FRAME, reference, np.ones((200, 200), bool), np.zeros((200, 200), bool), np.zeros((200, 200), bool), 1.0)
        self.assertAlmostEqual(float(field[100, 20, 0]), 1.2, delta=0.02)
        self.assertAlmostEqual(float(field[100, 180, 0]), 0.6, delta=0.02)

    def test_a_roof_of_the_capture_does_not_print_on_the_ground(self):
        reference = np.full((200, 200, 3), 100, np.uint8)
        reference[90:110, 90:110] = 250
        free = np.ones((200, 200), bool)
        free[86:114, 86:114] = False
        field = render_map.tone_field(FlatRender((100, 100, 100)), self.FRAME, reference, free, np.zeros((200, 200), bool), np.zeros((200, 200), bool), 1.0)
        self.assertAlmostEqual(float(field[100, 100, 0]), 1.0, delta=0.02)

    def test_a_forest_without_open_ground_takes_the_ratio_of_the_map(self):
        reference = np.full((200, 200, 3), 130, np.uint8)
        free = np.ones((200, 200), bool)
        free[:, 60:] = False
        field = render_map.tone_field(FlatRender((100, 100, 100)), self.FRAME, reference, free, np.zeros((200, 200), bool), np.zeros((200, 200), bool), 1.0)
        self.assertAlmostEqual(float(field[100, 190, 0]), 1.3, delta=0.02)

    def test_water_does_not_colour_the_shore(self):
        reference = np.full((200, 200, 3), 100, np.uint8)
        reference[:, 100:] = (160, 40, 40)
        water = np.zeros((200, 200), bool)
        water[:, 100:] = True
        land = ~ndimage.binary_dilation(water, iterations=3)
        field = render_map.tone_field(FlatRender((100, 100, 100)), self.FRAME, reference, land, water, np.zeros((200, 200), bool), 1.0)
        np.testing.assert_allclose(field[100, 99], (1.0, 1.0, 1.0), atol=0.02)
        np.testing.assert_allclose(field[100, 150], (1.6, 0.55, 0.55), atol=0.02)

    def test_a_pond_does_not_take_the_colour_of_the_sea(self):
        reference = np.full((200, 200, 3), 100, np.uint8)
        reference[:, 100:] = (40, 100, 160)
        water = np.zeros((200, 200), bool)
        water[:, 100:] = True
        water[20:24, 20:24] = True
        land = ~ndimage.binary_dilation(water, iterations=3)
        field = render_map.tone_field(FlatRender((100, 100, 100)), self.FRAME, reference, land, water, np.zeros((200, 200), bool), 1.0)
        np.testing.assert_allclose(field[22, 22], (1.0, 1.0, 1.0), atol=0.05)

    def test_a_capture_showing_land_at_the_shore_makes_no_rim_on_the_water(self):
        reference = np.full((200, 200, 3), 100, np.uint8)
        reference[:, 100:] = (90, 100, 110)
        reference[:, 100:103] = (200, 180, 120)
        water = np.zeros((200, 200), bool)
        water[:, 100:] = True
        land = ~ndimage.binary_dilation(water, iterations=3)
        field = render_map.tone_field(FlatRender((100, 100, 100)), self.FRAME, reference, land, water, np.zeros((200, 200), bool), 1.0)
        self.assertLess(float(field[100, 100, 0]), 1.15)

    def test_a_tree_only_the_capture_shows_does_not_print_on_the_ground(self):
        reference = np.full((200, 200, 3), 100, np.uint8)
        yy, xx = np.mgrid[:200, :200]
        reference[(yy - 100) ** 2 + (xx - 100) ** 2 < 25] = (30, 70, 20)
        everywhere, no_water = np.ones((200, 200), bool), np.zeros((200, 200), bool)
        field = render_map.tone_field(FlatRender((100, 100, 100)), self.FRAME, reference, everywhere, no_water, np.zeros((200, 200), bool), 1.0)
        np.testing.assert_allclose(field[100, 100], (1.0, 1.0, 1.0), atol=0.03)

    def test_mottling_of_the_ground_stays(self):
        reference = np.full((200, 200, 3), 100, np.uint8)
        reference[:, ::16] = 120
        reference[:, 1::16] = 120
        reference[:, 2::16] = 120
        reference[:, 3::16] = 120
        everywhere, no_water = np.ones((200, 200), bool), np.zeros((200, 200), bool)
        field = render_map.tone_field(FlatRender((100, 100, 100)), self.FRAME, reference, everywhere, no_water, np.zeros((200, 200), bool), 1.0)
        self.assertGreater(float(field[100, 97:99, 0].max() - field[100, 104:110, 0].min()), 0.05)

    def test_past_the_landscape_the_render_shows_the_capture(self):
        # Sanxian: the frame reaches past the landscape, where the capture shows the sea; the limits would leave a dark grey band
        reference = np.full((200, 200, 3), 100, np.uint8)
        reference[:, 180:] = (20, 40, 45)
        uncovered = np.zeros((200, 200), bool)
        uncovered[:, 180:] = True
        field = render_map.tone_field(FlatRender((100, 100, 100)), self.FRAME, reference, np.ones((200, 200), bool), np.zeros((200, 200), bool), uncovered, 1.0)
        np.testing.assert_allclose(field[100, 190] * 101 - 1, (20, 40, 45), atol=0.01)
        np.testing.assert_allclose(field[100, 100], (1.0, 1.0, 1.0), atol=0.02)

    def test_a_mesh_past_the_landscape_keeps_its_colours(self):
        # Chora: backdrop mountains are meshes standing past the landscape, drawn in their own colours
        reference = np.full((200, 200, 3), 100, np.uint8)
        reference[:, 180:] = (20, 40, 45)
        uncovered = np.zeros((200, 200), bool)
        uncovered[:, 160:] = True
        land = ~uncovered
        field = render_map.tone_field(FlatRender((100, 100, 100)), self.FRAME, reference, land, np.zeros((200, 200), bool), uncovered, 1.0)
        self.assertGreaterEqual(float(field[100, 190].min()), render_map.TONE_LIMITS[0])

    def test_a_changed_place_cannot_repaint_the_render(self):
        reference = np.zeros((200, 200, 3), np.uint8)
        field = render_map.tone_field(FlatRender((100, 100, 100)), self.FRAME, reference, np.ones((200, 200), bool), np.zeros((200, 200), bool), np.zeros((200, 200), bool), 1.0)
        self.assertGreaterEqual(float(field.min()), render_map.TONE_LIMITS[0])


class OpenGroundTest(unittest.TestCase):
    def setUp(self):
        self.raster = np.zeros((100, 100), np.int64)
        self.scene = FlatRender((0, 0, 0), self.raster, {"/a/Wall.Wall": 1, "/a/Bush.Bush": 2, "/a/MI_Water_River.MI_Water_River": 3})

    def ground(self):
        return ground_fit.open_ground(self.scene, (0.0, 0.0), 100.0, 100, 1.0)[0]

    def test_a_house_is_left_out_with_a_margin(self):
        self.raster[40:60, 40:60] = 1
        free = self.ground()
        self.assertFalse(free[50, 50])
        self.assertFalse(free[50, 62])
        self.assertTrue(free[50, 70])

    def test_a_scattered_bush_does_not_strike_out_its_field(self):
        self.raster[::8, ::8] = 2
        self.assertGreater(self.ground().mean(), 0.99)

    def test_water_is_its_own_class_and_the_shore_is_left_out(self):
        self.raster[:, 50:] = 3
        land, water = ground_fit.open_ground(self.scene, (0.0, 0.0), 100.0, 100, 1.0)
        self.assertTrue(water[50, 60])
        self.assertFalse(water[50, 40])
        self.assertFalse(land[50, 60])
        self.assertFalse(land[50, 48])
        self.assertTrue(land[50, 40])


def write_texture(folder, table, name, colour, noise=8, seed=0, root="/Game"):
    """A 16 px texture in `folder`/textures with its entry in `table` under `root`; its pixels vary around `colour`."""
    random = np.random.default_rng(seed)
    pixels = np.clip(np.array(colour, np.float32) + random.integers(-noise, noise + 1, (16, 16, 1)), 0, 255)
    data = np.dstack([pixels, np.full((16, 16), 255.0)]).astype(np.uint8)
    file = str(len(table))
    data.tofile(os.path.join(folder, "textures", file + ".bin"))
    table[f"{root}/{name}.{name}"] = {"file": file, "format": "PF_R8G8B8A8", "width": 16, "height": 16}
    return f"{root}/{name}.{name}"


class LayerDetailsTest(unittest.TestCase):
    def make_scene(self, folder, parameters):
        os.makedirs(os.path.join(folder, "textures"))
        table = {}
        textures = {key: write_texture(folder, table, name, colour) for key, (name, colour) in parameters.items()}
        Path(folder, "landscape.json").write_text(json.dumps({"level": {"textures": textures, "scalars": {}}}))
        Path(os.path.join(folder, "textures.json")).write_text(json.dumps(table))

    def test_goose_bay_layers_take_their_albedo_parameter_not_a_name_holding_the_letter(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_scene(folder, {"A Albedo": ("T_Snow_A", (222, 224, 225)), "B Albedo": ("T_SnowGrass_A", (134, 129, 110)), "Other": ("T_Asphalt_Dark", (60, 60, 60))})
            _, _, report = ground_fit.layer_details(folder, ["A_LayerInfo", "B_LayerInfo"], np.array([[220.0, 220, 220], [130, 130, 110]]))
            self.assertEqual(report, {"A_LayerInfo": "T_Snow_A", "B_LayerInfo": "T_SnowGrass_A"})

    def test_a_mask_packed_into_rgb_is_never_a_ground_texture(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_scene(folder, {"Plain": ("T_Grass_01", (90, 85, 50))})
            # Three masks in the channels of one texture: its mean is nearest to the layer's colour, its channels vary apart
            table = json.loads(Path(folder, "textures.json").read_text())
            path = write_texture(folder, table, "T_Packed", (30, 100, 56))
            pixels = np.random.default_rng(1).integers(0, 200, (16, 16, 4), np.uint8)
            pixels[..., 3] = 255
            pixels.tofile(os.path.join(folder, "textures", table[path]["file"] + ".bin"))
            Path(folder, "textures.json").write_text(json.dumps(table))
            landscape = json.loads(Path(folder, "landscape.json").read_text())
            landscape["level"]["textures"]["Packed"] = path
            Path(folder, "landscape.json").write_text(json.dumps(landscape))
            _, _, report = ground_fit.layer_details(folder, ["Unknown_LayerInfo"], np.array([[30.0, 100, 56]]))
            self.assertEqual(report["Unknown_LayerInfo"], "T_Grass_01")

    def test_a_texture_holding_the_layer_name_names_the_layer(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_scene(folder, {"First": ("T_Sand_01", (90, 85, 50)), "Second": ("T_EuropeanGrass_01_BC", (120, 95, 60))})
            _, _, report = ground_fit.layer_details(folder, ["Grass_LayerInfo"], np.array([[90.0, 85, 50]]))
            self.assertEqual(report["Grass_LayerInfo"], "T_EuropeanGrass_01_BC")

    def test_the_engines_default_textures_are_never_a_ground_texture(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_scene(folder, {"Grass Albedo": ("T_Grass_01", (90, 85, 50))})
            table = json.loads(Path(folder, "textures.json").read_text())
            # The landscape material lists its default parameter values beside the ground textures; this one is the nearest to the layer's colour
            engine = write_texture(folder, table, "BlendFunc_DefBase", (120, 120, 120), root="/Engine/EngineMaterials")
            Path(folder, "textures.json").write_text(json.dumps(table))
            landscape = json.loads(Path(folder, "landscape.json").read_text())
            landscape["level"]["textures"]["BlendFunc_DefBase"] = engine
            Path(folder, "landscape.json").write_text(json.dumps(landscape))
            _, _, report = ground_fit.layer_details(folder, ["Unknown_LayerInfo"], np.array([[120.0, 120, 120]]))
            self.assertEqual(report["Unknown_LayerInfo"], "T_Grass_01")

    def test_a_layer_with_only_engine_textures_to_choose_from_keeps_its_fitted_colour(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "textures"))
            table = {}
            engine = write_texture(folder, table, "BlendFunc_DefBlend", (83, 56, 40), root="/Engine/EngineMaterials")
            Path(folder, "textures.json").write_text(json.dumps(table))
            Path(folder, "landscape.json").write_text(json.dumps({"level": {"textures": {"BlendFunc_DefBlend": engine}, "scalars": {}}}))
            details, _, report = ground_fit.layer_details(folder, ["Gravel_LayerInfo"], np.array([[100.0, 90, 70]]))
            self.assertEqual(report, {"Gravel_LayerInfo": None})
            self.assertTrue((details == 128).all())


class InvisibleFoliageTest(unittest.TestCase):
    def make_scene(self, folder):
        os.makedirs(os.path.join(folder, "meshes"))
        meshes = {}
        for mesh_id, (name, height_cm) in enumerate((("Flower", 40.0), ("Rock", 150.0), ("Spruce", 2000.0), ("Few", 40.0))):
            vertices = np.zeros((2, 8), np.float32)
            vertices[1, 2] = height_cm
            vertices.tofile(os.path.join(folder, "meshes", f"{mesh_id}.bin"))
            meshes[f"/Game/{name}.{name}"] = {"id": mesh_id, "vertices": 2}
        Path(os.path.join(folder, "meshes.json")).write_text(json.dumps(meshes))
        place = {0: [(100, 100), (300, 100), (500, 100)] * 10, 1: [(20 + 4 * i, 200) for i in range(30)], 2: [(100 + 4 * i, 300) for i in range(30)], 3: [(50, 50)]}
        with open(os.path.join(folder, "instances.ndjson"), "w") as out:
            for mesh_id, points in place.items():
                instances = [{"q": [0, 0, 0, 1], "t": [x * 100, y * 100, 0], "s": [1, 1, 1]} for x, y in points]
                out.write(json.dumps({"type": "FoliageInstancedStaticMeshComponent", "mesh": mesh_id, "chain": [], "instances": instances}) + "\n")

    def test_what_the_capture_does_not_show_goes_and_the_rest_stays(self):
        with tempfile.TemporaryDirectory() as folder:
            self.make_scene(folder)
            reference = np.full((512, 512, 3), 100, np.uint8)
            # The rocks are lighter than their surroundings, the spruces leave no mark at all
            for i in range(30):
                x = 20 + 4 * i
                reference[198:203, x - 2:x + 3] = 180
            hidden, report = ground_fit.invisible_foliage(folder, reference, (0.0, 0.0), 512.0)
            self.assertEqual(hidden, [0])
            self.assertTrue(report["Rock"]["visible"])
            self.assertTrue(report["Spruce"]["visible"])
            self.assertFalse(report["Flower"]["visible"])
            self.assertNotIn("Few", report)


class FakeMaterialScene:
    """Scene as calibrate_materials sees it: one material over the whole block, its render and its ids."""

    def __init__(self, path, blend, lit, leaf=False):
        self.path, self.lit = path, lit
        self.materials = {path: {"blend": blend}}
        self.leaf_materials = {path} if leaf else set()
        self.crown_materials = set()
        self.material_gains = {}
        self.gain = (1.0, 1.0, 1.0)

    def render_ids(self, x0, y0, x1, y1, width, height, ids):
        ids.setdefault(self.path, 1)
        return np.ones((height, width), np.int64)

    def render(self, x0, y0, x1, y1, width, height, ssaa=2):
        return self.lit[:height, :width]


class CalibrateMaterialsTest(unittest.TestCase):
    def gain_of(self, scene, reference):
        ground_fit.calibrate_materials(scene, reference, (0.0, 0.0), 32.0, block=32, step_m=1.0, iterations=1)
        return np.array(scene.material_gains[scene.path]) * scene.gain[0]

    def test_a_wall_takes_the_mean_colour_of_the_capture(self):
        lit = np.full((32, 32, 3), 100, np.uint8)
        reference = np.full((32, 32, 3), 150, np.uint8)
        np.testing.assert_allclose(self.gain_of(FakeMaterialScene("/a/Wall.Wall", "BLEND_Opaque", lit), reference), (1.5 ** 2.2,) * 3, rtol=0.01)

    def test_a_masked_road_is_no_foliage(self):
        self.assertFalse(ground_fit.is_leafy(FakeMaterialScene("/a/MI_Roads_Asphalt.MI_Roads_Asphalt", "BLEND_Masked", None), "/a/MI_Roads_Asphalt.MI_Roads_Asphalt"))

    def test_palm_cards_are_read_from_the_leaves_not_the_sand_around_them(self):
        lit = np.full((32, 32, 3), 100, np.uint8)
        reference = np.full((32, 32, 3), 200, np.uint8)
        reference[:8] = 50
        gain = self.gain_of(FakeMaterialScene("/a/Frond.Frond", "BLEND_Masked", lit), reference)
        np.testing.assert_allclose(gain, (0.5 ** 2.2,) * 3, rtol=0.05)

    def test_a_plant_the_capture_does_not_show_stays_dark(self):
        lit = np.full((32, 32, 3), 100, np.uint8)
        reference = np.full((32, 32, 3), 240, np.uint8)
        gain = self.gain_of(FakeMaterialScene("/a/Tamarix.Tamarix", "BLEND_Opaque", lit, leaf=True), reference)
        np.testing.assert_allclose(gain, ((ground_fit.SNOW_LEAF_LUMA_LIMIT / 100) ** 2.2,) * 3, rtol=0.01)

    def test_on_a_map_without_snow_a_light_plant_is_limited_to_leaf_colours(self):
        lit = np.full((32, 32, 3), 100, np.uint8)
        reference = np.full((32, 32, 3), 180, np.uint8)
        gain = self.gain_of(FakeMaterialScene("/a/Tamarix.Tamarix", "BLEND_Opaque", lit, leaf=True), reference)
        np.testing.assert_allclose(gain, ((ground_fit.LEAF_LUMA_LIMIT / 100) ** 2.2,) * 3, rtol=0.01)

    def test_a_clipped_roof_goes_to_the_measured_roof_colour(self):
        lit = np.full((32, 32, 3), 100, np.uint8)
        reference = np.full((32, 32, 3), 255, np.uint8)
        scene = FakeMaterialScene("/a/Roof.Roof", "BLEND_Opaque", lit)
        ground_fit.calibrate_materials(scene, reference, (0.0, 0.0), 32.0, block=32, step_m=1.0, iterations=1, roof_target=(219, 206, 191))
        np.testing.assert_allclose(np.array(scene.material_gains[scene.path]) * scene.gain[0], [(v / 100) ** 2.2 for v in (219, 206, 191)], rtol=0.01)


class SplineBendTest(unittest.TestCase):
    """A spline mesh is turned about its spline by the component's roll: a slab 10 m long (Y, its forward axis), 4 m wide (X) and
    0.5 m thick (Z), its top facing up, along a straight spline that runs east."""

    @staticmethod
    def bent(roll):
        corners = [(x, y, z) for x in (-200.0, 200.0) for y in (0.0, 1000.0) for z in (0.0, 50.0)]
        vertices = np.array([[x, y, z, 0.0, 0.0, 1.0, x / 400.0, y / 1000.0] for x, y, z in corners])
        east = {"X": 1000.0, "Y": 0.0, "Z": 0.0}
        spline = {"p": {"StartPos": {"X": 0.0, "Y": 0.0, "Z": 0.0}, "StartTangent": east, "StartRoll": roll, "EndPos": east, "EndTangent": east, "EndRoll": roll},
                  "axis": "Y", "up": {"X": 0.0, "Y": 0.0, "Z": 1.0}}
        return vertices, scene_render.bend_along_spline(vertices, spline, (vertices[:, :3].min(0), vertices[:, :3].max(0)))

    def test_the_quarter_turn_of_a_landscape_spline_stands_a_mesh_that_runs_along_y_up(self):
        # Manicouagan's double pipeline, crash barriers, railway tracks, fences: without the roll they lay on their side, a thin line off the spline
        vertices, bent = self.bent(-math.pi / 2)
        np.testing.assert_allclose(bent[:, :3].min(0), (0, -200, 0), atol=1e-6)
        np.testing.assert_allclose(bent[:, :3].max(0), (1000, 200, 50), atol=1e-6)
        np.testing.assert_allclose(bent[:, 3:6], np.tile((0.0, 0.0, 1.0), (8, 1)), atol=1e-6)
        np.testing.assert_array_equal(bent[:, 6:], vertices[:, 6:])

    def test_without_a_roll_the_x_axis_of_such_a_mesh_is_up(self):
        _, bent = self.bent(0.0)
        np.testing.assert_allclose(bent[:, :3].min(0), (0, 0, -200), atol=1e-6)
        np.testing.assert_allclose(bent[:, :3].max(0), (1000, 50, 200), atol=1e-6)
        np.testing.assert_allclose(bent[:, 3:6], np.tile((0.0, 1.0, 0.0), (8, 1)), atol=1e-6)


class DepthRangeTest(unittest.TestCase):
    """A scene far from sea level, written to a temporary folder and drawn on the GPU (skipped without an EGL context)."""

    ROOF = "/Game/Maps/Test/Roof.Roof"

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        directory = cls.folder.name
        # A 40 m square standing 770 m below sea level, like Chora's buildings
        corners = [(-2000.0, -2000.0), (2000.0, -2000.0), (2000.0, 2000.0), (-2000.0, 2000.0)]
        vertices = np.array([[x, y, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0] for x, y in corners], np.float32)
        Path(directory, "meshes").mkdir()
        Path(directory, "meshes", "roof.bin").write_bytes(vertices.tobytes() + np.array([0, 1, 2, 0, 2, 3], np.uint32).tobytes())
        Path(directory, "meshes.json").write_text(json.dumps({"/Game/Roof.Roof": {"id": "roof", "vertices": 4, "materials": [cls.ROOF], "sections": [{"material": 0, "first": 0, "triangles": 2}]}}))
        Path(directory, "materials.json").write_text("{}")
        Path(directory, "textures.json").write_text("{}")
        link = {"l": {"X": 0.0, "Y": 0.0, "Z": -77000.0}, "r": {"Pitch": 0.0, "Yaw": 0.0, "Roll": 0.0}, "s": {"X": 1.0, "Y": 1.0, "Z": 1.0}}
        Path(directory, "instances.ndjson").write_text(json.dumps({"level": "L", "name": "Roof", "type": "StaticMeshComponent", "owner": "A", "mesh": "roof", "hidden": False,
                                                                   "cull": None, "overrides": None, "chain": [link], "instances": None, "spline": None}) + "\n")
        try:
            cls.scene = scene_render.Scene(directory)
        except Exception as error:
            cls.folder.cleanup()
            raise unittest.SkipTest(f"no OpenGL context: {error}")
        heights = np.full((64, 64), -770.0, np.float32)
        cls.scene.ground = {"heights": heights, "bounds": (-32.0, -32.0), "step": 1.0, "z_range": (-77000.0, -77000.0)}

    @classmethod
    def tearDownClass(cls):
        cls.scene.ctx.release()
        cls.folder.cleanup()

    def test_the_range_reaches_down_to_the_scene_and_keeps_the_default_above(self):
        low, high = self.scene.depth_range()
        self.assertLess(low, -77000.0)
        self.assertEqual(high, scene_render.DEFAULT_DEPTH_CM[1])

    def test_a_roof_far_below_sea_level_is_drawn(self):
        ids = {}
        material = self.scene.render_ids(-16.0, -16.0, 16.0, 16.0, 32, 32, ids)
        self.assertEqual(ids[self.ROOF], 1)
        self.assertTrue((material == 1).all())


@unittest.skipUnless(os.environ.get("MAPRENDER_SCENE"), "needs a scene of the game client and the GPU")
class RealSceneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scene, cls.frame, _ = render_map.load_map(os.environ["MAPRENDER_SCENE"], os.environ["MAPRENDER_TEXTURE"])

    def test_neighbouring_blocks_agree_along_their_common_edge(self):
        frame, scene = self.frame, self.scene
        metres_per_pixel = frame["w"] / (256 * 2 ** render_map.finest_zoom(frame["w"]))
        x0, y0 = frame["x"] + frame["w"] * 0.45, frame["y"] + frame["h"] * 0.45
        whole = scene.render(x0, y0, x0 + 512 * metres_per_pixel, y0 + 256 * metres_per_pixel, 512, 256, ssaa=2)
        left = scene.render(x0, y0, x0 + 256 * metres_per_pixel, y0 + 256 * metres_per_pixel, 256, 256, ssaa=2)
        right = scene.render(x0 + 256 * metres_per_pixel, y0, x0 + 512 * metres_per_pixel, y0 + 256 * metres_per_pixel, 256, 256, ssaa=2)
        joined = np.hstack([left, right]).astype(np.int32)
        difference = np.abs(joined - whole).mean(-1)
        self.assertLess(float(difference[:, 250:262].mean()), 3.0)
        self.assertLess(float(np.quantile(difference[:, 250:262], 0.99)), 25.0)

    def test_the_same_box_renders_the_same_twice(self):
        frame, scene = self.frame, self.scene
        x0, y0 = frame["x"] + frame["w"] * 0.4, frame["y"] + frame["h"] * 0.4
        first = scene.render(x0, y0, x0 + 64, y0 + 64, 256, 256, ssaa=2)
        second = scene.render(x0, y0, x0 + 64, y0 + 64, 256, 256, ssaa=2)
        np.testing.assert_array_equal(first, second)


if __name__ == "__main__":
    unittest.main()
