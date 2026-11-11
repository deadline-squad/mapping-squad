"""Check the game-file object surface (objects.py) against SquadHeight on a map with complete SDK data.

Usage: compare_objects.py <squadheight dir> <statics dir> <landscape level dir> [...]
With SAVE_NPZ=<file>, also saves the terrain, the fused surface and SquadHeight's for analysis.
"""

import json
import os
import sys

import numpy as np

import build_heightmap
import objects

OBJECT_M = 0.5


def main(squadheight_dir, statics_dir, *levels):
    meta, surface = build_heightmap.load_squadheight(squadheight_dir)
    # On SquadHeight's own grid, sample by sample
    grid = build_heightmap.squadheight_lattice(meta, surface)
    terrain = build_heightmap.game_terrain(build_heightmap.landscape_actors(levels), grid)
    top, stats = objects.object_surface(statics_dir, grid)
    ours = np.fmax(terrain, top)
    covered = ~np.isnan(terrain)
    sdk_obj = covered & (surface - terrain > OBJECT_M)
    our_obj = covered & (ours - terrain > OBJECT_M)
    both = sdk_obj & our_obj
    err = np.abs(ours - surface)[covered]
    print(json.dumps(stats))
    print(f"sdk_object_cells={sdk_obj.sum()} ours={our_obj.sum()} recall={both.sum() / max(sdk_obj.sum(), 1):.4f} "
          f"precision={both.sum() / max(our_obj.sum(), 1):.4f} "
          f"on_both |d|<0.5m={(np.abs(ours - surface)[both] < 0.5).mean():.4f} median|d|={np.median(np.abs(ours - surface)[both]):.3f}")
    if os.environ.get("SAVE_NPZ"):
        np.savez_compressed(os.environ["SAVE_NPZ"], terrain=terrain.astype(np.float32), ours=ours.astype(np.float32), surface=surface.astype(np.float32))
    print(f"all covered: |d|<0.5m={(err < 0.5).mean():.5f} |d|<2m={(err < 2).mean():.5f} p99.9={np.percentile(err, 99.9):.2f}")


if __name__ == "__main__":
    main(*sys.argv[1:])
