"""Tests of the JSON form of the committed data files.

Run: python3 -m unittest discover -s tools/game_audit
"""
import json
import unittest

import audit_json


class Form(unittest.TestCase):
    DATA = {"Mortar": {"pitch": [0.0, 43.8], "sight": [{"degrees": 45.0, "source": "widget"}], "curve": [[-180.0, 15.0], [1e-05, -2.5]]}, "names": ["a", "b"]}

    def test_the_text_reads_back_to_the_same_data(self):
        self.assertEqual(json.loads(audit_json.dumps(self.DATA)), self.DATA)

    def test_a_list_of_numbers_stays_on_one_line_and_a_key_has_its_own(self):
        lines = audit_json.dumps(self.DATA).split("\n")
        self.assertIn('  "pitch": [0.0, 43.8],', lines)
        self.assertIn("   [-180.0, 15.0],", lines)
        self.assertIn("   [1e-05, -2.5]", lines)
        self.assertIn('  "a",', lines)

    def test_the_text_ends_with_one_newline(self):
        text = audit_json.dumps({"a": [1, 2]})
        self.assertTrue(text.endswith("]\n}\n"))


if __name__ == "__main__":
    unittest.main()
