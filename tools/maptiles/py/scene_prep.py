"""Prepare the objects and crowns of the detailed map tiles from the client scene (after prep.py).

Usage: scene_prep.py <map> [--workers N] [--report] [--keep-raw] [--redo-merge | --rasterized]

Reads (container paths, see maptiles.sh):
    /scene/<map>/               the client scene (SquadExtract scene, tools/maprender): visible LOD 0 meshes and placements
    /prep/<map>/                ground.npy, meta.json and the 0.25 m collision raster obj_*.npy of prep.py
    /features/<map>/            server foliage (which trees have a blocking trunk) and landscape splines (top_lines.json)
    /extract/statics/<map>/     server static mesh collision (names of what the report finds only in the old raster)

Writes /prep/<map>/:
    top_h<k>.npy     uint16 object height above ground (cm) on the 0.1 * 2**k m grid, the highest cell sample
    top_c<k>.npy     uint8 class (features.OBJECT_CLASSES) of the highest object in the cell
    top_v<k>.npy     uint8 share of the cell covered by objects of 0.3 m and more, 0..255 (anti-aliased edges)
    top_labels.json  roof height labels of the larger buildings
    top_water.json   water planes of the scene (lakes whose planes the server files lack), as water.json
    top_ground.npy   ground.npy with the voids beyond the landscape filled by the scene's scenery (scenery_ground)
    top_lines.json   the landscape splines (lines.json) with the roads', tracks' and pavements' edges narrowed to the width their meshes show (road_width)
    top_paths.npy    uint8 weight of the tracks painted into the landscape on the 1 m grid of ground.npy (landscape_paths)
    crowns.npz       trees, bushes, palms and rocks of the scene (crowns.scene_crowns), with crowns_stamps.npy and crowns.json
    top_crops.npy    uint8 [rows, cols, 2] cover and height (dm) of the crop fields on the 1 m grid of ground.npy (crowns.crop_fields)
    raw_{h,c,v}0.npy (only with --keep-raw) the scene raster before the old raster's objects were merged in (--redo-merge starts from it)
    top_meta.json    grid, counts, sources and the completeness against the old raster (report)

Level 0 (top_h0, top_c0, top_v0) is rasterized here on the CPU, or beforehand on the GPU by scene_raster_gpu.py (which writes
top_raster.json); --rasterized starts from that.

The grid of level 0 has cells of CELL_M metres, cell [r, c] covering [c, c + 1) * CELL_M east and [r, r + 1) * CELL_M south of
the map's minimum corner. Objects that the scene does not show but the old collision raster (prep.py: static mesh collision
and SquadHeight's Blueprint objects) holds are kept from the old raster: its cells farther than OLD_KEEP_M from any
scene object, in runs of at least OLD_KEEP_MIN_M2, and not where their top is that of a mesh the scene has as terrain or water
(scene_objects.surface_groups: background mountains, _Vista levels, rivers), which the server's collision holds as objects.
"""

import argparse
import json
import multiprocessing
import os
import time

import numpy as np
from numpy.lib.format import open_memmap
from PIL import Image, ImageDraw
from scipy import ndimage

import crowns
import objects
import features
import landscape_paths
import prep
import road_width
import scene_objects as scene

BLOCK = 1024
PYRAMID_LEVELS = 7
OLD_KEEP_M = 2
OLD_KEEP_MIN_M2 = 4
VOID_MIN_M2 = 1000
# SquadHeight's floor lies on the served heightmap's minimum, up to the float rounding of z_min (Kohat: 0.0001 m)
VOID_FLOOR_M = 0.01
SURFACE_MATCH_M = 2.0
TERRAIN_RUN_SHARE = 0.5
SERVICE_SHARE = 0.5
LEGACY_STEP_M = 0.25
COVER_MIN = 128
REPORT_MIN_M2 = 40
REPORT_ITEMS = 8
RASTER_CHUNK_CELLS = 1_000_000
TRIANGLE_CACHE_BYTES = 200 * 2 ** 20

_state = {}


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def _init(scene_dir, prep_dir, z_min, bounds):
    objects.CHUNK_CELLS = RASTER_CHUNK_CELLS
    _state.update(scene=scene.SceneObjects(scene_dir), ground=np.load(os.path.join(prep_dir, "ground.npy")), prep=prep_dir, z_min=z_min, bounds=bounds)


def _block(task):
    """Rasterize one block of cells into top_h0 / top_c0 / top_v0 (blocks without objects are left unwritten)."""
    r0, r1, c0, c1 = task
    height, cls, cover = scene.raster_block(_state["scene"], _state["ground"], _state["z_min"], _state["bounds"], r0, r1, c0, c1)
    if not height.any():
        return 0
    for name, array in (("h", height), ("c", cls), ("v", cover)):
        out = open_memmap(os.path.join(_state["prep"], f"top_{name}0.npy"), mode="r+")
        out[r0:r1, c0:c1] = array
        out.flush()
    return int((cover > 0).sum())


def level0_shape(bounds):
    """(rows, cols) of the level 0 grid of a map (cells of scene_objects.CELL_M)."""
    return (int(np.ceil((bounds["max_y"] - bounds["min_y"]) / scene.CELL_M)), int(np.ceil((bounds["max_x"] - bounds["min_x"]) / scene.CELL_M)))


def blocks_of(shape):
    """[(r0, r1, c0, c1)] of the BLOCK x BLOCK cell blocks of level 0, row by row."""
    return [(r, min(r + BLOCK, shape[0]), c, min(c + BLOCK, shape[1])) for r in range(0, shape[0], BLOCK) for c in range(0, shape[1], BLOCK)]


def rasterize(scene_dir, prep_dir, bounds, z_min, shape, workers):
    """Level 0 of the scene pyramid on the CPU, in parallel blocks; returns the number of covered cells."""
    for name, dtype in (("h", np.uint16), ("c", np.uint8), ("v", np.uint8)):
        open_memmap(os.path.join(prep_dir, f"top_{name}0.npy"), mode="w+", dtype=dtype, shape=shape).flush()
    tasks = blocks_of(shape)
    total = 0
    with multiprocessing.Pool(workers, _init, (scene_dir, prep_dir, z_min, bounds)) as pool:
        for done, count in enumerate(pool.imap_unordered(_block, tasks), 1):
            total += count
            if done % max(1, len(tasks) // 10) == 0:
                log(f"scene objects {done}/{len(tasks)} blocks")
    return total


def copy_raster(prep_dir, source, target, strip=2048):
    """Copy the level 0 rasters <source>_{h,c,v}0.npy to <target>_{h,c,v}0.npy; only strips with objects are written (sparse files)."""
    for name in "hcv":
        src = np.load(os.path.join(prep_dir, f"{source}_{name}0.npy"), mmap_mode="r")
        dst = open_memmap(os.path.join(prep_dir, f"{target}_{name}0.npy"), mode="w+", dtype=src.dtype, shape=src.shape)
        for top in range(0, src.shape[0], strip):
            part = np.asarray(src[top:top + strip])
            if part.any():
                dst[top:top + strip] = part
        dst.flush()


def pool_metres(prep_dir, strip=1000):
    """The level 0 raster on a 1 m grid: (height cm uint16, class uint8) of the highest cell of each metre."""
    per = round(1 / scene.CELL_M)
    h0 = np.load(os.path.join(prep_dir, "top_h0.npy"), mmap_mode="r")
    c0 = np.load(os.path.join(prep_dir, "top_c0.npy"), mmap_mode="r")
    rows, cols = -(-h0.shape[0] // per), -(-h0.shape[1] // per)
    height, cls = np.zeros((rows, cols), np.uint16), np.zeros((rows, cols), np.uint8)
    for top in range(0, h0.shape[0], strip):
        h = np.zeros((strip, cols * per), np.uint16)
        c = np.zeros((strip, cols * per), np.uint8)
        part = np.asarray(h0[top:top + strip])
        h[:len(part), :h0.shape[1]] = part
        c[:len(part), :h0.shape[1]] = np.asarray(c0[top:top + strip])[:len(part)]
        n = strip // per
        quads = h.reshape(n, per, cols, per).transpose(0, 2, 1, 3).reshape(n, cols, per * per)
        classes = c.reshape(n, per, cols, per).transpose(0, 2, 1, 3).reshape(n, cols, per * per)
        pick = quads.argmax(2)[..., None]
        r0 = top // per
        r1 = min(r0 + n, rows)
        height[r0:r1] = np.take_along_axis(quads, pick, 2)[..., 0][:r1 - r0]
        cls[r0:r1] = np.take_along_axis(classes, pick, 2)[..., 0][:r1 - r0]
    return height, cls


def fit(array, shape):
    """array cut or zero-padded to shape."""
    out = np.zeros(shape, array.dtype)
    r, c = min(shape[0], array.shape[0]), min(shape[1], array.shape[1])
    out[:r, :c] = array[:r, :c]
    return out


def small_runs_removed(mask, min_cells):
    """mask without the connected runs (8-neighbour) smaller than min_cells."""
    labels, count = ndimage.label(mask, structure=np.ones((3, 3)))
    if not count:
        return mask
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    return (sizes >= min_cells)[labels]


def service_mask(boxes, bounds, shape):
    """Bool [rows, cols] on the 1 m grid: inside a box of scene.service_boxes."""
    canvas = Image.new("L", (shape[1], shape[0]), 0)
    draw = ImageDraw.Draw(canvas)
    for x0, y0, x1, y1 in boxes:
        c0, r0 = int(np.floor(x0 - bounds["min_x"])), int(np.floor(y0 - bounds["min_y"]))
        draw.rectangle((c0, r0, max(c0, int(np.ceil(x1 - bounds["min_x"])) - 1), max(r0, int(np.ceil(y1 - bounds["min_y"])) - 1)), fill=1)
    return np.asarray(canvas, bool)


def without_service_runs(keep, service):
    """keep without its connected runs of which at least SERVICE_SHARE lies in a service volume (invisible walls and zone boxes)."""
    labels, count = ndimage.label(keep, structure=np.ones((3, 3)))
    if not count:
        return keep
    total = np.bincount(labels.ravel(), minlength=count + 1)
    inside = np.bincount(labels.ravel(), weights=service.ravel(), minlength=count + 1)
    dropped = inside >= SERVICE_SHARE * np.maximum(total, 1)
    dropped[0] = False
    return keep & ~dropped[labels]


def legacy_water_surface(planes, bounds, shape, ground, old_height_cm):
    """Bool [rows, cols] on the 1 m grid: cells of the old raster that are the surface of a scene water plane (a lake) and no object.

    The old raster's SquadHeight objects include the surface of lakes whose planes the server files lack: a cell is one when
    it lies in a plane's rectangle, the ground is below the plane and the top of the "object" is within WATER_SURFACE_M of it.
    """
    canvas = Image.new("F", (shape[1], shape[0]), -1e9)
    draw = ImageDraw.Draw(canvas)
    for plane in sorted(planes, key=lambda p: p["z"]):
        draw.polygon([(x - bounds["min_x"], y - bounds["min_y"]) for x, y in plane["polygon"]], fill=plane["z"])
    level = np.asarray(canvas, np.float32)
    old = fit(old_height_cm, shape).astype(np.float32) / 100
    ground = fit(ground, shape)
    return (ground < level - 0.05) & (np.abs(ground + old - level) < prep.WATER_SURFACE_M)


def legacy_cells(leg_h, leg_c, rows, cols):
    """(height cm, class, coverage 0..255, source rows, source columns) [len(rows), len(cols)] of level 0 cells drawn from the
    old 0.25 m raster's objects; the source is the old raster's cell (global indices) the height and class come from.

    The old raster's object cells (COVERAGE_MIN_CM and taller, no rock) are a staircase of LEGACY_STEP_M squares. A cell's
    coverage is the bilinear interpolation of that mask at its centre, stretched so that its half level, the outline, stays
    put and a level 0 cell crosses it in one step: straight edges keep their place, corners and diagonals lose their steps.
    Its height and class are those of the old raster's nearest object cell.
    """
    scale = LEGACY_STEP_M / scene.CELL_M
    r_at, c_at = (rows + 0.5) / scale - 0.5, (cols + 0.5) / scale - 0.5
    r0, r1 = max(int(np.floor(r_at.min())) - 1, 0), min(int(np.ceil(r_at.max())) + 2, leg_h.shape[0])
    c0, c1 = max(int(np.floor(c_at.min())) - 1, 0), min(int(np.ceil(c_at.max())) + 2, leg_h.shape[1])
    window_h, window_c = np.asarray(leg_h[r0:r1, c0:c1]), np.asarray(leg_c[r0:r1, c0:c1])
    solid = (window_h >= prep.COVERAGE_MIN_CM) & (window_c != features.ROCK_OBJECT)
    if not solid.any():
        empty = np.zeros((len(rows), len(cols)), np.int64)
        return empty.astype(np.uint16), empty.astype(np.uint8), empty.astype(np.uint8), empty, empty

    def axis(at, low, size):
        clamped = np.clip(at - low, 0, size - 1)
        first = np.minimum(np.floor(clamped).astype(np.int64), max(size - 2, 0))
        return first, np.minimum(first + 1, size - 1), (clamped - first).astype(np.float32)
    ra, rb, rw = axis(r_at, r0, solid.shape[0])
    ca, cb, cw = axis(c_at, c0, solid.shape[1])
    mask = solid.astype(np.float32)
    along = mask[ra] * (1 - rw)[:, None] + mask[rb] * rw[:, None]
    cover = np.clip((along[:, ca] * (1 - cw) + along[:, cb] * cw - 0.5) * scale + 0.5, 0, 1)
    _, (near_r, near_c) = ndimage.distance_transform_edt(~solid, return_indices=True)
    inside_r = np.clip(np.floor(r_at + 0.5).astype(np.int64) - r0, 0, solid.shape[0] - 1)
    inside_c = np.clip(np.floor(c_at + 0.5).astype(np.int64) - c0, 0, solid.shape[1] - 1)
    nearest_r, nearest_c = near_r[np.ix_(inside_r, inside_c)], near_c[np.ix_(inside_r, inside_c)]
    return (window_h[nearest_r, nearest_c], window_c[nearest_r, nearest_c], np.rint(cover * 255).astype(np.uint8),
            nearest_r + r0, nearest_c + c0)


def merge_old(prep_dir, new_h1, shape1, service, not_objects, strip=1000):
    """Paint the old raster's objects that the scene lacks into level 0; returns (old mask, kept mask, old-only mask) on the 1 m grid.

    What ``not_objects`` marks is no object: the old raster's lake surfaces (legacy_water_surface) and its terrain and water meshes
    (legacy_surfaces).
    The old raster holds collision the game does not show (invisible walls around the map, zone boxes): its runs that lie
    in the scene's service volumes (``service``) are not kept. Nor are its rocks: the scene shows every rock mesh, and what
    only the collision has of them is the scenery beyond the map (mountains, background terrain, SCENERY_MIN_SIDE_M and wider).
    The kept objects are painted with smoothed outlines (legacy_cells) where the scene has nothing.
    """
    legacy_h2 = np.load(os.path.join(prep_dir, "obj_h2.npy"))
    legacy_c2 = np.load(os.path.join(prep_dir, "obj_c2.npy"))
    old = fit(legacy_h2 >= prep.COVERAGE_MIN_CM, shape1)
    keep_candidates = old & ~not_objects
    old_rocks = fit(legacy_c2 == features.ROCK_OBJECT, shape1)
    new = new_h1 >= prep.COVERAGE_MIN_CM
    near = ndimage.binary_dilation(new, iterations=OLD_KEEP_M)
    keep = without_service_runs(small_runs_removed(keep_candidates & ~near & ~old_rocks, OLD_KEEP_MIN_M2), service)
    old_only = old & ~ndimage.binary_dilation(new, iterations=1)
    per = round(1 / scene.CELL_M)
    leg_h = np.load(os.path.join(prep_dir, "obj_h0.npy"), mmap_mode="r")
    leg_c = np.load(os.path.join(prep_dir, "obj_c0.npy"), mmap_mode="r")
    h0 = open_memmap(os.path.join(prep_dir, "top_h0.npy"), mode="r+")
    c0 = open_memmap(os.path.join(prep_dir, "top_c0.npy"), mode="r+")
    v0 = open_memmap(os.path.join(prep_dir, "top_v0.npy"), mode="r+")
    metre_cols = np.minimum(np.arange(h0.shape[1]) // per, keep.shape[1] - 1)
    near_keep = ndimage.binary_dilation(keep, iterations=1)
    legacy_per = round(1 / LEGACY_STEP_M)
    for top in range(0, h0.shape[0], strip):
        rows = np.arange(top, min(top + strip, h0.shape[0]))
        # A kept metre's neighbours too: the smoothed outline of an object may reach a little past its metres
        near_kept = near_keep[np.minimum(rows // per, keep.shape[0] - 1)][:, metre_cols]
        if not near_kept.any():
            continue
        span = np.flatnonzero(near_kept.any(0))
        cols = np.arange(span[0], span[-1] + 1)
        block_h, block_c, block_v, source_r, source_c = legacy_cells(leg_h, leg_c, rows, cols)
        part = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1))
        h, c, v = np.asarray(h0[part]), np.asarray(c0[part]), np.asarray(v0[part])
        # A cell is painted when the old object cell it takes its height from lies in a kept metre
        kept_source = keep[np.minimum(source_r // legacy_per, keep.shape[0] - 1), np.minimum(source_c // legacy_per, keep.shape[1] - 1)]
        paint = kept_source & (block_v > 0) & (h == 0)
        h[paint], c[paint], v[paint] = block_h[paint], block_c[paint], block_v[paint]
        h0[part], c0[part], v0[part] = h, c, v
    for array in (h0, c0, v0):
        array.flush()
    return old, keep, old_only


def components_report(mask, bounds, namer, count=REPORT_ITEMS):
    """The largest runs of a 1 m mask: [{x, y, area_m2, names}] by area, with the names found at the run's centre by `namer`."""
    labels, n = ndimage.label(mask, structure=np.ones((3, 3)))
    if not n:
        return []
    areas = np.bincount(labels.ravel())
    areas[0] = 0
    out = []
    for index in np.argsort(-areas)[:count]:
        if areas[index] < REPORT_MIN_M2:
            break
        rows, cols = np.nonzero(labels == index)
        x = bounds["min_x"] + float(cols.mean()) + 0.5
        y = bounds["min_y"] + float(rows.mean()) + 0.5
        out.append({"x": round(x, 1), "y": round(y, 1), "area_m2": int(areas[index]), "names": namer(x, y)})
    return out


def scene_namer(objects_of_scene):
    """Function (x, y) -> mesh names of the scene whose placements' boxes hold the point, smallest first."""
    def names(x, y):
        found = []
        for group in objects_of_scene.groups:
            b = group["boxes"]
            hit = (b[:, 0] <= x) & (b[:, 2] >= x) & (b[:, 1] <= y) & (b[:, 3] >= y)
            if hit.any():
                found.append((float(((b[hit, 2] - b[hit, 0]) * (b[hit, 3] - b[hit, 1])).min()), group["name"].rsplit("/", 1)[-1].split(".")[0]))
        return [name for _, name in sorted(found)[:4]]
    return names


def collision_namer(statics_dir, bounds):
    """Function (x, y) -> mesh names of the server collision whose placements' boxes hold the point, smallest first."""
    meshes = prep._load_instances(statics_dir, bounds)
    paths = {}
    for mesh in meshes:
        info = json.load(open(os.path.join(statics_dir, "bodies", f"{mesh}.json")))
        paths[mesh] = (info.get("path") or str(mesh)).rsplit("/", 1)[-1].split(".")[0]

    def names(x, y):
        found = []
        for mesh, (_, boxes, _) in meshes.items():
            hit = (boxes[:, 0] <= x) & (boxes[:, 2] >= x) & (boxes[:, 1] <= y) & (boxes[:, 3] >= y)
            if hit.any():
                found.append((float(((boxes[hit, 2] - boxes[hit, 0]) * (boxes[hit, 3] - boxes[hit, 1])).min()), paths[mesh]))
        return [name for _, name in sorted(found)[:4]]
    return names


def label_comparison(new, old):
    """Roof height of the new labels against the nearest old label within 6 m: counts and the percentiles of new - old (m)."""
    if not new or not old:
        return {"new": len(new), "old": len(old)}
    ox, oy = np.array([l["x"] for l in old]), np.array([l["y"] for l in old])
    diffs = []
    for label in new:
        d = np.hypot(ox - label["x"], oy - label["y"])
        k = int(d.argmin())
        if d[k] <= 6:
            diffs.append(label["h"] - old[k]["h"])
    diffs = np.array(diffs)
    if not len(diffs):
        return {"new": len(new), "old": len(old), "paired": 0}
    return {"new": len(new), "old": len(old), "paired": len(diffs), "difference_m": {
        "p5": round(float(np.percentile(diffs, 5)), 2), "median": round(float(np.median(diffs)), 2), "p95": round(float(np.percentile(diffs, 95)), 2)}}


def surface_top(objects_of_scene, groups, shape, bounds):
    """Highest point (absolute m, float32, -inf where none) of the groups' meshes over each point of the 1 m grid of ground.npy."""
    top = np.full(shape, -np.inf, np.float32)
    for group in groups:
        corners = objects_of_scene.triangles(group)
        for m in group["matrices"]:
            world = ((corners @ m[:3, :3]) + m[3, :3]).reshape(-1, 3, 3) / 100
            objects.rasterize(world, top, bounds["min_x"], bounds["min_y"], 1.0)
    return top


def scenery_ground(ground, cover, land_top, z_min):
    """(ground [H, W] float32 on the 1 m grid of ground.npy with its voids filled, filled cells).

    Past the game landscape prep.py takes SquadHeight's surface, the server's world. Where the server has nothing (the background
    mountains of Skorpo and Blackcoast are client meshes without collision) that surface is its floor, the lowest point of the
    served heightmap: ground under VOID_FLOOR_M outside the landscape (cover NO_COVER), in runs of VOID_MIN_M2 and more. Below the
    sea level such a void is drawn as sea. The scenery of the client scene (``land_top``, the surface_top of
    scene_objects.surface_groups' land) gives those cells its height; a void that no scenery covers (the open sea) keeps its floor.
    """
    filled = np.array(ground, np.float32)
    void = (np.asarray(cover) == features.NO_COVER) & (filled < VOID_FLOOR_M)
    labels, count = ndimage.label(void)
    if not count:
        return filled, 0
    large = np.zeros(count + 1, bool)
    large[1:] = ndimage.sum_labels(void, labels, np.arange(1, count + 1)) >= VOID_MIN_M2
    fill = large[labels] & np.isfinite(land_top)
    filled[fill] = land_top[fill] - z_min
    return filled, int(fill.sum())


def legacy_surfaces(land_top, water_top, ground, z_min, old_height_cm, shape):
    """Bool [rows, cols] on the 1 m grid: cells of the old raster that are the server's collision of a terrain or water mesh of the
    scene (``land_top``, ``water_top``: the meshes' tops, absolute m on the grid of ground.npy), not objects.

    A cell's top must be within SURFACE_MATCH_M of the mesh's top. For water that is all. A terrain mesh may be a low-poly copy of
    the landscape lying on the ground (Chora, Skorpo, Goose Bay), where a low wall would match it too: a run of the old raster
    (8-neighbour) is terrain when at least TERRAIN_RUN_SHARE of its cells match a terrain mesh that rises SURFACE_MATCH_M and
    more above the ground (a background mountain), and then its cells that match the mesh, down to the mountain's foot.
    """
    old = fit(old_height_cm, shape).astype(np.float32) / 100
    ground_m = fit(ground, shape) + z_min
    top = ground_m + old
    present = old * 100 >= prep.COVERAGE_MIN_CM
    land_top = fit(land_top, shape)
    on_terrain = present & (np.abs(top - land_top) < SURFACE_MATCH_M)
    del top
    rising = on_terrain & (land_top - ground_m >= SURFACE_MATCH_M)
    del land_top, ground_m
    labels, count = ndimage.label(present, structure=np.ones((3, 3)))
    terrain_run = np.zeros(count + 1, bool)
    if count:
        cells = np.bincount(labels.ravel(), minlength=count + 1)
        terrain_run = np.bincount(labels.ravel(), weights=rising.ravel(), minlength=count + 1) >= TERRAIN_RUN_SHARE * np.maximum(cells, 1)
        terrain_run[0] = False
    water = present & (np.abs(fit(ground, shape) + z_min + old - fit(water_top, shape)) < SURFACE_MATCH_M)
    return (on_terrain & terrain_run[labels]) | water


def write_top_lines(scene_dir, feature_dir, prep_dir):
    """Write top_lines.json, the map's landscape splines with the roads narrowed to what their meshes show; the number of segments narrowed."""
    lines, _ = features.splines(feature_dir)
    narrowed = road_width.narrowed_lines(scene_dir, lines)
    json.dump(narrowed, open(os.path.join(prep_dir, "top_lines.json"), "w"))
    return sum("span" in line for line in narrowed)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("map")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--report", action="store_true", help="name the largest differences to the old raster (needs /extract/statics)")
    parser.add_argument("--keep-raw", action="store_true", help="keep the scene raster before the merge (raw_*.npy, as large as top_*0) for --redo-merge")
    start = parser.add_mutually_exclusive_group()
    start.add_argument("--redo-merge", action="store_true", help="skip the rasterization: start from the scene raster of a run with --keep-raw (raw_*.npy)")
    start.add_argument("--rasterized", action="store_true", help="skip the rasterization: level 0 was written by scene_raster_gpu.py (top_raster.json)")
    args = parser.parse_args()
    slug = args.map
    prep_dir = os.path.join("/prep", slug)
    scene_dir = os.path.join("/scene", slug)
    meta = json.load(open(os.path.join(prep_dir, "meta.json")))
    bounds, z_min = meta["bounds_m"], meta["z_min_m"]
    shape = level0_shape(bounds)
    started = time.time()

    objects_of_scene = scene.SceneObjects(scene_dir)
    scenery = objects_of_scene.scenery
    log(slug, f"left out as scenery: {scenery}")
    raster = {"sampler": "cpu"}
    if args.redo_merge:
        copy_raster(prep_dir, "raw", "top")
        log(slug, "scene raster restored from raw_*.npy")
    elif args.rasterized:
        raster = json.load(open(os.path.join(prep_dir, "top_raster.json")))
        if raster["shape"] != list(shape):
            raise SystemExit(f"{slug}: top_raster.json is for a level 0 of {raster['shape']}, the map's is {list(shape)}")
        log(slug, f"scene objects rasterized on the GPU ({raster['renderer']}), {raster['covered_cells']} covered cells, {raster['seconds']} s")
        if args.keep_raw:
            copy_raster(prep_dir, "top", "raw")
    else:
        covered = rasterize(scene_dir, prep_dir, bounds, z_min, shape, args.workers)
        log(slug, f"scene objects rasterized, {covered} covered cells")
        if args.keep_raw:
            copy_raster(prep_dir, "top", "raw")
    new_h1, _ = pool_metres(prep_dir)
    shape1 = new_h1.shape
    service = service_mask(scene.service_boxes(scene_dir), bounds, shape1)
    planes = scene.water_planes(scene_dir, z_min)
    json.dump({"planes": planes}, open(os.path.join(prep_dir, "top_water.json"), "w"))
    ground = np.load(os.path.join(prep_dir, "ground.npy"), mmap_mode="r")
    old_h2 = np.load(os.path.join(prep_dir, "obj_h2.npy"))
    water_surface = legacy_water_surface(planes, bounds, shape1, ground, old_h2)
    cover = np.load(os.path.join(prep_dir, "cover.npy"), mmap_mode="r")
    land, water = scene.surface_groups(scene_dir)
    land_top = surface_top(objects_of_scene, land, ground.shape, bounds)
    filled, scenery_m2 = scenery_ground(ground, cover, land_top, z_min)
    np.save(os.path.join(prep_dir, "top_ground.npy"), filled)
    del filled
    log(slug, f"ground beyond the landscape from the scenery: {scenery_m2} m2")
    paths = landscape_paths.path_weights(scene_dir, bounds, ground.shape)
    np.save(os.path.join(prep_dir, "top_paths.npy"), paths)
    path_m2 = int((paths >= 128).sum())
    del paths
    log(slug, f"tracks painted into the landscape: {path_m2} m2")
    lines = write_top_lines(scene_dir, os.path.join("/features", slug), prep_dir)
    log(slug, f"{lines} road segments narrowed to their visible width")
    surfaces = legacy_surfaces(land_top, surface_top(objects_of_scene, water, ground.shape, bounds), ground, z_min, old_h2, shape1)
    del land_top, old_h2
    old, keep, old_only = merge_old(prep_dir, new_h1, shape1, service, water_surface | surfaces)
    new = new_h1 >= prep.COVERAGE_MIN_CM
    new_only = new & ~ndimage.binary_dilation(old, iterations=1)
    log(slug, f"old raster objects kept: {int(keep.sum())} m2, in service volumes {int((old & service).sum())} m2")
    prep.build_pyramid(prep_dir, PYRAMID_LEVELS, prefix="top", coverage_exists=True)
    h1, c1 = pool_metres(prep_dir)
    labels = prep.building_labels(h1, c1, bounds, centre_m=0.5)
    json.dump(labels, open(os.path.join(prep_dir, "top_labels.json"), "w"))
    old_labels = json.load(open(os.path.join(prep_dir, "labels.json")))
    log(slug, f"{len(labels)} building labels")

    arrays, names, stamps = crowns.scene_crowns(scene_dir, os.path.join("/features", slug))
    np.savez(os.path.join(prep_dir, "crowns.npz"), **arrays)
    np.save(os.path.join(prep_dir, "crowns_stamps.npy"), stamps)
    json.dump(names, open(os.path.join(prep_dir, "crowns.json"), "w"))
    log(slug, f"{len(arrays['x'])} crowns of {len(names)} meshes")
    crops = crowns.crop_fields(scene_dir, bounds, ground.shape)
    np.save(os.path.join(prep_dir, "top_crops.npy"), crops)
    crop_m2 = int((crops[..., 0] >= 128).sum())
    del crops
    log(slug, f"crop fields: {crop_m2} m2")

    report = {
        "old_m2": int(old.sum()), "new_m2": int(new.sum()), "old_only_m2": int(old_only.sum()), "new_only_m2": int(new_only.sum()),
        "old_kept_m2": int(keep.sum()), "old_in_service_volumes_m2": int((old & service).sum()), "old_lake_surface_m2": int(water_surface.sum()),
        "old_scenery_and_water_meshes_m2": int(surfaces.sum()),
        "classes_m2": {name: int(((c1 == i) & (h1 >= prep.COVERAGE_MIN_CM)).sum()) for i, name in enumerate(features.OBJECT_CLASSES)},
        "labels": label_comparison(labels, old_labels),
    }
    if args.report:
        statics_dir = os.path.join("/extract/statics", slug)
        report["old_only_largest"] = components_report(old_only, bounds, collision_namer(statics_dir, bounds))
        report["new_only_largest"] = components_report(new_only, bounds, scene_namer(objects_of_scene))
    json.dump({
        "map": slug, "cell_m": scene.CELL_M, "shape": list(shape), "pyramid_levels": PYRAMID_LEVELS, "object_classes": features.OBJECT_CLASSES,
        "foliage_classes": features.FOLIAGE_CLASSES, "counts": {"crowns": int(len(arrays["x"])), "crown_meshes": len(names), "building_labels": len(labels)},
        "scenery_left_out": scenery, "scenery_ground_m2": scenery_m2, "painted_tracks_m2": path_m2, "crop_fields_m2": crop_m2, "completeness": report, "raster": raster,
        "seconds": round(time.time() - started),
    }, open(os.path.join(prep_dir, "top_meta.json"), "w"), indent=1)
    log(slug, "done", f"{time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
