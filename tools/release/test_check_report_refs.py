"""Tests of check_report_refs.py: what it extracts from a report and how it judges paths and commits."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_report_refs as refs  # noqa: E402


class CollectTest(unittest.TestCase):
    def collect(self, text):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.md"
            report.write_text(text, encoding="utf-8")
            return refs.collect(report)

    def test_extracts_keyed_bare_commit_and_issues(self):
        keyed, bare, commits, issues = self.collect(
            "See `SC:engine/README.md`, `py/columns.py`, commit `e34e481`, #22, SB#13 and deadline-squad/squad-ballistics#17.")
        self.assertEqual(keyed, {("SC", "engine/README.md")})
        self.assertEqual(bare, {"py/columns.py"})
        self.assertEqual(commits, {"e34e481"})
        self.assertEqual(issues, {
            ("deadline-squad/deadline-squadcalc", "22"), ("deadline-squad/squad-ballistics", "13"),
            ("deadline-squad/squad-ballistics", "17")})

    def test_ignores_units_urls_placeholders_and_plain_numbers(self):
        keyed, bare, commits, issues = self.collect(
            "Speed 110 m/s, `<map>/volume.vcol`, `http://localhost:9910/a.json`, `/heightmaps/jensen/meta.json`, `12345678`.")
        self.assertEqual((keyed, bare, commits, issues), (set(), set(), set(), set()))


class MainTest(unittest.TestCase):
    def test_missing_path_fails_and_existing_path_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            good = Path(directory) / "good.md"
            good.write_text("`AGL:tools/release/README.md`\n", encoding="utf-8")
            bad = Path(directory) / "bad.md"
            bad.write_text("`AGL:tools/release/no_such_file.md`\n", encoding="utf-8")
            script = Path(refs.__file__)
            run = lambda report: subprocess.run(
                [sys.executable, str(script), "--no-issues", str(report)], capture_output=True, text=True)
            self.assertEqual(run(good).returncode, 0)
            result = run(bad)
            self.assertEqual(result.returncode, 1)
            self.assertIn("MISSING", result.stdout)


if __name__ == "__main__":
    unittest.main()
