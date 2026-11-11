"""Prepare one map's sources for the detailed map tiles (render.py) from the Squad game files.

Usage: prep.py <map> [--workers N]

Reads (container paths, see maptiles.sh):
    /heightmaps/<map>/meta.json      the served precise heightmap: bounds and the z_min_m that SquadCalc's
                                     height readouts are relative to (tools/heightmaps)
    /squadheight/<Name>/             SquadHeight's surface (terrain outside the game landscape, and the
                                     SDK objects the game's static meshes miss, e.g. Blueprint buildings)
    /extract/landscapes/             landscape collision (SquadExtract extractall)
    /extract/statics/<map>/          static mesh placements and collision (SquadExtract statics)
    /features/<map>/                 foliage, landscape splines and water actors (SquadExtract features)

Writes /prep/<map>/:
    meta.json        grid, z_min_m, sea level, object pyramid levels, classification reports
    ground.npy       float32 [H, W] bare ground (game landscape, else SquadHeight) on the 1 m minimap grid, in
                     metres above z_min_m, i.e. the same scale as SquadCalc's readouts
    cover.npy        uint8 [H, W] landscape physical material (features.PHYSICAL_MATERIALS), 255 none
    obj_h<k>.npy     uint16 object height above ground (cm) on the 0.25 * 2**k m grid, the maximum
    obj_c<k>.npy     uint8 class (features.OBJECT_CLASSES) of the highest object in the cell
    obj_v<k>.npy     uint8 share of the cell covered by objects of 0.3 m and more, 0..255
    foliage.npz      trees, bushes and rocks (features.foliage)
    lines.json       landscape spline segments: roads, tracks, rivers, hedges, walls, trenches
    water.json       static water planes; the sea level is in meta.json
    labels.json      roof height labels of the larger buildings

Grids: the 1 m grid is SquadHeight's, from the minimap's corner (point [r, c] at world X = min_x + c, Y = min_y + r metres;
the served heightmap lies on the landscape's own vertices instead, tools/heightmaps lattice.py). Its ground is the game's
landscape collision at those points, read on the game's triangles from the landscape's vertices: what SquadCalc reads there;
level 0 of the object pyramid has 4 points per metre (point [r, c] at min + c / 4, min + r / 4); a
level k cell aggregates the 2**k x 2**k level 0 points from [r * 2**k, c * 2**k].
"""

import argparse
import collections
import json
import os
import time

import numpy as np
from numpy.lib.format import open_memmap
from PIL import Image, ImageDraw
from scipy import ndimage

import build_heightmap
import features
import landscape
import lattice
import objects
import worker_pool
from maps import MAPS

OBJECT_STEP_M = 0.25
OBJECT_BLOCK = 2048
# Per worker: mesh triangles kept between blocks, and cells per vectorised rasterizer chunk (its
# temporaries take about 120 bytes per cell); together they bound a worker to about 0.6 GB
TRIANGLE_CACHE_BYTES = 300 * 2 ** 20
RASTER_CHUNK_CELLS = 1_000_000
OBJECT_MIN_CM = 5
COVERAGE_MIN_CM = 30
PYRAMID_LEVELS = 6
SDK_OBJECT_MIN_M = 0.5
FOLIAGE_TRUNK_CLEARANCE_M = 1.5
WATER_SURFACE_M = 0.6
LABEL_MIN_HEIGHT_CM = 300
LABEL_MIN_AREA_M2 = 60

_state = {}


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def _load_instances(statics_dir, bounds):
    """Per mesh: (local collision box corners, instance matrices [n, 4, 4], world AABBs [n, 4], class).

    The same placements and collision filters as objects.object_surface; the box is
    objects.collision_bounds (the render bounds with a margin; a bent spline mesh's whole segment).
    """
    by_mesh = {}
    for line in open(os.path.join(statics_dir, "instances.ndjson")):
        item = json.loads(line)
        if any(part in item["level"] for part in objects.SKIPPED_LEVEL_PARTS) or not objects.blocks(item.get("collision")):
            continue
        world = objects.component_world(item["chain"])
        if item.get("instances") is not None:
            mats = [objects.affine(objects.quat_matrix(i["q"]), i["t"], i["s"]) @ world for i in item["instances"]]
        else:
            mats = [world]
        by_mesh.setdefault(item["mesh"], []).extend(mats)
    meshes = {}
    for mesh, mats in by_mesh.items():
        info = json.load(open(os.path.join(statics_dir, "bodies", f"{mesh}.json")))
        if not info.get("bounds"):
            continue
        lo, hi = objects.collision_bounds(info)
        corners = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        mats = np.array(mats)
        world = np.einsum("cj,njk->nck", corners, mats)[:, :, :2] / 100
        boxes = np.concatenate([world.min(1), world.max(1)], axis=1)
        meshes[mesh] = (mats, boxes, features.object_class(os.path.basename(info.get("path") or "")))
    return meshes


def _init_objects(statics_dir, bounds, ground_path, out_dir):
    _state.update(
        statics=statics_dir, bounds=bounds, out=out_dir,
        meshes=_load_instances(statics_dir, bounds),
        ground=np.load(ground_path, mmap_mode="r"),
        triangles=collections.OrderedDict(),
        cached_bytes=0,
    )
    objects.CHUNK_CELLS = RASTER_CHUNK_CELLS


def _triangles(mesh):
    """Collision triangle corners of a mesh [t * 3, 3] (cm, float32), or None without query collision.

    Kept in a per-worker cache of the most recently used meshes up to TRIANGLE_CACHE_BYTES.
    """
    cache = _state["triangles"]
    if mesh in cache:
        cache.move_to_end(mesh)
        return cache[mesh]
    found = objects.mesh_triangles(os.path.join(_state["statics"], "bodies", str(mesh)))
    corners = None if found is None or not objects.blocks(found[1]) else found[0].reshape(-1, 3).astype(np.float32)
    cache[mesh] = corners
    _state["cached_bytes"] += 0 if corners is None else corners.nbytes
    while _state["cached_bytes"] > TRIANGLE_CACHE_BYTES and len(cache) > 1:
        _, dropped = cache.popitem(last=False)
        _state["cached_bytes"] -= 0 if dropped is None else dropped.nbytes
    return corners


def _object_block(task):
    """Rasterize the static mesh collision over one block of the 0.25 m grid into obj_h0 / obj_c0."""
    r0, r1, c0, c1, z_min = task
    b = _state["bounds"]
    x0, y0 = b["min_x"] + c0 * OBJECT_STEP_M, b["min_y"] + r0 * OBJECT_STEP_M
    x1, y1 = b["min_x"] + (c1 - 1) * OBJECT_STEP_M, b["min_y"] + (r1 - 1) * OBJECT_STEP_M
    tops = np.full((len(features.OBJECT_CLASSES), r1 - r0, c1 - c0), -np.inf)
    triangles = 0
    for mesh, (mats, boxes, cls) in _state["meshes"].items():
        hit = (boxes[:, 0] <= x1) & (boxes[:, 2] >= x0) & (boxes[:, 1] <= y1) & (boxes[:, 3] >= y0)
        if not hit.any():
            continue
        corners = _triangles(mesh)
        if corners is None:
            continue
        for m in mats[hit]:
            world = ((corners @ m[:3, :3]) + m[3, :3]).reshape(-1, 3, 3) / 100
            objects.rasterize(world, tops[cls], x0, y0, OBJECT_STEP_M)
            triangles += len(world)
    top = tops.max(0)
    rows = (np.arange(r0, r1) * OBJECT_STEP_M)[:, None] * np.ones((1, c1 - c0))
    cols = np.ones((r1 - r0, 1)) * (np.arange(c0, c1) * OBJECT_STEP_M)[None, :]
    ground = ndimage.map_coordinates(_state["ground"], [rows, cols], order=1, mode="nearest") + z_min
    height_cm = np.where(np.isfinite(top), np.rint((top - ground) * 100), 0)
    height_cm = np.clip(np.where(height_cm >= OBJECT_MIN_CM, height_cm, 0), 0, 65535).astype(np.uint16)
    out_h = open_memmap(os.path.join(_state["out"], "obj_h0.npy"), mode="r+")
    out_c = open_memmap(os.path.join(_state["out"], "obj_c0.npy"), mode="r+")
    out_h[r0:r1, c0:c1] = height_cm
    out_c[r0:r1, c0:c1] = np.where(height_cm > 0, tops.argmax(0), 0).astype(np.uint8)
    out_h.flush()
    out_c.flush()
    return triangles


def rasterize_objects(statics_dir, bounds, shape_q, ground_path, out_dir, z_min, workers):
    """Level 0 of the object pyramid from the static meshes' collision, in parallel blocks."""
    open_memmap(os.path.join(out_dir, "obj_h0.npy"), mode="w+", dtype=np.uint16, shape=shape_q).flush()
    open_memmap(os.path.join(out_dir, "obj_c0.npy"), mode="w+", dtype=np.uint8, shape=shape_q).flush()
    tasks = [(r, min(r + OBJECT_BLOCK, shape_q[0]), c, min(c + OBJECT_BLOCK, shape_q[1]), z_min)
             for r in range(0, shape_q[0], OBJECT_BLOCK) for c in range(0, shape_q[1], OBJECT_BLOCK)]
    with worker_pool.Pool(workers, _init_objects, (statics_dir, bounds, ground_path, out_dir)) as pool:
        total = 0
        for done, count in enumerate(pool.imap_unordered(_object_block, tasks), 1):
            total += count
            if done % max(1, len(tasks) // 10) == 0:
                log(f"objects {done}/{len(tasks)} blocks")
    return total


def water_level(bounds, shape, sea, planes):
    """Highest water surface (absolute m) over each 1 m grid point: the sea, water planes; -inf elsewhere."""
    level = np.full(shape, -np.inf if sea is None else sea, np.float32)
    for plane in planes:
        canvas = Image.new("L", (shape[1], shape[0]), 0)
        ImageDraw.Draw(canvas).polygon([(x - bounds["min_x"], y - bounds["min_y"]) for x, y in plane["polygon"]], fill=1)
        inside = np.asarray(canvas, bool)
        level[inside] = np.maximum(level[inside], plane["z"])
    return level


def merge_sdk_objects(out_dir, terrain, surface, foliage, bounds, water):
    """Add SquadHeight's objects that no game static mesh explains (Blueprint buildings) to level 0.

    A 1 m point is such an object where the SDK surface rises SDK_OBJECT_MIN_M above the game
    terrain and the game objects do not. Left out: points under foliage with collision (tree trunks,
    rocks and bushes, drawn as foliage) and water surfaces (SquadHeight's trace stops on the sea and on
    lakes: the surface within WATER_SURFACE_M of the water level over lower terrain). Each point
    fills the 4 x 4 level 0 cells around it that hold no game object. Returns the points added.
    """
    h0 = open_memmap(os.path.join(out_dir, "obj_h0.npy"), mode="r+")
    c0 = open_memmap(os.path.join(out_dir, "obj_c0.npy"), mode="r+")
    game = np.asarray(h0[::4, ::4], dtype=np.float64) / 100
    rise = surface - terrain
    sdk = ~np.isnan(terrain) & (rise >= SDK_OBJECT_MIN_M) & (game < SDK_OBJECT_MIN_M)
    canvas = Image.new("L", (sdk.shape[1], sdk.shape[0]), 0)
    draw = ImageDraw.Draw(canvas)
    has = np.flatnonzero(foliage["collision"])
    for i in has:
        cx, cy = foliage["x"][i] - bounds["min_x"], foliage["y"][i] - bounds["min_y"]
        if foliage["cls"][i] in (features.CONIFER, features.DECIDUOUS):
            r = FOLIAGE_TRUNK_CLEARANCE_M
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=1)
        else:
            draw.polygon(features.ellipse_polygon(cx, cy, foliage["half_x"][i] + 1, foliage["half_y"][i] + 1, foliage["yaw"][i]), fill=1)
    sdk &= ~np.asarray(canvas, bool)
    with np.errstate(invalid="ignore"):
        sdk &= ~((np.abs(surface - water) < WATER_SURFACE_M) & (terrain < water))
    rise_cm = np.clip(np.rint(np.nan_to_num(rise) * 100), 0, 65535).astype(np.uint16)
    rr, cc = np.nonzero(sdk)
    for dr in range(-2, 2):
        for dc in range(-2, 2):
            r = rr * 4 + dr
            c = cc * 4 + dc
            ok = (r >= 0) & (r < h0.shape[0]) & (c >= 0) & (c < h0.shape[1])
            r, c, v = r[ok], c[ok], rise_cm[rr[ok], cc[ok]]
            empty = h0[r, c] == 0
            h0[r[empty], c[empty]] = v[empty]
            c0[r[empty], c[empty]] = features.STRUCTURE
    h0.flush()
    c0.flush()
    return int(sdk.sum())


def build_pyramid(out_dir, levels=PYRAMID_LEVELS, strip=4096, prefix="obj", coverage_exists=False, strip_cells=2 ** 24):
    """Levels 1..levels of the object pyramid and every level's coverage, from level 0.

    ``prefix`` names the files (<prefix>_h<k>.npy, _c, _v). The coverage of level 0 is made from the heights unless
    ``coverage_exists`` (the scene raster writes its anti-aliased coverage itself). A strip has at most ``strip`` rows and
    ``strip_cells`` cells (its copies take 5 bytes per cell each), so a 68 000 cell wide level 0 fits a 3 GB container.
    """
    rows_for = lambda width: min(strip, max(2, strip_cells // width // 2 * 2))
    h0 = np.load(os.path.join(out_dir, f"{prefix}_h0.npy"), mmap_mode="r")
    if not coverage_exists:
        cov = open_memmap(os.path.join(out_dir, f"{prefix}_v0.npy"), mode="w+", dtype=np.uint8, shape=h0.shape)
        step = rows_for(h0.shape[1])
        for top in range(0, h0.shape[0], step):
            cov[top:top + step] = np.where(np.asarray(h0[top:top + step]) >= COVERAGE_MIN_CM, 255, 0)
        cov.flush()
        del cov
    for k in range(1, levels + 1):
        h = np.load(os.path.join(out_dir, f"{prefix}_h{k - 1}.npy"), mmap_mode="r")
        step = rows_for(h.shape[1])
        c = np.load(os.path.join(out_dir, f"{prefix}_c{k - 1}.npy"), mmap_mode="r")
        v = np.load(os.path.join(out_dir, f"{prefix}_v{k - 1}.npy"), mmap_mode="r")
        shape = ((h.shape[0] + 1) // 2, (h.shape[1] + 1) // 2)
        out = {name: open_memmap(os.path.join(out_dir, f"{prefix}_{name}{k}.npy"), mode="w+", dtype=dtype, shape=shape)
               for name, dtype in (("h", np.uint16), ("c", np.uint8), ("v", np.uint8))}
        for top in range(0, shape[0], step // 2):
            rows = slice(2 * top, min(2 * (top + step // 2), h.shape[0]))
            hh, cc, vv = (np.asarray(a[rows]) for a in (h, c, v))
            if hh.shape[0] % 2:
                hh, cc, vv = (np.concatenate([a, a[-1:]]) for a in (hh, cc, vv))
            if hh.shape[1] % 2:
                hh, cc, vv = (np.concatenate([a, a[:, -1:]], axis=1) for a in (hh, cc, vv))
            n = hh.shape[0] // 2
            quads_h = hh.reshape(n, 2, -1, 2).transpose(0, 2, 1, 3).reshape(n, -1, 4)
            quads_c = cc.reshape(n, 2, -1, 2).transpose(0, 2, 1, 3).reshape(n, -1, 4)
            quads_v = vv.reshape(n, 2, -1, 2).transpose(0, 2, 1, 3).reshape(n, -1, 4)
            pick = quads_h.argmax(2)[..., None]
            out["h"][top:top + n] = np.take_along_axis(quads_h, pick, 2)[..., 0]
            out["c"][top:top + n] = np.take_along_axis(quads_c, pick, 2)[..., 0]
            out["v"][top:top + n] = np.rint(quads_v.mean(2)).astype(np.uint8)
        for array in out.values():
            array.flush()


def building_labels(h, c, bounds, centre_m=0.375):
    """Roof heights of the larger buildings: one label per connected building on a 1 m grid.

    ``h`` (cm) and ``c`` (class) are the height and class of the 1 m cells, cell [r, k] centred ``centre_m`` east and
    south of its corner at min + (k, r). A building is a connected area of structures at least LABEL_MIN_HEIGHT_CM tall and
    LABEL_MIN_AREA_M2 large; its label sits at the point farthest inside it and reads its 98th
    percentile height above ground (an antenna or chimney does not count).
    """
    mask = (h >= LABEL_MIN_HEIGHT_CM) & (c == features.STRUCTURE)
    labels, count = ndimage.label(mask, structure=np.ones((3, 3)))
    if not count:
        return []
    areas = np.bincount(labels.ravel())
    inside = ndimage.distance_transform_edt(mask)
    result = []
    objects_by_label = ndimage.find_objects(labels)
    for index, window in enumerate(objects_by_label, 1):
        if window is None or areas[index] < LABEL_MIN_AREA_M2:
            continue
        part = labels[window] == index
        depth = np.where(part, inside[window], -1)
        r, col = np.unravel_index(depth.argmax(), depth.shape)
        heights = h[window][part]
        result.append({
            "x": round(bounds["min_x"] + (window[1].start + col) * 1.0 + centre_m, 2),
            "y": round(bounds["min_y"] + (window[0].start + r) * 1.0 + centre_m, 2),
            "h": round(float(np.percentile(heights, 98)) / 100, 1),
            "area": int(areas[index]),
            "depth": round(float(depth.max()), 1),
        })
    return result


def bare_terrain(level_dirs, bounds, shape, strip=512):
    """Game landscape height (m, float32) on the 1 m grid, NaN outside the landscape.

    The game's collision at the points: the landscape's vertices read on its triangles (landscape.triangle_surface), the
    first landscape level covering a point winning as in build_heightmap.landscape_at, in row strips so the largest maps
    fit in memory next to the other jobs on the host.
    """
    actors = [actor for level in level_dirs for actor in landscape.assemble(level, transpose=False).values()]
    terrain = np.full(shape, np.nan, np.float32)
    xs = (bounds["min_x"] + np.arange(shape[1])) * 100.0
    for top in range(0, shape[0], strip):
        ys = (bounds["min_y"] + np.arange(top, min(top + strip, shape[0]))) * 100.0
        gx, gy = np.meshgrid(xs, ys)
        part = terrain[top:top + len(ys)]
        for actor in actors:
            z = landscape.sample_world(actor, gx, gy, "triangle") / 100
            part[:] = np.where(np.isnan(part), z, part)
    return terrain


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("map")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    slug = args.map
    squadheight_name, levels = MAPS[slug]
    out_dir = os.path.join("/prep", slug)
    os.makedirs(out_dir, exist_ok=True)
    hm_meta = json.load(open(os.path.join("/heightmaps", slug, "meta.json")))
    bounds = hm_meta["bounds_m"]
    z_min = hm_meta["z_min_m"]
    started = time.time()

    sh_meta, surface = build_heightmap.load_squadheight(os.path.join("/squadheight", squadheight_name))
    if sh_meta["bounds_m"] != bounds or surface.shape != lattice.minimap_shape(bounds, 1.0):
        raise SystemExit(f"{slug}: SquadHeight's grid is not the 1 m grid of the served heightmap's bounds")
    level_dirs = [os.path.join("/extract/landscapes", level) for level in levels]
    terrain = bare_terrain(level_dirs, bounds, surface.shape)
    ground = np.where(np.isnan(terrain), surface, terrain) - z_min
    ground_path = os.path.join(out_dir, "ground.npy")
    np.save(ground_path, ground.astype(np.float32))
    log(slug, "ground", ground.shape, f"{float(np.nanmin(ground)):.2f}..{float(np.nanmax(ground)):.2f} m")

    ground_shape = surface.shape
    np.save(os.path.join(out_dir, "cover.npy"), features.cover(level_dirs, bounds, surface.shape))
    log(slug, "cover")

    feature_dir = os.path.join("/features", slug)
    statics_dir = os.path.join("/extract/statics", slug)
    foliage, foliage_report = features.foliage(feature_dir)
    np.savez(os.path.join(out_dir, "foliage.npz"), **foliage)
    segments, spline_report = features.splines(feature_dir)
    json.dump(segments, open(os.path.join(out_dir, "lines.json"), "w"))
    sea = features.sea_level(feature_dir)
    planes = features.water_planes(statics_dir)
    for plane in planes:
        plane["z"] = round(plane["z"] - z_min, 3)
    json.dump({"planes": planes}, open(os.path.join(out_dir, "water.json"), "w"))
    log(slug, f"foliage {len(foliage['x'])}, splines {len(segments)}, water planes {len(planes)}, sea {sea}")

    shape_q = (4 * (surface.shape[0] - 1) + 1, 4 * (surface.shape[1] - 1) + 1)
    triangles = rasterize_objects(statics_dir, bounds, shape_q, ground_path, out_dir, z_min, args.workers)
    log(slug, f"objects rasterized, {triangles} triangles")
    water = water_level(bounds, surface.shape, sea, [{**p, "z": p["z"] + z_min} for p in planes])
    sdk_points = merge_sdk_objects(out_dir, terrain, surface, foliage, bounds, water)
    log(slug, f"SDK-only object points {sdk_points}")
    del terrain, surface, ground, water
    build_pyramid(out_dir)
    labels = building_labels(np.load(os.path.join(out_dir, "obj_h2.npy")), np.load(os.path.join(out_dir, "obj_c2.npy")), bounds)
    json.dump(labels, open(os.path.join(out_dir, "labels.json"), "w"))
    log(slug, f"pyramid, {len(labels)} building labels")

    json.dump({
        "map": slug,
        "bounds_m": bounds,
        "shape": list(ground_shape),
        "object_shape": list(shape_q),
        "object_step_m": OBJECT_STEP_M,
        "pyramid_levels": PYRAMID_LEVELS,
        "z_min_m": z_min,
        "sea_level_m": None if sea is None else round(sea - z_min, 3),
        "physical_materials": features.PHYSICAL_MATERIALS,
        "object_classes": features.OBJECT_CLASSES,
        "foliage_classes": features.FOLIAGE_CLASSES,
        "counts": {"foliage": int(len(foliage["x"])), "splines": len(segments), "water_planes": len(planes),
                   "object_triangles": triangles, "sdk_object_points": sdk_points, "building_labels": len(labels)},
        "foliage_report": foliage_report,
        "spline_report": spline_report,
        "seconds": round(time.time() - started),
    }, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)
    log(slug, "done", f"{time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
