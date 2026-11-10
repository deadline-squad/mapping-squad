"""The layers the calculator loads from the upstream API against the same layers of the game.

SquadCalc draws a layer (objectives, main bases, protection zones, factions) from ``<API>/get/layer?name=<layer>``,
data its upstream extracts from the game. This compares that answer with the layer of the installed build, for a list
of layers (``data/deadline_pool.txt``, the rotation of the Deadline server).

Usage::

    python3 -I api_layers.py fetch   <API> <layers.txt> <api dir>
    python3 -I api_layers.py compare <layers.txt> <api dir> <game_layers.json> <layer data dump> <calculator.json> <out.json>

``fetch`` asks for every layer and for the layer list of every map (``get/layers?map=``), at most two requests a
second, and records the HTTP status of each in ``status.tsv``. ``compare`` reads ``game_layers.json`` of
``layers.py reduce``, the layer data assets of ``game_audit.sh extract-layer-data`` and the map names of
``calculator.mjs``; it writes the result per layer and prints the counts and every layer with a difference.
Lengths are in cm, as in both sources.
"""
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import layers  # noqa: E402

# Seconds between two requests: at most two a second
REQUEST_INTERVAL = 0.6
USER_AGENT = "squadcalc-data-audit"
# cm: both sources keep positions as 32-bit floats of up to 400 000 cm
POSITION_TOLERANCE = 1.0
SIZE_TOLERANCE = 0.5
TEAM_TWO = "ESQTeam::Team_Two"


def read_list(path):
    """The layer names of a list file, one per line."""
    with open(path, encoding="utf-8") as source:
        return [line.strip() for line in source if line.strip()]


def fetch(api, layers_file, out_dir):
    """Save the API's answer for every layer of the list and the layer list of each of their maps."""
    os.makedirs(out_dir, exist_ok=True)
    names = read_list(layers_file)
    requests = [("layer", name, f"{api}/get/layer?name={urllib.parse.quote(name)}") for name in names]
    requests += [("layers", name, f"{api}/get/layers?map={urllib.parse.quote(name)}") for name in sorted({name.split("_", 1)[0] for name in names})]
    with open(os.path.join(out_dir, "status.tsv"), "w", encoding="utf-8") as status:
        for kind, name, url in requests:
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=60) as answer:
                    code, body = answer.status, answer.read()
            except urllib.error.HTTPError as error:
                code, body = error.code, b""
            with open(os.path.join(out_dir, f"{kind}_{name}.json"), "wb") as out:
                out.write(body)
            status.write(f"{kind}\t{name}\t{code}\t{len(body)}\n")
            time.sleep(REQUEST_INTERVAL)
    return len(requests)


def api_zones(node):
    """Every capture zone and main of an API layer, wherever its objective tree holds it, once per name and place."""
    found = {}

    def walk(value):
        if isinstance(value, dict):
            if "location_x" in value and "objects" in value and "objectName" in value:
                found.setdefault((value["objectName"], round(value["location_x"]), round(value["location_y"])), value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return list(found.values())


def distance(position, api_object):
    """Largest difference along an axis between a game position and an API object's ``location_*``."""
    return max(abs(position[axis] - api_object[key]) for axis, key in enumerate(("location_x", "location_y", "location_z")))


def shape_difference(api_object, shape):
    """What differs between an API shape and the game component of the same name, None when they agree.

    The game multiplies a sphere's radius by the smallest size of the component's scale, a capsule's by the smaller
    horizontal one and a box's extent by each axis; a size the level does not set is the Blueprint's, which the
    layer does not hold, and is not compared.
    """
    scale = [abs(axis) for axis in shape["scale"]]
    kinds = (bool(api_object.get("isSphere")), bool(api_object.get("isBox")), bool(api_object.get("isCapsule")))
    if kinds != tuple(shape["kind"] == kind for kind in layers.SHAPES):
        return f"kind {shape['kind']}"
    if kinds[0] and shape["radius"] is not None:
        game, api = shape["radius"] * min(scale), float(api_object["sphereRadius"])
        if abs(abs(api) - game) > SIZE_TOLERANCE:
            return f"radius {api:g} in the API, {game:g} in the game"
        if api < 0:
            return f"radius {api:g} in the API is negative, {game:g} in the game"
    if kinds[1] and shape["extent"] is not None:
        extent = api_object["boxExtent"]
        api = [abs(extent[f"extent_{axis}"] * extent.get(f"scaling_{axis}", 1.0)) for axis in "xyz"]
        game = [shape["extent"][axis.upper()] * scale[index] for index, axis in enumerate("xyz")]
        if max(abs(a - g) for a, g in zip(api, game)) > SIZE_TOLERANCE:
            return f"extent {api} in the API, {game} in the game"
    if kinds[2] and shape["radius"] is not None:
        game, api = shape["radius"] * min(scale[0], scale[1]), float(api_object["capsuleRadius"])
        if abs(api - game) > SIZE_TOLERANCE:
            return f"capsule radius {api:g} in the API, {game:g} in the game"
    return None


def compare_zones(api_layer, game_layer):
    """Capture zones and mains of one layer: counts, worst position difference and what differs."""
    zones = api_zones(api_layer.get("objectives"))
    mains = [zone for zone in game_layer["zones"] if "Main" in zone["type"]]
    capture = [zone for zone in game_layer["zones"] if "CaptureZone" in zone["type"] and "Cluster" not in zone["type"] and "Main" not in zone["type"]]
    by_name = {zone["name"]: zone for zone in game_layer["zones"]}
    result = {"api": len(zones), "game": len(capture), "mains": len(mains), "worst_position": 0.0,
              "not_in_game": [], "flag_names": [], "shapes": [], "shape_positions": []}
    matched = set()
    for zone in zones:
        name = zone["objectName"]
        game = by_name.get(name) or by_name.get(name.replace(" ", ""))
        if game is None:
            nearest = min((candidate for candidate in game_layer["zones"] if candidate["loc"]), key=lambda candidate: distance(candidate["loc"], zone), default=None)
            game = nearest if nearest is not None and distance(nearest["loc"], zone) < POSITION_TOLERANCE else None
        if game is None:
            result["not_in_game"].append(name)
            continue
        matched.add(game["name"])
        result["worst_position"] = max(result["worst_position"], distance(game["loc"], zone))
        if game["flag"] is not None and zone.get("name") is not None and game["flag"] != zone["name"]:
            result["flag_names"].append([zone["name"], game["flag"]])
        shapes = {shape["name"]: shape for shape in game["shapes"]}
        for api_object in zone.get("objects", []):
            shape = shapes.get(api_object["objectName"])
            if shape is None:
                result["shapes"].append(f"{name}/{api_object['objectName']}: no such component in the game")
                continue
            offset = distance(shape["loc"], api_object)
            if offset > POSITION_TOLERANCE:
                result["shape_positions"].append({"zone": name, "shape": shape["name"], "cm": round(offset, 1), "zone_tilted": shape["parent_tilted"]})
            difference = shape_difference(api_object, shape)
            if difference:
                result["shapes"].append(f"{name}/{shape['name']}: {difference}")
        if len(zone.get("objects", [])) != len(game["shapes"]):
            result["shapes"].append(f"{name}: {len(zone.get('objects', []))} shapes in the API, {len(game['shapes'])} in the game")
    result["not_in_api"] = sorted(zone["name"] for zone in capture + mains if zone["name"] not in matched)
    result["worst_position"] = round(result["worst_position"], 3)
    return result


def compare_protection(api_layer, game_layer, default_lock):
    """Protection zones of one layer: per API zone the game zone of the same team nearest to it, lock distance and shape.

    Returns {"zones": count, "lock": [differences], "shapes": [differences], "spheres": n, "boxes": n}.
    """
    result = {"zones": 0, "lock": [], "shapes": [], "spheres": 0, "boxes": 0}
    for zone in (api_layer.get("mapAssets") or {}).get("protectionZones", []):
        result["zones"] += 1
        label = zone.get("displayName") or f"team {zone.get('teamid')}"
        api_object = zone["objects"][0]
        candidates = [(candidate, shape) for candidate in game_layer["protection"] if str(candidate["scalars"].get("TeamId")) == str(zone.get("teamid"))
                      for shape in candidate["shapes"] if shape["name"] == api_object["objectName"]]
        if not candidates:
            result["shapes"].append(f"{label}: no zone of that team with a component {api_object['objectName']} in the game")
            continue
        game, shape = min(candidates, key=lambda pair: distance(pair[1]["loc"], api_object))
        lock = game["scalars"].get("DeployableLockDistance", default_lock)
        if abs(zone["deployableLockDistance"] - lock) > SIZE_TOLERANCE:
            result["lock"].append(f"{label}: lock distance {zone['deployableLockDistance']:g} in the API, {lock:g} in the game")
        result["spheres" if shape["kind"] == "SphereComponent" else "boxes"] += 1
        difference = shape_difference(api_object, shape)
        if difference:
            result["shapes"].append(f"{label}: {difference}")
    return result


def asset_name(reference):
    """Name of the asset a soft reference of a layer data asset points to, None for none."""
    path = (reference or {}).get("AssetPathName")
    return path.rsplit(".", 1)[-1] if path else None


def compare_settings(api_layer, layer_data):
    """Game mode, default faction unit and tickets of both teams and the faction units offered: what differs."""
    layer = next(export for export in layer_data if export["Type"] == "BP_SQLayer_C")["Properties"]
    teams = {2 if export["Properties"].get("Index") == TEAM_TWO else 1: export["Properties"] for export in layer_data if export["Type"] == "BP_SQLayerTeamConfig_C"}
    differences = []
    mode = (layer.get("GameMode") or {}).get("RowName")
    if api_layer.get("gamemode") != mode:
        differences.append(f"game mode {api_layer.get('gamemode')} in the API, {mode} in the game")
    for team in (1, 2):
        api_team = (api_layer.get("teamConfigs") or {}).get(f"team{team}") or {}
        game_team = teams.get(team) or {}
        unit = asset_name(game_team.get("SpecificFactionSetup"))
        if api_team.get("defaultFactionUnit") != unit:
            differences.append(f"team {team} default unit {api_team.get('defaultFactionUnit')} in the API, {unit} in the game")
        if game_team.get("Tickets") is not None and api_team.get("tickets") != game_team["Tickets"]:
            differences.append(f"team {team} tickets {api_team.get('tickets')} in the API, {game_team['Tickets']} in the game")
    game_units = set()
    for entry in layer.get("FactionsList", []):
        game_units.add(asset_name(entry["Value"].get("Faction")))
        game_units.update(asset_name(kind["Value"]) for kind in entry["Value"].get("Types", []))
    game_units.discard(None)
    api_units = {unit["unitObjectName"] for side in (api_layer.get("units") or {}).values() for unit in side}
    if api_units != game_units:
        differences.append(f"units only in the API {sorted(api_units - game_units)[:5]}, only in the game {sorted(game_units - api_units)[:5]}")
    return differences, len(api_units), len(game_units)


def compare_layer(name, api_layer, listed, game_layer, layer_data, map_names, default_lock):
    """Everything compared for one layer whose API answer was read; ``issues`` lists what differs in words."""
    result = {"issues": [], "listed": listed, "mapId": api_layer.get("mapId")}
    issues = result["issues"]
    if api_layer.get("rawName") != name:
        issues.append(f"rawName {api_layer.get('rawName')}")
    if not listed:
        issues.append("not in the API's layer list of its map")
    if api_layer.get("mapId") not in map_names:
        issues.append(f"map {api_layer.get('mapId')} is not a map of the calculator")
    if game_layer is None:
        issues.append("no such layer in the game build")
        return result
    api_corners = sorted((corner["location_x"], corner["location_y"]) for corner in api_layer.get("mapTextureCorners", []))
    game_corners = sorted((game_layer[key][0], game_layer[key][1]) for key in ("MapTextureCornerZero", "MapTextureCornerOne"))
    result["corners"] = round(max(abs(a[axis] - g[axis]) for a, g in zip(api_corners, game_corners) for axis in (0, 1)), 3) if len(api_corners) == 2 else None
    if result["corners"] is None or result["corners"] > SIZE_TOLERANCE:
        issues.append(f"minimap corners differ by {result['corners']} cm")
    texture = (game_layer.get("texture") or "").split("'")[1] if game_layer.get("texture") else None
    if api_layer.get("mapTexture") != texture:
        issues.append(f"minimap texture {api_layer.get('mapTexture')} in the API, {texture} in the game")
    zones = result["zones"] = compare_zones(api_layer, game_layer)
    if zones["worst_position"] > POSITION_TOLERANCE:
        issues.append(f"objective positions differ by up to {zones['worst_position']} cm")
    if zones["not_in_game"]:
        issues.append(f"API zones not in the game layer: {zones['not_in_game']}")
    if zones["not_in_api"]:
        issues.append(f"game zones missing in the API: {zones['not_in_api']}")
    if zones["flag_names"]:
        issues.append(f"flag names differ (API, game): {zones['flag_names']}")
    if zones["shape_positions"]:
        issues.append("capture-area positions differ: " + ", ".join(f"{p['zone']}/{p['shape']} {p['cm']} cm ({'zone tilted' if p['zone_tilted'] else 'zone level'})" for p in zones["shape_positions"]))
    if zones["shapes"]:
        issues.append(f"capture-area shapes: {zones['shapes']}")
    protection = result["protection"] = compare_protection(api_layer, game_layer, default_lock)
    issues += protection["lock"] + [f"protection zone {text}" for text in protection["shapes"]]
    if layer_data is None:
        issues.append("no layer data asset in the game build")
        return result
    differences, result["units_api"], result["units_game"] = compare_settings(api_layer, layer_data)
    issues += differences
    return result


def compare(layers_file, api_dir, game_file, layer_data_root, calculator_file, out_file):
    """Compare every layer of the list; write the result per layer and return the summary lines."""
    def load(path):
        with open(path, encoding="utf-8") as source:
            return json.load(source)

    game = load(game_file)
    map_names = {entry["name"] for entry in load(calculator_file)["maps"]}
    status = {}
    with open(os.path.join(api_dir, "status.tsv"), encoding="utf-8") as source:
        for line in source:
            kind, name, code = line.rstrip("\n").split("\t")[:3]
            status[(kind, name)] = code
    data_assets = {os.path.basename(path)[: -len(".uasset.json")]: path
                   for path in glob.glob(os.path.join(layer_data_root, "**", "Gameplay_Layer_Data", "*.uasset.json"), recursive=True)}
    zone_blueprint = glob.glob(os.path.join(layer_data_root, "**", "Gameplay_TeamZone.uasset.json"), recursive=True)[0]
    default_lock = layers.default_lock_distance(load(zone_blueprint))
    results = {}
    for name in read_list(layers_file):
        if status.get(("layer", name)) != "200":
            results[name] = {"issues": [f"the API answers {status.get(('layer', name))}"]}
            continue
        map_name = name.split("_", 1)[0]
        listed = status.get(("layers", map_name)) == "200" and any(row.get("rawName") == name for row in load(os.path.join(api_dir, f"layers_{map_name}.json")))
        layer_data = load(data_assets[name]) if name in data_assets else None
        results[name] = compare_layer(name, load(os.path.join(api_dir, f"layer_{name}.json")), listed, game.get(name), layer_data, map_names, default_lock)
    with open(out_file, "w", encoding="utf-8") as out:
        json.dump(results, out, indent=1)
    return results


def summary(results):
    """The counts over all compared layers, as printed lines."""
    compared = [result for result in results.values() if "zones" in result]
    protection = [result["protection"] for result in compared]
    return [
        f"{len(results)} layers, {sum(1 for result in results.values() if not result['issues'])} without a difference",
        f"answered and listed by the API: {sum(1 for result in results.values() if result.get('listed'))}",
        f"minimap corners: largest difference {max((result['corners'] or 0.0 for result in compared), default=0.0)} cm",
        f"capture zones and mains: {sum(result['zones']['api'] for result in compared)} in the API, "
        f"{sum(result['zones']['game'] + result['zones']['mains'] for result in compared)} in the game, "
        f"largest position difference {max((result['zones']['worst_position'] for result in compared), default=0.0)} cm",
        f"protection zones: {sum(p['zones'] for p in protection)} ({sum(p['spheres'] for p in protection)} spheres, {sum(p['boxes'] for p in protection)} boxes), "
        f"{sum(len(p['lock']) for p in protection)} lock distances differ, {sum(len(p['shapes']) for p in protection)} shapes differ",
    ]


def main(argv):
    command, arguments = (argv[1], argv[2:]) if len(argv) > 1 else (None, [])
    if command == "fetch" and len(arguments) == 3:
        print(fetch(*arguments), "requests")
    elif command == "compare" and len(arguments) == 6:
        results = compare(*arguments)
        print("\n".join(summary(results)))
        for name, result in results.items():
            if result["issues"]:
                print(name, "|", " ; ".join(re.sub(r"\s+", " ", issue) for issue in result["issues"]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
