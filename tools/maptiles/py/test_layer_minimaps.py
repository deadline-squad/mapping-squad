import struct
import unittest


import layer_minimaps as lm

TABLE = "\n".join([
    "SquadGame/Content/Maps/Mutaha/Gameplay_Layers/Mutaha_AAS_v1.umap\t/Game/Maps/Mutaha/Minimap/Mutaha_Minimap.Mutaha_Minimap\t0\t0\t1\t1",
    "SquadGame/Content/Maps/Mutaha/Gameplay_Layers/Mutaha_RAAS_v1.umap\t/Game/Maps/Mutaha/Minimap/Mutaha_Minimap.Mutaha_Minimap\t0\t0\t1\t1",
    "SquadGame/Content/Maps/Mutaha/Gameplay_Layers/Mutaha_Seed_v1.umap\t/Game/Maps/Mutaha/Minimap/Mutaha_Minimap_Seed_v1.Mutaha_Minimap_Seed_v1\t0\t0\t1\t1",
    "SquadGame/Content/Maps/Sumari/Gameplay_Layers/Sumari_AAS_v1.umap\t/Game/Maps/Sumari/Minimap/Sumari_Minimap.Sumari_Minimap\t0\t0\t1\t1",
    "SquadGame/Content/Maps/Sumari/Gameplay_Layers/Sumari_Skirmish_v1.umap\t/Game/Maps/Sumari/Minimap/Sumari_Minimap.Sumari_Minimap\t5\t5\t6\t6",
    "SquadGame/Content/Maps/Broken/Gameplay_Layers/Broken_AAS_v1.umap\tno world settings",
    "SquadGame/Content/Maps/Broken/Gameplay_Layers/Broken_AAS_v2.umap\tFAILED Exception: x",
])


def block(c0, c1, selectors):
    indices = sum(s << (2 * i) for i, s in enumerate(selectors))
    return struct.pack("<HHI", c0, c1, indices)


class LayerTable(unittest.TestCase):
    def test_parse_skips_rows_without_texture(self):
        rows = lm.parse_layer_table(TABLE)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[2], ("Mutaha_Seed_v1", "Mutaha_Minimap_Seed_v1"))

    def test_layer_minimap_is_a_texture_other_than_the_base(self):
        found = lm.find_layer_minimaps(lm.parse_layer_table(TABLE))
        self.assertEqual(found, {"Mutaha_Minimap_Seed_v1": ["Mutaha_Seed_v1"]})

    def test_same_texture_with_other_corners_is_not_a_layer_minimap(self):
        rows = [("Sumari_AAS_v1", "Sumari_Minimap"), ("Sumari_Skirmish_v1", "Sumari_Minimap")]
        self.assertEqual(lm.find_layer_minimaps(rows), {})

    def test_base_tie_goes_to_the_first_name(self):
        rows = [("Map_A", "B_Tex"), ("Map_B", "A_Tex")]
        self.assertEqual(lm.find_layer_minimaps(rows), {"B_Tex": ["Map_A"]})

    def test_texture_shared_by_several_layers_lists_all_sorted(self):
        rows = [("Map_AAS", "Base"), ("Map_RAAS", "Base"), ("Map_Seed_v2", "Fine"), ("Map_Seed_v1", "Fine")]
        self.assertEqual(lm.find_layer_minimaps(rows), {"Fine": ["Map_Seed_v1", "Map_Seed_v2"]})

    def test_folder_name_is_lower_case(self):
        self.assertEqual(lm.folder_name("T_AlBasrah_Minimap_Seed_v1"), "t_albasrah_minimap_seed_v1")


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


class Names(unittest.TestCase):
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
