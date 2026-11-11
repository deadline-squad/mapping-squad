"""The grid of a heightmap: the game's landscape vertices, extended over the minimap bounds.

SquadCalc reads a heightmap with the game's own collision rule (``getHeight`` of src/js/squadHeightmaps.js in the deployment
repository): every quad of four nodes is two triangles split from node (row, col) to node (row + 1, col + 1), and the height
of a point is interpolated on the triangle it is in. That is the game's landscape collision exactly when the nodes are the
landscape's own vertices (``landscape.triangle_surface``), so the grid is the landscape's lattice. Node (col i, row j) lies at
world (metres; Unreal X east, Y south)

    origin + i * resolution * (cos yaw, sin yaw) + j * resolution * (-sin yaw, cos yaw)

``resolution`` is the landscape actor's scale (1 m on most maps, 0.5 m on Chora and Kokan, 0.75 m on Anvil, 1.2 m on Skorpo,
1.003937 m on Black Coast, 0.9999 m on Logar) and ``yaw`` its rotation (-2.006195 degrees on Skorpo, 0 elsewhere). The grid
holds the nodes of that lattice that cover the minimap bounds: along each lattice axis its first node is at or before the
bounds' lowest corner and its last at or after the highest, so every point of the bounds lies in a quad of the grid.

The map pipelines (tools/maptiles, tools/maprender, tools/volumetric) work on grids aligned with the minimap's corner
(``minimap_step``); ``on_grid`` reads a heightmap at the points of such a grid with the same rule as the page.
"""

import collections
import math

import numpy as np

STRIP_POINTS = 2_000_000
# Largest distance, in nodes, between a landscape actor's first vertex and a node of the map's lattice
SNAP_NODES = 1e-3

Lattice = collections.namedtuple("Lattice", "origin_x origin_y resolution yaw_deg width height")


def landscape_lattice(actors):
    """(origin x, origin y, resolution, yaw) in metres and degrees of the vertices of a map's landscape actors.

    ``actors`` are the values of ``landscape.assemble`` of the map's levels; the origin is the first vertex of the first one.
    Raises ValueError when an actor is not on that lattice (another spacing, yaw, or vertices off its nodes).
    """
    base = None
    for grid, x0, y0, (loc, yaw, scale), _ in actors:
        if abs(scale[0] - scale[1]) > 1e-9 * scale[0]:
            raise ValueError(f"landscape scale {scale[:2]} differs along X and Y")
        x, y = _first_vertex(x0, y0, loc, yaw, scale)
        if base is None:
            base = (x, y, scale[0] / 100, yaw)
            continue
        if abs(scale[0] / 100 - base[2]) > 1e-9 or abs(yaw - base[3]) > 1e-9:
            raise ValueError(f"landscape actors with scale {scale[0] / 100} m and {base[2]} m, yaw {yaw} and {base[3]}")
        col, row = to_grid(Lattice(base[0], base[1], base[2], base[3], 0, 0), np.array(x), np.array(y))
        if max(abs(col - round(float(col))), abs(row - round(float(row)))) > SNAP_NODES:
            raise ValueError(f"landscape actor at ({x:.4f}, {y:.4f}) m is off the lattice of the first one")
    if base is None:
        raise ValueError("no landscape actor")
    return base


def _first_vertex(x0, y0, loc, yaw, scale):
    """World metres of local vertex (x0, y0) of a landscape actor (location cm, yaw degrees, scale cm per local unit)."""
    c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    lx, ly = x0 * scale[0], y0 * scale[1]
    return (loc[0] + c * lx - s * ly) / 100, (loc[1] + s * lx + c * ly) / 100


def covering(origin_x, origin_y, resolution, yaw_deg, bounds):
    """The Lattice of the nodes of (origin, resolution, yaw) that cover ``bounds`` (min_x, max_x, min_y, max_y metres)."""
    base = Lattice(origin_x, origin_y, resolution, yaw_deg, 0, 0)
    xs = np.array([bounds["min_x"], bounds["max_x"], bounds["min_x"], bounds["max_x"]], np.float64)
    ys = np.array([bounds["min_y"], bounds["min_y"], bounds["max_y"], bounds["max_y"]], np.float64)
    cols, rows = to_grid(base, xs, ys)
    # A corner within SNAP_NODES of a node is on it: no extra row of nodes for the rounding of its position
    first_col, last_col = math.floor(cols.min() + SNAP_NODES), math.ceil(cols.max() - SNAP_NODES)
    first_row, last_row = math.floor(rows.min() + SNAP_NODES), math.ceil(rows.max() - SNAP_NODES)
    x, y = to_world(base, np.array(float(first_col)), np.array(float(first_row)))
    return Lattice(float(x), float(y), float(resolution), float(yaw_deg), last_col - first_col + 1, last_row - first_row + 1)


def subdivided(lattice, factor):
    """The Lattice of ``factor`` times as many nodes along each axis, on the same extent (its every factor-th node is one of
    ``lattice``). The game's triangles are planar on each of its quads, so it reads bare landscape as exactly as ``lattice``."""
    return lattice._replace(resolution=lattice.resolution / factor, width=(lattice.width - 1) * factor + 1,
                            height=(lattice.height - 1) * factor + 1)


def to_grid(lattice, xs, ys):
    """Fractional (col, row) of world points (metres)."""
    c, s = math.cos(math.radians(lattice.yaw_deg)), math.sin(math.radians(lattice.yaw_deg))
    dx, dy = xs - lattice.origin_x, ys - lattice.origin_y
    return (c * dx + s * dy) / lattice.resolution, (-s * dx + c * dy) / lattice.resolution


def to_world(lattice, cols, rows):
    """World metres of fractional (col, row)."""
    c, s = math.cos(math.radians(lattice.yaw_deg)), math.sin(math.radians(lattice.yaw_deg))
    lx, ly = cols * lattice.resolution, rows * lattice.resolution
    return lattice.origin_x + c * lx - s * ly, lattice.origin_y + s * lx + c * ly


def to_local(lattice, xs, ys):
    """Points in the lattice's own metric frame: (col, row) * resolution."""
    cols, rows = to_grid(lattice, xs, ys)
    return cols * lattice.resolution, rows * lattice.resolution


def local_triangles(lattice, tris):
    """World triangles [t, 3, 3] (m) in the lattice's own metric frame (to_local), Z kept: what objects.rasterize walks with
    origin (0, 0) and the lattice's resolution."""
    x, y = to_local(lattice, tris[..., 0], tris[..., 1])
    return np.stack([x, y, tris[..., 2]], -1)


def node_rows(lattice, first, count):
    """World (x, y) [count, width] of the nodes of rows first .. first + count - 1."""
    cols, rows = np.meshgrid(np.arange(lattice.width, dtype=np.float64), np.arange(first, first + count, dtype=np.float64))
    return to_world(lattice, cols, rows)


def strips(lattice):
    """(first row, row count) of the strips of rows that hold about STRIP_POINTS nodes each."""
    per = max(1, STRIP_POINTS // lattice.width)
    return [(first, min(per, lattice.height - first)) for first in range(0, lattice.height, per)]


def read(values, lattice, xs, ys):
    """Height of ``values`` [height, width] (any unit) at world points with the page's rule (squadHeightmaps.js getHeight):
    the game's triangle split of every quad, the edge node within half a node outside the grid, NaN beyond."""
    rows, cols = values.shape
    col, row = to_grid(lattice, xs, ys)
    inside = (row >= -0.5) & (row <= rows - 0.5) & (col >= -0.5) & (col <= cols - 0.5)
    row = np.clip(row, 0, rows - 1)
    col = np.clip(col, 0, cols - 1)
    r0 = np.minimum(np.floor(row), rows - 2).astype(np.int64)
    c0 = np.minimum(np.floor(col), cols - 2).astype(np.int64)
    rw, cw = row - r0, col - c0
    corner = values[r0, c0].astype(np.float64)
    right = values[r0, c0 + 1].astype(np.float64)
    below = values[r0 + 1, c0].astype(np.float64)
    diagonal = values[r0 + 1, c0 + 1].astype(np.float64)
    z = np.where(cw >= rw, corner + (right - corner) * cw + (diagonal - right) * rw,
                 corner + (below - corner) * rw + (diagonal - below) * cw)
    return np.where(inside, z, np.nan)


def minimap_step(meta):
    """Metres between the points of the minimap-aligned grid of the map pipelines: 0.5 where the landscape's vertices are
    0.5 m apart or closer (Chora, Kokan), else SquadHeight's 1 m."""
    return 0.5 if meta["resolution_m"] <= 0.5 + 1e-9 else 1.0


def minimap_shape(bounds, step):
    """(rows, cols) of the grid of ``step`` metres from the bounds' min corner to its max corner, both included."""
    return (round((bounds["max_y"] - bounds["min_y"]) / step) + 1, round((bounds["max_x"] - bounds["min_x"]) / step) + 1)


def on_grid(values, lattice, bounds, step, dtype=np.float64):
    """``values`` read with ``read`` at the points (min_x + c * step, min_y + r * step) of the minimap-aligned grid
    [minimap_shape]: on bare landscape that is the game's collision at those points, exactly."""
    shape = minimap_shape(bounds, step)
    out = np.empty(shape, dtype)
    xs = bounds["min_x"] + np.arange(shape[1]) * step
    per = max(1, STRIP_POINTS // shape[1])
    for first in range(0, shape[0], per):
        ys = bounds["min_y"] + np.arange(first, min(first + per, shape[0])) * step
        gx, gy = np.meshgrid(xs, ys)
        out[first:first + len(ys)] = read(values, lattice, gx, gy)
    return out


def from_meta(meta):
    """The Lattice of a heightmap's meta.json (meta_entry). A heightmap built before the grid moved onto the landscape's
    vertices has no origin_m: its first sample is the bounds' min corner, along world X and Y."""
    if "origin_m" in meta:
        x, y = meta["origin_m"]
    else:
        x, y = meta["bounds_m"]["min_x"], meta["bounds_m"]["min_y"]
    return Lattice(float(x), float(y), float(meta["resolution_m"]), float(meta.get("yaw_deg", 0.0)), int(meta["width"]), int(meta["height"]))


def meta_entry(lattice):
    """The keys of meta.json that name the grid."""
    return {"origin_m": [lattice.origin_x, lattice.origin_y], "resolution_m": lattice.resolution, "yaw_deg": lattice.yaw_deg,
            "width": lattice.width, "height": lattice.height}
