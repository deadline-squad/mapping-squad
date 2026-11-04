"""Pick wall / opening segments from the voxel parity data (SquadCalc engine/README.md, "Voxel columns") for
tools/browser_check/volume_check.mjs.

    python pick_volume_cases.py <slug> [parity dir]    (JSON on stdout; tools/browser_check/volume_cases.json)

The parity dir (default /par) holds <slug>.segments.f64 (count x 6 float64, file frame), .exact.f64 (distance to the first
triangle hit, -1 clear), .rust.f64 (count x 4: column, row, z, t of the DDA; -1 clear), .grazing.u8 and <slug>.vcol.
A wall is a segment of 6 to 60 m, not steep, not grazing, that the exact tracer and the DDA both block. An opening is the
same kind of segment that both let through and that passes at least 3 samples (0.25 m apart) with a voxel 0.75 m to the
left and to the right of it: a doorway or window jamb, not open ground.
"""
import json
import sys
import numpy as np
import codec, columns

slug = sys.argv[1]
parity = sys.argv[2] if len(sys.argv) > 2 else "/par"
par = f"{parity}/{slug}"
seg = np.fromfile(par + ".segments.f64", np.float64).reshape(-1, 6)
exact = np.fromfile(par + ".exact.f64", np.float64)
rust = np.fromfile(par + ".rust.f64", np.float64).reshape(-1, 4)
graz = np.fromfile(par + ".grazing.u8", np.uint8)
keys, h = codec.decode(open(par + ".vcol", "rb").read())
occ = set(keys.tolist())
print("exact sample", exact[:6], "rust sample", rust[:3], "graz", graz[:6], file=sys.stderr)
cell, dz, z0, w = h["cell"], h["dz"], h["z_min"], h["width"]
def occupied(x, y, z):
    c = int(np.floor((x - h["min_x"]) / cell)); r = int(np.floor((y - h["min_y"]) / cell)); zi = int(np.floor((z - z0) / dz))
    return ((r * w + c) << columns.Z_BITS | zi) in occ
length = np.linalg.norm(seg[:, 3:] - seg[:, :3], axis=1)
blocked_exact = exact >= 0
blocked_dda = rust[:, 3] >= 0 if rust[:, 3].min() < 0 else None
print("rust t min", rust[:, 3].min(), file=sys.stderr)
out = {"wall": [], "opening": []}
cand = np.flatnonzero((graz == 0) & (length >= 6) & (length <= 60))
rng = np.random.default_rng(3)
rng.shuffle(cand)
for i in cand:
    a, b = seg[i, :3], seg[i, 3:]
    dda_blocked = not np.isnan(rust[i, 3]) and rust[i, 3] >= 0 and rust[i, 0] >= 0
    if blocked_exact[i] and dda_blocked and abs(b[2] - a[2]) < 0.25 * length[i] and len(out["wall"]) < 6:
        out["wall"].append(seg[i].tolist())
    elif not blocked_exact[i] and not dda_blocked and len(out["opening"]) < 6:
        d = (b - a) / length[i]
        side = np.array([-d[1], d[0], 0.0]); n = np.linalg.norm(side)
        if n < 0.3 or abs(d[2]) > 0.25:  # mostly vertical or steep: skip
            continue
        side /= n
        jamb = 0
        for t in np.arange(0, length[i], 0.25):
            p = a + d * t
            if occupied(*(p + side * 0.75)) and occupied(*(p - side * 0.75)):
                jamb += 1
        if jamb >= 3:
            out["opening"].append(dict(segment=seg[i].tolist(), jamb=jamb))
    if len(out["wall"]) == 6 and len(out["opening"]) == 6:
        break
json.dump(out, sys.stdout)
