"""Compare a map's heightmap with ground positions recorded by the game server.

Usage: audit_ground_truth.py <heightmaps dir> <map> <points file> [--extract <extract root>] [--objects] [--csv <file>]
                             [--all-kinds] [--tolerance <metres>]

The points file holds anonymous lines ``<MapFolder> <Kind> x y z`` (world centimetres), written by
``log_points.awk`` from a dedicated server log: placed map markers, deployables, spawn points. Kinds whose
Z is the position the server traced onto the ground are compared (GROUND_KINDS); ``--all-kinds`` compares
every kind to show which ones are not ground traces. Spawn points are the player capsule's centre and are
lowered by KIND_OFFSET_M. The file may not carry anything else: a line with an
extra word (a name) is rejected.

For each point the table gives the logged Z and the heightmap read four ways (bilinear, nearest, and
triangle along the game's diagonal, which is what SquadCalc reads), the difference of the triangle read,
and a verdict. With ``--extract`` the game's own landscape surface at the point joins it (``terrain``), and
with ``--objects`` the static meshes (the highest collision above the point, and the closest object).

Verdicts:
    ok              within the tolerance of the logged Z
    no-trace        the log has Z = 0: the server did not trace the ground for it
    sub-cell        the landscape surface agrees with the log but the heightmap grid does not
    grid-object     the heightmap holds an object (>= 0.5 m above the landscape) at a corner of the cell
                    that the log's ground does not stand on
    object          a static mesh collides at the logged Z: the heightmap lacks it or reads it between samples
    above-terrain   the log is above the landscape and no static mesh explains it (actors the paks do not place)
    below-terrain   the log is below the landscape surface
    unexplained     none of the above
"""

import argparse
import csv
import json
import os
import re
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

LINE = re.compile(r"^(\w+) ([\w:]+) (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)$")
GROUND_KINDS = (
    "Deployable:", "SpawnPoint:", "BP_MapMarker_Action_MoveSL", "BP_MapMarker_Action_MoveFT",
    "BP_MapMarker_POI", "BP_MapMarker_GridHeader_Spotted", "BP_MapMarker_Option_Rally",
    "BP_MapMarker_Option_Wheel", "BP_MapMarker_FriendlyDirector",
)
# Kinds logged at a fixed height above the ground: a spawn point is the centre of the player capsule
# (median 0.882 m above the landscape on Fallujah, Goose Bay, Black Coast and Yehorivka open ground).
KIND_OFFSET_M = {"SpawnPoint:": 0.88}
OBJECT_MIN_M = 0.5


def normalised(text):
    """Lower-case letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def folder_matches(folder, slug, squadheight_name):
    """Whether a log's map folder (Fallujah_City, Goose_Bay, AlBasrah) is the map `slug`."""
    folder = normalised(folder)
    return folder.startswith(normalised(slug)) or folder.startswith(normalised(squadheight_name))


def parse_points(lines, slug, squadheight_name):
    """The (kind, x, y, z) points of a map in metres, from anonymous point lines; z has KIND_OFFSET_M taken off.

    Raises ValueError for a line that is not ``<MapFolder> <Kind> x y z``: the file must stay anonymous.
    """
    points = []
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        match = LINE.match(line)
        if not match:
            raise ValueError(f"line {number} is not '<MapFolder> <Kind> x y z': {line[:40]!r}")
        folder, kind, x, y, z = match.groups()
        if folder_matches(folder, slug, squadheight_name):
            offset = next((v for k, v in KIND_OFFSET_M.items() if kind.startswith(k)), 0.0)
            points.append((kind, float(x) / 100, float(y) / 100, float(z) / 100 - offset))
    return points


class HeightGrid:
    """A served heightmap: levels * step + minimum on a grid from the bounds' min corner, row = world Y."""

    def __init__(self, heights, min_x, min_y, resolution):
        self.heights = heights
        self.min_x = min_x
        self.min_y = min_y
        self.resolution = resolution

    @classmethod
    def load(cls, directory):
        """Read ``heightmap.png`` and ``meta.json`` from a map's directory."""
        meta = json.load(open(os.path.join(directory, "meta.json")))
        levels = np.asarray(Image.open(os.path.join(directory, "heightmap.png"))).astype(np.float64)
        bounds = meta["bounds_m"]
        return cls(levels * meta["z_step_m"] + meta["z_min_m"], bounds["min_x"], bounds["min_y"], meta["resolution_m"])

    def cell(self, x, y):
        """(row, column, row fraction, column fraction) of world metres, or None outside the grid."""
        col = (x - self.min_x) / self.resolution
        row = (y - self.min_y) / self.resolution
        rows, cols = self.heights.shape
        if not (0 <= col < cols - 1 and 0 <= row < rows - 1):
            return None
        r0, c0 = int(row), int(col)
        return r0, c0, row - r0, col - c0

    def bilinear(self, x, y):
        """Bilinear read between the four samples around the point (what SquadCalc did before)."""
        found = self.cell(x, y)
        if found is None:
            return float("nan")
        r, c, fy, fx = found
        h = self.heights
        return (h[r, c] * (1 - fx) * (1 - fy) + h[r, c + 1] * fx * (1 - fy)
                + h[r + 1, c] * (1 - fx) * fy + h[r + 1, c + 1] * fx * fy)

    def nearest(self, x, y):
        """The nearest sample."""
        found = self.cell(x, y)
        if found is None:
            return float("nan")
        r, c, fy, fx = found
        return self.heights[r + (fy >= 0.5), c + (fx >= 0.5)]

    def triangle(self, x, y):
        """Read along the game's diagonal: each quad is two triangles split from (row, col) to (row + 1, col + 1)."""
        found = self.cell(x, y)
        if found is None:
            return float("nan")
        r, c, fy, fx = found
        h = self.heights
        if fx >= fy:
            return h[r, c] + fx * (h[r, c + 1] - h[r, c]) + fy * (h[r + 1, c + 1] - h[r, c + 1])
        return h[r, c] + fy * (h[r + 1, c] - h[r, c]) + fx * (h[r + 1, c + 1] - h[r + 1, c])


def verdict(row, tolerance):
    """Name the cause of a point's difference from the logged Z (see the module description)."""
    log_z, hm, terrain = row["log_z"], row["hm_triangle"], row["terrain"]
    if log_z == 0:
        return "no-trace"
    if np.isnan(hm):
        return "outside"
    if abs(hm - log_z) <= tolerance:
        return "ok"
    if not np.isnan(terrain) and abs(terrain - log_z) <= tolerance:
        return "grid-object" if row["grid_object"] else "sub-cell"
    if row["object_top"] > -np.inf and abs(row["object_top"] - log_z) <= 0.3:
        return "object"
    if not np.isnan(terrain):
        if log_z < terrain - tolerance:
            return "below-terrain"
        return "above-terrain"
    return "unexplained"


def audit(grid, points, actors=None, objects_dir=None, tolerance=0.15):
    """One dict per point: the reads of the heightmap, the landscape and the objects, and a verdict."""
    from landscape import sample_world

    rows = []
    for kind, x, y, z in points:
        row = {"kind": kind, "x": x, "y": y, "log_z": z, "terrain": float("nan"), "grid_object": False,
               "object_top": -np.inf, "object": "", "near": "", "near_m": float("nan"), "near_top": float("nan")}
        row.update(hm_bilinear=grid.bilinear(x, y), hm_nearest=grid.nearest(x, y), hm_triangle=grid.triangle(x, y))
        if actors:
            at = lambda px, py: next((v for v in (sample_world(a, np.array([px * 100.0]), np.array([py * 100.0]), "triangle")[0] / 100
                                                  for a in actors) if not np.isnan(v)), float("nan"))
            row["terrain"] = at(x, y)
            found = grid.cell(x, y)
            if found is not None and not np.isnan(row["terrain"]):
                r, c = found[0], found[1]
                for dr in (0, 1):
                    for dc in (0, 1):
                        corner = at(grid.min_x + (c + dc) * grid.resolution, grid.min_y + (r + dr) * grid.resolution)
                        if grid.heights[r + dr, c + dc] - corner >= OBJECT_MIN_M:
                            row["grid_object"] = True
        rows.append(row)
    if objects_dir:
        import objects

        xs = np.array([r["x"] for r in rows])
        ys = np.array([r["y"] for r in rows])
        top, top_mesh, near_m, near_top, near_mesh = objects.probe_points(objects_dir, xs, ys)
        for row, t, tm, nm, nt, nmesh in zip(rows, top, top_mesh, near_m, near_top, near_mesh):
            row["object_top"] = t
            row["object"] = objects.mesh_name(objects_dir, tm) if tm else ""
            row["near"] = objects.mesh_name(objects_dir, nmesh) if nmesh else ""
            row["near_m"], row["near_top"] = (nm, nt) if nmesh else (float("nan"), float("nan"))
    for row in rows:
        row["diff"] = row["hm_triangle"] - row["log_z"]
        row["verdict"] = verdict(row, tolerance)
    return rows


def describe(values, label):
    """One summary line of absolute differences."""
    values = np.abs(np.asarray(values, dtype=float))
    values = values[~np.isnan(values)]
    if not values.size:
        return f"{label}: no points"
    return (f"{label}: n={values.size} median {np.median(values):.3f} m  within 2 cm {np.mean(values <= 0.02):.0%}  "
            f"within 15 cm {np.mean(values <= 0.15):.0%}  p95 {np.percentile(values, 95):.3f} m")


def report(rows, out=sys.stdout):
    """Print the table of the points that differ and the summaries."""
    header = f"{'kind':34s} {'x':>9s} {'y':>9s} {'log':>8s} {'bilin':>8s} {'nearest':>8s} {'triangle':>8s} {'diff':>7s} {'terrain':>8s}  verdict / object"
    print(header, file=out)
    for row in rows:
        if row["verdict"] == "ok":
            continue
        extra = row["verdict"]
        if row["object"]:
            extra += f" on {row['object'].rsplit('/', 1)[-1]} top {row['object_top']:.2f}"
        elif row["near"]:
            extra += f" near {row['near'].rsplit('/', 1)[-1]} {row['near_m']:.1f} m top {row['near_top']:.2f}"
        print(f"{row['kind'][:34]:34s} {row['x']:9.2f} {row['y']:9.2f} {row['log_z']:8.2f} {row['hm_bilinear']:8.2f} "
              f"{row['hm_nearest']:8.2f} {row['hm_triangle']:8.2f} {row['diff']:7.2f} {row['terrain']:8.2f}  {extra}", file=out)
    print(file=out)
    usable = [r for r in rows if r["verdict"] not in ("no-trace", "outside")]
    for name in ("hm_bilinear", "hm_nearest", "hm_triangle"):
        print(describe([r[name] - r["log_z"] for r in usable if r["verdict"] in ("ok", "sub-cell")], f"{name:12s} on ok+sub-cell points"), file=out)
    if any(not np.isnan(r["terrain"]) for r in rows):
        print(describe([r["terrain"] - r["log_z"] for r in usable], "landscape     on all traced points"), file=out)
    counts = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    print("verdicts:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1])), file=out)
    kinds = {}
    for row in rows:
        kinds.setdefault(row["kind"], []).append(row["diff"])
    print("by kind:", file=out)
    for kind, diffs in sorted(kinds.items(), key=lambda kv: -len(kv[1])):
        print("  " + describe(diffs, f"{kind[:40]:40s}"), file=out)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("heightmaps")
    parser.add_argument("map")
    parser.add_argument("points")
    parser.add_argument("--extract", help="extract root (landscapes/ and statics/<map>/): adds the landscape and objects")
    parser.add_argument("--objects", action="store_true", help="probe the static meshes (slow: reads all of them)")
    parser.add_argument("--csv")
    parser.add_argument("--all-kinds", action="store_true")
    parser.add_argument("--tolerance", type=float, default=0.15)
    args = parser.parse_args()

    import landscape
    from maps import MAPS

    squadheight_name, levels = MAPS[args.map]
    points = parse_points(open(args.points), args.map, squadheight_name)
    if not args.all_kinds:
        points = [p for p in points if p[0].startswith(GROUND_KINDS)]
    actors = None
    if args.extract:
        actors = []
        for level in levels:
            actors += list(landscape.assemble(os.path.join(args.extract, "landscapes", level), transpose=False).values())
    objects_dir = os.path.join(args.extract, "statics", args.map) if args.extract and args.objects else None
    rows = audit(HeightGrid.load(os.path.join(args.heightmaps, args.map)), points, actors, objects_dir, args.tolerance)
    report(rows)
    if args.csv:
        with open(args.csv, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
