"""Orthographic top-down render of a Squad map from the assets of the game client (GPU, headless OpenGL).

The scene comes from `SquadExtract scene` (instances.ndjson, meshes.json, materials.json, textures.json) and
`SquadExtract lsweights` (landscape layer weights). World axes are those of the game: X east, Y south, Z up, centimetres, so a
top-down view has X to the right and Y downwards, the same as the map image.

Scene.render(x0, y0, x1, y1, width, height) returns an RGB array of a world box in metres. Everything is drawn again per block:
one depth pass from the sun (shadow map), one colour pass, supersampled and averaged down.
"""
import json
import math
import os
import re
from pathlib import Path

import moderngl
import numpy as np
from PIL import Image
from scipy import ndimage

# "_Vista": the scenery beyond the map, whose mountains would lie over the edge of the landscape
SKIPPED_LEVEL_PARTS = ("/Coop/", "/Tutorials/", "/Sound_Layers/", "Profiling", "Navmesh", "_Vista", "_Editor_Only")
SKIPPED_BLENDS = ("BLEND_Additive", "BLEND_Modulate")
# Level designers' volumes and the engine's default materials: zone boxes in translucent colours and walls around the map, up to 3 km long.
# The rest of the Blockout folder is real art: vehicles, containers and bridges use it.
DEVELOPER_MATERIAL = re.compile(r"/Engine/BasicShapes/|/Engine/EngineMaterials/WorldGridMaterial|/GameModes/TC/HexGrid/|/Blockout/MI_\w*Transparent|/Tools/POI_Reference_Marker/|/Gameplay/GameplayBorder/")
TEXTURE_LIMIT = 512
CROWN_MINIMUM_CM = 100.0
DOME_SHARE = 0.9
DOME_TILE_CM = 400.0
# Contact shadow: darkening of a surface by what stands around it, radius and full-strength height difference in metres
CONTACT_RADIUS_M, CONTACT_HEIGHT_M, CONTACT_STRENGTH = 1.2, 2.5, 0.5
# Heights (cm) that the orthographic passes always cover; Scene.depth_range widens them to the scene, as Chora lies 770 m below sea level
DEFAULT_DEPTH_CM = (-50000.0, 100000.0)
DEPTH_MARGIN_CM = 5000.0
# Base colour parameter of a material, best first. PM_Diffuse is CUE4Parse's guess and can be a mask, so it comes last.
DIFFUSE_NAMES = ("Base_Diffuse", "Albedo", "* Albedo", "Base_Color", "Diffuse", "mat01_difuse", "Road_texture_01_A", "Basedetaildifuse", "Paint_texture", "PM_Diffuse")
# When none of those is there: what a parameter or a texture holding a colour is called, spelling mistakes of the assets included
COLOUR_PARAMETER = re.compile(r"alb[ei]do|dif+use|base.?colou?r|colou?r.?map|(^|_)dif$|(^|_)a$|(^|_)bc$", re.IGNORECASE)
COLOUR_TEXTURE = re.compile(r"(_|^)(a|bc|d|c|col|color|colour|albedo|diffuse|difuse)(_\w{0,3})?$", re.IGNORECASE)
NOT_COLOUR = re.compile(r"normal|rough|mask|spec|gloss|metal|height|ao$|orm$|ors$|_n$|_r$|_m$|opacity|emissive", re.IGNORECASE)
# Foliage whose shading the cooked material does not state, and field crops, whose stems are drawn as they are and never as crowns
LEAF_NAME = re.compile(r"leaf|leaves|needle|frond|tamarix|bush|shrub|scrub|populus|poplar|olive|salix|pine|birch|oak|spruce|almond", re.IGNORECASE)
NOT_LEAF_NAME = re.compile(r"trunk|bark|rock|stone|cliff|boulder|log|stump|wood", re.IGNORECASE)
# Foliage drawn as its mesh, not as a solid crown: palms have fronds, crops and flowers stems, and branches under snow show the ground between them
KEEPS_ITS_SHAPE = re.compile(r"palm|snow|corn|maize|wheat|crop|rice|grass|flower|poppies|poppy|reed|cattail|potato|cannabis|fern", re.IGNORECASE)
MAX_LAYERS = 16
# Pseudo-layer of the cells no landscape component paints: the frame reaching past the landscape (Sanxian), or a component whose
# weights are all zero there. It takes its colour from the whole-map texture like a layer, and the capture itself through the tone field
UNCOVERED_LAYER = "Uncovered"

VERTEX = """
#version 430
layout(std430, binding = 0) buffer Instances { vec4 rows[]; };
uniform int first;
uniform vec4 box;      // x0, y0, x1, y1 in cm
uniform vec2 depth;    // z min, z max in cm
uniform mat3 view;     // world -> light space, identity for the top-down pass
uniform float crown_top;   // height of a tree mesh in its own space; 0 for everything else
in vec3 position; in vec3 normal; in vec2 uv;
out vec3 world_position; out vec3 world_normal; out vec2 tex; out float crown_light;
void main() {
    int i = (gl_InstanceID + first) * 3;
    vec4 p = vec4(position, 1.0);
    world_position = vec3(dot(rows[i], p), dot(rows[i + 1], p), dot(rows[i + 2], p));
    // A crown is lit as one rounded volume, brightest at its top, instead of as loose leaf cards
    vec3 n = crown_top > 0.0 ? normalize(position - vec3(0.0, 0.0, 0.55 * crown_top)) : normal;
    world_normal = vec3(dot(rows[i].xyz, n), dot(rows[i + 1].xyz, n), dot(rows[i + 2].xyz, n));
    crown_light = crown_top > 0.0 ? mix(0.65, 1.0, smoothstep(0.25, 1.0, position.z / crown_top)) : 1.0;
    tex = uv;
    vec3 v = view * world_position;
    gl_Position = vec4((v.x - box.x) / (box.z - box.x) * 2.0 - 1.0, (v.y - box.y) / (box.w - box.y) * 2.0 - 1.0,
                       1.0 - (v.z - depth.x) / (depth.y - depth.x) * 2.0, 1.0);
}
"""

FRAGMENT = """
#version 430
// Coarsest useful mip of a leaf texture: its average colour without the layout of the atlas
const float DOME_LEVEL = 8.0;
uniform sampler2D diffuse;
uniform sampler2D road_mask;
uniform int road_mode;      // 0: none, 1: road surface mask (R streaks, G opacity), 2: soft edges across U (dirt roads blended into the ground)
uniform sampler2DShadow shadow_map;
uniform vec3 tint;
uniform vec3 gain;
uniform float clip;
uniform float dome;         // 1 for the solid body of a crown
uniform vec3 sun;
uniform float ambient, sun_strength, bias;
uniform mat3 light_view;
uniform vec4 light_box;
uniform vec2 light_depth;
in vec3 world_position; in vec3 world_normal; in vec2 tex; in float crown_light;
out vec4 colour;
vec3 to_linear(vec3 c) { return pow(c, vec3(2.2)); }
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float value_noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x), f.y);
}
void main() {
    // The body of a crown: the average leaf colour with clumps of light and dark, fixed in the world so blocks agree at their edges
    vec4 t = dome > 0.5 ? textureLod(diffuse, tex, DOME_LEVEL) : texture(diffuse, tex);
    if (dome > 0.5) {
        float clumps = 0.55 * value_noise(world_position.xy / 110.0) + 0.3 * value_noise(world_position.xy / 47.0) + 0.15 * value_noise(world_position.xy / 19.0);
        t.rgb *= 0.72 + 0.56 * clumps;
    }
    // Coverage from the full-size mask: a mip level averages leaves with gaps and the alpha test would thin crowns at coarse zooms
    if (textureLod(diffuse, tex, 0.0).a < clip) discard;
    vec3 n = normalize(world_normal);
    if (n.z < 0.0) n = -n;
    vec3 v = light_view * world_position;
    vec3 s = vec3((v.x - light_box.x) / (light_box.z - light_box.x), (v.y - light_box.y) / (light_box.w - light_box.y),
                  (1.0 - (v.z - light_depth.x) / (light_depth.y - light_depth.x) * 2.0) * 0.5 + 0.5 - bias);
    float lit = 0.0;
    for (int dx = -1; dx <= 1; dx++) for (int dy = -1; dy <= 1; dy++)
        lit += textureOffset(shadow_map, s, ivec2(dx, dy));
    lit /= 9.0;
    vec3 linear = to_linear(t.rgb) * tint * gain * crown_light * (ambient + sun_strength * max(dot(n, sun), 0.0) * lit);
    float alpha = 1.0;
    if (road_mode == 1) {
        vec4 m = texture(road_mask, tex);
        linear *= pow(mix(0.72, 1.14, m.r), 2.2);
        alpha = m.g;
    } else if (road_mode == 2) {
        alpha = smoothstep(0.0, 0.2, tex.x) * smoothstep(1.0, 0.8, tex.x);
    }
    colour = vec4(pow(clamp(linear, 0.0, 1.0), vec3(1.0 / 2.2)), alpha);
}
"""

ID_FRAGMENT = """
#version 430
uniform sampler2D diffuse;
uniform float clip;
uniform vec3 material_id;
in vec2 tex;
out vec4 colour;
void main() { if (clip > 0.0 && textureLod(diffuse, tex, 0.0).a < clip) discard; colour = vec4(material_id, 1.0); }
"""

GROUND_ID_FRAGMENT = """
#version 430
out vec4 colour;
void main() { colour = vec4(0.0, 0.0, 0.0, 1.0); }
"""

GROUND_VERTEX = """
#version 430
uniform vec4 box;
uniform vec2 depth;
uniform vec4 frame;    // min x, min y, size x, size y of the weight rasters, in cm
in vec3 position; in vec3 normal;
out vec3 world_position; out vec3 world_normal; out vec2 weight_uv;
void main() {
    world_position = position;
    world_normal = normal;
    weight_uv = (position.xy - frame.xy) / frame.zw;
    gl_Position = vec4((position.x - box.x) / (box.z - box.x) * 2.0 - 1.0, (position.y - box.y) / (box.w - box.y) * 2.0 - 1.0,
                       1.0 - (position.z - depth.x) / (depth.y - depth.x) * 2.0, 1.0);
}
"""

GROUND_FRAGMENT = """
#version 430
uniform sampler2DArray weights;
uniform sampler2DArray details;
uniform sampler2DShadow shadow_map;
uniform vec3 colours[16];
uniform vec2 tiles[16];     // near and far tile of each layer, in cm
uniform int layers;
uniform float detail_strength, shade_strength, shadow_strength, bias;
uniform vec3 sun;
uniform mat3 light_view;
uniform vec4 light_box;
uniform vec2 light_depth;
in vec3 world_position; in vec3 world_normal; in vec2 weight_uv;
out vec4 colour;
const mat2 rotated_a = mat2(0.8387, 0.5446, -0.5446, 0.8387);
const mat2 rotated_b = mat2(0.3090, -0.9511, 0.9511, 0.3090);
void main() {
    vec3 c = vec3(0.0);
    float total = 0.0;
    for (int i = 0; i < layers; i++) {
        float w = texture(weights, vec3(weight_uv, float(i))).r;
        if (w <= 0.0) continue;
        vec3 near = texture(details, vec3(world_position.xy / tiles[i].x, float(i))).rgb * 2.0;
        // Two rotated samples of different size, so the large tile does not show as a lattice on open fields
        vec3 far = texture(details, vec3(rotated_a * world_position.xy / tiles[i].y, float(i))).rgb
                 * texture(details, vec3(rotated_b * world_position.xy / (tiles[i].y * 1.618), float(i))).rgb * 4.0;
        vec3 detail = mix(vec3(1.0), near * far, detail_strength);
        c += w * colours[i] * detail;
        total += w;
    }
    c /= max(total, 1e-3);
    vec3 n = normalize(world_normal);
    float shade = 1.0 + shade_strength * (max(dot(n, sun), 0.0) - sun.z);
    vec3 v = light_view * world_position;
    vec3 s = vec3((v.x - light_box.x) / (light_box.z - light_box.x), (v.y - light_box.y) / (light_box.w - light_box.y),
                  (1.0 - (v.z - light_depth.x) / (light_depth.y - light_depth.x) * 2.0) * 0.5 + 0.5 - bias);
    float lit = 0.0;
    for (int dx = -1; dx <= 1; dx++) for (int dy = -1; dy <= 1; dy++)
        lit += textureOffset(shadow_map, s, ivec2(dx, dy));
    lit /= 9.0;
    colour = vec4(clamp(c * shade * (1.0 - shadow_strength * (1.0 - lit)), 0.0, 1.0), 1.0);
}
"""

DEPTH_FRAGMENT = """
#version 430
uniform sampler2D diffuse;
uniform float clip;
in vec2 tex;
void main() { if (clip > 0.0 && textureLod(diffuse, tex, 0.0).a < clip) discard; }
"""


def rotator_matrix(r):
    """3x3 row-vector rotation of a UE FRotator (FRotationMatrix)."""
    p, y, ro = (math.radians(r[k]) for k in ("Pitch", "Yaw", "Roll"))
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(ro), math.cos(ro)
    return np.array([
        [cp * cy, cp * sy, sp],
        [sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp],
        [-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp],
    ])


def component_world(chain):
    """4x4 row-vector world matrix from an attach chain (component first, root last)."""
    world = np.eye(4)
    for link in chain:
        m = np.eye(4)
        m[:3, :3] = rotator_matrix(link["r"]) * np.array([link["s"]["X"], link["s"]["Y"], link["s"]["Z"]])[:, None]
        m[3, :3] = [link["l"]["X"], link["l"]["Y"], link["l"]["Z"]]
        world = world @ m
    return world


def instance_matrices(items):
    """[n, 4, 4] row-vector matrices of the per-instance transforms of an instanced component."""
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


def colour_texture_path(names):
    """Path of the texture holding a material's base colour among its texture parameters {parameter: path}, None when it has none.

    The known names come first, in the order of DIFFUSE_NAMES; then any parameter called like a colour, then any texture named like one.
    A *_m texture behind a colour name is a mask (red and green channels), never a colour.
    """
    short = lambda path: path.split(".")[-1]
    usable = {key: path for key, path in names.items() if not short(path).lower().endswith("_m")}
    for key in DIFFUSE_NAMES:
        if key in usable:
            return usable[key]
    for key in sorted(usable):
        if COLOUR_PARAMETER.search(key) and not NOT_COLOUR.search(key):
            return usable[key]
    for key in sorted(usable):
        if COLOUR_TEXTURE.search(short(usable[key])) and not NOT_COLOUR.search(short(usable[key])):
            return usable[key]
    return None


def crown_dome(lo, hi, seed, rings=7, segments=28):
    """Solid crown of a tree in the mesh's own space: (vertices [n, 8], indices [m]) of a lumpy ellipsoid cap, as wide as the tree.

    The game's map was captured with distant trees, whose low-detail meshes read as round solid crowns; seen from above, the branch
    geometry of the first LOD reads as thin stars instead. Lumps of the outline depend on `seed`, and instances turn it by their yaw.
    """
    random = np.random.default_rng(seed)
    centre = (lo + hi) / 2
    radius_x, radius_y = (hi[0] - lo[0]) / 2 * DOME_SHARE, (hi[1] - lo[1]) / 2 * DOME_SHARE
    middle_z, radius_z = hi[2] * 0.6, hi[2] * 0.4
    phases = random.uniform(0, 2 * math.pi, 3)
    vertices = []
    for ring in range(rings + 1):
        polar = math.radians(100.0) * ring / rings
        for segment in range(segments):
            around = 2 * math.pi * segment / segments
            lumps = 1.0 + 0.10 * math.sin(3 * around + phases[0]) + 0.07 * math.sin(5 * around + phases[1]) + 0.05 * math.sin(9 * around + phases[2])
            x = centre[0] + radius_x * lumps * math.sin(polar) * math.cos(around)
            y = centre[1] + radius_y * lumps * math.sin(polar) * math.sin(around)
            z = middle_z + radius_z * math.cos(polar)
            vertices.append((x, y, z, 0.0, 0.0, 1.0, x / DOME_TILE_CM, y / DOME_TILE_CM))
    indices = []
    for ring in range(rings):
        for segment in range(segments):
            a, b = ring * segments + segment, ring * segments + (segment + 1) % segments
            indices += [a, b, a + segments, b, b + segments, a + segments]
    return np.array(vertices, np.float32), np.array(indices, np.uint32)


def bend_along_spline(vertices, spline, bounds):
    """Vertices of a mesh deformed along its spline (USplineMeshComponent, X forward): positions and normals in component space."""
    p = spline["p"]
    vec = lambda v: np.array([v["X"], v["Y"], v["Z"]], np.float64)
    p0, t0, p1, t1 = vec(p["StartPos"]), vec(p["StartTangent"]), vec(p["EndPos"]), vec(p["EndTangent"])
    axis = {"X": 0, "Y": 1, "Z": 2}[spline["axis"][-1]]
    side, up = [(1, 2), (2, 0), (0, 1)][axis]
    lo, hi = bounds[0][axis], bounds[1][axis]
    a = np.clip((vertices[:, axis] - lo) / max(hi - lo, 1e-3), 0, 1)[:, None]
    # Cubic Hermite position and its derivative
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
    out = vertices.copy()
    out[:, :3] = position + right * (vertices[:, side:side + 1] * scale_x + offset_x) + upward * (vertices[:, up:up + 1] * scale_y + offset_y)
    normal = vertices[:, 3:6]
    n = direction * normal[:, axis:axis + 1] + right * normal[:, side:side + 1] + upward * normal[:, up:up + 1]
    out[:, 3:6] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-6)
    return out


class Scene:
    """A map's meshes, materials and placements on the GPU."""

    def __init__(self, directory, sun_azimuth=-135.0, sun_elevation=55.0, ambient=0.55, sun_strength=0.75, hidden_foliage=()):
        """hidden_foliage: ids of foliage meshes left out (see ground_fit.invisible_foliage)."""
        self.directory = directory
        self.hidden_foliage = set(hidden_foliage)
        self.ctx = moderngl.create_standalone_context(require=430, backend="egl", libgl="libGL.so.1", libegl="libEGL.so.1")
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ambient, self.sun_strength = ambient, sun_strength
        azimuth, elevation = math.radians(sun_azimuth), math.radians(sun_elevation)
        self.sun = np.array([math.cos(elevation) * math.cos(azimuth), math.cos(elevation) * math.sin(azimuth), math.sin(elevation)])
        self.materials = json.loads(Path(os.path.join(directory, "materials.json")).read_text())
        self.textures = json.loads(Path(os.path.join(directory, "textures.json")).read_text())
        self.gl_textures = {}
        self.colour_program = self.ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
        self.depth_program = self.ctx.program(vertex_shader=VERTEX, fragment_shader=DEPTH_FRAGMENT)
        self.white = self.ctx.texture((1, 1), 4, bytes([255, 255, 255, 255]))
        self.ground_program = self.ctx.program(vertex_shader=GROUND_VERTEX, fragment_shader=GROUND_FRAGMENT)
        self.id_program = self.ctx.program(vertex_shader=VERTEX, fragment_shader=ID_FRAGMENT)
        self.ground_id_program = self.ctx.program(vertex_shader=GROUND_VERTEX, fragment_shader=GROUND_ID_FRAGMENT)
        self.ground = None
        self.material_gains = {}
        self.water_tint = (0.2, 0.22, 0.17)
        self.gain = (1.0, 1.0, 1.0)
        self._load_geometry()
        self.instance_buffer = None

    def _load_geometry(self):
        """Merge every mesh into one vertex and index buffer; bent spline meshes become meshes of their own."""
        meshes = json.loads(Path(os.path.join(self.directory, "meshes.json")).read_text())
        by_id = {m["id"]: m | {"path": path} for path, m in meshes.items()}
        raw, bounds = {}, {}

        def load_mesh(mesh_id):
            if mesh_id not in raw:
                m = by_id[mesh_id]
                data = np.fromfile(os.path.join(self.directory, "meshes", f"{mesh_id}.bin"), np.uint8)
                n = m["vertices"] * 32
                vertices = np.frombuffer(data[:n].tobytes(), np.float32).reshape(-1, 8)
                indices = np.frombuffer(data[n:].tobytes(), np.uint32)
                raw[mesh_id] = (vertices, indices)
                bounds[mesh_id] = (vertices[:, :3].min(0), vertices[:, :3].max(0))
            return raw[mesh_id]

        groups = {}       # (mesh key) -> dict(vertices, indices, sections, instances)
        overrides_of = {}
        for line in Path(self.directory, "instances.ndjson").read_text().splitlines():
            item = json.loads(line)
            if item["hidden"] or any(part in item["level"] for part in SKIPPED_LEVEL_PARTS):
                continue
            if item["type"] == "FoliageInstancedStaticMeshComponent" and item["mesh"] in self.hidden_foliage:
                continue
            m = by_id[item["mesh"]]
            if "error" in m:
                continue
            world = component_world(item["chain"])
            overrides = tuple(item.get("overrides") or ())
            if item["spline"] is not None:
                vertices, indices = load_mesh(item["mesh"])
                key = ("spline", item["level"], item["name"])
                groups[key] = {"mesh": item["mesh"], "vertices": bend_along_spline(vertices.astype(np.float64), item["spline"], bounds[item["mesh"]]).astype(np.float32),
                               "indices": indices, "matrices": [world[None]]}
            else:
                load_mesh(item["mesh"])
                key = ("mesh", item["mesh"], overrides)
                group = groups.setdefault(key, {"mesh": item["mesh"], "vertices": None, "indices": None, "matrices": [], "foliage": item["type"] == "FoliageInstancedStaticMeshComponent"})
                if item["instances"] is not None:
                    if item["instances"]:
                        group["matrices"].append(instance_matrices(item["instances"]) @ world)
                else:
                    group["matrices"].append(world[None])
            overrides_of[key] = overrides

        vertex_chunks, index_chunks, offset, first_index = [], [], 0, 0
        self.leaf_materials, self.crown_materials = set(), set()
        placed = {}
        self.draws = []
        for key, group in groups.items():
            if not group["matrices"]:
                continue
            mesh_id = group["mesh"]
            if group["vertices"] is None:
                if mesh_id in placed:
                    base_first = placed[mesh_id][1]
                else:
                    vertices, indices = raw[mesh_id]
                    vertex_chunks.append(vertices)
                    index_chunks.append(indices + offset)
                    placed[mesh_id] = (offset, first_index)
                    base_first = first_index
                    offset += len(vertices)
                    first_index += len(indices)
                lo, hi = bounds[mesh_id]
            else:
                vertices, indices = group["vertices"], group["indices"]
                vertex_chunks.append(vertices)
                index_chunks.append(indices + offset)
                base_first = first_index
                offset += len(vertices)
                first_index += len(indices)
                lo, hi = vertices[:, :3].min(0), vertices[:, :3].max(0)
            matrices = np.concatenate(group["matrices"]).astype(np.float32)
            centre = (lo + hi) / 2
            extent = np.linalg.norm(hi - lo) / 2
            world_centres = centre @ matrices[:, :3, :3] + matrices[:, 3, :3]
            radii = extent * np.linalg.norm(matrices[:, :3, :3], axis=2).max(1)
            sections = []
            slots = by_id[mesh_id]["materials"]
            overrides = overrides_of[key]
            for section in by_id[mesh_id]["sections"]:
                index = section["material"]
                material = overrides[index] if index < len(overrides) and overrides[index] else (slots[index] if index < len(slots) else "")
                sections.append((base_first + section["first"], section["triangles"] * 3, material))
            leaf_sections = [item for item in sections if self.is_leaf_material(item[2])] if group.get("foliage") else []
            foliage = bool(leaf_sections)
            foliage_material = max(leaf_sections, key=lambda item: item[1])[2] if foliage else ""
            self.leaf_materials.update(item[2] for item in leaf_sections)
            # Palm fronds are a star from above in the capture too, the geometry stays
            if foliage and hi[2] >= CROWN_MINIMUM_CM and not KEEPS_ITS_SHAPE.search(foliage_material):
                self.crown_materials.add(foliage_material)
                dome_vertices, dome_indices = crown_dome(lo, hi, mesh_id)
                vertex_chunks.append(dome_vertices)
                index_chunks.append(dome_indices + offset)
                self.draws.append({"matrices": matrices, "centres": world_centres, "radii": radii, "sections": [(first_index, len(dome_indices), foliage_material)], "crown_top": float(hi[2]), "dome": True})
                offset += len(dome_vertices)
                first_index += len(dome_indices)
            else:
                self.draws.append({"matrices": matrices, "centres": world_centres, "radii": radii, "sections": sections, "crown_top": 0.0, "dome": False})
        vertices = np.concatenate(vertex_chunks)
        indices = np.concatenate(index_chunks)
        self.vertex_buffer = self.ctx.buffer(vertices.tobytes())
        self.index_buffer = self.ctx.buffer(indices.astype(np.uint32).tobytes())
        layout = [(self.vertex_buffer, "3f 3f 2f", "position", "normal", "uv")]
        self.colour_vao = self.ctx.vertex_array(self.colour_program, layout, self.index_buffer, index_element_size=4)
        depth_layout = [(self.vertex_buffer, "3f 3x4 2f", "position", "uv")]
        self.depth_vao = self.ctx.vertex_array(self.depth_program, depth_layout, self.index_buffer, index_element_size=4)
        self.id_vao = self.ctx.vertex_array(self.id_program, depth_layout, self.index_buffer, index_element_size=4)
        self.object_z = (float(min((d["centres"][:, 2] - d["radii"]).min() for d in self.draws)),
                         float(max((d["centres"][:, 2] + d["radii"]).max() for d in self.draws)))
        self.statistics = {"draw groups": len(self.draws), "vertices": len(vertices), "instances": int(sum(len(d["matrices"]) for d in self.draws))}

    def depth_range(self):
        """(lowest, highest) height in cm of the orthographic passes: DEFAULT_DEPTH_CM, widened to every object and to the landscape, with
        a margin. Anything outside the range is clipped, so a map lying below or above the default would draw nothing."""
        low, high = self.object_z
        if self.ground is not None:
            low, high = min(low, self.ground["z_range"][0]), max(high, self.ground["z_range"][1])
        return min(DEFAULT_DEPTH_CM[0], low - DEPTH_MARGIN_CM), max(DEFAULT_DEPTH_CM[1], high + DEPTH_MARGIN_CM)

    def is_leaf_material(self, path):
        """Leaves modelled as geometry: a material without a mask, with a foliage shading or a foliage name; rocks and trunks are neither."""
        material = self.materials.get(path) or {}
        name = path.rsplit(".", 1)[-1]
        if material.get("blend") != "BLEND_Opaque" or NOT_LEAF_NAME.search(name):
            return False
        return any(word in material.get("shading", "") for word in ("Subsurface", "Foliage")) or bool(LEAF_NAME.search(name))

    def texture_of(self, path, grey=False):
        """GL texture of a texture asset, limited to TEXTURE_LIMIT px, with mipmaps; None when it has no pixels.
        `grey` averages the channels of a mask into a brightness pattern."""
        if (path, grey) in self.gl_textures:
            return self.gl_textures[(path, grey)]
        info = self.textures.get(path)
        texture = None
        if info and "file" in info and info["format"] in ("PF_R8G8B8A8", "PF_B8G8R8A8", "PF_G8"):
            data = np.fromfile(os.path.join(self.directory, "textures", info["file"] + ".bin"), np.uint8)
            if info["format"] == "PF_G8":
                grey = data.reshape(info["height"], info["width"])
                pixels = np.dstack([grey, grey, grey, np.full_like(grey, 255)])
            else:
                pixels = data.reshape(info["height"], info["width"], 4)
                if info["format"] == "PF_B8G8R8A8":
                    pixels = pixels[..., [2, 1, 0, 3]]
                if grey:
                    level = pixels[..., :3].mean(-1).astype(np.uint8)
                    pixels = np.dstack([level, level, level, pixels[..., 3]])
            if max(pixels.shape[:2]) > TEXTURE_LIMIT:
                factor = TEXTURE_LIMIT / max(pixels.shape[:2])
                pixels = np.asarray(Image.fromarray(pixels).resize((max(int(pixels.shape[1] * factor), 1), max(int(pixels.shape[0] * factor), 1)), Image.BOX))
            texture = self.ctx.texture((pixels.shape[1], pixels.shape[0]), 4, pixels.tobytes())
            texture.build_mipmaps()
            texture.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            texture.anisotropy = 8.0
            texture.repeat_x = texture.repeat_y = True
        self.gl_textures[(path, grey)] = texture
        return texture

    def material_state(self, path):
        """(texture, tint, alpha clip, skip) of a material."""
        material = self.materials.get(path) or {}
        blend = material.get("blend", "BLEND_Opaque")
        if blend in SKIPPED_BLENDS or DEVELOPER_MATERIAL.search(path):
            return self.white, (1.0, 1.0, 1.0), 0.0, True
        names = material.get("textures", {})
        path_of_colour = colour_texture_path(names)
        texture = self.texture_of(path_of_colour) if path_of_colour else None
        # Rock materials paint a blend mask with colours from their parent; its brightness keeps the structure of the rock
        if texture is None and "BlendMap" in names:
            texture = self.texture_of(names["BlendMap"], grey=True)
        clip = 0.33 if blend in ("BLEND_Masked", "BLEND_Translucent") else 0.0
        colours = material.get("colors", {})
        if "water" in path.lower() or "ocean" in path.lower():
            return self.white, self.water_tint, 0.0, False
        tint = tuple(colours["roadcolor"][:3]) if "roadcolor" in colours else tuple(colours["Tint"][:3]) if "Tint" in colours else (1.0, 1.0, 1.0)
        if texture is None:
            colour = next((colours[k] for k in colours if "colo" in k.lower() or "tint" in k.lower()), None)
            return self.white, tuple(colour[:3]) if colour else (0.5, 0.5, 0.5), 0.0, False
        return texture, tint, clip, False

    def road_state(self, path):
        """(mode, mask texture) of the road pass of a material; see the fragment shader's road_mode."""
        material = self.materials.get(path) or {}
        names = material.get("textures", {})
        if "Masks" in names and any(k.startswith("Road_texture") for k in names):
            mask = self.texture_of(names["Masks"])
            if mask is not None:
                return 1, mask
        if "road" in path.lower() and "rvt" in path.lower():
            return 2, None
        return 0, None

    def _pass(self, vao, program, box, depth, view, colour, ids=None):
        """Draw every group that can reach the box."""
        margin = 0.0
        x0, y0, x1, y1 = box
        rows, firsts = [], []
        count = 0
        for draw in self.draws:
            view_centres = draw["centres"] @ view.T
            near = (view_centres[:, 0] + draw["radii"] >= x0 - margin) & (view_centres[:, 0] - draw["radii"] <= x1 + margin) & \
                   (view_centres[:, 1] + draw["radii"] >= y0 - margin) & (view_centres[:, 1] - draw["radii"] <= y1 + margin)
            n = int(near.sum())
            if not n:
                continue
            matrices = draw["matrices"][near]
            # Row-vector 4 x 4 -> three vec4 rows of the column-vector form
            rows.append(np.stack([matrices[:, :, 0], matrices[:, :, 1], matrices[:, :, 2]], 1).reshape(n, -1))
            firsts.append((draw, count, n))
            count += n
        if not rows:
            return
        if self.instance_buffer is not None:
            self.instance_buffer.release()
        self.instance_buffer = self.ctx.buffer(np.concatenate(rows).astype(np.float32).tobytes())
        self.instance_buffer.bind_to_storage_buffer(0)
        program["box"].value = tuple(box)
        program["depth"].value = tuple(depth)
        program["view"].value = tuple(view.T.flatten())
        for draw, first, n in firsts:
            program["first"].value = first
            for start, vertices, material in draw["sections"]:
                texture, tint, clip, skip = self.material_state(material)
                if skip:
                    continue
                texture.use(0)
                crown = draw["crown_top"]
                program["clip"].value = 0.0 if draw["dome"] else clip
                if colour:
                    program["crown_top"].value = crown
                    program["dome"].value = 1.0 if draw["dome"] else 0.0
                    gain = self.material_gains.get(material, (1.0, 1.0, 1.0))
                    program["tint"].value = tuple(t * g for t, g in zip(tint, gain))
                    mode, mask = self.road_state(material)
                    program["road_mode"].value = mode
                    if mask is not None:
                        mask.use(3)
                if ids is not None:
                    index = ids.setdefault(material, len(ids) + 1)
                    program["material_id"].value = ((index & 255) / 255, ((index >> 8) & 255) / 255, ((index >> 16) & 255) / 255)
                vao.render(moderngl.TRIANGLES, vertices=vertices, first=start, instances=n)

    def load_weights(self, frame_x, frame_y, step, n):
        """Layer weights on the map's grid: (layer names, uint8 [layers, n, n]), cell i centred at frame + i * step (metres).

        Components may belong to several landscape actors, each with its own origin, scale and yaw; every cell of the grid
        reads the component it falls in, bilinear between its vertices. A level can repeat another's components (Yehorivka keeps
        its landscape both as one actor and as World Partition proxies, and some proxies name the wrong weightmap channel): a
        component only writes the cells where its weights are not all zero. Cells that no component paints get the weight 255 of
        UNCOVERED_LAYER, the last name, which is there only when such cells are.
        """
        components = []
        root = os.path.join(self.directory, "landscape")
        for level in sorted(os.listdir(root)):
            for component in json.loads(Path(os.path.join(root, level, "components.json")).read_text()):
                component["folder"] = os.path.join(root, level, "wm")
                components.append(component)
        names = sorted({layer["layer"] for c in components for layer in c["layers"]})
        weights = np.zeros((len(names), n, n), np.uint8)
        byte = [2, 1, 0, 3]  # BGRA memory order: logical channel -> byte
        for c in components:
            quads, sub = c["componentSizeQuads"], c["subsectionSizeQuads"]
            scale = np.array(c["scale"][:2], np.float64)
            yaw = math.radians(c["yaw"])
            cos, sin = math.cos(yaw), math.sin(yaw)
            # Position in the actor's own quads. (0, 0) is a real value: the first component of a streaming proxy sits at the proxy's
            # location while its section base counts from the whole landscape's origin
            base = np.array(c["relative"], np.float64)
            # World corners (cm) of the component -> grid window
            corners = []
            for u, v in ((0, 0), (quads, 0), (0, quads), (quads, quads)):
                lx, ly = (base[0] + u) * scale[0], (base[1] + v) * scale[1]
                corners.append((c["location"][0] + cos * lx - sin * ly, c["location"][1] + sin * lx + cos * ly))
            corners = np.array(corners) / 100
            i0, j0 = np.floor((corners.min(0) - (frame_x, frame_y)) / step).astype(int)
            i1, j1 = np.ceil((corners.max(0) - (frame_x, frame_y)) / step).astype(int) + 1
            i0, j0, i1, j1 = max(i0, 0), max(j0, 0), min(i1, n), min(j1, n)
            if i0 >= i1 or j0 >= j1:
                continue
            gx, gy = np.meshgrid(frame_x + np.arange(i0, i1) * step, frame_y + np.arange(j0, j1) * step)
            dx, dy = gx * 100 - c["location"][0], gy * 100 - c["location"][1]
            u = (cos * dx + sin * dy) / scale[0] - base[0]
            v = (-sin * dx + cos * dy) / scale[1] - base[1]
            inside = (u >= -0.5) & (u <= quads + 0.5) & (v >= -0.5) & (v <= quads + 0.5)
            if not inside.any():
                continue
            # Bilinear between the vertices: the nearest one draws the edge of a road in steps of a quad on maps whose quads are not 1 m (Skorpo)
            u_low = np.clip(np.floor(u).astype(np.int64), 0, quads)
            v_low = np.clip(np.floor(v).astype(np.int64), 0, quads)
            u_high, v_high = np.minimum(u_low + 1, quads), np.minimum(v_low + 1, quads)
            u_share, v_share = np.clip(u - u_low, 0, 1), np.clip(v - v_low, 0, 1)
            texel = lambda a: np.where(a <= sub, a, sub + 1 + (a - sub)) if c["numSubsections"] == 2 else a
            size = (sub + 1) * c["numSubsections"]
            maps = [np.fromfile(os.path.join(c["folder"], t + ".bin"), np.uint8).reshape(size, size, 4) for t in c["weightmapTextures"]]
            values = {}
            for layer in c["layers"]:
                plane = maps[layer["texture"]][..., byte[layer["channel"]]]
                top = plane[texel(v_low), texel(u_low)] * (1 - u_share) + plane[texel(v_low), texel(u_high)] * u_share
                bottom = plane[texel(v_high), texel(u_low)] * (1 - u_share) + plane[texel(v_high), texel(u_high)] * u_share
                values[layer["layer"]] = np.round(top * (1 - v_share) + bottom * v_share)
            painted = inside & (sum(values.values()) > 0)
            for name, value in values.items():
                weights[names.index(name), j0:j1, i0:i1][painted] = value[painted]
        uncovered = weights.sum(0, dtype=np.int32) == 0
        if uncovered.any():
            names.append(UNCOVERED_LAYER)
            weights = np.concatenate([weights, np.where(uncovered, 255, 0).astype(np.uint8)[None]])
        return names, weights

    def set_ground(self, heights_m, bounds, frame_size, colours, details, tiles, detail_strength=0.5, shade_strength=1.2, shadow_strength=0.3):
        """The landscape pass. heights_m: [h, w] world Z on a 1 m grid from `bounds` (min x, min y in m); colours: [layers, 3] in 0..1;
        details: [layers, s, s, 3] uint8 (albedo / mean, 128 = 1); tiles: [layers, 2] near and far tile in cm."""
        step = (frame_size) / (heights_m.shape[0] - 1)
        names, weights = self.load_weights(bounds[0], bounds[1], step, heights_m.shape[0])
        array = self.ctx.texture_array((weights.shape[2], weights.shape[1], weights.shape[0]), 1, weights.tobytes())
        array.filter = (moderngl.LINEAR, moderngl.LINEAR)
        detail = self.ctx.texture_array((details.shape[2], details.shape[1], details.shape[0]), 3, details.tobytes())
        detail.build_mipmaps()
        detail.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        detail.repeat_x = detail.repeat_y = True
        detail.anisotropy = 8.0
        program = self.ground_program
        program["frame"].value = ((bounds[0] - step / 2) * 100, (bounds[1] - step / 2) * 100, weights.shape[2] * step * 100, weights.shape[1] * step * 100)
        program["layers"].value = len(names)
        program["colours"].value = [tuple(c) for c in colours] + [(0.0, 0.0, 0.0)] * (MAX_LAYERS - len(colours))
        program["tiles"].value = [tuple(t) for t in tiles] + [(100.0, 100.0)] * (MAX_LAYERS - len(tiles))
        program["detail_strength"].value = detail_strength
        program["shade_strength"].value = shade_strength
        program["shadow_strength"].value = shadow_strength
        self.ground = {"array": array, "detail": detail, "heights": heights_m, "bounds": bounds, "names": names, "step": step,
                       "z_range": (float(heights_m.min()) * 100, float(heights_m.max()) * 100)}

    def set_layer_colours(self, colours):
        """Replace the layer colours of the landscape pass ([layers, 3] in 0..1) after set_ground."""
        self.ground_program["colours"].value = [tuple(c) for c in colours] + [(0.0, 0.0, 0.0)] * (MAX_LAYERS - len(colours))

    def render_ids(self, x0, y0, x1, y1, width, height, ids):
        """[height, width] material index of the top surface over a world box in metres (0: landscape); `ids` maps materials to indices."""
        box = np.array([x0, y0, x1, y1], np.float64) * 100
        depth_range = self.depth_range()
        colour_target = self.ctx.texture((width, height), 3)
        depth_target = self.ctx.depth_renderbuffer((width, height))
        target = self.ctx.framebuffer(colour_target, depth_target)
        target.use()
        target.clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
        self.id_program["diffuse"].value = 0
        self._pass(self.id_vao, self.id_program, box, depth_range, np.eye(3), False, ids)
        self._draw_ground(box, depth_range, None, self.ground_id_program)
        data = np.frombuffer(target.read(components=3, alignment=1), np.uint8).reshape(height, width, 3).astype(np.int64)
        for resource in (target, colour_target, depth_target):
            resource.release()
        return data[..., 0] + (data[..., 1] << 8) + (data[..., 2] << 16)

    def _draw_ground(self, box, depth, shadow, program=None):
        """Draw the landscape grid over the box in cm (one vertex per grid metre, with a margin)."""
        g = self.ground
        h = g["heights"]
        step = g["step"]
        x0 = max(int((box[0] / 100 - g["bounds"][0]) / step) - 2, 0)
        y0 = max(int((box[1] / 100 - g["bounds"][1]) / step) - 2, 0)
        x1 = min(int((box[2] / 100 - g["bounds"][0]) / step) + 3, h.shape[1] - 1)
        y1 = min(int((box[3] / 100 - g["bounds"][1]) / step) + 3, h.shape[0] - 1)
        z = np.asarray(h[y0:y1 + 1, x0:x1 + 1], np.float32) * 100
        ny, nx = z.shape
        gy, gx = np.gradient(z, step * 100)
        normal = np.dstack([-gx, -gy, np.ones_like(z)])
        normal /= np.linalg.norm(normal, axis=2, keepdims=True)
        xs, ys = np.meshgrid((g["bounds"][0] + np.arange(x0, x1 + 1) * step) * 100, (g["bounds"][1] + np.arange(y0, y1 + 1) * step) * 100)
        vertices = np.dstack([xs, ys, z, normal]).astype(np.float32)
        a = (np.arange(ny - 1)[:, None] * nx + np.arange(nx - 1)).ravel()
        indices = np.stack([a, a + 1, a + nx, a + 1, a + nx + 1, a + nx], 1).astype(np.uint32)
        vbo = self.ctx.buffer(vertices.tobytes())
        ibo = self.ctx.buffer(indices.tobytes())
        full = program is None
        program = self.ground_program if full else program
        layout = (vbo, "3f 3f", "position", "normal") if full else (vbo, "3f 12x", "position")
        vao = self.ctx.vertex_array(program, [layout], ibo, index_element_size=4)
        program["box"].value = tuple(box)
        program["depth"].value = tuple(depth)
        if full:
            program["weights"].value = 0
            program["details"].value = 1
            program["shadow_map"].value = 2
            g["array"].use(0)
            g["detail"].use(1)
            shadow.use(2)
        vao.render(moderngl.TRIANGLES)
        vao.release()
        vbo.release()
        ibo.release()

    def render(self, x0, y0, x1, y1, width, height, ssaa=2, background=None):
        """RGB uint8 [height, width, 3] of the world box in metres, row 0 at y0, with contact shadows. The box is drawn with a margin
        of the shadow's radius, so that neighbouring blocks agree along their common edge."""
        metres_per_pixel = (x1 - x0) / width
        pad = int(np.ceil(CONTACT_RADIUS_M * 3 / metres_per_pixel))
        pad_x, pad_y = pad * metres_per_pixel, pad * (y1 - y0) / height
        full_width, full_height = width + 2 * pad, height + 2 * pad
        box = np.array([x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y], np.float64) * 100
        w, h = full_width * ssaa, full_height * ssaa
        depth_range = self.depth_range()
        # Light space: x and y across the sun's rays, z towards the sun
        z = self.sun
        x = np.cross((0.0, 1.0, 0.0), z)
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        light = np.array([x, y, z])
        corners = np.array([[box[i], box[j], k] for i in (0, 2) for j in (1, 3) for k in depth_range]) @ light.T
        margin = 3000.0
        light_box = (corners[:, 0].min() - margin, corners[:, 1].min() - margin, corners[:, 0].max() + margin, corners[:, 1].max() + margin)
        light_depth = (corners[:, 2].min(), corners[:, 2].max())
        shadow_size = 4096
        shadow = self.ctx.depth_texture((shadow_size, shadow_size))
        shadow.compare_func = "<="
        shadow.filter = (moderngl.LINEAR, moderngl.LINEAR)
        fbo = self.ctx.framebuffer(depth_attachment=shadow)
        fbo.use()
        fbo.clear(depth=1.0)
        self.depth_program["diffuse"].value = 0
        self._pass(self.depth_vao, self.depth_program, light_box, light_depth, light, False)

        colour_target = self.ctx.texture((w, h), 3)
        depth_target = self.ctx.depth_texture((w, h))
        target = self.ctx.framebuffer(colour_target, depth_target)
        target.use()
        target.clear(*(background if background is not None else (0.6, 0.53, 0.42)), 1.0, depth=1.0)
        program = self.colour_program
        program["diffuse"].value = 0
        program["shadow_map"].value = 1
        shadow.use(1)
        program["sun"].value = tuple(self.sun)
        program["ambient"].value = self.ambient
        program["sun_strength"].value = self.sun_strength
        program["bias"].value = 0.0015
        program["light_view"].value = tuple(light.T.flatten())
        program["light_box"].value = light_box
        program["light_depth"].value = light_depth
        program["gain"].value = tuple(self.gain)
        program["road_mask"].value = 3
        if self.ground is not None:
            ground = self.ground_program
            ground["sun"].value = tuple(self.sun)
            ground["bias"].value = 0.0015
            ground["light_view"].value = tuple(light.T.flatten())
            ground["light_box"].value = light_box
            ground["light_depth"].value = light_depth
            self._draw_ground(box, depth_range, shadow)
        shadow.use(1)
        # Roads fade into the ground drawn before them
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self._pass(self.colour_vao, program, box, depth_range, np.eye(3), True)
        self.ctx.disable(moderngl.BLEND)
        data = np.frombuffer(target.read(components=3, alignment=1), np.uint8).reshape(h, w, 3)
        colour = data.reshape(full_height, ssaa, full_width, ssaa, 3).mean((1, 3))
        depth = np.frombuffer(depth_target.read(alignment=1), np.float32).reshape(h, w)
        # Window z 0..1 -> height in metres (see the vertex shaders: 0 at the top of the depth range)
        top = (depth_range[0] + depth * (depth_range[1] - depth_range[0])) / 100
        top = top.reshape(full_height, ssaa, full_width, ssaa).mean((1, 3))
        around = ndimage.gaussian_filter(top, CONTACT_RADIUS_M / metres_per_pixel, truncate=3.0)
        occlusion = np.clip((around - top) / CONTACT_HEIGHT_M, 0.0, 1.0)
        colour *= (1.0 - CONTACT_STRENGTH * occlusion)[..., None]
        out = colour[pad:pad + height, pad:pad + width].round().astype(np.uint8)
        for resource in (fbo, shadow, target, colour_target, depth_target):
            resource.release()
        return out
