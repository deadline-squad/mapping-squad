"""Collision triangles per object class of one map, from the output of ``mesh_collision_kinds.py``.

A mesh is assigned to a class by the first matching path rule (see ``CLASS_RULES``). For every class the table lists
distinct meshes, placements, complex triangles (cooked Chaos trimesh) and simple triangles (AggGeom shapes), each also
weighted by placements, plus the count of meshes per CollisionTraceFlag.

Usage: class_table.py <kinds.json> <out.json>
"""
import collections
import json
import sys

CLASS_RULES = (
    ("roads_and_pavements", ("/Environments/Roads/",)),
    ("water_meshes", ("/Environments/water/",)),
    ("buildings", ("/Buildings/", "/Marketplace/", "/Airfield/", "/Warehouse/")),
    ("walls_fences_barriers", ("/Walls/", "/Fences/", "/Hesco", "Concrete_barrier", "/Roadside_Barrier")),
    ("vehicles_and_wrecks", ("/Vehicles/",)),
    ("props_and_infrastructure", ("/Props/", "/Street/", "/Railyard/", "/Camp/", "/Containers/", "/pipes/",
                                  "/Supplies/", "/Sewers/", "/Stairs/", "/Roadsigns/", "/3rdPartyContent/")),
    ("editor_and_blockout", ("/Engine/", "/Tools/")),
)
OTHER = "other"


def classify(path):
    """Returns the class name of an asset path: the first rule with a fragment contained in ``path``, else ``other``."""
    for name, fragments in CLASS_RULES:
        if any(fragment in path for fragment in fragments):
            return name
    return OTHER


def build(kinds):
    """Aggregates ``kinds["meshes"]`` rows into per-class totals. Returns a dict class -> counters."""
    table = collections.defaultdict(lambda: collections.Counter())
    for row in kinds["meshes"]:
        entry = table[classify(row["path"] or "")]
        placements = row["placements"]
        entry["meshes"] += 1
        entry["placements"] += placements
        entry["complex_triangles"] += row["complex_triangles"]
        entry["simple_triangles"] += row["simple_triangles"]
        entry["complex_triangles_placed"] += row["complex_triangles"] * placements
        entry["simple_triangles_placed"] += row["simple_triangles"] * placements
        entry["flag_" + row["trace_flag"]] += 1
    return {name: dict(counter) for name, counter in sorted(table.items())}


def main(kinds_file, out):
    table = build(json.load(open(kinds_file)))
    json.dump(table, open(out, "w"), indent=1)
    for name, entry in table.items():
        print(name, entry["meshes"], entry["placements"], entry["complex_triangles_placed"], entry["simple_triangles_placed"])


if __name__ == "__main__":
    main(*sys.argv[1:3])
