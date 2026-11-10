"""Trees, bushes and rocks of the client scene, and the top-down silhouette of every kind of them (a stamp).

The instances are the scene's foliage components (the same placements the Standard HD layer shows). Each mesh is classified by
its name (features._FOLIAGE_RULES); flowers, crops and ground clutter are left out. A stamp is the outline of the mesh's LOD 0
seen from above, taken once: coverage and relative height on a STAMP_PX square spanning the mesh's horizontal reach from its
pivot. An instance is drawn with its stamp turned by the instance's yaw and scaled to its crown radius (render.draw_foliage).

Whether a tree has a trunk that blocks (the tactical information of the trunk dot) is a property of the mesh in the game's
collision data, which only the server files hold (features.foliage); it is looked up there by mesh path.

The crops among the ground cover are no crowns but fields: crop_fields gives their cover and height on the map's 1 m grid
(render.draw_crops).
"""

import json
import math
import os
import re

import numpy as np
from scipy import ndimage

import features
import objects
import scene_objects as scene

STAMP_PX = 64
# Crops among the scene's ground cover (left out of the crowns): fields of wheat, maize, poppies, cannabis and potatoes. Wild field
# flowers (whose names hold "flower", also the field poppy), field grass and weeds are not crops.
CROP_NAME = re.compile(r"crop|wheat|(^|_)corn_|maize|popp(y|ies)|canib|cannabis|potato", re.IGNORECASE)
WILD_FLOWER_NAME = re.compile(r"flower", re.IGNORECASE)
# Gaps between the plants of a field that its cover fills (sigma of a Gaussian, m)
CROP_FILL_M = 1.5
# Gaps between leaf cards and branches that a crown fills: share of the stamp's side
CLOSING_SHARE = 0.09


def trunk_collision(features_dir):
    """{mesh path: whether its trunk blocks} from the server's foliage.ndjson (features.foliage's rule)."""
    result = {}
    for line in open(os.path.join(features_dir, "foliage.ndjson")):
        item = json.loads(line)
        info = item.get("info") or {}
        result[item["mesh"]] = bool(info.get("collision")) and objects.blocks(item.get("collision"))
    return result


def silhouette(vertices, indices, ranges):
    """(stamp uint8 [STAMP_PX, STAMP_PX, 2]: coverage, height share; reach cm) of a mesh seen from above.

    The coverage is closed over the gaps of loose leaves and smoothed, the height share is the top surface over the mesh's
    highest point, extended into the closed gaps from the nearest surface.
    """
    corners = scene.corners_of(vertices, indices, ranges)
    if not len(corners):
        return None
    reach = float(max(np.abs(corners[:, 0]).max(), np.abs(corners[:, 1]).max(), 1.0))
    step = 2 * reach / STAMP_PX
    top = np.full((STAMP_PX, STAMP_PX), -np.inf)
    objects.CHUNK_CELLS = 1_000_000
    objects.rasterize(corners.reshape(-1, 3, 3).astype(np.float64), top, -reach + step / 2, -reach + step / 2, step)
    covered = np.isfinite(top)
    if not covered.any():
        return None
    radius = max(1, int(round(CLOSING_SHARE * STAMP_PX)))
    y, x = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    disc = x * x + y * y <= radius * radius
    padded = np.pad(covered, radius)
    closed = ndimage.binary_closing(padded, structure=disc)[radius:-radius, radius:-radius]
    closed = ndimage.binary_fill_holes(closed)
    z_top = float(top[covered].max())
    height = np.where(covered, top, 0.0)
    nearest = ndimage.distance_transform_edt(~covered, return_distances=False, return_indices=True)
    height = np.where(closed, height[nearest[0], nearest[1]], 0.0)
    height = ndimage.gaussian_filter(np.clip(height, 0, None) / max(z_top, 1.0), 0.8)
    coverage = ndimage.gaussian_filter(closed.astype(np.float64), 0.7)
    stamp = np.stack([np.clip(coverage * 255, 0, 255), np.clip(height * 255, 0, 255)], axis=-1).astype(np.uint8)
    return stamp, reach


def scene_crowns(scene_dir, features_dir):
    """Foliage instances of the scene and one stamp per mesh.

    Returns (columns, names, stamps): columns are arrays over the instances {x, y, z, radius, half_x, half_y, yaw, height, cls,
    collision, mesh} in world metres and degrees (the keys and units of features.foliage, plus ``mesh``, the index into
    ``names``); names are the mesh paths; stamps uint8 [meshes, STAMP_PX, STAMP_PX, 2] (zeros for a mesh drawn as an ellipse).
    """
    collision = trunk_collision(features_dir)
    keys = ("x", "y", "z", "radius", "half_x", "half_y", "yaw", "height", "cls", "collision", "mesh")
    columns = {k: [] for k in keys}
    names, stamps, reaches = [], [], {}
    materials = json.load(open(os.path.join(scene_dir, "materials.json")))
    for item, path, info in scene.read_instances(scene_dir):
        if item["type"] != scene.FOLIAGE_TYPE:
            continue
        name = path.rsplit("/", 1)[-1].split(".")[0]
        # Flowers, crops and ground clutter are no crowns, by the rule that leaves them out of the objects: scattered corn drawn plant
        # by plant covers a field with specks
        if scene.GROUND_COVER_NAME.search(name) or not item["instances"]:
            continue
        cls = features._classify(name, features._FOLIAGE_RULES, None)
        if cls == features.FOLIAGE_SKIP:
            continue
        vertices, indices = scene.read_mesh(scene_dir, info)
        if not len(vertices):
            continue
        lo, hi = vertices[:, :3].min(0), vertices[:, :3].max(0)
        reach = float(max(abs(lo[0]), abs(hi[0]), abs(lo[1]), abs(hi[1])))
        matrices = scene.component_matrices(item)
        scale = np.linalg.norm(matrices[:, 0, :3], axis=1)
        height = hi[2] * scale / 100
        if cls is None:
            cls = features.DECIDUOUS if float(np.median(height)) >= features.TREE_MIN_M else features.BUSH if float(np.median(height)) >= features.BUSH_MIN_M else features.FOLIAGE_SKIP
            if cls == features.FOLIAGE_SKIP:
                continue
        radius = reach * scale / 100
        if cls == features.ROCK:
            keep = radius >= features.ROCK_MIN_RADIUS_M
            matrices, scale, radius, height = matrices[keep], scale[keep], radius[keep], height[keep]
        if not len(matrices):
            continue
        if path not in reaches:
            made = silhouette(vertices, indices, scene.visible_ranges(info, (), materials))
            reaches[path] = len(names)
            names.append(path)
            stamps.append(made[0] if made else np.zeros((STAMP_PX, STAMP_PX, 2), np.uint8))
        n = len(matrices)
        columns["x"].append(matrices[:, 3, 0] / 100)
        columns["y"].append(matrices[:, 3, 1] / 100)
        columns["z"].append(matrices[:, 3, 2] / 100)
        columns["radius"].append(radius)
        columns["half_x"].append((hi[0] - lo[0]) / 2 * scale / 100)
        columns["half_y"].append((hi[1] - lo[1]) / 2 * scale / 100)
        columns["yaw"].append(np.degrees(np.arctan2(matrices[:, 0, 1], matrices[:, 0, 0])))
        columns["height"].append(height)
        columns["cls"].append(np.full(n, cls, np.uint8))
        columns["collision"].append(np.full(n, collision.get(path, False)))
        columns["mesh"].append(np.full(n, reaches[path], np.uint16))
    arrays = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in columns.items()}
    for k in ("x", "y", "z", "radius", "half_x", "half_y", "yaw", "height"):
        arrays[k] = arrays[k].astype(np.float32)
    arrays["cls"] = arrays["cls"].astype(np.uint8)
    arrays["collision"] = arrays["collision"].astype(bool)
    arrays["mesh"] = arrays["mesh"].astype(np.uint16)
    return arrays, names, (np.stack(stamps) if stamps else np.zeros((0, STAMP_PX, STAMP_PX, 2), np.uint8))


def crop_fields(scene_dir, bounds, shape):
    """uint8 [rows, cols, 2] on the 1 m grid of ground.npy (point [r, c] at min_x + c, min_y + r metres): the share of the ground the
    crops of the scene cover (0..255) and their height, cover-weighted, in decimetres; zeros on a map without crops.

    Each plant covers the disc of its mesh's horizontal reach, scaled with the instance; the cover of the points is the plants' area
    around them, smoothed by CROP_FILL_M so the rows of a field close into its area, and at most 1.
    """
    rows, cols = shape
    area = np.zeros(shape, np.float64)
    height_area = np.zeros(shape, np.float64)
    reach_of = {}
    for item, path, info in scene.read_instances(scene_dir):
        if item["type"] != scene.FOLIAGE_TYPE or not item["instances"]:
            continue
        name = path.rsplit("/", 1)[-1].split(".")[0]
        if not CROP_NAME.search(name) or WILD_FLOWER_NAME.search(name):
            continue
        if path not in reach_of:
            vertices, _ = scene.read_mesh(scene_dir, info)
            if not len(vertices):
                reach_of[path] = None
            else:
                lo, hi = vertices[:, :3].min(0), vertices[:, :3].max(0)
                reach_of[path] = (float(max(abs(lo[0]), abs(hi[0]), abs(lo[1]), abs(hi[1]))), float(hi[2]))
        if reach_of[path] is None:
            continue
        reach, top = reach_of[path]
        matrices = scene.component_matrices(item)
        scale = np.linalg.norm(matrices[:, 0, :3], axis=1)
        c = np.rint(matrices[:, 3, 0] / 100 - bounds["min_x"]).astype(np.int64)
        r = np.rint(matrices[:, 3, 1] / 100 - bounds["min_y"]).astype(np.int64)
        inside = (r >= 0) & (r < rows) & (c >= 0) & (c < cols)
        disc = math.pi * (reach * scale[inside] / 100) ** 2
        np.add.at(area, (r[inside], c[inside]), disc)
        np.add.at(height_area, (r[inside], c[inside]), disc * top * scale[inside] / 100)
    result = np.zeros(shape + (2,), np.uint8)
    if not area.any():
        return result
    cover = ndimage.gaussian_filter(area, CROP_FILL_M)
    height = ndimage.gaussian_filter(height_area, CROP_FILL_M) / np.maximum(cover, 1e-9)
    result[..., 0] = np.rint(np.clip(cover, 0, 1) * 255)
    result[..., 1] = np.rint(np.clip(height * 10, 0, 255))
    result[..., 1][result[..., 0] == 0] = 0
    return result

