"""Tests of fob_radius.py on a made-up dump (no game data needed).

Run: python3 -m unittest discover -s tools/game_audit
"""
import json
import os
import tempfile
import unittest

import fob_radius

TABLE = [{"Type": "DataTable", "Name": "DT_FOBExclusionRadius", "Rows": {
    "01_Small": {"FOBExclusionRadius_4_DBB2C67F": 30000.0, "FOBConstructionRadius_6_A39C8AC4": 15000.0, "DisplayName_9_9545AD4C": {"SourceString": "Small FOB Radius"}},
    "02_Medium": {"FOBExclusionRadius_4_DBB2C67F": 40000.0, "FOBConstructionRadius_6_A39C8AC4": 15000.0, "DisplayName_9_9545AD4C": {"SourceString": "Medium FOB Radius"}},
}}]
LAYER_CLASS = [{"Type": "BlueprintGeneratedClass", "Name": "BP_SQLayer_C"},
               {"Type": "BP_SQLayer_C", "Name": "Default__BP_SQLayer_C", "Properties": {"FOBRadius": {"DataTable": {"ObjectName": "DataTable'DT_FOBExclusionRadius'"}, "RowName": "02_Medium"}}}]


def layer(name, row=None):
    properties = {"GameMode": {"RowName": "RAAS"}}
    if row:
        properties["FOBRadius"] = {"RowName": row}
    return [{"Type": "BP_SQLayer_C", "Name": name, "Properties": properties}, {"Type": "BP_SQLayerTeamConfig_C", "Name": "BP_SQLayerTeamConfig_C_0", "Properties": {}}]


class Rows(unittest.TestCase):
    def test_the_rows_are_metres_under_the_plain_field_names(self):
        self.assertEqual(fob_radius.rows(TABLE), {"01_Small": {"exclusion_m": 300.0, "construction_m": 150.0}, "02_Medium": {"exclusion_m": 400.0, "construction_m": 150.0}})

    def test_the_default_row_is_the_class_default(self):
        self.assertEqual(fob_radius.default_row(LAYER_CLASS), "02_Medium")

    def test_a_layer_keeps_the_default_unless_its_asset_names_a_row(self):
        self.assertEqual(fob_radius.layer_row(layer("AlBasrah_RAAS_v1"), "02_Medium"), ("AlBasrah_RAAS_v1", "02_Medium"))
        self.assertEqual(fob_radius.layer_row(layer("AlBasrah_RAAS_v3", "01_Small"), "02_Medium"), ("AlBasrah_RAAS_v3", "01_Small"))

    def test_a_layer_table_is_not_a_layer(self):
        self.assertIsNone(fob_radius.layer_row([{"Type": "DataTable", "Name": "AlBasrah_LayerTable", "Rows": {}}], "02_Medium"))


class Read(unittest.TestCase):
    def test_a_dump_gives_the_table_the_default_and_every_layer_sorted(self):
        with tempfile.TemporaryDirectory() as root:
            assets = {
                fob_radius.TABLE: TABLE, fob_radius.LAYER_CLASS: LAYER_CLASS,
                "SquadGame/Plugins/Al_Basrah/Content/Maps/Gameplay_Layer_Data/AlBasrah_RAAS_v3.uasset.json": layer("AlBasrah_RAAS_v3", "01_Small"),
                "SquadGame/Plugins/Al_Basrah/Content/Maps/Gameplay_Layer_Data/AlBasrah_LayerTable.uasset.json": [{"Type": "DataTable", "Name": "AlBasrah_LayerTable", "Rows": {}}],
                "SquadGame/Content/Maps/Anvil/Gameplay_Layer_Data/Anvil_AAS_v1.uasset.json": layer("Anvil_AAS_v1"),
            }
            for path, exports in assets.items():
                os.makedirs(os.path.dirname(os.path.join(root, path)), exist_ok=True)
                with open(os.path.join(root, path), "w", encoding="utf-8") as out:
                    json.dump(exports, out)
            result = fob_radius.read(root)
        self.assertEqual(result["default_row"], "02_Medium")
        self.assertEqual(list(result["layers"].items()), [("AlBasrah_RAAS_v3", "01_Small"), ("Anvil_AAS_v1", "02_Medium")])
        self.assertEqual(result["rows"]["01_Small"]["exclusion_m"], 300.0)


if __name__ == "__main__":
    unittest.main()
