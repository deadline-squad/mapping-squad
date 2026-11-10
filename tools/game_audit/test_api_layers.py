"""Tests of the comparison rules of api_layers.py on made-up API answers and game layers (no network, no game data).

Run: python3 -m unittest discover -s tools/game_audit
"""
import unittest

import api_layers


def api_object(name, x=0.0, y=0.0, z=0.0, **shape):
    kinds = {"isSphere": False, "isBox": False, "isCapsule": False}
    return {"objectName": name, "location_x": x, "location_y": y, "location_z": z, **kinds, **shape}


def api_zone(object_name, flag, x, y, z, objects):
    return {"name": flag, "objectName": object_name, "location_x": x, "location_y": y, "location_z": z, "objects": objects}


def game_shape(kind, name="Shape", loc=(0.0, 0.0, 0.0), radius=None, extent=None, scale=(1.0, 1.0, 1.0), tilted=False):
    return {"kind": kind, "name": name, "loc": list(loc), "radius": radius, "extent": extent, "half_height": None, "scale": list(scale), "parent_tilted": tilted}


def game_zone(kind, name, loc, shapes, flag=None, **scalars):
    return {"type": kind, "name": name, "loc": list(loc), "shapes": shapes, "flag": flag, "scalars": scalars}


class Shapes(unittest.TestCase):
    def test_a_sphere_is_scaled_by_the_smallest_axis(self):
        shape = game_shape("SphereComponent", radius=6000.0, scale=(0.75, 1.0, 1.0))
        self.assertIsNone(api_layers.shape_difference(api_object("Sphere", isSphere=True, sphereRadius="4500.0"), shape))
        self.assertEqual(api_layers.shape_difference(api_object("Sphere", isSphere=True, sphereRadius="6000.0"), shape), "radius 6000 in the API, 4500 in the game")

    def test_a_negative_radius_of_the_right_size_is_named_as_negative(self):
        shape = game_shape("SphereComponent", radius=15000.0, scale=(31149.57, 31149.57, -1.57585875))
        difference = api_layers.shape_difference(api_object("Sphere", isSphere=True, sphereRadius=-23637.880859375), shape)
        self.assertEqual(difference, "radius -23637.9 in the API is negative, 23637.9 in the game")

    def test_a_box_compares_each_axis_with_both_scales(self):
        shape = game_shape("BoxComponent", extent={"X": 7500.0, "Y": 4000.0, "Z": 3000.0}, scale=(2.0, 1.0, 1.0))
        extent = {"extent_x": 7500, "extent_y": 4000, "extent_z": 3000, "scaling_x": 2, "scaling_y": 1, "scaling_z": 1}
        self.assertIsNone(api_layers.shape_difference(api_object("Box", isBox=True, boxExtent=extent), shape))
        self.assertIn("extent", api_layers.shape_difference(api_object("Box", isBox=True, boxExtent={**extent, "scaling_x": 1}), shape))

    def test_a_capsule_is_scaled_by_the_smaller_horizontal_axis(self):
        shape = game_shape("CapsuleComponent", radius=2500.0, scale=(1.25, 2.0, 5.0))
        self.assertIsNone(api_layers.shape_difference(api_object("Capsule", isCapsule=True, capsuleRadius="3125.0"), shape))
        self.assertEqual(api_layers.shape_difference(api_object("Capsule", isCapsule=True, capsuleRadius="5000.0"), shape), "capsule radius 5000 in the API, 3125 in the game")

    def test_another_kind_of_shape_is_a_difference(self):
        self.assertEqual(api_layers.shape_difference(api_object("Box", isBox=True, boxExtent={}), game_shape("SphereComponent", radius=100.0)), "kind SphereComponent")

    def test_a_size_the_level_does_not_set_is_not_compared(self):
        self.assertIsNone(api_layers.shape_difference(api_object("Sphere", isSphere=True, sphereRadius="3000.0"), game_shape("SphereComponent")))


class Zones(unittest.TestCase):
    GAME = {"zones": [
        game_zone("BP_CaptureZoneMain_C", "00-Team1 Main", (-100.0, 0.0, 0.0), [], flag="US Main"),
        game_zone("BP_CaptureZone_C", "01-Village", (1000.0, 2000.0, 300.0), [game_shape("SphereComponent", "Sphere", (1000.0, 2000.0, 300.0), radius=3000.0)], flag="Village"),
        game_zone("BP_CaptureZone_C", "02-Bunker", (5000.0, 0.0, 0.0), [game_shape("BoxComponent", "Box", (5000.0, 7305.4, 0.0), tilted=True)], flag="Bunker"),
        game_zone("BP_CaptureZone_C", "B2-Homestead", (9000.0, 0.0, 0.0), [], flag="Homestead"),
        game_zone("BP_CaptureZoneCluster_C", "A1-Cluster", (0.0, 0.0, 0.0), []),
    ]}
    API = {"objectives": {
        "00-Team1 Main": api_zone("00-Team1 Main", "Main", -100.0, 0.0, 0.0, []),
        "A1-Cluster": {"name": "A1-Cluster", "points": [
            api_zone("01-Village", "Village", 1000.004, 2000.0, 300.0, [api_object("Sphere", 1000.004, 2000.0, 300.0, isSphere=True, sphereRadius="3000.0")]),
            api_zone("02-Bunker", "Bunker", 5000.0, 0.0, 0.0, [api_object("Box", 5000.0, 0.0, 0.0, isBox=True, boxExtent={})]),
        ]},
        "lane": [api_zone("01-Village", "Village", 1000.004, 2000.0, 300.0, [])],
    }}

    def test_a_zone_listed_twice_in_the_objective_tree_counts_once(self):
        self.assertEqual(len(api_layers.api_zones(self.API["objectives"])), 3)

    def test_counts_positions_names_and_what_is_missing(self):
        result = api_layers.compare_zones(self.API, self.GAME)
        self.assertEqual((result["api"], result["game"], result["mains"]), (3, 3, 1))
        self.assertEqual(result["worst_position"], 0.004)
        self.assertEqual(result["not_in_api"], ["B2-Homestead"])
        self.assertEqual(result["not_in_game"], [])
        self.assertEqual(result["flag_names"], [["Main", "US Main"]])

    def test_a_capture_area_elsewhere_than_the_game_puts_it_is_listed_with_the_tilt(self):
        result = api_layers.compare_zones(self.API, self.GAME)
        self.assertEqual(result["shape_positions"], [{"zone": "02-Bunker", "shape": "Box", "cm": 7305.4, "zone_tilted": True}])

    def test_an_api_zone_under_another_name_is_matched_by_its_place_or_reported(self):
        renamed = {"objectives": [api_zone("Village Centre", "Village", 1000.0, 2000.0, 300.0, []), api_zone("Nowhere", "Nowhere", 77777.0, 0.0, 0.0, [])]}
        result = api_layers.compare_zones(renamed, self.GAME)
        self.assertEqual(result["not_in_game"], ["Nowhere"])
        self.assertNotIn("01-Village", result["not_in_api"])


class Protection(unittest.TestCase):
    GAME = {"protection": [
        game_zone("Gameplay_TeamZone_C", "Team1ProtectionZone", (0.0, 0.0, 0.0), [
            game_shape("BoxComponent", "DummyPresetCollision"),
            game_shape("SphereComponent", "Sphere", (-153601.5, -175253.7, -25426.3), radius=15000.0, scale=(31149.57, 31149.57, -1.57585875))], TeamId=1),
        game_zone("Gameplay_TeamZone_C", "Team2ProtectionZone", (0.0, 0.0, 0.0), [game_shape("SphereComponent", "Sphere", (185162.5, 173416.2, -20267.2), radius=15000.0)], TeamId=2, DeployableLockDistance=20000.0),
    ]}

    def api(self, radius_one, lock_two):
        return {"mapAssets": {"protectionZones": [
            {"displayName": "Team1 Protection Zone", "deployableLockDistance": 15000, "teamid": "1",
             "objects": [api_object("Sphere", -153601.515625, -175253.6875, -25426.287109375, isSphere=True, sphereRadius=radius_one)]},
            {"displayName": "Team2 Protection Zone", "deployableLockDistance": lock_two, "teamid": "2",
             "objects": [api_object("Sphere", 185162.484375, 173416.234375, -20267.201171875, isSphere=True, sphereRadius=15000)]},
        ]}}

    def test_zones_are_matched_by_team_and_the_lock_distance_defaults_to_the_blueprints(self):
        result = api_layers.compare_protection(self.api(23637.88, 20000), self.GAME, 15000.0)
        self.assertEqual(result, {"zones": 2, "lock": [], "shapes": [], "spheres": 2, "boxes": 0})

    def test_goose_bays_negative_radius_and_a_wrong_lock_distance_are_reported(self):
        result = api_layers.compare_protection(self.api(-23637.880859375, 15000), self.GAME, 15000.0)
        self.assertEqual(result["shapes"], ["Team1 Protection Zone: radius -23637.9 in the API is negative, 23637.9 in the game"])
        self.assertEqual(result["lock"], ["Team2 Protection Zone: lock distance 15000 in the API, 20000 in the game"])

    def test_a_zone_of_a_team_the_game_layer_has_none_for_is_reported(self):
        result = api_layers.compare_protection(self.api(23637.88, 20000), {"protection": self.GAME["protection"][:1]}, 15000.0)
        self.assertEqual(len(result["shapes"]), 1)
        self.assertIn("Team2 Protection Zone: no zone of that team", result["shapes"][0])


class Settings(unittest.TestCase):
    DATA = [
        {"Type": "BP_SQLayer_C", "Name": "Chora_AAS_v1", "Properties": {"GameMode": {"RowName": "AAS"}, "FactionsList": [
            {"Key": "x", "Value": {"Faction": {"AssetPathName": "/Game/Settings/Factions/USA.USA_LO_CombinedArms"}, "Types": [{"Key": "t", "Value": {"AssetPathName": "/Game/Settings/Factions/USA.USA_S_Armored"}}]}}]}},
        {"Type": "BP_SQLayerTeamConfig_C", "Name": "T0", "Properties": {"SpecificFactionSetup": {"AssetPathName": "/Game/F.USA_LO_CombinedArms"}, "Tickets": 300}},
        {"Type": "BP_SQLayerTeamConfig_C", "Name": "T1", "Properties": {"Index": "ESQTeam::Team_Two", "SpecificFactionSetup": {"AssetPathName": "/Game/F.RGF_LO_CombinedArms"}, "Tickets": 300}},
    ]

    def api(self, **changes):
        return {"gamemode": "AAS", "teamConfigs": {"team1": {"defaultFactionUnit": "USA_LO_CombinedArms", "tickets": 300}, "team2": {"defaultFactionUnit": "RGF_LO_CombinedArms", "tickets": 300}},
                "units": {"team1Units": [{"unitObjectName": "USA_LO_CombinedArms"}], "team2Units": [{"unitObjectName": "USA_S_Armored"}]}, **changes}

    def test_equal_settings_have_no_difference_and_the_units_are_counted(self):
        self.assertEqual(api_layers.compare_settings(self.api(), self.DATA), ([], 2, 2))

    def test_mode_tickets_and_units_are_each_reported(self):
        changed = self.api(gamemode="RAAS", units={"team1Units": [{"unitObjectName": "USA_LO_CombinedArms"}]})
        changed["teamConfigs"]["team2"]["tickets"] = 250
        differences, _, _ = api_layers.compare_settings(changed, self.DATA)
        self.assertEqual(len(differences), 3)
        self.assertIn("game mode RAAS in the API, AAS in the game", differences)
        self.assertIn("team 2 tickets 250 in the API, 300 in the game", differences)


class Layer(unittest.TestCase):
    def test_a_layer_the_build_lacks_and_one_off_the_list_are_said_in_words(self):
        api = {"rawName": "Chora_AAS_v1", "mapId": "Chora"}
        result = api_layers.compare_layer("Chora_AAS_v1", api, False, None, None, {"Chora"}, 15000.0)
        self.assertEqual(result["issues"], ["not in the API's layer list of its map", "no such layer in the game build"])

    def test_the_summary_counts_over_the_compared_layers(self):
        game = {"MapTextureCornerZero": [-246400.0, -266400.0, 0.0], "MapTextureCornerOne": [159990.0, 140000.0, 0.0], "texture": "Texture2D'Chora_Minimap'", **Zones.GAME, **Protection.GAME}
        api = {"rawName": "Chora_AAS_v1", "mapId": "Chora", "mapTexture": "Chora_Minimap", **Zones.API, **Protection().api(23637.88, 20000), **Settings().api(),
               "mapTextureCorners": [{"location_x": -246400.0, "location_y": -266400.0}, {"location_x": 159990.004, "location_y": 140000.0}]}
        result = api_layers.compare_layer("Chora_AAS_v1", api, True, game, Settings.DATA, {"Chora"}, 15000.0)
        self.assertEqual(result["corners"], 0.004)
        lines = api_layers.summary({"Chora_AAS_v1": result, "Chora_AAS_v9": {"issues": ["the API answers 404"]}})
        self.assertEqual(lines[0], "2 layers, 0 without a difference")
        self.assertEqual(lines[1], "answered and listed by the API: 1")
        self.assertIn("3 in the API, 4 in the game", lines[3])
        self.assertIn("protection zones: 2 (2 spheres, 0 boxes), 0 lock distances differ, 0 shapes differ", lines[4])


if __name__ == "__main__":
    unittest.main()
