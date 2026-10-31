"""Render the detailed tactical map tiles of one map from its prepared sources (prep.py).

Usage: render.py <map> [--workers N] [--zooms Z ...] [--blocks z/bx/by ...] [--out DIR]

Tiles follow SquadCalc's map frame: Leaflet CRS.Simple, the map image spanning LatLng [0, 0] to
[-256, 256]; at zoom z the map is 256 * 2**z pixels wide and tile (z, x, y) covers pixels
[256 x, 256 (x + 1)) x [256 y, 256 (y + 1)). Pixel (px, py) has its centre at world
X = min_x + (px + 0.5) * size_x / (256 * 2**z), Y = min_y + (py + 0.5) * size_y / (256 * 2**z),
the same as squadGrid.js (gameToMapScale for X, gameToMapScaleY for Y). The finest zoom is the
first with at most FINEST_M_PER_PX metres per pixel.

Output in /tiles/<map>/ (swapped in whole when the map is done): <z>/<x>_<y>.webp and meta.json
(maxNativeZoom, bounds, sources) that the SquadCalc frontend reads.

Every input is sampled at the global pixel position, and the label and symbol placements depend
only on world data, so blocks rendered separately join without seams. Layers, bottom to top:
ground cover (landscape physical materials), hillshade and slope tint, water, roads and tracks,
contours, foliage, objects with their shadows, contour labels, roof height labels.
"""

import argparse
import json
import math
import multiprocessing
import os
import shutil
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage, sparse

import features

TILE = 256
BLOCK_TILES = 4
MARGIN = 64
FINEST_M_PER_PX = 0.33
WEBP_QUALITY = 82
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
STEEP_RGB = (172, 156, 128)
WATER_RGB = np.array((156, 196, 226), np.float32)
WATER_DEEP_RGB = np.array((92, 142, 192), np.float32)
SHORE_RGB = np.array((62, 112, 168), np.float32)
CONTOUR_RGB = np.array((150, 92, 40), np.float32)
CONTOUR_LABEL_RGB = (128, 72, 24)
HALO_RGB = (250, 246, 236)
# Spline layers: fill colour, casing colour (None: no casing), minimum width in pixels
SPLINE_STYLE = {
    "dirt": ((204, 170, 118), None, 1.2),
    "pavement": ((214, 210, 202), (120, 116, 110), 1.0),
    "asphalt": ((226, 224, 218), (92, 86, 78), 1.6),
    "rail": ((86, 82, 78), None, 1.4),
    "trench": ((96, 66, 40), None, 1.2),
    "hedge": ((70, 102, 50), None, 1.2),
}
ROAD_CLASSES = ("dirt", "pavement", "asphalt")  # spline classes coloured by the "road" field
SPLINE_ORDER = ["dirt", "pavement", "asphalt", "rail", "trench", "hedge"]
# Foliage: canopy colour and alpha, outline colour, by features.FOLIAGE_CLASSES
FOLIAGE_STYLE = {
    features.CONIFER: ((40, 98, 56), 0.56, (22, 62, 34)),
    features.DECIDUOUS: ((92, 150, 68), 0.5, (48, 98, 40)),
    features.BUSH: ((128, 160, 86), 0.55, (78, 110, 52)),
    features.ROCK: ((150, 146, 140), 0.9, (92, 88, 84)),
}
FOLIAGE_GROUPS = {features.CONIFER: "conifer", features.DECIDUOUS: "deciduous", features.BUSH: "bush"}  # fields of fit_fields.py
FOLIAGE_ORDER = [features.ROCK, features.BUSH, features.DECIDUOUS, features.CONIFER]
TRUNK_RGB = (60, 44, 30)
# Objects: colour ramp of structures by height above ground (m), other classes by colour
STRUCTURE_RAMP = [(0.3, (222, 214, 200)), (2.0, (196, 186, 170)), (5.0, (170, 158, 142)), (10.0, (140, 130, 118)),
                  (20.0, (108, 102, 96)), (40.0, (78, 76, 74))]
OBJECT_RGB = {features.WALL: (98, 92, 86), features.ROCK_OBJECT: (160, 154, 146), features.VEGETATION: (76, 108, 58)}
OUTLINE_RGB = np.array((52, 48, 44), np.float32)
SHADOW_FACTOR = 0.72
# Relief and line strengths a style may change (see apply_style)
STEEP_ALPHA = 0.4
SHADE_STRENGTH = 0.7
CONTOUR_ALPHA = (0.5, 0.85)  # minor, major contours
GRADE = None  # final colour grade: {"gain": [r, g, b], "offset": [r, g, b]}
FIELDS = {}  # colour fields of a style: {group: {"file": name in /prep/<map>, "cell_m": metres per cell}}
OBJECT_MIN_M = 0.3
LIGHT = np.array([-1.0, -1.0, math.sqrt(2.0)]) / 2.0  # from the north-west, 45 degrees up (image Y points south)
CONTOUR_LADDER = [1, 2, 5, 10, 20, 50, 100, 200]
MAJOR = {1: 10, 2: 10, 5: 25, 10: 50, 20: 100, 50: 250, 100: 500, 200: 1000}
LABEL_CELL = 320
LABEL_STEP = 8
LABEL_HALF_PX = 14

STYLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "styles")
FOLIAGE_NAMES = {"conifer": features.CONIFER, "deciduous": features.DECIDUOUS, "bush": features.BUSH, "rock": features.ROCK}
OBJECT_NAMES = {"wall": features.WALL, "rock": features.ROCK_OBJECT, "vegetation": features.VEGETATION}

_data = {}


def apply_style(path):
    """Replace the default palette and strengths by the ones of a style file (JSON, tools/maptiles/py/styles).

    Keys, all optional: COVER_RGB {physical material: rgb}, NO_COVER_RGB, STEEP_RGB, WATER_RGB, WATER_DEEP_RGB,
    SHORE_RGB, CONTOUR_RGB, CONTOUR_LABEL_RGB, SPLINE_FILL {spline class: rgb}, FOLIAGE_RGB {conifer, deciduous,
    bush, rock: rgb}, FOLIAGE_ALPHA {the same names: opacity of the canopy colour}, STRUCTURE_RAMP [[height m, rgb]], OBJECT_RGB {wall, rock, vegetation: rgb}, SHADOW_FACTOR,
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


def finest_zoom(size_m):
    """Smallest zoom whose pixels are at most FINEST_M_PER_PX metres."""
    return max(0, math.ceil(math.log2(size_m / (TILE * FINEST_M_PER_PX))))


def load(slug):
    """Prepared sources of a map, memory-mapped; once per worker."""
    base = os.path.join("/prep", slug)
    meta = json.load(open(os.path.join(base, "meta.json")))
    b = meta["bounds_m"]
    d = {
        "meta": meta,
        "min_x": b["min_x"], "min_y": b["min_y"],
        "size_x": b["max_x"] - b["min_x"], "size_y": b["max_y"] - b["min_y"],
        "ground": np.load(os.path.join(base, "ground.npy"), mmap_mode="r"),
        "cover": np.load(os.path.join(base, "cover.npy"), mmap_mode="r"),
        "foliage": dict(np.load(os.path.join(base, "foliage.npz"))),
        "lines": json.load(open(os.path.join(base, "lines.json"))),
        "planes": json.load(open(os.path.join(base, "water.json")))["planes"],
        "labels": json.load(open(os.path.join(base, "labels.json"))),
        "sea": meta["sea_level_m"],
        "levels": meta["pyramid_levels"],
        "obj": {(name, k): np.load(os.path.join(base, f"obj_{name}{k}.npy"), mmap_mode="r")
                for name in "hcv" for k in range(meta["pyramid_levels"] + 1)},
        "finest": finest_zoom(b["max_x"] - b["min_x"]),
    }
    palette = np.array([COVER_RGB[name] for name in meta["physical_materials"]] + [NO_COVER_RGB] * (256 - len(meta["physical_materials"])), np.float32)
    palette[features.NO_COVER] = NO_COVER_RGB
    d["palette"] = palette
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
    d["font_label"] = ImageFont.truetype(FONT_BOLD, 11)
    d["font_roof"] = ImageFont.truetype(FONT_BOLD, 10)
    return d


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


def reduce_mean(window, f):
    """Average f x f cells of a window whose shape is a multiple of f."""
    if f == 1:
        return window
    h, w = window.shape[0] // f, window.shape[1] // f
    shape = (h, f, w, f) + window.shape[2:]
    return window[:h * f, :w * f].reshape(shape).mean(axis=(1, 3))


def sample_grid(array, u, v, px, order, value_dtype=np.float64, transform=None, separable=False, smooth_m=0.0):
    """Sample a 1 m grid array at grid coordinates (u = column, v = row; arrays) for pixels of px metres.

    Fine pixels (px < 2 m) read the array directly; coarse ones first average f x f cells (f the
    largest power of two not above px, aligned to the global grid) and smooth with a Gaussian of
    half a pixel, so each pixel shows its area. ``order`` 3 is a cubic B-spline through the
    samples, 1 bilinear. ``transform`` maps the cropped window before filtering (a palette lookup).
    The window has margins wide enough that the result does not depend on the block it is cut for.
    ``separable``: u and v are the 1-D column and row coordinates of a pixel grid, the result is
    [len(v), len(u)] (see axis_weights); else u and v are point coordinates of any equal shape.
    ``smooth_m``: Gaussian of at least this many metres (softens class boundaries at fine zooms).
    """
    f = 1 if px < 2 else 2 ** int(math.floor(math.log2(px)))
    sigma = max(0.0 if px < 2 else 0.5 * px / f, smooth_m / f)
    pad = 16 + int(math.ceil(4 * sigma)) * f + 2 * f
    c0 = int(math.floor(np.min(u))) - pad
    c1 = int(math.ceil(np.max(u))) + pad + 1
    r0 = int(math.floor(np.min(v))) - pad
    r1 = int(math.ceil(np.max(v))) + pad + 1
    c0, r0 = c0 - c0 % f, r0 - r0 % f
    c1, r1 = c1 + (-c1) % f, r1 + (-r1) % f
    window = crop(array, r0, r1, c0, c1)
    window = (transform(window) if transform else window).astype(value_dtype)
    window = reduce_mean(window, f)
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


def draw_water(d, frame, h, rgb):
    """Water wherever the ground lies below a water surface: the sea (ocean actors' level), static
    water planes and river splines (their ribbons at the spline's height: the river mesh is laid
    bank to bank and the banks rise above it). Returns the water coverage [H, W]."""
    surfaces = []
    box = frame.world_box(4)
    for plane in d["planes"]:
        b = plane["box"]
        if b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3]:
            continue
        surfaces.append((plane["z"], np.asarray(plane["polygon"])))
    for line in d["lines"]:
        b = line["box"]
        if line["cls"] != "river" or b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3]:
            continue
        z = line["center"][:, 2] - d["meta"]["z_min_m"]
        for k in range(len(z) - 1):
            surfaces.append((float(max(z[k], z[k + 1])), np.array([line["left"][k], line["right"][k], line["right"][k + 1], line["left"][k + 1]])))
    level = np.full(h.shape, -np.inf if d["sea"] is None else d["sea"], np.float32)
    if surfaces:
        # Painter's order: the higher surface wins where two overlap
        canvas = Image.new("F", (frame.width, frame.height), -1e9)
        draw = ImageDraw.Draw(canvas)
        for z, polygon in sorted(surfaces, key=lambda item: item[0]):
            px, py = frame.to_px(polygon[:, 0], polygon[:, 1])
            draw.polygon(list(zip(px.tolist(), py.tolist())), fill=z)
        level = np.maximum(level, np.asarray(canvas, np.float32))
    depth = level - h
    water = smoothstep(-0.05, 0.15, depth)
    if not water.any():
        return np.zeros(h.shape, np.float32)
    deep = smoothstep(0.0, 12.0, depth)[..., None]
    if d.get("trace") is not None:
        d["trace"]["deep"] = deep[..., 0]
    field = field_colour(d, "water", frame)
    if field is None:
        colour, shore = WATER_RGB * (1 - deep) + WATER_DEEP_RGB * deep, SHORE_RGB
    else:
        # The field is the colour of shallow water; the deep and shore colours keep the style's ratios to it
        colour, shore = field * (1 - deep + deep * WATER_DEEP_RGB / WATER_RGB), field * (SHORE_RGB / WATER_RGB)
    blend(rgb, colour, water)
    edge = np.clip(ndimage.maximum_filter(water, 3) - ndimage.minimum_filter(water, 3), 0, 1) * water
    blend(rgb, shore, edge * (0.6 if frame.px < 2 else 0.35))
    return water


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
            blend(rgb, casing_rgb, np.clip(grown - mask, 0, 1) * 0.85 * (1 - water))
        blend(rgb, fill_rgb, mask * (0.92 if cls != "dirt" else 0.75) * (1 - water * 0.5))


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
    sees a label draws the same one.
    """
    reach = LABEL_CELL // 2
    gx_lo = (frame.gx0 - reach) // LABEL_CELL
    gx_hi = (frame.gx0 + frame.width + reach) // LABEL_CELL
    gy_lo = (frame.gy0 - reach) // LABEL_CELL
    gy_hi = (frame.gy0 + frame.height + reach) // LABEL_CELL
    full = TILE * 2 ** frame.z
    inset = 48
    offsets = np.arange(inset, LABEL_CELL - inset, LABEL_STEP) + 0.5
    labels = []
    for cy in range(gy_lo, gy_hi + 1):
        for cx in range(gx_lo, gx_hi + 1):
            if cx < 0 or cy < 0 or cx * LABEL_CELL >= full or cy * LABEL_CELL >= full:
                continue
            pxs, pys = np.meshgrid(cx * LABEL_CELL + offsets, cy * LABEL_CELL + offsets)
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
            ok = (dist < LABEL_STEP * 0.75) & (minor / grad >= 7) & (major / grad >= 28) & (grad > 1e-4)
            if frame.px <= 1:
                ok &= ~objects_near(d, u, v, LABEL_HALF_PX * frame.px)
            if d["sea"] is not None:
                ok &= level > d["sea"] + 0.5
            if not ok.any():
                continue
            centre = (LABEL_CELL - 1) / 2
            score = np.where(ok, dist + 0.02 * np.hypot(pxs - cx * LABEL_CELL - centre, pys - cy * LABEL_CELL - centre), np.inf)
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
            half = d["font_label"].getlength(text) / 2 + 3
            labels.append((x - frame.gx0, y - frame.gy0, angle, text, half))
    return labels


def objects_near(d, u, v, radius_m):
    """Whether an object (0.3 m or taller, 1 m pyramid level) lies within radius_m of each point (u, v in m)."""
    r = int(math.ceil(radius_m))
    # Level 2 cell i is centred i + 0.375 m from min (see prep.py)
    cols = np.rint(u - 0.375).astype(np.int64)
    rows = np.rint(v - 0.375).astype(np.int64)
    c0, r0 = int(cols.min()) - r, int(rows.min()) - r
    window = crop(d["obj"][("v", 2)], r0, int(rows.max()) + r + 1, c0, int(cols.max()) + r + 1) > 0
    if not window.any():
        return np.zeros(u.shape, bool)
    busy = ndimage.maximum_filter(window, size=2 * r + 1)
    return busy[rows - r0, cols - c0]


def knockout(alpha, labels, half_height=7.0):
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


def draw_foliage(d, frame, rgb, water):
    """Trees and bushes as crown discs at their real size (with outlines and trunks when large
    enough), forest density where crowns are smaller than a pixel; rocks as grey discs."""
    f = d["foliage"]
    if not len(f["x"]):
        return
    box = frame.world_box(MARGIN)
    near = (f["x"] + f["radius"] >= box[0]) & (f["x"] - f["radius"] <= box[2]) & (f["y"] + f["radius"] >= box[1]) & (f["y"] - f["radius"] <= box[3])
    if not near.any():
        return
    x, y = frame.to_px(f["x"][near], f["y"][near])
    r = f["radius"][near] / frame.px
    half_x = f["half_x"][near] / frame.px
    half_y = f["half_y"][near] / frame.px
    yaw = f["yaw"][near]
    cls = f["cls"][near]
    trunk = f["collision"][near] & (cls != features.ROCK) & (cls != features.BUSH)
    scale = 2
    for c in FOLIAGE_ORDER:
        fill_rgb, fill_alpha, line_rgb = FOLIAGE_STYLE[c]
        field = field_colour(d, FOLIAGE_GROUPS[c], frame) if c in FOLIAGE_GROUPS else None
        if field is not None:
            fill_rgb, line_rgb = field, field * 0.7
        sel = cls == c
        if not sel.any():
            continue
        small = sel & (r < 0.9)
        large = sel & ~small
        coverage = np.zeros(rgb.shape[:2], np.float32)
        if small.any():
            # Expected crown cover of sub-pixel crowns: 1 - exp(-sum of crown areas in pixels)
            area = np.zeros(rgb.shape[:2], np.float64)
            xi = np.floor(x[small]).astype(np.int64)
            yi = np.floor(y[small]).astype(np.int64)
            ok = (xi >= 0) & (xi < area.shape[1]) & (yi >= 0) & (yi < area.shape[0])
            np.add.at(area, (yi[ok], xi[ok]), np.pi * r[small][ok] ** 2)
            area = ndimage.gaussian_filter(area, 0.6)
            coverage = (1 - np.exp(-area)).astype(np.float32)
        outline = np.zeros_like(coverage)
        if large.any():
            idx = np.nonzero(large)[0]
            canvas = Image.new("L", (rgb.shape[1] * scale, rgb.shape[0] * scale), 0)
            rim = Image.new("L", canvas.size, 0)
            draw, draw_rim = ImageDraw.Draw(canvas), ImageDraw.Draw(rim)
            rim_width = max(1, int(round(scale * (0.9 if frame.px < 1 else 0.6))))
            for i in idx[np.argsort(-r[idx])]:
                cx, cy, rr = x[i] * scale, y[i] * scale, r[i] * scale
                if c == features.ROCK:
                    # A rock's footprint is its bounds turned with the instance, not a crown disc
                    outline = features.ellipse_polygon(cx, cy, half_x[i] * scale, half_y[i] * scale, yaw[i], 12)
                    draw.polygon(outline, fill=255)
                    if r[i] >= 2.5:
                        draw_rim.polygon(outline, outline=255, width=rim_width)
                    continue
                bbox = (cx - rr, cy - rr, cx + rr, cy + rr)
                draw.ellipse(bbox, fill=255)
                if r[i] >= 2.5:
                    draw_rim.ellipse(bbox, outline=255, width=rim_width)
            coverage = np.maximum(coverage, downsample(canvas, frame))
            outline = downsample(rim, frame)
        if d.get("trace") is not None:
            d["trace"]["foliage"][c] = coverage
        keep = 1 - water
        blend(rgb, fill_rgb, coverage * fill_alpha * keep)
        if outline.any():
            blend(rgb, line_rgb, outline * 0.7 * keep)
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


def draw_objects(d, frame, rgb, water):
    """Collision footprints of buildings, walls, rocks and props: coloured by class and height above
    ground, roof slopes shaded, outlines at height steps, and shadows cast to the south-east."""
    k = int(np.clip(math.floor(math.log2(max(frame.px, 0.25) / 0.25)), 0, d["levels"]))
    # Level k cell i aggregates level 0 points [i 2^k, (i + 1) 2^k), centred (2^k - 1) / 2 points on
    ui = (frame.u / 0.25 - (2 ** k - 1) / 2) / 2 ** k
    vi = (frame.v / 0.25 - (2 ** k - 1) / 2) / 2 ** k
    c0, c1 = int(math.floor(ui.min())) - 2, int(math.ceil(ui.max())) + 3
    r0, r1 = int(math.floor(vi.min())) - 2, int(math.ceil(vi.max())) + 3
    h_win = crop(d["obj"][("h", k)], r0, r1, c0, c1)
    if not h_win.any():
        return
    c_win = crop(d["obj"][("c", k)], r0, r1, c0, c1)
    v_win = crop(d["obj"][("v", k)], r0, r1, c0, c1).astype(np.float32) / 255
    near_u = np.clip(np.rint(ui - c0).astype(np.int64), 0, h_win.shape[1] - 1)
    near_v = np.clip(np.rint(vi - r0).astype(np.int64), 0, h_win.shape[0] - 1)
    height = h_win[np.ix_(near_v, near_u)].astype(np.float32) / 100
    cls = c_win[np.ix_(near_v, near_u)]
    rows, cols = axis_weights(vi - r0, v_win.shape[0], 1), axis_weights(ui - c0, v_win.shape[1], 1)
    alpha = (rows @ (cols @ v_win.T).T).astype(np.float32)
    alpha = np.clip(alpha, 0, 1) * (height >= OBJECT_MIN_M)
    if d.get("trace") is not None:
        d["trace"]["objects"] = (alpha, height, cls)
    # Work on the objects' bounding box (with room for their shadows); rgb is a view, written in place
    box = nonzero_box(alpha, 48)
    if box is None:
        return
    field = field_colour(d, "object", frame)
    alpha, height, cls, water, rgb = alpha[box], height[box], cls[box], water[box], rgb[box]
    # Shadows of the objects on the ground: a pixel is in shadow when an object that many steps towards the
    # light is taller than the ray's height there (the default light: north-west at 45 degrees)
    if frame.px <= 2:
        casting = np.where(alpha > 0, height, 0)
        shadow = np.zeros(alpha.shape, bool)
        away = -LIGHT[:2] / math.hypot(LIGHT[0], LIGHT[1])
        major = float(np.abs(away).max())
        step_m = frame.px / major  # metres along the ray per step of one pixel along its major axis
        tan_elevation = LIGHT[2] / math.hypot(LIGHT[0], LIGHT[1])
        max_shift = int(min(40, math.ceil(float(casting.max()) / (tan_elevation * step_m))))
        for s in range(1, max_shift + 1):
            dx, dy = int(round(s * away[0] / major)), int(round(s * away[1] / major))
            shifted = np.zeros_like(casting)
            shifted[max(dy, 0):casting.shape[0] + min(dy, 0), max(dx, 0):casting.shape[1] + min(dx, 0)] = \
                casting[max(-dy, 0):casting.shape[0] + min(-dy, 0), max(-dx, 0):casting.shape[1] + min(-dx, 0)]
            shadow |= shifted > s * step_m * tan_elevation
        shadow = ndimage.gaussian_filter(shadow.astype(np.float32), 0.6) * (1 - alpha)
        if d.get("trace") is not None:
            full = np.zeros(d["trace"]["objects"][0].shape, np.float32)
            full[box] = shadow
            d["trace"]["shadow"] = full
        rgb *= (1 - shadow * (1 - SHADOW_FACTOR) * (1 - water))[..., None]
    if field is None:
        colour = structure_colour(height)
        for c, value in OBJECT_RGB.items():
            colour[cls == c] = value
    else:
        colour = field[box]
    # Roof and rock relief: hillshade of the object top over the pixel grid
    top = ndimage.gaussian_filter(height, 0.7)
    gy, gx = np.gradient(top)
    gx /= frame.px
    gy /= frame.px
    normal_z = 1 / np.sqrt(1 + gx * gx + gy * gy)
    lam = (-gx * LIGHT[0] - gy * LIGHT[1] + LIGHT[2]) * normal_z
    shade = np.clip(1 + 0.8 * (lam - LIGHT[2]), 0.55, 1.25)[..., None]
    colour = np.clip(colour * shade, 0, 255)
    blend(rgb, colour, alpha)
    # Outlines: the footprint edge and height steps over 1 m inside it
    if frame.px <= 1.5:
        edge = np.clip(ndimage.maximum_filter(alpha, 3) - ndimage.minimum_filter(alpha, 3), 0, 1)
        hmax = ndimage.maximum_filter(height * (alpha > 0.5), 3)
        hmin = ndimage.minimum_filter(np.where(alpha > 0.5, height, hmax), 3)
        step_edge = ((hmax - hmin) > 1.0).astype(np.float32) * (alpha > 0.5)
        outline = np.maximum(edge * alpha, step_edge * 0.6)
        blend(rgb, OUTLINE_RGB, np.clip(outline, 0, 1) * (0.85 if frame.px <= 0.5 else 0.6))


def roof_labels(d, frame, canvas):
    """Roof height above ground of the larger buildings, at the finest two zooms."""
    if frame.z < d["finest"] - 1:
        return
    font = d["font_roof"]
    for label in d["labels"]:
        x, y = frame.to_px(label["x"], label["y"])
        if not (-MARGIN < x < frame.width + MARGIN and -MARGIN < y < frame.height + MARGIN):
            continue
        text = f"{label['h']:.0f}m"
        if label["depth"] / frame.px < font.getlength(text) / 2 + 2:
            continue
        paste(canvas, text_patch(text, font, 0, (30, 28, 26), (246, 244, 240), 2), x, y)


def render_block(d, z, bx, by):
    """RGB image [H, W, 3] of block (bx, by) of BLOCK_TILES tiles at zoom z, with MARGIN pixels around."""
    size = TILE * BLOCK_TILES
    full = TILE * 2 ** z
    width = min(size, full - bx * size) + 2 * MARGIN
    height = min(size, full - by * size) + 2 * MARGIN
    frame = Frame(d, z, bx * size - MARGIN, by * size - MARGIN, width, height)
    px = frame.px

    h = sample_grid(d["ground"], frame.u, frame.v, px, 3, separable=True).astype(np.float32)
    gy, gx = np.gradient(h)  # metres per pixel
    slope = np.hypot(gx / frame.px_x, gy / frame.px_y)

    # Material boundaries softened by 0.7 m (bilinear alone leaves diamond-shaped steps at fine zooms)
    rgb = field_colour(d, "ground", frame)
    if rgb is None:
        rgb = sample_grid(d["cover"], frame.u, frame.v, px, 1, np.float32, transform=lambda w: d["palette"][w],
                          separable=True, smooth_m=0.7).astype(np.float32)
        steep = smoothstep(0.6, 1.5, slope) * STEEP_ALPHA
        blend(rgb, STEEP_RGB, steep.astype(np.float32))

    exaggeration = 1.0 if px <= 2 else min(4.0, 1.0 + 0.5 * math.log2(px / 2) * 1.5)
    sx = gx / frame.px_x * exaggeration
    sy = gy / frame.px_y * exaggeration
    normal_z = 1 / np.sqrt(1 + sx * sx + sy * sy)
    lam = (-sx * LIGHT[0] - sy * LIGHT[1] + LIGHT[2]) * normal_z
    shade = np.clip(1 + SHADE_STRENGTH * (lam - LIGHT[2]), 0.6, 1.18)
    rgb *= shade[..., None].astype(np.float32)
    trace = d.get("trace")
    if trace is not None:
        trace.clear()
        trace.update(splines={}, foliage={}, shade=shade, slope_x=gx / frame.px_x, slope_y=gy / frame.px_y)
        cols = np.clip(np.floor(frame.u).astype(np.int64), 0, d["cover"].shape[1] - 1)
        rows = np.clip(np.floor(frame.v).astype(np.int64), 0, d["cover"].shape[0] - 1)
        window = np.asarray(d["cover"][rows.min():rows.max() + 1, cols.min():cols.max() + 1])
        trace["cover"] = window[np.ix_(rows - rows.min(), cols - cols.min())]

    water = draw_water(d, frame, h, rgb)
    draw_splines(d, frame, rgb, water)

    minor, major = contour_intervals(d, px)
    labels = contour_labels(d, frame, minor, major)
    a_minor, level = contour_alpha(h, gx, gy, minor, 0.9 if px < 1 else 0.7)
    is_major = (np.abs(np.round(level / major) * major - level) < 1e-3)
    a_major, _ = contour_alpha(h, gx, gy, major, 1.5 if px < 4 else 1.1)
    a_minor = np.where(is_major, 0, a_minor) * CONTOUR_ALPHA[0]
    a_major *= CONTOUR_ALPHA[1]
    contours = np.maximum(a_minor, a_major) * (1 - water)
    knockout(contours, labels)
    blend(rgb, CONTOUR_RGB, contours.astype(np.float32))

    draw_foliage(d, frame, rgb, water)
    draw_objects(d, frame, rgb, water)

    if trace is not None:
        trace.update(water=water, rgb=rgb.copy())
    if GRADE is not None:
        rgb = rgb * GRADE["gain"] + GRADE["offset"]
    canvas = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    for x, y, angle, text, _ in labels:
        paste(canvas, text_patch(text, d["font_label"], angle, CONTOUR_LABEL_RGB, HALO_RGB, 2), x, y)
    roof_labels(d, frame, canvas)
    return canvas.convert("RGB")


def _init(slug, out_dir, style=None):
    if style:
        apply_style(style)
    _data.update(load(slug))
    _data["out"] = out_dir


def _render(task):
    z, bx, by = task
    d = _data
    image = render_block(d, z, bx, by)
    tiles = 2 ** z
    count = 0
    for ty in range(BLOCK_TILES):
        for tx in range(BLOCK_TILES):
            x, y = bx * BLOCK_TILES + tx, by * BLOCK_TILES + ty
            if x >= tiles or y >= tiles:
                continue
            left, top = MARGIN + tx * TILE, MARGIN + ty * TILE
            tile = image.crop((left, top, left + TILE, top + TILE))
            os.makedirs(os.path.join(d["out"], str(z)), exist_ok=True)
            tile.save(os.path.join(d["out"], str(z), f"{x}_{y}.webp"), "WEBP", quality=WEBP_QUALITY, method=4)
            count += 1
    return count


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
    meta = json.load(open(os.path.join("/prep", slug, "meta.json")))
    b = meta["bounds_m"]
    finest = finest_zoom(b["max_x"] - b["min_x"])
    zooms = args.zooms if args.zooms else list(range(finest, -1, -1))
    blocks = [tuple(int(v) for v in s.split("/")) for s in args.blocks] if args.blocks else None
    folder = f"{slug}-{args.style}" if args.style else slug
    style = os.path.join(STYLES_DIR, f"{args.style}_{slug}.json") if args.style else None
    final = args.out or os.path.join("/tiles", folder)
    staging = args.out or os.path.join("/tiles", f".{folder}.tmp")
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
    build = json.load(open(os.path.join("/heightmaps", slug, "meta.json")))["sources"]["terrain"].split(",")[0]
    json.dump({
        "map": slug,
        "style": args.style or "detailed",
        "tileSize": TILE,
        "minNativeZoom": 0,
        "maxNativeZoom": finest,
        "metresPerPixel": round(m_per_px, 4),
        "bounds_m": b,
        "url": "{z}/{x}_{y}.webp",
        "sources": f"{build}: landscape collision and physical materials, static mesh collision, foliage, landscape "
                   "splines, water; SquadHeight for Blueprint objects (tools/maptiles)",
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seconds": round(time.time() - started),
    }, open(os.path.join(staging, "meta.json"), "w"), indent=1)
    if not args.out and not blocks and not args.zooms:
        old = os.path.join("/tiles", f".{folder}.old")
        if os.path.exists(final):
            os.rename(final, old)
        os.rename(staging, final)
        if os.path.exists(old):
            shutil.rmtree(old)
    print(time.strftime("%H:%M:%S"), slug, f"{done} tiles, zoom 0..{finest} ({m_per_px:.3f} m/px), {time.time() - started:.0f} s", flush=True)


if __name__ == "__main__":
    main()
