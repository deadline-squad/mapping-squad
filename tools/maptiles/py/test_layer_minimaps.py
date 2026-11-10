import contextlib
import io
import json
import os
import re
import struct
import tempfile
import unittest

from PIL import Image

import layer_minimaps as lm

LEVELS = "\n".join([
    "SquadGame/Content/Maps/Narva/Gameplay_Layers/Narva_AAS_v1.umap\t/Game/Maps/Narva/Minimap/Narva_Minimap.Narva_Minimap\t-138970.69\t139792.52\t141029.38\t-140207.44",
    "SquadGame/Content/Maps/Narva/Gameplay_Layers/Narva_RAAS_v1.umap\t/Game/Maps/Narva/Minimap/Narva_Minimap.Narva_Minimap\t-138970.69\t139792.52\t141029.38\t-140207.44",
    "SquadGame/Content/Maps/Narva/Gameplay_Layers/Narva_Skirmish_v1.umap\t/Game/Maps/Narva/Minimap/Narva_Minimap.Narva_Minimap\t-138970.69\t139792.52\t141029.38\t-140207.44",
    "SquadGame/Plugins/Expansions/BlackCoast/Content/Maps/Gameplay_Layers/BlackCoast_AAS_v1.umap\t/BlackCoast/Maps/Minimap/Black_Coast_Minimap_fix.Black_Coast_Minimap_fix\t-229999.52\t-212746.78\t229998.47\t247251.06",
    "SquadGame/Plugins/Expansions/BlackCoast/Content/Maps/Gameplay_Layers/BlackCoast_RAAS_v1.umap\t/BlackCoast/Maps/Minimap/Black_Coast_Minimap_fix.Black_Coast_Minimap_fix\t-229999.52\t-212746.78\t229998.47\t247251.06",
    "SquadGame/Plugins/Expansions/BlackCoast/Content/Maps/Gameplay_Layers/BlackCoast_Seed_v1.umap\t/BlackCoast/Maps/Minimap/Black_Coast_Minimap_Seed_v1.Black_Coast_Minimap_Seed_v1\t5000\t-20000\t-95000\t-120000",
    "SquadGame/Content/Maps/Skorpo/Gameplay_Layers/Skorpo_Invasion_v1.umap\t/Game/Maps/Skorpo/Minimap/Skorpo_Minimap_RAAS_v3_fix.Skorpo_Minimap_RAAS_v3_fix\t-360150\t-329300\t324850\t357608",
    "SquadGame/Content/Maps/Skorpo/Gameplay_Layers/Skorpo_RAAS_v1.umap\t/Game/Maps/Skorpo/Minimap/Skorpo_Minimap_RAAS_v3_fix.Skorpo_Minimap_RAAS_v3_fix\t-360150\t-329300\t324850\t357608",
    "SquadGame/Content/Maps/Skorpo/Gameplay_Layers/Skorpo_Invasion_v2.umap\t/Game/Maps/Skorpo/Minimap/Skorpo_Minimap_RAAS_v3_fix.Skorpo_Minimap_RAAS_v3_fix\t-360150\t-329300\t324850\t357608",
    "SquadGame/Content/Maps/Broken/Gameplay_Layers/Broken_AAS_v1.umap\tno world settings",
    "SquadGame/Content/Maps/Broken/Gameplay_Layers/Broken_AAS_v2.umap\tFAILED Exception: x",
    "SquadGame/Content/Maps/Broken/Gameplay_Layers/Broken_AAS_v3.umap\t/Game/Maps/Broken/Minimap/B.B\t?\t?\t0\t0",
])

NARVA_SKIRMISH = (-37000.0, -96000.0, 70000.0, 11000.0)
BLACKCOAST_SEED = (-95000.0, -120000.0, 5000.0, -20000.0)


def layer_data(layer, world_path, texture=None, corners=None, valid=1):
    """Exports of a layer data asset as the extractor's dumpall writes them (a BP_SQLayer and its team configs)."""
    properties = {"LevelId": layer.split("_")[0], "Worlds": [{"AssetPathName": world_path, "SubPathString": ""}]}
    if texture is not None:
        properties["OveriddenMinimapTexture"] = {"AssetPathName": texture, "SubPathString": ""}
    if corners is not None:
        x0, y0, x1, y1 = corners
        properties["MinimapCornersPosition"] = {"Min": {"X": x0, "Y": y0}, "Max": {"X": x1, "Y": y1}, "bIsValid": valid}
    return [{"Type": "BP_SQLayer_C", "Name": layer, "Properties": properties},
            {"Type": "BP_SQLayerTeamConfig_C", "Name": "BP_SQLayerTeamConfig_C_0", "Properties": {"Index": 1}}]


OVERRIDES = {
    "BlackCoast_Seed_v1": lm.layer_override(layer_data(
        "BlackCoast_Seed_v1", "/BlackCoast/Maps/Gameplay_Layers/BlackCoast_Seed_v1.BlackCoast_Seed_v1",
        "/BlackCoast/Maps/Minimap/BlackCoast_Seed_v1.T_BlackCoast_Seed_v1", BLACKCOAST_SEED))[1],
    "Narva_Skirmish_v1": lm.layer_override(layer_data(
        "Narva_Skirmish_v1", "/Game/Maps/Narva/Gameplay_Layers/Narva_Skirmish_v1.Narva_Skirmish_v1",
        "/Game/Maps/Narva/Minimap/Narva_Minimap_Skirmish_v1.Narva_Minimap_Skirmish_v1", NARVA_SKIRMISH))[1],
    "Skorpo_Invasion_v1": lm.layer_override(layer_data(
        "Skorpo_Invasion_v1", "/Game/Maps/Skorpo/Gameplay_Layers/Skorpo_Invasion_v1.Skorpo_Invasion_v1",
        "/Game/Maps/Skorpo/Minimap/Skorpo_Minimap_RAAS_v3_fix.Skorpo_Minimap_RAAS_v3_fix",
        (-380000.0, -380000.0, 380000.0, 380000.0)))[1],
}


def block(c0, c1, selectors):
    indices = sum(s << (2 * i) for i, s in enumerate(selectors))
    return struct.pack("<HHI", c0, c1, indices)


class LevelTable(unittest.TestCase):
    def test_parse_keeps_levels_with_a_texture_and_both_corners(self):
        levels = lm.parse_layer_table(LEVELS)
        self.assertEqual(len(levels), 9)
        self.assertNotIn("Broken_AAS_v3", levels)

    def test_rectangle_is_min_max_whatever_the_corner_order(self):
        levels = lm.parse_layer_table(LEVELS)
        self.assertEqual(levels["BlackCoast_Seed_v1"].rect, BLACKCOAST_SEED)
        self.assertEqual(levels["Narva_AAS_v1"].rect, (-138970.69, -140207.44, 141029.38, 139792.52))
        self.assertEqual(levels["BlackCoast_Seed_v1"].texture,
                         "/BlackCoast/Maps/Minimap/Black_Coast_Minimap_Seed_v1.Black_Coast_Minimap_Seed_v1")


class LayerData(unittest.TestCase):
    def test_texture_and_valid_corners(self):
        layer, override = lm.layer_override(layer_data(
            "Narva_Skirmish_v1", "/Game/Maps/Narva/Gameplay_Layers/Narva_Skirmish_v1.Narva_Skirmish_v1",
            "/Game/Maps/Narva/Minimap/Narva_Minimap_Skirmish_v1.Narva_Minimap_Skirmish_v1", NARVA_SKIRMISH))
        self.assertEqual(layer, "Narva_Skirmish_v1")
        self.assertEqual(override, lm.Override("/Game/Maps/Narva/Minimap/Narva_Minimap_Skirmish_v1.Narva_Minimap_Skirmish_v1",
                                               NARVA_SKIRMISH))

    def test_corners_count_only_when_valid(self):
        _, override = lm.layer_override(layer_data("Map_AAS_v1", "/Game/Maps/Map/Gameplay_Layers/Map_AAS_v1.Map_AAS_v1",
                                                   corners=(0.0, 0.0, 1.0, 1.0), valid=0))
        self.assertEqual(override, lm.Override(None, None))

    def test_swapped_corners_give_the_same_rectangle(self):
        # Gorodok_Destruction_v1 gives its Y corners in the other order
        _, override = lm.layer_override(layer_data(
            "Gorodok_Destruction_v1", "/Game/Maps/Gorodok/Gameplay_Layers/Gorodok_Destruction_v1.Gorodok_Destruction_v1",
            corners=(-203199.0, 203200.0, 203201.0, -203200.0)))
        self.assertEqual(override.rect, (-203199.0, -203200.0, 203201.0, 203200.0))

    def test_none_texture_keeps_the_level_texture(self):
        _, override = lm.layer_override(layer_data("Map_AAS_v1", "/Game/Maps/Map/Gameplay_Layers/Map_AAS_v1.Map_AAS_v1", "None"))
        self.assertIsNone(override.texture)

    def test_a_data_table_is_not_a_layer(self):
        self.assertIsNone(lm.layer_override([{"Type": "DataTable", "Name": "GooseBay_LayerTable", "Properties": {}}]))

    def test_read_layer_data_walks_the_dump(self):
        with tempfile.TemporaryDirectory() as root:
            folder = os.path.join(root, "SquadGame/Content/Maps/Narva/Gameplay_Layer_Data")
            os.makedirs(folder)
            with open(os.path.join(folder, "Narva_Skirmish_v1.uasset.json"), "w") as f:
                json.dump(layer_data("Narva_Skirmish_v1", "/Game/Maps/Narva/Gameplay_Layers/Narva_Skirmish_v1.Narva_Skirmish_v1",
                                     corners=NARVA_SKIRMISH), f)
            with open(os.path.join(folder, "Narva_LayerTable.uasset.json"), "w") as f:
                json.dump([{"Type": "DataTable", "Name": "Narva_LayerTable", "Properties": {}}], f)
            self.assertEqual(lm.read_layer_data(root), {"Narva_Skirmish_v1": lm.Override(None, NARVA_SKIRMISH)})


class LayerMinimaps(unittest.TestCase):
    def setUp(self):
        self.table = lm.layer_table(lm.parse_layer_table(LEVELS), OVERRIDES)

    def test_the_layer_data_texture_replaces_the_level_texture(self):
        # Black Coast Seed v1: the level names Black_Coast_Minimap_Seed_v1, the game shows T_BlackCoast_Seed_v1
        found = lm.find_layer_minimaps(self.table)
        self.assertEqual(found["BlackCoast_Seed_v1"],
                         lm.Minimap("/BlackCoast/Maps/Minimap/BlackCoast_Seed_v1.T_BlackCoast_Seed_v1", BLACKCOAST_SEED))

    def test_an_override_on_a_level_with_the_map_texture_is_a_layer_minimap_at_its_own_corners(self):
        found = lm.find_layer_minimaps(self.table)
        self.assertEqual(found["Narva_Skirmish_v1"],
                         lm.Minimap("/Game/Maps/Narva/Minimap/Narva_Minimap_Skirmish_v1.Narva_Minimap_Skirmish_v1", NARVA_SKIRMISH))

    def test_layers_with_the_map_texture_have_no_picture_of_their_own(self):
        found = lm.find_layer_minimaps(self.table)
        self.assertEqual(sorted(found), ["BlackCoast_Seed_v1", "Narva_Skirmish_v1"])

    def test_the_map_texture_over_other_corners_is_reported_not_served(self):
        self.assertEqual(lm.base_texture_elsewhere(self.table),
                         {"Skorpo_Invasion_v1": lm.Minimap("/Game/Maps/Skorpo/Minimap/Skorpo_Minimap_RAAS_v3_fix.Skorpo_Minimap_RAAS_v3_fix",
                                                           (-380000.0, -380000.0, 380000.0, 380000.0))})

    def test_layer_without_layer_data_keeps_its_level(self):
        self.assertEqual(self.table["Narva_AAS_v1"], lm.parse_layer_table(LEVELS)["Narva_AAS_v1"])

    def test_base_tie_goes_to_the_first_path(self):
        table = {"Map_A": lm.Minimap("/Game/B.B", (0, 0, 1, 1)), "Map_B": lm.Minimap("/Game/A.A", (0, 0, 1, 1))}
        self.assertEqual(lm.find_layer_minimaps(table), {"Map_A": table["Map_A"]})


class Names(unittest.TestCase):
    def test_folder_name_is_the_object_name_in_lower_case(self):
        self.assertEqual(lm.folder_name("/BlackCoast/Maps/Minimap/BlackCoast_Seed_v1.T_BlackCoast_Seed_v1"), "t_blackcoast_seed_v1")

    def test_package_name(self):
        self.assertEqual(lm.package_name("/BlackCoast/Maps/Minimap/BlackCoast_Seed_v1.T_BlackCoast_Seed_v1"), "BlackCoast_Seed_v1")

    def test_pak_pattern_matches_game_and_plugin_packages_only(self):
        pattern = re.compile(lm.pak_pattern([
            "/BlackCoast/Maps/Minimap/BlackCoast_Seed_v1.T_BlackCoast_Seed_v1",
            "/Game/Maps/Narva/Minimap/Narva_Minimap_Skirmish_v1.Narva_Minimap_Skirmish_v1",
        ]))
        self.assertTrue(pattern.search("SquadGame/Plugins/Expansions/BlackCoast/Content/Maps/Minimap/BlackCoast_Seed_v1.uasset"))
        self.assertTrue(pattern.search("SquadGame/Content/Maps/Narva/Minimap/Narva_Minimap_Skirmish_v1.uasset"))
        self.assertFalse(pattern.search("SquadGame/Content/Maps/Narva/Minimap/Narva_Minimap.uasset"))
        self.assertFalse(pattern.search("SquadGame/Plugins/Expansions/BlackCoast/Content/Maps/Gameplay_Layer_Data/BlackCoast_Seed_v1.uasset"))

    def test_manifest_entry_in_metres(self):
        minimap = lm.Minimap("/Game/Maps/Yehorivka/Minimap/Yehorivka_Minimap_Skirmish_v2_fix.Yehorivka_Minimap_Skirmish_v2_fix",
                             (-240000.0, -32677.357, -24000.0, 183322.66))
        self.assertEqual(lm.manifest_entry(minimap, "yehorivka_minimap_skirmish_v2_fix", 4096), {
            "texture": "Yehorivka_Minimap_Skirmish_v2_fix", "folder": "yehorivka_minimap_skirmish_v2_fix", "size": 4096,
            "min": [-2400.0, -326.77357], "max": [-240.0, 1833.2266]})


class Build(unittest.TestCase):
    def test_manifest_keyed_by_layer_with_the_game_texture_and_corners(self):
        with tempfile.TemporaryDirectory() as root:
            layers_path = os.path.join(root, "layers.tsv")
            with open(layers_path, "w") as f:
                f.write(LEVELS)
            data_dir = os.path.join(root, "layerdata")
            os.makedirs(data_dir)
            with open(os.path.join(data_dir, "BlackCoast_Seed_v1.uasset.json"), "w") as f:
                json.dump(layer_data("BlackCoast_Seed_v1", "/BlackCoast/Maps/Gameplay_Layers/BlackCoast_Seed_v1.BlackCoast_Seed_v1",
                                     "/BlackCoast/Maps/Minimap/BlackCoast_Seed_v1.T_BlackCoast_Seed_v1", BLACKCOAST_SEED), f)
            texture_dir = os.path.join(root, "tex")
            os.makedirs(texture_dir)
            with open(os.path.join(texture_dir, "BlackCoast_Seed_v1.PF_B8G8R8A8.4x4.bin"), "wb") as f:
                f.write(bytes([10, 20, 30, 255]) * 16)
            manifest_path = os.path.join(root, "appmanifest_393380.acf")
            with open(manifest_path, "w") as f:
                f.write('"AppState"\n{\n\t"buildid"\t\t"26234431"\n}')
            tiles = os.path.join(root, "tiles")
            with contextlib.redirect_stdout(io.StringIO()):
                lm.build(layers_path, data_dir, texture_dir, manifest_path, tiles)
            with open(os.path.join(tiles, "layer-minimaps.json")) as f:
                manifest = json.load(f)
            self.assertEqual(manifest["build"], "26234431")
            self.assertEqual(manifest["layers"], {"BlackCoast_Seed_v1": {
                "texture": "T_BlackCoast_Seed_v1", "folder": "t_blackcoast_seed_v1", "size": 4,
                "min": [-950.0, -1200.0], "max": [50.0, -200.0]}})
            with Image.open(os.path.join(tiles, "t_blackcoast_seed_v1", "0", "0_0.webp")) as image:
                self.assertEqual(image.size, (4, 4))

    def test_a_missing_texture_stops_the_build(self):
        with tempfile.TemporaryDirectory() as root:
            layers_path = os.path.join(root, "layers.tsv")
            with open(layers_path, "w") as f:
                f.write(LEVELS)
            os.makedirs(os.path.join(root, "layerdata"))
            os.makedirs(os.path.join(root, "tex"))
            with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
                lm.build(layers_path, os.path.join(root, "layerdata"), os.path.join(root, "tex"), "unused", os.path.join(root, "tiles"))


class Decoding(unittest.TestCase):
    def test_four_colour_block(self):
        data = block(0xF800, 0x001F, [0, 1, 2, 3] * 4)
        image = lm.decode_bc1(data, 4, 4)
        self.assertEqual(image.shape, (4, 4, 3))
        self.assertEqual(image[0, 0].tolist(), [255, 0, 0])
        self.assertEqual(image[0, 1].tolist(), [0, 0, 255])
        self.assertEqual(image[0, 2].tolist(), [170, 0, 85])
        self.assertEqual(image[0, 3].tolist(), [85, 0, 170])

    def test_three_colour_block_has_midpoint_and_black(self):
        data = block(0x001F, 0xF800, [2, 3] * 8)
        image = lm.decode_bc1(data, 4, 4)
        self.assertEqual(image[0, 0].tolist(), [127, 0, 127])
        self.assertEqual(image[0, 1].tolist(), [0, 0, 0])

    def test_endpoint_expansion_reaches_full_range(self):
        image = lm.decode_bc1(block(0xFFFF, 0x0000, [0] * 16), 4, 4)
        self.assertEqual(image[0, 0].tolist(), [255, 255, 255])

    def test_blocks_are_placed_row_major(self):
        red = block(0xF800, 0, [0] * 16)
        green = block(0x07E0, 0, [0] * 16)
        blue = block(0x001F, 0, [0] * 16)
        white = block(0xFFFF, 0, [0] * 16)
        image = lm.decode_bc1(red + green + blue + white, 8, 8)
        self.assertEqual(image[0, 0].tolist(), [255, 0, 0])
        self.assertEqual(image[0, 4].tolist(), [0, 255, 0])
        self.assertEqual(image[4, 0].tolist(), [0, 0, 255])
        self.assertEqual(image[7, 7].tolist(), [255, 255, 255])

    def test_bgra_gives_rgb(self):
        data = bytes([10, 20, 30, 255]) * 4
        image = lm.decode_bgra(data, 2, 2)
        self.assertEqual(image.shape, (2, 2, 3))
        self.assertEqual(image[1, 1].tolist(), [30, 20, 10])

    def test_unknown_format_is_rejected(self):
        with self.assertRaises(ValueError):
            lm.decode_texture(b"", "PF_BC7", 4, 4)


class RawNames(unittest.TestCase):
    def test_raw_name(self):
        self.assertEqual(lm.parse_raw_name("Black_Coast_Minimap_Seed_v1.PF_B8G8R8A8.2048x2048.bin"),
                         ("Black_Coast_Minimap_Seed_v1", "PF_B8G8R8A8", 2048, 2048))

    def test_bad_raw_name(self):
        with self.assertRaises(ValueError):
            lm.parse_raw_name("notes.txt")

    def test_client_build(self):
        self.assertEqual(lm.client_build('"AppState"\n{\n\t"buildid"\t\t"26234431"\n\t"TargetBuildID"\t\t"0"\n}'), "26234431")


if __name__ == "__main__":
    unittest.main()
