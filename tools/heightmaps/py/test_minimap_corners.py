"""Tests of minimap_corners.table on made-up layer records (no game data needed).

Run: python -m unittest test_minimap_corners   (in tools/heightmaps/py)
"""

import json
import os
import tempfile
import unittest

import minimap_corners


def record(layer, c0, c1):
    return {"layer": layer, "c0": {"loc": {"X": c0[0] * 100, "Y": c0[1] * 100}}, "c1": {"loc": {"X": c1[0] * 100, "Y": c1[1] * 100}}}


class TableTest(unittest.TestCase):
    def table(self, records):
        with tempfile.TemporaryDirectory() as folder:
            corners, game = os.path.join(folder, "corners.ndjson"), os.path.join(folder, "game.json")
            with open(corners, "w") as out:
                out.write("".join(json.dumps(r) + "\n" for r in records))
            minimap_corners.table(corners, game)
            return json.load(open(game))

    def test_modal_corners_of_the_regular_layers_and_the_skirmish_variant(self):
        base = "SquadGame/Content/Maps/Chora/Gameplay_Layers/"
        result = self.table([
            record(base + "Chora_AAS_v1.umap", (-2464, -2664), (1599.9, 1400)),
            record(base + "Chora_RAAS_v1.umap", (-2464, -2664), (1599.9, 1400)),
            record(base + "Chora_Skirmish_v1.umap", (-1456.84, -1442.01), (163.16, 177.99)),
        ])
        self.assertEqual(result["Chora"]["min"], [-2464.0, -2664.0])
        self.assertEqual(result["Chora"]["max"], [1599.9, 1400.0])
        self.assertEqual([v["layer"] for v in result["Chora"]["variants"]], ["Chora_Skirmish_v1"])

    def test_swapped_corners_give_the_same_extent_and_plugin_maps_use_their_plugin_name(self):
        result = self.table([
            record("SquadGame/Content/Maps/Fools_Road/Gameplay_Layers/FoolsRoad_AAS_v1.umap", (448.05, 448.05), (-1325.77, -1325.77)),
            record("SquadGame/Plugins/Al_Basrah/Content/Maps/Gameplay_Layers/AlBasrah_AAS_v1.umap", (-2000, -2000), (2000, 2000)),
        ])
        self.assertEqual(result["FoolsRoad"]["min"], [-1325.77, -1325.77])
        self.assertEqual(result["AlBasrah"]["max"], [2000.0, 2000.0])


if __name__ == "__main__":
    unittest.main()
