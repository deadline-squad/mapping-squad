"""Top surface of a map's static meshes from their collision in the game paks.

Input is a directory written by ``SquadExtract statics``:
    instances.ndjson  one line per static mesh component: level, component type, mesh id,
                      attach chain of relative transforms (component first), BodyInstance
                      overrides, and per-instance transforms of instanced components;
    bodies/<id>.json  mesh path, render bounds and BodySetup (simple collision in AggGeom);
    bodies/<id>.Chaos.bin  cooked Chaos collision holding the complex triangle meshes.

Each mesh collides with its complex triangle meshes when it has any (like SquadHeight's
trace_complex), else with its simple shapes. The surface is the highest collision point
straight above each grid point (the same sampling as SquadHeight's top-most trace).
"""

import json
import math
import os
import struct

import numpy as np
from scipy.spatial import ConvexHull, QhullError

NO_COLLISION = ("ECollisionEnabled::NoCollision", "ECollisionEnabled::PhysicsOnly", "ECollisionEnabled::ProbeOnly")
NO_COLLISION_PROFILES = ("NoCollision", "OverlapAll", "OverlapAllDynamic", "UI")
SKIPPED_LEVEL_PARTS = ("/Coop/", "/Tutorials/")
CHUNK_CELLS = 4_000_000
BOX_TRIANGLES = np.array([
    [0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6], [0, 1, 4], [1, 5, 4],
    [2, 6, 3], [3, 6, 7], [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5],
])


def rotator_matrix(r):
    """3x3 row-vector rotation of a UE FRotator (FRotationMatrix)."""
    p, y, ro = (math.radians(r[k]) for k in ("Pitch", "Yaw", "Roll"))
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(ro), math.cos(ro)
    return np.array([
        [cp * cy, cp * sy, sp],
        [sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp],
        [-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp],
    ])


def quat_matrix(q):
    """3x3 row-vector rotation of a UE FQuat."""
    x, y, z, w = q["X"], q["Y"], q["Z"], q["W"]
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)],
        [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)],
        [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)],
    ])


def affine(rotation, location, scale):
    """4x4 row-vector transform: scale, then rotate, then translate (FTransform order)."""
    m = np.eye(4)
    m[:3, :3] = rotation * np.array([scale["X"], scale["Y"], scale["Z"]])[:, None]
    m[3, :3] = [location["X"], location["Y"], location["Z"]]
    return m


def component_world(chain):
    """World matrix of a component from its attach chain (component first, root last)."""
    world = np.eye(4)
    for link in chain:
        world = world @ affine(rotator_matrix(link["r"]), link["l"], link["s"])
    return world


def chaos_trimeshes(data, lo, hi):
    """Triangle meshes (vertices [n, 3], triangles [m, 3]) found in a cooked Chaos blob.

    Chaos serialises a triangle mesh as int32 vertex count, float32 xyz per vertex, int32
    large-index flag, int32 triangle count and the vertex indices (uint16, or int32 when the flag
    is set). A match must have every vertex inside the mesh bounds and every index below the
    vertex count, which no other field of the blob satisfies by chance.
    """
    size = len(data)
    if size < 24:
        return []
    # The little-endian 32-bit word at every byte offset, read as int32 and as float32
    b = np.frombuffer(data, np.uint8).astype(np.uint32)
    words = b[:-3] | (b[1:-2] << 8) | (b[2:-1] << 16) | (b[3:] << 24)
    counts = words.view(np.int32).astype(np.int64)
    floats = words.view(np.float32)
    offsets = np.arange(len(words))
    candidates = offsets[(counts >= 3) & (counts <= 2_000_000) & (offsets + 4 + 12 * counts + 8 <= size)]
    # Cheap vectorised filters before the full check: the index header after the vertices must be
    # plausible, and the first and last vertices must lie in the bounds
    ends = candidates + 4 + 12 * counts[candidates]
    large = counts[ends]
    triangles = counts[ends + 4]
    width = np.where(large == 1, 4, 2)
    candidates = candidates[((large == 0) | (large == 1)) & (triangles > 0) & (triangles <= 4_000_000) & (ends + 8 + 3 * triangles * width <= size)]
    for first_byte in (lambda c: c + 4, lambda c: c + 4 + 12 * (counts[c] - 1)):
        vertex = np.stack([floats[first_byte(candidates) + 4 * k] for k in range(3)], axis=1)
        with np.errstate(invalid="ignore"):
            candidates = candidates[np.all((vertex >= lo) & (vertex <= hi), axis=1)]

    meshes = []
    resume = 0
    for offset in candidates.tolist():
        if offset < resume:
            continue
        n = int(struct.unpack_from("<i", data, offset)[0])
        end = offset + 4 + 12 * n
        verts = np.frombuffer(data, "<f4", 3 * n, offset + 4).reshape(n, 3)
        if not (np.all(np.isfinite(verts)) and np.all(verts >= lo) and np.all(verts <= hi)):
            continue
        large, m = struct.unpack_from("<ii", data, end)
        width = 4 if large == 1 else 2
        stop = end + 8 + 3 * m * width
        if large not in (0, 1) or not 0 < m <= 4_000_000 or stop > size:
            continue
        tris = np.frombuffer(data, "<i4" if width == 4 else "<u2", 3 * m, end + 8).reshape(m, 3)
        if tris.max() < n:
            meshes.append((verts.astype(np.float64), tris.astype(np.int64)))
            resume = stop
    return meshes


def hull_triangles(points):
    try:
        hull = ConvexHull(points)
    except (QhullError, ValueError):
        return None
    return points[hull.simplices]


def simple_triangles(agg):
    """Triangles [t, 3, 3] of a BodySetup's simple shapes, in mesh space (cm)."""
    out = []
    for box in agg.get("BoxElems") or []:
        half = np.array([box["X"], box["Y"], box["Z"]]) / 2
        corners = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]) * half
        corners = corners @ rotator_matrix(box.get("Rotation", {"Pitch": 0, "Yaw": 0, "Roll": 0}))
        corners += [box["Center"]["X"], box["Center"]["Y"], box["Center"]["Z"]]
        out.append(corners[BOX_TRIANGLES])
    sphere = np.array([[math.cos(a) * math.sin(b), math.sin(a) * math.sin(b), math.cos(b)]
                       for a in np.linspace(0, 2 * math.pi, 12, endpoint=False) for b in np.linspace(0, math.pi, 7)])
    for ball in agg.get("SphereElems") or []:
        c = ball["Center"]
        tris = hull_triangles(sphere * ball["Radius"] + [c["X"], c["Y"], c["Z"]])
        if tris is not None:
            out.append(tris)
    for capsule in agg.get("SphylElems") or []:
        r, half = capsule["Radius"], capsule["Length"] / 2
        points = np.concatenate([sphere * r + [0, 0, half], sphere * r - [0, 0, half]])
        points = points @ rotator_matrix(capsule.get("Rotation", {"Pitch": 0, "Yaw": 0, "Roll": 0}))
        c = capsule["Center"]
        tris = hull_triangles(points + [c["X"], c["Y"], c["Z"]])
        if tris is not None:
            out.append(tris)
    for convex in agg.get("ConvexElems") or []:
        points = np.array([[v["X"], v["Y"], v["Z"]] for v in convex.get("VertexData") or []])
        if len(points) < 4:
            continue
        transform = convex.get("Transform")
        if transform:
            q = transform.get("Rotation", {"X": 0, "Y": 0, "Z": 0, "W": 1})
            points = points * [transform["Scale3D"][k] for k in "XYZ"] @ quat_matrix(q) + [transform["Translation"][k] for k in "XYZ"]
        tris = hull_triangles(np.unique(points, axis=0))
        if tris is not None:
            out.append(tris)
    return np.concatenate(out) if out else None


def blocks(settings):
    """Whether a BodyInstance (component override or mesh default) leaves query collision on."""
    if not settings:
        return True
    if settings.get("CollisionEnabled") in NO_COLLISION:
        return False
    return settings.get("CollisionProfileName") not in NO_COLLISION_PROFILES


def collision_bounds(info):
    """Box (lo, hi) in component space that holds a body's collision vertices, with margin.

    A spline mesh's own body is bent along its Hermite segment: the box spans the segment's
    control points, widened by the mesh's largest scaled half-size and offset.
    """
    o, e = info["bounds"]["Origin"], info["bounds"]["BoxExtent"]
    extent = np.array([e["X"], e["Y"], e["Z"]])
    center = np.array([o["X"], o["Y"], o["Z"]])
    spline = info.get("spline")
    if not spline:
        margin = extent * 0.1 + 10
        return center - extent - margin, center + extent + margin
    vec = lambda key: np.array([spline.get(key, {}).get(k, 0.0) for k in "XYZ"])
    p0, p1 = vec("StartPos"), vec("EndPos")
    controls = np.array([p0, p0 + vec("StartTangent") / 3, p1 - vec("EndTangent") / 3, p1])
    scale = max(abs(spline.get(key, {}).get(k, 1.0)) for key in ("StartScale", "EndScale") for k in "XY")
    offset = max(abs(spline.get(key, {}).get(k, 0.0)) for key in ("StartOffset", "EndOffset") for k in "XY")
    reach = (np.abs(center) + extent).max() * max(scale, 1.0) + offset + 100
    return controls.min(0) - reach, controls.max(0) + reach


def mesh_triangles(body_prefix):
    """(triangles [t, 3, 3] in mesh space, mesh default BodyInstance, source) or None without collision."""
    info = json.load(open(body_prefix + ".json"))
    body = info.get("body") or {}
    props = body.get("Properties", {}) if isinstance(body, dict) else {}
    default = props.get("DefaultInstance") or info.get("meshDefault") or {}
    flag = props.get("CollisionTraceFlag", "CTF_UseDefault")
    complex_tris = None
    blob = body_prefix + ".Chaos.bin"
    if flag != "CTF_UseSimpleAsComplex" and os.path.exists(blob) and info.get("bounds"):
        lo, hi = collision_bounds(info)
        meshes = chaos_trimeshes(open(blob, "rb").read(), lo, hi)
        if meshes:
            complex_tris = np.concatenate([v[t] for v, t in meshes])
    if complex_tris is not None:
        return complex_tris, default, "complex"
    simple = simple_triangles(props.get("AggGeom") or {})
    if simple is not None and flag != "CTF_UseComplexAsSimple":
        return simple, default, "simple"
    return None


def rasterize(tris, top, x0, y0, step):
    """Raise `top` [rows, cols] to the highest triangle point straight above each grid point.

    `tris` [t, 3, 3] are world metres; grid point (row j, col i) is (x0 + i*step, y0 + j*step).
    """
    rows, cols = top.shape
    gx = (tris[:, :, 0] - x0) / step
    gy = (tris[:, :, 1] - y0) / step
    i0 = np.maximum(np.ceil(gx.min(1)), 0).astype(np.int64)
    i1 = np.minimum(np.floor(gx.max(1)), cols - 1).astype(np.int64)
    j0 = np.maximum(np.ceil(gy.min(1)), 0).astype(np.int64)
    j1 = np.minimum(np.floor(gy.max(1)), rows - 1).astype(np.int64)
    nx = i1 - i0 + 1
    ny = j1 - j0 + 1
    keep = (nx > 0) & (ny > 0)
    if not keep.any():
        return
    gx, gy, z = gx[keep], gy[keep], tris[keep][:, :, 2]
    i0, j0, nx, ny = i0[keep], j0[keep], nx[keep], ny[keep]
    counts = nx * ny
    flat = top.reshape(-1)
    start = 0
    while start < len(counts):
        stop = start + max(1, int(np.searchsorted(np.cumsum(counts[start:]), CHUNK_CELLS)))
        c = counts[start:stop]
        t = np.repeat(np.arange(start, stop), c)
        k = np.arange(c.sum()) - np.repeat(np.cumsum(c) - c, c)
        ci = i0[t] + k % nx[t]
        cj = j0[t] + k // nx[t]
        x_a, x_b, x_c = gx[t, 0], gx[t, 1], gx[t, 2]
        y_a, y_b, y_c = gy[t, 0], gy[t, 1], gy[t, 2]
        den = (y_b - y_c) * (x_a - x_c) + (x_c - x_b) * (y_a - y_c)
        with np.errstate(divide="ignore", invalid="ignore"):
            a = ((y_b - y_c) * (ci - x_c) + (x_c - x_b) * (cj - y_c)) / den
            b = ((y_c - y_a) * (ci - x_c) + (x_a - x_c) * (cj - y_c)) / den
        c3 = 1 - a - b
        inside = (den != 0) & (a >= -1e-9) & (b >= -1e-9) & (c3 >= -1e-9)
        height = a * z[t, 0] + b * z[t, 1] + c3 * z[t, 2]
        np.maximum.at(flat, (cj * cols + ci)[inside], height[inside])
        start = stop


def object_surface(directory, bounds, step, shape):
    """Highest static mesh collision above each grid point in metres (-inf where none), and stats."""
    top = np.full(shape, -np.inf)
    by_mesh = {}
    skipped = {"no_collision_component": 0, "level": 0}
    for line in open(os.path.join(directory, "instances.ndjson")):
        item = json.loads(line)
        if any(part in item["level"] for part in SKIPPED_LEVEL_PARTS):
            skipped["level"] += 1
            continue
        if not blocks(item.get("collision")):
            skipped["no_collision_component"] += 1
            continue
        world = component_world(item["chain"])
        if item.get("instances") is not None:
            mats = [affine(quat_matrix(i["q"]), i["t"], i["s"]) @ world for i in item["instances"]]
        else:
            mats = [world]
        by_mesh.setdefault(item["mesh"], []).extend(mats)
    sources = {"complex": 0, "simple": 0, "none": 0, "no_collision_mesh": 0}
    for mesh, mats in by_mesh.items():
        found = mesh_triangles(os.path.join(directory, "bodies", str(mesh)))
        if found is None:
            sources["none"] += len(mats)
            continue
        local, default, source = found
        if not blocks(default):
            sources["no_collision_mesh"] += len(mats)
            continue
        sources[source] += len(mats)
        points = np.concatenate([local.reshape(-1, 3), np.ones((local.shape[0] * 3, 1))], axis=1)
        for m in mats:
            world_tris = (points @ m)[:, :3].reshape(-1, 3, 3) / 100
            rasterize(world_tris, top, bounds["min_x"], bounds["min_y"], step)
    return top, {**skipped, **sources}
