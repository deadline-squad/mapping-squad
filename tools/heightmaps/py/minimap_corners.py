"""The game's minimap corners of every gameplay layer, and the table of them against SquadCalc's maps.js.

The game starts its map grid (A1) at the north-west corner of the minimap: ``MapTextureCornerZero`` and
``MapTextureCornerOne`` of the layer's ``SQWorldSettings`` name two actors whose location (cm, UE axes, +Y south)
is the corner. Every layer of a map names its own pair; Skirmish and Seed layers ship a smaller minimap.

Usage::

    python3 -I minimap_corners.py dump  <layers.txt> <extractor> <workdir> <corners.ndjson>
    python3 -I minimap_corners.py table <corners.ndjson> <game.json>

``layers.txt`` lists the ``Gameplay_Layers/*.umap`` paths (``SquadExtract list Gameplay_Layers/``). ``extractor`` is
a command that runs ``SquadExtract <paks> dumpall <regex> /out`` with ``/out`` mapped to ``<workdir>`` (for
example a shell script around ``docker run``, see ``heightmaps.sh``). One run dumps the layers of one map at a time
(a layer is about 55 MB of JSON) and keeps only the corners. ``table`` writes, per map, the modal corners of its
regular layers in metres and the layers that differ (``game.json``, the source of ``SDK_data.minimap.game`` in
SquadCalc's ``src/data/maps.js``).
"""
import collections
import json
import os
import re
import shutil
import subprocess
import sys

# Level folder (or plugin) name in the package -> SquadCalc map name
MAP_NAMES = {
    "Al_Basrah": "AlBasrah", "Fools_Road": "FoolsRoad", "Goose_Bay": "GooseBay", "Jensens_Range": "Jensen",
    "Kamdesh_Highlands": "Kamdesh", "Kokan_Valley": "Kokan", "Lashkar_Valley": "Lashkar", "Logar_Valley": "Logar",
    "Mestia_Green": "Mestia", "PacificProvingGrounds": "Pacific", "Tallil_Outskirts": "Tallil",
    "Fallujah_City": "Fallujah", "SanxianIslands": "Sanxian",
}


def corner(export_list, world_settings, key):
    """Location (cm) of the actor ``world_settings[key]`` points to: its root component's RelativeLocation."""
    reference = world_settings.get(key)
    if not reference:
        return None
    actor = reference["ObjectName"].split(".")[-1].rstrip("'")
    for export in export_list:
        if export["Type"] in ("SceneComponent", "StaticMeshComponent") and export["Outer"]["ObjectName"].endswith("." + actor + "'"):
            return export["Properties"].get("RelativeLocation")
    return None


def dump(layers_file, extractor, workdir, out_file):
    """Dump every layer, one map at a time, and append its corners to ``out_file`` (ndjson)."""
    layers = [line.strip() for line in open(layers_file) if line.strip()]
    groups = {}
    for layer in layers:
        groups.setdefault(layer[: layer.index("/Gameplay_Layers/")], []).append(layer)
    with open(out_file, "a") as out:
        for group, group_layers in groups.items():
            regex = "^" + re.escape(group) + r"/Gameplay_Layers/[^/]*\.umap$"
            subprocess.run([extractor, "dumpall", regex, "/out"], check=True, stderr=subprocess.DEVNULL)
            for layer in group_layers:
                path = os.path.join(workdir, layer + ".json")
                exports = json.load(open(path))
                settings = next((e["Properties"] for e in exports if e["Type"] == "SQWorldSettings"), None)
                record = {"layer": layer}
                if settings is None:
                    record["error"] = "no SQWorldSettings"
                else:
                    record["c0"] = corner(exports, settings, "MapTextureCornerZero")
                    record["c1"] = corner(exports, settings, "MapTextureCornerOne")
                    record["texture"] = (settings.get("MapTexture") or {}).get("ObjectName")
                out.write(json.dumps(record) + "\n")
                os.remove(path)
            shutil.rmtree(os.path.join(workdir, "SquadGame"), ignore_errors=True)


def table(corners_file, game_file):
    """Modal corners (m) per map and the layers that differ; written to ``game_file``."""
    per_map = collections.defaultdict(list)
    for line in open(corners_file):
        record = json.loads(line)
        if "error" in record or not record["c0"] or not record["c1"]:
            continue
        folder = re.search(r"Plugins/(?:Expansions/)?([^/]+)/Content/Maps/Gameplay", record["layer"]) or re.search(r"Maps/([^/]+)/Gameplay_Layers", record["layer"])
        name = MAP_NAMES.get(folder.group(1), folder.group(1))
        a, b = record["c0"].get("loc", record["c0"]), record["c1"].get("loc", record["c1"])
        if a is None or b is None:
            continue
        low = [round(min(a["X"], b["X"]) / 100, 2), round(min(a["Y"], b["Y"]) / 100, 2)]
        high = [round(max(a["X"], b["X"]) / 100, 2), round(max(a["Y"], b["Y"]) / 100, 2)]
        per_map[name].append((os.path.basename(record["layer"])[:-5], low, high))
    result = {}
    for name, layers in per_map.items():
        (low, high), regular = collections.Counter((tuple(l[1]), tuple(l[2])) for l in layers).most_common(1)[0]
        result[name] = {
            "min": list(low), "max": list(high), "layers": len(layers), "regular": regular,
            "variants": [{"layer": l[0], "min": l[1], "max": l[2]} for l in layers if (tuple(l[1]), tuple(l[2])) != (low, high)],
        }
    json.dump(result, open(game_file, "w"), indent=1)


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "dump":
        dump(*sys.argv[2:])
    elif len(sys.argv) == 4 and sys.argv[1] == "table":
        table(*sys.argv[2:])
    else:
        sys.exit(__doc__)
