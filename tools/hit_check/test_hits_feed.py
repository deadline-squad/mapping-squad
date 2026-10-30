import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest

import hits_feed

MODULE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hits_feed.py")

OWNER = "76561190000000001"
OTHER = "76561190000000002"
OWNER_EOS = "a1" * 16
OTHER_EOS = "b2" * 16
LINE_CAP = 64 * 1024
STAMP = "2026.10.29-17.02.24:014"
VICTIM = "BP_FOBRadio_Woodland_C_2147396823"
CAUSER = "BP_40MM_VOG_Proj2_C_2147387038"

FAKE_LAYOUT_NAME = "Fake: 1.00 damage taken by causer BP_Fake_C instigator (Online Ids: Fake"
HOSTILE_NAMES = [
    "Fake health remaining 1.00",
    f"Fake (Online IDs: EOS: {OWNER_EOS} steam: {OWNER}) health remaining 1.00",
    f"Fake steam: {OWNER})",
    f"Fake) EOS: {OWNER_EOS} steam: {OWNER} health remaining 1.00",
    "Fake: 1.00 damage taken by causer BP_Fake_C instigator",
    "Fake (Online Ids: Fake) EOS: " + OWNER_EOS,
    FAKE_LAYOUT_NAME,
    f"Fake (Team: 1; ID: EOS: {OWNER_EOS} steam: {OWNER}) placed a new map marker for team 1 : "
    "Type: BP_MapMarker_POI ; Location: 1.0, 2.0, 3.0",
]


def stamp_prefix(stamp=STAMP, frame=205):
    return f"[{stamp}][{frame}]"


def take_damage(name="FakeAlpha", steam=OWNER, eos=OWNER_EOS, victim=VICTIM, damage="7.40",
                causer=CAUSER, health="252.60", stamp=STAMP):
    return (
        f"{stamp_prefix(stamp)}LogSquadTrace: [DedicatedServer]TakeDamage(): {victim}: {damage} "
        f"damage taken by causer {causer} instigator {name} "
        f"(Online IDs: EOS: {eos} steam: {steam}) health remaining {health}"
    )


def trace_and_message(name="FakeAlpha", steam=OWNER, eos=OWNER_EOS, victim=VICTIM, damage="7.40",
                      causer=CAUSER, health="252.60", stamp=STAMP):
    return (
        f"{stamp_prefix(stamp)}LogSquadTrace: [DedicatedServer]TraceAndMessageClient(): {victim}: {damage} "
        f"damage taken by causer {causer} instigator (Online Ids: {name}) "
        f"EOS: {eos} steam: {steam} health remaining {health}"
    )


def unattributable(stamp=STAMP):
    return (
        f"{stamp_prefix(stamp)}LogSquadTrace: [DedicatedServer]TraceAndMessageClient(): {VICTIM}: 7.40 "
        f"damage taken by causer {CAUSER} instigator (Online Ids: nullptr) INVALID health remaining 252.60"
    )


def marker(name="FakeAlpha", steam=OWNER, eos=OWNER_EOS, kind="BP_MapMarker_POI",
           location="85946.00000, -57540.00000, 4675.00000", stamp=STAMP):
    return (
        f"{stamp_prefix(stamp)}LogSquad: Player {name} (Team: 1; ID: EOS: {eos} steam: {steam}) "
        f"placed a new map marker for team 1 : Type: {kind} ; Location: {location}"
    )


def event_for(line, steam=OWNER):
    return hits_feed.EventFilter(steam).event_for(line.encode())


class ParseTest(unittest.TestCase):
    def test_take_damage_line_of_the_owner(self):
        event = event_for(take_damage())
        self.assertEqual(
            event,
            {
                "type": "hit",
                "id": event["id"],
                "ts": "2026-10-29T17:02:24.014Z",
                "target": "BP_FOBRadio_Woodland_C",
                "damage": 7.4,
                "causer": "BP_40MM_VOG_Proj2_C",
                "health": 252.6,
            },
        )

    def test_trace_and_message_line_of_the_owner(self):
        event = event_for(trace_and_message(victim="BP_LAVN_C_17", health="-3.5"))
        self.assertEqual((event["target"], event["health"], event["damage"]), ("BP_LAVN_C", -3.5, 7.4))

    def test_the_unattributable_shape_is_dropped(self):
        self.assertIsNone(hits_feed.EventFilter().event_for(unattributable().encode()))

    def test_a_damage_attempt_line_is_not_used(self):
        line = trace_and_message().replace("damage taken by causer", "damage attempt by causer")
        self.assertIsNone(event_for(line))

    def test_a_victim_that_is_not_a_class_name_becomes_other(self):
        for victim in ("FakeVictim", "Two Words", "『TAG』 Name", "x" * 150 + " y", "Foo_C extra", ""):
            with self.subTest(victim=victim):
                self.assertEqual(event_for(trace_and_message(victim=victim))["target"], "other")

    def test_a_causer_that_is_not_a_class_name_drops_the_event(self):
        self.assertIsNone(event_for(trace_and_message(causer="FakeVictim")))

    def test_the_instance_suffix_is_cut(self):
        self.assertEqual(hits_feed.class_name("BP_X_C_2147396823"), "BP_X_C")
        self.assertEqual(hits_feed.class_name("BP_X_C"), "BP_X_C")
        self.assertIsNone(hits_feed.class_name("BP_X"))

    def test_a_windows_line_ending_is_ignored(self):
        self.assertIsNotNone(hits_feed.EventFilter(OWNER).event_for(take_damage().encode() + b"\r"))

    def test_other_lines_are_ignored(self):
        for line in ("", "garbage", f"{stamp_prefix()}LogSquad: Player connected", "[bad][1]LogSquad: x"):
            self.assertIsNone(event_for(line))

    def test_a_marker_line_of_the_owner(self):
        event = event_for(marker(kind="BP_MapMarker_Option_Mortar", location="-1.50000, 2.00000, 0.00000"))
        self.assertEqual(
            (event["type"], event["marker"], event["x"], event["y"], event["z"]),
            ("marker", "BP_MapMarker_Option_Mortar", -1.5, 2.0, 0.0),
        )
        self.assertEqual(event["ts"], "2026-10-29T17:02:24.014Z")

    def test_a_marker_that_is_not_a_map_marker_class_is_dropped(self):
        self.assertIsNone(event_for(marker(kind="Evil Thing")))

    def test_a_number_too_long_to_be_finite_is_dropped(self):
        self.assertIsNone(event_for(take_damage(damage="9" * 400)))


class HostileNameTest(unittest.TestCase):
    def test_the_owner_with_a_hostile_name_still_gets_the_real_event_once(self):
        for name in HOSTILE_NAMES:
            if name == FAKE_LAYOUT_NAME:
                continue
            for build in (take_damage, trace_and_message):
                with self.subTest(name=name, build=build.__name__):
                    event = event_for(build(name=name, damage="7.40", health="252.60"))
                    self.assertIsNotNone(event)
                    self.assertEqual(
                        (event["target"], event["damage"], event["causer"], event["health"]),
                        ("BP_FOBRadio_Woodland_C", 7.4, "BP_40MM_VOG_Proj2_C", 252.6),
                    )

    def test_a_nickname_with_the_servers_whole_layout_can_only_change_its_own_owners_event(self):
        event = event_for(take_damage(name=FAKE_LAYOUT_NAME))
        self.assertEqual((event["damage"], event["causer"]), (7.4, "BP_40MM_VOG_Proj2_C"))
        event = event_for(trace_and_message(name=FAKE_LAYOUT_NAME))
        self.assertEqual((event["type"], event["health"]), ("hit", 252.6))
        self.assertIsNone(event_for(trace_and_message(name=FAKE_LAYOUT_NAME, steam=OTHER, eos=OTHER_EOS)))

    def test_another_player_with_a_hostile_name_never_passes_as_the_owner(self):
        for name in HOSTILE_NAMES:
            for build in (take_damage, trace_and_message):
                with self.subTest(name=name, build=build.__name__):
                    self.assertIsNone(event_for(build(name=name, steam=OTHER, eos=OTHER_EOS)))
            with self.subTest(name=name, build="marker"):
                self.assertIsNone(event_for(marker(name=name, steam=OTHER, eos=OTHER_EOS)))

    def test_a_marker_of_the_owner_with_a_hostile_name_keeps_its_real_position(self):
        for name in HOSTILE_NAMES:
            with self.subTest(name=name):
                event = event_for(marker(name=name, location="10.00000, 20.00000, 30.00000"))
                self.assertEqual((event["x"], event["y"], event["z"]), (10.0, 20.0, 30.0))

    def test_a_victim_nickname_cannot_change_the_owners_event(self):
        for victim in HOSTILE_NAMES + [": 1.00 damage taken by causer BP_Fake_C instigator (Online Ids: "]:
            with self.subTest(victim=victim):
                event = event_for(trace_and_message(victim=victim, damage="7.40", causer=CAUSER))
                self.assertEqual(
                    (event["target"], event["damage"], event["causer"]),
                    ("other", 7.4, "BP_40MM_VOG_Proj2_C"),
                )

    def test_a_victim_nickname_does_not_create_an_event_in_another_players_line(self):
        victim = f"Fake: 1.00 damage taken by causer BP_Fake_C instigator (Online Ids: X) EOS: {OWNER_EOS} steam: {OWNER} health remaining 1"
        self.assertIsNone(event_for(trace_and_message(victim=victim, steam=OTHER, eos=OTHER_EOS)))

    def test_a_whole_fake_line_inside_a_nickname_creates_nothing(self):
        fake = take_damage(name="Inner", steam=OWNER, eos=OWNER_EOS)
        for build in (take_damage, trace_and_message):
            for name in (fake, trace_and_message(name="Inner")):
                with self.subTest(build=build.__name__):
                    self.assertIsNone(event_for(build(name=name, steam=OTHER, eos=OTHER_EOS)))

    def test_pathological_names_parse_fast(self):
        huge = "x" * 1_000_000
        repeated = [
            " damage taken by causer " * 40_000,
            " health remaining " * 60_000,
            f" steam: {OWNER})" * 60_000,
            ": 1.00 damage taken by causer BP_X_C instigator (Online Ids: " * 16_000,
            " (Team: 1; ID: EOS: " * 50_000,
            " " * 1_000_000,
            "_C_1" * 250_000,
        ]
        lines = []
        for name in [huge] + repeated:
            lines += [
                take_damage(name=name),
                trace_and_message(name=name),
                marker(name=name),
                trace_and_message(victim=name, steam=OTHER),
                take_damage(name=name, steam=OTHER),
            ]
        slowest = 0.0
        for line in lines:
            best = min(self._seconds(hits_feed.parse_line, line) for _ in range(3))
            slowest = max(slowest, best)
        self.assertLess(slowest, 0.05)

    @staticmethod
    def _seconds(function, argument):
        started = time.perf_counter()
        function(argument)
        return time.perf_counter() - started


class EventIdTest(unittest.TestCase):
    def test_the_id_has_stamp_chain_and_crc(self):
        self.assertRegex(event_for(take_damage())["id"], rf"\A{re.escape(STAMP)}#0#[0-9a-f]{{8}}\Z")

    def test_identical_lines_in_one_millisecond_get_different_ids(self):
        event_filter = hits_feed.EventFilter(OWNER)
        ids = [event_filter.event_for(take_damage().encode())["id"] for _ in range(3)]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual([i.split("#")[1] for i in ids], ["0", "1", "2"])
        self.assertEqual(len({i.split("#")[2] for i in ids}), 1)

    def test_the_same_lines_give_the_same_ids_in_a_new_run(self):
        lines = [take_damage().encode(), take_damage().encode(), marker().encode()]
        filter_a, filter_b = hits_feed.EventFilter(OWNER), hits_feed.EventFilter(OWNER)
        self.assertEqual(
            [filter_a.event_for(line)["id"] for line in lines],
            [filter_b.event_for(line)["id"] for line in lines],
        )

    def test_different_events_in_one_millisecond_differ_in_the_crc(self):
        a = event_for(take_damage(damage="7.40"))["id"].split("#")[2]
        b = event_for(take_damage(damage="7.50"))["id"].split("#")[2]
        self.assertNotEqual(a, b)

    def test_events_in_different_milliseconds_start_their_own_chain(self):
        event_filter = hits_feed.EventFilter(OWNER)
        event_filter.event_for(take_damage().encode())
        later = event_filter.event_for(take_damage(stamp="2026.10.29-17.02.24:015").encode())
        self.assertEqual(later["id"].split("#")[1], "0")


class FilterTest(unittest.TestCase):
    def test_the_owner_passes_and_another_player_is_dropped(self):
        owner = hits_feed.EventFilter(OWNER)
        for build in (take_damage, trace_and_message, marker):
            self.assertIsNotNone(owner.event_for(build().encode()))
            self.assertIsNone(owner.event_for(build(steam=OTHER, eos=OTHER_EOS).encode()))

    def test_without_an_id_every_attributable_event_passes_in_replay(self):
        everyone = hits_feed.EventFilter()
        self.assertIsNotNone(everyone.event_for(take_damage(steam=OTHER).encode()))


class LineSplitterTest(unittest.TestCase):
    def test_complete_lines_and_a_partial_one(self):
        splitter = hits_feed.LineSplitter()
        self.assertEqual(splitter.feed(b"one\ntwo\npart"), [b"one", b"two"])
        self.assertEqual(splitter.feed(b"ial\n"), [b"partial"])

    def test_the_cap_is_exact(self):
        splitter = hits_feed.LineSplitter()
        limit = LINE_CAP
        lines = splitter.feed(b"a" * limit + b"\n" + b"b" * (limit + 1) + b"\nok\n")
        self.assertEqual([len(line) for line in lines], [limit, 2])

    def test_an_oversize_line_fed_in_pieces_is_skipped_and_the_next_one_survives(self):
        splitter = hits_feed.LineSplitter()
        found = []
        for _ in range(5):
            found += splitter.feed(b"z" * 40_000)
        found += splitter.feed(b"\nnext\n")
        self.assertEqual(found, [b"next"])

    def test_the_buffer_stays_bounded(self):
        splitter = hits_feed.LineSplitter()
        for _ in range(100):
            splitter.feed(b"z" * 40_000)
        self.assertLessEqual(len(splitter._buffer), LINE_CAP)

    def test_a_line_over_the_cap_is_not_parsed(self):
        padded = take_damage(name="x" * LINE_CAP)
        splitter = hits_feed.LineSplitter()
        self.assertEqual(splitter.feed(padded.encode() + b"\n"), [])


class Collector:
    def __init__(self):
        self.events = []

    def __call__(self, event):
        self.events.append(event)

    def of_type(self, kind):
        return [event for event in self.events if event["type"] == kind]


class FollowerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.logs = os.path.join(self.root, "squad2", "Logs")
        os.makedirs(self.logs)
        self.path = os.path.join(self.logs, "SquadGame.log")
        self.allow = os.path.join(self.root, "squad2")
        self.out = Collector()
        self.now = 1000.0

    def write(self, *lines, mode="ab", path=None):
        with open(path or self.path, mode) as handle:
            for line in lines:
                handle.write(line if isinstance(line, bytes) else line.encode())

    def follower(self, since=None):
        follower = hits_feed.LogFollower(
            self.path, self.allow, hits_feed.EventFilter(OWNER), self.out, since, clock=lambda: self.now
        )
        self.addCleanup(follower.close)
        return follower

    def test_it_starts_at_the_end_of_the_log(self):
        self.write(take_damage() + "\n")
        follower = self.follower()
        follower.step()
        self.assertEqual(self.out.events, [])
        self.write(take_damage(stamp="2026.10.29-17.02.25:000") + "\n")
        follower.step()
        self.assertEqual([e["ts"] for e in self.out.events], ["2026-10-29T17:02:25.000Z"])

    def test_it_starts_at_the_first_line_at_or_after_since(self):
        before = take_damage(stamp="2026.10.29-17.02.23:999")
        at = take_damage(stamp="2026.10.29-17.02.24:000")
        after = marker(stamp="2026.10.29-17.02.26:500")
        self.write(before + "\n", "continuation line without a stamp\n", at + "\n", after + "\n")
        follower = self.follower(since="2026.10.29-17.02.24:000")
        follower.step()
        self.assertEqual([e["type"] for e in self.out.events], ["hit", "marker"])
        self.assertEqual(self.out.events[0]["ts"], "2026-10-29T17:02:24.000Z")

    def test_since_between_two_lines_starts_at_the_next_one(self):
        self.write(take_damage(stamp="2026.10.29-17.02.23:000") + "\n", take_damage(stamp="2026.10.29-17.02.25:000") + "\n")
        follower = self.follower(since="2026.10.29-17.02.24:000")
        follower.step()
        self.assertEqual([e["ts"] for e in self.out.events], ["2026-10-29T17:02:25.000Z"])

    def test_since_in_the_future_waits_for_a_later_line(self):
        self.write(take_damage() + "\n")
        follower = self.follower(since="2026.10.30-00.00.00:000")
        follower.step()
        self.assertEqual(self.out.events, [])
        self.write(take_damage(stamp="2026.10.30-00.00.01:000") + "\n")
        follower.step()
        self.assertEqual(len(self.out.events), 1)

    def test_a_resume_repeats_the_ids_of_the_first_run(self):
        self.write(take_damage() + "\n", take_damage() + "\n", marker(stamp="2026.10.29-17.02.25:000") + "\n")
        first = self.follower(since="2026.10.29-00.00.00:000")
        first.step()
        second_out = Collector()
        second = hits_feed.LogFollower(
            self.path, self.allow, hits_feed.EventFilter(OWNER), second_out, STAMP, clock=lambda: self.now
        )
        self.addCleanup(second.close)
        second.step()
        self.assertEqual(len(second_out.events), 3)
        self.assertEqual([e["id"] for e in self.out.events], [e["id"] for e in second_out.events])

    def test_a_partial_line_waits_for_its_end(self):
        follower = self.follower()
        line = take_damage()
        self.write(line[:60])
        follower.step()
        self.assertEqual(self.out.events, [])
        self.write(line[60:])
        follower.step()
        self.assertEqual(self.out.events, [])
        self.write("\n")
        follower.step()
        self.assertEqual(len(self.out.events), 1)

    def test_starting_inside_a_partial_line_skips_its_rest(self):
        self.write(take_damage()[:80])
        follower = self.follower()
        self.write(take_damage()[80:] + "\n" + marker() + "\n")
        follower.step()
        self.assertEqual([e["type"] for e in self.out.events], ["marker"])

    def test_an_oversize_line_is_skipped_and_the_next_line_arrives(self):
        follower = self.follower()
        self.write(take_damage(name="x" * (LINE_CAP + 1)) + "\n", marker() + "\n")
        follower.step()
        self.assertEqual([e["type"] for e in self.out.events], ["marker"])

    def test_a_line_exactly_at_the_cap_is_kept(self):
        follower = self.follower()
        base = len(take_damage(name=""))
        self.write(take_damage(name="x" * (LINE_CAP - base)) + "\n")
        follower.step()
        self.assertEqual(len(self.out.events), 1)

    def test_a_missing_file_is_waited_for_and_read_from_its_start(self):
        follower = self.follower()
        self.assertFalse(follower.step())
        self.write(take_damage() + "\n")
        follower.step()
        self.assertEqual(len(self.out.events), 1)

    def test_rotation_reads_the_old_file_to_its_end_then_follows_the_new_one(self):
        self.write(take_damage() + "\n")
        follower = self.follower()
        self.write(marker(stamp="2026.10.29-17.02.30:000") + "\n")
        os.rename(self.path, os.path.join(self.logs, "SquadGame-backup-2026.10.29-17.03.00.log"))
        self.write(take_damage(stamp="2026.10.29-17.03.01:000") + "\n", mode="wb")
        for _ in range(4):
            follower.step()
        self.assertEqual([e["type"] for e in self.out.events], ["marker", "rotate", "hit"])
        self.write(marker(stamp="2026.10.29-17.03.02:000") + "\n")
        follower.step()
        self.assertEqual([e["type"] for e in self.out.events][-1], "marker")

    def test_the_new_file_is_read_from_its_first_line(self):
        self.write(take_damage() + "\n")
        follower = self.follower()
        os.rename(self.path, self.path + ".old")
        self.write(take_damage(stamp="2026.10.29-17.05.00:000") + "\n", mode="wb")
        for _ in range(3):
            follower.step()
        self.assertEqual([e["type"] for e in self.out.events], ["rotate", "hit"])

    def test_a_gap_between_the_rename_and_the_new_file_loses_nothing(self):
        self.write(take_damage() + "\n")
        follower = self.follower()
        os.rename(self.path, self.path + ".old")
        follower.step()
        self.assertEqual(self.out.events, [])
        self.write(take_damage(stamp="2026.10.29-17.05.00:000") + "\n", mode="wb")
        for _ in range(3):
            follower.step()
        self.assertEqual([e["type"] for e in self.out.events], ["rotate", "hit"])

    def test_a_truncated_file_counts_as_a_rotation(self):
        self.write(take_damage() + "\n")
        follower = self.follower()
        self.write(take_damage(stamp="2026.10.29-17.02.30:000") + "\n")
        follower.step()
        self.write(marker() + "\n", mode="wb")
        follower.step()
        follower.step()
        self.assertEqual([e["type"] for e in self.out.events], ["hit", "rotate", "marker"])

    def test_a_heartbeat_every_five_seconds(self):
        follower = self.follower()
        follower.step()
        self.assertEqual(self.out.of_type("hb"), [])
        self.now += 5.0
        follower.step()
        follower.step()
        self.assertEqual(len(self.out.of_type("hb")), 1)
        self.assertRegex(self.out.of_type("hb")[0]["clock"], r"\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z\Z")
        self.now += 5.0
        follower.step()
        self.assertEqual(len(self.out.of_type("hb")), 2)

    def test_a_log_symlinked_outside_the_allowed_directory_is_never_read(self):
        outside = os.path.join(self.root, "squad1.log")
        self.write(take_damage() + "\n", path=outside)
        os.symlink(outside, self.path)
        follower = self.follower(since="2000.01.01-00.00.00:000")
        follower.step()
        self.assertEqual(self.out.events, [])

    def test_a_log_swapped_for_a_symlink_outside_is_ignored(self):
        self.write(take_damage() + "\n")
        follower = self.follower()
        outside = os.path.join(self.root, "squad1.log")
        self.write(marker() + "\n", path=outside)
        os.rename(self.path, self.path + ".old")
        os.symlink(outside, self.path)
        for _ in range(3):
            follower.step()
        self.assertEqual(self.out.of_type("marker"), [])

    def test_a_directory_or_fifo_in_place_of_the_log_is_ignored(self):
        os.mkfifo(self.path)
        follower = self.follower()
        self.assertFalse(follower.step())


class AllowUnderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = os.path.realpath(self._tmp.name)
        self.squad1 = os.path.join(root, "squad1")
        self.squad2 = os.path.join(root, "squad2")
        for directory in (self.squad1, self.squad2):
            os.makedirs(directory)
            open(os.path.join(directory, "SquadGame.log"), "w").close()

    def test_a_direct_path_inside_is_allowed(self):
        self.assertTrue(hits_feed.is_under(os.path.join(self.squad2, "SquadGame.log"), self.squad2))

    def test_a_direct_path_outside_is_refused(self):
        self.assertFalse(hits_feed.is_under(os.path.join(self.squad1, "SquadGame.log"), self.squad2))
        self.assertFalse(hits_feed.is_under("/etc/passwd", self.squad2))

    def test_dot_dot_out_of_the_directory_is_refused(self):
        sneaky = os.path.join(self.squad2, "..", "squad1", "SquadGame.log")
        self.assertFalse(hits_feed.is_under(sneaky, self.squad2))

    def test_dot_dot_that_stays_inside_is_allowed(self):
        self.assertTrue(hits_feed.is_under(os.path.join(self.squad2, "x", "..", "SquadGame.log"), self.squad2))

    def test_a_symlink_to_the_other_server_is_refused(self):
        link = os.path.join(self.squad2, "link.log")
        os.symlink(os.path.join(self.squad1, "SquadGame.log"), link)
        self.assertFalse(hits_feed.is_under(link, self.squad2))

    def test_a_symlinked_directory_to_the_other_server_is_refused(self):
        link = os.path.join(self.squad2, "dir")
        os.symlink(self.squad1, link)
        self.assertFalse(hits_feed.is_under(os.path.join(link, "SquadGame.log"), self.squad2))

    def test_a_directory_with_the_same_prefix_is_not_inside(self):
        sibling = self.squad2 + "-evil"
        os.makedirs(sibling)
        self.assertFalse(hits_feed.is_under(os.path.join(sibling, "SquadGame.log"), self.squad2))

    def test_the_allowed_directory_itself_may_be_a_symlink(self):
        alias = os.path.join(os.path.dirname(self.squad2), "alias")
        os.symlink(self.squad2, alias)
        self.assertTrue(hits_feed.is_under(os.path.join(self.squad2, "SquadGame.log"), alias))


class ClientRequestTest(unittest.TestCase):
    def test_no_request_means_start_at_the_end(self):
        self.assertIsNone(hits_feed.parse_client_request(None))

    def test_a_valid_since_is_returned(self):
        self.assertEqual(hits_feed.parse_client_request("since=2026.10.29-17.02.24:014"), "2026.10.29-17.02.24:014")

    def test_everything_else_is_refused(self):
        bad = [
            "",
            "id",
            "since=../../etc/passwd",
            "since=..;id",
            "since=$(id)",
            "since=2026.10.29-17.02.24:014\n",
            "since=2026.10.29-17.02.24:014\nid",
            "since=2026.10.29-17.02.24:014 ",
            " since=2026.10.29-17.02.24:014",
            "since=2026.10.29-17.02.24:014;id",
            "since=2026.13.29-17.02.24:014",
            "since=2026.10.29-25.02.24:014",
            "since=2026.10.29-17.02.24:01",
            "since=" + "a" * 5000,
            "since=2026.10.29-17.02.24:014" + "0" * 5000,
            "/bin/sh",
        ]
        for request in bad:
            with self.subTest(request=request[:40]):
                with self.assertRaises(hits_feed.Refused):
                    hits_feed.parse_client_request(request)


def run_module(*args, env=None, stdin=b""):
    environment = {"PATH": os.environ["PATH"]}
    environment.update(env or {})
    return subprocess.run(
        [sys.executable, "-I", MODULE, *args], input=stdin, capture_output=True, env=environment, timeout=5
    )


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = os.path.realpath(self._tmp.name)
        self.allow = os.path.join(self.root, "squad2")
        os.makedirs(self.allow)
        self.log = os.path.join(self.allow, "SquadGame.log")
        with open(self.log, "wb") as handle:
            handle.write((take_damage() + "\n").encode())

    def follow_args(self, **overrides):
        values = {"--log": self.log, "--allow-under": self.allow, "--steam-id": OWNER}
        values.update(overrides)
        return [item for pair in values.items() for item in pair if item is not None]

    def assert_refused(self, result):
        self.assertEqual(result.returncode, hits_feed.EXIT_REFUSED)
        self.assertEqual(result.stdout, b"")
        self.assertTrue(result.stderr.startswith(b"hits_feed: refused"))
        self.assertLess(len(result.stderr), 120)

    def test_a_log_outside_the_allowed_directory_is_refused(self):
        self.assert_refused(run_module(*self.follow_args(**{"--log": "/etc/passwd"})))

    def test_a_dot_dot_log_is_refused(self):
        self.assert_refused(run_module(*self.follow_args(**{"--log": self.allow + "/../../../etc/passwd"})))

    def test_a_symlink_log_is_refused(self):
        link = os.path.join(self.allow, "link.log")
        os.symlink("/etc/passwd", link)
        self.assert_refused(run_module(*self.follow_args(**{"--log": link})))

    def test_a_relative_path_is_refused(self):
        self.assert_refused(run_module(*self.follow_args(**{"--log": "SquadGame.log"})))

    def test_a_bad_or_missing_steam_id_is_refused(self):
        for steam in ("1234", OWNER + "0", "7656119000000000x", "../etc"):
            with self.subTest(steam=steam):
                self.assert_refused(run_module(*self.follow_args(**{"--steam-id": steam})))
        self.assert_refused(run_module("--log", self.log, "--allow-under", self.allow))

    def test_missing_or_unknown_arguments_are_refused(self):
        self.assert_refused(run_module())
        self.assert_refused(run_module(*self.follow_args(), "--shell"))
        self.assert_refused(run_module("--log", self.log, "--steam-id", OWNER))

    def test_every_client_request_but_since_is_refused(self):
        requests = [
            "id",
            "/bin/sh",
            "since=../../etc/passwd",
            "since=..;id",
            "since=$(id)",
            "since=2026.10.29-17.02.24:014\nid",
            "since=" + "a" * 5000,
        ]
        for request in requests:
            with self.subTest(request=request[:30]):
                result = run_module(*self.follow_args(), env={"SSH_ORIGINAL_COMMAND": request})
                self.assert_refused(result)
                self.assertNotIn(b"passwd", result.stderr)

    def test_replay_also_refuses_a_foreign_request(self):
        self.assert_refused(run_module("--replay", env={"SSH_ORIGINAL_COMMAND": "id"}))

    def test_a_valid_run_says_hello_then_sends_the_owners_new_events_only(self):
        process = subprocess.Popen(
            [sys.executable, "-I", MODULE, *self.follow_args()],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": os.environ["PATH"]},
        )
        try:
            hello = json.loads(process.stdout.readline())
            self.assertEqual((hello["type"], hello["version"]), ("hello", hits_feed.VERSION))
            with open(self.log, "ab") as handle:
                handle.write((take_damage(steam=OTHER, eos=OTHER_EOS) + "\n").encode())
                handle.write((marker() + "\n").encode())
            event = json.loads(process.stdout.readline())
            self.assertEqual(event["type"], "marker")
        finally:
            process.kill()
            process.wait()
            process.stdout.close()
            process.stderr.close()

    def test_a_valid_since_replays_from_that_stamp(self):
        process = subprocess.Popen(
            [sys.executable, "-I", MODULE, *self.follow_args()],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": os.environ["PATH"], "SSH_ORIGINAL_COMMAND": f"since={STAMP}"},
        )
        try:
            self.assertEqual(json.loads(process.stdout.readline())["type"], "hello")
            self.assertEqual(json.loads(process.stdout.readline())["type"], "hit")
        finally:
            process.kill()
            process.wait()
            process.stdout.close()
            process.stderr.close()

    def test_a_closed_client_ends_the_feed(self):
        process = subprocess.Popen(
            [sys.executable, "-I", MODULE, *self.follow_args()],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": os.environ["PATH"]},
        )
        process.stdout.readline()
        process.stdout.close()
        with open(self.log, "ab") as handle:
            handle.write((marker() + "\n").encode())
        self.assertEqual(process.wait(timeout=10), 0)
        process.stderr.close()


class ReplayTest(unittest.TestCase):
    def lines(self):
        return [
            take_damage(name="FakeAlpha"),
            trace_and_message(name="FakeBravo", steam=OTHER, eos=OTHER_EOS, victim="FakeVictim Name"),
            trace_and_message(name="FakeAlpha", victim="FakeVictim"),
            unattributable(),
            marker(name="FakeBravo", steam=OTHER, eos=OTHER_EOS),
            marker(name="FakeAlpha"),
            "unrelated line FakeAlpha " + OWNER,
        ]

    def replay(self, *args):
        data = ("\r\n".join(self.lines()) + "\r\n").encode()
        out = io.StringIO()
        code = hits_feed.main(list(args), environ={}, out=out, stdin=types.SimpleNamespace(buffer=io.BytesIO(data)))
        self.assertEqual(code, 0)
        return [json.loads(line) for line in out.getvalue().splitlines()], out.getvalue()

    def test_replay_of_standard_input_for_everyone(self):
        events, _ = self.replay("--replay")
        self.assertEqual([e["type"] for e in events], ["hit", "hit", "hit", "marker", "marker"])

    def test_replay_for_the_owner_only(self):
        events, _ = self.replay("--replay", "--steam-id", OWNER)
        self.assertEqual([e["type"] for e in events], ["hit", "hit", "marker"])
        self.assertEqual([e["target"] for e in events if e["type"] == "hit"], ["BP_FOBRadio_Woodland_C", "other"])

    def test_replay_of_a_file(self):
        with tempfile.NamedTemporaryFile(suffix=".log") as handle:
            handle.write((take_damage() + "\n").encode())
            handle.flush()
            out = io.StringIO()
            self.assertEqual(hits_feed.main(["--replay", "--log", handle.name], environ={}, out=out), 0)
        self.assertEqual(len(out.getvalue().splitlines()), 1)

    def test_replay_over_a_process_pipe(self):
        data = ("\n".join(self.lines()) + "\n").encode()
        result = run_module("--replay", "--steam-id", OWNER, stdin=data)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout.splitlines()), 3)

    def test_the_output_never_contains_a_name_or_an_id(self):
        _, text = self.replay("--replay")
        for secret in ("FakeAlpha", "FakeBravo", "FakeVictim", OWNER, OTHER, OWNER_EOS, OTHER_EOS):
            self.assertNotIn(secret, text)

    def test_the_output_of_hostile_lines_never_contains_the_fakes(self):
        lines = []
        for name in HOSTILE_NAMES:
            lines += [take_damage(name=name), trace_and_message(name=name), marker(name=name)]
            lines += [trace_and_message(victim=name, steam=OTHER, eos=OTHER_EOS)]
        out = io.StringIO()
        hits_feed.main(
            ["--replay"], environ={}, out=out, stdin=types.SimpleNamespace(buffer=io.BytesIO(("\n".join(lines) + "\n").encode()))
        )
        for secret in (OWNER, OWNER_EOS, OTHER, OTHER_EOS, "Fake ", "Fake:", "Fake)"):
            self.assertNotIn(secret, out.getvalue())


if __name__ == "__main__":
    unittest.main()
