"""Markdown status table of the all-maps build: python status_table.py [maps dir] [build_all.log] [statics dir].

Reads <maps>/<slug>/vcol.json and world_tris*.json written by build_map.sh and the start/end/FAILED lines of
build_all.log; maps without a result are listed as queued, running or failed.
"""

import datetime
import json
import os
import re
import sys

home = os.path.expanduser("~")
maps_dir = sys.argv[1] if len(sys.argv) > 1 else f"{home}/data/volumetric/maps"
log_path = sys.argv[2] if len(sys.argv) > 2 else f"{home}/data/volumetric/build_all.log"
statics = sys.argv[3] if len(sys.argv) > 3 else f"{home}/data/squad-extract/statics"

started, ended, failed = {}, {}, set()
for stamp, event, slug in re.findall(r"(\S+) (start|end|FAILED) (\w+)", open(log_path).read()):
    when = datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")
    if event == "start":
        ended.pop(slug, None)
        failed.discard(slug)
        started[slug] = when
    elif event == "end":
        ended[slug] = when
    else:
        failed.add(slug)

print("| map | state | voxels (M) | file MB (gzip) | build min | collision triangles (M) |\n|---|---|---|---|---|---|")
total_mb = 0.0
for slug in sorted(d for d in os.listdir(statics) if os.path.isdir(os.path.join(statics, d))):
    result = f"{maps_dir}/{slug}/vcol.json"
    if os.path.exists(result):
        j = json.load(open(result))
        tris = sum(json.load(open(p))["triangles"] for p in (f"{maps_dir}/{slug}/world_tris.json", f"{maps_dir}/{slug}/world_tris_foliage.json") if os.path.exists(p))
        minutes = (ended[slug] - started[slug]).total_seconds() / 60 if slug in ended and slug in started else None
        total_mb += j["gzip_bytes"] / 1e6
        print(f"| {slug} | built | {j['voxels'] / 1e6:.1f} | {j['gzip_bytes'] / 1e6:.2f} | {'-' if minutes is None else f'{minutes:.0f}'} | {tris / 1e6:.1f} |")
    else:
        state = "failed" if slug in failed else "running" if slug in started and slug not in ended else "queued"
        print(f"| {slug} | {state} | - | - | - | - |")
print(f"\nBuilt files so far: {total_mb:.1f} MB.")
