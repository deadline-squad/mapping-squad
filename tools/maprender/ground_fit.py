"""Ground of the top-down render: layer colours fitted to the map's whole-map texture, tiling from the landscape material."""
import json
import os
import re
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage, optimize

SKIP_TEXTURE = re.compile(r"noise|stencil|blank|utility|macro|_u$|_n$|placeholder|wind", re.IGNORECASE)
# Assets of the engine itself, never of the map's art: the placeholder and default textures
ENGINE_ASSETS = "/Engine/"
# Mean difference between a texture's channels (each divided by its mean) above which it is a mask packed into RGB, not a colour
MASK_CHROMA = 0.25
DETAIL_SIZE = 512
# Share of a material's pixels, darkest first, that show the leaves themselves and not the ground around them: thin masked cards
# need the darkest ones, a solid crown has its shaded rim there and needs most of its pixels
CARD_PIXEL_SHARE, CROWN_PIXEL_SHARE = 0.25, 0.75
LEAF_SAMPLES_PER_BLOCK = 20000
# Brightest colour of leaves; on a map under snow (median luma of the texture above SNOW_MAP_LUMA) the crowns hold snow themselves
LEAF_LUMA_LIMIT, SNOW_LEAF_LUMA_LIMIT, SNOW_MAP_LUMA = 110.0, 225.0, 205.0
MASKED_MINIMUM_PIXELS = 4
FLOWER_NAME = re.compile(r"flower|foxglove|poppy", re.IGNORECASE)
PRIOR_CELLS = 50.0
IRLS_FLOOR_WEIGHT = 0.25


def fit_layer_colours(weights_on_grid, reference, mask=None):
    """One colour per layer (0..255) so that the weights times the colours explain `reference` [h, w, 3] on the same grid.

    Least absolute error through iterative reweighting: what `mask` (bool [h, w], default all) does not remove of buildings, trees and
    roads is an outlier to a ground model. A layer seen on few cells keeps close to the median colour (PRIOR_CELLS), as nothing else
    says what it looks like: an unconstrained fit gives it whatever explains a few mixed cells, up to black or purple.
    """
    layers = weights_on_grid.shape[0]
    x = weights_on_grid.reshape(layers, -1).T.astype(np.float64)
    keep = x.sum(1) > 0
    if mask is not None:
        keep &= mask.ravel()
    x, y = x[keep] / x[keep].sum(1, keepdims=True), reference.reshape(-1, 3)[keep].astype(np.float64)
    prior_row = (PRIOR_CELLS * IRLS_FLOOR_WEIGHT) ** 0.5 * np.eye(layers)

    def solve(values, weight, prior):
        return optimize.lsq_linear(np.vstack([x * weight[:, None] ** 0.5, prior_row]), np.concatenate([values * weight ** 0.5, prior_row @ np.full(layers, prior)]),
                                   bounds=(0, 255), method="bvls").x

    colours = np.zeros((layers, 3))
    for channel in range(3):
        values = y[:, channel]
        prior = float(np.median(values))
        solution = solve(values, np.full(len(values), IRLS_FLOOR_WEIGHT), prior)
        for _ in range(5):
            solution = solve(values, 1 / np.maximum(np.abs(x @ solution - values), 1 / IRLS_FLOOR_WEIGHT), prior)
        colours[:, channel] = solution
    return colours


def open_ground(scene, bounds, frame_size, n, step_m, grow_m=3.0, small_m=2.0, shore_m=3.0, block=1024):
    """(land, water), bool [n, n]: cells where the whole-map texture shows bare ground, and cells of water.

    Objects wider than about twice `small_m` are left out of the land with a margin (`grow_m`, their shadows and the blur of the texture).
    So is a band of `shore_m` along the water: the capture and the render do not agree on the shoreline to the metre.
    """
    occupied = np.zeros((n, n), bool)
    water = np.zeros((n, n), bool)
    ids = {}
    for j0 in range(0, n, block):
        for i0 in range(0, n, block):
            w, h = min(block, n - i0), min(block, n - j0)
            x0, y0 = bounds[0] + i0 * step_m, bounds[1] + j0 * step_m
            material = scene.render_ids(x0, y0, x0 + w * step_m, y0 + h * step_m, w, h, ids)
            water_ids = [index for path, index in ids.items() if "water" in path.lower() or "ocean" in path.lower()]
            water[j0:j0 + h, i0:i0 + w] = np.isin(material, water_ids)
            occupied[j0:j0 + h, i0:i0 + w] = material != 0
    occupied &= ~water
    # Scattered bushes and fence posts are too small to matter and would otherwise strike out the whole field they stand in
    solid = ndimage.binary_opening(occupied, iterations=max(int(round(small_m / step_m)), 1))
    land = ~ndimage.binary_dilation(solid, iterations=max(int(round(grow_m / step_m)), 1))
    land &= ~ndimage.binary_dilation(water, iterations=max(int(round(shore_m / step_m)), 1))
    return land, water


def layer_token(layer):
    """'Grass_LayerInfo' -> 'grass'."""
    return layer.replace("_LayerInfo", "").replace("PhysMat", "").lower()


def tile_of(scalars, token):
    """(near, far) tile of a layer in the landscape material parameters, in metres; (2, 70) when the material has no such names."""
    near = next((v for k, v in scalars.items() if token[:5] in k.lower() and "near" in k.lower()), 2.0)
    far = next((v for k, v in scalars.items() if token[:5] in k.lower() and "far" in k.lower()), 70.0)
    return near, far


def layer_details(scene_dir, layers, colours):
    """[layers, s, s, 3] detail textures (albedo / mean, 128 = 1) and [layers, 2] tiles in cm, with {layer: texture} as a report. A layer
    takes the albedo parameter of its name in the landscape material, else the texture naming it, else the texture nearest to its
    fitted colour. The engine's own textures (ENGINE_ASSETS) are never candidates: the landscape material lists its default parameter
    values (BlendFunc_DefBase, BlendFunc_DefBlend: grids and crosses) beside the real ground textures, and a layer without a game
    texture of its own keeps its fitted colour (report None)."""
    landscape = next(iter(json.loads(Path(os.path.join(scene_dir, "landscape.json")).read_text()).values()))
    textures = json.loads(Path(os.path.join(scene_dir, "textures.json")).read_text())
    candidates = {}
    for path in sorted(set(landscape["textures"].values())):
        short = path.split(".")[-1]
        info = textures.get(path, {})
        if path.startswith(ENGINE_ASSETS) or SKIP_TEXTURE.search(short) or info.get("format") not in ("PF_R8G8B8A8", "PF_B8G8R8A8"):
            continue
        data = np.fromfile(os.path.join(scene_dir, "textures", info["file"] + ".bin"), np.uint8).reshape(info["height"], info["width"], 4)
        rgb = data[..., [2, 1, 0]] if info["format"] == "PF_B8G8R8A8" else data[..., :3]
        small = np.asarray(Image.fromarray(rgb).resize((DETAIL_SIZE, DETAIL_SIZE), Image.BOX), np.float32)
        relative = small / np.maximum(small.mean((0, 1), keepdims=True), 1)
        if np.abs(relative - relative.mean(-1, keepdims=True)).mean() <= MASK_CHROMA:
            candidates[short] = small
    details = np.full((len(layers), DETAIL_SIZE, DETAIL_SIZE, 3), 128, np.uint8)
    tiles = np.zeros((len(layers), 2))
    report = {}
    for i, layer in enumerate(layers):
        token = layer_token(layer)
        near, far = tile_of(landscape["scalars"], token)
        tiles[i] = near * 100, far * 100
        # The material names a layer's texture ("A Albedo"), and texture names may hold the layer's name as a word ("T_Grass_A")
        parameter = next((path.split(".")[-1] for key, path in sorted(landscape["textures"].items()) if key.lower() in (f"{token} albedo", f"{token} diffuse")), None)
        # A one-letter layer name ("A") has to be a word of its own, it is part of every other texture's name
        pattern = re.escape(token) if len(token) > 2 else rf"(^|_){re.escape(token)}(_|$)"
        named = [k for k in candidates if re.search(pattern, k.lower())]
        if parameter in candidates:
            chosen = parameter
        elif named:
            chosen = named[0]
        elif candidates:
            chosen = min(candidates, key=lambda k: np.abs(candidates[k].mean((0, 1)) - colours[i]).sum())
        else:
            report[layer] = None
            continue
        report[layer] = chosen
        ratio = candidates[chosen] / np.maximum(candidates[chosen].mean((0, 1), keepdims=True), 1)
        details[i] = np.clip(ratio * 128, 0, 255).astype(np.uint8)
    return details, tiles, report


def is_leafy(scene, path):
    """A material of a tree or of masked cards: its pixels are thin and mix with the ground below them in the whole-map texture.
    Road materials are masked too, but only along their edges."""
    if "road" in path.lower():
        return False
    return path in scene.leaf_materials or scene.materials.get(path, {}).get("blend") == "BLEND_Masked"


def darkest_mean(pixels, share):
    """Mean colour of the darkest `share` of `pixels` [n, 3] by luma."""
    luma = pixels.mean(1)
    return pixels[luma <= np.quantile(luma, share)].mean(0)


def calibrate_materials(scene, reference, bounds, frame_size, block=1024, step_m=1.0, roof_target=None, iterations=2, clipped_luma=240.0, clipped_share=0.25, minimum_pixels=40):
    """Fit one colour gain per material so its mean colour matches the map's whole-map texture `reference` (sRGB on the render grid).

    The game's whole-map texture clips bright roofs to white. A material with more than `clipped_share` of its pixels above
    `clipped_luma` cannot be read from it: those materials share one gain, chosen so their mean is `roof_target`.
    A leafy material (see is_leafy) compares its darkest pixels in each image, which show leaves rather than the ground between them;
    branches under snow are as light as the ground between them and compare all of their pixels.
    Returns a report per material. Gains are stored in scene.material_gains (linear light).
    """
    ids = {}
    n = int(frame_size / step_m)
    count = int(np.ceil(n / block))
    report = {}
    random = np.random.default_rng(0)
    leaf_limit = SNOW_LEAF_LUMA_LIMIT if np.median(reference.mean(-1)) > SNOW_MAP_LUMA else LEAF_LUMA_LIMIT
    for iteration in range(iterations):
        totals = {}
        leaf_samples = {}
        for by in range(count):
            for bx in range(count):
                x0, y0 = bounds[0] + bx * block * step_m, bounds[1] + by * block * step_m
                w, h = min(block, n - bx * block), min(block, n - by * block)
                x1, y1 = x0 + w * step_m, y0 + h * step_m
                material = scene.render_ids(x0, y0, x1, y1, w, h, ids)
                by_id = {index: path for path, index in ids.items()}
                lit = scene.render(x0, y0, x1, y1, w, h, ssaa=2).astype(np.float64)
                ref = reference[by * block:by * block + h, bx * block:bx * block + w].astype(np.float64)
                if ref.shape[:2] != material.shape:
                    continue
                # Only pixels well inside a surface: thin things (fences, leaves) mix with the ground in the whole-map texture
                for index in np.unique(material):
                    if index == 0:
                        continue
                    path = by_id.get(index, "")
                    leafy = is_leafy(scene, path)
                    # A road fades into the ground towards its edges, only its middle shows its own colour
                    mask = material == index if leafy else ndimage.binary_erosion(material == index, iterations=2 if "road" in path.lower() else 1)
                    if not mask.any():
                        continue
                    if leafy and "snow" not in path.lower():
                        rows, columns = np.nonzero(mask)
                        chosen = random.permutation(len(rows))[:LEAF_SAMPLES_PER_BLOCK]
                        leaf_samples.setdefault(index, []).append((lit[rows[chosen], columns[chosen]], ref[rows[chosen], columns[chosen]]))
                    sum_lit, sum_ref, clipped, pixels = totals.get(index, (0, 0, 0, 0))
                    totals[index] = (sum_lit + lit[mask].sum(0), sum_ref + ref[mask].sum(0), clipped + int((ref[mask].mean(1) > clipped_luma).sum()), pixels + int(mask.sum()))
        by_index = {index: path for path, index in ids.items()}
        clipped_lit, clipped_pixels, clipped_paths = np.zeros(3), 0, []
        report = {}
        for index, (sum_lit, sum_ref, clipped, pixels) in totals.items():
            path = by_index[index]
            if pixels < (MASKED_MINIMUM_PIXELS if is_leafy(scene, path) else minimum_pixels):
                continue
            if clipped / pixels > clipped_share and roof_target is not None:
                clipped_lit += sum_lit
                clipped_pixels += pixels
                clipped_paths.append(path)
                report[path] = {"pixels": pixels, "clipped": True}
                continue
            if index in leaf_samples:
                share = CROWN_PIXEL_SHARE if path in scene.crown_materials else CARD_PIXEL_SHARE
                mean_lit = np.maximum(darkest_mean(np.concatenate([s[0] for s in leaf_samples[index]]), share), 1.0)
                mean_ref = np.maximum(darkest_mean(np.concatenate([s[1] for s in leaf_samples[index]]), share), 1.0)
                # A plant the capture does not show would take the colour of the sand or snow below it
                mean_ref = mean_ref * min(leaf_limit / mean_ref.mean(), 1.0)
            else:
                mean_lit, mean_ref = np.maximum(sum_lit / pixels, 1.0), np.maximum(sum_ref / pixels, 1.0)
            gain = np.clip((mean_ref / mean_lit) ** 2.2, 0.1, 6.0)
            old = scene.material_gains.get(path, (1.0, 1.0, 1.0))
            scene.material_gains[path] = tuple(float(a * b) for a, b in zip(old, gain))
            report[path] = {"pixels": pixels, "render": (sum_lit / pixels).round(1).tolist(), "reference": (sum_ref / pixels).round(1).tolist()}
        if clipped_pixels:
            gain = np.clip((np.array(roof_target, np.float64) / np.maximum(clipped_lit / clipped_pixels, 1.0)) ** 2.2, 0.1, 12.0)
            for path in clipped_paths:
                old = scene.material_gains.get(path, (1.0, 1.0, 1.0))
                scene.material_gains[path] = tuple(float(a * b) for a, b in zip(old, gain))
    # Everything too small or thin to read takes the median brightness correction of the rest
    measured = [g for g in scene.material_gains.values()]
    if measured:
        scene.gain = tuple(float(np.median([np.mean(g) for g in measured])) for _ in range(3))
        scene.material_gains = {path: tuple(v / scene.gain[0] for v in g) for path, g in scene.material_gains.items()}
    return report


def invisible_foliage(scene_dir, reference, bounds, frame_size, threshold=3.2, minimum_instances=20, tall_m=5.0):
    """Ids of the foliage meshes the game's own map does not show (ground cover such as crops and flowers).

    A mesh stays when it is at least `tall_m` high (at its median instance scale) or when its instances differ from their surroundings
    in the whole-map texture `reference` (sRGB, frame_size metres wide from `bounds`) by `threshold` or more, darker like bushes or
    lighter like rocks; a flower never stays, it is a square of atlas seen from above. Returns (ids, report). Only instance positions and mesh vertices are used, so it needs no render.
    """
    from scene_render import component_world, instance_matrices
    luma = reference.mean(-1).astype(np.float32)
    step = frame_size / luma.shape[0]
    inner = max(int(round(1.5 / step)) * 2 + 1, 3)
    outer = inner * 6 + 1
    contrast = ndimage.uniform_filter(luma, outer) - ndimage.uniform_filter(luma, inner)
    positions, scales = {}, {}
    for line in Path(scene_dir, "instances.ndjson").read_text().splitlines():
        item = json.loads(line)
        if item["type"] != "FoliageInstancedStaticMeshComponent" or not item["instances"]:
            continue
        matrices = instance_matrices(item["instances"]) @ component_world(item["chain"])
        positions.setdefault(item["mesh"], []).append(matrices[:, 3, :2])
        scales.setdefault(item["mesh"], []).append(np.linalg.norm(matrices[:, 2, :3], axis=1))
    meshes = json.loads(Path(os.path.join(scene_dir, "meshes.json")).read_text())
    by_id = {m["id"]: (path.rsplit(".", 1)[-1], m) for path, m in meshes.items()}
    hidden, report = [], {}
    for mesh, chunks in positions.items():
        p = np.concatenate(chunks) / 100
        col = ((p[:, 0] - bounds[0]) / step).astype(np.int64)
        row = ((p[:, 1] - bounds[1]) / step).astype(np.int64)
        ok = (col >= 0) & (col < luma.shape[1]) & (row >= 0) & (row < luma.shape[0])
        if ok.sum() < minimum_instances:
            continue
        name, info = by_id[mesh]
        vertices = np.fromfile(os.path.join(scene_dir, "meshes", f"{mesh}.bin"), np.float32, count=info["vertices"] * 8).reshape(-1, 8)
        height = float(np.ptp(vertices[:, 2]) * np.median(np.concatenate(scales[mesh])) / 100)
        value = float(contrast[row[ok], col[ok]].mean())
        visible = height >= tall_m or (abs(value) >= threshold and not FLOWER_NAME.search(name))
        report[name] = {"instances": int(ok.sum()), "darkening": round(value, 1), "height": round(height, 1), "visible": visible}
        if not visible:
            hidden.append(mesh)
    return hidden, report
