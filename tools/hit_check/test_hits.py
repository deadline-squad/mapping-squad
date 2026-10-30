import unittest

import hits

LINE = (
    "[2026.10.29-17.02.24:014][205]LogSquadTrace: [DedicatedServer]TakeDamage(): "
    "US_Hab_Forest_C_2147396717: 0.16 damage taken by causer BP_Mortarround4_C_2147387038 "
    "instigator SomeNick (Online IDs: EOS: 0002aaaabbbbccccddddeeeeffff0000 "
    "steam: 76561198000000000) health remaining 498.69"
)


class HitsTest(unittest.TestCase):
    def test_an_event_is_parsed_without_the_instance_numbers(self):
        self.assertEqual(
            list(hits.parse([LINE])),
            [("2026.10.29-17.02.24", "US_Hab_Forest_C", 0.16, "BP_Mortarround4_C", 498.69)],
        )

    def test_nothing_about_the_player_is_kept(self):
        rendered = repr(list(hits.parse([LINE])))
        for secret in ("SomeNick", "76561198000000000", "0002aaaabbbbcccc"):
            self.assertNotIn(secret, rendered)

    def test_a_vehicle_hit_is_parsed_too(self):
        line = LINE.replace("TakeDamage()", "TraceAndMessageClient()").replace("US_Hab_Forest", "BP_LAVN")
        self.assertEqual(list(hits.parse([line]))[0][1], "BP_LAVN_C")

    def test_other_lines_are_ignored(self):
        other = "[2026.10.29-17.02.24:014][205]LogSquad: Player connected"
        self.assertEqual(list(hits.parse([other])), [])

    def test_a_name_with_spaces_and_symbols_does_not_break_the_line(self):
        line = LINE.replace("SomeNick", "『GRAD』Name With Spaces")
        self.assertEqual(len(list(hits.parse([line]))), 1)


if __name__ == "__main__":
    unittest.main()
