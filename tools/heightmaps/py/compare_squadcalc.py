"""Error of SquadCalc's 8-bit R/B heightmap against a SquadHeight export on the same grid."""

import json
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def main(squadcalc_png, squadheight_dir, z_step):
    rgb = np.asarray(Image.open(squadcalc_png)).astype(np.float64)
    calc = (255 + rgb[..., 0] - rgb[..., 2]) * float(z_step)
    meta = json.load(open(f"{squadheight_dir}/meta.json"))
    truth = np.asarray(Image.open(f"{squadheight_dir}/heightmap.png")).astype(np.float64) * meta["png_meters_per_unit"]
    if calc.shape != truth.shape:
        raise SystemExit(f"shape {calc.shape} != {truth.shape}")
    diff = calc - truth
    offset = np.median(diff)
    err = np.abs(diff - offset)
    print(f"offset={offset:+.2f} mean|err|={err.mean():.3f} p50={np.median(err):.3f} p95={np.percentile(err, 95):.3f} "
          f"p99={np.percentile(err, 99):.3f} max={err.max():.2f} >1m={(err > 1).mean():.4f} >3m={(err > 3).mean():.4f} levels={len(np.unique(calc))}")


if __name__ == "__main__":
    main(*sys.argv[1:])
