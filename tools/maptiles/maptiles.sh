#!/bin/sh
# Detailed tactical map tiles for SquadCalc from the Squad game files (see README.md).
#
#   maptiles.sh setup                  build the extractor (with the features mode) and the Python image
#   maptiles.sh extract [map ...]      foliage, landscape splines and water actors of each map from the paks
#   maptiles.sh prep [map ...]         ground, cover, 0.25 m object raster, features into $WORK/prep/<map>
#   maptiles.sh render [map ...]       webp tiles into $DIST/maptiles/<map> (written in place, map by map)
#   maptiles.sh all [map ...]          extract, prep and render
#   maptiles.sh check [map ...]        alignment of the tiles with the heightmap and the upstream images
#
# Without maps every map of ../heightmaps/py/maps.py is processed.
# Environment (defaults in brackets):
#   SQUAD_DIR    Squad dedicated server install, read only [~/data/squad-server]
#   SQUADHEIGHT  unpacked SquadHeight release [~/data/squadheight-v1.3.0/x]
#   EXTRACT      tools/heightmaps extraction: landscapes/ and statics/ [~/data/squad-extract]
#   HEIGHTMAPS   built precise heightmaps (tools/heightmaps) [~/data/squad-heightmaps]
#   WORK         extractor build, features and prepared rasters [~/data/squad-maptiles]
#   DIST         served SquadCalc [~/apps/squadcalc/dist]
#   CUE4PARSE    CUE4Parse checkout with ../heightmaps/extractor/cue4parse.patch [$EXTRACT/cue4parse]
#   WORKERS      parallel processes [3]
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
HEIGHTMAPS_TOOL=$(cd "$HERE/../heightmaps" && pwd)
SQUAD_DIR=${SQUAD_DIR:-$HOME/data/squad-server}
SQUADHEIGHT=${SQUADHEIGHT:-$HOME/data/squadheight-v1.3.0/x}
EXTRACT=${EXTRACT:-$HOME/data/squad-extract}
HEIGHTMAPS=${HEIGHTMAPS:-$HOME/data/squad-heightmaps}
WORK=${WORK:-$HOME/data/squad-maptiles}
DIST=${DIST:-$HOME/apps/squadcalc/dist}
CUE4PARSE=${CUE4PARSE:-$EXTRACT/cue4parse}
WORKERS=${WORKERS:-3}
DOTNET_IMAGE=mcr.microsoft.com/dotnet/sdk:10.0
PY_IMAGE=squadcalc-maptiles-py
USER_FLAGS="--user $(id -u):$(id -g) -e HOME=/tmp -e DOTNET_CLI_HOME=/tmp"

maps() {
    if [ $# -gt 0 ]; then echo "$@"; return; fi
    python3 -I -c "import sys; sys.path.insert(0, '$HEIGHTMAPS_TOOL/py'); import maps; print(' '.join(maps.MAPS))"
}

python_tool() {
    # shellcheck disable=SC2086
    nice docker run --rm $USER_FLAGS --shm-size=1g -e PYTHONPATH=/py:/hmpy \
        -v "$HERE/py:/py:ro" -v "$HEIGHTMAPS_TOOL/py:/hmpy:ro" -v "$SQUADHEIGHT:/squadheight:ro" \
        -v "$EXTRACT:/extract:ro" -v "$HEIGHTMAPS:/heightmaps:ro" -v "$WORK/features:/features:ro" \
        -v "$WORK/prep:/prep" -v "$DIST/maptiles:/tiles" -w /py "$PY_IMAGE" python -W ignore "$@"
}

case "${1:-}" in
setup)
    if [ ! -d "$CUE4PARSE/.git" ]; then
        echo "CUE4Parse missing in $CUE4PARSE: run ../heightmaps/heightmaps.sh setup first" >&2
        exit 1
    fi
    mkdir -p "$WORK/bin" "$WORK/nuget"
    # shellcheck disable=SC2086
    docker run --rm $USER_FLAGS -e NUGET_PACKAGES=/work/nuget -v "$WORK:/work" -v "$CUE4PARSE:/cue4parse" \
        -v "$HEIGHTMAPS_TOOL/extractor:/src:ro" "$DOTNET_IMAGE" \
        sh -c 'cp -r /src /tmp/extractor && cd /tmp/extractor && dotnet build -c Release -o /work/bin -p:CUE4ParseDir=/cue4parse'
    docker build -q -t "$PY_IMAGE" "$HERE/py"
    ;;
extract)
    shift
    for slug in $(maps "$@"); do
        root=$(python3 -I -c "import sys; sys.path.insert(0, '$HEIGHTMAPS_TOOL/py'); import maps; print(maps.statics_root('$slug'))")
        rm -rf "${WORK:?}/features/$slug"
        # shellcheck disable=SC2086
        nice docker run --rm $USER_FLAGS -v "$WORK:/work" -v "$SQUAD_DIR/SquadGame/Content/Paks:/paks:ro" -w /work/bin \
            "$DOTNET_IMAGE" dotnet SquadExtract.dll /paks features "$root" "/work/features/$slug"
    done
    ;;
prep)
    shift
    mkdir -p "$WORK/prep" "$DIST/maptiles"
    for slug in $(maps "$@"); do python_tool prep.py "$slug" --workers "$WORKERS"; done
    ;;
render)
    shift
    mkdir -p "$WORK/prep" "$DIST/maptiles"
    for slug in $(maps "$@"); do python_tool render.py "$slug" --workers "$WORKERS"; done
    ;;
all)
    shift
    for slug in $(maps "$@"); do
        "$0" extract "$slug"
        "$0" prep "$slug"
        "$0" render "$slug"
    done
    ;;
check)
    shift
    mkdir -p "$WORK/check"
    # shellcheck disable=SC2086
    nice docker run --rm $USER_FLAGS -e PYTHONPATH=/py:/hmpy -v "$HERE/py:/py:ro" -v "$HEIGHTMAPS_TOOL/py:/hmpy:ro" \
        -v "$WORK/prep:/prep:ro" -v "$DIST/maptiles:/tiles:ro" -v "$DIST/heightmaps:/heightmaps:ro" -v "$WORK/check:/check" \
        -w /py "$PY_IMAGE" \
        python -W ignore check_alignment.py $(maps "$@")
    ;;
*)
    sed -n '2,23p' "$0"
    exit 2
    ;;
esac
