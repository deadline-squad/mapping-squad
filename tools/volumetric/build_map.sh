#!/bin/sh
# Volumetric columns of one map from the game files already extracted by tools/heightmaps (statics, landscapes):
#   build_map.sh <slug> [cell m] [dz m]
# Needs: ~/data/squad-extract/{statics,landscapes}, a served heightmap meta.json per map (grid bounds),
# the extractor built by `volumetric.sh extractor` (foliage mode). Output: $OUT/<slug>/{<slug>.vcol,*.npz}.
# An existing statics.npz is reused. The multi-GB triangle files are deleted after the build; nothing under ~/apps or ~/data/squad-extract is written.
# Foliage triangles are cut into shards of SHARD_TRIANGLES (default 40 M, about 1.5 GB) so that the largest maps fit PY_MEM;
# stderr of the extractor and of every python step goes to $OUT/<slug>/build.log (a step killed by the memory cap exits 137).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
slug=$1; cell=${2:-1.0}; dz=${3:-0.25}
OUT=${OUT:-$HOME/data/volumetric/maps}
HM=${HM:-$HOME/data/squad-heightmaps}
SHARD_TRIANGLES=${SHARD_TRIANGLES:-40000000}
mkdir -p "$OUT/$slug"
if [ -s "$OUT/$slug/$slug.vcol" ] && [ -z "${FORCE:-}" ]; then echo "$slug.vcol exists, skipping (FORCE=1 rebuilds)" >&2; exit 0; fi
exec 2>>"$OUT/$slug/build.log"
py() { WORKTREE=${WORKTREE:-$(cd "$HERE/../.." && pwd)} "${PY_SH:-$HOME/data/volumetric/py.sh}" "$@"; }
root=$(python3 -I -c "import sys; sys.path.insert(0, '$HOME/agl/tools/heightmaps/py'); import maps; print(maps.statics_root('$slug'))")
if [ ! -d "$OUT/$slug/foliage" ]; then
    "${RUN_SH:-$HOME/data/volumetric/run.sh}" foliage "$root" "/out/maps/$slug/foliage" >/dev/null || true
fi
if [ ! -s "$OUT/$slug/statics.npz" ]; then
    py py/world_tris.py "/data/squad-extract/statics/$slug" "/data/volumetric/maps/$slug/tris.npz" > "$OUT/$slug/world_tris.json"
    py py/build_columns.py "/data/volumetric/maps/$slug/tris.npz" "/data/squad-heightmaps/$slug/meta.json" "/data/volumetric/maps/$slug/statics" "$cell" "$dz" visibility "$slug" > "$OUT/$slug/build_statics.log"
fi
sets="/data/volumetric/maps/$slug/statics.npz"
if [ -s "$OUT/$slug/foliage/instances.ndjson" ]; then
    rm -f "$OUT/$slug"/foliage_tris.*.npz "$OUT/$slug"/foliage.*.npz
    : > "$OUT/$slug/build_foliage.log"
    py py/world_tris.py "/data/volumetric/maps/$slug/foliage" "/data/volumetric/maps/$slug/foliage_tris.npz" "$SHARD_TRIANGLES" > "$OUT/$slug/world_tris_foliage.json"
    for shard in "$OUT/$slug"/foliage_tris.*.npz; do
        index=${shard##*foliage_tris.}; index=${index%.npz}
        py py/build_columns.py "/data/volumetric/maps/$slug/foliage_tris.$index.npz" "/data/squad-heightmaps/$slug/meta.json" "/data/volumetric/maps/$slug/foliage.$index" "$cell" "$dz" visibility "$slug" >> "$OUT/$slug/build_foliage.log"
        sets="$sets /data/volumetric/maps/$slug/foliage.$index.npz"
        rm -f "$shard"
    done
fi
# shellcheck disable=SC2086
py py/merge_encode.py "/data/volumetric/maps/$slug/$slug.vcol" $sets > "$OUT/$slug/vcol.json"
rm -f "$OUT/$slug/tris.npz"
cat "$OUT/$slug/vcol.json"
