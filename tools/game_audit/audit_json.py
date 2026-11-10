"""The JSON form of the audit's committed data files: one key per line, a list of numbers on one line."""
import json
import re

NUMBER_LIST = re.compile(r"\[\s+(-?[\d.e+-]+(?:,\s+-?[\d.e+-]+)*)\s+\]")


def dumps(data):
    """``data`` as indented JSON text in which every list of numbers stays on one line."""
    text = json.dumps(data, indent=1, ensure_ascii=False)
    return NUMBER_LIST.sub(lambda match: "[" + re.sub(r"\s+", " ", match.group(1)) + "]", text) + "\n"


def write(path, data):
    """Write ``data`` to ``path`` in the form of ``dumps``."""
    with open(path, "w", encoding="utf-8") as out:
        out.write(dumps(data))
