"""data-provenance.md / .ru.md against the weapon tables of both apps and the game files.

Run: python -m unittest discover -s tests (from tools/volumetric). The first group needs nothing; the second reads the
checkouts and the game data and is skipped where they are missing: SQUAD_BALLISTICS (Squad Ballistics checkout, default
~/dev/Squad-Ballistics), SQUADCALC (default ~/agl/SquadCalc), SQUAD_WEAPONS_DATA (resolved.json and dump/, default
~/data/squad-weapons).
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "game_ballistics"))

import provenance  # noqa: E402

DOCS = os.path.join(HERE, "..", "docs")
SB = os.path.expanduser(os.environ.get("SQUAD_BALLISTICS", "~/dev/Squad-Ballistics"))
SC = os.path.expanduser(os.environ.get("SQUADCALC", "~/agl/SquadCalc"))
DATA = os.path.expanduser(os.environ.get("SQUAD_WEAPONS_DATA", "~/data/squad-weapons"))


class IndexCoverage(unittest.TestCase):
    """The check that every weapon of both apps is in the document."""

    NAMES = [("SB", "RPG-29"), ("SC", "DF_RPG_29"), ("SC", "Mortar")]
    INDEX = "| App | Weapon | Classes | Origin |\n|---|---|---|---|\n| SB | RPG-29 | C10 | game |\n| SC | DF_RPG_29 | C10 | generated |\n| SC | Mortar | C01 | hand |"

    def test_a_complete_index_has_no_problem(self):
        self.assertEqual(provenance.missing_from_index(self.INDEX, self.NAMES), [])

    def test_a_missing_weapon_is_named(self):
        index = self.INDEX.replace("| SC | Mortar | C01 | hand |", "")
        problems = provenance.missing_from_index(index, self.NAMES)
        self.assertEqual(len(problems), 1)
        self.assertIn("Mortar", problems[0])

    def test_the_app_matters(self):
        problems = provenance.missing_from_index("| SB | Mortar | C01 | game |", [("SC", "Mortar")])
        self.assertEqual(len(problems), 1)

    def test_a_name_inside_another_cell_does_not_count(self):
        self.assertTrue(provenance.missing_from_index("| SB | RPG-29 | C10 | Mortar |", [("SB", "Mortar")]))


class Differences(unittest.TestCase):
    def test_only_differing_rows_are_reported(self):
        rows = [{"same": True, "app": "SB", "weapon": "a"}, {"same": False, "app": "SC", "weapon": "b"}]
        self.assertEqual(provenance.unexplained(rows), [rows[1]])

    def test_a_documented_difference_is_not_reported(self):
        rows = provenance.Rows()
        app, weapon, name = next(iter(provenance.KNOWN))
        rows.add(app, weapon, "-", name, "1385", "1000", "cap", "VERIFIED", same=False)
        self.assertEqual(provenance.unexplained(rows.rows), [])
        rows.add("SC", "other", "-", "max_speed", "1385", "1000", "cap", "VERIFIED", same=False)
        self.assertEqual(len(provenance.unexplained(rows.rows)), 1)

    def test_the_generated_blocks_are_replaced_in_place(self):
        text = "a\n<!-- generated:x -->\nold\n<!-- /generated:x -->\nb"
        out = provenance.BLOCK_RE.sub(lambda m: provenance.BLOCK.format(name=m.group(1), text="new"), text)
        self.assertEqual(out, "a\n<!-- generated:x -->\nnew\n<!-- /generated:x -->\nb")


@unittest.skipUnless(all(os.path.exists(p) for p in (os.path.join(SB, "weapons.json"), os.path.join(SC, "src", "data", "weapons.js"),
                                                    os.path.join(DATA, "resolved.json"))), "checkouts or game data missing")
class AgainstTheRepositories(unittest.TestCase):
    """The documents match the weapon tables and the game: no weapon missing, no stale block, no unexplained difference."""

    def test_documents_tables_and_game_agree(self):
        data = provenance.Data(os.path.join(DATA, "resolved.json"), SB, SC, os.path.join(DATA, "dump"))
        self.assertEqual(provenance.check_docs(DOCS, data), [])


if __name__ == "__main__":
    unittest.main()
