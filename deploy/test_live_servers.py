"""live_servers.py: the faction ID from the site's label, the feed's server, the feed file, and the loop with the network
stubbed (what each answer leaves in the feed, and how long the loop waits after it).
Run: python3 -m unittest test_live_servers.py"""
import contextlib
import datetime
import email.utils
import http.client
import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

import live_servers

AFU = {"factionID": "AFU", "factionName": "Armed Forces of Ukraine"}
GFI = {"factionID": "GFI", "factionName": "Ground Forces of Iran"}
RGF = {"factionID": "RGF", "factionName": "Russian Ground Forces"}
UNITS = [AFU, AFU, GFI]
LAYER = {"units": {"team1Units": UNITS, "team2Units": [RGF]}}
STATUS = {
    "name": "[RU] Deadline", "map": "AlBasrah_RAAS_v1", "players": 87, "max": 100, "queue": 3,
    "teams": {"1": {"faction": "Armed Forces of Ukraine", "players": 44}, "2": {"faction": "Russian Ground Forces", "players": 43}},
}
SERVER = {
    "id": "deadline",
    "attributes": {"name": "[RU] Deadline", "players": 87, "maxPlayers": 100, "details": {"map": "AlBasrah_RAAS_v1"}},
    "team1": "AFU",
    "team2": "RGF",
}
SITE = live_servers.SITE_URL
LAYER_OF_STATUS = live_servers.LAYER_URL + "AlBasrah_RAAS_v1"


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


class OfferedFactions(unittest.TestCase):
    def test_each_faction_of_a_team_once(self):
        self.assertEqual(live_servers.offered_factions(LAYER), {"1": [AFU, GFI], "2": [RGF]})

    def test_answer_of_another_shape_is_refused(self):
        for answer in (
            None, [], {}, {"units": []}, {"units": {"team1Units": [AFU]}}, {"units": {"team1Units": {}, "team2Units": []}},
            {"units": {"team1Units": ["AFU"], "team2Units": []}},
            {"units": {"team1Units": [{"factionID": "AFU"}], "team2Units": []}},
            {"units": {"team1Units": [{**AFU, "factionName": None}], "team2Units": []}},
            {"units": {"team1Units": [{**AFU, "factionID": 7}], "team2Units": []}},
        ):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                live_servers.offered_factions(answer)


class ServerEntry(unittest.TestCase):
    def entry(self, status, layer):
        return live_servers.server_entry(live_servers.site_status({"data": status}), layer and live_servers.offered_factions(layer))

    def test_server_with_both_teams(self):
        self.assertEqual(self.entry(STATUS, LAYER), SERVER)

    def test_team_whose_faction_is_not_resolved_is_left_out(self):
        first = {"faction": "Armed Forces of Ukraine"}
        for teams in ({"1": first, "2": {"faction": None}}, {"1": first, "2": None}, {"1": first},
                      {"1": first, "2": {"faction": "Ground Forces of Iran"}}):
            with self.subTest(teams=teams):
                entry = self.entry({**STATUS, "teams": teams}, LAYER)
                self.assertEqual(entry["team1"], "AFU")
                self.assertNotIn("team2", entry)

    def test_layer_unknown_to_the_api_lists_the_server_without_teams(self):
        entry = self.entry(STATUS, None)
        self.assertEqual(entry["attributes"]["details"]["map"], "AlBasrah_RAAS_v1")
        self.assertNotIn("team1", entry)
        self.assertNotIn("team2", entry)

    def test_no_server_while_no_layer_is_played(self):
        self.assertIsNone(self.entry({**STATUS, "map": None}, None))
        self.assertIsNone(self.entry({"name": None, "map": None, "teams": {}}, None))
        self.assertIsNone(self.entry({}, None))

    def test_site_answer_of_another_shape_is_refused(self):
        for body in (None, [], "maintenance", {}, {"data": None}, {"data": "maintenance"}, {"data": [STATUS]}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                live_servers.site_status(body)
        for field in ({"name": ["[RU] Deadline"]}, {"map": {"name": "AlBasrah_RAAS_v1"}}, {"players": "87"}, {"max": True},
                      {"teams": []}, {"teams": {"1": "Armed Forces of Ukraine"}}, {"teams": {"1": {"faction": 3}}}):
            with self.subTest(field=field), self.assertRaises(ValueError):
                live_servers.site_status({"data": {**STATUS, **field}})


class Watched:
    """A file opened for writing that calls `look` before and after every write, the written part flushed."""

    def __init__(self, file, look):
        self.file, self.look = file, look

    def __enter__(self):
        return self

    def __exit__(self, *error):
        self.file.close()

    def write(self, text):
        self.look()
        written = self.file.write(text)
        self.file.flush()
        self.look()
        return written


class WriteFeed(unittest.TestCase):
    def test_feed_is_replaced_whole_and_readable_by_the_web_server(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "servers.json")
            live_servers.write_feed(path, [])
            live_servers.write_feed(path, [SERVER])
            with open(path, encoding="utf-8") as file:
                feed = json.load(file)
            self.assertEqual(os.listdir(folder), ["servers.json"])
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)
        self.assertRegex(feed["generated"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(feed["servers"][0]["team2"], "RGF")

    def test_reader_sees_the_old_feed_whole_until_the_new_one_is_complete(self):
        real_open = open
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "servers.json")

            def served():
                with real_open(path, encoding="utf-8") as file:
                    text = file.read()
                try:
                    return json.loads(text)["servers"]
                except ValueError:
                    return f"half a file: {text!r}"

            seen = []

            def watched_open(file, mode="r", **options):
                opened = real_open(file, mode, **options)
                return Watched(opened, lambda: seen.append(served())) if "w" in mode else opened

            live_servers.write_feed(path, [])
            with mock.patch("builtins.open", watched_open):
                live_servers.write_feed(path, [SERVER])
            self.assertGreater(len(seen), 1)
            self.assertEqual(seen, [[]] * len(seen))
            self.assertEqual(served(), [SERVER])


class Answer:
    """A stubbed HTTP answer: a body (JSON of `body`, or the bytes given) and headers."""

    def __init__(self, body, headers=None):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *error):
        return False

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]


def status_error(url, code, headers=None):
    return urllib.error.HTTPError(url, code, http.client.responses[code], headers or {}, None)


class Stop(BaseException):
    """Ends main() once the rounds of a test are played."""


class Unscripted(BaseException):
    """A request the round of a test has no answer for."""


class Loop(unittest.TestCase):
    """main() with urlopen, the clock and sleep stubbed: a round maps each URL asked in it to its Answer, or to the
    exception urlopen raises."""

    GOOD = {SITE: Answer({"data": STATUS}, {"ETag": '"first"'}), LAYER_OF_STATUS: Answer(LAYER)}

    def play(self, rounds):
        """Runs main() for `rounds`. Sets `servers` (the feed's servers after each round, None while there is no
        feed), `writes` (the feed writes so far, after each round), `pauses` (the seconds to the next round), `lines`
        (what was logged) and `requests` (the (URL, If-None-Match) asked in each round)."""
        self.servers, self.writes, self.pauses, self.requests = [], [], [], [[]]
        clock = [1000.0]
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "servers.json")

            def urlopen(request, timeout):
                self.requests[-1].append((request.full_url, request.get_header("If-none-match")))
                answer = rounds[len(self.pauses)].get(request.full_url)
                if answer is None:
                    raise Unscripted(request.full_url)
                if isinstance(answer, Exception):
                    raise answer
                return answer

            def sleep(seconds):
                self.pauses.append(seconds)
                clock[0] += seconds
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as file:
                        self.servers.append(json.load(file)["servers"])
                else:
                    self.servers.append(None)
                self.writes.append(write_feed.call_count)
                if len(self.pauses) == len(rounds):
                    raise Stop
                self.requests.append([])

            logged = io.StringIO()
            with mock.patch.object(live_servers.urllib.request, "urlopen", urlopen), \
                    mock.patch.object(live_servers.time, "sleep", sleep), \
                    mock.patch.object(live_servers.time, "monotonic", lambda: clock[0]), \
                    mock.patch.object(live_servers, "write_feed", wraps=live_servers.write_feed) as write_feed, \
                    contextlib.redirect_stderr(logged), self.assertRaises(Stop):
                live_servers.main(path)
        self.lines = logged.getvalue().splitlines()

    def assert_left_alone_then_written(self, failure, bad_round):
        """A good round, `bad_round` twice, a good round: the feed of the first round stays through the bad ones, which
        log one line starting with `failure`, and the last round writes it again."""
        self.play([self.GOOD, bad_round, bad_round, self.GOOD])
        self.assertEqual(self.servers, [[SERVER]] * 4)
        self.assertEqual(self.writes, [1, 1, 1, 2])
        self.assertEqual(len(self.lines), 3, self.lines)
        self.assertTrue(self.lines[1].startswith(f"feed not updated: {failure}"), self.lines[1])
        self.assertEqual(self.lines[2], self.lines[0])

    def test_unchanged_site_answer_is_not_sent_again_and_the_feed_is_written_anew(self):
        unchanged = {SITE: status_error(SITE, 304)}
        self.play([self.GOOD, unchanged, {SITE: Answer({"data": {**STATUS, "map": None}}, {"ETag": '"second"'})}, unchanged])
        self.assertEqual(self.requests, [[(SITE, None), (LAYER_OF_STATUS, None)], [(SITE, '"first"')], [(SITE, '"first"')],
                                         [(SITE, '"second"')]])
        self.assertEqual(self.servers, [[SERVER], [SERVER], [], []])
        self.assertEqual(self.writes, [1, 2, 3, 4])
        self.assertEqual(self.pauses, [20, 20, 20, 20])
        self.assertEqual(self.lines, ["AlBasrah_RAAS_v1, teams AFU / RGF", "no layer played"])

    def test_site_answer_of_another_shape_leaves_the_feed(self):
        for body in (None, [STATUS], {"data": "maintenance"}, {"data": [STATUS]}, {"ok": False}, b"<html>502 Bad Gateway</html>",
                     {"data": {**STATUS, "teams": []}}, {"data": {**STATUS, "teams": {"1": "Armed Forces of Ukraine"}}},
                     {"data": {**STATUS, "map": ["AlBasrah_RAAS_v1"]}}, {"data": {**STATUS, "players": "<b>87</b>"}}):
            with self.subTest(body=body):
                self.assert_left_alone_then_written(SITE, {SITE: Answer(body), LAYER_OF_STATUS: Answer(LAYER)})

    def test_site_answer_longer_than_the_limit_leaves_the_feed(self):
        body = json.dumps({"data": STATUS}).encode().ljust(live_servers.MAX_BODY_BYTES + 1)
        self.assert_left_alone_then_written(SITE, {SITE: Answer(body)})

    def test_team_without_a_faction_is_listed_without_it(self):
        teams = {"1": None, "2": {"faction": "Russian Ground Forces"}}
        self.play([{SITE: Answer({"data": {**STATUS, "teams": teams}}), LAYER_OF_STATUS: Answer(LAYER)}])
        self.assertEqual(self.servers, [[{key: value for key, value in SERVER.items() if key != "team1"}]])

    def test_layer_answer_of_another_shape_leaves_the_feed_and_is_asked_again(self):
        for answer in ({"rawName": "AlBasrah_RAAS_v1"}, ["AlBasrah_RAAS_v1"], {"units": {"team1Units": UNITS}},
                       {"units": {"team1Units": UNITS, "team2Units": [{"factionID": "RGF"}]}},
                       {"units": {"team1Units": UNITS, "team2Units": [{**RGF, "factionName": None}]}}):
            with self.subTest(answer=answer):
                unreadable = {**self.GOOD, LAYER_OF_STATUS: Answer(answer)}
                self.play([unreadable, unreadable, self.GOOD, self.GOOD])
                self.assertEqual(self.servers, [None, None, [SERVER], [SERVER]])
                self.assertEqual([[url for url, _ in asked] for asked in self.requests], [[SITE, LAYER_OF_STATUS]] * 3 + [[SITE]])
                self.assertEqual(len(self.lines), 2, self.lines)
                self.assertTrue(self.lines[0].startswith(f"feed not updated: {LAYER_OF_STATUS}: "), self.lines[0])
                self.assertEqual(self.lines[1], "AlBasrah_RAAS_v1, teams AFU / RGF")

    def test_layer_the_api_does_not_have_lists_the_server_without_teams_and_is_asked_once(self):
        missing = {**self.GOOD, LAYER_OF_STATUS: status_error(LAYER_OF_STATUS, 404)}
        self.play([missing, missing])
        without_teams = {key: value for key, value in SERVER.items() if key in ("id", "attributes")}
        self.assertEqual(self.servers, [[without_teams], [without_teams]])
        self.assertEqual([[url for url, _ in asked] for asked in self.requests], [[SITE, LAYER_OF_STATUS], [SITE]])
        self.assertEqual(self.lines, ["AlBasrah_RAAS_v1, teams None / None"])

    def test_layer_is_asked_again_after_its_time_and_a_failed_request_leaves_the_last_answer(self):
        other = {"units": {"team1Units": [GFI], "team2Units": [RGF]}}
        site = {SITE: self.GOOD[SITE]}
        # Rounds 20 s apart; the answer is kept 30 s, a failed request is repeated 30 s later
        with mock.patch.object(live_servers, "LAYER_KEPT_S", 30), mock.patch.object(live_servers, "LAYER_RETRY_S", 30):
            self.play([self.GOOD, site, {**site, LAYER_OF_STATUS: status_error(LAYER_OF_STATUS, 502)}, site,
                       {**site, LAYER_OF_STATUS: Answer(other)}])
        self.assertEqual([[url for url, _ in asked] for asked in self.requests],
                         [[SITE, LAYER_OF_STATUS], [SITE], [SITE, LAYER_OF_STATUS], [SITE], [SITE, LAYER_OF_STATUS]])
        # The layer no longer offers team 1 the faction the site names: the server is listed without that team
        without_team1 = {key: value for key, value in SERVER.items() if key != "team1"}
        self.assertEqual(self.servers, [[SERVER]] * 4 + [[without_team1]])
        self.assertEqual(self.writes, [1, 2, 3, 4, 5])
        self.assertEqual(self.lines, ["AlBasrah_RAAS_v1, teams AFU / RGF", "AlBasrah_RAAS_v1, teams None / RGF"])

    def test_layer_the_api_did_not_have_is_asked_again_after_its_time(self):
        missing = {**self.GOOD, LAYER_OF_STATUS: status_error(LAYER_OF_STATUS, 404)}
        site = {SITE: self.GOOD[SITE]}
        with mock.patch.object(live_servers, "LAYER_KEPT_S", 30):
            self.play([missing, site, self.GOOD])
        self.assertEqual([[url for url, _ in asked] for asked in self.requests], [[SITE, LAYER_OF_STATUS], [SITE], [SITE, LAYER_OF_STATUS]])
        without_teams = {key: value for key, value in SERVER.items() if key in ("id", "attributes")}
        self.assertEqual(self.servers, [[without_teams], [without_teams], [SERVER]])

    def test_broken_connection_leaves_the_feed(self):
        for error in (http.client.IncompleteRead(b'{"data"', 400), http.client.BadStatusLine("garbage"),
                      http.client.RemoteDisconnected("closed"), TimeoutError("timed out"),
                      urllib.error.URLError(TimeoutError("timed out")), ConnectionResetError(104, "reset")):
            with self.subTest(site=error):
                self.assert_left_alone_then_written(SITE, {SITE: error})
        another = live_servers.LAYER_URL + "Mutaha_Seed_v1"
        moved = {SITE: Answer({"data": {**STATUS, "map": "Mutaha_Seed_v1"}})}
        for error in (http.client.IncompleteRead(b'{"units"', 400), TimeoutError("timed out"), status_error(another, 502)):
            with self.subTest(layer=error):
                self.assert_left_alone_then_written(another, {**moved, another: error})

    def test_request_after_a_failed_round_sends_no_etag(self):
        self.play([self.GOOD, {SITE: status_error(SITE, 500)}, self.GOOD])
        self.assertEqual([asked[0] for asked in self.requests], [(SITE, None), (SITE, '"first"'), (SITE, None)])
        self.assertEqual(self.pauses, [20, 20, 20])

    def test_too_many_requests_waits_as_long_as_the_answer_says(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        in_five_minutes = email.utils.format_datetime(now + datetime.timedelta(minutes=5), usegmt=True)
        for header, pause in (("90", 90), (" 45 ", 45), ("5", 20), ("86400", 3600), ("9" * 5000, 3600),
                               (in_five_minutes, 300)):
            with self.subTest(retry_after=header):
                self.play([self.GOOD, {SITE: status_error(SITE, 429, {"Retry-After": header})}, self.GOOD])
                self.assertAlmostEqual(self.pauses[1], pause, delta=2)
                self.assertEqual([self.pauses[0], self.pauses[2]], [20, 20])
                self.assertEqual(self.writes, [1, 1, 2])
                self.assertTrue(self.lines[1].startswith(f"feed not updated: {SITE}: "), self.lines[1])
                self.assertEqual(self.lines[1].endswith(f"; next request in {self.pauses[1]:.0f} s"), pause != 20, self.lines[1])
        layer = {**self.GOOD, LAYER_OF_STATUS: status_error(LAYER_OF_STATUS, 429, {"Retry-After": "120"})}
        self.play([layer, self.GOOD])
        self.assertEqual((self.pauses, self.servers), ([120, 20], [None, [SERVER]]))
        self.play([self.GOOD, {SITE: status_error(SITE, 503, {"Retry-After": "60"})}, {SITE: status_error(SITE, 503)}])
        self.assertEqual(self.pauses, [20, 60, 20])

    def test_too_many_requests_without_a_time_waits_twice_as_long_each_round(self):
        limited = {SITE: status_error(SITE, 429)}
        self.play([self.GOOD] + [limited] * 6 + [self.GOOD, limited])
        self.assertEqual(self.pauses, [20, 40, 80, 160, 300, 300, 300, 20, 40])
        self.assertEqual(self.writes, [1] * 7 + [2, 2])
        self.assertEqual(len(self.lines), 4, self.lines)
        self.assertTrue(self.lines[1].endswith("; next request in 40 s"), self.lines[1])


if __name__ == "__main__":
    unittest.main()
