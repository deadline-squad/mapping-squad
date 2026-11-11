"""Which of SquadHeight's objects the installed game has: the game's own mesh placements.

SquadHeight traces the collision of the Squad SDK's version of a map, and that is not the installed build's. Where it stands above
the game's terrain it can be an object the game has, or one only the SDK's map has: along Al Basrah's edge it holds the blocks of
a background city, 3 to 13 m high and more, where the game's landscape runs level, the server has that city's level with its
collision switched off and the client shows a part of it as scenery beyond the map. A heightmap that takes them gives a target on
open sand the height of a roof. build_heightmap.fuse therefore takes SquadHeight's surface above the terrain only at the grid
points where a placement of the game explains it (``explained``):

    server  the static mesh placements that collide (objects.placements), each with the box of its collision;
    client  every mesh placement that the game shows in the client scene (``SquadExtract scene`` of tools/maprender): static,
            instanced, foliage and spline meshes, the components of Blueprint actors and the water planes. The server's statics
            lack what is no static mesh placement of a level: foliage (trees, rocks), and the components whose mesh is set in
            their Blueprint (the lake planes, the houses of Al Basrah's village clusters, Fools Road's barns), for which
            SquadHeight is the heightmap's only source.

A box explains the surface at the grid points under it, MARGIN_M around it included, where SquadHeight's height lies between the
box's bottom and its top, MARGIN_M beyond them included: a block standing on a road mesh or over the sea is not explained by them.

A placement wider and longer than VAST_M is no object over a point, and its box holds the whole map. In the client scene it is
terrain or water that the game shows: background mountains whose foot stands on the landscape (Kamdesh's ``Mountain1Final``, up to
40 km wide, which SquadHeight follows to 0.25 m over 381 093 m2), the ocean plane (143 km wide), a sky sphere. It explains the
surface where its mesh passes within MARGIN_M of it, above or below. On the server such a placement's collision is in the object
surface where the cooked data can be read (objects.object_surface), and its box is left out.

Under an object that nothing explains the game's own surfaces stand: its terrain, its static collision, and the terrain or water
of a vast client mesh under SquadHeight's surface there (``surface_below``). A block that the SDK's map has standing in Al Basrah's
river leaves the water, not a pit down to the river bed.
"""

import json
import os

import numpy as np

import lattice
import objects
import spline_mesh

MARGIN_M = 1.0
VAST_M = 800.0
CHUNK_CELLS = 4_000_000
# Levels whose meshes are no part of the map the game shows: tools/maprender/scene_render.py SKIPPED_LEVEL_PARTS
SKIPPED_SCENE_LEVEL_PARTS = ("/Coop/", "/Tutorials/", "/Sound_Layers/", "Profiling", "Navmesh", "_Vista", "_Editor_Only")


def world_boxes(lo, hi, matrices):
    """World boxes [n, 6] (x0, y0, z0, x1, y1, z1 in metres) of a local box (corners ``lo``, ``hi`` in cm) under row-vector matrices [n, 4, 4]."""
    corners = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    world = np.einsum("cj,njk->nck", corners, matrices)[:, :, :3] / 100
    return np.concatenate([world.min(1), world.max(1)], axis=1)


def is_vast(boxes):
    """Bool [n]: the boxes [n, 6] that are wider and longer than VAST_M."""
    return np.minimum(boxes[:, 3] - boxes[:, 0], boxes[:, 4] - boxes[:, 1]) > VAST_M


def collision_boxes(statics_dir):
    """World boxes [n, 6] of the server's static mesh placements that collide (a directory of ``SquadExtract statics``): the
    placements objects.object_surface rasterizes, each with the box that holds its collision, the vast ones left out.

    A mesh's box is objects.collision_bounds, its render bounds with a margin. A spline mesh has a body of its own, already bent,
    and that function's box for it is the whole segment with the mesh's length around it (a road segment's: 45 by 58 m and 42 m
    high): its box here is that of the body's collision itself, and a body whose collision cannot be read has none.
    """
    boxes = [np.zeros((0, 6))]
    for mesh, matrices in objects.placements(statics_dir)[0].items():
        prefix = os.path.join(statics_dir, "bodies", str(mesh))
        info = json.load(open(prefix + ".json"))
        if not info.get("bounds"):
            continue
        if info.get("spline"):
            found = objects.mesh_triangles(prefix)
            if found is None:
                continue
            corners = found[0].reshape(-1, 3)
            lo, hi = corners.min(0), corners.max(0)
        else:
            lo, hi = objects.collision_bounds(info)
        boxes.append(world_boxes(lo, hi, np.array(matrices)))
    boxes = np.concatenate(boxes)
    return boxes[~is_vast(boxes)]


def instance_matrices(instances):
    """[n, 4, 4] row-vector matrices of the per-instance transforms of an instanced component of a scene: quaternion ``q``
    (x, y, z, w), translation ``t`` and scale ``s`` (the same as tools/maprender/scene_render.py instance_matrices)."""
    q = np.array([i["q"] for i in instances], np.float64)
    x, y, z, w = q.T
    m = np.zeros((len(instances), 4, 4))
    m[:, 0, 0], m[:, 0, 1], m[:, 0, 2] = 1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)
    m[:, 1, 0], m[:, 1, 1], m[:, 1, 2] = 2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)
    m[:, 2, 0], m[:, 2, 1], m[:, 2, 2] = 2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)
    m[:, :3, :3] *= np.array([i["s"] for i in instances], np.float64)[:, :, None]
    m[:, 3, :3] = [i["t"] for i in instances]
    m[:, 3, 3] = 1
    return m


def scene_placements(scene_dir):
    """(boxes [n, 6], surfaces) of the mesh placements that the game shows in a client scene (a directory of ``SquadExtract scene``).

    Every instance of every component that is not hidden and not in a level of SKIPPED_SCENE_LEVEL_PARTS. ``boxes``: the world box
    of the mesh's vertices under each placement that is not vast; a spline mesh has the box of the mesh bent along its spline
    (spline_mesh.bend_along_spline). ``surfaces``: the world triangles [t, 3, 3] (m) of each vast placement. A mesh the extractor
    could not read has neither.
    """
    meshes = {info["id"]: info for info in json.load(open(os.path.join(scene_dir, "meshes.json"))).values() if "error" not in info}
    local = {}

    def positions_of(mesh):
        return np.fromfile(os.path.join(scene_dir, "meshes", f"{mesh}.bin"), np.float32, count=meshes[mesh]["vertices"] * 8).reshape(-1, 8)[:, :3].astype(np.float64)

    boxes, surfaces = [np.zeros((0, 6))], []
    for line in open(os.path.join(scene_dir, "instances.ndjson")):
        item = json.loads(line)
        mesh = item["mesh"]
        if mesh not in meshes or not meshes[mesh]["vertices"] or item["hidden"] or any(part in item["level"] for part in SKIPPED_SCENE_LEVEL_PARTS):
            continue
        if item["instances"] is not None and not item["instances"]:
            continue
        if mesh not in local:
            positions = positions_of(mesh)
            local[mesh] = (positions.min(0), positions.max(0))
        lo, hi = local[mesh]
        bent = None
        if item["spline"] is not None:
            bent, _ = spline_mesh.bend_along_spline(positions_of(mesh), item["spline"], (lo, hi))
            lo, hi = bent.min(0), bent.max(0)
        world = objects.component_world(item["chain"])
        matrices = world[None] if item["instances"] is None else instance_matrices(item["instances"]) @ world
        placed = world_boxes(lo, hi, matrices)
        vast = is_vast(placed)
        boxes.append(placed[~vast])
        if vast.any():
            indices = np.fromfile(os.path.join(scene_dir, "meshes", f"{mesh}.bin"), np.uint32, offset=meshes[mesh]["vertices"] * 32).astype(np.int64)
            corners = (positions_of(mesh) if bent is None else bent)[indices]
            points = np.concatenate([corners, np.ones((len(corners), 1))], axis=1)
            surfaces.extend((points @ m)[:, :3].reshape(-1, 3, 3) / 100 for m in matrices[vast])
    return np.concatenate(boxes), surfaces


def _mark_under_boxes(out, surface, wanted, boxes, grid):
    """Set ``out`` at the wanted nodes of ``grid`` (a lattice.Lattice) under a box (MARGIN_M around it) whose surface height lies
    in the box's height range (MARGIN_M beyond it)."""
    rows, cols = surface.shape
    lo_x, lo_y = boxes[:, 0] - MARGIN_M, boxes[:, 1] - MARGIN_M
    hi_x, hi_y = boxes[:, 3] + MARGIN_M, boxes[:, 4] + MARGIN_M
    # The nodes whose lattice position lies within the box's corners, then (on a turned lattice) those inside it in the world
    corner_cols, corner_rows = lattice.to_grid(grid, np.stack([lo_x, hi_x, lo_x, hi_x], 1), np.stack([lo_y, lo_y, hi_y, hi_y], 1))
    c0 = np.clip(np.ceil(corner_cols.min(1)), 0, cols).astype(np.int64)
    c1 = np.clip(np.floor(corner_cols.max(1)) + 1, 0, cols).astype(np.int64)
    r0 = np.clip(np.ceil(corner_rows.min(1)), 0, rows).astype(np.int64)
    r1 = np.clip(np.floor(corner_rows.max(1)) + 1, 0, rows).astype(np.int64)
    # Wanted points in any window of the grid, from their summed table: most boxes reach none
    table = np.zeros((rows + 1, cols + 1), np.int32)
    np.cumsum(wanted, 0, dtype=np.int32, out=table[1:, 1:])
    np.cumsum(table[1:, 1:], 1, out=table[1:, 1:])
    for k in np.flatnonzero((c1 > c0) & (r1 > r0) & (table[r1, c1] - table[r0, c1] - table[r1, c0] + table[r0, c0] > 0)):
        window = (slice(r0[k], r1[k]), slice(c0[k], c1[k]))
        part = surface[window]
        under = wanted[window] & (part >= boxes[k, 2] - MARGIN_M) & (part <= boxes[k, 5] + MARGIN_M)
        if grid.yaw_deg:
            gc, gr = np.meshgrid(np.arange(c0[k], c1[k], dtype=np.float64), np.arange(r0[k], r1[k], dtype=np.float64))
            x, y = lattice.to_world(grid, gc, gr)
            under &= (x >= lo_x[k] - 1e-9) & (x <= hi_x[k] + 1e-9) & (y >= lo_y[k] - 1e-9) & (y <= hi_y[k] + 1e-9)
        out[window] |= under


def _points_under_triangles(tris, wanted, grid):
    """Yield (flat grid indices, heights) of the points of the world triangles [t, 3, 3] (m) straight above or below the wanted
    nodes of ``grid``, in chunks of CHUNK_CELLS nodes. The grid walk of objects.rasterize, in the lattice's own frame."""
    rows, cols = wanted.shape
    gx, gy = lattice.to_grid(grid, tris[:, :, 0], tris[:, :, 1])
    i0 = np.maximum(np.ceil(gx.min(1)), 0).astype(np.int64)
    j0 = np.maximum(np.ceil(gy.min(1)), 0).astype(np.int64)
    nx = np.minimum(np.floor(gx.max(1)), cols - 1).astype(np.int64) - i0 + 1
    ny = np.minimum(np.floor(gy.max(1)), rows - 1).astype(np.int64) - j0 + 1
    keep = (nx > 0) & (ny > 0)
    gx, gy, z, i0, j0, nx, ny = gx[keep], gy[keep], tris[keep][:, :, 2], i0[keep], j0[keep], nx[keep], ny[keep]
    counts = nx * ny
    flat_wanted = wanted.reshape(-1)
    start = 0
    while start < len(counts):
        stop = start + max(1, int(np.searchsorted(np.cumsum(counts[start:]), CHUNK_CELLS)))
        c = counts[start:stop]
        t = np.repeat(np.arange(start, stop), c)
        k = np.arange(c.sum()) - np.repeat(np.cumsum(c) - c, c)
        ci = i0[t] + k % nx[t]
        cj = j0[t] + k // nx[t]
        index = cj * cols + ci
        asked = flat_wanted[index]
        t, ci, cj, index = t[asked], ci[asked], cj[asked], index[asked]
        x_a, x_b, x_c = gx[t, 0], gx[t, 1], gx[t, 2]
        y_a, y_b, y_c = gy[t, 0], gy[t, 1], gy[t, 2]
        den = (y_b - y_c) * (x_a - x_c) + (x_c - x_b) * (y_a - y_c)
        with np.errstate(divide="ignore", invalid="ignore"):
            a = ((y_b - y_c) * (ci - x_c) + (x_c - x_b) * (cj - y_c)) / den
            b = ((y_c - y_a) * (ci - x_c) + (x_a - x_c) * (cj - y_c)) / den
            inside = (den != 0) & (a >= -1e-9) & (b >= -1e-9) & (1 - a - b >= -1e-9)
            height = a * z[t, 0] + b * z[t, 1] + (1 - a - b) * z[t, 2]
        yield index[inside], height[inside]
        start = stop


def explained(surface, wanted, boxes, grid, surfaces=()):
    """Bool [rows, cols]: the ``wanted`` nodes of ``grid`` (lattice.Lattice) whose ``surface`` height (m) a placement holds: one of
    the world ``boxes`` [n, 6], or a mesh of ``surfaces`` (world triangles [t, 3, 3] in m of each vast placement), as the module
    description says."""
    out = np.zeros(surface.shape, bool)
    _mark_under_boxes(out, surface, wanted, boxes, grid)
    flat_out, flat_surface = out.reshape(-1), surface.reshape(-1)
    for tris in surfaces:
        for index, height in _points_under_triangles(tris, wanted & ~out, grid):
            flat_out[index[np.abs(height - flat_surface[index]) <= MARGIN_M]] = True
    return out


def surface_below(surface, wanted, surfaces, grid):
    """Float [rows, cols]: at the ``wanted`` nodes of ``grid`` the highest point of the vast meshes (``surfaces``, as explained takes them)
    straight under the ``surface`` height (m), -inf where there is none and at the other points. What the game shows under an
    object it does not have: the water of the ocean plane, a mountain mesh."""
    below = np.full(surface.shape, -np.inf, surface.dtype)
    flat_below, flat_surface = below.reshape(-1), surface.reshape(-1)
    for tris in surfaces:
        for index, height in _points_under_triangles(tris, wanted, grid):
            under = height <= flat_surface[index]
            np.maximum.at(flat_below, index[under], height[under])
    return below
