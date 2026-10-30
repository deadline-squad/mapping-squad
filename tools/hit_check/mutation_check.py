"""Deliberately breaks hits_feed.py in six places and checks that the tests notice.

Each mutation is applied to a temporary copy of this directory, the unittest
suite is run there, and a mutation counts as killed when the suite fails.
Usage: python3 mutation_check.py   (exit code 1 if any mutation survives)
"""

import os
import shutil
import subprocess
import sys
import tempfile

MUTATIONS = [
    (
        "refused key: a foreign SSH_ORIGINAL_COMMAND is accepted",
        [('    if match is None:\n        raise Refused("only since=', '    if match is None:\n        return None\n        raise Refused("only since=')],
    ),
    (
        "de-duplication id: the chain number is always 0",
        [("chain = self._chains.pop(parsed.stamp, 0)", "chain = 0")],
    ),
    (
        "resume point: the line exactly at `since` is skipped",
        [("line[1:24] < self._since", "line[1:24] <= self._since")],
    ),
    (
        "line cap: the 64 KB limit is raised to 64 MB",
        [("MAX_LINE_BYTES = 64 * 1024", "MAX_LINE_BYTES = 64 * 1024 * 1024")],
    ),
    (
        "tail anchoring: the ID tails no longer have to end the line",
        [
            ("health remaining (?P<health>{NUMBER})\\Z", "health remaining (?P<health>{NUMBER})"),
            ("Location: (?P<x>{NUMBER}), (?P<y>{NUMBER}), (?P<z>{NUMBER})\\Z", "Location: (?P<x>{NUMBER}), (?P<y>{NUMBER}), (?P<z>{NUMBER})"),
        ],
    ),
    (
        "ID filter: every shooter's events pass",
        [("parsed.steam != self._steam_id", 'parsed.steam == ""')],
    ),
]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    survivors = 0
    for title, edits in MUTATIONS:
        with tempfile.TemporaryDirectory() as scratch:
            copy = os.path.join(scratch, "hit_check")
            shutil.copytree(here, copy, ignore=shutil.ignore_patterns("__pycache__"))
            path = os.path.join(copy, "hits_feed.py")
            source = open(path).read()
            for old, new in edits:
                if old not in source:
                    sys.exit(f"mutation does not apply: {title}: {old!r}")
                source = source.replace(old, new)
            open(path, "w").write(source)
            result = subprocess.run(
                [sys.executable, "-m", "unittest"], cwd=copy, capture_output=True, text=True, timeout=300
            )
        summary = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no output"
        killed = result.returncode != 0
        survivors += not killed
        print(f"{'KILLED  ' if killed else 'SURVIVED'} {title} -> {summary}")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
