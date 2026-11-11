import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image
from scipy import ndimage

import layer_minimaps as lm
import register_images as ri
import relief


def smooth_field(shape, seed, sigma=3.0):
    """A random field with structure at every position (no two windows alike)."""
    rng = np.random.default_rng(seed)
    return ndimage.gaussian_filter(rng.standard_normal(shape).astype(np.float32), sigma)


def displaced(field, dx, dy):
    """The field drawn with its content moved by (dx, dy) px, arrays over the field's grid (+ = east, south)."""
    rows, cols = np.mgrid[0:field.shape[0], 0:field.shape[1]].astype(np.float64)
    return ndimage.map_coordinates(field, [rows - dy, cols - dx], order=3, mode="reflect")


class NccShiftTest(unittest.TestCase):
    def test_sub_pixel_shift(self):
        reference = ri.edges(smooth_field((128, 128), 1, sigma=1.5))
        picture = ndimage.shift(reference, (-2.7, 3.4), order=3, mode="wrap")
        dx, dy, peak, sharpness, at_edge = ri.ncc_shift(picture, reference, 8)
        self.assertAlmostEqual(dx, 3.4, delta=0.1)
        self.assertAlmostEqual(dy, -2.7, delta=0.1)
        self.assertGreater(peak, 0.8)
        self.assertGreater(sharpness, ri.MIN_SHARPNESS)
        self.assertFalse(at_edge)

    def test_shift_past_the_search_is_on_its_edge(self):
        reference = smooth_field((96, 96), 2)
        picture = ndimage.shift(reference, (0, 12), order=3, mode="wrap")
        self.assertTrue(ri.ncc_shift(picture, reference, 6)[4])


class FitTest(unittest.TestCase):
    @staticmethod
    def points(dx, dy, n=8):
        """Windows on an n x n lattice whose shifts are the functions dx(u, v), dy(u, v) (u, v in -0.5..0.5)."""
        return [(i / (n - 1) * 0.8 + 0.1, j / (n - 1) * 0.8 + 0.1, dx(i / (n - 1) * 0.8 - 0.4, j / (n - 1) * 0.8 - 0.4),
                 dy(i / (n - 1) * 0.8 - 0.4, j / (n - 1) * 0.8 - 0.4), 0.5) for j in range(n) for i in range(n)]

    def test_offset_scale_and_turn(self):
        w = h = 1000
        turn = np.radians(0.25)
        # 0.3 % too wide, turned 0.25 degree clockwise, 2 px east and 1 px north
        points = self.points(lambda u, v: 2.0 + 0.003 * u * w - turn * v * h, lambda u, v: -1.0 + turn * u * w)
        fit = ri.summarise(points, 0.5, (h, w))
        self.assertAlmostEqual(fit["scale"][0], 0.003, places=5)
        self.assertAlmostEqual(fit["scale"][1], 0.0, places=5)
        self.assertAlmostEqual(fit["rotation_deg"], 0.25, places=3)
        self.assertAlmostEqual(fit["W"], (2.0 - 0.0015 * w) * 0.5, places=2)
        self.assertAlmostEqual(fit["E"], (2.0 + 0.0015 * w) * 0.5, places=2)
        self.assertEqual(fit["C"], [1.0, -0.5])
        self.assertEqual(fit["windows"], 64)
        self.assertEqual(fit["rms"], [0.0, 0.0])

    def test_outliers_left_out(self):
        points = self.points(lambda u, v: 1.0, lambda u, v: 1.0)
        points[5] = points[5][:2] + (9.0, 1.0, 0.5)
        points[40] = points[40][:2] + (1.0, -8.0, 0.5)
        fit = ri.summarise(points, 1.0, (500, 500))
        self.assertEqual(fit["windows"], 62)
        self.assertEqual(fit["C"], [1.0, 1.0])

    def test_too_few_windows(self):
        self.assertIsNone(ri.summarise(self.points(lambda u, v: 0.0, lambda u, v: 0.0, n=2), 1.0, (100, 100)))
        self.assertIsNone(ri.summarise([], 1.0, (100, 100)))


class RegisterTest(unittest.TestCase):
    def test_affine_displacement_in_metres(self):
        world = smooth_field((640, 640), 3)
        rows, cols = np.mgrid[0:640, 0:640].astype(np.float64)
        dx = 1.5 + 0.004 * (cols - 320)
        picture = ndimage.map_coordinates(world, [rows + 0.8, cols - dx], order=3, mode="reflect")
        fit, measured = ri.register(ri.edges(world), ri.edges(picture), np.ones(world.shape, bool), 0.5, search_m=8)
        self.assertEqual(measured, 64)
        self.assertAlmostEqual(fit["W"], (1.5 - 0.004 * 320) * 0.5, delta=0.05)
        self.assertAlmostEqual(fit["E"], (1.5 + 0.004 * 320) * 0.5, delta=0.05)
        self.assertAlmostEqual(fit["N"], -0.4, delta=0.05)
        self.assertAlmostEqual(fit["S"], -0.4, delta=0.05)
        self.assertAlmostEqual(fit["scale"][0], 0.004, delta=2e-4)

    def test_windows_without_picture_are_not_measured(self):
        world = smooth_field((320, 320), 4)
        valid = np.ones(world.shape, bool)
        valid[:, :160] = False
        _, measured = ri.register(ri.edges(world), ri.edges(world), valid, 1.0, search_m=4)
        # windows of 50 px start at 0, 38, 77, 115, 154, 192, 231, 270: the last three columns lie in the picture
        self.assertEqual(measured, 24)

    def test_picture_over_the_wrong_rectangle_gives_the_one_it_shows(self):
        # world points every metre from (-250, -250); the texture shows (-190, -200)-(205, 200), drawn over (-200, -200)-(200, 200)
        world = smooth_field((501, 501), 5, sigma=2.0)
        shows, drawn = (-190.0, -200.0, 205.0, 200.0), (-200.0, -200.0, 200.0, 200.0)
        n = 400
        tx = shows[0] + (np.arange(n) + 0.5) * (shows[2] - shows[0]) / n
        ty = shows[1] + (np.arange(n) + 0.5) * (shows[3] - shows[1]) / n
        texture = ri.sample_points(world, tx, ty, -250.0, -250.0, 1.0)
        step = (drawn[2] - drawn[0]) / n
        xs, ys = ri.frame_grid(drawn, step)
        placed = ri.sample_image(texture, xs, ys, drawn)
        reference = ri.edges(ri.sample_points(world, xs, ys, -250.0, -250.0, 1.0))
        fit, _ = ri.register(reference, ri.edges(np.nan_to_num(placed)), np.isfinite(placed), step, search_m=14)
        self.assertAlmostEqual(fit["W"], -10.0, delta=0.15)
        self.assertAlmostEqual(fit["E"], -5.0, delta=0.15)
        for got, want in zip(ri.fitted_rectangle(drawn, fit, xs, ys, step), shows):
            self.assertAlmostEqual(got, want, delta=0.3)


class ShadeTest(unittest.TestCase):
    # windows of 160 px: on smaller ones the overlap of the shifted window pulls a smooth field's peak toward zero.
    # The shading is recovered within 0.3 px, under the method's floor of about 0.4 m at the 1 m grid used here.
    @staticmethod
    def hills(shape, seed):
        return smooth_field(shape, seed, sigma=3.0) * 100.0

    def lit(self, ground, step):
        gy, gx = np.gradient(ground, step)
        return np.exp(4.0 + 0.8 * np.tanh(-0.6 * gx + 0.4 * gy))

    def test_shading_shift(self):
        ground = self.hills((1024, 1024), 6)
        picture = displaced(self.lit(ground, 1.0), 2.0, -1.0)
        reference, shading, valid = ri.shade_fields(ground, picture, 1.0)
        fit, _ = ri.register(reference, shading, valid, 1.0)
        self.assertAlmostEqual(fit["C"][0], 2.0, delta=0.3)
        self.assertAlmostEqual(fit["C"][1], -1.0, delta=0.3)

    def test_sea_and_outside_the_landscape(self):
        ground = self.hills((1024, 1024), 7)
        picture = displaced(self.lit(ground, 1.0) * np.where(ground > 0, 1.0, 0.6), -1.5, 0.0)
        ground[:, :80] = np.nan
        reference, shading, valid = ri.shade_fields(ground, picture, 1.0, sea_level=0.0)
        self.assertFalse(valid[:, :80].any())
        fit, _ = ri.register(reference, shading, valid, 1.0)
        self.assertEqual(fit["windows"], 56)
        self.assertAlmostEqual(fit["C"][0], -1.5, delta=0.3)
        self.assertAlmostEqual(fit["C"][1], 0.0, delta=0.3)


class SampleTest(unittest.TestCase):
    def test_texel_centres(self):
        image = np.arange(16, dtype=np.float32).reshape(4, 4)
        xs = np.array([12.5, 37.5, 87.5])
        ys = np.array([-87.5, -12.5])
        self.assertEqual(ri.sample_image(image, xs, ys, (0, -100, 100, 0)).tolist(), [[0, 1, 3], [12, 13, 15]])
        self.assertTrue(np.isnan(ri.sample_image(image, np.array([101.0]), np.array([-50.0]), (0, -100, 100, 0))).all())

    def test_points_with_two_spacings(self):
        points = np.array([[0, 1], [10, 11]], np.float32)
        self.assertAlmostEqual(float(ri.sample_points(points, np.array([1.0]), np.array([3.0]), 0.0, 0.0, 2.0, 6.0)[0, 0]), 5.5)

    def test_frame_grid(self):
        xs, ys = ri.frame_grid((-10.0, 0.0, 0.0, 5.0), 2.0)
        self.assertEqual(xs.tolist(), [-9.0, -7.0, -5.0, -3.0, -1.0])
        self.assertEqual(ys.tolist(), [1.0, 3.0])


class OrientationTest(unittest.TestCase):
    texture = smooth_field((1024, 1024), 8, sigma=4.0)

    def test_same_picture(self):
        result = ri.compare_orientation(self.texture, self.texture)
        self.assertEqual(result["orientation"], "rot0")
        self.assertEqual(result["correlation"], 1.0)
        self.assertEqual(result["windows"], 49)
        self.assertEqual(result["offset_px"], [0.0, 0.0])
        self.assertEqual(result["across_px"], [0.0, 0.0])

    def test_turned_picture(self):
        self.assertEqual(ri.compare_orientation(self.texture, np.rot90(self.texture))["orientation"], "rot270")
        self.assertEqual(ri.compare_orientation(self.texture, self.texture[:, ::-1])["orientation"], "rot0_mirror")

    def test_larger_picture_and_offset(self):
        # the picture 0.2 % larger about its centre and 0.5 px east: 1 px further east at the east edge than at the centre
        rows, cols = np.mgrid[0:1024, 0:1024].astype(np.float64)
        picture = ndimage.map_coordinates(self.texture, [511.5 + (rows - 511.5) / 1.002, 511.5 + (cols - 512.0) / 1.002], order=3, mode="reflect")
        picture = ndimage.zoom(picture, 0.5, order=1)
        result = ri.compare_orientation(self.texture, picture)
        self.assertEqual(result["orientation"], "rot0")
        self.assertAlmostEqual(result["offset_px"][0], 0.5, delta=0.15)
        self.assertAlmostEqual(result["across_px"][0], 1024 * 0.002, delta=0.25)
        self.assertAlmostEqual(result["across_px"][1], 1024 * 0.002, delta=0.25)


class LocateTest(unittest.TestCase):
    base = smooth_field((600, 600), 9, sigma=2.0)
    rect = (0.0, 0.0, 1200.0, 1200.0)
    # a 200 m square of the base at (500, 200), as a texture of 400 px
    texture = ndimage.zoom(base[100:200, 250:350], 4, order=3)

    def check(self, results, orientation):
        best = max(results, key=lambda r: r["best"]["ncc"])
        self.assertEqual(best["size_m"], 200.0)
        self.assertEqual(best["best"]["orientation"], orientation)
        self.assertGreater(best["best"]["ncc"], 0.9)
        for got, want in zip(best["best"]["shows"], (500, 200, 700, 400)):
            self.assertAlmostEqual(got, want, delta=2.5)

    def test_square_found_at_its_size(self):
        self.check(ri.locate(self.base, self.rect, self.texture, [160.0, 200.0, 240.0]), "rot0")

    def test_mirrored_and_cropped(self):
        self.check(ri.locate(self.base, self.rect, self.texture[:, ::-1], [200.0], crop=(0.25, 0.9, 0.1, 0.7)), "rot0_mirror")

    def test_sizes(self):
        self.assertEqual(ri.parse_sizes("700:750:25"), [700.0, 725.0, 750.0])
        self.assertEqual(ri.parse_sizes("700,725"), [700.0, 725.0])


@contextlib.contextmanager
def directories():
    """A temporary root with prep/, register/tex/ and layer-minimaps/ under it, patched into the module's paths."""
    with tempfile.TemporaryDirectory() as root:
        paths = {name: os.path.join(root, name) for name in ("prep", "register", "layer-minimaps", "layer-tiles")}
        for path in paths.values():
            os.makedirs(path)
        os.makedirs(os.path.join(paths["register"], "tex"))
        with mock.patch.multiple(ri, PREP=paths["prep"], REGISTER=paths["register"], LAYER_MINIMAPS=paths["layer-minimaps"],
                                 LAYER_TILES=paths["layer-tiles"]):
            yield paths


def write_prep(prep, slug, bounds, shape):
    os.makedirs(os.path.join(prep, slug))
    with open(os.path.join(prep, slug, "meta.json"), "w") as f:
        json.dump({"bounds_m": bounds}, f)
    np.save(os.path.join(prep, slug, "ground.npy"), np.zeros(shape, np.float32))


def write_bgra(directory, package, rgb):
    """A raw B8G8R8A8 texture file as the extractor's texraw writes it."""
    h, w = rgb.shape[:2]
    bgra = np.dstack([rgb[..., ::-1], np.full((h, w), 255, np.uint8)])
    with open(os.path.join(directory, f"{package}.PF_B8G8R8A8.{w}x{h}.bin"), "wb") as f:
        f.write(bgra.tobytes())


LEVELS = "\n".join([
    "SquadGame/Content/Maps/Jensens_Range/Gameplay_Layers/Jensens_Range_US_vs_RU.umap\t/Game/Maps/Jensens_Range/Minimap/Jensens_Range_Minimap.Jensens_Range_Minimap\t-200400\t-200400\t200400\t200400",
    "SquadGame/Content/Maps/Jensens_Range/Gameplay_Layers/Jensens_Range_US_vs_MEA.umap\t/Game/Maps/Jensens_Range/Minimap/Jensens_Range_Minimap.Jensens_Range_Minimap\t200400\t200400\t-200400\t-200400",
    "SquadGame/Content/Maps/Narva/Gameplay_Layers/Narva_AAS_v1.umap\t/Game/Maps/Narva/Minimap/Narva_Minimap.Narva_Minimap\t-138970.69\t139792.52\t141029.38\t-140207.44",
    "SquadGame/Content/Maps/Narva/Gameplay_Layers/Narva_RAAS_v1.umap\t/Game/Maps/Narva/Minimap/Narva_Minimap.Narva_Minimap\t-138970.69\t139792.52\t141029.38\t-140207.44",
    "SquadGame/Content/Maps/Narva/Gameplay_Layers/Narva_Skirmish_v1.umap\t/Game/Maps/Narva/Minimap/Narva_Minimap.Narva_Minimap\t-37000\t-96000\t70000\t11000",
    "SquadGame/Content/Maps/Mutaha/Gameplay_Layers/Mutaha_AAS_v1.umap\t/Game/Maps/Mutaha/Minimap/Mutaha_Minimap.Mutaha_Minimap\t-93500\t-114000\t182000\t161500",
])


class MapInfoTest(unittest.TestCase):
    def test_base_texture_game_and_image_rectangles(self):
        with directories() as paths:
            write_prep(paths["prep"], "jensen", {"min_x": -2004.0, "min_y": -2004.0, "max_x": 2004.0, "max_y": 2004.0}, (4, 4))
            write_prep(paths["prep"], "narva", {"min_x": -1390.0, "min_y": -1402.0, "max_x": 1410.0, "max_y": 1398.0}, (4, 4))
            infos = ri.map_infos(lm.layer_table(lm.parse_layer_table(LEVELS), {}))
        self.assertEqual(sorted(infos), ["jensen", "narva"])
        self.assertEqual(infos["jensen"].game_rect, (-2004.0, -2004.0, 2004.0, 2004.0))
        self.assertEqual(infos["narva"].texture, "/Game/Maps/Narva/Minimap/Narva_Minimap.Narva_Minimap")
        self.assertEqual(infos["narva"].game_rect, (-1389.7069, -1402.0744, 1410.2938, 1397.9252))
        self.assertEqual(infos["narva"].image_rect, (-1390.0, -1402.0, 1410.0, 1398.0))

    def test_slugs(self):
        self.assertEqual(ri.slug_of("Jensens"), "jensen")
        self.assertEqual(ri.slug_of("PacificProvingGrounds"), "pacific")
        self.assertEqual(ri.slug_of("BlackCoast"), "blackcoast")

    def test_textures_pattern(self):
        with directories() as paths:
            with open(os.path.join(paths["layer-minimaps"], "layers.tsv"), "w") as f:
                f.write(LEVELS)
            os.makedirs(os.path.join(paths["layer-minimaps"], "layerdata"))
            with open(os.path.join(paths["layer-minimaps"], "layerdata", "Narva_Skirmish_v1.json"), "w") as f:
                json.dump([{"Properties": {"Worlds": [{"AssetPathName": "/Game/Maps/Narva/Gameplay_Layers/Narva_Skirmish_v1.Narva_Skirmish_v1"}],
                                           "OveriddenMinimapTexture": {"AssetPathName": "/Game/Maps/Narva/Minimap/Narva_Minimap_Skirmish_v1.Narva_Minimap_Skirmish_v1"}}}], f)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                ri.print_textures()
        pattern = output.getvalue().strip()
        for package in ("Jensens_Range_Minimap", "Narva_Minimap", "Narva_Minimap_Skirmish_v1", "Mutaha_Minimap"):
            self.assertIn(package, pattern)
        self.assertEqual(pattern.count("|"), 3)


class TextureTest(unittest.TestCase):
    def test_client_texture_by_name_and_path(self):
        rgb = np.random.default_rng(10).integers(0, 255, (8, 12, 3), dtype=np.uint8)
        with directories() as paths:
            write_bgra(os.path.join(paths["register"], "tex"), "T_BlackCoast_Seed_v1", rgb)
            self.assertEqual(ri.client_texture("t_blackcoast_seed_v1").tolist(), rgb.tolist())
            self.assertEqual(ri.client_texture("/BlackCoast/Maps/Minimap/T_BlackCoast_Seed_v1.T_BlackCoast_Seed_v1").shape, (8, 12, 3))
            self.assertEqual(ri.texture_width("T_BlackCoast_Seed_v1"), 12)
            with self.assertRaises(SystemExit):
                ri.client_texture("Missing")

    def test_upstream_heightmap_levels(self):
        rgb = np.array([[[10, 3, 0], [0, 0, 20]]], np.uint8)
        self.assertEqual(ri.upstream_heightmap(rgb).tolist(), [[265.0, 235.0]])

    def test_tile_mosaic(self):
        with tempfile.TemporaryDirectory() as tiles, mock.patch.object(ri, "TILES", tiles):
            os.makedirs(os.path.join(tiles, "map", "1"))
            for x, y, value in ((0, 0, 10), (1, 0, 20), (1, 1, 40)):
                Image.fromarray(np.full((256, 256, 3), value, np.uint8)).save(os.path.join(tiles, "map", "1", f"{x}_{y}.webp"), lossless=True)
            mosaic = ri.tile_mosaic("map", 1)
        self.assertEqual(mosaic.shape, (512, 512, 3))
        self.assertEqual([int(mosaic[0, 0, 0]), int(mosaic[0, 300, 0]), int(mosaic[300, 0, 0]), int(mosaic[300, 300, 0])], [10, 20, 0, 40])

    def test_pmtiles_mosaic(self):
        level = np.tile(np.linspace(0.1, 0.9, 512, dtype=np.float32), (512, 1))
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "map.pmtiles")
            relief.write_pmtiles(path, {0: level[::2, ::2], 1: level}, {})
            mosaic = ri.pmtiles_mosaic(path, 1)
            self.assertEqual(mosaic.shape, (512, 512))
            self.assertLess(float(np.abs(mosaic - level * 255).mean()), 2.0)
            self.assertTrue(np.isnan(ri.pmtiles_mosaic(path, 2)).all())


class FeaturesTest(unittest.TestCase):
    bounds = {"min_x": 0.0, "min_y": 0.0, "max_x": 100.0, "max_y": 100.0}

    def test_crowns_without_rocks(self):
        foliage = {"cls": np.array([1, 3]), "radius": np.array([3.0, 3.0]), "x": np.array([40.0, 70.0]), "y": np.array([50.0, 50.0])}
        crowns = ri.crown_field(foliage, self.bounds, (100, 100))
        self.assertAlmostEqual(float(crowns[50, 40]), 1.0, delta=0.05)
        self.assertEqual(float(crowns[50, 70]), 0.0)

    def test_road_surfaces(self):
        lines = [{"cls": "asphalt", "left": [[10, 48], [90, 48]], "right": [[10, 52], [90, 52]]},
                 {"cls": "wall", "left": [[10, 20], [90, 20]], "right": [[10, 24], [90, 24]]}]
        canvas = ri.road_canvas(lines, self.bounds, (100, 100), 2)
        self.assertEqual(canvas.shape, (200, 200))
        self.assertEqual(float(canvas[100, 100]), 1.0)
        self.assertEqual(float(canvas[44, 100]), 0.0)

    def test_reference_follows_the_level(self):
        with directories() as paths:
            write_prep(paths["prep"], "test", self.bounds, (100, 100))
            coverage = np.zeros((100, 100), np.uint8)
            coverage[30:60, 20:50] = 255
            np.save(os.path.join(paths["prep"], "test", "obj_v2.npy"), coverage)
            np.savez(os.path.join(paths["prep"], "test", "foliage.npz"), cls=np.array([1]), radius=np.array([2.0]), x=np.array([80.0]), y=np.array([80.0]))
            with open(os.path.join(paths["prep"], "test", "lines.json"), "w") as f:
                json.dump([], f)
            xs, ys = ri.frame_grid((0.0, 0.0, 100.0, 100.0), 1.0)
            reference = ri.Features("test", 1.0).reference(xs, ys)
        # the building's west wall at x = 20 m (cell 19.5 m) is an edge, its inside is not
        self.assertGreater(reference[45, 19:22].max(), 5 * abs(reference[45, 35]))
        self.assertGreater(reference[80, 76:85].max(), 0.0)


class LocateMeasureTest(unittest.TestCase):
    def test_displacement_where_it_is_drawn(self):
        base = (np.clip(smooth_field((300, 300), 11, sigma=2.0) * 400 + 128, 0, 255)).astype(np.uint8)
        texture = ndimage.zoom(base[50:100, 125:175], 4, order=1)
        info = ri.MapInfo("test", "/Game/Maps/Test/Minimap/Test_Minimap.Test_Minimap", (0.0, 0.0, 600.0, 600.0), (0.0, 0.0, 600.0, 600.0))
        with directories() as paths:
            write_bgra(os.path.join(paths["register"], "tex"), "Test_Minimap", np.dstack([base] * 3))
            write_bgra(os.path.join(paths["register"], "tex"), "Test_Seed", np.dstack([texture] * 3))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                ri.measure_locate({"test": info}, "test", "Test_Seed", (0.0, 0.0, 150.0, 150.0), [100.0], (0.0, 1.0, 0.0, 1.0))
        result = json.loads(output.getvalue().splitlines()[-1])
        # it shows (250, 100)-(350, 200): drawn over (0, 0)-(150, 150), its content lies 250 m west and 100 m north of itself
        self.assertEqual(result["orientation"], "rot0")
        for key, want in (("W", -250.0), ("E", -200.0), ("N", -100.0), ("S", -50.0)):
            self.assertAlmostEqual(result[key], want, delta=2.5)


if __name__ == "__main__":
    unittest.main()
