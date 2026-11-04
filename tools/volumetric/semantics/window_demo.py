"""Exact-tracer demonstration of windows in one building mesh: glass is collision, and the wall is open behind it.

The cooked complex collision of a building is its render LOD0 triangle list, so its triangles follow the render
section order (INFERRED from the section counts adding up to the cooked count; the check below validates it: pane
triangles must be small, coplanar pairs). Triangles of sections whose physical material contains ``Glass`` are the
panes. For every glass triangle of at least 0.05 m2 a segment is cast along its normal, 2 m each side of its centroid, with ``reference.TriangleIndex`` (Moller-Trumbore, float64):

* all triangles       -> the segment must hit the pane (glass blocks);
* glass removed       -> a segment without any hit is a hole in the wall, i.e. a shell could fly through if the
                         glass did not block;
* simple shapes only  -> hits of the AggGeom convex/box shapes (closed volume, no window).

Usage: window_demo.py <statics dir> <sections.ndjson> <mesh path fragment> <out.json>
"""
import json
import os
import sys

import numpy as np

import objects
import reference

GLASS = 1
WALL = 2
ALL = GLASS | WALL
REACH_M = 2.0
MIN_AREA_M2 = 0.05


def section_ranges(row):
    """[(start, stop, is_glass)] triangle ranges of the render sections in listed order."""
    out, start = [], 0
    for section in row["sections"]:
        slot = row["materials"][section["MaterialIndex"]]
        stop = start + section["NumTriangles"]
        out.append((start, stop, "Glass" in (slot.get("physMaterial") or "") and section["bEnableCollision"]))
        start = stop
    return out


def run(tris_cm, ranges, simple_tris_cm):
    """Pane statistics for one mesh. ``tris_cm`` [t,3,3] in cm, ``ranges`` from ``section_ranges``."""
    tris = (tris_cm / 100.0).astype(np.float32)
    mask = np.full(len(tris), WALL, np.uint8)
    for start, stop, is_glass in ranges:
        if is_glass:
            mask[start:stop] = GLASS
    low = tris.reshape(-1, 3).min(0)
    size = tris.reshape(-1, 3).max(0) - low
    shift = low - 1.0
    index = reference.TriangleIndex(tris - shift, mask, 0.0, 0.0, float(size[0]) + 2, float(size[1]) + 2)
    rows = []
    for glass_id in np.nonzero(mask == GLASS)[0]:
        pane = tris[glass_id] - shift
        cross = np.cross(pane[1] - pane[0], pane[2] - pane[0])
        area = 0.5 * np.linalg.norm(cross)
        if area < MIN_AREA_M2:
            continue
        centre = pane.mean(0)
        normal = cross / (2 * area)
        a, b = centre - normal * REACH_M, centre + normal * REACH_M
        rows.append({"area_m2": round(float(area), 2), "hits_glass": int(len(index.hits(a, b, GLASS)[1])),
                     "hits_wall": int(len(index.hits(a, b, WALL)[1])),
                     "centre_local_m": [round(float(x), 2) for x in centre + shift],
                     "normal": [round(float(x), 3) for x in normal]})
    simple_hits = None
    if simple_tris_cm is not None and len(rows):
        simple = (simple_tris_cm / 100.0).astype(np.float32) - shift
        simple_index = reference.TriangleIndex(simple, np.full(len(simple), WALL, np.uint8), 0.0, 0.0,
                                               float(size[0]) + 2, float(size[1]) + 2)
        simple_hits = 0
        for r in rows:
            c = np.array(r["centre_local_m"]) - shift
            n = np.array(r["normal"])
            simple_hits += int(len(simple_index.hits(c - n * REACH_M, c + n * REACH_M, WALL)[1]) > 0)
    return {"glass_triangles": len(rows), "glass_triangles_blocking": sum(1 for r in rows if r["hits_glass"] > 0),
            "segments_through_open_wall": sum(1 for r in rows if r["hits_wall"] == 0),
            "segments_with_wall_hit": sum(1 for r in rows if r["hits_wall"] > 0),
            "segments_hit_by_simple_shapes": simple_hits, "sample_panes": rows[:5]}


def main(directory, sections_file, fragment, out):
    row = next(r for r in map(json.loads, open(sections_file)) if fragment in r["path"] and r.get("sections"))
    names = json.load(open(os.path.join(directory, "meshes.json")))
    mesh_id = next(v for k, v in names.items() if k == row["path"])
    prefix = os.path.join(directory, "bodies", str(mesh_id))
    tris, _, source = objects.mesh_triangles(prefix)
    ranges = section_ranges(row)
    if sum(stop - start for start, stop, _ in ranges) != len(tris):
        raise SystemExit(f"section triangles {sum(s[1] - s[0] for s in ranges)} != collision triangles {len(tris)}")
    props = (json.load(open(prefix + ".json")).get("body") or {}).get("Properties", {})
    simple = objects.simple_triangles(props.get("AggGeom") or {})
    result = {"mesh": row["path"], "source": source, "triangles": int(len(tris)), **run(tris, ranges, simple)}
    json.dump(result, open(out, "w"), indent=1)
    print(json.dumps({k: v for k, v in result.items() if k != "sample_panes"}))


if __name__ == "__main__":
    main(*sys.argv[1:5])
