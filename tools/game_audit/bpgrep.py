"""Every property of dumped Blueprints whose name matches a pattern, at any depth, per export.

The audit's way to find where the game keeps a value before a reader is written for it: which component holds
``PitchInterval``, which widget has ``MinAngle``.

Usage::

    python3 -I bpgrep.py <regex over property names> <file.uasset.json> [...]
"""
import json
import re
import sys


def matches(value, pattern, path=""):
    """(dotted path, value) of every property under ``value`` whose name matches; a match is not searched further."""
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if pattern.search(key):
                found.append((child_path, child))
            else:
                found += matches(child, pattern, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found += matches(child, pattern, f"{path}[{index}]")
    return found


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    pattern = re.compile(argv[1], re.IGNORECASE)
    for path in argv[2:]:
        with open(path, encoding="utf-8") as dump:
            exports = json.load(dump)
        asset = path.rsplit("/", 1)[-1].removesuffix(".json")
        for export in exports:
            for where, value in matches(export.get("Properties") or {}, pattern):
                print(f"{asset} | {export['Type']} {export['Name']} | {where} = {json.dumps(value)[:300]}")


if __name__ == "__main__":
    main(sys.argv)
