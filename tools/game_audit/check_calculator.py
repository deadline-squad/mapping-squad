"""SquadCalc's map and weapon data against the game data of ``data/``.

Usage::

    python3 -I check_calculator.py <calculator.json> <data dir>

``calculator.json`` is the output of ``calculator.mjs`` (the calculator's ``weapons.js`` and ``maps.js`` and what its
own solver gives at the stops of the game's mounts). Checked, each against the file of ``data/`` named:

* elevation limits of the artillery weapons = pitch range of the mount + what the sight adds (``mount_limits.json``);
* minimum distance of a weapon its mount stops short of the near ground = the range on level ground at that stop;
* range circle of the mortar and hell cannon markers = the longest shot of the weapon, in whole metres;
* landscape origin, size and scale of every map (``landscapes.json``);
* the game's minimap corners of every map, and the image corners within a metre of them (``minimap_corners.json``);
* FOB exclusion radius of every layer (``fob_radius.json``).

Prints one line per difference and exits 1 when there is one. A difference listed in ``KNOWN`` is printed with its
reason and does not fail the check: it is open in ``docs/game-data-audit.md``.
"""
import json
import os
import sys

# Degrees: below the 0.1 degree a sight shows; the cooked values are 32-bit floats
LIMIT_TOLERANCE = 0.005
# Metres: minimum distances are kept to 0.1 m
MIN_DISTANCE_TOLERANCE = 0.05
# Metres: maps.js keeps the image corners in whole metres
WHOLE_METRE = 1.0
# Metres: and the landscape's first vertex to the millimetre (the heightmap's samples are the landscape's vertices)
ORIGIN_TOLERANCE = 0.0005
SCALE_TOLERANCE = 1e-3
# Metres: maps.js keeps the game's corners to the centimetre
CORNER_TOLERANCE = 0.005
# Metres the longest shot at any elevation may exceed the longest the mount allows before it is reported
REACH_TOLERANCE = 1.0

# Differences that are open and documented: (check, subject) -> the entry of docs/game-data-audit.md and why it stays
KNOWN = {
    ("reach", "UB-32"): "O3: the range circle is the longest shot at any elevation, as in Squad Ballistics; a solution beyond the mount's reach is refused",
    ("reach", "M1064M121"): "O3: the range circle is the longest shot at any elevation, as in Squad Ballistics; a solution beyond the mount's reach is refused",
    ("image corners", "Skorpo"): "the map image was fitted 9.5 m and 10.5 m off; the grid uses the game's corners",
}


def stopped_by_mount(angle_type, low, high):
    """Whether a mount stops the barrel short of the near ground: which arc the weapon fires and where that arc ends.

    A weapon fired on the high arc lands nearer the steeper it is laid, down to 0 m at the vertical; one fired on
    the low arc lands nearer the flatter, and reaches the ground in front of it once the barrel points below the
    horizon. ``low`` and ``high`` are barrel elevations in degrees.
    """
    return high < 90 if angle_type == "high" else low >= 0


def limit_differences(weapons, mounts):
    """Weapons whose elevation limits are not the game's reading range."""
    differences = []
    for weapon in weapons:
        reading = mounts[weapon["name"]]["reading"]
        if any(abs(used - game) > LIMIT_TOLERANCE for used, game in zip(weapon["minElevation"], reading)):
            differences.append(("limits", weapon["name"], f"elevation limits {weapon['minElevation']}, the game's {reading}"))
    return differences


def min_distance_differences(weapons, mounts):
    """Shells whose minimum distance is not the range at the stop of the mount (0 for a mount that does not stop it)."""
    differences = []
    for weapon in weapons:
        low, high = (reading + weapon["angleOffset"] for reading in mounts[weapon["name"]]["reading"])
        stopped = stopped_by_mount(weapon["angleType"], low, high)
        for shell in weapon["shells"]:
            expected = (shell["atHighStop"] if weapon["angleType"] == "high" else shell["atLowStop"]) if stopped else 0.0
            if abs(shell["minDistance"] - expected) > MIN_DISTANCE_TOLERANCE:
                stop = high if weapon["angleType"] == "high" else low
                differences.append(("min distance", weapon["name"], f"shell {shell['name']}: minimum distance {shell['minDistance']} m, "
                                    + (f"{expected:.2f} m at the mount's stop {stop:g} degrees" if stopped else "the mount does not stop it: 0")))
    return differences


def reach_differences(weapons):
    """Weapons whose longest shot at any elevation is beyond the longest their mount allows."""
    differences = []
    for weapon in weapons:
        shell = max(weapon["shells"], key=lambda candidate: candidate["maxRange"] - candidate["reach"])
        if shell["maxRange"] - shell["reach"] > REACH_TOLERANCE:
            differences.append(("reach", weapon["name"], f"longest shot {shell['maxRange']:.0f} m, {shell['reach']:.0f} m with the mount's pitch range"))
    return differences


def circle_differences(circles):
    """Marker circles that are not the weapon's longest shot in whole metres."""
    return [("circle", name, f"range circle {circle['radius']} m, longest shot {circle['maxRange']:.2f} m")
            for name, circle in circles.items() if circle["radius"] != round(circle["maxRange"])]


def landscape_differences(maps, landscapes):
    """Maps whose ``SDK_data.heightmap`` is not the game's landscape: origin to the millimetre, size, scale."""
    differences = []
    for entry in maps:
        used, game = entry["heightmap"], landscapes.get(entry["name"])
        if game is None:
            differences.append(("landscape", entry["name"], "no landscape in the game data"))
            continue
        problems = []
        if any(abs(used["origin"][axis] - game["origin_m"][axis]) > ORIGIN_TOLERANCE for axis in (0, 1)):
            problems.append(f"origin {used['origin']}, the game's {game['origin_m']}")
        if list(used["size"]) != game["size_vertices"]:
            problems.append(f"size {used['size']}, the game's {game['size_vertices']}")
        if any(abs(used["scale"][axis] - game["scale_m"][axis]) > SCALE_TOLERANCE for axis in (0, 1, 2)):
            problems.append(f"scale {used['scale']}, the game's {game['scale_m']}")
        if problems:
            differences.append(("landscape", entry["name"], "; ".join(problems)))
    return differences


def corner_differences(maps, corners):
    """Maps whose ``minimap.game`` is not the game's corners, or whose image corners are a metre or more off them."""
    differences = []
    for entry in maps:
        game, minimap = corners.get(entry["name"]), entry["minimap"]
        if game is None:
            differences.append(("game corners", entry["name"], "no minimap corners in the game data"))
            continue
        used = minimap["game"]
        if any(abs(used[side][axis] - game[side][axis]) > CORNER_TOLERANCE for side in ("min", "max") for axis in (0, 1)):
            differences.append(("game corners", entry["name"], f"minimap.game {used['min']} / {used['max']}, the game's {game['min']} / {game['max']}"))
        image = {"min": [min(minimap["corner0"][axis], minimap["corner1"][axis]) for axis in (0, 1)],
                 "max": [max(minimap["corner0"][axis], minimap["corner1"][axis]) for axis in (0, 1)]}
        worst = max(abs(image[side][axis] - game[side][axis]) for side in ("min", "max") for axis in (0, 1))
        if worst > WHOLE_METRE:
            differences.append(("image corners", entry["name"], f"image corners {image['min']} / {image['max']} are {worst:.2f} m off the game's"))
    return differences


def map_of(layer, map_names):
    """The map of ``map_names`` a layer belongs to by its name (``AlBasrah_RAAS_v3``), None for a layer of no such map."""
    return next((name for name in map_names if layer.startswith(name + "_")), None)


def fob_differences(maps, small_layers, fob):
    """Layers whose FOB exclusion radius in the calculator is not the game's.

    The calculator gives a layer 300 m when it is listed in ``SMALL_FOB_LAYERS`` and the radius of its map
    otherwise. Layers of maps the calculator does not have (the tutorials) are not compared.
    """
    radius_of = {entry["name"]: entry["radiusExclusion"] for entry in maps}
    small = set(small_layers)
    differences = []
    for layer, row in fob["layers"].items():
        name = map_of(layer, radius_of)
        if name is None:
            continue
        used, game = (300 if layer in small else radius_of[name]), fob["rows"][row]["exclusion_m"]
        if used != game:
            differences.append(("fob radius", layer, f"exclusion radius {used} m, the game's {game:g} m (row {row})"))
    differences += [("fob radius", layer, "listed in SMALL_FOB_LAYERS, not a layer of the game") for layer in sorted(small - set(fob["layers"]))]
    return differences


def differences(calculator, data):
    """Every difference between the calculator and the game data, as (check, subject, text)."""
    return (limit_differences(calculator["weapons"], data["mount_limits"])
            + min_distance_differences(calculator["weapons"], data["mount_limits"])
            + reach_differences(calculator["weapons"])
            + circle_differences(calculator["circles"])
            + landscape_differences(calculator["maps"], data["landscapes"])
            + corner_differences(calculator["maps"], data["minimap_corners"])
            + fob_differences(calculator["maps"], calculator["smallFobLayers"], data["fob_radius"]))


def load_data(directory):
    """The game data files of ``directory`` by name."""
    data = {}
    for name in ("source", "mount_limits", "landscapes", "minimap_corners", "fob_radius"):
        with open(os.path.join(directory, name + ".json"), encoding="utf-8") as source:
            data[name] = json.load(source)
    return data


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    with open(argv[1], encoding="utf-8") as source:
        calculator = json.load(source)
    data = load_data(argv[2])
    found = differences(calculator, data)
    unexplained = [difference for difference in found if difference[:2] not in KNOWN]
    for check, subject, text in found:
        known = KNOWN.get((check, subject))
        print(f"{'KNOWN' if known else 'DIFFERS'} {check}: {subject}: {text}" + (f" [{known}]" if known else ""))
    small = sum(1 for layer in calculator["smallFobLayers"] if layer in data["fob_radius"]["layers"])
    print(f"SquadCalc {calculator['version']} against Squad build {data['source']['squad_dedicated_server_build']}: "
          f"{len(calculator['weapons'])} mounts, {len(calculator['maps'])} maps, {len(data['fob_radius']['layers'])} layers "
          f"({small} with the small FOB radius on a map of the medium one); "
          f"{len(unexplained)} differences, {len(found) - len(unexplained)} known")
    return 1 if unexplained else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
