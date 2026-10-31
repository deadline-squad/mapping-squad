"""List concrete places where the heightmap is wrong and the voxel columns right, with the blocking mesh name.

    python cases_report.py <cases.csv> <tris.npz> <statics dir> <heightmap dir> [count]

Prints a markdown table. The blocker is the first reference triangle on the segment (false_clear
cases); false_blocked cases have none: the segment is clear and the heightmap top above an endpoint's floor hides it.
"""

import csv
import json
import os
import sys

import numpy as np

import eval_los


def mesh_name(statics, part_row):
    mesh, _ = part_row
    key = f"s{mesh - 1_000_000}" if mesh >= 1_000_000 else str(mesh)
    try:
        return json.load(open(os.path.join(statics, "bodies", key + ".json")))["path"].split("/")[-1].split(".")[0]
    except (OSError, KeyError):
        return key


def main():
    cases_path, tris_path, statics, hm_dir = sys.argv[1:5]
    count = int(sys.argv[5]) if len(sys.argv) > 5 else 12
    parts = np.load(tris_path)["parts"]
    top, b = eval_los.load_heightmap(hm_dir)
    under = lambda x, y, z: max(0.0, top[int(y - b["min_y"]), int(x - b["min_x"])] - z)
    rows = [r for r in csv.DictReader(open(cases_path)) if r["heightmap"] != str(r["truth"]) and r["voxels"] == r["truth"]]
    rng = np.random.default_rng(3)
    by_kind = {"heightmap says BLOCKED, truth CLEAR": [r for r in rows if r["truth"] == "0"],
               "heightmap says CLEAR, truth BLOCKED": [r for r in rows if r["truth"] == "1"]}
    print(f"cases where heightmap wrong and voxels right: {len(rows)}")
    for kind, items in by_kind.items():
        print(f"\n{kind}: {len(items)}\n\n| A (x, y, floor z) | B (x, y, floor z) | length m | heightmap top above A / B floor m | blocker |\n|---|---|---|---|---|")
        for r in [items[i] for i in rng.permutation(len(items))[:count]]:
            blocker = mesh_name(statics, parts[int(r["blocker_part"])]) if int(r["blocker_part"]) >= 0 else "-"
            print(f"| {float(r['ax']):.1f}, {float(r['ay']):.1f}, {float(r['az']):.2f} | {float(r['bx']):.1f}, {float(r['by']):.1f}, {float(r['bz']):.2f} | {r['length']} | {under(float(r['ax']), float(r['ay']), float(r['az'])):.1f} / {under(float(r['bx']), float(r['by']), float(r['bz'])):.1f} | {blocker} |")


if __name__ == "__main__":
    main()
