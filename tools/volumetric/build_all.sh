#!/bin/sh
# Sequentially build every map (smallest first), continuing after a failure: build_all.sh [cell] [dz] [slug ...]
HERE=$(cd "$(dirname "$0")" && pwd)
cell=${1:-0.5}; dz=${2:-0.25}; shift 2 2>/dev/null
STATICS=${STATICS:-$HOME/data/squad-extract/statics}
if [ $# -eq 0 ]; then set -- $(ls -S -r "$STATICS"/*/instances.ndjson | sed -E 's#.*/([^/]+)/instances.ndjson#\1#'); fi
for slug in "$@"; do
    echo "$(date -u +%FT%TZ) start $slug"
    "$HERE/build_map.sh" "$slug" "$cell" "$dz" || echo "$(date -u +%FT%TZ) FAILED $slug"
    echo "$(date -u +%FT%TZ) end $slug"
done
