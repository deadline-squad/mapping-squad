"""Collision triangle counts per mesh kind of one map: complex (cooked Chaos trimesh) and simple (AggGeom shapes).

For each distinct static mesh of a ``SquadExtract statics`` directory: CollisionTraceFlag, complex triangle count
(``objects.chaos_trimeshes``), simple-shape triangle count (``objects.simple_triangles``) and the number of
placements, so triangles can be weighted by placement. Output JSON: per mesh and totals grouped by trace flag /
which representations exist.

Usage: mesh_collision_kinds.py <statics dir> <out.json>
"""
import collections
import json
import os
import sys

import objects


def mesh_row(directory, mesh):
    prefix = os.path.join(directory, "bodies", mesh)
    info = json.load(open(prefix + ".json"))
    body = info.get("body") or {}
    props = body.get("Properties", {}) if isinstance(body, dict) else {}
    flag = props.get("CollisionTraceFlag", "CTF_UseDefault").replace("CTF_", "")
    complex_count = 0
    if os.path.exists(prefix + ".Chaos.bin") and info.get("bounds"):
        lo, hi = objects.collision_bounds(info)
        meshes = objects.chaos_trimeshes(open(prefix + ".Chaos.bin", "rb").read(), lo, hi)
        complex_count = sum(len(t) for _, t in meshes) if meshes else 0
    simple = objects.simple_triangles(props.get("AggGeom") or {})
    return {"mesh": mesh, "path": info.get("path"), "trace_flag": flag, "complex_triangles": complex_count,
            "simple_triangles": 0 if simple is None else len(simple)}


def main(directory, out):
    placements = collections.Counter()
    for line in open(os.path.join(directory, "instances.ndjson")):
        item = json.loads(line)
        placements[item["mesh"]] += len(item["instances"]) if item.get("instances") is not None else 1
    rows = []
    for mesh, count in placements.items():
        try:
            row = mesh_row(directory, mesh)
        except Exception as error:
            row = {"mesh": mesh, "error": str(error)}
        row["placements"] = count
        rows.append(row)
    totals = collections.defaultdict(lambda: {"meshes": 0, "placements": 0, "complex_triangles": 0, "simple_triangles": 0})
    for row in rows:
        if "error" in row:
            key = "error"
        else:
            key = f"{row['trace_flag']} complex={'yes' if row['complex_triangles'] else 'no'} simple={'yes' if row['simple_triangles'] else 'no'}"
        t = totals[key]
        t["meshes"] += 1
        t["placements"] += row["placements"]
        t["complex_triangles"] += row.get("complex_triangles", 0) * row["placements"]
        t["simple_triangles"] += row.get("simple_triangles", 0) * row["placements"]
    json.dump({"totals": totals, "meshes": rows}, open(out, "w"), indent=1)
    for key, t in sorted(totals.items()):
        print(key, t)


if __name__ == "__main__":
    main(*sys.argv[1:3])
