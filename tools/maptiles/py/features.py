"""Map features from the Squad game files, in world metres, for the detailed map tiles.

Inputs are written by SquadExtract (tools/heightmaps/extractor):
    ``features`` mode: foliage.ndjson, splines.ndjson, water.ndjson of one map;
    ``statics`` mode: instances.ndjson and bodies/ of the map's static meshes (water planes);
    ``extractall`` mode: the cooked landscape collision, whose heightfields also hold the dominant
    physical material of every landscape quad.

World coordinates are UE's (X east, Y south, Z up) converted from centimetres to metres.
Transforms use the row-vector convention of tools/heightmaps/py/objects.py: p_world = p_local @ M.
"""

import glob
import json
import math
import os
import re
import struct

import numpy as np

import landscape
import objects

# Physical materials of the landscape layers (every one found in build 26005357), in a fixed order: the
# cover raster stores the index into this list, NO_COVER where no landscape covers a point or the quad is a hole
PHYSICAL_MATERIALS = [
    "PhysMat_Grass", "PhysMat_GrassTall", "PhysMat_GrassTall_Rustle", "PhysMat_Dirt", "PhysMat_DirtGravel",
    "PhysMat_Gravel", "PhysMat_Mud_deep", "PhysMat_Rock", "PhysMat_Loose_Rocks", "PhysMat_Sand",
    "PhysMat_Leafs", "PhysMat_LeafsNoRustle", "PhysMat_Asphalt", "PhysMat_Snow", "PhysMat_SnowWet",
    "PhysMat_Default",
]
NO_COVER = 255
HOLE_INDEX = 255

# Foliage classes, by mesh name; FOLIAGE_SKIP is ground clutter too small for a map symbol
CONIFER, DECIDUOUS, BUSH, ROCK = 0, 1, 2, 3
FOLIAGE_CLASSES = ["conifer", "deciduous", "bush", "rock"]
FOLIAGE_SKIP = -1
_FOLIAGE_RULES = [
    (FOLIAGE_SKIP, r"grass|flower|fern|clutter|weed|foxglove|daisy|nettle|moss_|leaves|leaf_|debris|pebble|snowpole|decal"
                   r"|haybale|log|trash|cardboard|cloth|breezeblock|brick|tire|tyre|barrel|crate|bottle|garbage|litter|paper"),
    (ROCK, r"rock|stone|boulder|cliff"),
    (BUSH, r"shrub|bush|hedge|reed|sapling|scrub|juniper|thorn|bramble|cactus|plant"),
    (CONIFER, r"pine|spruce|(^|_)fir|conifer|cedar|larch|cypress|taiga|evergreen"),
    (DECIDUOUS, r"tree|birch|oak|maple|beech|poplar|willow|palm|aspen|alder|(^|_)elm|(^|_)ash|linden|acacia|olive"
                r"|chestnut|walnut|cherry|apple|mulberry|eucalyptus|banana|bamboo|deciduous"),
]
# Foliage whose mesh name matches no rule: a tree from this height (m), a bush from BUSH_MIN_M
TREE_MIN_M = 3.0
BUSH_MIN_M = 0.8
ROCK_MIN_RADIUS_M = 0.5

# Landscape spline classes, by the names of the meshes laid along the segment
SPLINE_CLASSES = ["asphalt", "dirt", "pavement", "rail", "river", "hedge", "wall", "trench"]
_SPLINE_RULES = [
    ("river", r"river|stream|water"),
    ("trench", r"trench"),
    ("hedge", r"hedge"),
    ("wall", r"wall|fence|barrier|guard|hesco|sandbag|berm|railing"),
    ("rail", r"railroad|railway|rail_?track|tracks_x|train"),
    ("pavement", r"pavement|paveing|paving|sidewalk|curb|kerb"),
    ("dirt", r"dirt|track|gravel|trail|path|mud"),
    ("asphalt", r"road|vei|asphalt|highway|lane|street|motorway|tarmac|bridge"),
]

# Static mesh classes for the object raster (see prep.py), by mesh path
STRUCTURE, WALL, ROCK_OBJECT, VEGETATION = 0, 1, 2, 3
OBJECT_CLASSES = ["structure", "wall", "rock", "vegetation"]
_OBJECT_RULES = [
    (VEGETATION, r"hedge|tree|bush|shrub|foliage|reed|plant|palm"),
    (WALL, r"wall|fence|barrier|hesco|sandbag|railing|guardrail|barricade|gate"),
    (ROCK_OBJECT, r"rock|cliff|boulder|stone|mountain|landscape_mesh|terrain"),
]

# Static water surfaces, by mesh path; the exclusions are props named after water
_WATER_MESH = r"waterplane|oceanplane|oceanwater|sm_env_river|lake|pond"
_WATER_MESH_EXCLUDE = r"tank|tower|pump|melon|container|rcon|bottle|well"


def _classify(name, rules, default):
    lower = name.lower()
    for value, pattern in rules:
        if re.search(pattern, lower):
            return value
    return default


def object_class(mesh_path):
    """Object raster class (STRUCTURE, WALL, ROCK_OBJECT, VEGETATION) of a static mesh, by its path."""
    return _classify(mesh_path, _OBJECT_RULES, STRUCTURE)


def ellipse_polygon(cx, cy, half_x, half_y, yaw_deg, points=16):
    """Vertices [(x, y)] of an ellipse with half axes half_x, half_y turned by yaw (degrees, X towards Y)."""
    t = np.linspace(0, 2 * math.pi, points, endpoint=False)
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    ex, ey = half_x * np.cos(t), half_y * np.sin(t)
    return list(zip((cx + c * ex - s * ey).tolist(), (cy + s * ex + c * ey).tolist()))


def spline_class(mesh_paths):
    """Class name from SPLINE_CLASSES of a landscape spline segment, or None when no rule matches."""
    names = " ".join(os.path.basename(p).split(".")[0] for p in mesh_paths)
    return _classify(names, _SPLINE_RULES, None) if names else None


def _transform_points(points_cm, matrix):
    """World metres [n, 3] of component-space points [n, 3] in cm."""
    p = np.asarray(points_cm, dtype=np.float64).reshape(-1, 3)
    return (np.concatenate([p, np.ones((len(p), 1))], axis=1) @ matrix)[:, :3] / 100


def foliage(directory):
    """Foliage instances of a map as arrays (world metres) and a per-mesh classification report.

    Returns ({x, y, z, radius, half_x, half_y, yaw, height, cls, collision}, {mesh name: (class name,
    count)}). The crown radius is the horizontal reach of the mesh's render bounds from its pivot,
    scaled; half_x and half_y are the bounds' half extents along the instance's own axes, turned by
    yaw (degrees, world); the height is the top of the render bounds above the pivot. Ground clutter
    (FOLIAGE_SKIP) is left out.
    """
    columns = {k: [] for k in ("x", "y", "z", "radius", "half_x", "half_y", "yaw", "height", "cls", "collision")}
    report = {}
    for line in open(os.path.join(directory, "foliage.ndjson")):
        item = json.loads(line)
        rows = np.asarray(item["instances"], dtype=np.float64).reshape(-1, 5)
        bounds = (item.get("info") or {}).get("bounds")
        name = os.path.basename(item["mesh"]).split(".")[0]
        if not len(rows) or not bounds:
            continue
        o, e = bounds["Origin"], bounds["BoxExtent"]
        reach_cm = max(abs(o["X"]) + e["X"], abs(o["Y"]) + e["Y"])
        top_cm = o["Z"] + e["Z"]
        matrix = objects.component_world(item["chain"])
        component_scale = float(np.linalg.norm(matrix[0, :3]))
        scale = rows[:, 4] * component_scale
        radius = reach_cm * scale / 100
        height = top_cm * scale / 100
        cls = _classify(name, _FOLIAGE_RULES, None)
        if cls is None:
            typical = float(np.median(height))
            cls = DECIDUOUS if typical >= TREE_MIN_M else BUSH if typical >= BUSH_MIN_M else FOLIAGE_SKIP
        if cls == ROCK:
            keep = radius >= ROCK_MIN_RADIUS_M
            rows, radius, height, scale = rows[keep], radius[keep], height[keep], scale[keep]
        label = FOLIAGE_CLASSES[cls] if cls >= 0 else "skip"
        previous = report.get(name, (label, 0))[1]
        report[name] = (label, previous + len(rows))
        if cls == FOLIAGE_SKIP or not len(rows):
            continue
        world = _transform_points(rows[:, :3], matrix)
        columns["x"].append(world[:, 0])
        columns["y"].append(world[:, 1])
        columns["z"].append(world[:, 2])
        columns["radius"].append(radius)
        columns["half_x"].append(e["X"] * scale / 100)
        columns["half_y"].append(e["Y"] * scale / 100)
        columns["yaw"].append(rows[:, 3] + math.degrees(math.atan2(matrix[0, 1], matrix[0, 0])))
        columns["height"].append(height)
        columns["cls"].append(np.full(len(rows), cls, np.uint8))
        columns["collision"].append(np.full(len(rows), bool((item.get("info") or {}).get("collision")) and objects.blocks(item.get("collision"))))
    arrays = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in columns.items()}
    arrays["cls"] = arrays["cls"].astype(np.uint8)
    arrays["collision"] = arrays["collision"].astype(bool)
    for k in ("x", "y", "z", "radius", "half_x", "half_y", "yaw", "height"):
        arrays[k] = arrays[k].astype(np.float32)
    return arrays, report


def splines(directory):
    """Landscape spline segments as {cls, left, right, center} in world metres, and a class report.

    ``left`` and ``right`` are the segment's edges (the width the meshes are laid with), ``center``
    the centre line with its height. Segments whose meshes match no rule are reported and left out.
    """
    segments = []
    report = {}
    for line in open(os.path.join(directory, "splines.ndjson")):
        item = json.loads(line)
        if not item.get("chain") or len(item["center"]) < 2:
            continue
        cls = spline_class(item["meshes"])
        key = ",".join(sorted({os.path.basename(p).split(".")[0] for p in item["meshes"]})) or "<no mesh>"
        previous = report.get(key, (cls, 0))[1]
        report[key] = (cls, previous + 1)
        if cls is None:
            continue
        matrix = objects.component_world(item["chain"])
        segments.append({
            "cls": cls,
            "left": np.round(_transform_points(item["left"], matrix)[:, :2], 2).tolist(),
            "right": np.round(_transform_points(item["right"], matrix)[:, :2], 2).tolist(),
            "center": np.round(_transform_points(item["center"], matrix), 2).tolist(),
        })
    return segments, report


def sea_level(directory):
    """World Z (m) of the map's ocean (median over ocean actors of every weather layer), or None."""
    levels = []
    for line in open(os.path.join(directory, "water.ndjson")):
        item = json.loads(line)
        if "ocean" in item["actor"].lower() and item["chain"]:
            levels.append(objects.component_world(item["chain"][-1:])[3, 2] / 100)
    return float(np.median(levels)) if levels else None


def water_planes(statics_dir):
    """Static water surfaces (lakes, ponds, river planes) as {polygon [[x, y] * 4], z} in world metres."""
    planes = []
    for line in open(os.path.join(statics_dir, "instances.ndjson")):
        item = json.loads(line)
        info_path = os.path.join(statics_dir, "bodies", f"{item['mesh']}.json")
        if not os.path.exists(info_path):
            continue
        info = json.load(open(info_path))
        path = (info.get("path") or "").lower()
        if not re.search(_WATER_MESH, path) or re.search(_WATER_MESH_EXCLUDE, path) or not info.get("bounds"):
            continue
        o, e = info["bounds"]["Origin"], info["bounds"]["BoxExtent"]
        corners = np.array([[o["X"] + sx * e["X"], o["Y"] + sy * e["Y"], o["Z"] + e["Z"]]
                            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        world = objects.component_world(item["chain"])
        mats = [objects.affine(objects.quat_matrix(i["q"]), i["t"], i["s"]) @ world for i in item["instances"]] \
            if item.get("instances") is not None else [world]
        for m in mats:
            p = _transform_points(corners, m)
            planes.append({"polygon": np.round(p[:, :2], 2).tolist(), "z": round(float(p[:, 2].max()), 3)})
    return planes


def read_materials(path):
    """Dominant physical material index of every quad [rows - 1, cols - 1] of a cooked Chaos heightfield.

    After the heights (see landscape.read_heightfield) and the scale, bounds, size, range and
    height-per-unit fields come int32 n = (rows - 1) * (cols - 1) and n uint8 indices into the
    component's CookedPhysicalMaterials (HOLE_INDEX for a landscape hole). Verified on build 26005357.
    """
    data = open(path, "rb").read()
    count = struct.unpack_from("<i", data, landscape.HEIGHTS_OFFSET)[0]
    tail = landscape.HEIGHTS_OFFSET + 4 + 2 * count
    rows, cols = struct.unpack_from("<HH", data, tail + 28)
    start = tail + 48
    n = struct.unpack_from("<i", data, start)[0]
    if n != (rows - 1) * (cols - 1):
        raise ValueError(f"{path}: {n} material indices for {rows}x{cols}")
    return np.frombuffer(data, np.uint8, n, start + 4).reshape(rows - 1, cols - 1)


def _material_grids(level_dirs):
    """Per landscape actor: (material index grid [quads y, quads x], origin quad x, origin quad y, root)."""
    grids = []
    for level in level_dirs:
        roots = landscape.load_roots(level)
        parts = {}
        for path in glob.glob(os.path.join(level, "*.json")):
            if os.path.basename(path).startswith("root_"):
                continue
            export = json.load(open(path))
            props = export["Properties"]
            actor = export["Outer"]["ObjectName"].split(".")[-1].rstrip("'")
            names = [m["ObjectName"].split("'")[1] for m in props.get("CookedPhysicalMaterials", [])]
            lookup = np.full(256, NO_COVER, np.uint8)
            for i, name in enumerate(names):
                lookup[i] = PHYSICAL_MATERIALS.index(name if name in PHYSICAL_MATERIALS else "PhysMat_Default")
            materials = lookup[read_materials(path[:-5] + ".bin")]
            location = props.get("RelativeLocation", {})
            parts.setdefault(actor, []).append((int(round(location.get("X", 0))), int(round(location.get("Y", 0))), materials))
        for actor, items in parts.items():
            x0 = min(x for x, _, _ in items)
            y0 = min(y for _, y, _ in items)
            x1 = max(x + m.shape[1] for x, _, m in items)
            y1 = max(y + m.shape[0] for _, y, m in items)
            grid = np.full((y1 - y0, x1 - x0), NO_COVER, np.uint8)
            for x, y, m in items:
                grid[y - y0:y - y0 + m.shape[0], x - x0:x - x0 + m.shape[1]] = m
            grids.append((grid, x0, y0, roots[actor]))
    return grids


def cover(level_dirs, bounds, shape, strip=256):
    """Physical material index (into PHYSICAL_MATERIALS) at every point of the 1 m grid, NO_COVER outside.

    Each landscape quad holds the material that dominates it in the game; a grid point takes the
    quad it lies in, through the landscape actor's transform (the inverse of landscape.sample_world).
    The first landscape level covering a point wins, like build_heightmap.game_terrain. Rows are
    processed in strips of ``strip`` to bound memory on the largest maps.
    """
    grids = _material_grids(level_dirs)
    result = np.full(shape, NO_COVER, np.uint8)
    xs = (bounds["min_x"] + np.arange(shape[1])) * 100
    for top in range(0, shape[0], strip):
        ys = (bounds["min_y"] + np.arange(top, min(top + strip, shape[0]))) * 100
        gx_world, gy_world = np.meshgrid(xs, ys)
        out = result[top:top + len(ys)]
        for grid, x0, y0, (loc, yaw, scale) in grids:
            c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
            dx, dy = gx_world - loc[0], gy_world - loc[1]
            col = np.floor((c * dx + s * dy) / scale[0] - x0).astype(np.int64)
            row = np.floor((-s * dx + c * dy) / scale[1] - y0).astype(np.int64)
            inside = (col >= 0) & (col < grid.shape[1]) & (row >= 0) & (row < grid.shape[0]) & (out == NO_COVER)
            out[inside] = grid[row[inside], col[inside]]
    return result
