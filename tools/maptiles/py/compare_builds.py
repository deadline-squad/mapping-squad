"""Placements of the server build against the client build, per map: are they the same objects at the same places?

Usage: compare_builds.py <map> [<map> ...]   (prints JSON; container paths as scene_prep.py)

The detailed tiles take the ground, foliage trunks and the old collision raster from the dedicated server's files (build 26005357,
/extract/statics) and the visible meshes and crowns from the client's scene (build 26234431, /scene). For every static mesh
that the server places (outside the levels the scene skips, scene_objects.SKIPPED_LEVEL_PARTS) the nearest client placement of the same mesh is looked for; a placement
within MATCH_M counts as the same object. The same is done for foliage: instances per mesh in both builds.
"""

import json
import os
import sys

import numpy as np
from scipy.spatial import cKDTree

import objects
import scene_objects as scene

MATCH_M = 0.5


def server_placements(statics_dir):
    """{mesh name: world positions [n, 3] in m} of the server's static meshes (objects.placements) outside the levels the scene skips."""
    by_mesh, _ = objects.placements(statics_dir, scene.SKIPPED_LEVEL_PARTS)
    result = {}
    for mesh, mats in by_mesh.items():
        info = json.load(open(os.path.join(statics_dir, "bodies", f"{mesh}.json")))
        name = (info.get("path") or str(mesh)).rsplit("/", 1)[-1].split(".")[0]
        result.setdefault(name, []).append(np.array([m[3, :3] for m in mats]) / 100)
    return {name: np.concatenate(parts) for name, parts in result.items()}


def client_placements(scene_dir):
    """{mesh name: world positions [n, 3] in m} of the client's static meshes and, apart, the foliage instances per mesh name."""
    statics, foliage = {}, {}
    for item, path, _ in scene.read_instances(scene_dir):
        name = path.rsplit("/", 1)[-1].split(".")[0]
        matrices = scene.component_matrices(item)
        if not len(matrices):
            continue
        target = foliage if item["type"] == scene.FOLIAGE_TYPE else statics
        target.setdefault(name, []).append(matrices[:, 3, :3] / 100)
    return {k: np.concatenate(v) for k, v in statics.items()}, {k: np.concatenate(v) for k, v in foliage.items()}


def compare(server, client):
    """Counts of server placements with a client placement of the same mesh within MATCH_M, and of the others; by mesh the worst."""
    total = matched = 0
    missing_meshes, unmatched = {}, {}
    for name, positions in server.items():
        total += len(positions)
        if name not in client:
            missing_meshes[name] = len(positions)
            continue
        distance, _ = cKDTree(client[name]).query(positions)
        ok = int((distance <= MATCH_M).sum())
        matched += ok
        if ok < len(positions):
            unmatched[name] = len(positions) - ok
    client_total = sum(len(v) for v in client.values())
    return {"server_placements": total, "matched": matched, "matched_share": round(matched / max(total, 1), 4), "client_placements": client_total,
            "server_meshes_not_in_client": dict(sorted(missing_meshes.items(), key=lambda kv: -kv[1])[:8]),
            "meshes_with_unmatched": dict(sorted(unmatched.items(), key=lambda kv: -kv[1])[:8])}


def main():
    for slug in sys.argv[1:]:
        statics_client, foliage_client = client_placements(os.path.join("/scene", slug))
        report = {"map": slug, "static_meshes": compare(server_placements(os.path.join("/extract/statics", slug)), statics_client)}
        server_foliage = {}
        for line in open(os.path.join("/features", slug, "foliage.ndjson")):
            item = json.loads(line)
            rows = np.asarray(item["instances"], np.float64).reshape(-1, 5)
            if not len(rows):
                continue
            matrix = objects.component_world(item["chain"])
            world = (np.concatenate([rows[:, :3], np.ones((len(rows), 1))], axis=1) @ matrix)[:, :3] / 100
            server_foliage.setdefault(item["mesh"].rsplit("/", 1)[-1].split(".")[0], []).append(world)
        report["foliage"] = compare({k: np.concatenate(v) for k, v in server_foliage.items()}, foliage_client)
        print(json.dumps(report, indent=1), flush=True)


if __name__ == "__main__":
    main()
