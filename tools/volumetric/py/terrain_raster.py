"""Landscape-only heights of one map ("TER1"): the ground that the voxel layer needs under the objects.

The served heightmap fuses the landscape with the buildings, so under a bridge or in a doorway it reports the roof.
The voxel layer (VCOL1) only holds what stands above the landscape, so a page that answers segment tests with it needs
the landscape alone, on the heightmap's own grid, plus the quads the landscape visibility mask cut out (holes do not block).

    python terrain_raster.py <slug> <heightmap meta.json> <out terrain.bin>

File layout (little endian), before gzip:
    magic "TER1\\0\\0\\0\\0", float32 min_x, min_y, cell, z_min, step, uint32 width, height, hole_count
    width * height residuals, stored as all their low bytes then all their high bytes (gzip packs the planes better):
    the level of a vertex minus the plane prediction left + above - above-left (0 for a neighbour outside the grid),
    modulo 65536, as a signed 16-bit number zigzag coded ((r << 1) ^ (r >> 15)); level 0 = no landscape under the
    vertex, else z = z_min + (level - 1) * step
    hole_count varints: the vertex indices (row * width + column) of the holes, as differences of the sorted list.
Vertex (column, row) lies at world (min_x + column * cell, min_y + row * cell). A vertex is a hole when
``terrain.sample`` reports a hole at it (the flag of the quad the vertex is the lower corner of, as eval_los does).
"""

import gzip
import json
import struct
import sys

import numpy as np

import maps
import terrain

MAGIC = b"TER1\0\0\0\0"
HEADER = "<8s5f3I"
LANDSCAPE_ROOT = "/data/squad-extract/landscapes"
LEVELS = 65535
MIN_STEP_M = 0.05
STRIP_CELLS = 1_000_000
LEVEL_ROWS = 256


def sample_grid(actors, min_x, min_y, cell, width, height):
    """(z [height, width] with NaN where no landscape, hole [height, width]) at the grid vertices."""
    z = np.full((height, width), np.nan)
    hole = np.zeros((height, width), bool)
    xs = min_x + np.arange(width) * cell
    rows_per_strip = max(1, STRIP_CELLS // width)
    for first in range(0, height, rows_per_strip):
        ys = min_y + np.arange(first, min(height, first + rows_per_strip)) * cell
        gx, gy = np.meshgrid(xs, ys)
        z[first:first + len(ys)], hole[first:first + len(ys)] = terrain.sample(actors, gx, gy)
    return z, hole


def choose_step(z):
    """(z_min, step) that fit the heights of `z` in 16-bit levels (level 0 stays free for 'no landscape')."""
    known = z[~np.isnan(z)]
    z_min = float(np.floor(known.min())) if len(known) else 0.0
    step = max(MIN_STEP_M, np.ceil((known.max() - z_min) / (LEVELS - 1) * 1000) / 1000) if len(known) else MIN_STEP_M
    return z_min, float(step)


def varints(values):
    out = bytearray()
    for v in values:
        while v >= 0x80:
            out.append((v & 0x7F) | 0x80)
            v >>= 7
        out.append(v)
    return out


def encode(z, hole, min_x, min_y, cell):
    """gzip bytes of the TER1 file for heights `z` [height, width] (NaN: no landscape) and the hole mask."""
    height, width = z.shape
    z_min, step = choose_step(z)
    # int32 and row blocks keep the peak near three copies of the grid (a 66 M-vertex map fits in 4 GB)
    levels = np.zeros(z.shape, np.int32)
    for first in range(0, height, LEVEL_ROWS):
        block = z[first:first + LEVEL_ROWS]
        levels[first:first + LEVEL_ROWS] = np.where(np.isnan(block), 0, np.rint((np.nan_to_num(block) - z_min) / step) + 1)
    padded = np.pad(levels, ((1, 0), (1, 0)))
    residual = (levels - (padded[1:, :-1] + padded[:-1, 1:] - padded[:-1, :-1])) & 0xFFFF
    del padded, levels
    signed = np.where(residual >= 0x8000, residual - 0x10000, residual)
    del residual
    zigzag = ((signed << 1) ^ (signed >> 15)) & 0xFFFF
    del signed
    holes = np.flatnonzero(hole.ravel())
    head = struct.pack(HEADER, MAGIC, min_x, min_y, cell, z_min, step, width, height, len(holes))
    planes = (zigzag & 0xFF).astype(np.uint8).tobytes() + (zigzag >> 8).astype(np.uint8).tobytes()
    body = planes + bytes(varints(np.diff(holes, prepend=0).tolist()))
    return gzip.compress(head + body, 6)


def decode(blob):
    """(z [height, width] with NaN where no landscape, hole mask, header dict) from `encode` output."""
    raw = gzip.decompress(blob)
    size = struct.calcsize(HEADER)
    magic, min_x, min_y, cell, z_min, step, width, height, hole_count = struct.unpack_from(HEADER, raw, 0)
    if magic != MAGIC:
        raise ValueError("not a TER1 file")
    count = width * height
    low = np.frombuffer(raw, np.uint8, count, size).astype(np.int64)
    high = np.frombuffer(raw, np.uint8, count, size + count).astype(np.int64)
    zigzag = low | (high << 8)
    residual = ((zigzag >> 1) ^ -(zigzag & 1)).reshape(height, width)
    levels = np.cumsum(np.cumsum(residual, axis=1), axis=0) & 0xFFFF
    z = np.where(levels == 0, np.nan, z_min + (levels - 1) * step)
    pos = size + 2 * count
    hole = np.zeros(width * height, bool)
    index = 0
    for _ in range(hole_count):
        shift = value = 0
        while True:
            b = raw[pos]
            pos += 1
            value |= (b & 0x7F) << shift
            if b < 0x80:
                break
            shift += 7
        index += value
        hole[index] = True
    header = dict(min_x=min_x, min_y=min_y, cell=cell, z_min=z_min, step=step, width=width, height=height, holes=hole_count)
    return z, hole.reshape(height, width), header


def main():
    slug, meta_path, out = sys.argv[1:4]
    meta = json.load(open(meta_path))
    b = meta["bounds_m"]
    cell = float(meta.get("resolution_m", 1.0))
    width = int(round((b["max_x"] - b["min_x"]) / cell)) + 1
    height = int(round((b["max_y"] - b["min_y"]) / cell)) + 1
    actors = [(g, h, x0, y0, root) for level in maps.MAPS[slug][1] for g, h, x0, y0, root in terrain.assemble(f"{LANDSCAPE_ROOT}/{level}").values()]
    z, hole = sample_grid(actors, b["min_x"], b["min_y"], cell, width, height)
    blob = encode(z, hole, b["min_x"], b["min_y"], cell)
    open(out, "wb").write(blob)
    print(json.dumps(dict(file=out, width=width, height=height, holes=int(hole.sum()), no_landscape=int(np.isnan(z).sum()), gzip_bytes=len(blob))))


if __name__ == "__main__":
    main()
