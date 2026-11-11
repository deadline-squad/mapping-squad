"""Add heightmap.webp to built precise heightmaps, and prove it equals the PNG.

Usage: convert_webp.py <heightmaps root> <out root> [map folder ...]

Reads <root>/<map>/heightmap.png and meta.json of every map (or the given folders) and writes
<out>/<map>/heightmap.webp and the meta.json that announces it (see heightmap_webp.py); the PNG
is not touched and not copied. The WebP holds the PNG's levels at its step; before it writes, it is decoded again and
must match the PNG pixel for pixel. Exits with 1 when a check fails. Prints one line per map.
"""

import datetime
import json
import os
import sys

import numpy as np
from PIL import Image

import heightmap_webp

Image.MAX_IMAGE_PIXELS = None


def convert(source_dir, out_dir):
    """Convert one map folder; returns its report line and whether the checks passed."""
    meta = json.load(open(os.path.join(source_dir, "meta.json")))
    png = np.asarray(Image.open(os.path.join(source_dir, "heightmap.png")))
    if png.dtype != np.uint16 or png.ndim != 2:
        raise SystemExit(f"{source_dir}: not a 16-bit grayscale PNG")
    step = meta["z_step_m"]

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, heightmap_webp.FILE)
    heightmap_webp.encode(png, path)

    mismatch = int((heightmap_webp.decode(path) != png).sum())
    ok = mismatch == 0

    meta["format"] = heightmap_webp.FORMAT
    meta["generated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["png"] = "heightmap.png: 16-bit grayscale PNG; height above z_min_m = value * z_step_m"
    meta["webp"] = heightmap_webp.meta_entry(png, step, path)
    json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)

    png_bytes = os.path.getsize(os.path.join(source_dir, "heightmap.png"))
    webp_bytes = os.path.getsize(path)
    return (f"{'ok  ' if ok else 'FAIL'} {meta['map']:<12} png {png_bytes / 1e6:6.2f} MB -> webp {webp_bytes / 1e6:6.2f} MB "
            f"({100 * (webp_bytes / png_bytes - 1):+5.1f} %)  step {step * 1000:6.3f} mm  png mismatches {mismatch}"), ok


def main(root, out_root, *only):
    failed = False
    for name in sorted(only or os.listdir(root)):
        if not os.path.exists(os.path.join(root, name, "heightmap.png")):
            continue
        line, ok = convert(os.path.join(root, name), os.path.join(out_root, name))
        print(line, flush=True)
        failed |= not ok
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(*sys.argv[1:])
