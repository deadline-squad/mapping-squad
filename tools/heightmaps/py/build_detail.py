"""Build the detail where objects stand (heightmap_detail.py) of heightmaps that build_all.py wrote.

Usage: build_detail.py <squadheight root> <extract root> <scene root> <heightmaps dir> [map ...]

For each map of maps.MAPS (or the ones named) whose folder in <heightmaps dir> holds heightmap.png and meta.json: the
heightmap's lattice subdivided by heightmap_detail.FACTOR, fused like the heightmap (build_all.fuse_on) in bands of whole quad
rows of at most BAND_NODES nodes; each quad's sub-grid nodes against the triangle rule's read of its four corners
(heightmap_detail.predicted); the smallest threshold whose file keeps heightmap.webp and the detail within the size of
heightmap.png (heightmap_detail.choose), written as heightmap.detail.bin with the ``detail`` entry of meta.json. A map where
no threshold fits gets neither (an earlier file and entry are removed), and the line printed for it says so.
"""

import json
import os
import sys

import numpy as np
from PIL import Image

import build_all
import heightmap_detail
import lattice
from maps import MAPS

# Fine nodes fused at once: beside its landscape and meshes, a band of 32 M nodes of Yehorivka does not fit a 4 GB container
# (with 16 M it peaks at 3.95 GB)
BAND_NODES = 16_000_000
CHUNK_QUAD_ROWS = 256


def band(fine, first_row, rows):
    """The Lattice of the rows first_row .. first_row + rows - 1 of the Lattice ``fine``."""
    x, y = lattice.to_world(fine, np.array(0.0), np.array(float(first_row)))
    return fine._replace(origin_x=float(x), origin_y=float(y), height=rows)


def sub_grid_levels(fused, meta, first_quad_row, quad_rows, factor):
    """Int64 [quad_rows, quad columns, inner nodes]: the levels (meta.json z_min_m and z_step_m) of the sub-grid nodes of the
    quads of ``fused`` (the fine nodes of a band whose row 0 is the top edge of quad row first_quad_row) that are not their
    corners, in the order of heightmap_detail.inner_nodes."""
    i, j = (np.array(axis, np.int64) for axis in zip(*heightmap_detail.inner_nodes(factor)))
    rows = (first_quad_row + np.arange(quad_rows))[:, None, None] * factor + i
    cols = np.arange((fused.shape[1] - 1) // factor)[None, :, None] * factor + j
    return np.rint((fused[rows, cols].astype(np.float64) - meta["z_min_m"]) / meta["z_step_m"]).astype(np.int64)


def residuals_of(levels, meta, sources, label):
    """(sorted flat indices of the quads whose sub-grid nodes lie more than the smallest threshold from the triangle rule's
    read, the largest |residual| of each, their residuals int64 [n, inner nodes]) of the heightmap ``levels``
    [height, width] described by ``meta``, fused from ``sources`` (build_all.sources)."""
    factor = heightmap_detail.FACTOR
    grid = lattice.from_meta(meta)
    fine = lattice.subdivided(grid, factor)
    quad_rows, quad_cols = grid.height - 1, grid.width - 1
    per_band = max(1, BAND_NODES // (fine.width * factor))
    smallest = heightmap_detail.THRESHOLDS_M[0] / meta["z_step_m"]
    quads, largest, residuals = [], [], []
    for first in range(0, quad_rows, per_band):
        last = min(first + per_band, quad_rows)
        fused, _ = build_all.fuse_on(f"{label} quad rows {first}-{last - 1}", band(fine, first * factor, (last - first) * factor + 1),
                                     *sources)
        if not np.isfinite(fused).all():
            raise ValueError(f"{label}: fused heights that are not finite in quad rows {first}-{last - 1}")
        for row in range(first, last, CHUNK_QUAD_ROWS):
            count = min(CHUNK_QUAD_ROWS, last - row)
            nodes = sub_grid_levels(fused, meta, row - first, count, factor)
            r, c = np.meshgrid(np.arange(row, row + count), np.arange(quad_cols), indexing="ij")
            residual = nodes.reshape(-1, nodes.shape[-1]) - heightmap_detail.predicted(levels, r.ravel(), c.ravel(), factor)
            most = np.abs(residual).max(1)
            keep = most > smallest
            quads.append((r.ravel() * quad_cols + c.ravel())[keep])
            largest.append(most[keep])
            residuals.append(residual[keep])
        del fused
    return np.concatenate(quads), np.concatenate(largest), np.concatenate(residuals)


def main(squadheight_root, extract_root, scene_root, heightmaps_dir, *only):
    for slug in MAPS:
        out_dir = os.path.join(heightmaps_dir, slug)
        if only and slug not in only or not os.path.exists(os.path.join(out_dir, "heightmap.png")):
            continue
        meta_path = os.path.join(out_dir, "meta.json")
        with open(meta_path) as f:
            meta = json.load(f)
        with Image.open(os.path.join(out_dir, "heightmap.png")) as image:
            levels = np.asarray(image)
        sh_meta, sh_surface, actors, statics, scene = build_all.sources(squadheight_root, extract_root, scene_root, slug)
        quads, largest, residuals = residuals_of(levels, meta, (sh_meta, sh_surface, actors, statics, scene), f"{slug} detail")
        del sh_surface, actors
        budget = os.path.getsize(os.path.join(out_dir, "heightmap.png")) - os.path.getsize(os.path.join(out_dir, meta["webp"]["file"]))
        shape = (meta["height"] - 1, meta["width"] - 1)
        chosen, sizes = heightmap_detail.choose(shape, quads, largest, residuals, heightmap_detail.FACTOR, budget, meta["z_step_m"])
        path = os.path.join(out_dir, heightmap_detail.FILE)
        if chosen:
            threshold, flags, data = chosen
            with open(path, "wb") as f:
                f.write(data)
            meta["detail"] = heightmap_detail.meta_entry(threshold, flags, data, heightmap_detail.FACTOR,
                                                         heightmap_detail.unit_levels(meta["z_step_m"]))
        else:
            if os.path.exists(path):
                os.remove(path)
            meta.pop("detail", None)
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=1)
        print(slug, "detail", json.dumps({"budget_bytes": budget, "bytes_by_threshold_m": sizes,
                                           "detail": meta.get("detail", "none: no threshold fits the budget")}), flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
