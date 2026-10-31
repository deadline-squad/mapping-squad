"""Union several built voxel sets (statics, foliage) of one map and write the VCOL1 file.

    python merge_encode.py <out.vcol> <cols.npz> [<cols.npz> ...]

The sets must share a grid. Prints a JSON line with voxel, column and run counts and the gzip size.
"""

import json
import sys

import numpy as np

import codec
import columns


def main():
    out, paths = sys.argv[1], sys.argv[2:]
    sets = [np.load(p) for p in paths]
    d = sets[0]
    grid = columns.Grid(float(d["min_x"]), float(d["min_y"]), int(d["width"]) * float(d["cell"]), int(d["height"]) * float(d["cell"]), float(d["cell"]), float(d["dz"]), float(d["z_min"]))
    occupied = np.unique(np.concatenate([s["occupied"] for s in sets]))
    blob = codec.encode(occupied, grid)
    open(out, "wb").write(blob)
    print(json.dumps(dict(file=out, voxels=int(len(occupied)), columns=int(len(np.unique(occupied >> columns.Z_BITS))), gzip_bytes=len(blob))))


if __name__ == "__main__":
    main()
