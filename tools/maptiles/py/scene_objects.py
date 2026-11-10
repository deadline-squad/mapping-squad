"""Visible static meshes of a map's client scene, rasterized top-down into a fine height and class grid.

The scene is written by `SquadExtract scene` (tools/maprender): ``instances.ndjson`` (placements), ``meshes.json`` and
``meshes/<id>.bin`` (LOD 0 vertices, 8 float32 each, then uint32 indices), ``materials.json``. The placements, the skipped levels
and materials follow ``tools/maprender/scene_render.py`` (the "Standard HD" renderer), so the two layers show the same objects.

World axes are the game's: X east, Y south, Z up, centimetres in the files and metres here. Matrices are row-vector 4 x 4
(p_world = p_local @ M), as in tools/heightmaps/py/objects.py.

Grid: cell (r, c) covers [c, c + 1) * CELL_M east and [r, r + 1) * CELL_M south of the map's minimum corner. Every cell is
sampled at 2 x 2 points; its height is the highest of them, its coverage the share of them that stand at least COVERAGE_MIN_M
above the ground, which anti-aliases the edges of the footprints.
"""

import json
import os
import re

import numpy as np
from scipy import ndimage

import features
import objects

CELL_M = 0.1
SUBSAMPLES = 2
OBJECT_MIN_CM = 5
COVERAGE_MIN_M = 0.3
THIN_WIDTH_M = 0.3
THIN_MARGIN = 4
# A placement wider and longer than this (m) is scenery beyond the map, no object (SceneObjects.scenery)
SCENERY_MIN_SIDE_M = 800.0
# A sky sphere is scenery too wide for the map, but no ground
SKY_NAME = re.compile(r"sky", re.IGNORECASE)
# Service volumes that count: walls (their short side) up to SERVICE_THIN_M, or boxes up to SERVICE_SMALL_M2
SERVICE_THIN_M = 30.0
SERVICE_SMALL_M2 = 2500.0
# tools/maprender/scene_render.py: SKIPPED_LEVEL_PARTS, SKIPPED_BLENDS, DEVELOPER_MATERIAL
SKIPPED_LEVEL_PARTS = ("/Coop/", "/Tutorials/", "/Sound_Layers/", "Profiling", "Navmesh", "_Vista", "_Editor_Only")
SKIPPED_BLENDS = ("BLEND_Additive", "BLEND_Modulate", "BLEND_Translucent")
DEVELOPER_MATERIAL = re.compile(r"/Engine/BasicShapes/|/Engine/EngineMaterials/WorldGridMaterial|/GameModes/TC/HexGrid/|/Blockout/MI_\w*Transparent|/Tools/POI_Reference_Marker/|/Gameplay/GameplayBorder/")
WATER_PATH = re.compile(r"water|ocean", re.IGNORECASE)
FOLIAGE_TYPE = "FoliageInstancedStaticMeshComponent"
# Flowers, crops, low grass, weeds, ivy on walls and leaf litter are never drawn (tools/maprender/ground_fit.py FLOWER_NAME), nor are their
# stems. "Corn" and "crop" count only as whole words: wall corners and "cropped" parts are objects.
GROUND_COVER_NAME = re.compile(
    r"flower|foxglove|poppy|poppies|maize|wheat|(^|_)corn_(tall|mix)|(^|_)crop(_|\d|$)|canib|grasscluster|grasstall|fieldgrass|semigreenmix"
    r"|(^|_)fern_|(^|_)weed\d|fol_ivy|broadleaf_(pile|scatter)", re.IGNORECASE)
# Static meshes whose leaves are foliage-shaded (MSM_TwoSidedFoliage) with a plant-like material name are vegetation (hedges, brambles,
# vineyard rows, orchard trees), whatever the mesh is called; tents, awnings and camouflage nets use the same shading but no such name.
FOLIAGE_SHADING = "MSM_TwoSidedFoliage"
PLANT_MATERIAL = re.compile(r"leaf|leaves|foliage|hedge|bush|shrub|bramb+le|branch|grape|vine|twig|almond|(?<!s)tree", re.IGNORECASE)
PLANT_MESH_SHARE = 0.5
# A road surface mesh paints the road into the landscape's runtime virtual texture (an "_RVT" material): it lies on the ground, below
# the objects' height threshold, and only rises above it on a bridge deck (Al Basrah's river bridges)
ROAD_SURFACE_NAME = re.compile(r"(^|_)road(_|$)", re.IGNORECASE)
VIRTUAL_TEXTURE_MATERIAL = "_RVT"


def is_shown(item):
    """Whether a component is drawn at all: not hidden and not in a skipped level."""
    return not item["hidden"] and not any(part in item["level"] for part in SKIPPED_LEVEL_PARTS)


def read_instances(scene_dir, shown_only=True):
    """Placements of the scene: (item, mesh path, mesh info) for every component, by default only those that are shown (is_shown)."""
    meshes = json.load(open(os.path.join(scene_dir, "meshes.json")))
    by_id = {info["id"]: (path, info) for path, info in meshes.items() if "error" not in info}
    for line in open(os.path.join(scene_dir, "instances.ndjson")):
        item = json.loads(line)
        if item["mesh"] not in by_id or (shown_only and not is_shown(item)):
            continue
        path, info = by_id[item["mesh"]]
        yield item, path, info


def instance_matrices(items):
    """[n, 4, 4] row-vector matrices of the per-instance transforms (quaternion q, translation t, scale s) of an instanced component.

    The same as tools/maprender/scene_render.py instance_matrices.
    """
    q = np.array([i["q"] for i in items], np.float64)
    t = np.array([i["t"] for i in items], np.float64)
    s = np.array([i["s"] for i in items], np.float64)
    x, y, z, w = q.T
    m = np.zeros((len(items), 4, 4))
    m[:, 0, 0], m[:, 0, 1], m[:, 0, 2] = 1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)
    m[:, 1, 0], m[:, 1, 1], m[:, 1, 2] = 2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)
    m[:, 2, 0], m[:, 2, 1], m[:, 2, 2] = 2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)
    m[:, :3, :3] *= s[:, None, :].transpose(0, 2, 1)
    m[:, 3, :3] = t
    m[:, 3, 3] = 1
    return m


def component_matrices(item):
    """[n, 4, 4] world matrices of a component's instances (one for a plain component, none for an empty instanced one)."""
    world = objects.component_world(item["chain"])
    if item.get("instances") is None:
        return world[None]
    if not item["instances"]:
        return np.zeros((0, 4, 4))
    return instance_matrices(item["instances"]) @ world


def is_water_mesh(path):
    """Whether a mesh is a water surface (lake, pond, river plane), by the rules of features.water_planes (water is drawn from the water data)."""
    lower = path.lower()
    return bool(re.search(features._WATER_MESH, lower)) and not re.search(features._WATER_MESH_EXCLUDE, lower)


def hidden_material(path, materials, water_shown=False):
    """Whether a material is not shown from above: decals and glass (translucent), light shafts, developer volumes, water surfaces.

    ``water_shown``: a water surface is as shown as its blend mode says (the lakes of water_planes). A lake's material is a dynamic
    instance named after its level (``WL_<map>_Water.<actor>.Lake.MID_...``), so the word "water" in its path says nothing.
    """
    if path and (DEVELOPER_MATERIAL.search(path) or (WATER_PATH.search(path) and not water_shown)):
        return True
    return (materials.get(path) or {}).get("blend", "BLEND_Opaque") in SKIPPED_BLENDS


def visible_ranges(info, overrides, materials, water_shown=False):
    """[(first index, index count)] of the sections of a mesh whose material is shown (hidden_material); `overrides` are the component's material slots."""
    slots = info["materials"]
    ranges = []
    for section in info["sections"]:
        slot = section["material"]
        material = overrides[slot] if slot < len(overrides) and overrides[slot] else (slots[slot] if slot < len(slots) else "")
        if not hidden_material(material, materials, water_shown):
            ranges.append((section["first"], section["triangles"] * 3))
    return ranges


def object_class_of(name, info, overrides, materials):
    """Object class of a static mesh: by its asset name (features.object_class), but a mesh the name leaves a plain structure
    is vegetation when at least PLANT_MESH_SHARE of its shown triangles carry a foliage-shaded plant material.

    A rock or a wall keeps its class: a mossy rock's material is no leaf, and a twig fence is a fence. A road surface mesh
    (ROAD_SURFACE_NAME with a VIRTUAL_TEXTURE_MATERIAL) is a bridge: only a bridge deck lifts it into the objects.
    """
    cls = features.object_class(name)
    if cls != features.STRUCTURE:
        return cls
    slots = info["materials"]
    plant = total = 0
    for section in info["sections"]:
        slot = section["material"]
        material = overrides[slot] if slot < len(overrides) and overrides[slot] else (slots[slot] if slot < len(slots) else "")
        if hidden_material(material, materials):
            continue
        if VIRTUAL_TEXTURE_MATERIAL in material and ROAD_SURFACE_NAME.search(name):
            return features.BRIDGE
        total += section["triangles"]
        if (materials.get(material) or {}).get("shading") == FOLIAGE_SHADING and PLANT_MATERIAL.search(material.rsplit("/", 1)[-1].split(".")[0]):
            plant += section["triangles"]
    return features.VEGETATION if total and plant >= PLANT_MESH_SHARE * total else cls


def read_mesh(scene_dir, info):
    """(vertices [n, 8] float32: position cm, normal, uv; indices uint32) of a mesh's LOD 0."""
    path = os.path.join(scene_dir, "meshes", f"{info['id']}.bin")
    vertices = np.fromfile(path, np.float32, count=info["vertices"] * 8).reshape(-1, 8)
    indices = np.fromfile(path, np.uint32, offset=info["vertices"] * 32)
    return vertices, indices


def bend_along_spline(vertices, spline, bounds):
    """Positions [n, 3] (cm) of a mesh deformed along its spline (USplineMeshComponent, forward axis from the file).

    The engine's slice transform (USplineMeshComponent::CalcSliceTransformAtSplineOffset): cubic Hermite position, smoothstep scale,
    offset and roll. The roll turns the slice about the spline's direction, after the offset. A mesh whose forward axis is Y has its
    X axis up until a roll of -90 degrees stands it up, and the landscape splines give it that roll (pipelines, crash barriers,
    railway tracks, fences): without the roll it is drawn on its side and off its line. tools/maprender/scene_render.py
    bend_along_spline is this deformation without the roll.
    """
    p = spline["p"]
    vec = lambda v: np.array([v["X"], v["Y"], v["Z"]], np.float64)
    p0, t0, p1, t1 = vec(p["StartPos"]), vec(p["StartTangent"]), vec(p["EndPos"]), vec(p["EndTangent"])
    axis = {"X": 0, "Y": 1, "Z": 2}[spline["axis"][-1]]
    side, up = [(1, 2), (2, 0), (0, 1)][axis]
    lo, hi = bounds[0][axis], bounds[1][axis]
    a = np.clip((vertices[:, axis] - lo) / max(hi - lo, 1e-3), 0, 1)[:, None]
    a2, a3 = a * a, a * a * a
    position = (2 * a3 - 3 * a2 + 1) * p0 + (a3 - 2 * a2 + a) * t0 + (-2 * a3 + 3 * a2) * p1 + (a3 - a2) * t1
    direction = (6 * a2 - 6 * a) * p0 + (3 * a2 - 4 * a + 1) * t0 + (-6 * a2 + 6 * a) * p1 + (3 * a2 - 2 * a) * t1
    direction /= np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1e-6)
    world_up = vec(spline["up"]) if any(spline["up"][k] for k in "XYZ") else np.array([0.0, 0.0, 1.0])
    right = np.cross(world_up, direction)
    right /= np.maximum(np.linalg.norm(right, axis=1, keepdims=True), 1e-6)
    upward = np.cross(direction, right)
    start_scale, end_scale = p.get("StartScale", {"X": 1, "Y": 1}), p.get("EndScale", {"X": 1, "Y": 1})
    start_offset, end_offset = p.get("StartOffset", {"X": 0, "Y": 0}), p.get("EndOffset", {"X": 0, "Y": 0})
    blend = a * a * (3 - 2 * a)
    scale_x = start_scale["X"] * (1 - blend) + end_scale["X"] * blend
    scale_y = start_scale["Y"] * (1 - blend) + end_scale["Y"] * blend
    offset_x = start_offset["X"] * (1 - blend) + end_offset["X"] * blend
    offset_y = start_offset["Y"] * (1 - blend) + end_offset["Y"] * blend
    roll = p.get("StartRoll", 0.0) * (1 - blend) + p.get("EndRoll", 0.0) * blend
    rolled_right = np.cos(roll) * right - np.sin(roll) * upward
    rolled_upward = np.cos(roll) * upward + np.sin(roll) * right
    return (position + right * offset_x + upward * offset_y
            + rolled_right * (vertices[:, side:side + 1] * scale_x) + rolled_upward * (vertices[:, up:up + 1] * scale_y))


def corners_of(vertices, indices, ranges):
    """Triangle corners [t * 3, 3] (float32, cm) of the index ranges of a mesh."""
    picked = np.concatenate([indices[first:first + count] for first, count in ranges]) if ranges else np.zeros(0, np.uint32)
    return vertices[picked, :3].astype(np.float32)


def world_boxes(local_lo, local_hi, matrices):
    """World AABBs [n, 4] (x0, y0, x1, y1 in metres) of a local box under row-vector matrices."""
    corners = np.array([[x, y, z, 1.0] for x in (local_lo[0], local_hi[0]) for y in (local_lo[1], local_hi[1]) for z in (local_lo[2], local_hi[2])])
    world = np.einsum("cj,njk->nck", corners, matrices)[:, :, :2] / 100
    return np.concatenate([world.min(1), world.max(1)], axis=1)


class SceneObjects:
    """The shown static meshes of a scene: groups of one mesh (or one spline-bent mesh) with the matrices of its placements.

    A group is a dict: mesh (id), name (mesh path), cls (features object class), ranges (index ranges of the shown
    sections), spline (the component's spline or None), matrices [n, 4, 4], boxes [n, 4] world AABBs in metres.
    Foliage components are left out (crowns.py draws them) and so are flowers and crops. A placement wider and longer than
    SCENERY_MIN_SIDE_M is no object of the map: it is a sky sphere, a low-poly copy of the landscape or mountains beyond the
    map; ``scenery`` counts them by mesh name (surface_groups has them as terrain).
    """

    def __init__(self, scene_dir):
        self.directory = scene_dir
        self.materials = json.load(open(os.path.join(scene_dir, "materials.json")))
        self.groups = []
        plain = {}
        bounds = {}

        def mesh_bounds(info):
            if info["id"] not in bounds:
                vertices, _ = read_mesh(scene_dir, info)
                bounds[info["id"]] = (vertices[:, :3].min(0), vertices[:, :3].max(0)) if len(vertices) else (np.zeros(3), np.zeros(3))
            return bounds[info["id"]]

        self.scenery = {}
        for item, path, info in read_instances(scene_dir):
            name = path.rsplit("/", 1)[-1]
            if item["type"] == FOLIAGE_TYPE or GROUND_COVER_NAME.search(name) or is_water_mesh(path):
                continue
            overrides = tuple(item.get("overrides") or ())
            ranges = visible_ranges(info, overrides, self.materials)
            if not ranges:
                continue
            matrices = component_matrices(item)
            if not len(matrices):
                continue
            if item["spline"] is not None:
                vertices, _ = read_mesh(scene_dir, info)
                bent = bend_along_spline(vertices.astype(np.float64), item["spline"], mesh_bounds(info))
                boxes = world_boxes(bent.min(0), bent.max(0), matrices)
                self.groups.append({"mesh": info["id"], "name": path, "cls": object_class_of(name, info, overrides, self.materials), "ranges": ranges,
                                    "spline": item["spline"], "matrices": matrices, "boxes": boxes})
                continue
            key = (info["id"], overrides)
            if key not in plain:
                plain[key] = {"mesh": info["id"], "name": path, "cls": object_class_of(name, info, overrides, self.materials), "ranges": ranges, "spline": None, "mats": [], "box_list": []}
                lo, hi = mesh_bounds(info)
                plain[key]["local"] = (lo, hi)
            group = plain[key]
            boxes = world_boxes(*group["local"], matrices)
            vast = np.minimum(boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1]) > SCENERY_MIN_SIDE_M
            if vast.any():
                self.scenery[name] = self.scenery.get(name, 0) + int(vast.sum())
            group["mats"].append(matrices[~vast])
            group["box_list"].append(boxes[~vast])
        for group in plain.values():
            if sum(len(m) for m in group["mats"]):
                self.groups.append({"mesh": group["mesh"], "name": group["name"], "cls": group["cls"], "ranges": group["ranges"], "spline": None,
                                    "matrices": np.concatenate(group["mats"]), "boxes": np.concatenate(group["box_list"])})
        self.meshes = json.load(open(os.path.join(scene_dir, "meshes.json")))
        self.infos = {info["id"]: info for info in self.meshes.values()}
        self._triangles = {}
        self._triangle_bytes = 0
        # The boxes of all groups in one array, for hit_groups: group k owns rows box_starts[k]:box_starts[k + 1]
        self.boxes = np.concatenate([group["boxes"] for group in self.groups]) if self.groups else np.zeros((0, 4))
        self.box_starts = np.cumsum([0] + [len(group["boxes"]) for group in self.groups])
        self.box_owner = np.repeat(np.arange(len(self.groups)), np.diff(self.box_starts))

    def triangles(self, group, limit_bytes=300 * 2 ** 20):
        """Local triangle corners [t * 3, 3] (cm) of a group, kept for reuse up to limit_bytes in all."""
        key = id(group)
        if key in self._triangles:
            return self._triangles[key]
        info = self.infos[group["mesh"]]
        vertices, indices = read_mesh(self.directory, info)
        if group["spline"] is not None:
            lo, hi = vertices[:, :3].min(0), vertices[:, :3].max(0)
            vertices = vertices.copy()
            vertices[:, :3] = bend_along_spline(vertices.astype(np.float64), group["spline"], (lo, hi)).astype(np.float32)
        corners = corners_of(vertices, indices, group["ranges"])
        if self._triangle_bytes + corners.nbytes > limit_bytes:
            self._triangles.clear()
            self._triangle_bytes = 0
        self._triangles[key] = corners
        self._triangle_bytes += corners.nbytes
        return corners


def surface_groups(scene_dir):
    """(land, water): groups (the keys of SceneObjects.groups, all sections of the mesh) of the meshes that are terrain or water and
    no object of the map.

    Land is the scenery beyond the map: placements wider and longer than SCENERY_MIN_SIDE_M but the sky, and every mesh of the
    _Vista levels. Water is the water meshes (lakes, rivers) that SceneObjects leaves out. The server's collision raster
    (prep.py) holds them as objects; scene_prep.py takes them out of it, and the land is the ground where the server has none.
    """
    land, water = [], []
    bounds = {}
    for item, path, info in read_instances(scene_dir, shown_only=False):
        if item["hidden"] or item["type"] == FOLIAGE_TYPE:
            continue
        skipped = [part for part in SKIPPED_LEVEL_PARTS if part in item["level"]]
        if skipped not in ([], ["_Vista"]):
            continue
        name = path.rsplit("/", 1)[-1]
        matrices = component_matrices(item)
        if not len(matrices) or SKY_NAME.search(name):
            continue
        group = {"mesh": info["id"], "name": path, "cls": 0, "ranges": [(0, info["indices"])], "spline": item["spline"], "matrices": matrices}
        if is_water_mesh(path):
            water.append(group)
        elif skipped:
            land.append(group)
        elif item["spline"] is None:
            if info["id"] not in bounds:
                vertices, _ = read_mesh(scene_dir, info)
                bounds[info["id"]] = (vertices[:, :3].min(0), vertices[:, :3].max(0)) if len(vertices) else (np.zeros(3), np.zeros(3))
            boxes = world_boxes(*bounds[info["id"]], matrices)
            vast = np.minimum(boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1]) > SCENERY_MIN_SIDE_M
            if vast.any():
                land.append({**group, "matrices": matrices[vast]})
    return land, water


def sheet_groups(scene_dir):
    """Groups (as surface_groups') of the flat sheets that the game does not show from above: placements of meshes no thicker than
    OBJECT_MIN_CM whose component is hidden or whose sections are all hidden materials, water meshes and skipped levels aside
    (surface_groups has those).

    The server's collision holds such a sheet as an object that stands at the sheet's height over the ground below it
    (scene_prep.legacy_sheets): Goose Bay's ponds and rivers are covered by 18 ``BasicShapes/Plane`` placements with a translucent
    ice material, 195 000 m2 of them, and 17 are too large for service_boxes.
    """
    materials = json.load(open(os.path.join(scene_dir, "materials.json")))
    sheets, thickness = [], {}
    for item, path, info in read_instances(scene_dir, shown_only=False):
        if item["type"] == FOLIAGE_TYPE or item["spline"] is not None or is_water_mesh(path) or any(part in item["level"] for part in SKIPPED_LEVEL_PARTS):
            continue
        if not item["hidden"] and visible_ranges(info, tuple(item.get("overrides") or ()), materials):
            continue
        if info["id"] not in thickness:
            vertices, _ = read_mesh(scene_dir, info)
            thickness[info["id"]] = float(np.ptp(vertices[:, 2])) if len(vertices) else np.inf
        matrices = component_matrices(item)
        flat = thickness[info["id"]] * np.linalg.norm(matrices[:, 2, :3], axis=1) <= OBJECT_MIN_CM
        if flat.any():
            sheets.append({"mesh": info["id"], "name": path, "cls": 0, "ranges": [(0, info["indices"])], "spline": None, "matrices": matrices[flat]})
    return sheets


def water_planes(scene_dir, z_min):
    """Water surfaces of the scene (lakes, ponds, river planes): [{polygon [[x, y] * 4] in m, z in m above z_min}].

    The same as features.water_planes, which reads the server's collision bodies and so misses the planes without one: the
    lakes (``BP_Lake*`` actors, the mesh ``SM_env_river``, a flat plane scaled to the lake), which the server holds no body for.
    A plane is the rectangle that a water mesh's bounds make under each placement, at the mesh's top. The game draws it as water
    wherever it lies above the landscape, so where the ground lies below the rectangle's height there is water (render.draw_water),
    and the rectangle's edge is the lake's edge where a dam or a bank holds it. Only placements that the game shows are taken, by
    the blend mode of their material (a lake's own material is a dynamic instance of the lake master, named after its weather
    layer level, which is not a hint of anything). The ``waterplane*`` meshes are in the server's planes or along the landscape
    splines, and the ocean plane is left out: the sea level of the weather layers is the sea.
    """
    materials = json.load(open(os.path.join(scene_dir, "materials.json")))
    planes, bounds = [], {}
    for item, path, info in read_instances(scene_dir):
        name = path.rsplit("/", 1)[-1]
        if item["type"] == FOLIAGE_TYPE or item["spline"] is not None or not is_water_mesh(path) or re.search("ocean", name, re.IGNORECASE):
            continue
        if not visible_ranges(info, tuple(item.get("overrides") or ()), materials, water_shown=True) or WATER_PATH.search(name):
            continue
        if info["id"] not in bounds:
            vertices, _ = read_mesh(scene_dir, info)
            bounds[info["id"]] = (vertices[:, :3].min(0), vertices[:, :3].max(0)) if len(vertices) else None
        if bounds[info["id"]] is None:
            continue
        lo, hi = bounds[info["id"]]
        corners = np.array([[x, y, hi[2], 1.0] for x, y in ((lo[0], lo[1]), (hi[0], lo[1]), (hi[0], hi[1]), (lo[0], hi[1]))])
        for matrix in component_matrices(item):
            world = (corners @ matrix)[:, :3] / 100
            planes.append({"polygon": np.round(world[:, :2], 2).tolist(), "z": round(float(world[:, 2].max()) - z_min, 3)})
    return planes


def service_boxes(scene_dir):
    """World boxes [n, 4] (x0, y0, x1, y1 in m) of the plain static meshes that the game does not show: hidden components, those in skipped
    levels and those whose shown sections are all hidden materials (developer volumes, glass). Foliage and spline meshes are not counted.
    Boxes that are both wide and long (zone volumes over a district or the whole map) are left out: they say nothing about what lies in them."""
    materials = json.load(open(os.path.join(scene_dir, "materials.json")))
    boxes, bounds = [], {}
    for item, path, info in read_instances(scene_dir, shown_only=False):
        if item["type"] == FOLIAGE_TYPE or item["spline"] is not None:
            continue
        if is_shown(item) and visible_ranges(info, tuple(item.get("overrides") or ()), materials):
            continue
        if info["id"] not in bounds:
            vertices, _ = read_mesh(scene_dir, info)
            bounds[info["id"]] = (vertices[:, :3].min(0), vertices[:, :3].max(0)) if len(vertices) else None
        if bounds[info["id"]] is not None:
            matrices = component_matrices(item)
            if len(matrices):
                boxes.append(world_boxes(*bounds[info["id"]], matrices))
    if not boxes:
        return np.zeros((0, 4))
    boxes = np.concatenate(boxes)
    width, length = boxes[:, 2] - boxes[:, 0], boxes[:, 3] - boxes[:, 1]
    return boxes[(np.minimum(width, length) <= SERVICE_THIN_M) | (width * length <= SERVICE_SMALL_M2)]


def ground_on_grid(ground, z_min, rows_m, cols_m):
    """Absolute ground height (m) [len(rows_m), len(cols_m)] at the grid of points rows_m metres south and cols_m metres east of
    the minimum corner: bilinear on the 1 m grid, the edge values beyond it, in the ground's own precision (as
    scipy.ndimage.map_coordinates order 1, mode "nearest" gives it). One axis after the other: the rows by indexing, the columns
    as a product with their [window, points] weight matrix, which is faster than gathering every point."""
    def axis(coordinates, size):
        clamped = np.clip(coordinates, 0, size - 1)
        low = np.minimum(np.floor(clamped).astype(np.int64), max(size - 2, 0))
        return low, np.minimum(low + 1, size - 1), clamped - low
    r_low, r_high, r_share = axis(rows_m, ground.shape[0])
    c_low, c_high, c_share = axis(cols_m, ground.shape[1])
    lo, hi = int(c_low.min()), int(c_high.max()) + 1
    window = np.asarray(ground[:, lo:hi], np.float64)
    along_rows = window[r_low] * (1 - r_share)[:, None] + window[r_high] * r_share[:, None]
    weights = np.zeros((hi - lo, len(cols_m)))
    points = np.arange(len(cols_m))
    np.add.at(weights, (c_low - lo, points), 1 - c_share)
    np.add.at(weights, (c_high - lo, points), c_share)
    return (along_rows @ weights).astype(ground.dtype) + z_min


def remove_thin(height_cm, cls, cover):
    """Drop the parts of objects narrower than THIN_WIDTH_M (wires, cables, antennas) in place; walls and bridges are kept at any width.

    A cell stays when a disc of THIN_WIDTH_M fits over it in the footprint of cells that are at least half covered, or when it
    is next to such a place (the anti-aliased rim): a pole 0.35 m across stays, a cable does not.
    """
    radius = round(THIN_WIDTH_M / CELL_M) // 2
    y, x = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    solid = ndimage.binary_opening(cover >= 128, structure=(x * x + y * y) <= radius * radius + 0.5)
    solid |= (cover > 0) & np.isin(cls, (features.WALL, features.BRIDGE))
    drop = (cover > 0) & ~ndimage.binary_dilation(solid, iterations=1)
    height_cm[drop] = 0
    cls[drop] = 0
    cover[drop] = 0


def raster_block(scene, ground, z_min, bounds, r0, r1, c0, c1, sampler=None):
    """Height (cm, uint16), class (uint8) and coverage (0..255, uint8) of cells [r0, r1) x [c0, c1) of the CELL_M grid.

    Height is above the bare ground, 0 below OBJECT_MIN_CM. Class is the object class of the highest surface of the cell.
    Objects thinner than THIN_WIDTH_M are removed (remove_thin); the block is rasterized with THIN_MARGIN cells around it so
    that the result of a cell does not depend on where the blocks are cut. ``sampler`` finds the highest surface at the sample
    points: sample_tops (the default, CPU) or scene_raster_gpu.GpuSampler, which give the same answer.
    """
    return block_cells(block_samples(scene, bounds, r0, r1, c0, c1, sampler or sample_tops), ground, z_min, bounds, r0, r1, c0, c1)


def block_samples(scene, bounds, r0, r1, c0, c1, sampler):
    """The first half of raster_block: (top, class) of ``sampler`` at the sample points of the block and its THIN_MARGIN, or None
    where no placement reaches it."""
    step = CELL_M / SUBSAMPLES
    rows, cols = (r1 - r0 + 2 * THIN_MARGIN) * SUBSAMPLES, (c1 - c0 + 2 * THIN_MARGIN) * SUBSAMPLES
    x0 = bounds["min_x"] + (c0 - THIN_MARGIN) * CELL_M + step / 2
    y0 = bounds["min_y"] + (r0 - THIN_MARGIN) * CELL_M + step / 2
    hits = hit_groups(scene, x0, y0, x0 + (cols - 1) * step, y0 + (rows - 1) * step)
    return sampler(scene, hits, x0, y0, step, rows, cols) if hits else None


def block_cells(samples, ground, z_min, bounds, r0, r1, c0, c1):
    """The second half of raster_block: its result from block_samples' (top, class) or None. Needs no scene, so it can run in another
    process than the sampling (scene_raster_gpu.py)."""
    rows, cols = r1 - r0, c1 - c0
    if samples is None:
        return np.zeros((rows, cols), np.uint16), np.zeros((rows, cols), np.uint8), np.zeros((rows, cols), np.uint8)
    height_cm, cell_class, cover = _cells(*samples, ground, z_min, bounds, r0 - THIN_MARGIN, c0 - THIN_MARGIN)
    remove_thin(height_cm, cell_class, cover)
    inner = (slice(THIN_MARGIN, -THIN_MARGIN), slice(THIN_MARGIN, -THIN_MARGIN))
    return height_cm[inner], cell_class[inner], cover[inner]


def hit_groups(scene, x0, y0, x1, y1):
    """[(group, bool [n] of its placements whose box overlaps [x0, x1] x [y0, y1] metres)] of the groups with any such placement."""
    boxes = scene.boxes
    hit = (boxes[:, 0] <= x1) & (boxes[:, 2] >= x0) & (boxes[:, 1] <= y1) & (boxes[:, 3] >= y0)
    starts = scene.box_starts
    return [(scene.groups[k], hit[starts[k]:starts[k + 1]]) for k in np.unique(scene.box_owner[hit])]


def sample_tops(scene, hits, x0, y0, step, rows, cols):
    """(top [rows, cols] float64, absolute metres, -inf where no surface; class [rows, cols] int, the object class of that surface)
    of the hit placements at the points (x0 + i * step, y0 + j * step), on the CPU (tools/heightmaps/py/objects.py rasterize).

    A point inside a triangle (edges included) takes the triangle's height there; of equal heights the lowest class index wins.
    """
    tops = np.full((len(features.OBJECT_CLASSES), rows, cols), -np.inf, np.float64)
    for group, hit in hits:
        corners = scene.triangles(group)
        if not len(corners):
            continue
        for m in group["matrices"][hit]:
            world = ((corners @ m[:3, :3]) + m[3, :3]).reshape(-1, 3, 3) / 100
            objects.rasterize(world, tops[group["cls"]], x0, y0, step)
    return tops.max(0), tops.argmax(0)


def _cells(top, top_class, ground, z_min, bounds, r0, c0):
    """Height (cm), class and coverage of the cells of a sample window whose first cell is (r0, c0), before remove_thin."""
    step = CELL_M / SUBSAMPLES
    rows, cols = top.shape[0] // SUBSAMPLES, top.shape[1] // SUBSAMPLES
    rows_m = np.arange(top.shape[0]) * step + (r0 * CELL_M + step / 2)
    cols_m = np.arange(top.shape[1]) * step + (c0 * CELL_M + step / 2)
    height = np.where(np.isfinite(top), top - ground_on_grid(ground, z_min, rows_m, cols_m), 0.0)
    shape4 = (rows, SUBSAMPLES, cols, SUBSAMPLES)
    quad = lambda a: a.reshape(shape4).transpose(0, 2, 1, 3).reshape(rows, cols, SUBSAMPLES * SUBSAMPLES)
    heights = quad(height)
    pick = heights.argmax(2)[..., None]
    cell_height = np.take_along_axis(heights, pick, 2)[..., 0]
    cell_class = np.take_along_axis(quad(top_class), pick, 2)[..., 0]
    cover = np.rint((heights >= COVERAGE_MIN_M).mean(2) * 255).astype(np.uint8)
    height_cm = np.rint(cell_height * 100)
    height_cm = np.clip(np.where(height_cm >= OBJECT_MIN_CM, height_cm, 0), 0, 65535).astype(np.uint16)
    return height_cm, np.where(height_cm > 0, cell_class, 0).astype(np.uint8), cover
