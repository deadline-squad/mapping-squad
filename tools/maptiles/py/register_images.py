"""Where each map picture of SquadCalc lies on the world, measured against the level's own data.

A picture is placed over a world rectangle as the calculator or the game places it, resampled to a grid of about
one of its pixels over the map's frame, and registered on a reference made from game data placed by world
coordinates, in WINDOWS x WINDOWS overlapping windows: normalised cross-correlation within +-SEARCH_M, a sub-pixel
peak, windows with a weak (MIN_PEAK) or ambiguous (MIN_SHARPNESS) peak or one at the search's edge left out, and an
affine fit of the window shifts, d = a + b u + c v (u, v the window's centre across the grid, -0.5 to 0.5), weighted
by the peak, windows more than OUTLIER_PX off the fit left out.

Every result is the displacement of the picture's content from the world in metres, + = drawn east (x) or south (y)
of where it is: `W` and `E` the x displacement at the middle of the grid's west and east edges, `N` and `S` the y
displacement at the middle of its north and south edges, `C` at its centre, `worst` the largest component at its four
corners, `rms` of the kept windows about the fit (x, y), `windows` the windows the fit kept; `scale` the picture's
size on the world over its true size minus 1 (x, y) and `rotation_deg` its turn, clockwise on the map, both from the
fit's linear terms. A fit needs MIN_FIT_WINDOWS windows; one on fewer than 20 is weak. Displacements under about
0.4 m are below the method (the Detailed layer, drawn from the same level data, reads 0.08 to 0.40 m on 23 maps).

References:

features  edges of the level's objects (the 0.25 m collision coverage of `prep`, obj_v1 or obj_v2 by the grid),
          tree crowns (foliage.npz, rocks left out) and road surfaces (lines.json), weighted FEATURE_WEIGHTS, against
          the edges of the picture's luminance
shade     the ground's slopes (ground.npy) lit from the direction fitted over the map, plus its coastline where the
          map has a sea, against the band-passed log luminance of the picture: the terrain shading the picture
          carries, independent of the objects

Measures (each prints one JSON object per line):

textures                    the pak path pattern of every minimap texture the levels and the layer data name
                            (the extractor's texraw mode)
basemaps [map ...]          by features: `game` the client's base texture between the game's corners (what the game
                            shows), `image` the upstream basemap between the image corners (the tile frame),
                            `basemap_game` the upstream basemap between the game's corners, `detailed` the served
                            Detailed tiles (/tiles/<map>) at the zoom nearest that grid, over the image corners
rect <map> <basemap|texture> <min x> <min y> <max x> <max y> [--reference shade]
                            one picture over one rectangle; `fitted` is the rectangle the picture shows (the
                            rectangle minus the displacement, carried to its edges)
layer-minimaps [map ...]    the layer minimaps of /layer-tiles/layer-minimaps.json between their corners, by features;
                            `finer` is the map's base texture's metres per pixel over the layer minimap's
locate <map> <texture> <min x> <min y> <max x> <max y> <sizes> [--crop x0 x1 y0 y1]
                            where a texture's picture lies on the map's base texture (between the game's corners) when
                            it shows a square of each side in <sizes> (`a:b:step` or a list, metres): edge-image NCC of
                            the 8 orientations of the texture (or of the given fraction of it); `W`, `E`, `N`, `S` the
                            displacement of its content when it is drawn over the given rectangle
orientation [map ...]       the upstream basemap against the client's base texture: correlation of the 8 orientations
                            (512 px), and the shift of ORIENTATION_WINDOWS^2 windows of the oriented basemap fitted
                            as an offset (px at the centre) and a change across the image per axis
upstream-relief [map ...]   upstream's 8-bit heightmap (heightmap.png, points from corner to corner, level 255 + red -
                            blue) against the ground; the hillshade in terrainmap.webp (over basemap.webp) and in
                            topomap.webp against that heightmap lit from the fitted direction
relief [map ...] [--reference heightmap]
                            the relief layer (/tiles/relief/<map>.pmtiles, zoom RELIEF_ZOOM) against `mdow`, the
                            multi-directional hillshade of the ground, and `layer`, the layer's own shading of it
                            (relief.shade_map, relief.blend); of the bare ground of prep, or of the served heightmap

Container paths, as the other tools: /prep (prep rasters), /tiles (served tiles), /heightmaps (served heightmaps),
/layer-minimaps (layers.tsv and layerdata/ of the layer-minimaps step), /register (`maptiles.sh register-setup`:
tex/ the client's minimap textures as the extractor's texraw writes them, upstream/<map>/ the upstream images),
/layer-tiles (the layer minimaps measured). Maps by SquadCalc folder name; without maps, every map of maps.MAPS.
"""
import argparse
import io
import json
import os
import sys
from collections import Counter, namedtuple

import numpy as np
from PIL import Image, ImageDraw
from pmtiles.reader import MmapSource, Reader
from scipy import ndimage, signal

import features
import layer_minimaps
import maps
import relief
import topometrics

PREP = "/prep"
TILES = "/tiles"
HEIGHTMAPS = "/heightmaps"
LAYER_MINIMAPS = "/layer-minimaps"
REGISTER = "/register"
LAYER_TILES = "/layer-tiles"

WINDOWS = 8
WINDOW_OVERLAP = 1.25          # window side: the grid's shorter side over WINDOWS, times this
SEARCH_M = 30.0
MIN_PEAK = 0.12
MIN_SHARPNESS = 1.15           # the peak over the highest correlation outside its 7 x 7 neighbourhood
VALID_SHARE = 0.98             # a window is measured where this share of it holds the picture
OUTLIER_PX = 2.5
OUTLIER_MEDIANS = 3.0          # ... or this many times the median residual, whichever is larger
FIT_ITERATIONS = 4
MIN_FIT_WINDOWS = 6
FEATURE_WEIGHTS = (("objects", 1.0), ("trees", 0.7), ("roads", 0.5))
ROAD_CLASSES = ("asphalt", "dirt", "pavement")
CROWN_RADIUS_BINS = ((0, 1.5), (1.5, 3), (3, 5), (5, 8), (8, 100))
FEATURE_SIGMA_MIN_M = 0.35
ROAD_FINE_CELLS = 30e6         # maps with fewer 1 m cells draw their roads on a 0.5 m canvas
LAYER_MINIMAP_MIN_STEP_M = 0.4
LOCATE_STEP_M = 2.0
ORIENTATION_THUMB_PX = 512
ORIENTATION_WINDOWS = 7
ORIENTATION_WINDOW_PX = 384
ORIENTATION_SEARCH_PX = 24
ORIENTATION_MIN_PEAK = 0.2
UPSTREAM_GRID_PX = 2048        # upstream-relief: the grid has this many cells across, but no cell under 1 m
UPSTREAM_SEARCH_M = 80.0
UPSTREAM_MIN_PEAK = 0.2
RELIEF_ZOOM = 4
LIGHT_FIT_STRIDE = 37          # every n-th valid cell enters the fit of the light direction
UPSTREAM_LIGHT_STRIDE = 53
LUMINANCE = np.array([0.299, 0.587, 0.114], np.float32)
# First token of a layer's name -> SquadCalc map folder, where it is not the token in lower case
LAYER_MAP_SLUGS = {"Jensens": "jensen", "PacificProvingGrounds": "pacific"}
# A map: its base texture's object path, the rectangle the game draws it over and the image corners (the tile
# frame of prep), each (min x, min y, max x, max y) in metres
MapInfo = namedtuple("MapInfo", "slug texture game_rect image_rect")


def slug_of(layer_map):
    """SquadCalc map folder of a layer name's first token (`Jensens` of `Jensens_Range_...` is `jensen`)."""
    return LAYER_MAP_SLUGS.get(layer_map, layer_map.lower())


def map_infos(table):
    """`{slug: MapInfo}` of the maps of a layer table (layer_minimaps.read_tables) that have prep rasters.

    The game rectangle is the one most of the layers that show the base texture stretch it over.
    """
    base = layer_minimaps.base_textures(table)
    rects = {}
    for layer, minimap in table.items():
        name = layer_minimaps.map_name(layer)
        if minimap.texture == base[name]:
            rects.setdefault(name, Counter())[minimap.rect] += 1
    infos = {}
    for name, texture in base.items():
        slug = slug_of(name)
        meta_path = os.path.join(PREP, slug, "meta.json")
        if not os.path.exists(meta_path):
            continue
        with open(meta_path) as f:
            bounds = json.load(f)["bounds_m"]
        game = tuple(round(v / 100, 5) for v in rects[name].most_common(1)[0][0])
        infos[slug] = MapInfo(slug, texture, game, (bounds["min_x"], bounds["min_y"], bounds["max_x"], bounds["max_y"]))
    return infos


def read_map_infos():
    """`{slug: MapInfo}` of the layer table under /layer-minimaps."""
    table = layer_minimaps.read_tables(os.path.join(LAYER_MINIMAPS, "layers.tsv"), os.path.join(LAYER_MINIMAPS, "layerdata"))
    return map_infos(table)


def texture_files(directory):
    """`{package name in lower case: file name}` of the extractor's raw textures in a directory."""
    return {layer_minimaps.parse_raw_name(name)[0].lower(): name for name in os.listdir(directory) if name.endswith(".bin")}


def client_texture(name):
    """RGB array of a client minimap texture by object path or package name (the raw file's: `BlackCoast_Seed_v1` holds
    `T_BlackCoast_Seed_v1`), case-insensitive."""
    directory = os.path.join(REGISTER, "tex")
    filename = texture_files(directory).get(layer_minimaps.package_name(name).lower())
    if filename is None:
        raise SystemExit(f"no raw texture for {name} in {directory}: run maptiles.sh register-setup")
    _, pixel_format, width, height = layer_minimaps.parse_raw_name(filename)
    with open(os.path.join(directory, filename), "rb") as f:
        return layer_minimaps.decode_texture(f.read(), pixel_format, width, height)


def texture_width(name):
    """Width in px of a client texture (object path or package name), from its raw file name."""
    return layer_minimaps.parse_raw_name(texture_files(os.path.join(REGISTER, "tex"))[layer_minimaps.package_name(name).lower()])[2]


def upstream_image(slug, filename):
    """RGB array of an upstream image (/register/upstream/<map>/<file>)."""
    return np.asarray(Image.open(os.path.join(REGISTER, "upstream", slug, filename)).convert("RGB"))


def luminance(rgb):
    """Luminance (float32) of an RGB array."""
    return rgb.astype(np.float32) @ LUMINANCE


def frame_grid(rect, step):
    """World x of the columns and y of the rows (cell centres) of a grid of `step` from the rectangle's min corner."""
    x0, y0, x1, y1 = rect
    nx, ny = int((x1 - x0) // step), int((y1 - y0) // step)
    return x0 + (np.arange(nx) + 0.5) * step, y0 + (np.arange(ny) + 0.5) * step


def sample_image(image, xs, ys, rect):
    """Samples a 2-D image whose pixel edges span the rectangle (texel centres at (i + 0.5) / N) at world xs, ys.

    Returns (len(ys), len(xs)) float32, bilinear, NaN outside the image.
    """
    x0, y0, x1, y1 = rect
    h, w = image.shape
    rows, cols = np.meshgrid((ys - y0) / (y1 - y0) * h - 0.5, (xs - x0) / (x1 - x0) * w - 0.5, indexing="ij")
    return ndimage.map_coordinates(image.astype(np.float32), [rows, cols], order=1, mode="constant", cval=np.nan)


def sample_points(points, xs, ys, x_first, y_first, step_x, step_y=None):
    """Samples a point grid (point [r, c] at x_first + c * step_x, y_first + r * step_y) at world xs, ys; NaN outside."""
    rows, cols = np.meshgrid((ys - y_first) / (step_y or step_x), (xs - x_first) / step_x, indexing="ij")
    return ndimage.map_coordinates(np.asarray(points, np.float32), [rows, cols], order=1, mode="constant", cval=np.nan)


def edges(a, sigma=1.0):
    """Gradient magnitude of the smoothed image less its local mean (8 sigma): edges, independent of the brightness."""
    a = np.nan_to_num(a.astype(np.float32), nan=float(np.nanmean(a)))
    smooth = ndimage.gaussian_filter(a, sigma)
    magnitude = np.hypot(ndimage.sobel(smooth, 1), ndimage.sobel(smooth, 0))
    return magnitude - ndimage.gaussian_filter(magnitude, 8 * sigma)


def band_pass(a, fine=1.0, coarse=10.0):
    """Difference of two Gaussian blurs (px): the detail between the two scales; NaN filled with the mean."""
    a = np.nan_to_num(a.astype(np.float32), nan=float(np.nanmean(a)))
    return ndimage.gaussian_filter(a, fine) - ndimage.gaussian_filter(a, coarse)


def ncc_shift(picture, reference, search):
    """Shift (dx, dy) in px of the reference's content in the picture, within +-search, by normalised cross-correlation.

    Returns (dx, dy, peak, sharpness, at_edge): the sub-pixel peak (a parabola through it and its neighbours on each
    axis), its height, its ratio to the highest correlation outside its 7 x 7 neighbourhood, and whether it lies on
    the search's border (then not a measurement).
    """
    a = picture - picture.mean()
    b = reference - reference.mean()
    h, w = a.shape
    padded = (h + 2 * search, w + 2 * search)
    corr = np.fft.irfft2(np.fft.rfft2(a, padded) * np.conj(np.fft.rfft2(b, padded)), padded)
    corr = np.roll(np.roll(corr, search, 0), search, 1)[:2 * search + 1, :2 * search + 1]
    corr = corr / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-9)
    j, i = np.unravel_index(np.argmax(corr), corr.shape)

    def vertex(before, at, after):
        curvature = before - 2 * at + after
        return 0.0 if curvature == 0 else 0.5 * (before - after) / curvature

    at_edge = not (0 < j < 2 * search and 0 < i < 2 * search)
    dy = j - search + (0.0 if at_edge else vertex(corr[j - 1, i], corr[j, i], corr[j + 1, i]))
    dx = i - search + (0.0 if at_edge else vertex(corr[j, i - 1], corr[j, i], corr[j, i + 1]))
    peak = float(corr[j, i])
    masked = corr.copy()
    masked[max(0, j - 3):j + 4, max(0, i - 3):i + 4] = -np.inf
    second = float(masked.max())
    return float(dx), float(dy), peak, peak / second if second > 0 else 99.0, at_edge


def fit_affine(points):
    """Weighted affine fit of window shifts (u, v, dx, dy, peak; u, v in 0..1 across the grid) with outlier rejection.

    Returns (coef_x, coef_y, kept) with d = c0 + c1 (u - 0.5) + c2 (v - 0.5) in px, or None when fewer than
    MIN_FIT_WINDOWS windows are left.
    """
    p = np.asarray(points, np.float64)
    u, v, dx, dy, weight = p[:, 0] - 0.5, p[:, 1] - 0.5, p[:, 2], p[:, 3], np.sqrt(p[:, 4])
    design = np.c_[np.ones(len(p)), u, v]

    def solve(keep):
        rows = design[keep] * weight[keep, None]
        cx, *_ = np.linalg.lstsq(rows, dx[keep] * weight[keep], rcond=None)
        cy, *_ = np.linalg.lstsq(rows, dy[keep] * weight[keep], rcond=None)
        return cx, cy

    keep = np.ones(len(p), bool)
    for _ in range(FIT_ITERATIONS):
        if keep.sum() < MIN_FIT_WINDOWS:
            return None
        cx, cy = solve(keep)
        residual = np.hypot(dx - design @ cx, dy - design @ cy)
        new = residual <= max(OUTLIER_PX, OUTLIER_MEDIANS * np.median(residual[keep]))
        if (new == keep).all():
            return cx, cy, keep
        keep = new
    if keep.sum() < MIN_FIT_WINDOWS:
        return None
    cx, cy = solve(keep)
    return cx, cy, keep


def summarise(points, step, shape):
    """The displacement figures of a window fit in metres (see the module docstring), None without a fit."""
    fitted = fit_affine(points) if points else None
    if fitted is None:
        return None
    cx, cy, keep = fitted
    h, w = shape
    p = np.asarray(points, np.float64)[keep]
    design = np.c_[np.ones(len(p)), p[:, 0] - 0.5, p[:, 1] - 0.5]

    def at(u, v):
        return [round(float((cx[0] + cx[1] * u + cx[2] * v) * step), 2), round(float((cy[0] + cy[1] * u + cy[2] * v) * step), 2)]

    corners = [at(u, v) for u in (-0.5, 0.5) for v in (-0.5, 0.5)]
    # d(dx)/dx = c1 / w per px; a picture turned clockwise by t moves (x, y) by t (-y, x)
    rotation = 0.5 * (cy[1] / w - cx[2] / h)
    return {
        "W": at(-0.5, 0)[0], "E": at(0.5, 0)[0], "N": at(0, -0.5)[1], "S": at(0, 0.5)[1], "C": at(0, 0),
        "worst": max(max(abs(c[0]), abs(c[1])) for c in corners),
        "rms": [round(float(np.sqrt(((p[:, 2] - design @ cx) ** 2).mean()) * step), 2),
                round(float(np.sqrt(((p[:, 3] - design @ cy) ** 2).mean()) * step), 2)],
        "windows": int(keep.sum()),
        "scale": [round(float(cx[1] / w), 5), round(float(cy[2] / h), 5)],
        "rotation_deg": round(float(np.degrees(rotation)), 3),
    }


def register(reference, picture, valid, step, search_m=SEARCH_M, min_peak=MIN_PEAK):
    """Registers the picture (2-D field) on the reference (same grid) in WINDOWS x WINDOWS windows.

    Args:
        reference, picture: float fields of one grid, compared as they are (edges, band-passed shading).
        valid: bool mask of the grid cells the picture covers.
        step: grid cell in metres.
        search_m, min_peak: search reach of each window and the least correlation peak counted.

    Returns:
        (summary or None, windows measured).
    """
    h, w = reference.shape
    side = int(min(h, w) / WINDOWS * WINDOW_OVERLAP)
    search = int(np.ceil(search_m / step))
    points = []
    for j in range(WINDOWS):
        for i in range(WINDOWS):
            y, x = int((h - side) * j / (WINDOWS - 1)), int((w - side) * i / (WINDOWS - 1))
            window = (slice(y, y + side), slice(x, x + side))
            if valid[window].mean() < VALID_SHARE or reference[window].std() < 1e-6:
                continue
            dx, dy, peak, sharpness, at_edge = ncc_shift(picture[window], reference[window], search)
            if at_edge or peak < min_peak or sharpness < MIN_SHARPNESS:
                continue
            points.append(((x + side / 2) / w, (y + side / 2) / h, dx, dy, peak))
    return summarise(points, step, reference.shape), len(points)


def prep_meta(slug):
    """meta.json of a map's prep rasters."""
    with open(os.path.join(PREP, slug, "meta.json")) as f:
        return json.load(f)


class Features:
    """The level's feature fields of one map (prep rasters), smoothed for a grid of `step` and sampled on any grid of it.

    objects: collision coverage, level k = 1 (0.5 m cells) below a 0.75 m grid, else 2 (1 m); a level-k cell
    aggregates the 0.25 m points min + 2^k c + (0 .. 2^k - 1) / 4, its centre lies at + (2^k - 1) / 8.
    trees: the crowns of foliage.npz (rocks left out) splatted as Gaussian blobs of sigma radius / 1.5 on the 1 m
    ground grid, by radius class. roads: the road surfaces of lines.json filled as polygons (0.5 m canvas on maps of
    fewer than ROAD_FINE_CELLS cells, else 1 m).
    """

    def __init__(self, slug, step):
        folder = os.path.join(PREP, slug)
        with open(os.path.join(folder, "meta.json")) as f:
            self.bounds = bounds = json.load(f)["bounds_m"]
        sigma = max(step / 2.0, FEATURE_SIGMA_MIN_M)
        level = 1 if step < 0.75 else 2
        self.cell = 0.25 * 2 ** level
        self.first = (2 ** level - 1) / 8.0
        coverage = np.load(os.path.join(folder, f"obj_v{level}.npy"), mmap_mode="r")
        self.objects = ndimage.gaussian_filter(np.asarray(coverage, np.float32) / 255.0, sigma / self.cell)
        shape = np.load(os.path.join(folder, "ground.npy"), mmap_mode="r").shape
        self.trees = ndimage.gaussian_filter(np.minimum(crown_field(np.load(os.path.join(folder, "foliage.npz")), bounds, shape), 1.0), sigma)
        self.scale = 2 if shape[0] * shape[1] < ROAD_FINE_CELLS else 1
        with open(os.path.join(folder, "lines.json")) as f:
            canvas = road_canvas(json.load(f), bounds, shape, self.scale)
        self.roads = ndimage.gaussian_filter(canvas, sigma * self.scale)

    def reference(self, xs, ys):
        """The weighted sum of the edges of the three fields on the grid of xs, ys."""
        b = self.bounds
        fields = {
            "objects": sample_points(self.objects, xs, ys, b["min_x"] + self.first, b["min_y"] + self.first, self.cell),
            "trees": sample_points(self.trees, xs, ys, b["min_x"], b["min_y"], 1.0),
            "roads": sample_points(self.roads, xs, ys, b["min_x"], b["min_y"], 1.0 / self.scale),
        }
        return sum(weight * edges(np.nan_to_num(fields[name])) for name, weight in FEATURE_WEIGHTS)


def crown_field(foliage, bounds, shape):
    """Crown cover of the foliage on the 1 m grid of `shape` from the bounds' min corner (rocks left out)."""
    crowns = np.zeros(shape, np.float32)
    keep = foliage["cls"] != features.ROCK
    radius = foliage["radius"][keep]
    fx, fy = foliage["x"][keep] - bounds["min_x"], foliage["y"][keep] - bounds["min_y"]
    for low, high in CROWN_RADIUS_BINS:
        chosen = (radius >= low) & (radius < high)
        if not chosen.any():
            continue
        impulses = np.zeros(shape, np.float32)
        cols = np.clip(np.rint(fx[chosen]).astype(int), 0, shape[1] - 1)
        rows = np.clip(np.rint(fy[chosen]).astype(int), 0, shape[0] - 1)
        np.add.at(impulses, (rows, cols), 1.0)
        sigma = float(np.median(radius[chosen])) / 1.5
        crowns += ndimage.gaussian_filter(impulses, max(sigma, 0.5)) * (2 * np.pi * sigma ** 2)
    return crowns


def road_canvas(lines, bounds, shape, scale):
    """Road surfaces (ROAD_CLASSES) of lines.json filled on a canvas of 1 / scale m from the bounds' min corner, 0..1."""
    canvas = Image.new("L", (shape[1] * scale, shape[0] * scale), 0)
    draw = ImageDraw.Draw(canvas)
    for segment in lines:
        if segment.get("cls") not in ROAD_CLASSES:
            continue
        polygon = [((x - bounds["min_x"]) * scale, (y - bounds["min_y"]) * scale) for x, y in segment["left"] + segment["right"][::-1]]
        if len(polygon) >= 3:
            draw.polygon(polygon, fill=255)
    return np.asarray(canvas, np.float32) / 255.0



def fill_nearest(a):
    """The array with every NaN cell given the value of the nearest finite one, and the mask of the finite cells."""
    finite = np.isfinite(a)
    if finite.all():
        return a, finite
    nearest = ndimage.distance_transform_edt(~finite, return_distances=False, return_indices=True)
    return a[tuple(nearest)], finite


def ground_on_grid(slug, xs, ys, step):
    """The bare ground of prep (1 m nodes at min + c) smoothed to the grid and sampled on it (NaN where it has none)."""
    bounds = prep_meta(slug)["bounds_m"]
    ground = np.load(os.path.join(PREP, slug, "ground.npy"), mmap_mode="r")
    return sample_points(ndimage.gaussian_filter(np.asarray(ground, np.float32), step / 2), xs, ys, bounds["min_x"], bounds["min_y"], 1.0)


def shade_fields(ground, picture, step, sea_level=None):
    """The shading reference, the picture's shading and the cells both cover, on one grid.

    The picture's band-passed log luminance is fitted as a linear function of the band-passed slopes of the ground
    (the light direction); the reference is the slopes lit so, plus, where the map has a sea, the band-passed coastline
    at half the reference's spread with the sign of its correlation with the picture.

    Args:
        ground: heights on the grid, NaN outside the landscape (left out, the slopes there taken as flat).
        picture: the picture's luminance on the grid, NaN where it has none.
        step: grid cell in metres.
        sea_level: the map's sea level (prep meta.json `sea_level_m`), or None.
    """
    ground, inside = fill_nearest(ground)
    gy, gx = np.gradient(ground, step)
    valid = np.isfinite(picture) & inside
    shading = band_pass(np.log(np.clip(np.nan_to_num(picture, nan=1.0), 1, None)))
    slopes = np.c_[band_pass(gx)[valid][::LIGHT_FIT_STRIDE], band_pass(gy)[valid][::LIGHT_FIT_STRIDE]]
    light, *_ = np.linalg.lstsq(slopes, shading[valid][::LIGHT_FIT_STRIDE], rcond=None)
    reference = band_pass(light[0] * gx + light[1] * gy)
    if sea_level is not None:
        coast = band_pass((ground > sea_level).astype(np.float32))
        correlation = np.corrcoef(coast[valid][::LIGHT_FIT_STRIDE], shading[valid][::LIGHT_FIT_STRIDE])[0, 1]
        sign = np.sign(correlation) if np.isfinite(correlation) and correlation != 0 else 1.0
        reference = reference + 0.5 * np.std(reference[valid]) / (np.std(coast[valid]) + 1e-9) * sign * coast
    return reference, shading, valid


def fitted_rectangle(rect, fit, xs, ys, step):
    """The rectangle a picture drawn over `rect` shows: each edge less the displacement there, the displacement
    carried linearly from the grid's edges (W to E, N to S) to the rectangle's edges."""
    low = (xs[0] - step / 2, ys[0] - step / 2)
    high = (xs[-1] + step / 2, ys[-1] + step / 2)

    def along(first, last, axis, value):
        return first + (last - first) * (value - low[axis]) / (high[axis] - low[axis])

    x0, y0, x1, y1 = rect
    return [round(x0 - along(fit["W"], fit["E"], 0, x0), 2), round(y0 - along(fit["N"], fit["S"], 1, y0), 2),
            round(x1 - along(fit["W"], fit["E"], 0, x1), 2), round(y1 - along(fit["N"], fit["S"], 1, y1), 2)]


def emit(record):
    """Prints one result as a JSON line."""
    print(json.dumps(record), flush=True)


def tile_mosaic(folder, zoom):
    """RGB mosaic of the served tiles of one zoom (/tiles/<folder>/<z>/<x>_<y>.webp, 256 px; black where one is missing)."""
    n = 2 ** zoom
    out = np.zeros((256 * n, 256 * n, 3), np.uint8)
    for y in range(n):
        for x in range(n):
            path = os.path.join(TILES, folder, str(zoom), f"{x}_{y}.webp")
            if os.path.exists(path):
                out[256 * y:256 * (y + 1), 256 * x:256 * (x + 1)] = np.asarray(Image.open(path).convert("RGB"))
    return out


def measure_basemaps(infos, slugs):
    """The base texture, the upstream basemap and the Detailed tiles of each map on the world, by features (module docstring)."""
    for slug in slugs:
        info = infos[slug]
        texture = client_texture(info.texture)
        basemap = upstream_image(slug, "basemap.webp")
        step = (info.game_rect[2] - info.game_rect[0]) / texture.shape[1]
        xs, ys = frame_grid(info.image_rect, step)
        reference = Features(slug, step).reference(xs, ys)
        placements = [("game", texture, info.game_rect), ("image", basemap, info.image_rect),
                      ("basemap_game", basemap, info.game_rect)]
        if os.path.exists(os.path.join(TILES, slug, "meta.json")):
            placements.append(("detailed", tile_mosaic(slug, int(round(np.log2(len(xs) / 256)))), info.image_rect))
        for picture, image, rect in placements:
            placed = sample_image(luminance(image), xs, ys, rect)
            fit, measured = register(reference, edges(np.nan_to_num(placed)), np.isfinite(placed), step)
            emit({"map": slug, "picture": picture, "texture": layer_minimaps.object_name(info.texture), "rect": list(rect),
                  "step_m": round(step, 4), "measured": measured, "fit": fit})


def measure_rect(infos, slug, source, rect, reference):
    """One picture (`basemap` or the base `texture`) over one rectangle, by features or by shade."""
    info = infos[slug]
    image = upstream_image(slug, "basemap.webp") if source == "basemap" else client_texture(info.texture)
    step = (rect[2] - rect[0]) / image.shape[1]
    xs, ys = frame_grid(info.image_rect, step)
    placed = sample_image(luminance(image), xs, ys, rect)
    if reference == "shade":
        lit, shading, valid = shade_fields(ground_on_grid(slug, xs, ys, step), placed, step, prep_meta(slug).get("sea_level_m"))
        fit, measured = register(lit, shading, valid, step)
    else:
        fit, measured = register(Features(slug, step).reference(xs, ys), edges(np.nan_to_num(placed)), np.isfinite(placed), step)
    emit({"map": slug, "picture": source, "reference": reference, "rect": list(rect), "step_m": round(step, 4),
          "measured": measured, "fit": fit, "fitted": fitted_rectangle(rect, fit, xs, ys, step) if fit else None})


def measure_layer_minimaps(infos, slugs):
    """The layer minimaps of /layer-tiles between their corners on the world, by features."""
    with open(os.path.join(LAYER_TILES, "layer-minimaps.json")) as f:
        manifest = json.load(f)
    for slug in slugs:
        layers = sorted(layer for layer in manifest["layers"] if slug_of(layer_minimaps.map_name(layer)) == slug)
        if not layers:
            continue
        info = infos[slug]
        base_m_per_px = (info.game_rect[2] - info.game_rect[0]) / texture_width(info.texture)
        fields = {}
        for layer in layers:
            entry = manifest["layers"][layer]
            rect = (*entry["min"], *entry["max"])
            image = np.asarray(Image.open(os.path.join(LAYER_TILES, entry["folder"], "0", "0_0.webp")).convert("RGB"))
            m_per_px = (rect[2] - rect[0]) / image.shape[1]
            step = max(m_per_px, LAYER_MINIMAP_MIN_STEP_M)
            if step not in fields:
                fields = {step: Features(slug, step)}
            xs, ys = frame_grid(rect, step)
            placed = sample_image(luminance(image), xs, ys, rect)
            fit, measured = register(fields[step].reference(xs, ys), edges(np.nan_to_num(placed)), np.isfinite(placed), step)
            emit({"map": slug, "layer": layer, "texture": entry["texture"], "rect": list(rect), "size": image.shape[1],
                  "m_per_px": round(m_per_px, 4), "finer": round(base_m_per_px / m_per_px, 2), "step_m": round(step, 4),
                  "measured": measured, "fit": fit})


ORIENTATIONS = [(k, mirror) for k in range(4) for mirror in (False, True)]


def orientation_name(k, mirror):
    """`rot90_mirror` for a quarter turn of np.rot90 followed by a left-right mirror."""
    return f"rot{90 * k}{'_mirror' if mirror else ''}"


def orient(image, k, mirror):
    """The image turned by k quarter turns (np.rot90), then mirrored left to right."""
    turned = np.rot90(image, k)
    return turned[:, ::-1] if mirror else turned


def locate(base, base_rect, texture, sizes, crop=(0.0, 1.0, 0.0, 1.0), step=LOCATE_STEP_M):
    """Where a texture's picture lies on a base picture, for each assumed side length of the square it shows.

    The base (luminance, pixel edges over base_rect) is resampled to `step`; the texture (luminance) is scaled to show
    `size` metres across at that step, the crop (fractions x0, x1, y0, y1 of it) is taken, and each of the 8
    orientations of the crop is searched over the whole base by normalised cross-correlation of edge images.

    Returns:
        A list per size of {"size_m", "ncc": {orientation: peak}, "best": {"orientation", "ncc", "shows"}}, `shows`
        the rectangle (min x, min y, max x, max y) the whole oriented texture covers at the peak.
    """
    xs = np.arange(base_rect[0] + step / 2, base_rect[2], step)
    ys = np.arange(base_rect[1] + step / 2, base_rect[3], step)
    base_edges = edges(np.nan_to_num(sample_image(base, xs, ys, base_rect)), 1.0)
    h, w = texture.shape
    results = []
    for size in sizes:
        scaled = ndimage.zoom(texture, (size * h / w / step / h, size / step / w), order=1)
        sh, sw = scaled.shape
        rows, cols = slice(int(crop[2] * sh), int(crop[3] * sh)), slice(int(crop[0] * sw), int(crop[1] * sw))
        index = np.arange(sh * sw).reshape(sh, sw)
        energy = {}
        trials = {}
        for k, mirror in ORIENTATIONS:
            template = edges(orient(scaled[rows, cols], k, mirror), 1.0)
            template = template - template.mean()
            if template.shape not in energy:
                ones = np.ones_like(template)
                s1 = signal.fftconvolve(base_edges, ones, mode="valid")
                s2 = signal.fftconvolve(base_edges * base_edges, ones, mode="valid")
                energy[template.shape] = np.maximum(s2 - s1 * s1 / template.size, 1e-9)
            ncc = signal.fftconvolve(base_edges, template[::-1, ::-1], mode="valid") / np.sqrt(energy[template.shape] * (template * template).sum())
            j, i = np.unravel_index(np.argmax(ncc), ncc.shape)
            whole = orient(index, k, mirror)
            offset_row, offset_col = np.argwhere(whole == orient(index[rows, cols], k, mirror)[0, 0])[0]
            x0 = xs[0] - step / 2 + (i - offset_col) * step
            y0 = ys[0] - step / 2 + (j - offset_row) * step
            trials[orientation_name(k, mirror)] = (float(ncc[j, i]), [round(float(x0), 1), round(float(y0), 1), round(float(x0 + whole.shape[1] * step), 1),
                                                                      round(float(y0 + whole.shape[0] * step), 1)])
        best = max(trials, key=lambda name: trials[name][0])
        results.append({"size_m": float(size), "ncc": {name: round(peak, 3) for name, (peak, _) in trials.items()},
                        "best": {"orientation": best, "ncc": round(trials[best][0], 3), "shows": trials[best][1]}})
    return results


def measure_locate(infos, slug, texture_name, rect, sizes, crop):
    """Where a texture shows the map, and how far its content lies from there when drawn over `rect`."""
    info = infos[slug]
    results = locate(luminance(client_texture(info.texture)), info.game_rect, luminance(client_texture(texture_name)), sizes, crop)
    for result in results:
        emit({"map": slug, "texture": texture_name, **result})
    best = max(results, key=lambda result: result["best"]["ncc"])
    shows = best["best"]["shows"]
    emit({"map": slug, "texture": texture_name, "drawn": list(rect), "size_m": best["size_m"], **best["best"],
          "W": round(rect[0] - shows[0], 1), "E": round(rect[2] - shows[2], 1), "N": round(rect[1] - shows[1], 1), "S": round(rect[3] - shows[3], 1)})


def correlation(a, b):
    """Pearson correlation of two arrays of one shape."""
    a, b = a - a.mean(), b - b.mean()
    return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))


def compare_orientation(texture, picture):
    """The orientation of `picture` (luminance) that matches `texture` (luminance) and the geometry of the match.

    Returns {"orientation", "correlation", "correlations", "windows", "offset_px", "across_px", "rms_px"}: the
    correlations of ORIENTATION_THUMB_PX thumbnails over the 8 orientations of the picture; then the picture in the
    best orientation, resampled to the texture's size, against the texture in ORIENTATION_WINDOWS^2 windows of edges
    (the picture's content shift, + = east or south), fitted per axis as the offset at the centre plus a change across
    the image (in px of the texture: 0 and 0 for the same picture).
    """
    thumb_texture = ndimage.zoom(texture, ORIENTATION_THUMB_PX / texture.shape[0], order=1)
    thumb_picture = ndimage.zoom(picture, ORIENTATION_THUMB_PX / picture.shape[0], order=1)
    correlations = {orientation_name(k, mirror): round(correlation(thumb_texture, orient(thumb_picture, k, mirror)), 3)
                    for k, mirror in ORIENTATIONS if orient(thumb_picture, k, mirror).shape == thumb_texture.shape}
    best = max(correlations, key=correlations.get)
    k, mirror = next(o for o in ORIENTATIONS if orientation_name(*o) == best)
    oriented = orient(picture, k, mirror)
    if oriented.shape != texture.shape:
        oriented = ndimage.zoom(oriented, (texture.shape[0] / oriented.shape[0], texture.shape[1] / oriented.shape[1]), order=1)
    texture_edges, picture_edges = edges(texture), edges(oriented)
    h, w = texture.shape
    side, n = ORIENTATION_WINDOW_PX, ORIENTATION_WINDOWS
    shifts = []
    for j in range(n):
        for i in range(n):
            y, x = int((h - side) * j / (n - 1)), int((w - side) * i / (n - 1))
            window = (slice(y, y + side), slice(x, x + side))
            dx, dy, peak, _, at_edge = ncc_shift(picture_edges[window], texture_edges[window], ORIENTATION_SEARCH_PX)
            if peak > ORIENTATION_MIN_PEAK and not at_edge:
                shifts.append(((x + side / 2) / w, (y + side / 2) / h, dx, dy))
    result = {"orientation": best, "correlation": correlations[best], "correlations": correlations, "windows": len(shifts)}
    if len(shifts) >= MIN_FIT_WINDOWS:
        s = np.asarray(shifts)
        fits = []
        for position, shift in ((0, 2), (1, 3)):
            design = np.c_[np.ones(len(s)), s[:, position] - 0.5]
            coef, *_ = np.linalg.lstsq(design, s[:, shift], rcond=None)
            fits.append((coef, float(np.sqrt(((s[:, shift] - design @ coef) ** 2).mean()))))
        result.update({"offset_px": [round(float(c[0]), 3) for c, _ in fits], "across_px": [round(float(c[1]), 3) for c, _ in fits],
                       "rms_px": [round(r, 3) for _, r in fits]})
    return result


def measure_orientation(infos, slugs):
    """The upstream basemap of each map against the client's base texture."""
    for slug in slugs:
        info = infos[slug]
        texture, basemap = luminance(client_texture(info.texture)), luminance(upstream_image(slug, "basemap.webp"))
        emit({"map": slug, "texture": layer_minimaps.object_name(info.texture), "texture_px": list(texture.shape[::-1]),
              "basemap_px": list(basemap.shape[::-1]), **compare_orientation(texture, basemap)})


def upstream_heightmap(rgb):
    """Heights (8-bit levels, float32) of upstream's heightmap.png: 255 + red - blue."""
    rgb = rgb.astype(np.float32)
    return 255 + rgb[..., 0] - rgb[..., 2]


def measure_upstream_relief(infos, slugs):
    """Upstream's 8-bit heightmap against the ground, and the shading of its terrain and topographic maps against it."""
    for slug in slugs:
        info = infos[slug]
        x0, y0, x1, y1 = info.image_rect
        step = max((x1 - x0) / UPSTREAM_GRID_PX, 1.0)
        xs, ys = frame_grid(info.image_rect, step)
        bounds = prep_meta(slug)["bounds_m"]
        ground = np.load(os.path.join(PREP, slug, "ground.npy"), mmap_mode="r")
        gnd = sample_points(ndimage.gaussian_filter(np.asarray(ground, np.float32), step / 2), xs, ys, bounds["min_x"], bounds["min_y"], 1.0)
        levels = upstream_heightmap(upstream_image(slug, "heightmap.png"))
        h, w = levels.shape
        spacing_x, spacing_y = (x1 - x0) / (w - 1), (y1 - y0) / (h - 1)
        hm8 = sample_points(ndimage.gaussian_filter(levels, (0.5 * step / spacing_y, 0.5 * step / spacing_x)), xs, ys, x0, y0, spacing_x, spacing_y)
        valid = np.isfinite(gnd) & np.isfinite(hm8)
        fit, measured = register(band_pass(gnd), band_pass(hm8), valid, step, UPSTREAM_SEARCH_M, UPSTREAM_MIN_PEAK)
        common = {"map": slug, "step_m": round(step, 4)}
        emit({**common, "picture": "heightmap", "heightmap_px": [w, h], "measured": measured, "fit": fit})
        base = sample_image(luminance(upstream_image(slug, "basemap.webp")), xs, ys, info.image_rect)
        terrain = sample_image(luminance(upstream_image(slug, "terrainmap.webp")), xs, ys, info.image_rect)
        topo = sample_image(luminance(upstream_image(slug, "topomap.webp")), xs, ys, info.image_rect)
        gy, gx = np.gradient(np.nan_to_num(hm8, nan=float(np.nanmean(hm8))), step)
        covered = valid & np.isfinite(topo)
        slopes = np.c_[band_pass(gx)[covered][::UPSTREAM_LIGHT_STRIDE], band_pass(gy)[covered][::UPSTREAM_LIGHT_STRIDE]]
        shadings = (("terrain_shade", np.log(np.clip(np.nan_to_num(terrain), 1, None) / np.clip(np.nan_to_num(base), 1, None))),
                    ("topo_shade", np.log(np.clip(np.nan_to_num(topo), 1, None))))
        for picture, shading in shadings:
            light, *_ = np.linalg.lstsq(slopes, band_pass(shading)[covered][::UPSTREAM_LIGHT_STRIDE], rcond=None)
            fit, measured = register(band_pass(light[0] * gx + light[1] * gy), band_pass(shading), covered, step,
                                     UPSTREAM_SEARCH_M, UPSTREAM_MIN_PEAK)
            emit({**common, "picture": picture, "measured": measured, "fit": fit})


def pmtiles_mosaic(path, zoom):
    """Luminance (float32, NaN where a tile is missing) of the tiles of one zoom of a PMTiles archive as one image."""
    n = 1 << zoom
    out = np.full((256 * n, 256 * n), np.nan, np.float32)
    with open(path, "rb") as handle:
        reader = Reader(MmapSource(handle))
        for y in range(n):
            for x in range(n):
                data = reader.get(zoom, x, y)
                if data:
                    out[256 * y:256 * (y + 1), 256 * x:256 * (x + 1)] = luminance(np.asarray(Image.open(io.BytesIO(data)).convert("RGB")))
    return out


def measure_relief(infos, slugs, source):
    """The relief layer of each map against the MDOW hillshade and the layer's own shading of the ground or heightmap."""
    for slug in slugs:
        info = infos[slug]
        image = pmtiles_mosaic(os.path.join(TILES, "relief", f"{slug}.pmtiles"), RELIEF_ZOOM)
        x0, y0, x1, y1 = info.image_rect
        step = max(x1 - x0, y1 - y0) / image.shape[1]
        xs, ys = frame_grid(info.image_rect, step)
        placed = sample_image(image, xs, ys, info.image_rect)
        if source == "heightmap":
            heights, meta = topometrics.load_heightmap(os.path.join(HEIGHTMAPS, slug))
            bounds, cell = meta["bounds_m"], meta["resolution_m"]
        else:
            heights = np.load(os.path.join(PREP, slug, "ground.npy")).astype(np.float64)
            bounds, cell = prep_meta(slug)["bounds_m"], 1.0
        heights, inside = fill_nearest(heights)
        hillshade, sky = relief.shade_map(heights, cell)
        shadings = {"mdow": hillshade, "layer": relief.blend(hillshade, sky)}
        del sky

        def on_grid(field):
            return sample_points(ndimage.gaussian_filter(field.astype(np.float32), step / 2 / cell), xs, ys, bounds["min_x"], bounds["min_y"], cell)

        valid = np.isfinite(placed) & (on_grid(inside.astype(np.float32)) > 1 - 1e-3)
        del heights, inside
        shading = band_pass(np.log(np.clip(np.nan_to_num(placed, nan=1.0), 1, None)))
        for picture in ("mdow", "layer"):
            reference = on_grid(shadings.pop(picture))
            # the hillshade as it is; the layer's shade, which the tiles store, in log as the tiles are compared
            if picture == "layer":
                reference = np.log(np.clip(reference, 1e-3, None))
            fit, measured = register(band_pass(reference), shading, valid, step)
            emit({"map": slug, "picture": picture, "source": source, "zoom": RELIEF_ZOOM, "step_m": round(step, 4),
                  "measured": measured, "fit": fit})


def print_textures():
    """Prints the pak path pattern of every minimap texture the levels and the layer data name."""
    with open(os.path.join(LAYER_MINIMAPS, "layers.tsv")) as f:
        levels = layer_minimaps.parse_layer_table(f.read())
    overrides = layer_minimaps.read_layer_data(os.path.join(LAYER_MINIMAPS, "layerdata"))
    textures = {minimap.texture for minimap in levels.values()} | {o.texture for o in overrides.values() if o.texture}
    print(layer_minimaps.pak_pattern(textures))


def parse_sizes(text):
    """Side lengths in metres from `a:b:step` (b included) or a comma-separated list."""
    if ":" in text:
        first, last, step = map(float, text.split(":"))
        return list(np.arange(first, last + step / 2, step))
    return [float(v) for v in text.split(",")]


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="measure", required=True)
    commands.add_parser("textures")
    for name in ("basemaps", "layer-minimaps", "orientation", "upstream-relief"):
        commands.add_parser(name).add_argument("maps", nargs="*")
    relief_parser = commands.add_parser("relief")
    relief_parser.add_argument("maps", nargs="*")
    relief_parser.add_argument("--reference", choices=("ground", "heightmap"), default="ground")
    rect_parser = commands.add_parser("rect")
    rect_parser.add_argument("map")
    rect_parser.add_argument("picture", choices=("basemap", "texture"))
    rect_parser.add_argument("rect", nargs=4, type=float, metavar=("MIN_X", "MIN_Y", "MAX_X", "MAX_Y"))
    rect_parser.add_argument("--reference", choices=("features", "shade"), default="features")
    locate_parser = commands.add_parser("locate")
    locate_parser.add_argument("map")
    locate_parser.add_argument("texture")
    locate_parser.add_argument("rect", nargs=4, type=float, metavar=("MIN_X", "MIN_Y", "MAX_X", "MAX_Y"))
    locate_parser.add_argument("sizes", type=parse_sizes)
    locate_parser.add_argument("--crop", nargs=4, type=float, default=(0.0, 1.0, 0.0, 1.0), metavar=("X0", "X1", "Y0", "Y1"))
    args = parser.parse_args(argv)
    if args.measure == "textures":
        print_textures()
        return
    infos = read_map_infos()
    if args.measure == "rect":
        measure_rect(infos, args.map, args.picture, tuple(args.rect), args.reference)
    elif args.measure == "locate":
        measure_locate(infos, args.map, args.texture, tuple(args.rect), args.sizes, tuple(args.crop))
    else:
        slugs = args.maps or sorted(maps.MAPS)
        missing = [slug for slug in slugs if slug not in infos]
        if missing:
            raise SystemExit(f"no layer table entry or prep rasters for {', '.join(missing)}")
        if args.measure == "basemaps":
            measure_basemaps(infos, slugs)
        elif args.measure == "layer-minimaps":
            measure_layer_minimaps(infos, slugs)
        elif args.measure == "orientation":
            measure_orientation(infos, slugs)
        elif args.measure == "upstream-relief":
            measure_upstream_relief(infos, slugs)
        else:
            measure_relief(infos, slugs, args.reference)


if __name__ == "__main__":
    main(sys.argv[1:])
