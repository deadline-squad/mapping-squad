"""publish_regions.py: copies region files next to the served volume layer and lists them in meta.json."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py"))

import build_region  # noqa: E402
import publish_regions  # noqa: E402

TRIANGLE = np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 1]]], np.float32)


class PublishRegionsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        os.makedirs(os.path.join(self.dir, "served", "jensen"))
        self.meta = os.path.join(self.dir, "served", "jensen", "meta.json")
        json.dump({"map": "Jensen", "volume": {"file": "volume.vcol", "bytes": 1}}, open(self.meta, "w"))

    def region(self, name, centre_x, centre_y):
        path = os.path.join(self.dir, name)
        square = (centre_x - 150, centre_y - 150, centre_x + 150, centre_y + 150)
        open(path, "wb").write(build_region.encode(TRIANGLE, square, 0.6))
        return path

    def publish(self, *paths):
        argv = sys.argv
        sys.argv = ["publish_regions.py", "jensen", os.path.join(self.dir, "served"), *paths]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                publish_regions.main()
        finally:
            sys.argv = argv
        return json.load(open(self.meta))["volume"]["regions"]

    def test_lists_the_square_of_each_file_and_backs_meta_up(self):
        regions = self.publish(self.region("region_221_-229.rtri", 221, -229))
        self.assertEqual(len(regions), 1)
        entry = regions[0]
        self.assertEqual(entry["file"], "regions/region_221_-229.rtri")
        self.assertEqual((entry["centre"], entry["radius"], entry["margin"]), ([221.0, -229.0], 150.0, 0.6))
        served = os.path.join(self.dir, "served", "jensen")
        self.assertEqual(entry["bytes"], os.path.getsize(os.path.join(served, entry["file"])))
        self.assertTrue(any(name.startswith("meta.json.bak.") and name.endswith("-regions") for name in os.listdir(served)))

    def test_a_republished_region_replaces_its_entry_and_others_stay(self):
        self.publish(self.region("a.rtri", 0, 0), self.region("b.rtri", 250, 0))
        regions = self.publish(self.region("a.rtri", 10, 0))
        self.assertEqual([(entry["file"], entry["centre"]) for entry in regions], [("regions/a.rtri", [10.0, 0.0]), ("regions/b.rtri", [250.0, 0.0])])

    def test_refuses_a_file_that_is_not_a_region(self):
        path = os.path.join(self.dir, "x.rtri")
        import gzip
        open(path, "wb").write(gzip.compress(b"NOPE" * 20))
        with self.assertRaises(SystemExit):
            self.publish(path)


if __name__ == "__main__":
    unittest.main()
