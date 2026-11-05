"""Heightmap of a map that is not in the server package, from SquadHeight alone.

Usage: build_squadheight_only.py <SquadHeight map folder> <out folder> <map name>

Belaya Pass is playable in the game but its level is not in the dedicated server package, so there is no landscape
collision or static mesh to fuse (README.md, map inventory). The heightmap is SquadHeight's top-most trace of the
Squad SDK collision, as exported, on SquadHeight's own 1 m grid (the same grid and orientation as the other maps,
build_heightmap.grid_shape) and written in the served form (PNG, WebP, meta.json). meta.json carries `provenance`
and `sources` saying so; nothing in it is derived from the server package, checked against server data or split
into terrain and objects, so none of the agreement statistics of the other maps exist for it.
"""

import sys

import build_heightmap

PROVENANCE = "SquadHeight 1.3.0 (Mod SDK export), terrain only, not validated against server data"


def build(squadheight_dir, out_dir, name):
    """Write `name`'s heightmap files into `out_dir` from the SquadHeight export in `squadheight_dir`."""
    meta, surface = build_heightmap.load_squadheight(squadheight_dir)
    rows, cols = build_heightmap.grid_shape(meta, meta["resolution_m"])
    if surface.shape != (rows, cols):
        raise ValueError(f"{squadheight_dir}: image is {surface.shape}, bounds and resolution give {(rows, cols)}")
    sources = {"sdk_surface": f"SquadHeight {meta['exported_utc']} (Squad Mod SDK collision trace, top-most)"}
    build_heightmap.write(out_dir, name, surface, meta, {}, None, sources=sources, provenance=PROVENANCE)


if __name__ == "__main__":
    build(*sys.argv[1:4])
