"""Compare an assembled game landscape against a SquadHeight export (world-space, metres)."""

import json
import sys

import numpy as np
from PIL import Image

import landscape

Image.MAX_IMAGE_PIXELS = None


def main(component_dir, squadheight_dir):
    meta = json.load(open(f"{squadheight_dir}/meta.json"))
    png = np.asarray(Image.open(f"{squadheight_dir}/heightmap.png")).astype(np.float64)
    surface = png * meta["png_meters_per_unit"] + meta["z_offset_m"]
    b = meta["bounds_m"]
    rows, cols = surface.shape
    xs = b["min_x"] + np.arange(cols) * meta["resolution_m"]
    ys = b["min_y"] + np.arange(rows) * meta["resolution_m"]
    gx, gy = np.meshgrid(xs * 100, ys * 100)
    for transpose in (False, True):
        actors = landscape.assemble(component_dir, transpose)
        terrain = np.full(surface.shape, np.nan)
        for actor, grid in actors.items():
            z = landscape.sample_world(grid, gx, gy) / 100
            terrain = np.where(np.isnan(terrain), z, terrain)
        diff = surface - terrain
        valid = ~np.isnan(diff)
        d = diff[valid]
        near = np.abs(d) < 1.0
        print(f"transpose={transpose} seam_mismatch={[round(g[4], 3) for g in actors.values()]} "
              f"valid={valid.mean():.4f} |d|<1m={near.mean():.4f} median={np.median(d):+.3f} "
              f"p05={np.percentile(d, 5):+.3f} p95={np.percentile(d, 95):+.3f} "
              f"near_mean={d[near].mean():+.4f} near_rms={np.sqrt((d[near] ** 2).mean()):.4f} "
              f">+0.5m={(d > 0.5).mean():.4f} <-0.5m={(d < -0.5).mean():.4f}")


if __name__ == "__main__":
    main(*sys.argv[1:])
