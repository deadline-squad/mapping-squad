#!/bin/sh
# Detailed tactical map tiles for SquadCalc from the Squad game files (see README.md).
#
#   maptiles.sh setup                  build the extractor (with the features mode) and the Python image
#   maptiles.sh extract [map ...]      foliage, landscape splines and water actors of each map from the paks
#   maptiles.sh prep [map ...]         ground, cover, 0.25 m object raster, features into $WORK/prep/<map>
#   maptiles.sh scene [map ...]        objects and crowns from the client scene (maprender.sh scene) into $WORK/prep/<map>/top_*,
#                                      crowns*; the scene raster is drawn on the GPU (py/scene_raster_gpu.py, with $PYTHON on
#                                      the host) unless SCENE_RASTER=cpu; SCENE_ARGS="--report" names the largest differences
#                                      to the collision raster
#   maptiles.sh render [map ...]       webp tiles into $DIST/maptiles/<map> (written in place, map by map)
#   maptiles.sh all [map ...]          extract, prep, scene and render
#   maptiles.sh check [map ...]        alignment of the tiles with the Standard HD layer, the heightmap and the upstream images
#   maptiles.sh measure [map ...]      accuracy of the tiles against Standard HD and the served heightmap (py/measure_accuracy.py:
#                                      roads, water, crowns, heights, contours) into $WORK/check/<map>_<measure>.json
#   maptiles.sh palette                contrast of the map's classes under normal and colour-deficient vision (py/palette_contrast.py)
#   maptiles.sh outline [map ...]      building outlines of the tiles, the HD layer and OUTLINE_BEFORE against the game's own
#                                      Seed and Skirmish minimap textures (py/outline_accuracy.py) into
#                                      $WORK/check/<map>_outline_<pair>.json; needs the scene rasters (run after "scene")
#   maptiles.sh colour-fit [map ...]   style "colour" (the game's colours) of each map fitted to its upstream basemap
#   maptiles.sh colour-relief [map ...] relief strength and light direction of the style against the basemap (report)
#   maptiles.sh colour-render [map ...] webp tiles of the style into $DIST/maptiles/<map>-colour
#   maptiles.sh colour-distance map tilesdir [args]  mean colour distance of a tile folder to the basemap (zoom 4)
#   maptiles.sh relief-setup           Python image of the relief layer (numpy, scipy, Pillow, RVT, pmtiles)
#   maptiles.sh relief [map ...]       shaded relief PMTiles (MDOW hillshade + anisotropic SVF) into $WORK/relief/<map>.pmtiles;
#                                      RELIEF_ARGS adds options of py/relief.py (--tint, --extra-zoom N)
#   maptiles.sh layer-minimaps         the game's per-layer minimap textures (Seed, Skirmish; a layer's data asset overrides
#                                      its level's texture and corners) as webp into $DIST/maptiles/<texture>/0/0_0.webp and
#                                      $DIST/maptiles/layer-minimaps.json (keyed by layer, with the corners)
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
#   SCENES       client scenes of tools/maprender (maprender.sh scene) [~/data/squad-scene]
#   HEIGHTMAPS_SERVED  the served precise heightmaps of "check" [$DIST/heightmaps]
#   HD_TILES     the folder of the Standard HD layers <map>-hd of "check" and "outline" (tools/maprender) [$DIST/maptiles]
#   PAIRS        minimap texture pairs of squad-map-restoration: pairs_all.json and pairs/<tag>.npz [~/data/mapsr]
#   OUTLINE_BEFORE  a second Detailed tile root (<map>/ folders) that "outline" scores beside $DIST/maptiles [none]
#   MEMORY       memory limit of every container, no swap [3g]
#   PYTHON       host Python with numpy, scipy and moderngl, for the GPU scene raster [~/data/venv-torch/bin/python]
#   SCENE_RASTER gpu or cpu: where "scene" draws the scene raster [gpu]
#   CLIENT_DIR   Squad game client install (its paks hold the minimap textures) [~/data/squad-client]
#   BASEMAPS     upstream basemap images <map>.webp for the colour styles, fetched when missing [$WORK/basemaps]
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
BASEMAPS=${BASEMAPS:-$WORK/basemaps}
CLIENT_DIR=${CLIENT_DIR:-$HOME/data/squad-client}
SCENES=${SCENES:-$HOME/data/squad-scene}
MEMORY=${MEMORY:-3g}
PYTHON=${PYTHON:-$HOME/data/venv-torch/bin/python}
SCENE_RASTER=${SCENE_RASTER:-gpu}
PAIRS=${PAIRS:-$HOME/data/mapsr}
DOTNET_IMAGE=mcr.microsoft.com/dotnet/sdk:10.0
PY_IMAGE=squadcalc-maptiles-py
RELIEF_IMAGE=squadcalc-relief-py
USER_FLAGS="--user $(id -u):$(id -g) -e HOME=/tmp -e DOTNET_CLI_HOME=/tmp"

maps() {
    if [ $# -gt 0 ]; then echo "$@"; return; fi
    python3 -I -c "import sys; sys.path.insert(0, '$HEIGHTMAPS_TOOL/py'); import maps; print(' '.join(maps.MAPS))"
}

# buildid of the Squad client the scenes were extracted from
client_build() {
    sed -n 's/.*"buildid"[^"]*"\([0-9]*\)".*/\1/p' "$CLIENT_DIR/steamapps/appmanifest_393380.acf" | head -1
}

python_tool() {
    # shellcheck disable=SC2086
    nice docker run --rm $USER_FLAGS --memory="$MEMORY" --memory-swap="$MEMORY" --shm-size=1g -e PYTHONPATH=/py:/hmpy \
        -e CLIENT_BUILD="$(client_build)" -v "$HERE/py:/py:ro" -v "$HEIGHTMAPS_TOOL/py:/hmpy:ro" -v "$SQUADHEIGHT:/squadheight:ro" \
        -v "$EXTRACT:/extract:ro" -v "$HEIGHTMAPS:/heightmaps:ro" -v "$WORK/features:/features:ro" -v "$SCENES:/scene:ro" \
        -v "$WORK/prep:/prep" -v "$DIST/maptiles:/tiles" -w /py "$PY_IMAGE" python -W ignore "$@"
}

# Tools of the colour styles: the styles directory is written, the basemaps are read
colour_tool() {
    # shellcheck disable=SC2086
    nice docker run --rm $USER_FLAGS --memory="$MEMORY" --memory-swap="$MEMORY" --shm-size=1g -e PYTHONPATH=/py:/hmpy -e CLIENT_BUILD="$(client_build)" \
        -v "$HERE/py:/py" -v "$HEIGHTMAPS_TOOL/py:/hmpy:ro" -v "$EXTRACT:/extract:ro" -v "$HEIGHTMAPS:/heightmaps:ro" \
        -v "$WORK/features:/features:ro" -v "$WORK/prep:/prep" -v "$BASEMAPS:/basemaps:ro" -v "$DIST/maptiles:/tiles" \
        -w /py "$PY_IMAGE" python -W ignore "$@"
}

fetch_basemap() {
    mkdir -p "$BASEMAPS"
    [ -s "$BASEMAPS/$1.webp" ] || curl -fsS -o "$BASEMAPS/$1.webp" "https://squadcalc.app/api/img/maps/$1/basemap.webp"
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
scene)
    shift
    for slug in $(maps "$@"); do
        if [ "$SCENE_RASTER" = gpu ]; then
            PYTHONPATH="$HERE/py:$HEIGHTMAPS_TOOL/py" nice "$PYTHON" -W ignore "$HERE/py/scene_raster_gpu.py" "$slug" \
                --scene "$SCENES/$slug" --prep "$WORK/prep/$slug" --workers "$WORKERS"
            # shellcheck disable=SC2086
            python_tool scene_prep.py "$slug" --workers "$WORKERS" --rasterized ${SCENE_ARGS:-}
        else
            # shellcheck disable=SC2086
            python_tool scene_prep.py "$slug" --workers "$WORKERS" ${SCENE_ARGS:-}
        fi
    done
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
        "$0" scene "$slug"
        "$0" render "$slug"
    done
    ;;
outline)
    shift
    mkdir -p "$WORK/check"
    for slug in $(maps "$@"); do
        # the layers of pairs_all.json with a pair file (a pair file alone has no corners to place it)
        tags=$(python3 -c "import json, sys; print(*(p['tag'] for p in json.load(open(sys.argv[1])) if p['tag'].startswith(sys.argv[2] + '_')))" \
            "$PAIRS/pairs_all.json" "$slug")
        for tag in $tags; do
            [ -e "$PAIRS/pairs/$tag.npz" ] || continue
            folders="/tiles/$slug"
            [ -e "${HD_TILES:-$DIST/maptiles}/$slug-hd/meta.json" ] && folders="$folders /hd/$slug-hd"
            [ -n "${OUTLINE_BEFORE:-}" ] && [ -e "$OUTLINE_BEFORE/$slug/meta.json" ] && folders="$folders /before/$slug"
            # shellcheck disable=SC2086
            nice docker run --rm $USER_FLAGS --memory="$MEMORY" --memory-swap="$MEMORY" -e PYTHONPATH=/py:/hmpy \
                -v "$HERE/py:/py:ro" -v "$HEIGHTMAPS_TOOL/py:/hmpy:ro" -v "$WORK/prep:/prep:ro" -v "$DIST/maptiles:/tiles:ro" \
                -v "${HD_TILES:-$DIST/maptiles}:/hd:ro" -v "${OUTLINE_BEFORE:-$DIST/maptiles}:/before:ro" -v "$PAIRS:/pairs:ro" \
                -w /py "$PY_IMAGE" python -W ignore outline_accuracy.py "$slug" /pairs/pairs_all.json "$tag" "/pairs/pairs/$tag.npz" \
                $folders > "$WORK/check/${slug}_outline_$tag.json"
        done
    done
    ;;
check)
    shift
    mkdir -p "$WORK/check"
    # shellcheck disable=SC2086
    nice docker run --rm $USER_FLAGS -e PYTHONPATH=/py:/hmpy -v "$HERE/py:/py:ro" -v "$HEIGHTMAPS_TOOL/py:/hmpy:ro" \
        -v "$WORK/prep:/prep:ro" -v "$DIST/maptiles:/tiles:ro" -v "${HEIGHTMAPS_SERVED:-$DIST/heightmaps}:/heightmaps:ro" -v "$WORK/check:/check" \
        -v "${HD_TILES:-$DIST/maptiles}:/hd:ro" \
        -w /py "$PY_IMAGE" \
        python -W ignore check_alignment.py $(maps "$@")
    ;;
measure)
    shift
    mkdir -p "$WORK/check"
    for measure in roads water crowns heights contours; do
        # shellcheck disable=SC2086
        nice docker run --rm $USER_FLAGS --memory="$MEMORY" --memory-swap="$MEMORY" -e PYTHONPATH=/py:/hmpy -v "$HERE/py:/py:ro" \
            -v "$HEIGHTMAPS_TOOL/py:/hmpy:ro" -v "$WORK/prep:/prep:ro" -v "$DIST/maptiles:/tiles:ro" \
            -v "${HEIGHTMAPS_SERVED:-$DIST/heightmaps}:/heightmaps:ro" -v "$WORK/check:/check" -v "${HD_TILES:-$DIST/maptiles}:/hd:ro" \
            -w /py "$PY_IMAGE" python -W ignore measure_accuracy.py "$measure" $(maps "$@")
    done
    ;;
palette)
    # shellcheck disable=SC2086
    docker run --rm $USER_FLAGS -e PYTHONPATH=/py:/hmpy -v "$HERE/py:/py:ro" -v "$HEIGHTMAPS_TOOL/py:/hmpy:ro" -w /py "$PY_IMAGE" \
        python -W ignore palette_contrast.py
    ;;
colour-fit)
    shift
    for slug in $(maps "$@"); do
        fetch_basemap "$slug"
        colour_tool fit_palette.py "$slug" --iterations 5 --workers "$WORKERS"
        colour_tool fit_fields.py "$slug" --workers "$WORKERS"
    done
    ;;
colour-relief)
    shift
    for slug in $(maps "$@"); do
        fetch_basemap "$slug"
        colour_tool fit_relief.py "$slug" --workers "$WORKERS"
    done
    ;;
colour-render)
    shift
    for slug in $(maps "$@"); do colour_tool render.py "$slug" --style colour --workers "$WORKERS"; done
    ;;
layer-minimaps)
    out="$WORK/layer-minimaps"
    rm -rf "${out:?}/layerdata" "${out:?}/tex"
    mkdir -p "$out" "$DIST/maptiles"
    extractor() {
        # shellcheck disable=SC2086
        nice docker run --rm $USER_FLAGS -v "$WORK:/work" -v "$CLIENT_DIR/SquadGame/Content/Paks:/paks:ro" -w /work/bin \
            "$DOTNET_IMAGE" dotnet SquadExtract.dll /paks "$@"
    }
    layer_minimaps() {
        # shellcheck disable=SC2086
        nice docker run --rm $USER_FLAGS -v "$HERE/py:/py:ro" -v "$out:/layer-minimaps" -v "$DIST/maptiles:/tiles" \
            -v "$CLIENT_DIR/steamapps:/steamapps:ro" -w /py "$PY_IMAGE" python -W ignore layer_minimaps.py "$@"
    }
    extractor layerminimaps 'Gameplay_Layers/' > "$out/layers.tsv"
    extractor dumpall '/Gameplay_Layer_Data/[^/]+\.uasset$' /work/layer-minimaps/layerdata
    textures=$(layer_minimaps textures /layer-minimaps/layers.tsv /layer-minimaps/layerdata)
    extractor texraw "$textures" /work/layer-minimaps/tex
    layer_minimaps build /layer-minimaps/layers.tsv /layer-minimaps/layerdata /layer-minimaps/tex \
        /steamapps/appmanifest_393380.acf /tiles
    ;;
relief-setup)
    docker build -q -t "$RELIEF_IMAGE" -f "$HERE/py/Dockerfile.relief" "$HERE/py"
    ;;
relief)
    shift
    mkdir -p "$WORK/relief"
    # shellcheck disable=SC2086
    nice -n 10 docker run --rm $USER_FLAGS -e PYTHONPATH=/py:/hmpy -v "$HERE/py:/py:ro" -v "$HEIGHTMAPS_TOOL/py:/hmpy:ro" \
        -v "$DIST/heightmaps:/heightmaps:ro" -v "$DIST/maptiles:/tiles:ro" -v "$WORK/relief:/out" -w /py "$RELIEF_IMAGE" \
        python -W ignore relief.py /heightmaps /tiles /out $(maps "$@") ${RELIEF_ARGS:-}
    ;;
colour-distance)
    shift
    slug=$1; folder=$2; shift 2
    fetch_basemap "$slug"
    colour_tool colour_distance.py "$slug" "/tiles/$folder" "$@"
    ;;
*)
    sed -n '2,/^set -eu$/{/^#/p;}' "$0"
    exit 2
    ;;
esac
