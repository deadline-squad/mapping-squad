"""The landscape of every map in the game: where its first vertex is, how many vertices it has, their spacing.

A landscape actor (``Landscape`` or ``LandscapeStreamingProxy``) has a location, a rotation and a scale, and its
terrain is a set of collision components at whole offsets (in quads) from the actor. The first vertex of the
terrain is therefore the actor's location plus the offset of its lowest component, turned and scaled with the actor.
On most maps the components start at the actor; on Chora they start 762 m south of it. SquadCalc's
``SDK_data.heightmap`` of ``maps.js`` holds the same three things per map: ``origin`` (metres), ``size`` (vertices)
and ``scale`` (metres per vertex and per height unit).

Usage::

    python3 -I landscapes.py <landscapes root> <landscapes.json>

``<landscapes root>`` is the landscape extraction of ``tools/heightmaps/heightmaps.sh extract`` or of
``game_audit.sh extract-landscapes`` (``$WORK/landscapes``): per level, ``root_<actor>.*.json`` with the actor's
transform and one JSON per ``LandscapeHeightfieldCollisionComponent``. The levels of a map are named by
``tools/heightmaps/py/maps.py``.
"""
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "heightmaps", "py"))

import audit_json  # noqa: E402
import maps as heightmap_maps  # noqa: E402


def actor_of(export):
    """Name of the actor that owns a dumped component."""
    return export["Outer"]["ObjectName"].split(".")[-1].rstrip("'")


def read_level(directory):
    """{actor: {"location", "scale", "yaw", "low", "high", "components"}} of one extracted level.

    ``location`` and ``scale`` are the actor's (cm, cm per quad and per height unit), ``low`` and ``high`` the
    corners of the rectangle its components cover, in quads from the actor.
    """
    actors = {}
    for path in glob.glob(os.path.join(directory, "root_*.json")):
        with open(path, encoding="utf-8") as dump:
            export = json.load(dump)
        properties = export["Properties"]
        location, scale = properties.get("RelativeLocation", {}), properties.get("RelativeScale3D", {})
        actors[actor_of(export)] = {
            "location": [location.get(axis, 0.0) for axis in "XYZ"], "scale": [scale.get(axis, 1.0) for axis in "XYZ"],
            "yaw": (properties.get("RelativeRotation") or {}).get("Yaw", 0.0), "low": None, "high": None, "components": 0,
        }
    for path in glob.glob(os.path.join(directory, "*.json")):
        if os.path.basename(path).startswith("root_"):
            continue
        with open(path, encoding="utf-8") as dump:
            export = json.load(dump)
        properties = export["Properties"]
        offset = properties.get("RelativeLocation", {})
        x, y, quads = round(offset.get("X", 0)), round(offset.get("Y", 0)), properties["CollisionSizeQuads"]
        actor = actors[actor_of(export)]
        actor["low"] = [x, y] if actor["low"] is None else [min(actor["low"][0], x), min(actor["low"][1], y)]
        actor["high"] = [x + quads, y + quads] if actor["high"] is None else [max(actor["high"][0], x + quads), max(actor["high"][1], y + quads)]
        actor["components"] += 1
    return {name: actor for name, actor in actors.items() if actor["components"]}


def first_vertex(actor):
    """World position (cm) of the lowest vertex of an actor's components: its offset scaled, turned by the yaw, moved."""
    x, y = actor["low"][0] * actor["scale"][0], actor["low"][1] * actor["scale"][1]
    yaw = math.radians(actor["yaw"])
    return [actor["location"][0] + x * math.cos(yaw) - y * math.sin(yaw), actor["location"][1] + x * math.sin(yaw) + y * math.cos(yaw)]


def describe(level, name, actor):
    """One actor as it is written to the data file: metres, vertices, degrees."""
    return {
        "level": level, "actor": name, "components": actor["components"],
        "location_m": [round(value / 100, 3) for value in actor["location"]], "yaw": round(actor["yaw"], 6),
        "first_quad": actor["low"], "origin_m": [round(value / 100, 3) for value in first_vertex(actor)],
        "size_vertices": [actor["high"][axis] - actor["low"][axis] + 1 for axis in (0, 1)],
        "scale_m": [round(value / 100, 6) for value in actor["scale"]],
    }


def landscape(actors):
    """Origin, size and scale of a map from its described actors.

    One actor is the landscape. Several (Fallujah's streaming proxies) are joined into the rectangle they cover,
    which needs them to share a scale and to be unturned; ValueError otherwise.
    """
    if len(actors) == 1:
        return {key: actors[0][key] for key in ("origin_m", "size_vertices", "scale_m", "yaw")}
    scale = actors[0]["scale_m"]
    if any(actor["scale_m"] != scale or actor["yaw"] for actor in actors):
        raise ValueError("landscape actors with different scales or a rotation cannot be joined")
    low = [min(actor["origin_m"][axis] for actor in actors) for axis in (0, 1)]
    high = [max(actor["origin_m"][axis] + (actor["size_vertices"][axis] - 1) * scale[axis] for actor in actors) for axis in (0, 1)]
    return {"origin_m": low, "size_vertices": [round((high[axis] - low[axis]) / scale[axis]) + 1 for axis in (0, 1)], "scale_m": scale, "yaw": 0.0}


def read(root):
    """{SquadCalc map name: landscape with its actors} for every map of ``tools/heightmaps/py/maps.py``."""
    result = {}
    for name, levels in heightmap_maps.MAPS.values():
        actors = []
        for level in levels:
            for actor_name, actor in sorted(read_level(os.path.join(root, level)).items()):
                actors.append(describe(level.rsplit("/", 1)[-1], actor_name, actor))
        if not actors:
            raise FileNotFoundError(f"{name}: no landscape under {root} for {levels}")
        result[name] = {**landscape(actors), "actors": actors}
    return result


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    audit_json.write(argv[2], read(argv[1]))


if __name__ == "__main__":
    main(sys.argv)
