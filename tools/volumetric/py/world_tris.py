"""Every placed static mesh of a map as world-space collision triangles with their query-block mask.

Reads a directory written by ``SquadExtract statics`` (same input as tools/heightmaps/py/objects.py, whose
placement maths and cooked-Chaos triangle reader are reused) and writes one ``.npz``:
    tris    float32 [n, 3, 3]  world metres, triangle corners (UE axes: x east, y south, z up)
    mask    uint8   [n]        collision.block_mask of the placement
    part    int32   [n]        index into ``parts`` (one per mesh placement)
    parts   int32   [p, 2]     (mesh id, 0 complex / 1 simple collision)
Unlike the heightmap rasteriser this keeps every triangle (not only the top-most hit per cell).

    python world_tris.py <statics dir> <out.npz> [max triangles per shard]

With the third argument the output is split into ``<out minus .npz>.<i>.npz`` files of about that many triangles
and the printed JSON lists them under ``shards``.
"""

import json
import os
import sys

import numpy as np

import collision
import objects

SKIPPED_LEVEL_PARTS = objects.SKIPPED_LEVEL_PARTS


def placements(directory):
    """{mesh id: [4x4 world matrices]} and {mesh id: component BodyInstance dict list} of the map."""
    by_mesh = {}
    for line in open(os.path.join(directory, "instances.ndjson")):
        item = json.loads(line)
        if any(part in item["level"] for part in SKIPPED_LEVEL_PARTS):
            continue
        world = objects.component_world(item["chain"])
        if item.get("instances") is not None:
            mats = [objects.affine(objects.quat_matrix(i["q"]), i["t"], i["s"]) @ world for i in item["instances"]]
        else:
            mats = [world]
        by_mesh.setdefault(item["mesh"], []).extend((m, item.get("collision")) for m in mats)
    return by_mesh


def iter_shards(directory, max_triangles=None):
    """Yield (tris, mask, part, parts, stats) shards of the map in ``directory``.

    With ``max_triangles`` a shard is closed as soon as it holds at least that many triangles, so a map whose
    placements do not fit in memory at once (Kamdesh foliage: 378 M triangles, 13.6 GB as float32) is processed in
    pieces. Without it the whole map is one shard. ``stats`` is the same dict for every shard and keeps growing.
    """
    all_tris, all_mask, all_part, parts = [], [], [], []
    held = 0
    stats = {"placements": 0, "meshes_without_collision": 0, "triangles": 0, "blocked_by_mask": {}}

    def shard():
        tris = np.concatenate(all_tris)
        stats["triangles"] += int(len(tris))
        return tris, np.concatenate(all_mask), np.concatenate(all_part), np.array(parts, np.int32), stats

    for mesh, placed in placements(directory).items():
        found = objects.mesh_triangles(os.path.join(directory, "bodies", str(mesh)))
        if found is None:
            stats["meshes_without_collision"] += len(placed)
            continue
        local, default, source = found
        points = np.concatenate([local.reshape(-1, 3), np.ones((local.shape[0] * 3, 1))], axis=1)
        for matrix, override in placed:
            mask = collision.block_mask(override, default)
            stats["blocked_by_mask"][mask] = stats["blocked_by_mask"].get(mask, 0) + 1
            stats["placements"] += 1
            if mask == 0:
                continue
            world = ((points @ matrix)[:, :3].reshape(-1, 3, 3) / 100).astype(np.float32)
            all_tris.append(world)
            all_mask.append(np.full(len(world), mask, np.uint8))
            all_part.append(np.full(len(world), len(parts), np.int32))
            parts.append((int(mesh.lstrip("s") or 0) + (1_000_000 if mesh.startswith("s") else 0), 0 if source == "complex" else 1))
            held += len(world)
            if max_triangles and held >= max_triangles:
                yield shard()
                all_tris, all_mask, all_part, parts, held = [], [], [], [], 0
    if all_tris:
        yield shard()


def build(directory):
    """Return (tris, mask, part, parts, stats) for the whole map in ``directory`` as one shard."""
    return next(iter_shards(directory))


if __name__ == "__main__":
    directory, out = sys.argv[1:3]
    max_triangles = int(sys.argv[3]) if len(sys.argv) > 3 else None
    base = out[:-len(".npz")] if out.endswith(".npz") else out
    written = []
    for index, (tris, mask, part, parts, stats) in enumerate(iter_shards(directory, max_triangles)):
        path = out if max_triangles is None else f"{base}.{index}.npz"
        np.savez(path, tris=tris, mask=mask, part=part, parts=parts)
        written.append(path)
    print(json.dumps(dict(stats, shards=written)))
