"""Tests of build_squadheight_only.py on a made-up SquadHeight export: python -m unittest test_build_squadheight_only"""

import json
import os
import tempfile
import unittest

import numpy as np
from PIL import Image

import build_squadheight_only
import heightmap_webp

META = {
    "map": "Mini",
    "exported_utc": "2026-06-12T11:11:24Z",
    "resolution_m": 1.0,
    "bounds_m": {"min_x": -2.0, "max_x": 3.0, "min_y": 5.0, "max_y": 7.0},
    "z_offset_m": -10.0,
    "png_meters_per_unit": 0.01,
}


def write_export(directory, levels):
    Image.fromarray(levels).save(os.path.join(directory, "heightmap.png"))
    json.dump(META, open(os.path.join(directory, "meta.json"), "w"))


class TerrainOnlyBuild(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = os.path.join(self.temp.name, "src")
        self.out = os.path.join(self.temp.name, "out")
        os.mkdir(self.source)
        # 3 rows (Y 5..7) by 6 columns (X -2..3), level 0..65535 spread over the grid
        self.levels = np.linspace(0, 65535, 18).astype(np.uint16).reshape(3, 6)

    def test_meta_labels_the_lower_provenance_and_has_no_game_sources(self):
        write_export(self.source, self.levels)
        build_squadheight_only.build(self.source, self.out, "Mini")
        meta = json.load(open(os.path.join(self.out, "meta.json")))
        self.assertEqual(meta["provenance"], "SquadHeight 1.3.0 (Mod SDK export), terrain only, not validated against server data")
        self.assertEqual(list(meta["sources"]), ["sdk_surface"])
        self.assertEqual(meta["stats"], {})
        self.assertNotIn("object_min_m", meta)
        self.assertNotIn("volume", meta)
        self.assertEqual((meta["width"], meta["height"], meta["resolution_m"]), (6, 3, 1.0))
        self.assertEqual(meta["bounds_m"], META["bounds_m"])

    def test_heights_are_the_export_heights_in_the_same_orientation(self):
        write_export(self.source, self.levels)
        build_squadheight_only.build(self.source, self.out, "Mini")
        meta = json.load(open(os.path.join(self.out, "meta.json")))
        expected = self.levels * META["png_meters_per_unit"] + META["z_offset_m"]
        png = np.asarray(Image.open(os.path.join(self.out, "heightmap.png")))
        self.assertLessEqual(np.abs(png * meta["z_step_m"] + meta["z_min_m"] - expected).max(), meta["z_step_m"])
        webp = heightmap_webp.decode(os.path.join(self.out, "heightmap.webp"))
        self.assertLessEqual(np.abs(webp * meta["webp"]["z_step_m"] + meta["z_min_m"] - expected).max(), meta["webp"]["z_step_m"])

    def test_image_that_does_not_match_the_bounds_is_refused(self):
        write_export(self.source, self.levels[:, :5])
        with self.assertRaises(ValueError):
            build_squadheight_only.build(self.source, self.out, "Mini")


if __name__ == "__main__":
    unittest.main()
