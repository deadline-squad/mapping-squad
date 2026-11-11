"""Prepare the objects and crowns of the detailed map tiles from the client scene (after prep.py).

Usage: scene_prep.py <map> [--workers N] [--report] [--keep-raw] [--redo-merge | --rasterized]

Reads (container paths, see maptiles.sh):
    /scene/<map>/               the client scene (SquadExtract scene, tools/maprender): visible LOD 0 meshes and placements
    /prep/<map>/                ground.npy, meta.json and the 0.25 m collision raster obj_*.npy of prep.py
    /features/<map>/            server foliage (which trees have a blocking trunk) and landscape splines (top_lines.json)
    /extract/statics/<map>/     server static mesh collision (what of the old raster it explains, and the names of what the report finds only in the old raster)

Writes /prep/<map>/:
    top_h<k>.npy     uint16 object height above ground (cm) on the 0.1 * 2**k m grid, the highest cell sample
    top_c<k>.npy     uint8 class (features.OBJECT_CLASSES) of the highest object in the cell
    top_v<k>.npy     uint8 share of the cell covered by objects of 0.3 m and more, 0..255 (anti-aliased edges)
    top_labels.json  roof height labels of the larger buildings
    top_water.json   water planes of the scene (lakes whose planes the server files lack), as water.json
    top_water_surface.npy  float32 top of the scene's river and pond meshes on the 1 m grid of ground.npy, m above the map's lowest
                     point, NO_WATER_SURFACE where none (river_surface)
    top_ground.npy   ground.npy with the scene's scenery where it is the ground: in the voids beyond the landscape, and over the landscape where the server collides with it (scenery_ground)
    top_ground_base.npy  top_ground smoothed by GROUND_BASE_SIGMA_M, the ground a structure's colour measures its height from
    top_lines.json   the landscape splines (lines.json) with the roads', tracks' and pavements' edges narrowed to the width their meshes show (road_width)
    top_paths.npy    uint8 weight of the tracks painted into the landscape on the 1 m grid of ground.npy (landscape_paths)
    crowns.npz       trees, bushes, palms and rocks of the scene (crowns.scene_crowns), with crowns_stamps.npy and crowns.json
    top_crops.npy    uint8 [rows, cols, 2] cover and height (dm) of the crop fields on the 1 m grid of ground.npy (crowns.crop_fields)
    raw_{h,c,v}0.npy (only with --keep-raw) the scene raster before the old raster's objects were merged in (--redo-merge starts from it),
                     with raw_raster.json (the sampler that made it)
    top_meta.json    grid, counts, sources and the completeness against the old raster (report)

Level 0 (top_h0, top_c0, top_v0) is rasterized here on the CPU, or beforehand on the GPU by scene_raster_gpu.py (which writes
top_raster.json); --rasterized starts from that.

The grid of level 0 has cells of CELL_M metres, cell [r, c] covering [c, c + 1) * CELL_M east and [r, r + 1) * CELL_M south of
the map's minimum corner. Objects that the scene raster does not draw but the static meshes' collision in the old raster (prep.py)
holds are kept from the old raster: its cells farther than OLD_KEEP_M from any scene object, in runs of at least OLD_KEEP_MIN_M2
that the scene shows before its thin objects are taken out (shown_runs: a run it shows nothing of is collision without a mesh).
What the old raster holds besides is no object (old_non_objects): the tops of the meshes the scene has as terrain or water
(scene_objects.surface_groups: background mountains, _Vista levels, rivers) and of the sheets the game does not show
(scene_objects.sheet_groups), which the server's collision holds as objects; what only SquadHeight holds; ground cover; the
cells off the landscape; and the railway tracks, which are drawn from their splines.
"""

import argparse
import json
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
import worker_pool

BLOCK = 1024
PYRAMID_LEVELS = 7
OLD_KEEP_M = 2
OLD_KEEP_MIN_M2 = 4
VOID_MIN_M2 = 1000
# SquadHeight's floor lies on the served heightmap's minimum, up to the float rounding of z_min (Kohat: 0.0001 m)
VOID_FLOOR_M = 0.01
SURFACE_MATCH_M = 2.0
SURFACE_FLUSH_M = 0.25
TERRAIN_RUN_SHARE = 0.5
SERVICE_SHARE = 0.5
SHOWN_RUN_SHARE = 0.5
SHOWN_TILE_M = 16
LEGACY_STEP_M = 0.25
REPORT_MIN_M2 = 40
REPORT_ITEMS = 8
RASTER_CHUNK_CELLS = 1_000_000
# The ground a structure's colour measures its height from (render.draw_objects): the ground smoothed by a Gaussian of this
# sigma (m), so the edge of a jetty or a rock under a deck, or the landscape's 1 m steps, do not show through a flat roof
GROUND_BASE_SIGMA_M = 6.0
NO_WATER_SURFACE = -1e9

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
    with worker_pool.Pool(workers, _init, (scene_dir, prep_dir, z_min, bounds)) as pool:
        for done, count in enumerate(pool.imap_unordered(_block, tasks), 1):
            total += count
            if done % max(1, len(tasks) // 10) == 0:
                log(f"scene objects {done}/{len(tasks)} blocks")
    return total


def ground_base(ground):
    """The ground (1 m grid) a structure's colour measures its height from: smoothed by GROUND_BASE_SIGMA_M (render.draw_objects)."""
    return ndimage.gaussian_filter(np.asarray(ground, np.float32), GROUND_BASE_SIGMA_M, mode="nearest")


def river_surface(water_top, z_min):
    """The top of the scene's water meshes (surface_top, absolute m) as heights above the map's lowest point, NO_WATER_SURFACE
    where no mesh lies: the surface render.draw_water puts water under.

    A river is a mesh bent along its spline, and its surface is the mesh's, not the spline's centre line: on Anvil the mesh lies
    up to 0.5 m above the line (median 0.16 m), so water drawn below the line's height was 12 000 m2 of a river of 131 000 m2.
    """
    return np.where(np.isfinite(water_top), water_top - z_min, NO_WATER_SURFACE).astype(np.float32)


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


def box_mask(boxes, bounds, shape):
    """Bool [rows, cols] on the 1 m grid: inside one of the world boxes [n, 4] (x0, y0, x1, y1 in m)."""
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


def edge_points(triangles, spacing):
    """Points [n, 3] along the edges of triangles [t, 3, 3], their corners included, at most ``spacing`` apart."""
    starts = triangles.reshape(-1, 3)
    ends = triangles[:, [1, 2, 0]].reshape(-1, 3)
    steps = np.maximum(np.ceil(np.linalg.norm(ends - starts, axis=1) / spacing), 1).astype(np.int64)
    edge = np.repeat(np.arange(len(steps)), steps)
    share = (np.arange(steps.sum()) - np.repeat(np.cumsum(steps) - steps, steps)) / steps[edge]
    return starts[edge] + (ends - starts)[edge] * share[:, None]


def unthinned_objects(objects_of_scene, ground, z_min, bounds, wanted):
    """Bool [rows, cols] on the 1 m grid of ``wanted``: the scene has an object standing prep.COVERAGE_MIN_CM and more in the metre,
    however thin: what the game shows there, where the raster the tiles are drawn from has lost what is narrower than
    scene_objects.THIN_WIDTH_M.

    A metre holds an object when a cell of the scene raster stands that high in it before scene_objects.remove_thin, or when an
    edge of a shown mesh passes that high through it: the raster's points are 5 cm apart and miss a wire, a clothesline or a fence
    of one sheet that runs between them, and the old raster's run along such an object must not depend on how the object lies on
    the grid. Drawn on the CPU (scene_objects.sample_tops) in tiles of SHOWN_TILE_M metres, and only the tiles that hold a wanted
    metre or one beside it: the cost follows the wanted area, not the map's. A metre of a tile that was not drawn is False.
    """
    per = round(1 / scene.CELL_M)
    shape0 = level0_shape(bounds)
    seen = np.zeros(wanted.shape, bool)
    rows, cols = np.nonzero(ndimage.binary_dilation(wanted, structure=np.ones((3, 3))))
    for tile_row, tile_col in sorted(set(zip((rows // SHOWN_TILE_M).tolist(), (cols // SHOWN_TILE_M).tolist()))):
        r0, c0 = tile_row * SHOWN_TILE_M * per, tile_col * SHOWN_TILE_M * per
        r1, c1 = min(r0 + SHOWN_TILE_M * per, shape0[0]), min(c0 + SHOWN_TILE_M * per, shape0[1])
        samples = scene.block_samples(objects_of_scene, bounds, r0, r1, c0, c1, scene.sample_tops)
        if samples is None:
            continue
        height_cm, _, _ = scene.block_cells(samples, ground, z_min, bounds, r0, r1, c0, c1, thin=False)
        metres = (-(-(r1 - r0) // per), -(-(c1 - c0) // per))
        cells = np.zeros((metres[0] * per, metres[1] * per), np.uint16)
        cells[:height_cm.shape[0], :height_cm.shape[1]] = height_cm
        part = seen[tile_row * SHOWN_TILE_M:tile_row * SHOWN_TILE_M + metres[0], tile_col * SHOWN_TILE_M:tile_col * SHOWN_TILE_M + metres[1]]
        part |= (cells.reshape(metres[0], per, metres[1], per).max((1, 3)) >= prep.COVERAGE_MIN_CM)[:part.shape[0], :part.shape[1]]
        # The edges of the meshes that reach the tile
        x0, y0 = bounds["min_x"] + tile_col * SHOWN_TILE_M, bounds["min_y"] + tile_row * SHOWN_TILE_M
        x1, y1 = x0 + part.shape[1], y0 + part.shape[0]
        for group, hit in scene.hit_groups(objects_of_scene, x0, y0, x1, y1):
            corners = objects_of_scene.triangles(group)
            for m in group["matrices"][hit]:
                world = ((corners @ m[:3, :3]) + m[3, :3]).reshape(-1, 3, 3) / 100
                reach = (world[:, :, 0].max(1) >= x0) & (world[:, :, 0].min(1) < x1) & (world[:, :, 1].max(1) >= y0) & (world[:, :, 1].min(1) < y1)
                points = edge_points(world[reach], 1.0 / per)
                points = points[(points[:, 0] >= x0) & (points[:, 0] < x1) & (points[:, 1] >= y0) & (points[:, 1] < y1)]
                if not len(points):
                    continue
                below = scene.ground_points(ground, z_min, points[:, 1] - bounds["min_y"], points[:, 0] - bounds["min_x"])
                high = points[points[:, 2] - below >= prep.COVERAGE_MIN_CM / 100]
                part[(high[:, 1] - y0).astype(np.int64), (high[:, 0] - x0).astype(np.int64)] = True
    return seen


def shown_runs(keep, seen):
    """keep without its connected runs (8-neighbour) that the scene does not show: runs of which less than SHOWN_RUN_SHARE of the
    metres have a metre of ``seen`` (unthinned_objects) in them or beside them.

    What merge_old keeps is what the scene raster drops as thin and the server collides with: the frames of unfinished tents,
    power lines, clotheslines, signs, pipe stands. The game shows them, and the scene has them all along their runs: of the
    29 690 m2 kept on the 25 maps, 25 159 m2 lie in 1 423 runs of which none is shown in less than three quarters of its metres.
    A run of which the scene shows nothing is collision without a mesh over it: the collision of Manicouagan's dam meshes that
    stands 2 to 3 m above the reservoir where the game shows water (275 m2), that of background mountains and terrain meshes
    along a map's edge (Kamdesh's mountains, 1 905 m2), of river and lake planes, of road meshes, of the gap in a ruined wall.
    Those are 4 531 m2 in 119 runs, none shown in more than a tenth of its metres.
    """
    labels, count = ndimage.label(keep, structure=np.ones((3, 3)))
    if not count:
        return keep
    total = np.bincount(labels.ravel(), minlength=count + 1)
    beside = ndimage.binary_dilation(seen, structure=np.ones((3, 3)))
    shown = np.bincount(labels.ravel(), weights=beside.ravel(), minlength=count + 1) >= SHOWN_RUN_SHARE * np.maximum(total, 1)
    shown[0] = False
    return keep & shown[labels]


def collision_footprints(statics_dir, bounds, shape):
    """(any, ground cover): bool [rows, cols] on the 1 m grid, inside the box of a static mesh placement with collision (the placements
    prep.py rasterizes), and inside the box of such a placement of ground cover.

    The old raster has two sources, the static meshes' collision and SquadHeight's surface where it stands above the landscape
    (prep.merge_sdk_objects), so its cells outside the first mask are SquadHeight's alone, and no object the scene lacks. SquadHeight
    was traced in the SDK, on a map that is not the game build's: what the game has of its objects is in the client scene (the
    components of Blueprint actors too), and what the scene has nothing near is not in the game (Al Basrah: blocks of a Vista city that
    the build does not have along the north edge, 3 to 12 m high, and walls in open sand; Black Coast: steps across a river).

    Ground cover (scene_objects.GROUND_COVER_NAME: crops, flowers, weeds) is left out of the scene's objects (crowns.crop_fields
    draws the crop fields), so nothing of the scene stands near its collision either: Yehorivka has 1 634 maize plants set by hand
    with the BlockAll profile, each about 1.3 m wide and 2.4 m high, while the plants of the fields themselves have no collision.
    """
    every, cover_boxes = [np.zeros((0, 4))], [np.zeros((0, 4))]
    for mesh, (_, boxes, _) in prep._load_instances(statics_dir, bounds).items():
        every.append(boxes)
        if scene.GROUND_COVER_NAME.search(os.path.basename(objects.mesh_name(statics_dir, mesh) or "")):
            cover_boxes.append(boxes)
    return box_mask(np.concatenate(every), bounds, shape), box_mask(np.concatenate(cover_boxes), bounds, shape)


def off_landscape(cover, shape):
    """Bool [rows, cols] on the 1 m grid: cells outside the game landscape (cover NO_COVER).

    There ground.npy is SquadHeight's surface, the top of all the server has, so the old raster's height over it is no object's. Next
    to the landscape it is the fall of the ground between the two: prep.py measures every point of its 0.25 m grid from the ground
    interpolated between the nodes, and Gorodok's first column, a node on the Vista mesh 15 m above the landscape's first node, holds
    3.7, 7.4 and 11.2 m at its three points towards it, a wall 1 m wide along the whole west edge.
    """
    return fit(np.asarray(cover) == features.NO_COVER, shape)


def railway_cells(lines, bounds, shape):
    """Bool [rows, cols] on the 1 m grid: cells between the edges of a railway's spline segments (``lines``: features.splines).

    The tiles draw a railway from its spline. The scene raster has nothing of the track there: its sleepers lie lower than
    COVERAGE_MIN_CM and its rails are thinner than scene_objects.THIN_WIDTH_M. The server's collision of the track mesh stands 0.3 to
    0.45 m high, and the old raster would hold it as structures along the line (Manicouagan: 815 m2 in runs of up to 52 m2).
    """
    canvas = Image.new("L", (shape[1], shape[0]), 0)
    draw = ImageDraw.Draw(canvas)
    for line in lines:
        if line["cls"] == "rail":
            draw.polygon([(x - bounds["min_x"], y - bounds["min_y"]) for x, y in line["left"] + line["right"][::-1]], fill=1, outline=1)
    return np.asarray(canvas, bool)


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


def merge_old(prep_dir, new_h1, shape1, service, not_objects, unthinned, strip=1000):
    """Paint the old raster's objects that the scene lacks into level 0; returns (old mask, kept mask, old-only mask) on the 1 m grid.

    What ``not_objects`` marks is no object: the old raster's lake surfaces (legacy_water_surface), its terrain (legacy_terrain), its
    water meshes (legacy_water) and sheets (legacy_sheets), what no static mesh's collision explains and the ground cover
    (collision_footprints), the cells off the landscape (off_landscape) and the railway tracks (railway_cells): old_non_objects.
    The old raster holds collision the game does not show (invisible walls around the map, zone boxes): its runs that lie
    in the scene's service volumes (``service``) are not kept. Nor are its rocks: the scene shows every rock mesh, and what
    only the collision has of them is the scenery beyond the map (mountains, background terrain, SCENERY_MIN_SIDE_M and wider).
    Nor are the runs of which the scene shows nothing even before its thin objects are taken out (shown_runs; ``unthinned``: the
    function that gives unthinned_objects for a bool grid of metres): collision with no mesh over it.
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
    keep = shown_runs(keep, unthinned(keep))
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


def scenery_ground(ground, cover, land_top, z_min, terrain):
    """(ground [H, W] float32 on the 1 m grid of ground.npy with the scenery that is the ground taken in, void cells filled, cells raised).

    Past the game landscape prep.py takes SquadHeight's surface, the server's world. Where the server has nothing (the background
    mountains of Skorpo and Blackcoast are client meshes without collision) that surface is its floor, the lowest point of the
    served heightmap: ground under VOID_FLOOR_M outside the landscape (cover NO_COVER), in runs of VOID_MIN_M2 and more. Below the
    sea level such a void is drawn as sea. The scenery of the client scene (``land_top``, the surface_top of
    scene_objects.surface_groups' land) gives those cells its height; a void that no scenery covers (the open sea) keeps its floor.

    On the landscape the scenery can be the ground too: along a map's edge the landscape runs on below a mesh that the game shows
    and the server collides with (Gorodok: from 34 m before the east edge the landscape falls away under the Vista mesh, over 2 m
    below it at the frame, and its last 16 m repeat one height per row, the rows 0.07 to 0.16 m apart, which the hillshade draws as
    bars; in the west it lies 15 m below, and the served heightmap holds the mesh's height). An area (8-neighbour) where the scenery
    lies above the landscape takes the scenery's height when the server holds that surface and it continues the ground around it.
    The server holds it when at least TERRAIN_RUN_SHARE of the area's cells that rise COVERAGE_MIN_CM and more are ``terrain`` (bool
    on the 1 m grid: the cells of legacy_terrain that a static mesh's collision explains): a mesh the server has no collision for
    stays scenery over the ground. It continues the ground when at least TERRAIN_RUN_SHARE of the cells along the area's rim, lifted
    to the scenery, step less than SURFACE_MATCH_M to the ground beside them (rim_steps): a block of a Vista city stands on the
    ground and is no hill.
    """
    filled = np.array(ground, np.float32)
    void = (np.asarray(cover) == features.NO_COVER) & (filled < VOID_FLOOR_M)
    labels, count = ndimage.label(void)
    fill = np.zeros(filled.shape, bool)
    if count:
        large = np.zeros(count + 1, bool)
        large[1:] = ndimage.sum_labels(void, labels, np.arange(1, count + 1)) >= VOID_MIN_M2
        fill = large[labels] & np.isfinite(land_top)
        filled[fill] = land_top[fill] - z_min
    scenery = land_top - z_min
    rise = np.where(void, 0, scenery - filled)
    labels, count = ndimage.label(rise > 0, structure=np.ones((3, 3)))
    raised = np.zeros(filled.shape, bool)
    if count:
        share = lambda part, of: np.bincount(labels[part], minlength=count + 1) >= TERRAIN_RUN_SHARE * np.maximum(np.bincount(labels[of], minlength=count + 1), 1)
        tall = rise * 100 >= prep.COVERAGE_MIN_CM
        rim, step = rim_steps(rise > 0, scenery, filled)
        ground_area = share(tall & fit(terrain, filled.shape), tall) & share(rim & (step < SURFACE_MATCH_M), rim)
        ground_area[0] = False
        raised = ground_area[labels]
        filled[raised] = scenery[raised]
    return filled, int(fill.sum()), int(raised.sum())


def rim_steps(area, lifted, ground):
    """(rim, step) [H, W]: the cells of ``area`` (bool) with a neighbour (8) outside it, and the largest step (m) from such a cell at its
    ``lifted`` height to the ``ground`` of a neighbour outside (0 off the rim). The grid's edge is no neighbour."""
    rim, step = np.zeros(area.shape, bool), np.zeros(area.shape, np.float32)
    rows, cols = area.shape
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr or dc:
                cell = (slice(max(-dr, 0), rows - max(dr, 0)), slice(max(-dc, 0), cols - max(dc, 0)))
                beside = (slice(max(dr, 0), rows - max(-dr, 0)), slice(max(dc, 0), cols - max(-dc, 0)))
                edge = area[cell] & ~area[beside]
                rim[cell] |= edge
                step[cell] = np.maximum(step[cell], np.where(edge, np.abs(lifted[cell] - ground[beside]), 0))
    return rim, step


def legacy_terrain(land_top, ground, z_min, old_height_cm, shape):
    """Bool [rows, cols] on the 1 m grid: cells of the old raster that are the server's collision of a terrain mesh of the scene
    (``land_top``: the meshes' tops, absolute m on the grid of ground.npy), not objects.

    A cell's top must be within SURFACE_MATCH_M of the mesh's top. A terrain mesh may be a low-poly copy of the landscape lying on
    the ground (Chora, Skorpo, Goose Bay), where a low wall would match it too: a run of matching cells (8-neighbour) is terrain when
    at least TERRAIN_RUN_SHARE of its cells show the mesh, and then all of them, down to the foot of a mountain. A cell shows the
    mesh when the mesh rises SURFACE_MATCH_M and more above the ground (a background mountain), or when the mesh rises at least
    COVERAGE_MIN_CM and the cell's top is flush with it, within SURFACE_FLUSH_M: the mesh is the ground there, the surface the
    server traced, where the landscape under it lies flat (Gorodok's edge, a band along the map's side that rises from 0.3 to 2.3 m).
    """
    old = fit(old_height_cm, shape).astype(np.float32) / 100
    ground_m = fit(ground, shape) + z_min
    present = old * 100 >= prep.COVERAGE_MIN_CM
    land_top = fit(land_top, shape)
    gap = np.abs(ground_m + old - land_top)
    rise = land_top - ground_m
    on_terrain = present & (gap < SURFACE_MATCH_M)
    shown = on_terrain & ((rise >= SURFACE_MATCH_M) | ((gap < SURFACE_FLUSH_M) & (rise * 100 >= prep.COVERAGE_MIN_CM)))
    del land_top, ground_m, gap, rise
    labels, count = ndimage.label(on_terrain, structure=np.ones((3, 3)))
    terrain_run = np.zeros(count + 1, bool)
    if count:
        cells = np.bincount(labels.ravel(), minlength=count + 1)
        terrain_run = np.bincount(labels.ravel(), weights=shown.ravel(), minlength=count + 1) >= TERRAIN_RUN_SHARE * np.maximum(cells, 1)
        terrain_run[0] = False
    return on_terrain & terrain_run[labels]


def legacy_water(water_top, ground, z_min, old_height_cm, shape):
    """Bool [rows, cols] on the 1 m grid: cells of the old raster whose top is within SURFACE_MATCH_M of a water mesh's (``water_top``:
    the tops of scene_objects.surface_groups' water, absolute m on the grid of ground.npy), which the server's collision holds as objects."""
    old = fit(old_height_cm, shape).astype(np.float32) / 100
    present = old * 100 >= prep.COVERAGE_MIN_CM
    return present & (np.abs(fit(ground, shape) + z_min + old - fit(water_top, shape)) < SURFACE_MATCH_M)


def lowest_ground(ground, shape):
    """The ground (m, float32) [rows, cols] under the lowest of the 4 x 4 points of prep.py's 0.25 m grid in each metre (bilinear between
    the nodes of ``ground``): the ground that the old raster's height of a level surface over the metre is measured from."""
    nodes = np.pad(np.asarray(ground, np.float32), ((0, 1), (0, 1)), mode="edge")
    nodes = np.pad(nodes, ((0, max(shape[0] + 1 - nodes.shape[0], 0)), (0, max(shape[1] + 1 - nodes.shape[1], 0))), mode="edge")[:shape[0] + 1, :shape[1] + 1]
    here, east, south, across = nodes[:-1, :-1], nodes[:-1, 1:], nodes[1:, :-1], nodes[1:, 1:]
    lowest = here.copy()
    for south_share in np.arange(4) * LEGACY_STEP_M:
        for east_share in np.arange(4) * LEGACY_STEP_M:
            north_row = here * (1 - east_share) + east * east_share
            south_row = south * (1 - east_share) + across * east_share
            np.minimum(lowest, north_row * (1 - south_share) + south_row * south_share, out=lowest)
    return lowest


def legacy_sheets(sheet_top, ground, z_min, old_height_cm, shape):
    """Bool [rows, cols] on the 1 m grid: cells of the old raster that are the server's collision of a flat sheet the game does not show
    (``sheet_top``: the tops of scene_objects.sheet_groups, absolute m on the grid of ground.npy).

    The old raster holds a sheet as an object that stands at the sheet's height over the ground below it, measured where that ground
    is lowest in the metre (lowest_ground): a cell is the sheet when its height is that, within SURFACE_FLUSH_M. All 6 622 m2 of Goose
    Bay's kept ice are within 0.05 m of it, and a crash barrier that stands beside a sheet lying on the ground (Harju) is 0.8 m off.
    """
    old = fit(old_height_cm, shape).astype(np.float32) / 100
    present = old * 100 >= prep.COVERAGE_MIN_CM
    return present & (np.abs(old - (fit(sheet_top, shape) - z_min - lowest_ground(ground, shape))) < SURFACE_FLUSH_M)


def old_non_objects(objects_of_scene, statics_dir, planes, lines, ground, cover, z_min, old_height_cm, bounds, shape):
    """What the old raster holds that is no object the scene lacks: ({reason: bool [rows, cols] on the 1 m grid}, the tops of the
    scene's terrain meshes and of its water meshes, absolute m on the grid of ground.npy). merge_old keeps nothing of them; the
    reasons name the report's rows.

    ``planes``: scene_objects.water_planes; ``lines``: features.splines; ``old_height_cm``: obj_h2.npy.
    """
    scene_dir = objects_of_scene.directory
    land, water = scene.surface_groups(scene_dir)
    land_top = surface_top(objects_of_scene, land, ground.shape, bounds)
    water_top = surface_top(objects_of_scene, water, ground.shape, bounds)
    sheet_top = surface_top(objects_of_scene, scene.sheet_groups(scene_dir), ground.shape, bounds)
    collided, ground_cover = collision_footprints(statics_dir, bounds, shape)
    return {
        "lake_surface": legacy_water_surface(planes, bounds, shape, ground, old_height_cm),
        "scenery": legacy_terrain(land_top, ground, z_min, old_height_cm, shape),
        "water_meshes": legacy_water(water_top, ground, z_min, old_height_cm, shape),
        "sheets": legacy_sheets(sheet_top, ground, z_min, old_height_cm, shape),
        "without_collision": ~collided,
        "ground_cover": ground_cover,
        "off_landscape": off_landscape(cover, shape),
        "railway": railway_cells(lines, bounds, shape),
    }, land_top, water_top


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
        raster = json.load(open(os.path.join(prep_dir, "raw_raster.json")))
        log(slug, "scene raster restored from raw_*.npy")
    elif args.rasterized:
        raster = json.load(open(os.path.join(prep_dir, "top_raster.json")))
        if raster["shape"] != list(shape):
            raise SystemExit(f"{slug}: top_raster.json is for a level 0 of {raster['shape']}, the map's is {list(shape)}")
        log(slug, f"scene objects rasterized on the GPU ({raster['renderer']}), {raster['covered_cells']} covered cells, {raster['seconds']} s")
        if args.keep_raw:
            copy_raster(prep_dir, "top", "raw")
            json.dump(raster, open(os.path.join(prep_dir, "raw_raster.json"), "w"))
    else:
        covered = rasterize(scene_dir, prep_dir, bounds, z_min, shape, args.workers)
        log(slug, f"scene objects rasterized, {covered} covered cells")
        if args.keep_raw:
            copy_raster(prep_dir, "top", "raw")
            json.dump(raster, open(os.path.join(prep_dir, "raw_raster.json"), "w"))
    new_h1, _ = pool_metres(prep_dir)
    shape1 = new_h1.shape
    service = box_mask(scene.service_boxes(scene_dir), bounds, shape1)
    planes = scene.water_planes(scene_dir, z_min)
    json.dump({"planes": planes}, open(os.path.join(prep_dir, "top_water.json"), "w"))
    ground = np.load(os.path.join(prep_dir, "ground.npy"), mmap_mode="r")
    old_h2 = np.load(os.path.join(prep_dir, "obj_h2.npy"))
    cover = np.load(os.path.join(prep_dir, "cover.npy"), mmap_mode="r")
    statics_dir = os.path.join("/extract/statics", slug)
    lines, _ = features.splines(os.path.join("/features", slug))
    not_objects, land_top, water_top = old_non_objects(objects_of_scene, statics_dir, planes, lines, ground, cover, z_min, old_h2, bounds, shape1)
    np.save(os.path.join(prep_dir, "top_water_surface.npy"), river_surface(water_top, z_min))
    del water_top
    del lines
    del old_h2
    filled, scenery_m2, raised_m2 = scenery_ground(ground, cover, land_top, z_min, not_objects["scenery"] & ~not_objects["without_collision"])
    np.save(os.path.join(prep_dir, "top_ground.npy"), filled)
    np.save(os.path.join(prep_dir, "top_ground_base.npy"), ground_base(filled))
    del filled, land_top
    log(slug, f"ground from the scenery: {scenery_m2} m2 beyond the landscape, {raised_m2} m2 on it")
    paths = landscape_paths.path_weights(scene_dir, bounds, ground.shape)
    np.save(os.path.join(prep_dir, "top_paths.npy"), paths)
    path_m2 = int((paths >= 128).sum())
    del paths
    log(slug, f"tracks painted into the landscape: {path_m2} m2")
    lines = write_top_lines(scene_dir, os.path.join("/features", slug), prep_dir)
    log(slug, f"{lines} road segments narrowed to their visible width")
    old, keep, old_only = merge_old(prep_dir, new_h1, shape1, service, np.logical_or.reduce(list(not_objects.values())),
                                    lambda wanted: unthinned_objects(objects_of_scene, ground, z_min, bounds, wanted))
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
        "old_kept_m2": int(keep.sum()), "old_in_service_volumes_m2": int((old & service).sum()),
        **{f"old_{reason}_m2": int((old & mask).sum()) for reason, mask in not_objects.items()},
        "classes_m2": {name: int(((c1 == i) & (h1 >= prep.COVERAGE_MIN_CM)).sum()) for i, name in enumerate(features.OBJECT_CLASSES)},
        "labels": label_comparison(labels, old_labels),
    }
    if args.report:
        report["old_only_largest"] = components_report(old_only, bounds, collision_namer(statics_dir, bounds))
        report["new_only_largest"] = components_report(new_only, bounds, scene_namer(objects_of_scene))
    json.dump({
        "map": slug, "cell_m": scene.CELL_M, "shape": list(shape), "pyramid_levels": PYRAMID_LEVELS, "object_classes": features.OBJECT_CLASSES,
        "foliage_classes": features.FOLIAGE_CLASSES, "counts": {"crowns": int(len(arrays["x"])), "crown_meshes": len(names), "building_labels": len(labels)},
        "scenery_left_out": scenery, "scenery_ground_m2": scenery_m2, "ground_on_scenery_m2": raised_m2, "painted_tracks_m2": path_m2, "crop_fields_m2": crop_m2, "completeness": report, "raster": raster,
        "seconds": round(time.time() - started),
    }, open(os.path.join(prep_dir, "top_meta.json"), "w"), indent=1)
    log(slug, "done", f"{time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
