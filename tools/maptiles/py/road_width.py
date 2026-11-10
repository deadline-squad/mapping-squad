"""Visible width of roads, tracks and pavements for the detailed map tiles, from the client scene.

A landscape spline segment's left and right edges are the full width of the mesh laid along it. The mesh need not be visible
over all of that width: a masked dirt road fades out towards its sides, a road painted into the virtual texture ramps in over
a fifth of its width, a pavement mesh holds a verge strip next to the path. This module finds, per road mesh and material,
which part of the mesh's width a player sees, and pulls the segments' edges in to it.

Method, per mesh with the materials its spline mesh components use (the component's material slots override the mesh's):

1. The mesh's side axis is the one the spline bends it by (``scene_objects.bend_along_spline``: Y for a mesh running along X).
   Its extent over all vertices is the spline's width, so a position across the road is a fraction 0..1 of that extent,
   from the -side edge (the segment's ``left`` edge) to the +side edge (``right``).
2. Per section (one material): sections whose material is not shown from above (``scene_objects.hidden_material``) are dropped.
   The texture coordinate across the road (the UV channel that is a function of the side coordinate) is read off the
   section's vertices as a piecewise linear function of the side coordinate.
3. The opacity of a material along that coordinate follows the Standard render's rules (tools/maprender/scene_render.py
   ``road_state`` and the road pass of the fragment shader): the G channel of ``Masks`` where the material has road layers
   (``Road_texture_*``); the smooth ramp over the outer fifth of U at each side of a road painted into the virtual texture
   (a ``road`` material called ``RVT``); otherwise the colour texture's alpha where the material is masked; otherwise
   opaque. A texture column's opacity is the median over its rows (the texture is laid along the road, so rows repeat the
   profile), linearly interpolated between columns, and the texture repeats outside 0..1.
4. A position is visible where every opacity of the material reaches OPACITY_CLIP, the clip value the Standard render and
   the engine's default use. The section's visible span is the outer extent of its visible positions; the mesh's, the union of
   its sections'.

A segment takes the span of the (mesh, materials) its spline mesh components have (matched by position, the most common
variant of the mesh along the segment); a segment with no match, or with a mesh that has no visible section, keeps its width.
"""

import json
import os
import re
from collections import Counter

import numpy as np
from scipy import spatial

import objects
import scene_objects as scene
from render import smoothstep

OPACITY_CLIP = 0.33
SOFT_EDGE = 0.2
SPAN_SAMPLES = 512
MATCH_M = 4.0
RESAMPLE_M = 1.0
MIN_SHRINK = 0.005
ROAD_CLASSES = ("asphalt", "dirt", "pavement")
SIDE_AXIS = {"X": 1, "Y": 2, "Z": 0}
UV_COLUMNS = (6, 7)
UV_SPREAD = 0.01

# The material's colour texture among its texture parameters: tools/maprender/scene_render.py colour_texture_path
DIFFUSE_NAMES = ("Base_Diffuse", "Albedo", "* Albedo", "Base_Color", "Diffuse", "mat01_difuse", "Road_texture_01_A", "Basedetaildifuse", "Paint_texture", "PM_Diffuse")
COLOUR_PARAMETER = re.compile(r"alb[ei]do|dif+use|base.?colou?r|colou?r.?map|(^|_)dif$|(^|_)a$|(^|_)bc$", re.IGNORECASE)
COLOUR_TEXTURE = re.compile(r"(_|^)(a|bc|d|c|col|color|colour|albedo|diffuse|difuse)(_\w{0,3})?$", re.IGNORECASE)
NOT_COLOUR = re.compile(r"normal|rough|mask|spec|gloss|metal|height|ao$|orm$|ors$|_n$|_r$|_m$|opacity|emissive", re.IGNORECASE)

OPAQUE, ALPHA, MASK, SOFT, HIDDEN, UNRESOLVED = "opaque", "alpha", "mask", "soft", "hidden", "uv"


def colour_texture_path(names):
    """Path of the texture holding a material's base colour among its texture parameters {parameter: path}, None when it has none."""
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


class Textures:
    """The scene's textures: the opacity of a texture channel per column, read once."""

    def __init__(self, scene_dir):
        self.directory = scene_dir
        self.info = json.load(open(os.path.join(scene_dir, "textures.json")))
        self.columns = {}

    def pixels(self, path):
        """[h, w, 4] float32 0..1 of an 8 bit texture, None when the scene has no pixels of it."""
        info = self.info.get(path)
        if not info or "file" not in info or info["format"] not in ("PF_R8G8B8A8", "PF_B8G8R8A8", "PF_G8"):
            return None
        data = np.fromfile(os.path.join(self.directory, "textures", info["file"] + ".bin"), np.uint8)
        if info["format"] == "PF_G8":
            grey = data.reshape(info["height"], info["width"])
            return np.dstack([grey, grey, grey, np.full_like(grey, 255)]) / np.float32(255)
        pixels = data.reshape(info["height"], info["width"], 4) / np.float32(255)
        return pixels[..., [2, 1, 0, 3]] if info["format"] == "PF_B8G8R8A8" else pixels

    def profile(self, path, channel):
        """Opacity across the texture's U: a function of u (the texture repeats) from the median of a channel's rows, None without pixels."""
        if (path, channel) not in self.columns:
            pixels = self.pixels(path)
            self.columns[(path, channel)] = None if pixels is None else np.median(pixels[..., channel], axis=0)
        values = self.columns[(path, channel)]
        if values is None:
            return None
        centres = (np.arange(len(values)) + 0.5) / len(values)
        return lambda u: np.interp(u, centres, values, period=1.0)


def opacity_rules(material_path, materials, textures):
    """([opacity function of u], source) of a material: every function must reach OPACITY_CLIP; source is one of OPAQUE, ALPHA, MASK, SOFT."""
    material = materials.get(material_path) or {}
    names = material.get("textures", {})
    if "Masks" in names and any(key.startswith("Road_texture") for key in names):
        mask = textures.profile(names["Masks"], 1)
        if mask is not None:
            return [mask], MASK
    if "road" in material_path.lower() and "rvt" in material_path.lower():
        return [lambda u: smoothstep(0.0, SOFT_EDGE, u) * smoothstep(1.0, 1.0 - SOFT_EDGE, u)], SOFT
    if material.get("blend") == "BLEND_Masked":
        colour = colour_texture_path(names)
        alpha = textures.profile(colour, 3) if colour else None
        if alpha is not None:
            return [alpha], ALPHA
    return [], OPAQUE


def coordinate_across(vertices, side):
    """(sorted side coordinates, texture coordinate at each) of a section's vertices, None when no UV channel is a function of the side coordinate.

    The channel is the one whose values at one side coordinate differ least; the coordinate of a side position is the mean over its vertices.
    """
    y = np.round(vertices[:, side], 2)
    positions, inverse = np.unique(y, return_inverse=True)
    best = None
    for column in UV_COLUMNS:
        u = vertices[:, column].astype(np.float64)
        lo = np.full(len(positions), np.inf)
        hi = np.full(len(positions), -np.inf)
        np.minimum.at(lo, inverse, u)
        np.maximum.at(hi, inverse, u)
        spread = float((hi - lo).max())
        if best is None or spread < best[0]:
            best = (spread, (lo + hi) / 2)
    return (positions, best[1]) if best[0] <= UV_SPREAD else None


def mesh_span(vertices, indices, info, slot_materials, materials, textures, axis="X"):
    """((lo, hi) visible span of the mesh's width as fractions from its -side edge to its +side edge, None when no section is shown) and sources.

    ``slot_materials`` are the material paths per slot as a component has them (its overrides over the mesh's own); sources are the
    set of SOFT, MASK, ALPHA, OPAQUE, UNRESOLVED (a section whose UV is no function of the side coordinate counts as fully visible) and
    HIDDEN (sections not shown, which add nothing).
    """
    side = SIDE_AXIS[axis]
    low, high = float(vertices[:, side].min()), float(vertices[:, side].max())
    sources = set()
    spans = []
    for section in info["sections"]:
        slot = section["material"]
        material = slot_materials[slot] if slot < len(slot_materials) else ""
        if scene.hidden_material(material, materials):
            sources.add(HIDDEN)
            continue
        used = indices[section["first"]:section["first"] + section["triangles"] * 3]
        if not len(used):
            continue
        part = vertices[np.unique(used)]
        a, b = float(part[:, side].min()), float(part[:, side].max())
        rules, source = opacity_rules(material, materials, textures)
        across = coordinate_across(part, side) if rules else None
        if rules and across is None:
            source = UNRESOLVED
        if not rules or across is None or b <= a:
            spans.append((a, b))
        else:
            y = a + (np.arange(SPAN_SAMPLES) + 0.5) / SPAN_SAMPLES * (b - a)
            u = np.interp(y, *across)
            shown = np.all([rule(u) >= OPACITY_CLIP for rule in rules], axis=0)
            if not shown.any():
                sources.add(source)
                continue
            first, last = int(np.argmax(shown)), SPAN_SAMPLES - 1 - int(np.argmax(shown[::-1]))
            spans.append((a + first / SPAN_SAMPLES * (b - a), a + (last + 1) / SPAN_SAMPLES * (b - a)))
        sources.add(source)
    if not spans or high <= low:
        return None, sources
    lo = max(0.0, (min(s[0] for s in spans) - low) / (high - low))
    hi = min(1.0, (max(s[1] for s in spans) - low) / (high - low))
    return (round(lo, 4), round(hi, 4)), sources


def spline_meshes(scene_dir):
    """The shown spline mesh components of the landscape: {mesh path, materials (the component's slots), axis, flip, x, y (world m, the middle)}.

    ``flip``: the component's scale across the road is negative, so its +side edge is the segment's left one.
    """
    meshes = json.load(open(os.path.join(scene_dir, "meshes.json")))
    by_id = {info["id"]: (path, info) for path, info in meshes.items() if "error" not in info}
    for line in open(os.path.join(scene_dir, "instances.ndjson")):
        if '"SplineMeshComponent"' not in line:
            continue
        item = json.loads(line)
        if item["type"] != "SplineMeshComponent" or not item["owner"].startswith("Landscape") or not scene.is_shown(item) or item["mesh"] not in by_id:
            continue
        path, info = by_id[item["mesh"]]
        p = item["spline"]["p"]
        vec = lambda v: np.array([v["X"], v["Y"], v["Z"]], np.float64)
        middle = (vec(p["StartPos"]) + vec(p["EndPos"])) / 2 + (vec(p["StartTangent"]) - vec(p["EndTangent"])) / 8
        world = (np.append(middle, 1.0) @ objects.component_world(item["chain"]))[:2] / 100
        overrides = item["overrides"]
        slots = tuple(overrides[i] if i < len(overrides) and overrides[i] else material for i, material in enumerate(info["materials"]))
        yield {"mesh": path, "materials": slots, "axis": item["spline"]["axis"][-1], "flip": p.get("StartScale", {"X": 1})["X"] < 0, "x": float(world[0]), "y": float(world[1])}


def variant_spans(scene_dir, components):
    """{(mesh path, materials, axis): (span or None, sources)} for the variants among the spline mesh components."""
    materials = json.load(open(os.path.join(scene_dir, "materials.json")))
    meshes = json.load(open(os.path.join(scene_dir, "meshes.json")))
    textures = Textures(scene_dir)
    spans = {}
    for key in {(c["mesh"], c["materials"], c["axis"]) for c in components}:
        path, slots, axis = key
        vertices, indices = scene.read_mesh(scene_dir, meshes[path])
        spans[key] = mesh_span(vertices, indices, meshes[path], slots, materials, textures, axis)
    return spans


def centre_points(line):
    """Points [n, 2] along a segment's centre line, at most RESAMPLE_M apart."""
    centre = np.asarray(line["center"], np.float64)[:, :2]
    parts = [centre[:1]]
    for a, b in zip(centre[:-1], centre[1:]):
        steps = max(int(np.ceil(np.hypot(*(b - a)) / RESAMPLE_M)), 1)
        parts.append(a + (b - a) * (np.arange(1, steps + 1) / steps)[:, None])
    return np.concatenate(parts)


def segment_spans(lines, components, spans):
    """Per line its visible span (lo, hi) as fractions from its left edge to its right edge, None where the line keeps its width.

    A road line (ROAD_CLASSES) takes, per mesh it lays, the most common variant among the components of that mesh whose middle is
    within MATCH_M of its centre line; the span is the union over its meshes. A mesh without a match or without a visible section
    leaves the whole width.
    """
    by_mesh = {}
    for component in components:
        by_mesh.setdefault(component["mesh"], []).append(component)
    wanted = {mesh for line in lines if line["cls"] in ROAD_CLASSES for mesh in line.get("meshes", [])}
    votes = {}
    for mesh in wanted & set(by_mesh):
        owners = [(i, centre_points(line)) for i, line in enumerate(lines) if line["cls"] in ROAD_CLASSES and mesh in line.get("meshes", [])]
        points = np.concatenate([p for _, p in owners])
        owner = np.concatenate([np.full(len(p), i) for i, p in owners])
        middles = np.array([[c["x"], c["y"]] for c in by_mesh[mesh]])
        distance, nearest = spatial.cKDTree(points).query(middles)
        for component, d, k in zip(by_mesh[mesh], distance, nearest):
            if d <= MATCH_M:
                votes.setdefault((int(owner[k]), mesh), Counter())[(component["materials"], component["axis"], component["flip"])] += 1
    result = []
    for i, line in enumerate(lines):
        lo, hi = 1.0, 0.0
        found = line["cls"] in ROAD_CLASSES and bool(line.get("meshes"))
        for mesh in line.get("meshes", []) if found else []:
            if (i, mesh) not in votes:
                found = False
                break
            (slots, axis, flip), _ = votes[(i, mesh)].most_common(1)[0]
            span = spans[(mesh, slots, axis)][0]
            if span is None:
                found = False
                break
            lo, hi = min(lo, 1 - span[1] if flip else span[0]), max(hi, 1 - span[0] if flip else span[1])
        result.append((lo, hi) if found and hi - lo < 1 - MIN_SHRINK * 2 else None)
    return result


def narrowed(line, span):
    """A line with its edges pulled in to the span (fractions from its left edge to its right one), the centre line in the middle of the new edges."""
    left, right = np.asarray(line["left"], np.float64), np.asarray(line["right"], np.float64)
    new_left, new_right = left + (right - left) * span[0], left + (right - left) * span[1]
    centre = np.asarray(line["center"], np.float64).copy()
    centre[:, :2] = (new_left + new_right) / 2
    return {**line, "left": np.round(new_left, 2).tolist(), "right": np.round(new_right, 2).tolist(), "center": np.round(centre, 2).tolist(), "span": list(span)}


def narrowed_lines(scene_dir, lines):
    """The lines with the edges of every road segment narrowed to what its meshes show (see the module description)."""
    components = list(spline_meshes(scene_dir))
    spans = segment_spans(lines, components, variant_spans(scene_dir, components))
    return [line if span is None else narrowed(line, span) for line, span in zip(lines, spans)]
