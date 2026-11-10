"""Per-layer minimap textures of the Squad client as webp files for SquadCalc.

Most layers of a map share one minimap texture of the whole map. Seed and Skirmish layers ship a texture of
their own, several times finer than the whole-map image because it covers only part of the map. The game takes
the texture of a layer from two places: the layer's level (`SQWorldSettings`: `MapTexture` between the actors
`MapTextureCornerZero` and `MapTextureCornerOne`), replaced by the layer's data asset
(`Gameplay_Layer_Data/<layer>`, class BP_SQLayer) when that sets `OveriddenMinimapTexture` (the texture) and
`MinimapCornersPosition` with `bIsValid` (the corners). This tool joins both into one table per layer, finds the
layers whose texture is not their map's, decodes those textures and writes

    <tiles>/<texture name in lower case>/0/0_0.webp     lossy webp, quality 90, method 4
    <tiles>/layer-minimaps.json                          manifest: client build, layer -> texture, folder, size, corners

Usage:
    layer_minimaps.py textures <layers.tsv> <layer data dir>
        prints the regular expression over pak paths of the textures the layers need (the extractor's texraw mode)
    layer_minimaps.py build <layers.tsv> <layer data dir> <texture dir> <appmanifest_393380.acf> <tiles dir>

`layers.tsv` is the output of the extractor's `layerminimaps` mode, the layer data dir the output of its `dumpall`
mode over `/Gameplay_Layer_Data/` and the texture dir the output of its `texraw` mode.
"""
import json
import os
import re
import sys
from collections import Counter, namedtuple
from datetime import datetime, timezone

import numpy as np
from PIL import Image

WEBP_QUALITY = 90
WEBP_METHOD = 4

# The minimap of one layer: the texture's object path (`/Game/Maps/Narva/Minimap/X.X`) and the rectangle it is
# stretched over, (min x, min y, max x, max y) in cm
Minimap = namedtuple("Minimap", "texture rect")
# What a layer's data asset sets: the texture's object path or None, the rectangle or None (corners not valid)
Override = namedtuple("Override", "texture rect")


def rectangle(x0, y0, x1, y1):
    """(min x, min y, max x, max y) of two opposite corners: the game stretches the texture over the min/max
    rectangle of its corners, so their order does not matter (BPFL_MapConversions takes FMin/FMax)."""
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def parse_layer_table(text):
    """`{layer: Minimap}` of the levels in the layers.tsv text: each level's `MapTexture` and corners.

    `layer` is the file name of the layer's .umap without extension. Lines without a texture (failed or without
    world settings) or without both corners are skipped.
    """
    levels = {}
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) != 6 or not fields[1].startswith("/") or "?" in fields[2:]:
            continue
        layer = fields[0].rsplit("/", 1)[-1].removesuffix(".umap")
        levels[layer] = Minimap(fields[1], rectangle(*map(float, fields[2:])))
    return levels


def object_name(path):
    """The object of an object path: `T_BlackCoast_Seed_v1` of `/BlackCoast/Maps/Minimap/BlackCoast_Seed_v1.T_BlackCoast_Seed_v1`."""
    return path.rsplit(".", 1)[-1]


def layer_override(exports):
    """`(layer, Override)` of the exports of one layer data asset, None when none of them is a layer (data tables).

    The layer is the object of the asset's first `Worlds` entry. An empty `OveriddenMinimapTexture` (absent, empty
    or `None`) keeps the level's texture; `MinimapCornersPosition` counts only with `bIsValid`.
    """
    for export in exports:
        properties = export.get("Properties") or {}
        if not properties.get("Worlds"):
            continue
        layer = object_name(properties["Worlds"][0]["AssetPathName"])
        texture = (properties.get("OveriddenMinimapTexture") or {}).get("AssetPathName") or None
        if texture == "None":
            texture = None
        corners = properties.get("MinimapCornersPosition") or {}
        rect = None
        if corners.get("bIsValid"):
            rect = rectangle(corners["Min"]["X"], corners["Min"]["Y"], corners["Max"]["X"], corners["Max"]["Y"])
        return layer, Override(texture, rect)
    return None


def read_layer_data(directory):
    """`{layer: Override}` of every layer data asset dumped as JSON under the directory."""
    overrides = {}
    for root, _, files in os.walk(directory):
        for filename in sorted(files):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(root, filename), encoding="utf-8") as f:
                found = layer_override(json.load(f))
            if found is not None:
                overrides[found[0]] = found[1]
    return overrides


def layer_table(levels, overrides):
    """`{layer: Minimap}` the game shows: the level's texture and corners, each replaced by the layer data's."""
    table = {}
    for layer, level in levels.items():
        override = overrides.get(layer, Override(None, None))
        table[layer] = Minimap(override.texture or level.texture, override.rect or level.rect)
    return table


def map_name(layer):
    """The map of a layer: the first `_` token of its name."""
    return layer.split("_", 1)[0]


def base_textures(table):
    """`{map: texture}`: the texture most of a map's layers show (ties: the alphabetically first path)."""
    usage = {}
    for layer, minimap in table.items():
        usage.setdefault(map_name(layer), Counter())[minimap.texture] += 1
    return {name: min(counts, key=lambda t: (-counts[t], t)) for name, counts in usage.items()}


def find_layer_minimaps(table):
    """`{layer: Minimap}` of the layers whose texture is not their map's base texture, sorted by layer.

    A layer that shows the base texture over other corners (Skorpo_Invasion_v1's data asset) has no picture of its
    own: the calculator shows the whole-map image there, placed where that texture lies on the world.
    """
    base = base_textures(table)
    return {layer: minimap for layer, minimap in sorted(table.items()) if minimap.texture != base[map_name(layer)]}


def base_texture_elsewhere(table):
    """`{layer: Minimap}` of the layers that show their map's base texture over a rectangle the other layers do not."""
    base = base_textures(table)
    usual = {}
    for layer, minimap in table.items():
        if minimap.texture == base[map_name(layer)]:
            usual.setdefault(map_name(layer), Counter())[minimap.rect] += 1
    return {layer: minimap for layer, minimap in sorted(table.items())
            if minimap.texture == base[map_name(layer)] and usual[map_name(layer)].most_common(1)[0][0] != minimap.rect}


def package_name(texture):
    """The package file name of a texture's object path: `BlackCoast_Seed_v1` of `/BlackCoast/Maps/Minimap/BlackCoast_Seed_v1.T_BlackCoast_Seed_v1`."""
    return texture.rsplit(".", 1)[0].rsplit("/", 1)[-1]


def pak_pattern(textures):
    """Regular expression over pak paths matching the packages of the textures' object paths.

    `/Game/<path>` lies in `SquadGame/Content/<path>`, a plugin's `/<Plugin>/<path>` in
    `.../<Plugin>/Content/<path>` (for example `SquadGame/Plugins/Expansions/BlackCoast/Content/Maps/...`).
    """
    parts = []
    for texture in sorted(set(textures)):
        root, path = texture.rsplit(".", 1)[0].lstrip("/").split("/", 1)
        prefix = "^SquadGame/Content/" if root == "Game" else f"/{re.escape(root)}/Content/"
        parts.append(prefix + re.escape(path) + r"\.uasset$")
    return "|".join(parts)


def folder_name(texture):
    """Folder of a texture under the tiles directory: its object name in lower case."""
    return object_name(texture).lower()


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
    """`(package, pixel format, width, height)` of an extractor file name `<package>.<format>.<w>x<h>.bin`."""
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


def manifest_entry(minimap, folder, size):
    """Manifest entry of one layer: texture, folder, side in px and the rectangle's min and max corner in metres."""
    x0, y0, x1, y1 = minimap.rect
    return {
        "texture": object_name(minimap.texture),
        "folder": folder,
        "size": size,
        "min": [round(x0 / 100, 5), round(y0 / 100, 5)],
        "max": [round(x1 / 100, 5), round(y1 / 100, 5)],
    }


def write_webp(image, path):
    """Writes the image as webp under a temporary name, then renames it into place."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    Image.fromarray(image).save(temporary, "WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
    os.replace(temporary, path)


def read_tables(layers_path, layer_data_dir):
    """The layer table of the game: the levels of layers.tsv with the overrides of the layer data assets."""
    with open(layers_path, encoding="utf-8") as f:
        levels = parse_layer_table(f.read())
    return layer_table(levels, read_layer_data(layer_data_dir))


def print_textures(layers_path, layer_data_dir):
    """Prints the pak path pattern of the textures the layer minimaps need."""
    wanted = find_layer_minimaps(read_tables(layers_path, layer_data_dir))
    print(pak_pattern(minimap.texture for minimap in wanted.values()))


def build(layers_path, layer_data_dir, texture_dir, manifest_path, tiles_dir):
    """Writes the webp of every layer minimap texture and the manifest keyed by layer."""
    table = read_tables(layers_path, layer_data_dir)
    wanted = find_layer_minimaps(table)
    for layer, minimap in base_texture_elsewhere(table).items():
        print(f"{layer}: the map's own texture over {minimap.rect} cm, no picture of its own", flush=True)
    raw_files = {}
    for filename in os.listdir(texture_dir):
        if filename.endswith(".bin"):
            raw_files[parse_raw_name(filename)[0].lower()] = filename
    written = {}
    layers = {}
    for layer, minimap in wanted.items():
        if minimap.texture not in written:
            filename = raw_files.get(package_name(minimap.texture).lower())
            if filename is None:
                raise SystemExit(f"no raw texture for {minimap.texture} in {texture_dir}")
            _, pixel_format, width, height = parse_raw_name(filename)
            with open(os.path.join(texture_dir, filename), "rb") as f:
                image = decode_texture(f.read(), pixel_format, width, height)
            write_webp(image, os.path.join(tiles_dir, folder_name(minimap.texture), "0", "0_0.webp"))
            written[minimap.texture] = width
            print(f"{object_name(minimap.texture)}: {pixel_format} {width}x{height}", flush=True)
        layers[layer] = manifest_entry(minimap, folder_name(minimap.texture), written[minimap.texture])
        print(f"{layer}: {layers[layer]['texture']} {layers[layer]['min']} {layers[layer]['max']}", flush=True)
    with open(manifest_path, encoding="utf-8") as f:
        game_build = client_build(f.read())
    manifest = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build": game_build,
        "layers": layers,
    }
    target = os.path.join(tiles_dir, "layer-minimaps.json")
    with open(target + ".tmp", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    os.replace(target + ".tmp", target)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "textures":
        print_textures(*sys.argv[2:])
    elif len(sys.argv) == 7 and sys.argv[1] == "build":
        build(*sys.argv[2:])
    else:
        raise SystemExit(__doc__)
