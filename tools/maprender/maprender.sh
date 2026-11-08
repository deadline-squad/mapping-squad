#!/bin/sh
# The "Standard HD" map of SquadCalc from the Squad client (see README.md).
#
#   maprender.sh build                 extractor with the scene mode
#   maprender.sh scene [map ...]       meshes, materials, textures, placements, landscape layers into $SCENES/<map>
#   maprender.sh render [map ...]      tiles into $DIST/<map>-hd (GPU)
#   maprender.sh all [map ...]         scene and render, map by map
#
# Without maps every map of ../heightmaps/py/maps.py is processed. A map whose tiles exist is skipped unless FORCE=1.
# Environment: CLIENT_DIR [~/data/squad-client], EXTRACT [~/data/squad-extract], SCENES [~/data/squad-scene], PREP [prepared rasters of
# tools/maptiles], DIST [served maptiles folder], PYTHON [~/data/venv-torch/bin/python], TABLE [layerminimaps.tsv],
# EXTRACT_MEMORY [11g, hard limit of the extractor container without swap: the host runs other services]
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
CLIENT_DIR=${CLIENT_DIR:-$HOME/data/squad-client}
EXTRACT=${EXTRACT:-$HOME/data/squad-extract}
SCENES=${SCENES:-$HOME/data/squad-scene}
DIST=${DIST:-$HOME/apps/squadcalc/dist/maptiles}
PYTHON=${PYTHON:-$HOME/data/venv-torch/bin/python}
TABLE=${TABLE:-$HOME/data/squad-client-extract/layerminimaps.tsv}
EXTRACT_MEMORY=${EXTRACT_MEMORY:-11g}
DOTNET_IMAGE=mcr.microsoft.com/dotnet/sdk:10.0
export SCENES DIST

sources() { "$PYTHON" -I "$HERE/map_sources.py" "$TABLE"; }
maps() { if [ $# -gt 0 ]; then echo "$@"; else sources | cut -d' ' -f1; fi; }

scene() {
    root=$(sources | awk -v m="$1" '$1 == m {print $2}')
    if [ -s "$SCENES/$1/textures.json" ] && [ "${FORCE:-0}" != 1 ]; then return; fi
    rm -rf "$SCENES/$1"; mkdir -p "$SCENES/$1"
    nice docker run --rm --memory="$EXTRACT_MEMORY" --memory-swap="$EXTRACT_MEMORY" --user "$(id -u):$(id -g)" -e HOME=/tmp -e DOTNET_CLI_HOME=/tmp -e DOTNET_GCConserveMemory=5 -e DOTNET_GCHeapHardLimitPercent=5A -v "$EXTRACT/texbin:/bin2:ro" \
        -v "$CLIENT_DIR/SquadGame/Content/Paks:/paks:ro" -v "$SCENES/$1:/out" -w /bin2 "$DOTNET_IMAGE" \
        dotnet SquadExtract.dll /paks scene "$root" /out > "$SCENES/$1.log" 2>&1 || { rm -rf "$SCENES/$1"; echo "$1: FAILED, see $SCENES/$1.log"; return 1; }
    tail -1 "$SCENES/$1.log"
}

render() {
    if [ -s "$DIST/$1-hd/meta.json" ] && [ "${FORCE:-0}" != 1 ]; then echo "$1: tiles exist"; return; fi
    texture=$(sources | awk -v m="$1" '$1 == m {print $3}')
    (cd "$HERE" && nice "$PYTHON" render_map.py "$1" "$texture")
}

command=${1:-}; shift || true
case "$command" in
build)
    mkdir -p "$EXTRACT/texsrc"; cp "$HERE/../heightmaps/extractor/Program.cs" "$HERE/../heightmaps/extractor/SquadExtract.csproj" "$EXTRACT/texsrc/"
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e DOTNET_CLI_HOME=/tmp -e NUGET_PACKAGES=/work/nuget -v "$EXTRACT:/work" -w /work/texsrc \
        "$DOTNET_IMAGE" dotnet build -c Release -o /work/texbin -p:CUE4ParseDir=/work/cue4parse
    ;;
scene) failed=""; for slug in $(maps "$@"); do scene "$slug" || failed="$failed $slug"; done; [ -z "$failed" ] || { echo "failed:$failed"; exit 1; } ;;
render) failed=""; for slug in $(maps "$@"); do render "$slug" || failed="$failed $slug"; done; [ -z "$failed" ] || { echo "failed:$failed"; exit 1; } ;;
all) failed=""; for slug in $(maps "$@"); do { scene "$slug" && render "$slug"; } || failed="$failed $slug"; done; [ -z "$failed" ] || { echo "failed:$failed"; exit 1; } ;;
*) sed -n 2,9p "$0"; exit 2 ;;
esac
