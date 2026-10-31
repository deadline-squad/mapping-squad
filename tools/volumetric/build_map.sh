#!/bin/sh
# Volumetric columns of one map from the game files already extracted by tools/heightmaps (statics, landscapes):
#   build_map.sh <slug> [cell m] [dz m]
# Needs: ~/data/squad-extract/{statics,landscapes}, a served heightmap meta.json per map (grid bounds),
# the extractor built by `volumetric.sh extractor` (foliage mode). Output: $OUT/<slug>/{<slug>.vcol,*.npz}.
# An existing statics.npz is reused. The multi-GB triangle files are deleted after the build; nothing under ~/apps or ~/data/squad-extract is written.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
slug=$1; cell=${2:-1.0}; dz=${3:-0.25}
OUT=${OUT:-$HOME/data/volumetric/maps}
HM=${HM:-$HOME/data/squad-heightmaps}
mkdir -p "$OUT/$slug"
py() { WORKTREE=${WORKTREE:-$(cd "$HERE/../.." && pwd)} "${PY_SH:-$HOME/data/volumetric/py.sh}" "$@"; }
root=$(python3 -I -c "import sys; sys.path.insert(0, '$HOME/agl/tools/heightmaps/py'); import maps; print(maps.statics_root('$slug'))")
if [ ! -d "$OUT/$slug/foliage" ]; then
    "${RUN_SH:-$HOME/data/volumetric/run.sh}" foliage "$root" "/out/maps/$slug/foliage" >/dev/null 2>&1 || true
fi
if [ ! -s "$OUT/$slug/statics.npz" ]; then
    py py/world_tris.py "/data/squad-extract/statics/$slug" "/data/volumetric/maps/$slug/tris.npz" > "$OUT/$slug/world_tris.json"
    py py/build_columns.py "/data/volumetric/maps/$slug/tris.npz" "/data/squad-heightmaps/$slug/meta.json" "/data/volumetric/maps/$slug/statics" "$cell" "$dz" visibility "$slug" > "$OUT/$slug/build_statics.log"
fi
sets="/data/volumetric/maps/$slug/statics.npz"
if [ -s "$OUT/$slug/foliage/instances.ndjson" ]; then
    py py/world_tris.py "/data/volumetric/maps/$slug/foliage" "/data/volumetric/maps/$slug/foliage_tris.npz" > "$OUT/$slug/world_tris_foliage.json"
    py py/build_columns.py "/data/volumetric/maps/$slug/foliage_tris.npz" "/data/squad-heightmaps/$slug/meta.json" "/data/volumetric/maps/$slug/foliage" "$cell" "$dz" visibility "$slug" > "$OUT/$slug/build_foliage.log"
    sets="$sets /data/volumetric/maps/$slug/foliage.npz"
fi
# shellcheck disable=SC2086
py py/merge_encode.py "/data/volumetric/maps/$slug/$slug.vcol" $sets > "$OUT/$slug/vcol.json"
rm -f "$OUT/$slug/tris.npz" "$OUT/$slug/foliage_tris.npz"
cat "$OUT/$slug/vcol.json"
