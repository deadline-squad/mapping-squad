"""Put precision regions of one map next to its served volume layer and announce them in the heightmap's meta.json.

    python publish_regions.py <slug> <served heightmaps dir> <region.rtri> [<region.rtri> ...]

Copies each ``RTRI1`` file (``build_region.py``) to <dir>/<slug>/regions/ and lists it in the ``volume.regions`` of
<dir>/<slug>/meta.json, which ``publish_volume.py`` wrote:

    "regions": [{"file": "regions/region_221_-229.rtri", "bytes", "sha256", "centre": [x, y], "radius", "margin"}]

``centre`` and ``radius`` (the square's half side, metres, in the frame of the volume file) are read from the file's
header. SquadCalc (src/js/squadVolume.js, positionHeatmap.pickRegion) uses the region that holds a target at least
50 m from the edge of its square for the reverse-position heatmap; the file is fetched as <file>?v=<generated> and
checked against its sha256. meta.json is copied to meta.json.bak.<date>-regions before it is changed; a region already
listed (same file name) is replaced.
"""

import datetime
import gzip
import hashlib
import json
import os
import shutil
import struct
import sys

HEADER = "<8s5f3f2I"
MAGIC = b"RTRI1\0\0\0"


def describe(path):
    """The meta.json entry of a published region file."""
    blob = open(path, "rb").read()
    magic, min_x, min_y, max_x, max_y, margin, *_ = struct.unpack_from(HEADER, gzip.decompress(blob))
    if magic != MAGIC:
        raise SystemExit(f"{path}: not an RTRI1 file")
    if abs((max_x - min_x) - (max_y - min_y)) > 1e-3:
        raise SystemExit(f"{path}: the region is not a square")
    return {
        "file": f"regions/{os.path.basename(path)}", "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
        "centre": [round((min_x + max_x) / 2, 3), round((min_y + max_y) / 2, 3)],
        "radius": round((max_x - min_x) / 2, 3), "margin": round(margin, 3),
    }


def main():
    slug, served, *paths = sys.argv[1:]
    if not paths:
        raise SystemExit(__doc__)
    target = os.path.join(served, slug)
    meta_path = os.path.join(target, "meta.json")
    meta = json.load(open(meta_path))
    if "volume" not in meta:
        raise SystemExit(f"{meta_path}: no volume entry; run publish_volume.py first")
    shutil.copyfile(meta_path, f"{meta_path}.bak.{datetime.date.today():%Y%m%d}-regions")
    os.makedirs(os.path.join(target, "regions"), exist_ok=True)
    entries = {entry["file"]: entry for entry in meta["volume"].get("regions", [])}
    for path in paths:
        shutil.copyfile(path, os.path.join(target, "regions", os.path.basename(path)))
        entry = describe(os.path.join(target, "regions", os.path.basename(path)))
        entries[entry["file"]] = entry
    meta["volume"]["regions"] = sorted(entries.values(), key=lambda entry: entry["file"])
    json.dump(meta, open(meta_path, "w"), indent=1)
    print(json.dumps(meta["volume"]["regions"]))


if __name__ == "__main__":
    main()
