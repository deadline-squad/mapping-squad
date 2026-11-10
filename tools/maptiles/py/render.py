"""Render the detailed tactical map tiles of one map from its prepared sources (prep.py).

Usage: render.py <map> [--workers N] [--zooms Z ...] [--blocks z/bx/by ...] [--out DIR]

Tiles follow SquadCalc's map frame: Leaflet CRS.Simple, the map image spanning LatLng [0, 0] to
[-256, 256]; at zoom z the map is 256 * 2**z pixels wide and tile (z, x, y) covers pixels
[256 x, 256 (x + 1)) x [256 y, 256 (y + 1)). Pixel (px, py) has its centre at world
X = min_x + (px + 0.5) * size_x / (256 * 2**z), Y = min_y + (py + 0.5) * size_y / (256 * 2**z),
the same as squadGrid.js (gameToMapScale for X, gameToMapScaleY for Y). The finest zoom is the
first with at most FINEST_M_PER_PX metres per pixel.

Output in /tiles/<map>/ (swapped in whole when the map is done): <z>/<x>_<y>.webp and meta.json
(maxNativeZoom, bounds, sources, the legend's symbols) that the SquadCalc frontend reads.

Every input is sampled at the global pixel position, and the label and symbol placements depend
only on world data, so blocks rendered separately join without seams (a block's margin is wider than
the longest shadow, the biggest crown and a label). Layers, bottom to top: ground cover (landscape
physical materials), crop fields, tracks painted into the landscape, hillshade and slope tint, contours,
water, roads and tracks, object shadows, objects (visible meshes of the scene, scene_prep.py), crowns
(silhouettes of the real meshes), contour labels, summits, roof height labels.
"""

import argparse
import json
import math
import multiprocessing
import os
import re
import shutil
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage, sparse

import features

# Container paths (maptiles.sh)
PREP_DIR = "/prep"
TILES_DIR = "/tiles"
HEIGHTMAPS_DIR = "/heightmaps"
TILE = 256
BLOCK_TILES = 4
MARGIN = 64
# A block whose reach holds nothing but sea at least this deep is one colour (WATER_DEEP_RGB: the water's colour is deep from 12 m on,
# and the ground's cubic interpolation can overshoot its samples a little)
UNIFORM_SEA_DEPTH_M = 13.0
# Reach of a block beyond its margin, in pixels and metres: the sampling windows and smoothing of render_block stay inside it
UNIFORM_REACH_PX = 24
UNIFORM_REACH_M = 24.0
# Shadows longer than this are cut; the block margin covers it
SHADOW_REACH_M = 8.0
# Shadows fall to the south-east like the relief's light but from a higher sun: a shadow is 0.58 times its object's height long
SHADOW_TAN_ELEVATION = math.tan(math.radians(60))
# The scene raster is 0.1 m; the next zoom (a quarter of the tiles) would add 3x the weight and time but no detail
FINEST_M_PER_PX = 0.125
# The finest pixel size of the first Detailed layer. Text and contour lines keep at least their size on screen there: from that
# layer's finest zoom on, label sizes, halos and widths double with every zoom (label_scale), so that a phone shows them as large
# as it did when the tiles ended at that zoom and the browser stretched them.
LEGACY_FINEST_M_PER_PX = 0.33
OBJECT_CELL_M = 0.1
NEAR_LEVEL = 3  # pyramid level (0.8 m cells) that tells the contour labels where objects are
WEBP_QUALITY = 88
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Ground cover colours by landscape physical material (features.PHYSICAL_MATERIALS)
COVER_RGB = {
    "PhysMat_Grass": (200, 216, 162), "PhysMat_GrassTall": (182, 204, 140), "PhysMat_GrassTall_Rustle": (182, 204, 140),
    "PhysMat_Dirt": (216, 198, 160), "PhysMat_DirtGravel": (208, 196, 172), "PhysMat_Gravel": (204, 200, 190),
    "PhysMat_Mud_deep": (178, 166, 138), "PhysMat_Rock": (184, 178, 170), "PhysMat_Loose_Rocks": (194, 188, 176),
    "PhysMat_Sand": (236, 224, 184), "PhysMat_Leafs": (174, 194, 136), "PhysMat_LeafsNoRustle": (174, 194, 136),
    "PhysMat_Asphalt": (170, 168, 164), "PhysMat_Snow": (244, 246, 250), "PhysMat_SnowWet": (230, 234, 240),
    "PhysMat_Default": (212, 206, 190),
}
NO_COVER_RGB = (214, 208, 192)
# Beyond the game's landscape (cover NO_COVER: SquadHeight's world or the client's low-poly scenery, never played on) the ground is
# drawn towards this grey by OUTSIDE_ALPHA and without contours, contour labels or summits: a low-poly backdrop shaded and contoured
# like real ground was the loudest surface of Kohat, Skorpo, Chora, Mestia and Sumari
OUTSIDE_RGB = (212, 211, 207)
OUTSIDE_ALPHA = 0.7
STEEP_RGB = (172, 156, 128)
WATER_RGB = np.array((156, 196, 226), np.float32)
WATER_DEEP_RGB = np.array((92, 142, 192), np.float32)
SHORE_RGB = np.array((62, 112, 168), np.float32)
# The water's colour runs from shallow to deep with the square root of the depth up to WATER_DEEP_M: half of the range is spent on
# the first quarter of it (3 m), where a ford differs from a channel; a linear ramp over 12 m left a wadeable stream and a 2 m
# channel 4 grey levels apart
WATER_DEEP_M = 12.0
# The water's depth is cut at this much above the surface before the shore is smoothed, so the smoothing moves a shore by
# centimetres; the "no surface" of a plane's or river mesh's edge (a billion metres down) ate 4 sigma of water along it
SHORE_DRY_M = 0.3
SHORE_LINE_PX = 1.2  # width of the shore line, the level line where the water's cover is a half
CONTOUR_RGB = np.array((150, 92, 40), np.float32)
CONTOUR_LABEL_RGB = (128, 72, 24)
HALO_RGB = (250, 246, 236)
# Spline layers: fill colour, casing colour (None: no casing), minimum width in pixels
SPLINE_STYLE = {
    "dirt": ((212, 176, 116), (128, 96, 58), 1.2),
    "pavement": ((214, 210, 202), (120, 116, 110), 1.0),
    "asphalt": ((226, 224, 218), (92, 86, 78), 1.6),
    "rail": ((86, 82, 78), None, 1.4),
    "trench": ((96, 66, 40), None, 1.2),
    "hedge": ((104, 140, 76), (70, 102, 50), 1.2),
}
ROAD_CLASSES = ("dirt", "pavement", "asphalt")  # spline classes coloured by the "road" field
# Strength of a spline class's casing (0..1): a dirt road's is half an asphalt road's, enough to carry it across grass for a
# red-green colour-blind reader (its fill differs from grass mostly in hue: CIEDE2000 2.6 under deuteranopia) without the weight of a road
CASING_ALPHA = {"dirt": 0.45}
CASING_ALPHA_DEFAULT = 0.85
# A railway is its line with cross ties every RAIL_TIE_M metres, RAIL_TIE_REACH times the line's width to each side, where a pixel
# is at most RAIL_TIE_MAX_PX_M: without them it was a dark line 2.7 CIEDE2000 from a wall
RAIL_TIE_M = 4.0
RAIL_TIE_REACH = 1.6
RAIL_TIE_MAX_PX_M = 1.0
SPLINE_ORDER = ["dirt", "pavement", "asphalt", "rail", "trench", "hedge"]
# Weights (0..1) of the landscape's path layers between which a painted track fades in
PAINTED_TRACK_EDGE = (0.4, 0.6)
# Crop fields (crowns.crop_fields): drawn where the crops cover CROP_EDGE of the ground, coloured from low crops (wheat, poppies) to
# tall ones (maize, cannabis) by their height (m), which is what they hide; a diagonal hatch every CROP_HATCH_PX pixels marks them
# as fields where a pixel is CROP_HATCH_MAX_M or finer
CROP_EDGE = (0.3, 0.7)
CROP_RGB = ((0.6, (226, 200, 112)), (2.0, (146, 166, 98)))
CROP_ALPHA = 0.55
CROP_HATCH_PX = 6.0
CROP_HATCH_MAX_M = 1.0
# Foliage: canopy colour and alpha, outline colour, by features.FOLIAGE_CLASSES
FOLIAGE_STYLE = {
    features.CONIFER: ((40, 98, 56), 0.56, (22, 62, 34)),
    features.DECIDUOUS: ((92, 150, 68), 0.5, (48, 98, 40)),
    features.BUSH: ((128, 160, 86), 0.55, (78, 110, 52)),
    features.ROCK: ((166, 161, 153), 0.9, (124, 119, 112)),
    features.PALM: ((112, 164, 74), 0.62, (64, 110, 44)),
}
# Colour of a species (mesh name pattern) over its class colour: crowns of different species differ in colour as in the game
SPECIES_RGB = [
    (r"olive", (136, 160, 108)),
    (r"poplar|populus", (82, 142, 66)),
    (r"salix|willow", (124, 160, 90)),
    (r"tamarix", (108, 152, 110)),
]
FOLIAGE_GROUPS = {features.CONIFER: "conifer", features.DECIDUOUS: "deciduous", features.BUSH: "bush"}  # fields of fit_fields.py
FOLIAGE_ORDER = [features.ROCK, features.BUSH, features.DECIDUOUS, features.PALM, features.CONIFER]
TRUNK_RGB = (60, 44, 30)
# Crowns up to CROWN_SPRITE_MAX_PX across (coarse zooms: thousands per block) are cut from a cache of stamps turned and scaled to
# steps of CROWN_SPRITE_YAW_DEG and CROWN_SPRITE_STEP_PX (also their height in pixels, which lights them): an edge moves by at most
# a quarter of a pixel against the exact stamp. Larger crowns are drawn exactly.
CROWN_SPRITE_MAX_PX = 8.0
CROWN_SPRITE_YAW_DEG = 7.5
CROWN_SPRITE_STEP_PX = 0.25
CROWN_SPRITE_CACHE = 20000
CROWN_OUTLINE_PX = 2.5
# Objects: colour ramp of structures by height above ground (m), other classes by colour
# The ramp is a slate (CIELAB hue 285 degrees, chroma 6-8) in even lightness steps L* 74, 62, 52, 42, 33, 25: a hue no ground cover,
# crown or rock has, so a building differs from a conifer by 2-3 times the colour distance of the earlier grey-brown under the
# red-green deficiencies, which keep the blue-yellow axis (py/palette_contrast.py)
STRUCTURE_RAMP = [(0.3, (179, 181, 194)), (2.0, (147, 149, 163)), (5.0, (121, 123, 137)), (10.0, (96, 99, 112)),
                  (20.0, (75, 77, 88)), (40.0, (57, 59, 68))]
# A roof is darker than the ground around it by at least ROOF_CONTRAST grey levels (0-255 luma), as far as the ramp allows: the
# ramp's lightest roofs (low buildings, light beige) vanish on snow or sand, and the edges of a building are what the eye reads on a
# map. The ramp is squeezed, not cut, so the order of heights stays; ROOF_MIN_SCALE keeps some of it on the darkest ground.
ROOF_CONTRAST = 90.0
ROOF_MIN_SCALE = 0.25
# An object that covers only a part of a pixel is drawn at a stronger coverage once a pixel is wider than OBJECT_SOLID_PX_M metres:
# the coverage c becomes 1 - (1 - c) ** (px / OBJECT_SOLID_PX_M), so a house, a car or a wall a few metres long does not fade into
# the ground at the overview zooms (a 2 x 5 m car covers 0.1 of a 10 m pixel). At pixels that size and finer, where the
# edges are placed to a fraction of a pixel, the coverage is untouched.
OBJECT_SOLID_PX_M = 1.0
GROUND_LUMA_LEVEL = 5  # pyramid level (3.2 m cells) of the map of ground luma that roofs are held against
LUMA = np.array((0.299, 0.587, 0.114), np.float32)
OBJECT_RGB = {features.WALL: (84, 82, 92), features.ROCK_OBJECT: (166, 161, 153), features.VEGETATION: (118, 152, 86),
              features.BRIDGE: (224, 222, 216)}
OUTLINE_RGB = np.array((40, 40, 48), np.float32)
# Outlines of the classes that are not buildings: hedges get a green rim, rocks a grey one (a rock is cover, but its dark rim made
# it louder than the buildings), bridge and quay decks a rim darker than a road's casing, so a bridge differs from the road on it
OUTLINE_BY_CLASS = {features.VEGETATION: np.array((76, 108, 54), np.float32), features.BRIDGE: np.array((56, 52, 48), np.float32),
                    features.ROCK_OBJECT: np.array((124, 119, 112), np.float32)}
# A deck-class cell (features.BRIDGE: decks, pavements, kerbs, road lines) lower than this above the ground lies on it: a paved
# surface, drawn in the pavement's colour without rim or relief; higher, it is a bridge or quay deck
PAVED_MAX_M = 1.0
STEP_OUTLINE_M = 0.8
STEP_OUTLINE_PX_M = 1.5
SHADOW_FACTOR = 0.72
# Relief and line strengths a style may change (see apply_style)
STEEP_ALPHA = 0.4
SHADE_STRENGTH = 0.7
CONTOUR_ALPHA = (0.5, 0.85)  # minor, major contours
GRADE = None  # final colour grade: {"gain": [r, g, b], "offset": [r, g, b]}
FIELDS = {}  # colour fields of a style: {group: {"file": name in /prep/<map>, "cell_m": metres per cell}}
LIGHT = np.array([-1.0, -1.0, math.sqrt(2.0)]) / 2.0  # from the north-west, 45 degrees up (image Y points south)
# The ground's relief is a multi-directional oblique-weighted hillshade (MDOW, Mark 1992; the formula of relief.py, the relief
# layer) of lights from these compass bearings at LIGHT's elevation: slopes of every orientation read alike. A style that sets
# LIGHT_FROM (matched to the single light baked into the game's minimap) is lit by LIGHT alone. Objects, crowns and shadows
# always take LIGHT.
RELIEF_AZIMUTHS = (360.0, 315.0, 270.0, 225.0)
MULTIDIRECTIONAL_RELIEF = True
# Averaging four lights, the MDOW of the maps' ground spreads about 2.5 times less around flat than one light does (standard
# deviation on 1 km windows: Kamdesh 2.57, Al Basrah 2.65, Gorodok 2.49 times less): the relief strength is raised by that much,
# so the default style keeps its contrast
MDOW_CONTRAST = 2.5
CONTOUR_LADDER = [1, 2, 5, 10, 20, 50, 100, 200]
MAJOR = {1: 10, 2: 10, 5: 25, 10: 50, 20: 100, 50: 250, 100: 500, 200: 1000}
SHORE_SMOOTH_M = 0.6
LABEL_CELL = 320
LABEL_STEP = 8
LABEL_HALF_PX = 14
# Every label (contour and roof height) has the same text colour family and halo
LABEL_TEXT_RGB = (40, 36, 30)
LABEL_HALO_PX = 2
ROOF_LABEL_CELL = 64
ROOF_LABEL_PAD = 3
ROOF_LABEL_HALF_HEIGHT = 8
LABEL_FONT_PT = {"contour": 11, "roof": 12}
# Summits (spot heights): the tops of the ground that stand SUMMIT_RISE_M and more above the mean ground SUMMIT_RING_M around them
# and are the highest point within SUMMIT_REACH_M, found on the ground smoothed by SUMMIT_SMOOTH_M; drawn as a dot of
# SUMMIT_DOT_PX radius with the height, the highest rise first, never closer than SUMMIT_SPACING_PX
SUMMIT_SMOOTH_M = 4.0
SUMMIT_REACH_M = 40.0
SUMMIT_RING_M = 60.0
SUMMIT_RISE_M = 4.0
SUMMIT_EDGE_M = 8.0  # the highest point of a slope that the map's edge cuts is the top of no hill
SUMMIT_SPACING_PX = 180
SUMMIT_DOT_PX = 2.4
SUMMIT_RGB = (96, 52, 14)
SHADOW_MIN_CASTER_PX = 2  # an object narrower than this casts no shadow: it is not visible on its own at that zoom

STYLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "styles")
FOLIAGE_NAMES = {"conifer": features.CONIFER, "deciduous": features.DECIDUOUS, "bush": features.BUSH, "rock": features.ROCK, "palm": features.PALM}
OBJECT_NAMES = {"wall": features.WALL, "rock": features.ROCK_OBJECT, "vegetation": features.VEGETATION, "bridge": features.BRIDGE}

_data = {}


def apply_style(path):
    """Replace the default palette and strengths by the ones of a style file (JSON, tools/maptiles/py/styles).

    Keys, all optional: COVER_RGB {physical material: rgb}, NO_COVER_RGB, STEEP_RGB, WATER_RGB, WATER_DEEP_RGB,
    SHORE_RGB, CONTOUR_RGB, CONTOUR_LABEL_RGB, SPLINE_FILL {spline class: rgb}, FOLIAGE_RGB {conifer, deciduous,
    bush, rock, palm: rgb}, FOLIAGE_ALPHA {the same names: opacity of the canopy colour}, STRUCTURE_RAMP [[height m, rgb]], OBJECT_RGB {wall, rock, vegetation, bridge: rgb}, SHADOW_FACTOR,
    FIELDS {colour group: {file, cell_m}} (fit_fields.py: the game's regional colours of the ground, water, road, object,
    conifer, deciduous and bush groups, sampled instead of the class colours), STEEP_ALPHA, SHADE_STRENGTH, LIGHT_FROM (azimuth of the light of the ground relief in degrees, image axes: x east,
    y south, the default -135 is the north-west), CONTOUR_ALPHA [minor, major] and GRADE {gain, offset}. Unnamed colours stay
    as in the default style. Every worker process applies the style after import.
    """
    style = json.load(open(path))
    colour = lambda value: tuple(int(round(c)) for c in value)
    vector = lambda value: np.array(value, np.float32)
    for key in ("NO_COVER_RGB", "STEEP_RGB", "CONTOUR_LABEL_RGB"):
        if key in style:
            globals()[key] = colour(style[key])
    for key in ("WATER_RGB", "WATER_DEEP_RGB", "SHORE_RGB", "CONTOUR_RGB"):
        if key in style:
            globals()[key] = vector(style[key])
    if "LIGHT_FROM" in style:
        light = math.radians(style["LIGHT_FROM"])
        LIGHT[:] = (math.sqrt(0.5) * math.cos(light), math.sqrt(0.5) * math.sin(light), math.sqrt(0.5))
        globals()["MULTIDIRECTIONAL_RELIEF"] = False
    for key in ("SHADOW_FACTOR", "STEEP_ALPHA", "SHADE_STRENGTH"):
        if key in style:
            globals()[key] = float(style[key])
    if "CONTOUR_ALPHA" in style:
        globals()["CONTOUR_ALPHA"] = tuple(style["CONTOUR_ALPHA"])
    if "FIELDS" in style:
        FIELDS.clear()
        FIELDS.update(style["FIELDS"])
    if "GRADE" in style:
        globals()["GRADE"] = {k: vector(v) for k, v in style["GRADE"].items()}
    COVER_RGB.update({name: colour(rgb) for name, rgb in style.get("COVER_RGB", {}).items()})
    for cls, rgb in style.get("SPLINE_FILL", {}).items():
        SPLINE_STYLE[cls] = (colour(rgb),) + SPLINE_STYLE[cls][1:]
    for name, rgb in style.get("FOLIAGE_RGB", {}).items():
        FOLIAGE_STYLE[FOLIAGE_NAMES[name]] = (colour(rgb),) + FOLIAGE_STYLE[FOLIAGE_NAMES[name]][1:]
    for name, rgb in style.get("OBJECT_RGB", {}).items():
        OBJECT_RGB[OBJECT_NAMES[name]] = colour(rgb)
    for name, alpha in style.get("FOLIAGE_ALPHA", {}).items():
        FOLIAGE_STYLE[FOLIAGE_NAMES[name]] = FOLIAGE_STYLE[FOLIAGE_NAMES[name]][:1] + (float(alpha),) + FOLIAGE_STYLE[FOLIAGE_NAMES[name]][2:]
    if "STRUCTURE_RAMP" in style:
        STRUCTURE_RAMP[:] = [(float(h), colour(rgb)) for h, rgb in style["STRUCTURE_RAMP"]]


def legend():
    """The map's symbols for a legend, in reading order: [{"key", "kind" ("area", "line" or "point"), "rgb", "outline" (optional)}].

    Written into meta.json, so the page's legend shows the colours of the tiles it has loaded (a style changes them) and
    needs none of its own. The keys are the page's label keys (SquadCalc src/js/detailedLegend.js, LEGEND_KEYS).
    """
    def entry(key, kind, rgb, outline=None):
        item = {"key": key, "kind": kind, "rgb": [int(round(float(c))) for c in rgb]}
        if outline is not None:
            item["outline"] = [int(round(float(c))) for c in outline]
        return item
    ramp = dict(STRUCTURE_RAMP)
    spline = lambda cls: SPLINE_STYLE[cls][0]
    foliage = lambda cls: FOLIAGE_STYLE[cls][0]
    return [
        entry("building_low", "area", ramp[2.0], OUTLINE_RGB), entry("building_tall", "area", ramp[20.0], OUTLINE_RGB),
        entry("wall", "line", OBJECT_RGB[features.WALL]), entry("deck", "area", OBJECT_RGB[features.BRIDGE], OUTLINE_BY_CLASS[features.BRIDGE]),
        entry("road_asphalt", "line", spline("asphalt"), SPLINE_STYLE["asphalt"][1]), entry("road_dirt", "line", spline("dirt"), SPLINE_STYLE["dirt"][1]),
        entry("railway", "line", spline("rail")), entry("trench", "line", spline("trench")),
        entry("water_shallow", "area", WATER_RGB, SHORE_RGB), entry("water_deep", "area", WATER_DEEP_RGB, SHORE_RGB),
        entry("contour", "line", CONTOUR_RGB), entry("summit", "point", SUMMIT_RGB),
        entry("conifer", "point", foliage(features.CONIFER)), entry("deciduous", "point", foliage(features.DECIDUOUS)),
        entry("bush", "point", foliage(features.BUSH)), entry("rock", "point", foliage(features.ROCK), FOLIAGE_STYLE[features.ROCK][2]),
        entry("crop_low", "area", CROP_RGB[0][1]), entry("crop_tall", "area", CROP_RGB[1][1]),
        entry("grass", "area", COVER_RGB["PhysMat_Grass"]), entry("dirt", "area", COVER_RGB["PhysMat_Dirt"]), entry("sand", "area", COVER_RGB["PhysMat_Sand"]),
        entry("rock_ground", "area", COVER_RGB["PhysMat_Rock"]), entry("snow", "area", COVER_RGB["PhysMat_Snow"]),
        entry("asphalt_ground", "area", COVER_RGB["PhysMat_Asphalt"]), entry("outside", "area", OUTSIDE_RGB),
    ]


def finest_zoom(size_m, m_per_px=FINEST_M_PER_PX):
    """Smallest zoom whose pixels are at most m_per_px metres."""
    return max(0, math.ceil(math.log2(size_m / (TILE * m_per_px))))


def label_scale(d, z):
    """Factor (1, 2, 4, ...) of the label sizes, halos and contour widths at zoom z: 1 up to the first layer's finest zoom, then doubling."""
    return 2 ** max(0, z - d["legacy_finest"])


def label_font(d, kind, scale):
    """Bold font of a label kind ("contour" or "roof") at a label_scale, made once per size."""
    key = (kind, scale)
    if key not in d["fonts"]:
        d["fonts"][key] = ImageFont.truetype(FONT_BOLD, LABEL_FONT_PT[kind] * scale)
    return d["fonts"][key]


def load(slug):
    """Prepared sources of a map, memory-mapped; once per worker."""
    base = os.path.join(PREP_DIR, slug)
    meta = json.load(open(os.path.join(base, "meta.json")))
    top = json.load(open(os.path.join(base, "top_meta.json")))
    b = meta["bounds_m"]
    names = json.load(open(os.path.join(base, "crowns.json")))
    d = {
        "meta": meta,
        "min_x": b["min_x"], "min_y": b["min_y"],
        "size_x": b["max_x"] - b["min_x"], "size_y": b["max_y"] - b["min_y"],
        "ground": np.load(os.path.join(base, "top_ground.npy"), mmap_mode="r"),
        "ground_base": np.load(os.path.join(base, "top_ground_base.npy"), mmap_mode="r"),
        "paths": np.load(os.path.join(base, "top_paths.npy"), mmap_mode="r"),
        "crops": np.load(os.path.join(base, "top_crops.npy"), mmap_mode="r"),
        "water_top": np.load(os.path.join(base, "top_water_surface.npy"), mmap_mode="r"),
        "cover": np.load(os.path.join(base, "cover.npy"), mmap_mode="r"),
        "foliage": dict(np.load(os.path.join(base, "crowns.npz"))),
        "stamps": np.load(os.path.join(base, "crowns_stamps.npy")),
        "lines": json.load(open(os.path.join(base, "top_lines.json"))),
        "planes": json.load(open(os.path.join(base, "water.json")))["planes"] + json.load(open(os.path.join(base, "top_water.json")))["planes"],
        "labels": json.load(open(os.path.join(base, "top_labels.json"))),
        "roof_cache": {},
        "sea": meta["sea_level_m"],
        "levels": top["pyramid_levels"],
        "obj": {(name, k): np.load(os.path.join(base, f"top_{name}{k}.npy"), mmap_mode="r")
                for name in "hcv" for k in range(top["pyramid_levels"] + 1)},
        "finest": finest_zoom(b["max_x"] - b["min_x"]),
        "legacy_finest": finest_zoom(b["max_x"] - b["min_x"], LEGACY_FINEST_M_PER_PX),
        "fonts": {},
    }
    palette = np.array([COVER_RGB[name] for name in meta["physical_materials"]] + [NO_COVER_RGB] * (256 - len(meta["physical_materials"])), np.float32)
    palette[features.NO_COVER] = NO_COVER_RGB
    d["palette"] = palette
    d["ground_luma_level"] = min(GROUND_LUMA_LEVEL, d["levels"])
    k = d["ground_luma_level"]
    d["ground_luma"] = ground_luma_map(d["cover"], palette, d["obj"][("h", k)], d["obj"][("v", k)], OBJECT_CELL_M * 2 ** k)
    d["fields"] = {group: (np.load(os.path.join(base, spec["file"]), mmap_mode="r"), spec["cell_m"]) for group, spec in FIELDS.items()}
    ground = d["ground"]
    gy, gx = np.gradient(np.asarray(ground[::4, ::4], dtype=np.float64), 4.0)
    slope = np.hypot(gx, gy)
    # Relief of the map: a hilly map gets 2 m minor contours at the finest zoom, a flat one 1 m
    d["relief_slope"] = float(np.percentile(slope, 80))
    d["minor_finest"] = 2 if d["relief_slope"] > 0.18 else 1
    for line in d["lines"]:
        line["left"] = np.asarray(line["left"], np.float64)
        line["right"] = np.asarray(line["right"], np.float64)
        line["center"] = np.asarray(line["center"], np.float64)
        both = np.concatenate([line["left"], line["right"]])
        line["box"] = (both[:, 0].min(), both[:, 1].min(), both[:, 0].max(), both[:, 1].max())
    for plane in d["planes"]:
        p = np.asarray(plane["polygon"])
        plane["box"] = (p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max())
    d["species_rgb"] = {i: colour for i, name in enumerate(names) for pattern, colour in SPECIES_RGB if re.search(pattern, name, re.IGNORECASE)}
    # no summit on a rise of a lake's bed
    tops = summits(np.asarray(ground), np.asarray(d["cover"]), d["sea"])
    d["summits"] = [s for s in tops if not under_water(d, np.array([d["min_x"] + s["u"]]), np.array([d["min_y"] + s["v"]]), np.array([s["h"]]))[0]]
    d["summit_cache"] = {}
    return d


def summits(ground, cover, sea):
    """Summits of the ground [{u, v, h, rise}] (u, v: metres east and south of the map's corner; h: the height contours are labelled
    with), the highest rise first; see SUMMIT_RISE_M. Not beyond the landscape, nor at or below the sea."""
    step = 2
    coarse = ndimage.gaussian_filter(np.asarray(ground[::step, ::step], np.float32), SUMMIT_SMOOTH_M / step, mode="nearest")
    reach = int(round(SUMMIT_REACH_M / step))
    top = (coarse == ndimage.maximum_filter(coarse, 2 * reach + 1, mode="nearest"))
    ring = int(round(SUMMIT_RING_M / step))
    around = ndimage.uniform_filter(coarse, 2 * ring + 1, mode="nearest")
    found = []
    edge = int(round(SUMMIT_EDGE_M / step))
    top[:edge], top[-edge:], top[:, :edge], top[:, -edge:] = False, False, False, False
    for r, c in zip(*np.nonzero(top & (coarse - around >= SUMMIT_RISE_M))):
        window = ground[max(0, r * step - step):r * step + step + 1, max(0, c * step - step):c * step + step + 1]
        dr, dc = np.unravel_index(int(np.argmax(window)), window.shape)
        v, u = max(0, r * step - step) + dr, max(0, c * step - step) + dc
        h = float(ground[v, u])
        if cover[min(v, cover.shape[0] - 1), min(u, cover.shape[1] - 1)] == features.NO_COVER or (sea is not None and h <= sea + 0.5):
            continue
        found.append({"u": float(u), "v": float(v), "h": h, "rise": float(coarse[r, c] - around[r, c])})
    return sorted(found, key=lambda s: (-s["rise"], s["u"], s["v"]))


def field_colour(d, group, frame):
    """Colour field of a style group (fit_fields.py) at the block's pixels [H, W, 3], or None when the style has none."""
    if group not in d["fields"]:
        return None
    array, cell = d["fields"][group]
    return sample_grid(array, frame.u / cell - 0.5, frame.v / cell - 0.5, frame.px / cell, 1, np.float32, separable=True).astype(np.float32)


def crop(array, r0, r1, c0, c1):
    """array[r0:r1, c0:c1] with indices outside the array clamped to its edge (global 'nearest' padding)."""
    rows = np.clip(np.arange(r0, r1), 0, array.shape[0] - 1)
    cols = np.clip(np.arange(c0, c1), 0, array.shape[1] - 1)
    inner = np.asarray(array[rows.min():rows.max() + 1, cols.min():cols.max() + 1])
    return inner[np.ix_(rows - rows.min(), cols - cols.min())]


def reduce_cells(window, f, pool="mean"):
    """The mean (or with pool "max" the highest value) of f x f cells of a window whose shape is a multiple of f."""
    if f == 1:
        return window
    h, w = window.shape[0] // f, window.shape[1] // f
    shape = (h, f, w, f) + window.shape[2:]
    cells = window[:h * f, :w * f].reshape(shape)
    return cells.max(axis=(1, 3)) if pool == "max" else cells.mean(axis=(1, 3))


def sample_grid(array, u, v, px, order, value_dtype=np.float64, transform=None, separable=False, smooth_m=0.0, pool="mean"):
    """Sample a 1 m grid array at grid coordinates (u = column, v = row; arrays) for pixels of px metres.

    Fine pixels (px < 2 m) read the array directly; coarse ones first average f x f cells (f the
    largest power of two not above px, aligned to the global grid) and smooth with a Gaussian of
    half a pixel, so each pixel shows its area. ``order`` 3 is a cubic B-spline through the
    samples, 1 bilinear. ``transform`` maps the cropped window before filtering (a palette lookup).
    The window has margins wide enough that the result does not depend on the block it is cut for.
    ``separable``: u and v are the 1-D column and row coordinates of a pixel grid, the result is
    [len(v), len(u)] (see axis_weights); else u and v are point coordinates of any equal shape.
    ``smooth_m``: Gaussian of at least this many metres (softens class boundaries at fine zooms).
    ``pool`` "max": coarse pixels take the highest of their f x f cells, unsmoothed, so that a feature narrower than a pixel (a
    track) keeps its full value instead of fading into its surroundings.
    """
    f = 1 if px < 2 else 2 ** int(math.floor(math.log2(px)))
    sigma = max(0.0 if px < 2 or pool == "max" else 0.5 * px / f, smooth_m / f)
    pad = 16 + int(math.ceil(4 * sigma)) * f + 2 * f
    c0 = int(math.floor(np.min(u))) - pad
    c1 = int(math.ceil(np.max(u))) + pad + 1
    r0 = int(math.floor(np.min(v))) - pad
    r1 = int(math.ceil(np.max(v))) + pad + 1
    c0, r0 = c0 - c0 % f, r0 - r0 % f
    c1, r1 = c1 + (-c1) % f, r1 + (-r1) % f
    window = crop(array, r0, r1, c0, c1)
    window = (transform(window) if transform else window).astype(value_dtype)
    window = reduce_cells(window, f, pool)
    cu = (u - c0 - (f - 1) / 2) / f
    cv = (v - r0 - (f - 1) / 2) / f
    channels = window.shape[2:] and range(window.shape[2])
    planes = [window[..., i] for i in channels] if channels else [window]
    if separable:
        rows, cols = axis_weights(cv, window.shape[0], order), axis_weights(cu, window.shape[1], order)
    out = []
    for plane in planes:
        if sigma:
            plane = ndimage.gaussian_filter(plane, sigma, mode="nearest", truncate=4.0)
        if order == 3:
            plane = ndimage.spline_filter(plane, order=3, mode="mirror")
        if separable:
            out.append(rows @ (cols @ plane.T).T)
        else:
            out.append(ndimage.map_coordinates(plane, [cv, cu], order=order, prefilter=False, mode="nearest"))
    return np.stack(out, axis=-1) if channels else out[0]


def axis_weights(coords, n, order):
    """Sparse [len(coords), n] matrix of interpolation weights along one axis, indices clamped to the window.

    order 0: nearest sample; 1: linear; 3: cubic B-spline basis (of spline_filter coefficients). On a
    pixel grid the column coordinate depends only on x and the row only on y, so a 2-D sample is
    rows @ window @ cols.T, the same values as ndimage.map_coordinates at a fraction of its cost.
    """
    c = np.asarray(coords, np.float64)
    if order == 0:
        taps = np.floor(c + 0.5).astype(np.int64)[:, None]
        weights = np.ones_like(taps, np.float64)
    else:
        base = np.floor(c).astype(np.int64)
        t = (c - base)[:, None]
        if order == 1:
            taps = base[:, None] + np.arange(2)
            weights = np.concatenate([1 - t, t], axis=1)
        else:
            taps = base[:, None] + np.arange(-1, 3)
            weights = np.concatenate([(1 - t) ** 3, 3 * t ** 3 - 6 * t ** 2 + 4, -3 * t ** 3 + 3 * t ** 2 + 3 * t + 1, t ** 3], axis=1) / 6
    rows = np.repeat(np.arange(len(c)), taps.shape[1])
    return sparse.csr_matrix((weights.ravel(), (rows, np.clip(taps, 0, n - 1).ravel())), shape=(len(c), n))


class Frame:
    """Pixel geometry of a block: global pixel window at a zoom and its world coordinates."""

    def __init__(self, d, z, gx0, gy0, width, height):
        self.z = z
        self.gx0, self.gy0, self.width, self.height = gx0, gy0, width, height
        self.px_x = d["size_x"] / (TILE * 2 ** z)
        self.px_y = d["size_y"] / (TILE * 2 ** z)
        self.px = self.px_x
        self.min_x, self.min_y = d["min_x"], d["min_y"]
        i = np.arange(width)
        j = np.arange(height)
        self.u = (gx0 + i + 0.5) * self.px_x  # metres east of min_x == 1 m grid column
        self.v = (gy0 + j + 0.5) * self.px_y  # metres south of min_y == 1 m grid row

    def to_px(self, x, y):
        """Block pixel coordinates (float, pixel centres at .5) of world points."""
        return ((np.asarray(x) - self.min_x) / self.px_x - self.gx0, (np.asarray(y) - self.min_y) / self.px_y - self.gy0)

    def world_box(self, pad_px=0):
        return (self.min_x + (self.gx0 - pad_px) * self.px_x, self.min_y + (self.gy0 - pad_px) * self.px_y,
                self.min_x + (self.gx0 + self.width + pad_px) * self.px_x, self.min_y + (self.gy0 + self.height + pad_px) * self.px_y)


def ground_light(sx, sy):
    """Illumination [H, W] of ground of slopes sx (east) and sy (south, image axes): the MDOW of RELIEF_AZIMUTHS, or LIGHT's
    alone without MULTIDIRECTIONAL_RELIEF. Flat ground gets LIGHT[2] either way.

    MDOW = sum(w HS) / sum(w) with HS the hillshade of each light (clipped at 0) and w = sin^2(aspect - azimuth), aspect the
    bearing of the downhill direction; for four bearings 45 degrees apart the weights always sum to 2.
    """
    normal_z = 1 / np.sqrt(1 + sx * sx + sy * sy)
    if not MULTIDIRECTIONAL_RELIEF:
        return (-sx * LIGHT[0] - sy * LIGHT[1] + LIGHT[2]) * normal_z
    horizontal = math.hypot(LIGHT[0], LIGHT[1])
    aspect = np.arctan2(-sx, sy)
    total = np.zeros(sx.shape, np.float64)
    for azimuth in np.radians(RELIEF_AZIMUTHS):
        towards_x, towards_y = math.sin(azimuth) * horizontal, -math.cos(azimuth) * horizontal
        shade = np.maximum((-sx * towards_x - sy * towards_y + LIGHT[2]) * normal_z, 0)
        total += np.sin(aspect - azimuth) ** 2 * shade
    return total / 2


def contour_intervals(d, px):
    """(minor, major) contour interval in metres at a pixel size: minor lines about 6 px apart on the
    map's typical (80th percentile) slope, never finer than the map's finest interval."""
    need = 6 * px * d["relief_slope"]
    minor = next((step for step in CONTOUR_LADDER if step >= max(need, d["minor_finest"])), CONTOUR_LADDER[-1])
    return minor, MAJOR[minor]


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def nonzero_box(alpha, pad=0):
    """(rows, cols) slices of the bounding box of alpha > 0 grown by pad, or None when alpha is all 0."""
    rows = np.flatnonzero(alpha.any(1))
    if not len(rows):
        return None
    cols = np.flatnonzero(alpha.any(0))
    return (slice(max(0, rows[0] - pad), rows[-1] + pad + 1), slice(max(0, cols[0] - pad), cols[-1] + pad + 1))


def blend(rgb, colour, alpha):
    """In-place alpha blend of a colour (rgb tuple or [H, W, 3]) over rgb [H, W, 3] with alpha [H, W]."""
    box = nonzero_box(alpha)
    if box is None:
        return
    a = alpha[box][..., None]
    target = rgb[box]
    colour = np.asarray(colour, np.float32)
    target *= 1 - a
    target += a * (colour[box] if colour.ndim == 3 else colour)


def supersampled_mask(frame, draw_fn, factor=2):
    """Anti-aliased coverage [H, W] in 0..1 of shapes drawn by draw_fn(draw, scale) on a finer canvas."""
    canvas = Image.new("L", (frame.width * factor, frame.height * factor), 0)
    draw_fn(ImageDraw.Draw(canvas), factor)
    return downsample(canvas, frame)


def downsample(canvas, frame):
    """Coverage [H, W] in 0..1 of a supersampled "L" canvas, by box averaging (PIL, in C)."""
    return np.asarray(canvas.resize((frame.width, frame.height), Image.BOX), np.float32) / 255


def water_surfaces(d, box):
    """[(height above the map's lowest point, polygon [n, 2] in world metres)] of the flat water surfaces that reach into a world
    box: the static water planes and the lakes. Rivers are no planes: see water_top_at."""
    surfaces = []
    for plane in d["planes"]:
        b = plane["box"]
        if b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3]:
            continue
        surfaces.append((plane["z"], np.asarray(plane["polygon"])))
    return surfaces


def water_top_at(d, u, v):
    """Height of the scene's river and pond meshes (top_water_surface.npy, scene_prep.river_surface) at points (u, v: metres east
    and south of the map's corner, arrays of one shape): the nearest sample of the 1 m grid, far below any ground where no mesh lies."""
    grid = d["water_top"]
    rows = np.clip(np.floor(v + 0.5).astype(np.int64), 0, grid.shape[0] - 1)
    cols = np.clip(np.floor(u + 0.5).astype(np.int64), 0, grid.shape[1] - 1)
    r0, c0 = int(rows.min()), int(cols.min())
    return np.asarray(grid[r0:int(rows.max()) + 1, c0:int(cols.max()) + 1])[rows - r0, cols - c0]


def in_polygon(polygon, x, y):
    """Bool array: whether the points (x, y arrays) lie in a polygon [n, 2] (even-odd rule)."""
    inside = np.zeros(np.shape(x), bool)
    for (x0, y0), (x1, y1) in zip(polygon, np.roll(polygon, -1, axis=0)):
        if y0 == y1:
            continue
        crosses = ((y0 > y) != (y1 > y)) & (x < (x1 - x0) * (y - y0) / (y1 - y0) + x0)
        inside ^= crosses
    return inside


def under_water(d, x, y, h):
    """Bool array: whether the ground of height h at the world points (x, y arrays) lies below the sea or a water surface."""
    level = np.maximum(-np.inf if d["sea"] is None else d["sea"], water_top_at(d, x - d["min_x"], y - d["min_y"]).astype(np.float64))
    box = (float(np.min(x)), float(np.min(y)), float(np.max(x)), float(np.max(y)))
    for z, polygon in water_surfaces(d, box):
        level = np.where(in_polygon(polygon, x, y), np.maximum(level, z), level)
    return level > h


def draw_water(d, frame, h, rgb):
    """Water wherever the ground lies below a water surface: the sea (ocean actors' level), static water planes, lakes and the
    scene's river and pond meshes (a river mesh is laid bank to bank and the banks rise above it; a pixel coarser than its 1 m
    grid takes the highest of its cells, so a stream stays a line at the overview zooms). Returns the water coverage [H, W]."""
    surfaces = water_surfaces(d, frame.world_box(4))
    level = np.maximum(-np.inf if d["sea"] is None else d["sea"],
                       sample_grid(d["water_top"], frame.u, frame.v, frame.px, 0, np.float32, separable=True, pool="max")).astype(np.float32)
    if surfaces:
        # Painter's order: the higher surface wins where two overlap
        canvas = Image.new("F", (frame.width, frame.height), -1e9)
        draw = ImageDraw.Draw(canvas)
        for z, polygon in sorted(surfaces, key=lambda item: item[0]):
            px, py = frame.to_px(polygon[:, 0], polygon[:, 1])
            draw.polygon(list(zip(px.tolist(), py.tolist())), fill=z)
        level = np.maximum(level, np.asarray(canvas, np.float32))
    depth = np.maximum(level - h, -SHORE_DRY_M)
    # The shore is where the surface meets the ground: smoothed over SHORE_SMOOTH_M so that it is a clean curve at fine zooms
    sigma = min(6.0, SHORE_SMOOTH_M / frame.px)
    if sigma >= 0.4:
        depth = ndimage.gaussian_filter(depth, sigma)
    water = smoothstep(-0.05, 0.15, depth)
    if not water.any():
        return np.zeros(h.shape, np.float32)
    deep = np.sqrt(np.clip(depth / WATER_DEEP_M, 0.0, 1.0))[..., None]
    if d.get("trace") is not None:
        d["trace"]["deep"] = deep[..., 0]
    field = field_colour(d, "water", frame)
    if field is None:
        colour, shore = WATER_RGB * (1 - deep) + WATER_DEEP_RGB * deep, SHORE_RGB
    else:
        # The field is the colour of shallow water; the deep and shore colours keep the style's ratios to it
        colour, shore = field * (1 - deep + deep * WATER_DEEP_RGB / WATER_RGB), field * (SHORE_RGB / WATER_RGB)
    blend(rgb, colour, water)
    blend(rgb, shore, shore_line(water) * (0.75 if frame.px < 2 else 0.45))
    return water


def shore_line(water):
    """Alpha [H, W] of the shore: the level line where the water's cover [H, W] is a half, SHORE_LINE_PX wide whatever the width of
    the cover's ramp (at the finest zooms the ramp is several pixels and its max-min rim was a faint band)."""
    gy, gx = np.gradient(water)
    distance = np.abs(water - 0.5) / (np.hypot(gx, gy) + 1e-6)
    return np.clip(SHORE_LINE_PX / 2 + 0.5 - distance, 0, 1) * (np.hypot(gx, gy) > 1e-3)


def polygon_mask(frame, lines, box, min_width_px):
    """Coverage of spline segments' left-right ribbons; narrower than min_width_px they are drawn as
    centre lines of that width so a track stays visible at small scales."""
    def draw(canvas, s):
        for line in lines:
            b = line["box"]
            if b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3]:
                continue
            lx, ly = frame.to_px(line["left"][:, 0], line["left"][:, 1])
            rx, ry = frame.to_px(line["right"][:, 0], line["right"][:, 1])
            width_px = float(np.median(np.hypot(lx - rx, ly - ry)))
            if width_px < min_width_px:
                cx, cy = frame.to_px(line["center"][:, 0], line["center"][:, 1])
                canvas.line([(x * s, y * s) for x, y in zip(cx, cy)], fill=255, width=max(1, int(round(min_width_px * s))), joint="curve")
                continue
            for k in range(len(lx) - 1):
                canvas.polygon([(lx[k] * s, ly[k] * s), (rx[k] * s, ry[k] * s), (rx[k + 1] * s, ry[k + 1] * s), (lx[k + 1] * s, ly[k + 1] * s)], fill=255)
    return supersampled_mask(frame, draw)


def draw_crops(d, frame, rgb, water):
    """Crop fields: a tint from the low crops' colour to the tall crops' by their height, and a diagonal hatch in the global pixel
    grid of the zoom (so that it runs on across tiles) at the finer zooms. Not drawn in a style with ground colour fields (the
    game's texture shows the fields there)."""
    if "ground" in d["fields"]:
        return
    cover = sample_grid(d["crops"][..., 0], frame.u, frame.v, frame.px, 1, np.float32, separable=True) / 255
    if cover.max() < CROP_EDGE[0]:
        return
    height = sample_grid(d["crops"][..., 1], frame.u, frame.v, frame.px, 1, np.float32, separable=True) / 10
    (low_m, low_rgb), (tall_m, tall_rgb) = CROP_RGB
    t = np.clip((height - low_m) / (tall_m - low_m), 0, 1)[..., None]
    colour = np.array(low_rgb, np.float32) * (1 - t) + np.array(tall_rgb, np.float32) * t
    alpha = smoothstep(*CROP_EDGE, cover) * (1 - water)
    blend(rgb, colour, alpha * CROP_ALPHA)
    if frame.px <= CROP_HATCH_MAX_M:
        gx = frame.gx0 + np.arange(frame.width, dtype=np.float32)
        gy = frame.gy0 + np.arange(frame.height, dtype=np.float32)
        along = (gx[None, :] + gy[:, None]) / math.sqrt(2)
        distance = np.abs((along / CROP_HATCH_PX) % 1 - 0.5) * CROP_HATCH_PX
        line = np.clip(1.0 - distance, 0, 1)
        blend(rgb, colour * 0.78, line * alpha * 0.6)


def draw_painted_tracks(d, frame, rgb, water):
    """Tracks painted into the landscape (landscape_paths): the dirt track's colour where the path layers weigh half and more,
    with an edge a pixel wide; the road field colours them like the dirt splines. Pixels coarser than a track take its highest
    weight, so that a footpath stays a line a pixel wide at the overview zooms instead of averaging away."""
    weight = sample_grid(d["paths"], frame.u, frame.v, frame.px, 1, np.float32, separable=True, pool="max") / 255
    if weight.max() < PAINTED_TRACK_EDGE[0]:
        return
    alpha = smoothstep(*PAINTED_TRACK_EDGE, weight)
    fill_rgb = SPLINE_STYLE["dirt"][0]
    field = field_colour(d, "road", frame)
    blend(rgb, fill_rgb if field is None else field, alpha * 0.75 * (1 - water * 0.5))


def draw_splines(d, frame, rgb, water):
    box = frame.world_box(8)
    for cls in SPLINE_ORDER:
        lines = [line for line in d["lines"] if line["cls"] == cls]
        if not lines:
            continue
        fill_rgb, casing_rgb, min_width = SPLINE_STYLE[cls]
        field = field_colour(d, "road", frame) if cls in ROAD_CLASSES else None
        if field is not None:
            fill_rgb = field
            casing_rgb = None if casing_rgb is None else field * 0.7
        mask = polygon_mask(frame, lines, box, min_width)
        if not mask.any():
            continue
        if d.get("trace") is not None:
            d["trace"]["splines"][cls] = mask
        if casing_rgb is not None and frame.px < 4:
            grown = ndimage.grey_dilation(mask, size=(3, 3))
            blend(rgb, casing_rgb, np.clip(grown - mask, 0, 1) * CASING_ALPHA.get(cls, CASING_ALPHA_DEFAULT) * (1 - water))
        blend(rgb, fill_rgb, mask * (0.92 if cls != "dirt" else 0.75) * (1 - water * 0.5))
        if cls == "rail" and frame.px <= RAIL_TIE_MAX_PX_M:
            blend(rgb, fill_rgb, rail_ties(frame, lines, box, min_width) * 0.92)


def rail_ties(frame, lines, box, min_width_px):
    """Coverage [H, W] of the cross ties of railway splines: a tick across the track every RAIL_TIE_M metres of each segment's
    centre line (counted from its start, so every block draws the same ticks), RAIL_TIE_REACH line widths to each side."""
    def draw(canvas, s):
        for line in lines:
            b = line["box"]
            if b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3]:
                continue
            centre = line["center"][:, :2]
            along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(centre, axis=0).T))])
            width_m = float(np.median(np.hypot(*(line["left"][:, :2] - line["right"][:, :2]).T)))
            reach = RAIL_TIE_REACH * max(width_m, min_width_px * frame.px)
            for at in np.arange(RAIL_TIE_M / 2, along[-1], RAIL_TIE_M):
                k = min(int(np.searchsorted(along, at, side="right")) - 1, len(centre) - 2)
                direction = (centre[k + 1] - centre[k]) / max(along[k + 1] - along[k], 1e-9)
                point = centre[k] + direction * (at - along[k])
                normal = np.array([-direction[1], direction[0]]) * reach
                (x0, x1), (y0, y1) = frame.to_px(*np.stack([point - normal, point + normal], 1))
                canvas.line([(x0 * s, y0 * s), (x1 * s, y1 * s)], fill=255, width=max(1, int(round(max(0.5 / frame.px, 1.0) * s))))
    return supersampled_mask(frame, draw)


def contour_alpha(h, gx, gy, interval, width):
    """Anti-aliased alpha of lines where h crosses multiples of interval: distance to the level in
    pixels is |h - level| / |grad h| (h in metres, gradient in metres per pixel)."""
    grad = np.hypot(gx, gy) + 1e-6
    level = np.round(h / interval) * interval
    dist = np.abs(h - level) / grad
    alpha = np.clip(width / 2 + 0.5 - dist, 0, 1)
    spacing = interval / grad
    return alpha * smoothstep(1.5, 3.5, spacing), level


def text_patch(text, font, angle, fill, halo, halo_width):
    """RGBA image of a text with a halo, rotated by angle (degrees, counter-clockwise) about its centre."""
    left, top, right, bottom = font.getbbox(text, stroke_width=halo_width)
    image = Image.new("RGBA", (right - left + 4, bottom - top + 4), (0, 0, 0, 0))
    ImageDraw.Draw(image).text((2 - left, 2 - top), text, font=font, fill=fill + (255,), stroke_width=halo_width,
                               stroke_fill=halo + (200,))
    return image.rotate(angle, resample=Image.BICUBIC, expand=True) if angle else image


def paste(canvas, patch, cx, cy):
    canvas.alpha_composite(patch, (int(round(cx - patch.width / 2)), int(round(cy - patch.height / 2))))


def contour_labels(d, frame, minor, major):
    """Major contour labels whose boxes reach into the block: [(x px, y px, angle deg, text, half length)].

    Candidates come from fixed cells of LABEL_CELL pixels of the global pixel grid at this zoom: in
    each cell, the lattice point closest to a major contour where the lines are far enough apart
    for a label, moved onto the contour. The choice depends only on the cell, so every block that
    sees a label draws the same one. Cells, text and spacings grow with label_scale, so a label takes the same share of the screen.
    """
    scale = label_scale(d, frame.z)
    cell_px, step_px = LABEL_CELL * scale, LABEL_STEP * scale
    font = label_font(d, "contour", scale)
    reach = cell_px // 2
    gx_lo = (frame.gx0 - reach) // cell_px
    gx_hi = (frame.gx0 + frame.width + reach) // cell_px
    gy_lo = (frame.gy0 - reach) // cell_px
    gy_hi = (frame.gy0 + frame.height + reach) // cell_px
    full = TILE * 2 ** frame.z
    inset = 48 * scale
    offsets = np.arange(inset, cell_px - inset, step_px) + 0.5
    labels = []
    for cy in range(gy_lo, gy_hi + 1):
        for cx in range(gx_lo, gx_hi + 1):
            if cx < 0 or cy < 0 or cx * cell_px >= full or cy * cell_px >= full:
                continue
            pxs, pys = np.meshgrid(cx * cell_px + offsets, cy * cell_px + offsets)
            u = pxs * frame.px_x
            v = pys * frame.px_y
            stack_u = np.stack([u, u + 0.5 * frame.px_x, u - 0.5 * frame.px_x, u, u])
            stack_v = np.stack([v, v, v, v + 0.5 * frame.px_y, v - 0.5 * frame.px_y])
            hs = sample_grid(d["ground"], stack_u, stack_v, frame.px, 3)
            h = hs[0]
            gx = hs[1] - hs[2]
            gy = hs[3] - hs[4]
            grad = np.hypot(gx, gy) + 1e-9
            level = np.round(h / major) * major
            dist = np.abs(h - level) / grad
            ok = (dist < step_px * 0.75) & (minor / grad >= 7 * scale) & (major / grad >= 28 * scale) & (grad > 1e-4)
            if frame.px <= 1:
                ok &= ~objects_near(d, u, v, LABEL_HALF_PX * scale * frame.px)
            if d["sea"] is not None:
                ok &= level > d["sea"] + 0.5
            if ok.any():
                # a label names ground a player can stand on: none on a lake or river (the contours run on under the water) nor
                # beyond the landscape
                ok &= ~under_water(d, d["min_x"] + u, d["min_y"] + v, h) & ~outside_landscape(d, u, v)
            if not ok.any():
                continue
            centre = (cell_px - 1) / 2
            score = np.where(ok, dist + 0.02 * np.hypot(pxs - cx * cell_px - centre, pys - cy * cell_px - centre), np.inf)
            k = np.unravel_index(np.argmin(score), score.shape)
            g = np.array([gx[k], gy[k]]) / grad[k]
            shift = (h[k] - level[k]) / grad[k]
            x = pxs[k] - shift * g[0]
            y = pys[k] - shift * g[1]
            angle = math.degrees(math.atan2(g[0], -g[1]))
            if angle > 90:
                angle -= 180
            elif angle < -90:
                angle += 180
            text = f"{level[k]:.0f}"
            half = font.getlength(text) / 2 + 3 * scale
            labels.append((x - frame.gx0, y - frame.gy0, angle, text, half))
    return labels


def outside_landscape(d, u, v):
    """Bool array: whether the points (u, v: metres east and south of the map's corner) lie beyond the game's landscape."""
    cover = d["cover"]
    rows = np.clip(np.floor(v).astype(np.int64), 0, cover.shape[0] - 1)
    cols = np.clip(np.floor(u).astype(np.int64), 0, cover.shape[1] - 1)
    r0, c0 = int(rows.min()), int(cols.min())
    return np.asarray(cover[r0:int(rows.max()) + 1, c0:int(cols.max()) + 1])[rows - r0, cols - c0] == features.NO_COVER


def objects_near(d, u, v, radius_m):
    """Whether an object (0.3 m or taller) lies within radius_m of each point (u, v in m), on pyramid level NEAR_LEVEL."""
    cell = OBJECT_CELL_M * 2 ** NEAR_LEVEL
    r = int(math.ceil(radius_m / cell))
    cols = np.floor(u / cell).astype(np.int64)
    rows = np.floor(v / cell).astype(np.int64)
    c0, r0 = int(cols.min()) - r, int(rows.min()) - r
    window = crop(d["obj"][("v", NEAR_LEVEL)], r0, int(rows.max()) + r + 1, c0, int(cols.max()) + r + 1) >= 128
    if not window.any():
        return np.zeros(u.shape, bool)
    busy = ndimage.maximum_filter(window, size=2 * r + 1)
    return busy[rows - r0, cols - c0]


def any_overlap(label, boxes, frame, scale):
    """Whether a contour label (x, y in block pixels, angle, text, half length) touches a roof label box (global pixels)."""
    x, y, _, _, half = label
    gx, gy = x + frame.gx0, y + frame.gy0
    reach = half + LABEL_HALF_PX * scale
    return any(b[0] < gx + reach and b[2] > gx - reach and b[1] < gy + reach and b[3] > gy - reach for b in boxes)


def knockout(alpha, labels, half_height):
    """Clear the contour alpha under each label's rotated box."""
    for x, y, angle, _, half in labels:
        r = int(math.ceil(half + half_height)) + 1
        x0, y0 = max(0, int(math.floor(x)) - r), max(0, int(math.floor(y)) - r)
        x1, y1 = min(alpha.shape[1], int(math.floor(x)) + r + 1), min(alpha.shape[0], int(math.floor(y)) + r + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        ys, xs = np.mgrid[y0:y1, x0:x1]
        theta = math.radians(-angle)
        dx, dy = xs + 0.5 - x, ys + 0.5 - y
        along = dx * math.cos(theta) + dy * math.sin(theta)
        across = -dx * math.sin(theta) + dy * math.cos(theta)
        inside = (np.abs(along) <= half) & (np.abs(across) <= half_height)
        alpha[ys[inside], xs[inside]] = 0


def crown_stamp_image(stamp, size_px, yaw):
    """Coverage and height share [h, w] (0..1 float32 each) of a crown stamp scaled to size_px across and turned by yaw (degrees).

    The stamp spans the mesh's reach on each side of its pivot, so size_px is twice the instance's crown radius in pixels.
    """
    image = Image.fromarray(stamp, "LA").rotate(-yaw, resample=Image.BICUBIC, expand=True)
    scale = size_px / stamp.shape[0]
    size = (max(1, int(round(image.width * scale))), max(1, int(round(image.height * scale))))
    scaled = np.asarray(image.resize(size, Image.BILINEAR if scale >= 1 else Image.BOX), np.float32) / 255
    return scaled[..., 0], scaled[..., 1]


def crown_light(cover, height, crown_height_px, outline):
    """(shade [h, w], rim [h, w] 0..1 or None) of a crown stamp: its surface shaded by the map's light, brighter towards the top,
    and, with ``outline``, the rim where its cover falls off."""
    gy, gx = np.gradient(height * crown_height_px)
    normal_z = 1 / np.sqrt(1 + gx * gx + gy * gy)
    lam = (-gx * LIGHT[0] - gy * LIGHT[1] + LIGHT[2]) * normal_z
    shade = np.clip(1 + 0.9 * (lam - LIGHT[2]), 0.62, 1.22) * (0.84 + 0.2 * height)
    rim = np.clip(cover - ndimage.minimum_filter(cover, 3), 0, 1) * 0.7 if outline else None
    return shade, rim


def crown_colour(shade, rim, base_rgb, line_rgb):
    """Colour [h, w, 3] of a lit crown (crown_light) of a base colour, its rim in the line colour."""
    colour = np.clip(np.asarray(base_rgb, np.float32) * shade[..., None], 0, 255)
    if rim is None:
        return colour
    return colour * (1 - rim[..., None]) + np.asarray(line_rgb, np.float32) * rim[..., None]


def crown_sprite(d, mesh, size_px, yaw, crown_height_px, outline):
    """(cover, shade, rim) of a small crown (at most CROWN_SPRITE_MAX_PX across) from the worker's cache: the stamp turned, scaled
    and lit at the nearest steps of CROWN_SPRITE_YAW_DEG and CROWN_SPRITE_STEP_PX."""
    step = CROWN_SPRITE_STEP_PX
    key = (int(mesh), round(size_px / step), round(yaw / CROWN_SPRITE_YAW_DEG) % round(360 / CROWN_SPRITE_YAW_DEG), round(crown_height_px / step), outline)
    cache = d.setdefault("crown_sprites", {})
    if key not in cache:
        if len(cache) >= CROWN_SPRITE_CACHE:
            cache.clear()
        cover, relief = crown_stamp_image(d["stamps"][mesh], key[1] * step, key[2] * CROWN_SPRITE_YAW_DEG)
        cache[key] = (cover, *crown_light(cover, relief, key[3] * step, outline))
    return cache[key]


def draw_foliage(d, frame, rgb, water):
    """Trees, bushes, palms and rocks as the top-down outlines of their real meshes at their real size, turned and scaled with
    each instance, lit from the map's light; forest density where crowns are smaller than a pixel."""
    f = d["foliage"]
    if not len(f["x"]):
        return
    box = frame.world_box(MARGIN)
    near = (f["x"] + f["radius"] >= box[0]) & (f["x"] - f["radius"] <= box[2]) & (f["y"] + f["radius"] >= box[1]) & (f["y"] - f["radius"] <= box[3])
    if not near.any():
        return
    x, y = frame.to_px(f["x"][near], f["y"][near])
    r = f["radius"][near] / frame.px
    height_m = f["height"][near]
    yaw = f["yaw"][near]
    cls = f["cls"][near]
    mesh = f["mesh"][near]
    trunk = f["collision"][near] & (cls != features.ROCK) & (cls != features.BUSH)
    keep = 1 - water
    # Crowns smaller than a pixel: their expected cover 1 - exp(-sum of crown areas in pixels)
    small = r < 0.9
    for c in FOLIAGE_ORDER:
        sel = small & (cls == c)
        if not sel.any():
            continue
        fill_rgb, fill_alpha, _ = FOLIAGE_STYLE[c]
        field = field_colour(d, FOLIAGE_GROUPS[c], frame) if c in FOLIAGE_GROUPS else None
        if field is not None:
            fill_rgb = field
        area = np.zeros(rgb.shape[:2], np.float64)
        xi, yi = np.floor(x[sel]).astype(np.int64), np.floor(y[sel]).astype(np.int64)
        ok = (xi >= 0) & (xi < area.shape[1]) & (yi >= 0) & (yi < area.shape[0])
        np.add.at(area, (yi[ok], xi[ok]), np.pi * r[sel][ok] ** 2)
        coverage = (1 - np.exp(-ndimage.gaussian_filter(area, 0.6))).astype(np.float32)
        if d.get("trace") is not None:
            d["trace"].setdefault("foliage", {})[c] = coverage
        blend(rgb, fill_rgb, coverage * fill_alpha * keep)
    # The others, one by one: low crowns first so that the higher ones lie over them
    large = np.flatnonzero(~small)
    layer = np.zeros(rgb.shape, np.float32)
    layer_alpha = np.zeros(rgb.shape[:2], np.float32)
    for i in large[np.argsort(height_m[large], kind="stable")]:
        c = int(cls[i])
        fill_rgb, fill_alpha, line_rgb = FOLIAGE_STYLE[c]
        field = field_colour(d, FOLIAGE_GROUPS[c], frame) if c in FOLIAGE_GROUPS else None
        species = d["species_rgb"].get(int(mesh[i]))
        stamp = d["stamps"][mesh[i]]
        size = 2 * r[i]
        if not stamp.any():
            continue
        outline = r[i] >= CROWN_OUTLINE_PX
        if size <= CROWN_SPRITE_MAX_PX:
            cover, shade, rim = crown_sprite(d, mesh[i], size, yaw[i], height_m[i] / frame.px, outline)
        else:
            cover, relief = crown_stamp_image(stamp, size, yaw[i])
            shade, rim = crown_light(cover, relief, height_m[i] / frame.px, outline)
        x0, y0 = int(round(x[i] - cover.shape[1] / 2)), int(round(y[i] - cover.shape[0] / 2))
        sx0, sy0 = max(0, -x0), max(0, -y0)
        sx1, sy1 = min(cover.shape[1], rgb.shape[1] - x0), min(cover.shape[0], rgb.shape[0] - y0)
        if sx1 <= sx0 or sy1 <= sy0:
            continue
        if field is not None:
            centre = field[int(np.clip(y[i], 0, rgb.shape[0] - 1)), int(np.clip(x[i], 0, rgb.shape[1] - 1))]
            base, line = centre, centre * 0.7
        else:
            base, line = species or fill_rgb, line_rgb
        window = (slice(y0 + sy0, y0 + sy1), slice(x0 + sx0, x0 + sx1))
        colour = crown_colour(shade[sy0:sy1, sx0:sx1], None if rim is None else rim[sy0:sy1, sx0:sx1], base, line)
        a = (cover[sy0:sy1, sx0:sx1] * fill_alpha * keep[window]).astype(np.float32)
        if d.get("trace") is not None:
            per_class = d["trace"].setdefault("foliage", {})
            per_class[c] = np.zeros(rgb.shape[:2], np.float32) if c not in per_class else per_class[c]
            per_class[c][window] = np.maximum(per_class[c][window], cover[sy0:sy1, sx0:sx1])
        layer[window] = layer[window] * (1 - a[..., None]) + colour * a[..., None]
        layer_alpha[window] = layer_alpha[window] * (1 - a) + a
    if layer_alpha.any():
        rgb *= (1 - layer_alpha)[..., None]
        rgb += layer
    if frame.px <= 0.6 and trunk.any():
        tr = np.maximum(0.25 / frame.px, 0.7)

        def draw(canvas, s):
            for cx, cy in zip(x[trunk], y[trunk]):
                canvas.ellipse((cx * s - tr * s, cy * s - tr * s, cx * s + tr * s, cy * s + tr * s), fill=255)
        blend(rgb, TRUNK_RGB, supersampled_mask(frame, draw, 4) * 0.9 * (1 - water))


def structure_colour(height_m):
    """Colour of structures by height above ground (piecewise linear STRUCTURE_RAMP)."""
    stops = np.array([s for s, _ in STRUCTURE_RAMP])
    colours = np.array([c for _, c in STRUCTURE_RAMP], np.float32)
    t = np.clip(height_m, stops[0], stops[-1])
    out = np.empty(t.shape + (3,), np.float32)
    for ch in range(3):
        out[..., ch] = np.interp(t, stops, colours[:, ch])
    return out


def visible_coverage(alpha, px):
    """Coverage [H, W] of objects as drawn at a pixel of px metres: see OBJECT_SOLID_PX_M."""
    gain = px / OBJECT_SOLID_PX_M
    return alpha if gain <= 1 else 1 - (1 - alpha) ** gain


def roof_contrast(colour, ground_luma):
    """Colours [.., 3] of structures with the ramp squeezed towards its darkest stop until its lightest roofs are ROOF_CONTRAST
    below the ground luma [..] around them (not at all where the ground is light enough already, at most down to ROOF_MIN_SCALE of the
    ramp's luma range). A colour keeps its hue: all three channels shift by the change of its luma."""
    stops = [float(np.dot(c, LUMA)) for _, c in STRUCTURE_RAMP]
    lightest, darkest = max(stops), min(stops)
    luma = colour @ LUMA
    squeeze = np.clip((ground_luma - ROOF_CONTRAST - darkest) / (lightest - darkest), ROOF_MIN_SCALE, 1.0)
    target = np.where(luma > darkest, darkest + (luma - darkest) * squeeze, luma)
    return np.clip(colour + (target - luma)[..., None], 0, 255)


def ground_luma_map(cover, palette, heights, coverage, cell_m):
    """Luma [rows, cols] of the ground on cells of cell_m metres (cell i covers [i, i + 1) * cell_m): the cover's palette colour
    at the cell's centre, with the cells an object covers (``heights`` and ``coverage`` of the pyramid level of that cell size) taken
    from the nearest cell that none covers, smoothed by one cell. A function of the map alone, so every block of tiles gives
    a roof the same reference however large the roof."""
    rows = np.clip(((np.arange(heights.shape[0]) + 0.5) * cell_m).astype(np.int64), 0, cover.shape[0] - 1)
    cols = np.clip(((np.arange(heights.shape[1]) + 0.5) * cell_m).astype(np.int64), 0, cover.shape[1] - 1)
    luma = (palette @ LUMA)[np.asarray(cover[rows[0]:rows[-1] + 1])[np.ix_(rows - rows[0], cols)]]
    covered = (np.asarray(heights) > 0) & (np.asarray(coverage) > 0)
    if covered.all():
        return luma.astype(np.float32)
    nearest = ndimage.distance_transform_edt(covered, return_distances=False, return_indices=True)
    return ndimage.gaussian_filter(luma[nearest[0], nearest[1]], 1.0, mode="nearest").astype(np.float32)


def cast_shadow(height, alpha, px, origin):
    """Shadow [H, W] in 0..1 of objects on the pixel grid: a pixel is shaded when an object that many steps towards the light is taller
    than the ray's height there (the light of the relief, from the north-west, at 60 degrees), up to SHADOW_REACH_M.

    The rays are marched on a grid of about 0.25 m (the maximum height of each group of pixels), then smoothed back to pixels:
    a shadow is a soft shape and a march over every pixel of a 0.08 m zoom would be 150 steps of the whole block.
    ``origin`` is the global pixel (x, y) of the arrays' first pixel: the groups are aligned to the global pixel grid, so
    that blocks cut at other places give the same shadow. Only objects at least SHADOW_MIN_CASTER_PX pixels wide cast one: a post or
    wire thinner than that is no more than a speck at this zoom, and a shadow must not appear without an object to explain it.
    """
    f = max(1, int(round(0.25 / px)))
    h, w = height.shape
    lead_y, lead_x = origin[1] % f, origin[0] % f
    ph, pw = (-(h + lead_y)) % f, (-(w + lead_x)) % f
    solid = alpha > 0.5
    solid = ndimage.binary_opening(solid, structure=np.ones((SHADOW_MIN_CASTER_PX, SHADOW_MIN_CASTER_PX), bool))
    casting = np.where(solid, height, 0)
    coarse = np.pad(casting, ((lead_y, ph), (lead_x, pw))).reshape((h + lead_y + ph) // f, f, (w + lead_x + pw) // f, f).max(axis=(1, 3))
    cell = px * f
    away = -LIGHT[:2] / math.hypot(LIGHT[0], LIGHT[1])
    major = float(np.abs(away).max())
    step_m = cell / major
    tan_elevation = SHADOW_TAN_ELEVATION
    shadow = np.zeros(coarse.shape, bool)
    for s in range(1, int(min(math.ceil(SHADOW_REACH_M / step_m), math.ceil(float(coarse.max()) / (tan_elevation * step_m)))) + 1):
        dx, dy = int(round(s * away[0] / major)), int(round(s * away[1] / major))
        shifted = np.zeros_like(coarse)
        shifted[max(dy, 0):coarse.shape[0] + min(dy, 0), max(dx, 0):coarse.shape[1] + min(dx, 0)] = \
            coarse[max(-dy, 0):coarse.shape[0] + min(-dy, 0), max(-dx, 0):coarse.shape[1] + min(-dx, 0)]
        shadow |= shifted > s * step_m * tan_elevation
    soft = ndimage.gaussian_filter(shadow.astype(np.float32), 0.7)
    full = np.asarray(Image.fromarray(soft).resize((w + lead_x + pw, h + lead_y + ph), Image.BILINEAR), np.float32)
    return full[lead_y:lead_y + h, lead_x:lead_x + w]


def draw_objects(d, frame, rgb, water):
    """Objects of the scene (buildings, walls, rocks, props, bridges) seen from above: coloured by class and height above ground,
    roofs shaded by the slope of their top so ridges and levels show, a 1 px outline, and shadows cast to the south-east.

    The shading and the height steps of the outline follow the top itself (ground + height), and a structure's colour its height
    over the smoothed ground (top_ground_base.npy, scene_prep.GROUND_BASE_SIGMA_M): a flat deck or roof over uneven ground stays flat, the ground's relief does not
    show through it. The ground added back is bilinear between the 1 m samples, as scene_objects.ground_on_grid measured the heights
    from (the cubic ground of the relief rounds a jetty's edge off and would leave a ridge along it on the deck above).
    """
    k = int(np.clip(math.floor(math.log2(max(frame.px, OBJECT_CELL_M) / OBJECT_CELL_M)), 0, d["levels"]))
    cell = OBJECT_CELL_M * 2 ** k
    # Level k cell i covers [i, i + 1) * cell: its centre is (i + 0.5) * cell
    ui = frame.u / cell - 0.5
    vi = frame.v / cell - 0.5
    c0, c1 = int(math.floor(ui.min())) - 2, int(math.ceil(ui.max())) + 3
    r0, r1 = int(math.floor(vi.min())) - 2, int(math.ceil(vi.max())) + 3
    h_win = crop(d["obj"][("h", k)], r0, r1, c0, c1)
    if not h_win.any():
        return
    c_win = crop(d["obj"][("c", k)], r0, r1, c0, c1)
    v_win = crop(d["obj"][("v", k)], r0, r1, c0, c1).astype(np.float32) / 255
    rows, cols = axis_weights(vi - r0, v_win.shape[0], 1), axis_weights(ui - c0, v_win.shape[1], 1)
    sample = lambda window: (rows @ (cols @ window.T).T).astype(np.float32)
    weight = sample(v_win)
    # Height weighted by coverage, so that the rim of a roof keeps the roof's height and not its mix with the ground
    height = sample(h_win.astype(np.float32) / 100 * v_win) / np.maximum(weight, 1e-3)
    near_u = np.clip(np.rint(ui - c0).astype(np.int64), 0, h_win.shape[1] - 1)
    near_v = np.clip(np.rint(vi - r0).astype(np.int64), 0, h_win.shape[0] - 1)
    cls = c_win[np.ix_(near_v, near_u)]
    alpha = visible_coverage(np.clip(weight, 0, 1), frame.px)
    if d.get("trace") is not None:
        d["trace"]["objects"] = (alpha, height, cls)
    reach = int(math.ceil(SHADOW_REACH_M / frame.px))
    box = nonzero_box(alpha, reach)
    if box is None:
        return
    field = field_colour(d, "object", frame)
    alpha, height, cls, water, rgb = alpha[box], height[box], cls[box], water[box], rgb[box]
    ground = sample_grid(d["ground"], frame.u[box[1]], frame.v[box[0]], frame.px, 1, np.float32, separable=True)
    shadow = cast_shadow(height, alpha, frame.px, (frame.gx0 + box[1].start, frame.gy0 + box[0].start)) * (1 - alpha)
    if d.get("trace") is not None:
        full = np.zeros(d["trace"]["objects"][0].shape, np.float32)
        full[box] = shadow
        d["trace"]["shadow"] = full
    rgb *= (1 - shadow * (1 - SHADOW_FACTOR) * (1 - water))[..., None]
    top = height + ground
    if field is None:
        base = sample_grid(d["ground_base"], frame.u, frame.v, frame.px, 1, np.float32, separable=True)[box]
        colour = structure_colour(np.where(height > 0, top - base, 0))
        cell = OBJECT_CELL_M * 2 ** d["ground_luma_level"]
        luma = sample_grid(d["ground_luma"], frame.u / cell - 0.5, frame.v / cell - 0.5, frame.px / cell, 1, np.float32, separable=True)[box]
        colour = roof_contrast(colour, luma)
        for c, value in OBJECT_RGB.items():
            colour[cls == c] = value
        paved = (cls == features.BRIDGE) & (height < PAVED_MAX_M)
        colour[paved] = SPLINE_STYLE["pavement"][0]
    else:
        colour = field[box]
        paved = np.zeros(cls.shape, bool)
    # Roof relief: hillshade of the object's top over the pixel grid
    gy, gx = np.gradient(ndimage.gaussian_filter(top, 0.5))
    gx /= frame.px
    gy /= frame.px
    normal_z = 1 / np.sqrt(1 + gx * gx + gy * gy)
    lam = (-gx * LIGHT[0] - gy * LIGHT[1] + LIGHT[2]) * normal_z
    shade = np.clip(1 + 0.8 * (lam - LIGHT[2]), 0.55, 1.25)
    shade = np.where(np.isin(cls, (features.VEGETATION, features.BRIDGE)), np.clip(shade, 0.92, 1.08), shade)
    shade = np.where(paved, 1.0, shade)[..., None]
    blend(rgb, np.clip(colour * shade, 0, 255), alpha)
    # Outline: the rim of the footprint, 1 px wide at every zoom, and where a pixel is at most STEP_OUTLINE_PX_M metres the height
    # steps over STEP_OUTLINE_M inside it (at a wider pixel every cluster of objects is full of them)
    rim = np.clip(alpha - ndimage.minimum_filter(alpha, 3), 0, 1)
    strength = rim * alpha
    if frame.px <= STEP_OUTLINE_PX_M:
        hmax = ndimage.maximum_filter(np.where(alpha > 0.5, top, -np.inf), 3)
        hmin = ndimage.minimum_filter(np.where(alpha > 0.5, top, hmax), 3)
        step_edge = ((hmax - hmin) > STEP_OUTLINE_M).astype(np.float32) * (alpha > 0.5)
        strength = np.maximum(strength, step_edge * 0.55)
    line = np.broadcast_to(OUTLINE_RGB, rgb.shape).copy()
    for c, value in OUTLINE_BY_CLASS.items():
        line[cls == c] = value
    blend(rgb, line, np.clip(strength, 0, 1) * 0.85 * ~paved)


def roof_labels_of(d, frame):
    """Roof height labels placed on the pixel grid of this zoom: [(x px, y px, text)] in global pixels, never overlapping.

    Largest buildings first (deepest label point); a label is dropped when its box would touch one already placed. The text must
    fit inside the roof (the roof's depth, the distance of the label point to the roof's edge). Computed once per zoom.
    """
    cache = d["roof_cache"]
    if frame.z in cache:
        return cache[frame.z]
    scale = label_scale(d, frame.z)
    font = label_font(d, "roof", scale)
    placed, boxes = [], []
    cell = ROOF_LABEL_CELL
    taken = {}
    for label in sorted(d["labels"], key=lambda l: (-l["depth"], l["x"], l["y"])):
        gx = (label["x"] - d["min_x"]) / frame.px_x
        gy = (label["y"] - d["min_y"]) / frame.px_y
        text = f"{label['h']:.0f}m"
        half_w, half_h = font.getlength(text) / 2 + ROOF_LABEL_PAD * scale, ROOF_LABEL_HALF_HEIGHT * scale
        if label["depth"] / frame.px < half_w:
            continue
        box = (gx - half_w, gy - half_h, gx + half_w, gy + half_h)
        cells = [(i, j) for i in range(int(box[0] // cell) - 1, int(box[2] // cell) + 2) for j in range(int(box[1] // cell) - 1, int(box[3] // cell) + 2)]
        if any(other[0] < box[2] and other[2] > box[0] and other[1] < box[3] and other[3] > box[1] for ij in cells for other in taken.get(ij, ())):
            continue
        for ij in cells:
            taken.setdefault(ij, []).append(box)
        placed.append((gx, gy, text))
        boxes.append(box)
    cache[frame.z] = (placed, boxes)
    return cache[frame.z]


def roof_labels(d, frame, canvas):
    """Roof height above ground of the larger buildings, from the zoom before the first layer's finest on."""
    if frame.z < d["legacy_finest"] - 1:
        return
    scale = label_scale(d, frame.z)
    font = label_font(d, "roof", scale)
    placed, _ = roof_labels_of(d, frame)
    for gx, gy, text in placed:
        x, y = gx - frame.gx0, gy - frame.gy0
        if not (-MARGIN < x < frame.width + MARGIN and -MARGIN < y < frame.height + MARGIN):
            continue
        paste(canvas, text_patch(text, font, 0, LABEL_TEXT_RGB, HALO_RGB, LABEL_HALO_PX * scale), x, y)


def summits_of(d, frame):
    """Summit labels placed on the pixel grid of this zoom: ([(x px, y px, text)], [label boxes]) in global pixels, the highest rise
    first, none within SUMMIT_SPACING_PX (times label_scale) of one already placed, none on a roof label. Computed once per zoom."""
    cache = d["summit_cache"]
    if frame.z in cache:
        return cache[frame.z]
    scale = label_scale(d, frame.z)
    font = label_font(d, "contour", scale)
    spacing = SUMMIT_SPACING_PX * scale
    roofs = roof_labels_of(d, frame)[1] if frame.z >= d["legacy_finest"] - 1 else []
    placed, boxes, taken = [], [], {}
    for summit in d["summits"]:
        gx, gy = summit["u"] / frame.px_x, summit["v"] / frame.px_y
        cell = (int(gx // spacing), int(gy // spacing))
        near = [p for i in range(cell[0] - 1, cell[0] + 2) for j in range(cell[1] - 1, cell[1] + 2) for p in taken.get((i, j), ())]
        if any(math.hypot(gx - x, gy - y) < spacing for x, y in near):
            continue
        text = f"{summit['h']:.0f}"
        box = (gx - SUMMIT_DOT_PX * scale - 2, gy - ROOF_LABEL_HALF_HEIGHT * scale, gx + (SUMMIT_DOT_PX + 4) * scale + font.getlength(text), gy + ROOF_LABEL_HALF_HEIGHT * scale)
        if any(b[0] < box[2] and b[2] > box[0] and b[1] < box[3] and b[3] > box[1] for b in roofs):
            continue
        if frame.px <= 1 and objects_near(d, np.array([summit["u"]]), np.array([summit["v"]]), 2.0)[0]:
            continue
        taken.setdefault(cell, []).append((gx, gy))
        placed.append((gx, gy, text))
        boxes.append(box)
    cache[frame.z] = (placed, boxes)
    return cache[frame.z]


def summit_labels(d, frame, canvas):
    """The summits of summits_of in a block: a dot on the top and its height to the right."""
    scale = label_scale(d, frame.z)
    font = label_font(d, "contour", scale)
    draw = ImageDraw.Draw(canvas)
    radius = SUMMIT_DOT_PX * scale
    for gx, gy, text in summits_of(d, frame)[0]:
        x, y = gx - frame.gx0, gy - frame.gy0
        reach = radius + 6 * scale + font.getlength(text)
        if not (-reach < x < frame.width + reach and -reach < y < frame.height + reach):
            continue
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=SUMMIT_RGB + (255,), outline=HALO_RGB + (255,), width=max(1, scale))
        patch = text_patch(text, font, 0, SUMMIT_RGB, HALO_RGB, LABEL_HALO_PX * scale)
        paste(canvas, patch, x + radius + 2 * scale + patch.width / 2, y)


def block_margin(d, z):
    """Pixels around a block at zoom z that are rendered and discarded: at least MARGIN, and the longest shadow."""
    return max(MARGIN, int(math.ceil(SHADOW_REACH_M / (d["size_x"] / (TILE * 2 ** z)))) + 8)


def block_frame(d, z, bx, by):
    """Frame of block (bx, by) of BLOCK_TILES tiles at zoom z with its block_margin pixels around."""
    size = TILE * BLOCK_TILES
    full = TILE * 2 ** z
    margin = block_margin(d, z)
    width = min(size, full - bx * size) + 2 * margin
    height = min(size, full - by * size) + 2 * margin
    return Frame(d, z, bx * size - margin, by * size - margin, width, height)


def uniform_block_colour(d, frame):
    """RGB (uint8) of a block that render_block would draw in one colour, or None.

    That is open sea: under the default style (no colour fields, no grade) every ground sample within the frame's reach is
    UNIFORM_SEA_DEPTH_M or more below the sea level, so the water covers it fully in the deep colour and no contour label is
    placed, and nothing is drawn over the water there: no object (the coarsest level of the height pyramid, the highest of its
    cells), spline, crown or painted track.
    """
    if d["sea"] is None or d["fields"] or GRADE is not None:
        return None
    x0, y0, x1, y1 = frame.world_box(UNIFORM_REACH_PX)
    x0, y0, x1, y1 = x0 - UNIFORM_REACH_M, y0 - UNIFORM_REACH_M, x1 + UNIFORM_REACH_M, y1 + UNIFORM_REACH_M
    c0, r0 = int(math.floor(x0 - d["min_x"])), int(math.floor(y0 - d["min_y"]))
    c1, r1 = int(math.ceil(x1 - d["min_x"])) + 1, int(math.ceil(y1 - d["min_y"])) + 1
    if float(crop(d["ground"], r0, r1, c0, c1).max()) > d["sea"] - UNIFORM_SEA_DEPTH_M:
        return None
    if crop(d["paths"], r0, r1, c0, c1).any():
        return None
    level = d["levels"]
    cell = OBJECT_CELL_M * 2 ** level
    heights = d["obj"][("h", level)]
    if crop(heights, int(r0 // cell), int(r1 // cell) + 1, int(c0 // cell), int(c1 // cell) + 1).any():
        return None
    if any(line["box"][0] <= x1 and line["box"][2] >= x0 and line["box"][1] <= y1 and line["box"][3] >= y0 for line in d["lines"]):
        return None
    f = d["foliage"]
    if np.any((f["x"] + f["radius"] >= x0) & (f["x"] - f["radius"] <= x1) & (f["y"] + f["radius"] >= y0) & (f["y"] - f["radius"] <= y1)):
        return None
    return tuple(int(c) for c in np.clip(WATER_DEEP_RGB, 0, 255).astype(np.uint8))


def render_block(d, z, bx, by):
    """RGB image [H, W, 3] of block (bx, by) of BLOCK_TILES tiles at zoom z, with block_margin pixels around."""
    frame = block_frame(d, z, bx, by)
    px = frame.px

    h = sample_grid(d["ground"], frame.u, frame.v, px, 3, separable=True).astype(np.float32)
    gy, gx = np.gradient(h)  # metres per pixel
    slope = np.hypot(gx / frame.px_x, gy / frame.px_y)

    outside = sample_grid(d["cover"], frame.u, frame.v, px, 1, np.float32, transform=lambda w: (w == features.NO_COVER).astype(np.float32),
                          separable=True, smooth_m=0.7).astype(np.float32)
    # Material boundaries softened by 0.7 m (bilinear alone leaves diamond-shaped steps at fine zooms)
    rgb = field_colour(d, "ground", frame)
    if rgb is None:
        rgb = sample_grid(d["cover"], frame.u, frame.v, px, 1, np.float32, transform=lambda w: d["palette"][w],
                          separable=True, smooth_m=0.7).astype(np.float32)
        steep = smoothstep(0.6, 1.5, slope) * STEEP_ALPHA
        blend(rgb, STEEP_RGB, steep.astype(np.float32))
        blend(rgb, OUTSIDE_RGB, outside * OUTSIDE_ALPHA)

    exaggeration = 1.0 if px <= 2 else min(4.0, 1.0 + 0.5 * math.log2(px / 2) * 1.5)
    sx = gx / frame.px_x * exaggeration
    sy = gy / frame.px_y * exaggeration
    strength = SHADE_STRENGTH * (MDOW_CONTRAST if MULTIDIRECTIONAL_RELIEF else 1.0)
    shade = np.clip(1 + strength * (ground_light(sx, sy) - LIGHT[2]), 0.6, 1.18)
    shade = 1 + (shade - 1) * (1 - OUTSIDE_ALPHA * outside)
    rgb *= shade[..., None].astype(np.float32)
    trace = d.get("trace")
    if trace is not None:
        trace.clear()
        trace.update(splines={}, foliage={}, shade=shade, slope_x=gx / frame.px_x, slope_y=gy / frame.px_y)
        cols = np.clip(np.floor(frame.u).astype(np.int64), 0, d["cover"].shape[1] - 1)
        rows = np.clip(np.floor(frame.v).astype(np.int64), 0, d["cover"].shape[0] - 1)
        window = np.asarray(d["cover"][rows.min():rows.max() + 1, cols.min():cols.max() + 1])
        trace["cover"] = window[np.ix_(rows - rows.min(), cols - cols.min())]

    minor, major = contour_intervals(d, px)
    scale = label_scale(d, z)
    labels = contour_labels(d, frame, minor, major)
    taken_boxes = summits_of(d, frame)[1] + (roof_labels_of(d, frame)[1] if z >= d["legacy_finest"] - 1 else [])
    labels = [label for label in labels if not any_overlap(label, taken_boxes, frame, scale)]
    a_minor, level = contour_alpha(h, gx, gy, minor, (0.9 if px < 1 else 0.7) * scale)
    is_major = (np.abs(np.round(level / major) * major - level) < 1e-3)
    a_major, _ = contour_alpha(h, gx, gy, major, (1.5 if px < 4 else 1.1) * scale)
    a_minor = np.where(is_major, 0, a_minor) * CONTOUR_ALPHA[0]
    a_major *= CONTOUR_ALPHA[1]
    contours = np.maximum(a_minor, a_major) * (1 - outside)
    knockout(contours, labels, 7.0 * scale)
    blend(rgb, CONTOUR_RGB, contours.astype(np.float32))

    water = draw_water(d, frame, h, rgb)
    draw_crops(d, frame, rgb, water)
    draw_painted_tracks(d, frame, rgb, water)
    draw_splines(d, frame, rgb, water)
    draw_objects(d, frame, rgb, water)
    draw_foliage(d, frame, rgb, water)

    if trace is not None:
        trace.update(water=water, rgb=rgb.copy())
    if GRADE is not None:
        rgb = rgb * GRADE["gain"] + GRADE["offset"]
    canvas = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    font = label_font(d, "contour", scale)
    for x, y, angle, text, _ in labels:
        paste(canvas, text_patch(text, font, angle, CONTOUR_LABEL_RGB, HALO_RGB, LABEL_HALO_PX * scale), x, y)
    summit_labels(d, frame, canvas)
    roof_labels(d, frame, canvas)
    return canvas.convert("RGB")


def _init(slug, out_dir, style=None):
    if style:
        apply_style(style)
    _data.update(load(slug))
    _data["out"] = out_dir


def _render(task):
    """Render one block's tiles into d["out"]; returns the number of tiles. A block of one colour (uniform_block_colour) is not
    drawn: its tiles are hard links to one tile of that colour per zoom and worker, the bytes the drawing would give."""
    z, bx, by = task
    d = _data
    folder = os.path.join(d["out"], str(z))
    os.makedirs(folder, exist_ok=True)
    tiles = 2 ** z
    places = [(tx, ty) for ty in range(BLOCK_TILES) for tx in range(BLOCK_TILES)
              if bx * BLOCK_TILES + tx < tiles and by * BLOCK_TILES + ty < tiles]
    uniform = uniform_block_colour(d, block_frame(d, z, bx, by))
    if uniform is not None:
        shared = d.setdefault("uniform_tiles", {})
        for tx, ty in places:
            path = vacant(os.path.join(folder, f"{bx * BLOCK_TILES + tx}_{by * BLOCK_TILES + ty}.webp"))
            if (z, uniform) in shared:
                os.link(shared[(z, uniform)], path)
            else:
                Image.new("RGB", (TILE, TILE), uniform).save(path, "WEBP", quality=WEBP_QUALITY, method=4)
                shared[(z, uniform)] = path
        return len(places)
    image = render_block(d, z, bx, by)
    margin = block_margin(d, z)
    for tx, ty in places:
        left, top = margin + tx * TILE, margin + ty * TILE
        tile = image.crop((left, top, left + TILE, top + TILE))
        tile.save(vacant(os.path.join(folder, f"{bx * BLOCK_TILES + tx}_{by * BLOCK_TILES + ty}.webp")), "WEBP", quality=WEBP_QUALITY, method=4)
    return len(places)


def vacant(path):
    """path, with the tile a previous render left there removed (a render into a folder that holds tiles, --out): the tiles of a
    uniform block are hard links to one file, which writing over one of them would change for all."""
    if os.path.lexists(path):
        os.unlink(path)
    return path


def tasks_for(zooms, blocks=None):
    tasks = []
    for z in zooms:
        n = math.ceil(2 ** z / BLOCK_TILES)
        tasks += [(z, bx, by) for by in range(n) for bx in range(n)]
    if blocks:
        tasks = [t for t in tasks if t in blocks]
    return tasks


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("map")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--zooms", type=int, nargs="*")
    parser.add_argument("--blocks", nargs="*", help="only these blocks, as z/bx/by (a test render)")
    parser.add_argument("--style", help="style name: tools/maptiles/py/styles/<style>_<map>.json, tiles in /tiles/<map>-<style>")
    parser.add_argument("--out", help="output directory instead of /tiles/<map> (a test render)")
    args = parser.parse_args()
    slug = args.map
    meta = json.load(open(os.path.join(PREP_DIR, slug, "meta.json")))
    b = meta["bounds_m"]
    finest = finest_zoom(b["max_x"] - b["min_x"])
    zooms = args.zooms if args.zooms else list(range(finest, -1, -1))
    blocks = [tuple(int(v) for v in s.split("/")) for s in args.blocks] if args.blocks else None
    folder = f"{slug}-{args.style}" if args.style else slug
    style = os.path.join(STYLES_DIR, f"{args.style}_{slug}.json") if args.style else None
    final = args.out or os.path.join(TILES_DIR, folder)
    staging = args.out or os.path.join(TILES_DIR, f".{folder}.tmp")
    if not args.out and os.path.exists(staging):
        shutil.rmtree(staging)
    os.makedirs(staging, exist_ok=True)
    tasks = tasks_for(zooms, blocks)
    started = time.time()
    done = 0
    with multiprocessing.Pool(args.workers, _init, (slug, staging, style)) as pool:
        for i, count in enumerate(pool.imap_unordered(_render, tasks), 1):
            done += count
            if i % max(1, len(tasks) // 20) == 0:
                print(time.strftime("%H:%M:%S"), slug, f"{i}/{len(tasks)} blocks, {done} tiles", flush=True)
    m_per_px = (b["max_x"] - b["min_x"]) / (TILE * 2 ** finest)
    # "Squad dedicated server build <n>, landscape collision" of the heightmap the ground comes from
    build = json.load(open(os.path.join(HEIGHTMAPS_DIR, slug, "meta.json")))["sources"]["terrain"].split(",")[0]
    json.dump({
        "map": slug,
        "style": args.style or "detailed",
        "tileSize": TILE,
        "minNativeZoom": 0,
        "maxNativeZoom": finest,
        "metresPerPixel": round(m_per_px, 4),
        "bounds_m": b,
        "url": "{z}/{x}_{y}.webp",
        "legend": legend(),
        "sources": f"{build}: landscape collision and physical materials (ground), foliage collision (trunks), landscape splines, water, "
                   f"static mesh collision (objects the scene raster leaves out) and SquadHeight (ground beyond the landscape); Squad client build "
                   f"{os.environ.get('CLIENT_BUILD', 'unknown')}: visible LOD 0 meshes and foliage (objects, roofs, crowns), scenery meshes "
                   f"(ground beyond the landscape where the server has none) (tools/maptiles)",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seconds": round(time.time() - started),
    }, open(os.path.join(staging, "meta.json"), "w"), indent=1)
    if not args.out and not blocks and not args.zooms:
        old = os.path.join(TILES_DIR, f".{folder}.old")
        if os.path.exists(final):
            os.rename(final, old)
        os.rename(staging, final)
        if os.path.exists(old):
            shutil.rmtree(old)
    print(time.strftime("%H:%M:%S"), slug, f"{done} tiles, zoom 0..{finest} ({m_per_px:.3f} m/px), {time.time() - started:.0f} s", flush=True)


if __name__ == "__main__":
    main()
