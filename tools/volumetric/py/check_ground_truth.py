"""Compare map markers with real ground Z (from the game server log) against the heightmap and the voxel floors.

    python check_ground_truth.py <markers.txt> <map name prefix> <cols.npz> <heightmap dir> <terrain.npz>

Marker types FriendlyDirector, Option_Rally, Option_WheelIFV/APC and GridHeader_Spotted_Mine sit on the ground, so
their Z is the floor at that point (cm in the file). For each: terrain, the served top-surface height, and the
floors known to the voxel set (tops of up-facing voxels in the column, plus the terrain), and which of them lies
within TOL_M of the marker's Z.
"""

import sys

import numpy as np

import columns
import eval_los

GROUND_TYPES = ("FriendlyDirector", "Option_Rally", "Option_WheelIFV", "Option_WheelAPC", "GridHeader_Spotted_Mine")
TOL_M = 0.3


def floors_at(up, grid, x, y, terrain_z):
    col = int(np.floor((x - grid.min_x) / grid.cell))
    row = int(np.floor((y - grid.min_y) / grid.cell))
    base = (row * grid.width + col) << columns.Z_BITS
    z = up[(up >= base) & (up < base + (1 << columns.Z_BITS))] - base
    return sorted([terrain_z] + [(int(k) + 1) * grid.dz + grid.z_min for k in z])


def main():
    markers_path, prefix, cols_path, hm_dir, terrain_path = sys.argv[1:6]
    cols = np.load(cols_path)
    grid = columns.Grid(float(cols["min_x"]), float(cols["min_y"]), int(cols["width"]) * float(cols["cell"]), int(cols["height"]) * float(cols["cell"]), float(cols["cell"]), float(cols["dz"]), float(cols["z_min"]))
    top, b = eval_los.load_heightmap(hm_dir)
    ter = np.load(terrain_path)["z"]
    n = top_ok = floor_ok = covered = 0
    for line in open(markers_path):
        parts = line.split()
        if len(parts) < 5 or not parts[0].startswith(prefix) or not any(t in parts[1] for t in GROUND_TYPES):
            continue
        x, y, z = (float(v) / 100 for v in parts[2:5])
        c, r = int(np.floor(x - b["min_x"])), int(np.floor(y - b["min_y"]))
        if not (0 <= c < top.shape[1] and 0 <= r < top.shape[0]) or abs(z) < 1e-6:
            continue
        n += 1
        floors = floors_at(cols["up"], grid, x, y, float(ter[r, c]))
        top_ok += abs(top[r, c] - z) <= TOL_M
        floor_ok += any(abs(f - z) <= TOL_M for f in floors)
        covered += top[r, c] - z > TOL_M
        print(f"{parts[1][13:]:28s} z={z:7.2f} top={top[r, c]:7.2f} terrain={ter[r, c]:7.2f} floors={[round(f, 2) for f in floors][:4]}")
    print(f"markers with ground Z in the map: {n}; heightmap within {TOL_M} m: {top_ok}; voxel floors contain Z within {TOL_M} m: {floor_ok}; marker below the top surface by more than {TOL_M} m: {covered}")


if __name__ == "__main__":
    main()
