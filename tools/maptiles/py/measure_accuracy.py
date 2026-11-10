"""Accuracy of the served detailed tiles against references that share no drawing code with them.

Usage: measure_accuracy.py <measure> <map> [<map> ...]   (writes /check/<map>_<measure>.json and prints it)

Measures (container paths as check_alignment.py: /tiles, /hd, /prep, /heightmaps, /check):

roads     Road splines of top_lines.json against the Standard HD layer. At straight stretches with no other spline near, the colour
          profile across the road (averaged along STRIP_ALONG_M of it) is taken from the finest tiles and from HD. Centreline: the
          shift of the cross-correlation peak of the two profiles' edge strengths, as a world offset (east, south; positive where
          the tiles lie east or south of HD, the sign of the HD gate). Width: in each picture the distance between the two points
          where the profile is halfway from the ground's colour (outside the road) to the road's (its middle).
water     The tiles' water (the renderer's water colours) against HD's on the whole map at a pixel of 0.5 to 1.7 m: intersection over
          union, and the distance from HD's shoreline to the tiles'. HD's water colours are learned from the map itself: the
          colour bins most of whose pixels lie inside the tiles' water and that fill its core (hd_water_lookup), so the measure
          is of the outline, not of whether HD has water at all.
crowns    Tree crowns at trees with no other crown near, on the picture of the crown (the colour distance from the ground around
          it). Against the scene's foliage instances: whether the crown is drawn, and the mean offset of its centroid from the
          instance's pivot (a mesh is not symmetric about its pivot, but the instances' yaws are, so a mean far from zero is a
          misplacement). Against HD: the cross-correlation peak of the two layers' pictures, split into the component across the
          light (the placement) and along it (HD darkens the ground south-east of a crown, the tiles do not).
heights   Roof height labels (client meshes) against the served precise heightmap (server collision, another game build and
          another rasterizer): the 98th percentile of the heightmap's rise over the bare ground in the building under the label.
contours  Contour lines against the served heightmap: the pixels of the lines are found by colour on open ground, the heightmap
          gives the height under each, and the interval is the one of CONTOUR_LADDER whose multiples they lie closest to. The
          error of a pixel is its distance to the nearest true level line, |height - level| / slope.

Every summary carries the number of samples and a 95 % bootstrap interval of its median (bootstrap_ci), so a table can state
the uncertainty and not only the median.
"""

import json
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage, spatial

import check_alignment
import compare_crops
import render

ROAD_CLASSES = ("asphalt", "dirt", "pavement")
STATION_STEP_M = 20.0      # a station every so many metres of a road spline ...
STATION_REACH_M = 6.0      # ... where the road this far before and after it ...
STATION_BEND_DEG = 4.0     # ... turns by less than this
ROAD_CLEAR_M = 10.0        # no other spline within the half width plus this
ROAD_MARGIN_M = 6.0        # profile reach beyond the road's edge
STRIP_ALONG_M = 6.0        # length of road a profile is averaged over
PROFILE_STEP_M = 0.05
ROAD_SEARCH_M = 2.0
ROAD_MIN_PEAK = 0.3
ROAD_MIN_CONTRAST = 12.0   # RGB distance between the road's and the ground's colour for a width measurement
STATIONS_PER_MAP = 240
WATER_PIXEL_M = 1.0        # the water comparison uses the first zoom whose pixel is at most this ...
WATER_MAX_ZOOM = 4         # ... but no finer than a mosaic of 4096 px a side (Skorpo, 6.9 km: 1.7 m per pixel)
WATER_TOLERANCE = 22.0     # RGB distance of a tile pixel to the renderer's water colours
WATER_BIN = 4              # HD colours are binned to this many levels per bin
WATER_MIN_PX = 200
WATER_MIN_SHARE = 0.0005   # a map with less water than this share of its area has no water to compare
CROWN_MIN_RADIUS_M = 1.5
CROWN_CLEAR_M = 1.0
CROWN_PIXEL_M = 0.1
CROWNS_PER_MAP = 300
CROWN_MIN_PEAK = 0.3
CROWN_MIN_CONTRAST = 18.0  # RGB distance from the ground's colour that makes a pixel part of a crown
CROWN_MIN_SHARE = 0.15     # a crown is drawn when this share of its reach disc differs from the ground
HEIGHT_OBJECT_M = 2.0      # the heightmap's objects, as check_alignment
HEIGHT_MIN_DEPTH_M = 3.0   # labels of roofs at least this deep
CONTOUR_WINDOWS = 48
CONTOUR_WINDOW_PX = 512
CONTOUR_MIN_ALPHA = 0.3
CONTOUR_MAX_RESIDUAL = 14.0
BOOTSTRAP = 2000


def bootstrap_ci(values, statistic=np.median, draws=BOOTSTRAP, seed=0):
    """95 % percentile bootstrap interval [low, high] of a statistic of the values (None for fewer than three)."""
    values = np.asarray(values, np.float64)
    if len(values) < 3:
        return None
    rng = np.random.default_rng(seed)
    samples = statistic(values[rng.integers(0, len(values), (draws, len(values)))], axis=1)
    return [round(float(np.percentile(samples, 2.5)), 4), round(float(np.percentile(samples, 97.5)), 4)]


def summary(values, digits=3):
    """{n, median, ci95 of the median, mad (median absolute deviation), p90 of the absolute values} of a sample."""
    values = np.asarray(values, np.float64)
    if not len(values):
        return {"n": 0}
    median = float(np.median(values))
    return {"n": int(len(values)), "median": round(median, digits), "ci95": bootstrap_ci(values),
            "mad": round(float(np.median(np.abs(values - median))), digits), "p90_abs": round(float(np.percentile(np.abs(values), 90)), digits)}


def mean_summary(values, digits=3):
    """{n, mean, ci95 of the mean, sd} of a sample."""
    values = np.asarray(values, np.float64)
    if not len(values):
        return {"n": 0}
    return {"n": int(len(values)), "mean": round(float(values.mean()), digits), "ci95": bootstrap_ci(values, np.mean), "sd": round(float(values.std()), digits)}


def resampled(points, step_m=1.0):
    """A polyline [n, k] resampled at equal steps of about step_m along its first two coordinates, both ends kept."""
    points = np.asarray(points, np.float64)
    along = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(points[:, :2], axis=0).T))])
    at = np.linspace(0.0, along[-1], max(2, int(round(along[-1] / step_m)) + 1))
    return np.stack([np.interp(at, along, points[:, k]) for k in range(points.shape[1])], 1)


def road_stations(lines, limit=STATIONS_PER_MAP, seed=0):
    """Stations [(class, x, y, tangent x, tangent y, drawn half width)] on straight, lone stretches of the road splines.

    Every STATION_STEP_M along a spline segment's centre line, where the road within STATION_REACH_M on both sides turns by less
    than STATION_BEND_DEG and no other spline comes within the half width plus ROAD_CLEAR_M of the station outside the road's own
    corridor (the next segment of the same road lies in it). At most ``limit``, drawn at random.
    """
    centres = [resampled(np.asarray(line["center"], np.float64)[:, :2]) for line in lines]
    if not centres:
        return []
    owner = np.concatenate([np.full(len(c), index) for index, c in enumerate(centres)])
    points = np.concatenate(centres)
    tree = spatial.cKDTree(points)
    reach = int(STATION_REACH_M)
    stations = []
    for index, line in enumerate(lines):
        centre = centres[index]
        if line["cls"] not in ROAD_CLASSES or len(centre) < 2 * reach + 1:
            continue
        width = resampled(np.concatenate([np.asarray(line["center"], np.float64)[:, :2],
                                          np.hypot(*(np.asarray(line["left"], np.float64)[:, :2] - np.asarray(line["right"], np.float64)[:, :2]).T)[:, None]], 1))[:, 2]
        for k in range(reach, len(centre) - reach, int(STATION_STEP_M)):
            before, after = centre[k] - centre[k - reach], centre[k + reach] - centre[k]
            turn = abs((math.degrees(math.atan2(after[1], after[0]) - math.atan2(before[1], before[0])) + 180) % 360 - 180)
            if turn > STATION_BEND_DEG:
                continue
            tangent = (before + after) / np.hypot(*(before + after))
            half = width[k] / 2
            near = np.array([j for j in tree.query_ball_point(centre[k], half + ROAD_CLEAR_M) if owner[j] != index], np.int64)
            if len(near) and (np.abs((points[near] - centre[k]) @ np.array([-tangent[1], tangent[0]])) > half + 1.0).any():
                continue
            stations.append((line["cls"], centre[k, 0], centre[k, 1], tangent[0], tangent[1], half))
    if len(stations) > limit:
        stations = [stations[i] for i in sorted(np.random.default_rng(seed).choice(len(stations), limit, replace=False))]
    return stations


def cross_profile(folder, station):
    """Mean colour [n, 3] across the road at a station, at PROFILE_STEP_M from -(half + ROAD_MARGIN_M) to +(half + ROAD_MARGIN_M)
    along the left-hand normal (-ty, tx), averaged over STRIP_ALONG_M of road; and the offsets [n] in metres."""
    _, x, y, tx, ty, half = station
    reach = half + ROAD_MARGIN_M
    size_m = 2 * (reach + STRIP_ALONG_M)
    size_px = int(round(size_m / PROFILE_STEP_M))
    picture = np.asarray(compare_crops.window(folder, (x, y), size_m, size_px), np.float32)
    across = np.arange(-reach, reach + PROFILE_STEP_M / 2, PROFILE_STEP_M)
    along = np.arange(-STRIP_ALONG_M / 2, STRIP_ALONG_M / 2 + 0.01, 0.25)
    wx = x + across[:, None] * -ty + along[None, :] * tx
    wy = y + across[:, None] * tx + along[None, :] * ty
    cols = (wx - (x - size_m / 2)) / PROFILE_STEP_M - 0.5
    rows = (wy - (y - size_m / 2)) / PROFILE_STEP_M - 0.5
    profile = np.stack([ndimage.map_coordinates(picture[..., c], [rows, cols], order=1, mode="nearest").mean(1) for c in range(3)], -1)
    return profile, across


def profile_shift(ours, theirs, step_m=PROFILE_STEP_M, search_m=ROAD_SEARCH_M):
    """(shift in metres, normalised peak) of the cross-correlation of two profiles' edge strengths: positive when ``ours`` lies
    towards larger offsets than ``theirs``."""
    def edges(profile):
        smooth = ndimage.gaussian_filter1d(profile, 0.15 / step_m, axis=0)
        strength = np.linalg.norm(np.gradient(smooth, axis=0), axis=1)
        return strength - strength.mean()
    a, b = edges(ours), edges(theirs)
    search = int(round(search_m / step_m))
    lags = np.arange(-search, search + 1)
    corr = np.array([np.sum(a[max(0, k):len(a) + min(0, k)] * b[max(0, -k):len(b) + min(0, -k)]) for k in lags])
    i = int(corr.argmax())
    fine = 0.0
    if 0 < i < len(corr) - 1 and corr[i - 1] != corr[i + 1]:
        fine = 0.5 * (corr[i - 1] - corr[i + 1]) / (corr[i - 1] - 2 * corr[i] + corr[i + 1])
    peak = float(corr[i] / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-9))
    return float((lags[i] + fine) * step_m), peak


def profile_width(profile, across, half):
    """Width (m) of the road in a profile: between the points nearest its middle on each side where the colour is halfway from the
    ground's (beyond half + ROAD_MARGIN_M / 2) to the road's (within 0.4 of the half width). None when the two colours are closer
    than ROAD_MIN_CONTRAST or a side has no crossing."""
    ground = profile[np.abs(across) > half + ROAD_MARGIN_M / 2].mean(0)
    road = profile[np.abs(across) < 0.4 * half].mean(0)
    axis = road - ground
    if np.linalg.norm(axis) < ROAD_MIN_CONTRAST:
        return None
    level = (profile - ground) @ axis / (axis @ axis)
    centre = len(across) // 2
    edges = []
    for direction in (-1, 1):
        k = centre
        while 0 < k < len(across) - 1 and level[k] >= 0.5:
            k += direction
        if level[k] >= 0.5:
            return None
        inside = k - direction
        t = (level[inside] - 0.5) / max(level[inside] - level[k], 1e-9)
        edges.append(across[inside] + t * (across[k] - across[inside]))
    return float(edges[1] - edges[0])


def measure_roads(slug):
    tiles, hd = os.path.join("/tiles", slug), os.path.join(check_alignment.HD_DIR, f"{slug}-hd")
    lines = json.load(open(os.path.join("/prep", slug, "top_lines.json")))
    report = {"map": slug, "measure": "roads", "classes": {}}
    rows = []
    for station in road_stations(lines):
        ours, across = cross_profile(tiles, station)
        theirs, _ = cross_profile(hd, station)
        cls, _, _, tx, ty, half = station
        shift, peak = profile_shift(ours, theirs)
        measured = peak >= ROAD_MIN_PEAK and abs(shift) < ROAD_SEARCH_M - PROFILE_STEP_M
        rows.append({"cls": cls, "dx": shift * -ty if measured else None, "dy": shift * tx if measured else None, "drawn": 2 * half,
                     "ours": profile_width(ours, across, half), "theirs": profile_width(theirs, across, half)})
    report["stations"] = len(rows)
    for cls in ROAD_CLASSES + ("all",):
        chosen = [r for r in rows if cls in ("all", r["cls"])]
        shifts = [(r["dx"], r["dy"]) for r in chosen if r["dx"] is not None]
        both = [r for r in chosen if r["ours"] is not None and r["theirs"] is not None]
        report["classes"][cls] = {
            "stations": len(chosen),
            "centre_dx_m": summary([s[0] for s in shifts]), "centre_dy_m": summary([s[1] for s in shifts]),
            "centre_abs_m": summary([math.hypot(*s) for s in shifts]),
            "width_tiles_minus_hd_m": summary([r["ours"] - r["theirs"] for r in both]),
            "width_tiles_over_hd": summary([r["ours"] / r["theirs"] for r in both]),
            "width_tiles_over_drawn": summary([r["ours"] / r["drawn"] for r in chosen if r["ours"] is not None]),
        }
    return report


def tile_water(rgb):
    """Bool [H, W]: pixels of the renderer's water, within WATER_TOLERANCE of the line from the shallow to the deep water colour."""
    a, b = np.asarray(render.WATER_RGB, np.float32), np.asarray(render.WATER_DEEP_RGB, np.float32)
    p = rgb.astype(np.float32) - a
    axis = b - a
    t = np.clip(p @ axis / (axis @ axis), 0, 1)
    return np.linalg.norm(p - t[..., None] * axis, axis=-1) < WATER_TOLERANCE


def colour_bins(rgb):
    """Index [H, W] of each pixel's colour bin (WATER_BIN levels a side) in a table of (256 // WATER_BIN) ** 3 bins."""
    n = 256 // WATER_BIN
    bins = (rgb // WATER_BIN).astype(np.uint32)
    return (bins[..., 0] * n + bins[..., 1]) * n + bins[..., 2]


def hd_water_lookup(hd_rgb, seed, valid):
    """Bool table [(256 // WATER_BIN) ** 3] of the HD layer's water colours by colour_bins.

    A bin is water when at least WATER_MIN_PX of its pixels lie in the core of ``seed`` (the tiles' water, 3 px inside) and at
    least half of all its valid pixels lie in ``seed``: a colour that is as common on land (snow, sand, roofs) is not water.
    """
    size = (256 // WATER_BIN) ** 3
    index = colour_bins(hd_rgb)
    core = ndimage.binary_erosion(seed, iterations=3) & valid
    in_core = np.bincount(index[core], minlength=size)
    in_seed = np.bincount(index[seed & valid], minlength=size)
    everywhere = np.bincount(index[valid], minlength=size)
    return (in_core >= WATER_MIN_PX) & (in_seed * 2 >= everywhere)


def water_agreement(ours, theirs, valid, pixel_m):
    """{iou, shares, shoreline distance} of two water masks on valid pixels; the distance (m) is from each shore pixel of
    ``theirs`` (of its runs of WATER_MIN_PX and more) to the nearest shore pixel of ``ours``."""
    ours, theirs = ours & valid, theirs & valid
    union = int((ours | theirs).sum())
    report = {"tiles_px": int(ours.sum()), "hd_px": int(theirs.sum()), "iou": round(int((ours & theirs).sum()) / max(union, 1), 4),
              "hd_water_in_tiles": round(int((ours & theirs).sum()) / max(int(theirs.sum()), 1), 4),
              "tiles_water_in_hd": round(int((ours & theirs).sum()) / max(int(ours.sum()), 1), 4)}
    labels, count = ndimage.label(theirs)
    large = np.zeros(count + 1, bool)
    large[1:] = np.bincount(labels.ravel(), minlength=count + 1)[1:] >= WATER_MIN_PX
    theirs = large[labels]
    shore = lambda mask: mask & ~ndimage.binary_erosion(mask) & ndimage.binary_erosion(valid, iterations=2)
    our_shore, their_shore = shore(ours), shore(theirs)
    if our_shore.any() and their_shore.any():
        distance = ndimage.distance_transform_edt(~our_shore)[their_shore] * pixel_m
        report["shore_distance_m"] = summary(distance, 2)
    return report


def measure_water(slug):
    tiles, hd = os.path.join("/tiles", slug), os.path.join(check_alignment.HD_DIR, f"{slug}-hd")
    meta, hd_meta = json.load(open(os.path.join(tiles, "meta.json"))), json.load(open(os.path.join(hd, "meta.json")))
    size = meta["bounds_m"]["max_x"] - meta["bounds_m"]["min_x"]
    z = min(render.finest_zoom(size, WATER_PIXEL_M), WATER_MAX_ZOOM, meta["maxNativeZoom"], hd_meta["maxNativeZoom"])
    n = 2 ** z
    ours_rgb, hd_rgb = check_alignment.mosaic(tiles, z, 0, 0, n), check_alignment.mosaic(hd, z, 0, 0, n)
    valid = hd_rgb.any(-1)
    ours = ndimage.binary_opening(tile_water(ours_rgb))
    report = {"map": slug, "measure": "water", "zoom": z, "pixel_m": round(size / (256 * n), 3), "tiles_water_share": round(float(ours.mean()), 5)}
    if ours.mean() < WATER_MIN_SHARE:
        return report | {"water": False}
    lookup = hd_water_lookup(hd_rgb, ours, valid)
    theirs = ndimage.binary_opening(lookup[colour_bins(hd_rgb)])
    return report | {"water": True, "hd_colour_bins": int(lookup.sum())} | water_agreement(ours, theirs, valid, size / (256 * n))


def lone_crowns(crowns, bounds, limit=CROWNS_PER_MAP, seed=0):
    """Indices of the trees (conifer, deciduous, palm; crown radius CROWN_MIN_RADIUS_M and more) with no other crown or rock
    within the two radii plus CROWN_CLEAR_M, inside the map; at most ``limit``, drawn at random."""
    x, y, radius = crowns["x"].astype(np.float64), crowns["y"].astype(np.float64), crowns["radius"].astype(np.float64)
    tree = spatial.cKDTree(np.stack([x, y], 1))
    trees = np.isin(crowns["cls"], (0, 1, 4)) & (radius >= CROWN_MIN_RADIUS_M)
    reach = float(radius.max()) if len(radius) else 0.0
    chosen = []
    for i in np.random.default_rng(seed).permutation(np.flatnonzero(trees)):
        margin = 2 * radius[i] + 4
        if not (bounds["min_x"] + margin < x[i] < bounds["max_x"] - margin and bounds["min_y"] + margin < y[i] < bounds["max_y"] - margin):
            continue
        near = [j for j in tree.query_ball_point((x[i], y[i]), radius[i] + reach + CROWN_CLEAR_M) if j != i]
        if all(math.hypot(x[j] - x[i], y[j] - y[i]) > radius[i] + radius[j] + CROWN_CLEAR_M for j in near):
            chosen.append(int(i))
            if len(chosen) == limit:
                break
    return chosen


def crown_picture(folder, x, y, radius):
    """Distance [n, n] of each pixel's colour from the ground's around a crown (the median colour of the ring from radius + 1 to
    radius + 2 m), on CROWN_PIXEL_M pixels in a window of twice (radius + 2) metres."""
    size_m = 2 * (radius + 2)
    n = int(round(size_m / CROWN_PIXEL_M))
    picture = np.asarray(compare_crops.window(folder, (x, y), size_m, n), np.float32)
    rows, cols = np.mgrid[:n, :n]
    distance = np.hypot(rows + 0.5 - n / 2, cols + 0.5 - n / 2) * CROWN_PIXEL_M
    ground = np.median(picture[(distance > radius + 1) & (distance < radius + 2)], axis=0)
    return np.linalg.norm(picture - ground, axis=-1)


def crown_centroid(picture, radius):
    """(dx, dy, area share) of a crown in a crown_picture: the centroid (m east and south of the window's centre, the instance's
    pivot) of the pixels within the crown's radius that differ from the ground by CROWN_MIN_CONTRAST and more, and their share
    of the disc of that radius; None when fewer than CROWN_MIN_SHARE of the disc differ (no crown drawn)."""
    n = picture.shape[0]
    rows, cols = np.mgrid[:n, :n]
    east, south = (cols + 0.5 - n / 2) * CROWN_PIXEL_M, (rows + 0.5 - n / 2) * CROWN_PIXEL_M
    disc = np.hypot(east, south) <= radius + 0.5
    crown = disc & (picture >= CROWN_MIN_CONTRAST)
    share = float(crown.sum() / max(int((np.hypot(east, south) <= radius).sum()), 1))
    if share < CROWN_MIN_SHARE:
        return None
    return float(east[crown].mean()), float(south[crown].mean()), share


def measure_crowns(slug):
    tiles, hd = os.path.join("/tiles", slug), os.path.join(check_alignment.HD_DIR, f"{slug}-hd")
    crowns = np.load(os.path.join("/prep", slug, "crowns.npz"))
    bounds = json.load(open(os.path.join(tiles, "meta.json")))["bounds_m"]
    chosen = lone_crowns(crowns, bounds)
    offsets, centroids = [], []
    for i in chosen:
        x, y, radius = float(crowns["x"][i]), float(crowns["y"][i]), float(crowns["radius"][i])
        ours, theirs = crown_picture(tiles, x, y, radius), crown_picture(hd, x, y, radius)
        centroid = crown_centroid(ours, radius)
        if centroid is not None:
            centroids.append(centroid)
        search = int(min(20, ours.shape[0] // 4))
        dx, dy, peak = check_alignment.peak_offset(ours, theirs, search)
        if peak >= CROWN_MIN_PEAK and max(abs(dx), abs(dy)) < search - 0.5:
            offsets.append((dx * CROWN_PIXEL_M, dy * CROWN_PIXEL_M))
    # HD lights its crowns from the north-west and darkens the ground to their south-east, the tiles cast no crown shadow: along
    # that axis the correlation measures the shadow, across it (north-east to south-west) the crown's place
    across = [(dx - dy) / math.sqrt(2) for dx, dy in offsets]
    along = [(dx + dy) / math.sqrt(2) for dx, dy in offsets]
    return {"map": slug, "measure": "crowns", "lone_trees": len(chosen), "drawn": len(centroids),
            "centroid_from_pivot_dx_m": mean_summary([c[0] for c in centroids]), "centroid_from_pivot_dy_m": mean_summary([c[1] for c in centroids]),
            "crown_share_of_reach_disc": summary([c[2] for c in centroids]),
            "hd_measured": len(offsets), "hd_across_light_m": summary(across), "hd_along_light_m": summary(along)}


def served_heightmap(slug, ground):
    """The served precise heightmap (m above the map's lowest point) on the 1 m grid of the prepared ground."""
    folder = os.path.join("/heightmaps", slug)
    step = json.load(open(os.path.join(folder, "meta.json")))["z_step_m"]
    return check_alignment.on_ground_grid(np.asarray(Image.open(os.path.join(folder, "heightmap.png"))).astype(np.float64) * step, ground)


def roof_height_pairs(labels, heightmap, ground, bounds):
    """[(label height, heightmap height)] of the roof labels at least HEIGHT_MIN_DEPTH_M deep that lie on an object of the
    heightmap: the 98th percentile of its rise over the bare ground in the object's connected run (the labels' own statistic)."""
    rise = heightmap - ground
    runs, _ = ndimage.label(rise > HEIGHT_OBJECT_M, structure=np.ones((3, 3)))
    wanted = {}
    for label in labels:
        col, row = int(label["x"] - bounds["min_x"]), int(label["y"] - bounds["min_y"])
        if label["depth"] >= HEIGHT_MIN_DEPTH_M and 0 <= row < runs.shape[0] and 0 <= col < runs.shape[1] and runs[row, col]:
            wanted.setdefault(int(runs[row, col]), []).append(label["h"])
    if not wanted:
        return []
    slices = ndimage.find_objects(runs)
    pairs = []
    for run, heights in wanted.items():
        box = slices[run - 1]
        top = float(np.percentile(rise[box][runs[box] == run], 98))
        # a run that holds several labelled roofs is several buildings joined by walls: its one percentile describes none of them
        if len(heights) == 1:
            pairs.append((heights[0], top))
    return pairs


def measure_heights(slug):
    prep = os.path.join("/prep", slug)
    ground = np.load(os.path.join(prep, "ground.npy"))
    bounds = json.load(open(os.path.join(prep, "meta.json")))["bounds_m"]
    labels = json.load(open(os.path.join(prep, "top_labels.json")))
    pairs = np.array(roof_height_pairs(labels, served_heightmap(slug, ground), ground, bounds)).reshape(-1, 2)
    difference = pairs[:, 0] - pairs[:, 1]
    report = {"map": slug, "measure": "heights", "labels": len(labels), "label_minus_heightmap_m": summary(difference, 2)}
    if len(difference):
        report["within_0_5_m"] = round(float((np.abs(difference) <= 0.5).mean()), 3)
        report["within_1_m"] = round(float((np.abs(difference) <= 1.0).mean()), 3)
    return report


def contour_pixels(rgb):
    """Bool [H, W]: the centre pixels of contour lines on plain ground.

    A line pixel is the contour colour blended over the ground: its difference from the ground's colour (the 9 px median of the
    picture) is a share of at least CONTOUR_MIN_ALPHA of (contour colour - ground), with no more than CONTOUR_MAX_RESIDUAL left
    over; the centre of a line is where that share is the largest of its 3 x 3 neighbours. Ground whose colour varies (roads,
    buildings, crowns, labels) is left out.
    """
    picture = rgb.astype(np.float32)
    ground = np.stack([ndimage.median_filter(picture[..., c], 9) for c in range(3)], -1)
    towards = np.asarray(render.CONTOUR_RGB, np.float32) - ground
    difference = picture - ground
    share = (difference * towards).sum(-1) / np.maximum((towards * towards).sum(-1), 1.0)
    residual = np.linalg.norm(difference - share[..., None] * towards, axis=-1)
    plain = ndimage.uniform_filter(np.linalg.norm(ground - ndimage.uniform_filter(ground, (15, 15, 1)), axis=-1), 15) < 6
    return (share >= CONTOUR_MIN_ALPHA) & (residual < CONTOUR_MAX_RESIDUAL) & plain & (share >= ndimage.maximum_filter(share, 3))


def contour_fit(heights, slopes, pixel_m):
    """The contour interval of CONTOUR_LADDER that the heights (m) under contour pixels fit best, and their errors.

    For an interval I the error of a pixel is |h - nearest multiple of I| / slope, its distance in metres to the true level line; the
    interval chosen has the smallest median of error / (I / slope / 4), the error against that of a pixel placed at random (which
    lies a quarter of the line spacing from a line on average), so a finer interval does not win by being finer.
    """
    best = None
    for interval in render.CONTOUR_LADDER:
        distance = np.abs(heights - np.round(heights / interval) * interval) / slopes
        score = float(np.median(distance / (interval / slopes / 4)))
        if best is None or score < best[0]:
            best = (score, interval, distance)
    score, interval, distance = best
    return {"interval_m": interval, "random_ratio": round(score, 3), "distance_m": summary(distance, 3),
            "distance_px": summary(distance / pixel_m, 2), "within_1_px": round(float((distance <= pixel_m).mean()), 3)}


def measure_contours(slug, zooms=None):
    tiles, prep = os.path.join("/tiles", slug), os.path.join("/prep", slug)
    meta = json.load(open(os.path.join(tiles, "meta.json")))
    ground = np.load(os.path.join(prep, "ground.npy"))
    heightmap = served_heightmap(slug, ground)
    open_ground = np.abs(heightmap - ground) < 0.05
    spline = ndimage.spline_filter(heightmap, order=3, mode="mirror")
    b = meta["bounds_m"]
    size_x, size_y = b["max_x"] - b["min_x"], b["max_y"] - b["min_y"]
    gy, gx = np.gradient(ground[::4, ::4].astype(np.float64), 4.0)
    relief = float(np.percentile(np.hypot(gx, gy), 80))
    finest = meta["maxNativeZoom"]
    report = {"map": slug, "measure": "contours", "zooms": {}}
    rng = np.random.default_rng(0)
    for z in zooms or sorted({finest, render.finest_zoom(size_x, render.LEGACY_FINEST_M_PER_PX), max(0, finest - 4)}):
        px_x, px_y = size_x / (256 * 2 ** z), size_y / (256 * 2 ** z)
        n = CONTOUR_WINDOW_PX // 256
        heights, slopes = [], []
        for _ in range(CONTOUR_WINDOWS):
            x0, y0 = (int(rng.integers(0, max(1, 2 ** z - n + 1))) for _ in range(2))
            rgb = check_alignment.mosaic(tiles, z, x0, y0, min(n, 2 ** z))
            rows, cols = np.nonzero(contour_pixels(rgb))
            u, v = (256 * x0 + cols + 0.5) * px_x, (256 * y0 + rows + 0.5) * px_y
            keep = open_ground[np.clip(v.astype(int), 0, ground.shape[0] - 1), np.clip(u.astype(int), 0, ground.shape[1] - 1)]
            u, v = u[keep], v[keep]
            if not len(u):
                continue
            # the renderer's ground: a cubic B-spline through the samples, sample i at metre i of the frame (SquadCalc's grid)
            at = lambda du, dv: ndimage.map_coordinates(spline, [v + dv, u + du], order=3, prefilter=False, mode="nearest")
            h = at(0, 0)
            slope = np.hypot((at(0.5, 0) - at(-0.5, 0)), (at(0, 0.5) - at(0, -0.5)))
            steep = slope > 0.02
            heights.append(h[steep])
            slopes.append(slope[steep])
        heights, slopes = (np.concatenate(a) if a else np.zeros(0) for a in (heights, slopes))
        expected = next((step for step in render.CONTOUR_LADDER if step >= max(6 * px_x * relief, 2 if relief > 0.18 else 1)), render.CONTOUR_LADDER[-1])
        entry = {"pixel_m": round(px_x, 4), "contour_pixels": int(len(heights)), "interval_by_rule_m": expected}
        if len(heights) >= 200:
            entry |= contour_fit(heights, slopes, px_x)
        report["zooms"][str(z)] = entry
    return report


MEASURES = {"roads": measure_roads, "water": measure_water, "crowns": measure_crowns, "heights": measure_heights, "contours": measure_contours}


def main(argv):
    if len(argv) < 2 or argv[0] not in MEASURES:
        raise SystemExit(__doc__)
    for slug in argv[1:]:
        report = MEASURES[argv[0]](slug)
        json.dump(report, open(f"/check/{slug}_{argv[0]}.json", "w"), indent=1)
        print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
