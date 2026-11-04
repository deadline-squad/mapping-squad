"""Put the volume layer of one map next to its served heightmap and announce it in the heightmap's meta.json.

    python publish_volume.py <slug> <vcol file> <terrain file> <served heightmaps dir>

Copies the files to <dir>/<slug>/volume.vcol and terrain.bin and adds a ``volume`` entry to <dir>/<slug>/meta.json:

    "volume": {"file": "volume.vcol", "bytes", "sha256", "cell", "dz", "z_min_m", "terrain": {"file": "terrain.bin", "bytes", "sha256"}}

SquadCalc (src/js/volumeWorker.js) reads the entry, fetches both files as <file>?v=<meta.generated> and keeps the
1 m heightmap when the entry is absent or a file cannot be used. ``generated`` is set (to the time of this run) when
meta.json has none, so that the files get a cache key. Nothing else in meta.json changes.
"""

import datetime
import gzip
import hashlib
import json
import os
import shutil
import struct
import sys

VCOL_HEADER = "<8s5f3I"


def describe(path):
    """{"file" (name only), "bytes", "sha256"} of a published file."""
    data = open(path, "rb").read()
    return {"file": os.path.basename(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    slug, vcol, terrain, served = sys.argv[1:5]
    target = os.path.join(served, slug)
    meta_path = os.path.join(target, "meta.json")
    meta = json.load(open(meta_path))
    raw = gzip.decompress(open(vcol, "rb").read())
    magic, _, _, cell, dz, z_min, _, _, columns = struct.unpack_from(VCOL_HEADER, raw, 0)
    if magic != b"VCOL1\0\0\0":
        raise SystemExit(f"{vcol}: not a VCOL1 file")
    shutil.copyfile(vcol, os.path.join(target, "volume.vcol"))
    shutil.copyfile(terrain, os.path.join(target, "terrain.bin"))
    meta["volume"] = {
        **describe(os.path.join(target, "volume.vcol")),
        "cell": round(cell, 4), "dz": round(dz, 4), "z_min_m": round(z_min, 4), "columns": columns,
        "terrain": describe(os.path.join(target, "terrain.bin")),
    }
    meta.setdefault("generated", datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    json.dump(meta, open(meta_path, "w"), indent=1)
    print(json.dumps(meta["volume"]))


if __name__ == "__main__":
    main()
