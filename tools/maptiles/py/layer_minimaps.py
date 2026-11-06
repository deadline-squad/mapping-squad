"""Per-layer minimap textures of the Squad client as webp files for SquadCalc.

Most layers of a map share one minimap texture of the whole map. Seed and Skirmish layers ship a texture of
their own, several times finer than the whole-map image because it covers only part of the map. This tool reads
the layer table written by the extractor's `layerminimaps` mode and the raw textures written by its `texraw`
mode, finds those textures, decodes them and writes

    <tiles>/<texture name in lower case>/0/0_0.webp     lossy webp, quality 90, method 4
    <tiles>/layer-minimaps.json                          manifest: client build, texture -> folder, size, layers

Usage: layer_minimaps.py <layers.tsv> <texture dir> <appmanifest_393380.acf> <tiles dir>
"""
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

import numpy as np
from PIL import Image

WEBP_QUALITY = 90
WEBP_METHOD = 4


def parse_layer_table(text):
    """Rows `(layer, texture)` of the layers.tsv text.

    `layer` is the file name of the layer's .umap without extension, `texture` the name of its MapTexture
    object. Lines without a texture (failed or without world settings) are skipped.
    """
    rows = []
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < 2 or not fields[1].startswith("/"):
            continue
        layer = fields[0].rsplit("/", 1)[-1].removesuffix(".umap")
        texture = fields[1].rsplit(".", 1)[-1]
        rows.append((layer, texture))
    return rows


def map_name(layer):
    """The map of a layer: the first `_` token of its name."""
    return layer.split("_", 1)[0]


def find_layer_minimaps(rows):
    """Textures that a layer uses but that are not the base texture of its map.

    The base texture of a map is the one used by most of its layers (ties: the alphabetically first name).
    Returns `{texture: [layer, ...]}` with the layers sorted.
    """
    usage = {}
    for layer, texture in rows:
        usage.setdefault(map_name(layer), Counter())[texture] += 1
    base = {name: min(counts, key=lambda t: (-counts[t], t)) for name, counts in usage.items()}
    found = {}
    for layer, texture in rows:
        if texture != base[map_name(layer)]:
            found.setdefault(texture, []).append(layer)
    return {texture: sorted(layers) for texture, layers in sorted(found.items())}


def folder_name(texture):
    """Folder of a texture under the tiles directory."""
    return texture.lower()


def decode_bc1(data, width, height):
    """Decodes BC1 (DXT1) data into a `(height, width, 3)` uint8 RGB array.

    Each 8-byte block holds two RGB565 endpoints and 2-bit indices of 16 texels. With c0 > c1 the block has
    four colours (two interpolated at 1/3 and 2/3), otherwise three: the midpoint and transparent black.
    """
    blocks_x, blocks_y = width // 4, height // 4
    blocks = np.frombuffer(data, dtype="<u2", count=blocks_x * blocks_y * 4).reshape(-1, 4)
    c0, c1 = blocks[:, 0], blocks[:, 1]
    indices = blocks[:, 2].astype(np.uint32) | (blocks[:, 3].astype(np.uint32) << 16)

    def rgb888(c):
        r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
        return np.stack([r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2], axis=1).astype(np.int32)

    e0, e1 = rgb888(c0), rgb888(c1)
    four = (c0 > c1)[:, None]
    palette = np.stack([
        e0,
        e1,
        np.where(four, (2 * e0 + e1) // 3, (e0 + e1) // 2),
        np.where(four, (e0 + 2 * e1) // 3, 0),
    ], axis=1)
    selectors = (indices[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3
    texels = np.take_along_axis(palette, selectors[:, :, None].astype(np.intp), axis=1)
    image = texels.reshape(blocks_y, blocks_x, 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(height, width, 3)
    return image.astype(np.uint8)


def decode_bgra(data, width, height):
    """Decodes B8G8R8A8 data into a `(height, width, 3)` uint8 RGB array (alpha dropped)."""
    pixels = np.frombuffer(data, dtype=np.uint8, count=width * height * 4).reshape(height, width, 4)
    return np.ascontiguousarray(pixels[:, :, 2::-1])


def parse_raw_name(filename):
    """`(texture, pixel format, width, height)` of an extractor file name `<name>.<format>.<w>x<h>.bin`."""
    match = re.fullmatch(r"(.+)\.(PF_\w+)\.(\d+)x(\d+)\.bin", filename)
    if match is None:
        raise ValueError(f"not a raw texture file name: {filename}")
    return match.group(1), match.group(2), int(match.group(3)), int(match.group(4))


def decode_texture(data, pixel_format, width, height):
    """RGB array of raw mip 0 data in the given pixel format."""
    if pixel_format == "PF_DXT1":
        return decode_bc1(data, width, height)
    if pixel_format == "PF_B8G8R8A8":
        return decode_bgra(data, width, height)
    raise ValueError(f"unsupported pixel format {pixel_format}")


def client_build(manifest_text):
    """The `buildid` of a Steam appmanifest."""
    match = re.search(r'"buildid"\s+"(\d+)"', manifest_text)
    if match is None:
        raise ValueError("no buildid in the appmanifest")
    return match.group(1)


def write_webp(image, path):
    """Writes the image as webp under a temporary name, then renames it into place."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    Image.fromarray(image).save(temporary, "WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
    os.replace(temporary, path)


def main(layers_path, texture_dir, manifest_path, tiles_dir):
    with open(layers_path, encoding="utf-8") as f:
        wanted = find_layer_minimaps(parse_layer_table(f.read()))
    raw_files = {}
    for filename in os.listdir(texture_dir):
        if filename.endswith(".bin"):
            raw_files[parse_raw_name(filename)[0].lower()] = filename
    textures = {}
    for texture, layers in wanted.items():
        filename = raw_files.get(texture.lower())
        if filename is None:
            raise SystemExit(f"no raw texture for {texture} in {texture_dir}")
        _, pixel_format, width, height = parse_raw_name(filename)
        with open(os.path.join(texture_dir, filename), "rb") as f:
            image = decode_texture(f.read(), pixel_format, width, height)
        folder = folder_name(texture)
        write_webp(image, os.path.join(tiles_dir, folder, "0", "0_0.webp"))
        textures[texture] = {"folder": folder, "size": width, "layers": layers}
        print(f"{texture}: {pixel_format} {width}x{height}, {len(layers)} layers", flush=True)
    with open(manifest_path, encoding="utf-8") as f:
        build = client_build(f.read())
    manifest = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build": build,
        "textures": textures,
    }
    target = os.path.join(tiles_dir, "layer-minimaps.json")
    with open(target + ".tmp", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    os.replace(target + ".tmp", target)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
