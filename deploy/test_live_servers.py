"""live_servers.py: the faction ID from the site's label and the feed's server. Run: python3 -m unittest test_live_servers.py"""
import json
import os
import tempfile
import unittest

import live_servers

UNITS = [
    {"factionID": "AFU", "factionName": "Armed Forces of Ukraine"},
    {"factionID": "AFU", "factionName": "Armed Forces of Ukraine"},
    {"factionID": "GFI", "factionName": "Ground Forces of Iran"},
]
LAYER = {"units": {"team1Units": UNITS, "team2Units": [{"factionID": "RGF", "factionName": "Russian Ground Forces"}]}}
STATUS = {
    "name": "[RU] Deadline", "map": "AlBasrah_RAAS_v1", "players": 87, "max": 100, "queue": 3,
    "teams": {"1": {"faction": "Armed Forces of Ukraine", "players": 44}, "2": {"faction": "Russian Ground Forces", "players": 43}},
}


class FactionId(unittest.TestCase):
    def test_display_name(self):
        self.assertEqual(live_servers.faction_id("Armed Forces of Ukraine", UNITS), "AFU")
        self.assertEqual(live_servers.faction_id("armed forces of ukraine", UNITS), "AFU")

    def test_upper_cased_id_of_a_faction_the_site_has_no_name_for(self):
        self.assertEqual(live_servers.faction_id("GFI", UNITS), "GFI")

    def test_faction_the_layer_does_not_offer(self):
        self.assertIsNone(live_servers.faction_id("Russian Ground Forces", UNITS))
        self.assertIsNone(live_servers.faction_id(None, UNITS))
        self.assertIsNone(live_servers.faction_id("", UNITS))


class ServerEntry(unittest.TestCase):
    def test_server_with_both_teams(self):
        self.assertEqual(live_servers.server_entry(STATUS, LAYER), {
            "id": "deadline",
            "attributes": {"name": "[RU] Deadline", "players": 87, "maxPlayers": 100, "details": {"map": "AlBasrah_RAAS_v1"}},
            "team1": "AFU",
            "team2": "RGF",
        })

    def test_team_whose_faction_is_not_resolved_is_left_out(self):
        teams = {"1": {"faction": "Armed Forces of Ukraine"}, "2": {"faction": None}}
        entry = live_servers.server_entry({**STATUS, "teams": teams}, LAYER)
        self.assertEqual(entry["team1"], "AFU")
        self.assertNotIn("team2", entry)

    def test_layer_unknown_to_the_api_lists_the_server_without_teams(self):
        entry = live_servers.server_entry(STATUS, None)
        self.assertEqual(entry["attributes"]["details"]["map"], "AlBasrah_RAAS_v1")
        self.assertNotIn("team1", entry)
        self.assertNotIn("team2", entry)

    def test_no_server_while_no_layer_is_played(self):
        self.assertIsNone(live_servers.server_entry({**STATUS, "map": None}, None))
        self.assertIsNone(live_servers.server_entry({"name": None, "map": None, "teams": {}}, None))


class WriteFeed(unittest.TestCase):
    def test_feed_is_replaced_whole_and_readable_by_the_web_server(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "servers.json")
            live_servers.write_feed(path, [])
            live_servers.write_feed(path, [live_servers.server_entry(STATUS, LAYER)])
            with open(path, encoding="utf-8") as file:
                feed = json.load(file)
            self.assertEqual(os.listdir(folder), ["servers.json"])
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)
        self.assertRegex(feed["generated"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(feed["servers"][0]["team2"], "RGF")


if __name__ == "__main__":
    unittest.main()
