"""Top-down map of Squad from the game client's assets as Leaflet tiles (see README.md).

    render_map.py <slug> <texture> [--zoom Z] [--out DIR]

Reads the scene (SquadExtract scene), the prepared ground of tools/maptiles (heights and the map frame) and the whole-map texture.
Colours come only from the game's data: layer colours and material gains are fitted to the whole-map texture of the same map.
Tiles follow the frame of tools/maptiles: pixel (px, py) of zoom z is centred at min + (p + 0.5) * size / (256 * 2 ** z).
"""
import argparse
import json
import os
import shutil
import time
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

import ground_fit
import registration
import scene_render

HOME = os.path.expanduser("~")
SCENES = os.environ.get("SCENES", f"{HOME}/data/squad-scene")
PREP = os.environ.get("PREP", f"{HOME}/data/squad-maptiles/prep")
TEXTURES = os.environ.get("MINIMAP_TEXTURES", f"{HOME}/data/squad-client-extract/tex")
DIST = os.environ.get("DIST", f"{HOME}/apps/squadcalc/dist/maptiles")
TILE = 256
BLOCK_TILES = 4
FINEST_M_PER_PX = 0.33
WEBP_QUALITY = 88
# Median colour in the Mutaha Seed texture of the 54216 pixels that the whole-map texture clips to white (luma above 240, eroded by 2 px)
ROOF_TARGET = (219, 206, 191)
SUN_AZIMUTH, SUN_ELEVATION = -135.0, 65.0
DETAIL_STRENGTH = 0.35
TONE_SIGMA_M = 2.0
TONE_WIDE_SIGMA_M = 40.0
TONE_LIMITS = (0.55, 1.8)
TONE_BLOCK = 1024
TONE_SHORE_M = 3.0
TONE_STALE_LIMITS = (0.72, 1.38)
TONE_STALE_GROW_M = 2.0
TONE_PRIOR = 2.0
TONE_ROOF_LUMA, TONE_ROOF_RANGE = 215.0, 50.0
# The outer part of the map, which the game's capture darkens outside the play area, says nothing about the colours of the layers
CAPTURE_BORDER_SHARE = 0.15


def decode_bc1(raw, width, height):
    """RGB uint8 array of a BC1 texture."""
    blocks = np.frombuffer(raw, np.uint8).reshape(height // 4, width // 4, 8)
    c0 = blocks[..., 0].astype(np.uint32) | (blocks[..., 1].astype(np.uint32) << 8)
    c1 = blocks[..., 2].astype(np.uint32) | (blocks[..., 3].astype(np.uint32) << 8)
    rgb = lambda c: np.stack([(c >> 11 & 31) * 255 // 31, (c >> 5 & 63) * 255 // 63, (c & 31) * 255 // 31], -1)
    a, b = rgb(c0), rgb(c1)
    opaque = (c0 > c1)[..., None]
    third = np.where(opaque, (2 * a + b) // 3, (a + b) // 2)
    fourth = np.where(opaque, (a + 2 * b) // 3, 0)
    palette = np.stack([a, b, third, fourth], 2)
    bits = blocks[..., 4].astype(np.uint32) | blocks[..., 5].astype(np.uint32) << 8 | blocks[..., 6].astype(np.uint32) << 16 | blocks[..., 7].astype(np.uint32) << 24
    out = np.zeros((height, width, 3), np.uint8)
    for y in range(4):
        for x in range(4):
            index = (bits >> (2 * (4 * y + x))) & 3
            out[y::4, x::4] = np.take_along_axis(palette, index[:, :, None, None].repeat(3, -1), 2)[:, :, 0]
    return out


def whole_map_texture(name):
    """RGB array of an extracted whole-map texture `<name>.PF_DXT1.<w>x<h>.bin`."""
    file = next(f for f in os.listdir(TEXTURES) if f.startswith(name + ".PF_"))
    _, fmt, size, _ = file.split(".")
    width, height = (int(v) for v in size.split("x"))
    raw = Path(TEXTURES, file).read_bytes()
    if fmt == "PF_DXT1":
        return decode_bc1(raw, width, height)
    return np.frombuffer(raw, np.uint8).reshape(height, width, 4)[..., [2, 1, 0]].copy()


def square_texture(texture, frame):
    """The whole-map texture (covering the frame) on a square of the frame's larger side, its origin at the frame's origin; the rest repeats the edge."""
    if frame["w"] == frame["h"]:
        return texture
    size = texture.shape[0]
    longest = max(frame["w"], frame["h"])
    width, height = round(size * frame["w"] / longest), round(size * frame["h"] / longest)
    fitted = np.asarray(Image.fromarray(texture).resize((width, height), Image.LANCZOS))
    return np.pad(fitted, ((0, size - height), (0, size - width), (0, 0)), mode="edge")


def render_on_grid(scene, frame, n, step):
    """RGB [n, n, 3] render of the whole map, cell i centred at frame + i * step."""
    image = np.zeros((n, n, 3), np.uint8)
    for j0 in range(0, n, TONE_BLOCK):
        for i0 in range(0, n, TONE_BLOCK):
            w, h = min(TONE_BLOCK, n - i0), min(TONE_BLOCK, n - j0)
            x0, y0 = frame["x"] + i0 * step, frame["y"] + j0 * step
            image[j0:j0 + h, i0:i0 + w] = scene.render(x0, y0, x0 + w * step, y0 + h * step, w, h, ssaa=2)
    return image


def load_map(slug, texture_name):
    """Scene of a map with its ground set up and colours calibrated; returns (scene, frame, report)."""
    scene_dir = os.path.join(SCENES, slug)
    meta = json.loads(Path(os.path.join(PREP, slug, "meta.json")).read_text())
    bounds = meta["bounds_m"]
    frame = {"x": bounds["min_x"], "y": bounds["min_y"], "w": bounds["max_x"] - bounds["min_x"], "h": bounds["max_y"] - bounds["min_y"]}
    origin = (frame["x"], frame["y"])
    # The calibration runs on a square over the frame; a frame is at most a few metres from one (Skorpo: 6849 x 6869 m)
    size = max(frame["w"], frame["h"])
    ground = np.load(os.path.join(PREP, slug, "ground.npy"), mmap_mode="r")
    n = max(ground.shape)
    ground = np.pad(np.asarray(ground, np.float32), ((0, n - ground.shape[0]), (0, n - ground.shape[1])), mode="edge")
    heights = ground + meta["z_min_m"]
    step = size / (n - 1)

    def open_scene(texture, hidden):
        scene = scene_render.Scene(scene_dir, SUN_AZIMUTH, SUN_ELEVATION, ambient=0.7, sun_strength=0.6, hidden_foliage=hidden)
        names, weights = scene.load_weights(frame["x"], frame["y"], step, n)
        reference = np.asarray(Image.fromarray(texture).resize((n, n), Image.LANCZOS))
        smooth = ndimage.gaussian_filter(reference.astype(np.float32), (3, 3, 0))
        window = ndimage.gaussian_filter(weights.astype(np.float32), (0, 3, 3))
        colours = ground_fit.fit_layer_colours(window[:, ::6, ::6], smooth[::6, ::6])
        details, tiles, detail_report = ground_fit.layer_details(scene_dir, names, colours)
        scene.set_ground(heights, origin, size, colours / 255, details, tiles, detail_strength=DETAIL_STRENGTH)
        uncovered = weights[names.index(scene_render.UNCOVERED_LAYER)] > 0 if scene_render.UNCOVERED_LAYER in names else np.zeros((n, n), bool)
        return scene, names, reference, smooth, window, detail_report, uncovered

    texture = square_texture(whole_map_texture(texture_name), frame)
    hidden, foliage_report = ground_fit.invisible_foliage(scene_dir, texture, origin, size)
    scene, names, reference, smooth, window, detail_report, uncovered = open_scene(texture, hidden)
    warp = registration.fit_warp(registration.patch_shifts(render_on_grid(scene, frame, n, step), reference, step), step)
    if warp is not None:
        texture = registration.warp_texture(texture, warp, size)
        hidden, foliage_report = ground_fit.invisible_foliage(scene_dir, texture, origin, size)
        scene.ctx.release()
        scene, names, reference, smooth, window, detail_report, uncovered = open_scene(texture, hidden)
    land, water = ground_fit.open_ground(scene, origin, size, n, step)
    border = int(n * CAPTURE_BORDER_SHARE)
    inner = np.zeros_like(land)
    inner[border:n - border, border:n - border] = land[border:n - border, border:n - border]
    colours = ground_fit.fit_layer_colours(window[:, ::6, ::6], smooth[::6, ::6], inner[::6, ::6])
    scene.set_layer_colours(colours / 255)
    sea_level = meta["sea_level_m"]
    if sea_level is not None:
        below = ground < sea_level - 0.3
        if below.sum() > 500:
            scene.water_tint = tuple((np.median(smooth[below], axis=0) / 255) ** 2.2)
    material_report = ground_fit.calibrate_materials(scene, reference, origin, size, step_m=step, roof_target=ROOF_TARGET)
    report = {"foliage": foliage_report, "layers": dict(zip(names, colours.round(1).tolist())), "details": detail_report,
              "materials": len(material_report), "clipped materials": sum(1 for v in material_report.values() if v.get("clipped")),
              "gain": scene.gain, "scene": scene.statistics, "texture": texture_name,
              "texture warp m": None if warp is None else dict(zip(("dx", "dx over the map", "dy", "dy over the map"), np.round(warp, 2).tolist()))}
    scene.tone = tone_field(scene, frame, reference, land, water, uncovered, step)
    scene.tone_step = step
    return scene, frame, report


def tone_field(scene, frame, reference, land, water, uncovered, step):
    """Colour of the capture over the render: [n, n, 3] ratio of the whole-map texture to the render on the texture's grid.

    The render has no source for what the capture shows of the ground at this scale (mottling, stripes on fields, colour patches, the
    dark border of the map, shallows). The ratio is taken on open ground only (`land`) and without cells far from the ratio around them,
    so that roofs and crowns of the capture, and trees it shows that the map no longer has, do not print on the ground: blurred by
    TONE_SIGMA_M where there is enough open ground, by TONE_WIDE_SIGMA_M elsewhere. Water takes a field of its own from its own cells: water and land have so different colours that a ratio crossing the shore burns a coloured rim on the
    other side. It is limited to TONE_LIMITS so that a place changed since the capture cannot repaint the render.
    Open ground and water that no landscape component paints (`uncovered`, past the landscape) have no layers to draw: there the ratio
    is taken cell by cell and unlimited, so the render shows the capture itself. Meshes standing there (Chora's backdrop mountains)
    keep their own colours.
    """
    # Single precision throughout: three channels of the largest maps are 570 MB each
    rendered = render_on_grid(scene, frame, reference.shape[0], step).astype(np.float32)
    captured = reference.astype(np.float32)

    def field_of(cells, whole_map_fallback):
        def blurred_ratio(sigma_m, weight):
            sigma = sigma_m / step
            # Where a blur finds next to no such cells (dense forest) the ratio falls back on that of the whole map. Not so on water: the
            # colour the sea needs says nothing about a pond
            overall = np.ones(3, np.float32)
            if whole_map_fallback:
                totals = [(captured[..., c] * weight).sum(dtype=np.float64) / max((rendered[..., c] * weight).sum(dtype=np.float64), 1.0) for c in range(3)]
                overall = np.array(totals, np.float32)
            share = ndimage.gaussian_filter(weight, sigma)
            ratio = np.empty(captured.shape, np.float32)
            for c in range(3):
                top = ndimage.gaussian_filter(captured[..., c] * weight, sigma)
                bottom = ndimage.gaussian_filter(rendered[..., c] * weight, sigma)
                ratio[..., c] = (top + TONE_PRIOR * overall[c]) / (bottom + TONE_PRIOR)
            return ratio, share

        wide, _ = blurred_ratio(TONE_WIDE_SIGMA_M, cells.astype(np.float32))
        # What the capture shows and the map no longer has (trees felled since, a road moved): far from its surroundings in some channel
        stale = np.zeros(cells.shape, bool)
        for c in range(3):
            deviation = (captured[..., c] + 1) / (rendered[..., c] + 1) / wide[..., c]
            stale |= (deviation < TONE_STALE_LIMITS[0]) | (deviation > TONE_STALE_LIMITS[1])
        stale = ndimage.binary_dilation(stale, iterations=max(int(round(TONE_STALE_GROW_M / step)), 1))
        fine, share = blurred_ratio(TONE_SIGMA_M, (cells & ~stale).astype(np.float32))
        trust = np.clip((share - 0.1) / 0.4, 0, 1)[..., None]
        fallback = wide if whole_map_fallback else np.float32(1)
        return np.clip(trust * fine + (1 - trust) * fallback, *TONE_LIMITS, dtype=np.float32)

    field = field_of(land, True)
    if water.any():
        # Without the shore: where the capture shows land and the render water the ratio would make a bright rim on both sides
        core = ndimage.binary_erosion(water, iterations=max(int(round(TONE_SHORE_M / step)), 1))
        field[water] = field_of(core if core.any() else water, False)[water]
    shown = uncovered & (land | water)
    if shown.any():
        field[shown] = (captured[shown] + 1) / (rendered[shown] + 1)
    return field


def apply_tone(image, field, x0, y0, metres_per_pixel, frame, step):
    """`image` [h, w, 3] with row 0 and column 0 centred half a pixel from (x0, y0), multiplied by the tone field at each pixel.

    metres_per_pixel: (along x, along y).
    """
    h, w = image.shape[:2]
    rows = (y0 + (np.arange(h) + 0.5) * metres_per_pixel[1] - frame["y"]) / step
    columns = (x0 + (np.arange(w) + 0.5) * metres_per_pixel[0] - frame["x"]) / step
    grid = np.meshgrid(rows, columns, indexing="ij")
    factors = np.dstack([ndimage.map_coordinates(field[..., c], grid, order=1, mode="nearest") for c in range(3)])
    # Light surfaces such as roofs keep their colour: the ratio describes the ground, and would burn them out
    keep = np.clip((TONE_ROOF_LUMA - image.mean(-1, keepdims=True)) / TONE_ROOF_RANGE, 0, 1)
    return np.clip(image * (1 + (factors - 1) * keep) + 0.5, 0, 255).astype(np.uint8)


def finest_zoom(size_m):
    """First zoom with at most FINEST_M_PER_PX metres per pixel."""
    zoom = 0
    while size_m / (TILE * 2 ** zoom) > FINEST_M_PER_PX:
        zoom += 1
    return zoom


def render_zoom(scene, frame, zoom, folder):
    """Tiles of one zoom, written as `<folder>/<zoom>/<x>_<y>.webp`."""
    n = 2 ** zoom
    blocks = int(np.ceil(n / BLOCK_TILES))
    os.makedirs(os.path.join(folder, str(zoom)), exist_ok=True)
    started = time.time()
    px_x, px_y = frame["w"] / (TILE * n), frame["h"] / (TILE * n)
    for by in range(blocks):
        for bx in range(blocks):
            tx, ty = bx * BLOCK_TILES, by * BLOCK_TILES
            w, h = min(BLOCK_TILES, n - tx), min(BLOCK_TILES, n - ty)
            x0, y0 = frame["x"] + tx * TILE * px_x, frame["y"] + ty * TILE * px_y
            image = scene.render(x0, y0, x0 + w * TILE * px_x, y0 + h * TILE * px_y, w * TILE, h * TILE, ssaa=2)
            image = apply_tone(image, scene.tone, x0, y0, (px_x, px_y), frame, scene.tone_step)
            for j in range(h):
                for i in range(w):
                    tile = image[j * TILE:(j + 1) * TILE, i * TILE:(i + 1) * TILE]
                    Image.fromarray(tile).save(os.path.join(folder, str(zoom), f"{tx + i}_{ty + j}.webp"), quality=WEBP_QUALITY, method=4)
        print(f"zoom {zoom}: row {by + 1}/{blocks}, {time.time() - started:.0f} s", flush=True)


def build_pyramid(folder, finest):
    """Coarser zooms from the finer one by 2 x 2 averaging of decoded tiles."""
    for zoom in range(finest - 1, -1, -1):
        n = 2 ** zoom
        os.makedirs(os.path.join(folder, str(zoom)), exist_ok=True)
        for ty in range(n):
            for tx in range(n):
                canvas = np.zeros((TILE * 2, TILE * 2, 3), np.uint8)
                for j in range(2):
                    for i in range(2):
                        canvas[j * TILE:(j + 1) * TILE, i * TILE:(i + 1) * TILE] = np.asarray(Image.open(os.path.join(folder, str(zoom + 1), f"{2 * tx + i}_{2 * ty + j}.webp")).convert("RGB"))
                tile = canvas.reshape(TILE, 2, TILE, 2, 3).mean((1, 3)).round().astype(np.uint8)
                Image.fromarray(tile).save(os.path.join(folder, str(zoom), f"{tx}_{ty}.webp"), quality=WEBP_QUALITY, method=4)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("slug")
    parser.add_argument("texture", help="name of the map's whole-map texture")
    parser.add_argument("--zoom", type=int, help="render only this zoom, without coarser ones (for tests)")
    parser.add_argument("--out")
    args = parser.parse_args()
    started = time.time()
    final = args.out or os.path.join(DIST, f"{args.slug}-hd")
    temporary = final + ".tmp"
    shutil.rmtree(temporary, ignore_errors=True)
    os.makedirs(temporary)
    scene, frame, report = load_map(args.slug, args.texture)
    print(json.dumps({k: v for k, v in report.items() if k != "foliage"}), flush=True)
    finest = args.zoom if args.zoom is not None else finest_zoom(frame["w"])
    render_zoom(scene, frame, finest, temporary)
    if args.zoom is None:
        build_pyramid(temporary, finest)
    meta = {"map": args.slug, "style": "hd", "tileSize": TILE, "minNativeZoom": 0, "maxNativeZoom": finest, "metresPerPixel": round(frame["w"] / (TILE * 2 ** finest), 4),
            "bounds_m": {"min_x": frame["x"], "max_x": frame["x"] + frame["w"], "min_y": frame["y"], "max_y": frame["y"] + frame["h"]},
            "url": "{z}/{x}_{y}.webp", "sources": "Top-down render from the meshes, materials, landscape layers and placements of the Squad client; colours fitted to the map's whole-map texture (tools/maprender)",
            "report": report, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seconds": round(time.time() - started)}
    Path(os.path.join(temporary, "meta.json")).write_text(json.dumps(meta, indent=1))
    if os.path.exists(final):
        shutil.rmtree(final + ".old", ignore_errors=True)
        os.rename(final, final + ".old")
    os.rename(temporary, final)
    shutil.rmtree(final + ".old", ignore_errors=True)
    print(f"{args.slug}: done in {time.time() - started:.0f} s", flush=True)


if __name__ == "__main__":
    main()
