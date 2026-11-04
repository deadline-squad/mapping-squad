"""Relief layer of a map as a PMTiles archive: python relief.py HEIGHTMAPS_DIR MAPTILES_DIR OUT_DIR MAP [options]

A high-fidelity shaded relief of the precise heightmap (tools/heightmaps), in the tile frame of the Detailed layer
(256 px WebP tiles, Leaflet CRS.Simple, the map square spanning 256 * 2^z px at zoom z, row 0 = minimum Y; see
README.md "Tile frame"), written as one PMTiles v3 archive (https://github.com/protomaps/PMTiles) of WebP tiles.

Shading, computed on the heightmap's own grid in float64 and tile-independent:

1. Horn gradients p (east) and q (north) of the 3 x 3 window, topometrics.gradients:
       p = ((z3 + 2 z6 + z9) - (z1 + 2 z4 + z7)) / (8 cell),   q = ((z1 + 2 z2 + z3) - (z7 + 2 z8 + z9)) / (8 cell)
   slope = atan(z_factor * hypot(p, q)); aspect = bearing of the downhill direction (clockwise from north).
2. One hillshade per azimuth az in (360, 315, 270, 225) degrees (compass bearing of the light), sun elevation e:
       HS(az) = cos(90 - e) cos(slope) + sin(90 - e) sin(slope) cos(az - aspect)       (clipped at 0)
3. Multi-directional oblique-weighted hillshade (Mark 1992; Esri's multidirectional hillshade): the weights favour
   the lights that cross the slope obliquely,
       w(az) = sin^2(aspect - az),   MDOW = sum(w HS) / sum(w)
   (the four weights always sum to 2 for azimuths 45 degrees apart; flat cells, whose aspect is undefined, get equal
   weights and the same HS for every azimuth).
4. Anisotropic sky-view factor of RVT (Relief Visualization Toolbox, Kokalj et al.: rvt.vis.sky_view_factor with
   compute_asvf, level 1, main direction 315 degrees, 16 directions, search radius SVF_RADIUS_M), stretched so that
   the map's 1st percentile becomes 0 and 1 stays 1.
5. Multiply blend of the stretched ASVF over MDOW at 50 % opacity: shade = MDOW * (0.5 + 0.5 * ASVF').
6. Optional hypsometric tint (--tint): a colour ramp over the map's 1st to 99th height percentile, multiplied by the
   shade, so the layer stays readable as relief.

The shade is resampled (Lanczos) to the pyramid's finest zoom: the grid sample at index i sits at X = min + i * cell and
the tile pixel (px, py) has its centre at min + (px + 0.5) * size / (256 * 2^z), the Detailed layer's convention. The
finest zoom is the first whose pixel is no coarser than the grid cell (plus --extra-zoom oversampling); coarser zooms
average 2 x 2 pixels of the zoom below. Heightmaps are shaded in blocks with a halo, so the memory stays bounded.
"""

import argparse
import io
import json
import os
import sys
import time

import numpy as np
from PIL import Image
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

import topometrics

Image.MAX_IMAGE_PIXELS = None

AZIMUTHS = (360.0, 315.0, 270.0, 225.0)
SUN_ELEVATION_DEG = 45.0
SVF_RADIUS_M = 25.0
SVF_DIRECTIONS = 16
ASVF_DIRECTION_DEG = 315
SVF_OPACITY = 0.5
TILE = 256
WEBP_QUALITY = 82

# Hypsometric ramp: position 0..1 -> RGB
TINT_RAMP = ((0.0, (74, 120, 92)), (0.25, (150, 176, 110)), (0.5, (218, 207, 150)), (0.75, (176, 134, 98)),
             (1.0, (236, 232, 228)))


def mdow(z, cell, z_factor=1.0, sun_elevation=SUN_ELEVATION_DEG, azimuths=AZIMUTHS):
    """Multi-directional oblique-weighted hillshade in 0..1 (float32) of a block of heights (float64, metres)."""
    p, q = topometrics.gradients(z, cell)
    p, q = p * z_factor, q * z_factor
    slope = np.arctan(np.hypot(p, q))
    aspect = np.arctan2(-p, -q)
    zenith = np.radians(90.0 - sun_elevation)
    weighted = np.zeros(z.shape)
    total = np.zeros(z.shape)
    for azimuth in azimuths:
        light = np.radians(azimuth)
        shade = np.maximum(np.cos(zenith) * np.cos(slope) + np.sin(zenith) * np.sin(slope) * np.cos(light - aspect), 0.0)
        weight = np.sin(aspect - light) ** 2
        weighted += weight * shade
        total += weight
    flat = total < 1e-12
    flat_shade = np.cos(zenith) * np.cos(slope)
    return np.where(flat, flat_shade, weighted / np.where(flat, 1.0, total)).astype(np.float32)


def asvf(z, cell):
    """RVT anisotropic sky-view factor (0..1, float32) of a block of heights."""
    import rvt.vis

    radius = max(1, round(SVF_RADIUS_M / cell))
    out = rvt.vis.sky_view_factor(z.astype(np.float32), cell, compute_svf=False, compute_asvf=True,
                                  svf_n_dir=SVF_DIRECTIONS, svf_r_max=radius, asvf_dir=ASVF_DIRECTION_DEG, asvf_level=1)
    return out["asvf"].astype(np.float32)


def shade_map(z, cell, z_factor=1.0, sun_elevation=SUN_ELEVATION_DEG):
    """MDOW and stretched ASVF of the whole map, block by block with a halo.

    Returns:
        (mdow, asvf_stretched) float32 arrays of z's shape.
    """
    halo = round(SVF_RADIUS_M / cell) + 2
    hillshade = np.empty(z.shape, dtype=np.float32)
    sky = np.empty(z.shape, dtype=np.float32)
    for start in range(0, z.shape[0], topometrics.BLOCK_ROWS):
        stop = min(start + topometrics.BLOCK_ROWS, z.shape[0])
        lo, hi = max(0, start - halo), min(z.shape[0], stop + halo)
        block = z[lo:hi]
        hillshade[start:stop] = mdow(block, cell, z_factor, sun_elevation)[start - lo:stop - lo]
        sky[start:stop] = asvf(block, cell)[start - lo:stop - lo]
    floor = float(np.percentile(sky, 1))
    return hillshade, np.clip((sky - floor) / (1.0 - floor), 0.0, 1.0)


def blend(hillshade, sky, opacity=SVF_OPACITY):
    """Multiply blend of `sky` over `hillshade` at `opacity`: hillshade * ((1 - opacity) + opacity * sky)."""
    return hillshade * ((1.0 - opacity) + opacity * sky)


def tint(z):
    """Hypsometric colour (float32 rows x cols x 3, 0..1) of heights, ramp over their 1st to 99th percentile."""
    low, high = np.percentile(z[::7, ::7], (1, 99))
    position = np.clip((z - low) / max(high - low, 1e-9), 0, 1)
    stops = np.array([stop for stop, _ in TINT_RAMP])
    colours = np.array([colour for _, colour in TINT_RAMP], dtype=np.float32) / 255.0
    return np.stack([np.interp(position, stops, colours[:, channel]) for channel in range(3)], axis=-1).astype(np.float32)


def finest_zoom(cells_across, extra_zoom):
    """First zoom whose pixel (map size / (256 * 2^z)) is no coarser than the grid cell, plus extra_zoom."""
    zoom = 0
    while TILE * 2**zoom < cells_across:
        zoom += 1
    return zoom + extra_zoom


def resample(image, rows, cols, size):
    """Lanczos resample of a grid whose samples sit on the frame's nodes (first and last on its edges) to size x size."""
    box = (0.5, 0.5, cols - 0.5, rows - 0.5)
    return np.asarray(Image.fromarray(image).resize((size, size), Image.LANCZOS, box=box), dtype=np.float32)


def tiles_of_level(level):
    """Yield (x, y, bytes) WebP tiles of a (size, size[, 3]) float 0..1 image."""
    size = level.shape[0]
    pixels = (np.clip(level, 0, 1) * 255 + 0.5).astype(np.uint8)
    for y in range(size // TILE):
        for x in range(size // TILE):
            tile = Image.fromarray(pixels[y * TILE:(y + 1) * TILE, x * TILE:(x + 1) * TILE]).convert("RGB")
            buffer = io.BytesIO()
            tile.save(buffer, "WEBP", quality=WEBP_QUALITY, method=4)
            yield x, y, buffer.getvalue()


def reduce_half(level):
    """Average of 2 x 2 pixels."""
    if level.ndim == 2:
        return level.reshape(level.shape[0] // 2, 2, level.shape[1] // 2, 2).mean(axis=(1, 3))
    return level.reshape(level.shape[0] // 2, 2, level.shape[1] // 2, 2, -1).mean(axis=(1, 3))


def write_pmtiles(path, levels, meta_json):
    """Write {zoom: image} as a PMTiles v3 archive of WebP tiles, tile ids in order."""
    entries = []
    for zoom, level in levels.items():
        entries += [(zxy_to_tileid(zoom, x, y), data) for x, y, data in tiles_of_level(level)]
    entries.sort(key=lambda entry: entry[0])
    with open(path, "wb") as handle:
        writer = Writer(handle)
        for tile_id, data in entries:
            writer.write_tile(tile_id, data)
        header = {
            "version": 3, "tile_compression": Compression.NONE, "tile_type": TileType.WEBP,
            "min_zoom": min(levels), "max_zoom": max(levels),
            "min_lon_e7": -1800000000, "min_lat_e7": -850000000, "max_lon_e7": 1800000000, "max_lat_e7": 850000000,
            "center_zoom": min(levels), "center_lon_e7": 0, "center_lat_e7": 0,
        }
        writer.finalize(header, meta_json)
    return len(entries)


def build(heightmaps_dir, maptiles_dir, out_dir, name, with_tint=False, extra_zoom=0, z_factor=1.0,
          sun_elevation=SUN_ELEVATION_DEG, suffix=""):
    """Render one map's relief archive to out_dir/<name><suffix>.pmtiles; returns a report dict."""
    started = time.time()
    z, meta = topometrics.load_heightmap(os.path.join(heightmaps_dir, name))
    with open(os.path.join(maptiles_dir, name, "meta.json")) as handle:
        tile_meta = json.load(handle)
    if tile_meta["bounds_m"] != meta["bounds_m"]:
        raise ValueError(f"{name}: the maptiles frame {tile_meta['bounds_m']} differs from the heightmap's {meta['bounds_m']}")
    cell = meta["resolution_m"]
    rows, cols = z.shape
    size_m = meta["bounds_m"]["max_x"] - meta["bounds_m"]["min_x"]
    max_zoom = finest_zoom(max(rows, cols) - 1, extra_zoom)
    hillshade, sky = shade_map(z, cell, z_factor, sun_elevation)
    shade = blend(hillshade, sky)
    finest = TILE * 2**max_zoom
    image = resample(shade, rows, cols, finest)
    if with_tint:
        colour = tint(z)
        image = image[..., None] * np.stack([resample(colour[..., c], rows, cols, finest) for c in range(3)], axis=-1)
    del hillshade, sky, shade
    levels = {max_zoom: image}
    for zoom in range(max_zoom - 1, -1, -1):
        levels[zoom] = reduce_half(levels[zoom + 1])
    meta_json = {
        "name": f"{meta['map']} relief", "format": "webp", "tileSize": TILE, "minNativeZoom": 0, "maxNativeZoom": max_zoom,
        "metresPerPixel": round(size_m / finest, 4), "bounds_m": meta["bounds_m"], "tint": with_tint,
        "method": {"hillshade": "MDOW, azimuths 360/315/270/225, Horn gradients", "sun_elevation_deg": sun_elevation,
                   "z_factor": z_factor, "svf": f"RVT ASVF level 1 dir {ASVF_DIRECTION_DEG}, {SVF_DIRECTIONS} dirs, "
                   f"{SVF_RADIUS_M} m, Multiply {int(SVF_OPACITY * 100)} %"},
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = os.path.join(out_dir, f"{name}{suffix}.pmtiles")
    os.makedirs(out_dir, exist_ok=True)
    temporary = path + ".tmp"
    tiles = write_pmtiles(temporary, levels, meta_json)
    os.replace(temporary, path)
    return {"map": name, "path": path, "max_zoom": max_zoom, "tiles": tiles, "bytes": os.path.getsize(path),
            "seconds": round(time.time() - started, 1)}


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("heightmaps")
    parser.add_argument("maptiles")
    parser.add_argument("out")
    parser.add_argument("maps", nargs="+")
    parser.add_argument("--tint", action="store_true", help="multiply a hypsometric tint with the shade")
    parser.add_argument("--extra-zoom", type=int, default=0, help="zooms beyond the grid's resolution")
    parser.add_argument("--z-factor", type=float, default=1.0)
    parser.add_argument("--sun-elevation", type=float, default=SUN_ELEVATION_DEG)
    parser.add_argument("--suffix", default="")
    args = parser.parse_args(argv)
    for name in args.maps:
        print(json.dumps(build(args.heightmaps, args.maptiles, args.out, name, args.tint, args.extra_zoom,
                               args.z_factor, args.sun_elevation, args.suffix)), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
