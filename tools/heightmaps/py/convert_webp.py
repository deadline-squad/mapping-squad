"""Add heightmap.webp to built precise heightmaps, and prove it equals the PNG.

Usage: convert_webp.py <heightmaps root> <out root> [map folder ...]

Reads <root>/<map>/heightmap.png and meta.json of every map (or the given folders) and writes
<out>/<map>/heightmap.webp and the meta.json that announces it (see heightmap_webp.py); the PNG
is not touched and not copied. Before it writes, the WebP is decoded again and compared with the levels
it was made from (exact), and the heights with the PNG's: a map whose step stays the same must match
the PNG pixel for pixel; where the step is coarsened every height must be within half of the new step
of the PNG's. Exits with 1 when a check fails. Prints one line per map.
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
    png_step = meta["z_step_m"]
    step = heightmap_webp.step_for(meta["map"], png_step)
    if step == png_step:
        levels = png
    else:
        levels = np.clip(np.rint(png.astype(np.float64) * (png_step / step)), 0, 65535).astype(np.uint16)

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, heightmap_webp.FILE)
    heightmap_webp.encode(levels, path)

    decoded = heightmap_webp.decode(path)
    roundtrip_mismatch = int((decoded != levels).sum())
    png_mismatch = int((decoded != png).sum()) if step == png_step else None
    error_m = float(np.abs(decoded.astype(np.float64) * step - png.astype(np.float64) * png_step).max())
    ok = roundtrip_mismatch == 0 and error_m <= step / 2 + 1e-9 and (png_mismatch in (None, 0))

    meta["format"] = heightmap_webp.FORMAT
    meta["generated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["png"] = "heightmap.png: 16-bit grayscale PNG; height above z_min_m = value * z_step_m"
    meta["webp"] = heightmap_webp.meta_entry(levels, step, path)
    json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)

    png_bytes = os.path.getsize(os.path.join(source_dir, "heightmap.png"))
    webp_bytes = os.path.getsize(path)
    return (f"{'ok  ' if ok else 'FAIL'} {meta['map']:<12} png {png_bytes / 1e6:6.2f} MB -> webp {webp_bytes / 1e6:6.2f} MB "
            f"({100 * (webp_bytes / png_bytes - 1):+5.1f} %)  step {png_step * 1000:6.3f} -> {step * 1000:6.3f} mm  "
            f"png mismatches {png_mismatch if png_mismatch is not None else 'n/a (requantised)'}  roundtrip mismatches {roundtrip_mismatch}  "
            f"max height error {error_m * 1000:.3f} mm (limit {step / 2 * 1000:.3f})"), ok


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
