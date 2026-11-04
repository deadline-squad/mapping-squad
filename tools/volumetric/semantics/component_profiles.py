"""Collision profile and Projectile-channel response of every Blueprint component in a dump (vehicles, deployables, doors).

Walks the ``dumpall`` JSON files below a directory; every export that carries a BodyInstance-like object with a
``CollisionProfileName`` is reported with the response to the Projectile channel (listed responses in the
serialised container; unlisted channels are Block, see static_semantics.py). Grouped by the first two directories
below SquadGame/Content.

Usage: component_profiles.py <dump dir> [<dump dir> ...]   (JSON on stdout)
"""
import collections
import json
import os
import sys


def bodies(node):
    if isinstance(node, dict):
        if "CollisionProfileName" in node:
            yield node
        for value in node.values():
            yield from bodies(value)
    elif isinstance(node, list):
        for value in node:
            yield from bodies(value)


def main(roots):
    table = collections.Counter()
    examples = {}
    for root in roots:
        content = os.path.join(root, "SquadGame", "Content")
        for directory, _, files in os.walk(content):
            group = "/".join(os.path.relpath(directory, content).split(os.sep)[:2])
            for name in files:
                if not name.endswith(".uasset.json"):
                    continue
                data = json.load(open(os.path.join(directory, name)))
                if not isinstance(data, list):
                    continue
                for export in data:
                    for body in bodies(export.get("Properties") or {}):
                        listed = {r["Channel"]: r["Response"][4:] for r in (body.get("CollisionResponses") or {}).get("ResponseArray", [])}
                        enabled = (body.get("CollisionEnabled") or "default").split("::")[-1]
                        projectile = "Ignore" if enabled in ("NoCollision", "PhysicsOnly") else listed.get("Projectile", "Block")
                        key = (group, export.get("Type"), body["CollisionProfileName"], enabled, projectile)
                        table[key] += 1
                        examples.setdefault(key, f"{name[:-len('.uasset.json')]}:{export.get('Name')}")
    rows = [dict(zip(("group", "component_type", "profile", "collision_enabled", "projectile"), k), count=n, example=examples[k]) for k, n in table.most_common()]
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
