"""Simple-collision primitives (BodySetup AggGeom) of every static mesh of one map, weighted by placement.

For each distinct mesh of a ``SquadExtract statics`` directory: how many boxes, spheres, capsules (Sphyl) and
convex hulls its BodySetup holds and how many times the mesh is placed. Totals are the per-mesh counts times the
placements, so they say how many primitives the whole map contains. Meshes without a readable body are listed
under ``errors``.

Usage: primitive_counts.py <statics dir> <out.json>
"""
import collections
import json
import os
import sys

SHAPES = {"BoxElems": "box", "SphereElems": "sphere", "SphylElems": "capsule", "ConvexElems": "convex"}


def shape_counts(body):
    """{"box", "sphere", "capsule", "convex"} counts of a bodies/<id>.json ``body`` entry (an AggGeom may be absent)."""
    props = body.get("Properties", {}) if isinstance(body, dict) else {}
    agg = props.get("AggGeom") or {}
    return {name: len(agg.get(key) or []) for key, name in SHAPES.items()}


def placements_per_mesh(directory):
    """{mesh id: number of placements} from instances.ndjson (instanced components count every instance)."""
    placements = collections.Counter()
    for line in open(os.path.join(directory, "instances.ndjson")):
        item = json.loads(line)
        placements[item["mesh"]] += len(item["instances"]) if item.get("instances") is not None else 1
    return placements


def summarize(directory):
    """Return {"totals": {shape: count over all placements}, "meshes": [...], "errors": [...]}."""
    totals = dict.fromkeys(SHAPES.values(), 0)
    meshes, errors = [], []
    for mesh, count in sorted(placements_per_mesh(directory).items()):
        try:
            info = json.load(open(os.path.join(directory, "bodies", mesh + ".json")))
        except (OSError, ValueError) as error:
            errors.append({"mesh": mesh, "placements": count, "error": str(error)})
            continue
        shapes = shape_counts(info.get("body"))
        for name, number in shapes.items():
            totals[name] += number * count
        if any(shapes.values()):
            meshes.append({"mesh": mesh, "path": info.get("path"), "placements": count, **shapes})
    return {"totals": totals, "meshes": meshes, "errors": errors}


if __name__ == "__main__":
    result = summarize(sys.argv[1])
    json.dump(result, open(sys.argv[2], "w"), indent=1)
    print(result["totals"], "meshes", len(result["meshes"]), "errors", len(result["errors"]))
