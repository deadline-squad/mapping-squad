#!/bin/sh
# Precise SquadCalc heightmaps from the Squad game files (see README.md).
#
#   heightmaps.sh setup               clone CUE4Parse at the pinned commit, build the extractor and the Python image
#   heightmaps.sh extract             landscape collision and static meshes of every map from the paks
#   heightmaps.sh build [map ...]     fuse them with SquadHeight into $OUT/<map>/{heightmap.png,meta.json}
#   heightmaps.sh deploy              copy $OUT into the served SquadCalc (backup first)
#   heightmaps.sh webp [map ...]      heightmap.webp and its meta.json for heightmaps already in $DIST/heightmaps, into $OUT_WEBP
#   heightmaps.sh deploy-webp         copy the WebP files of $OUT_WEBP next to the served PNGs (hard-linked backup first, the
#                                     PNGs stay, meta.json is not touched: nothing changes for a page yet)
#   heightmaps.sh switch-webp         then copy each map's meta.json of $OUT_WEBP: the page reads the WebP from now on
#
# Environment (defaults in brackets):
#   SQUAD_DIR    Squad dedicated server install, read only [~/data/squad-server]
#   SQUADHEIGHT  unpacked SquadHeight release: <Map>/heightmap.png + meta.json [~/data/squadheight-v1.3.0/x]
#   WORK         extractor build and extracted data [~/data/squad-extract]
#   OUT          built heightmaps [~/data/squad-heightmaps]
#   OUT_WEBP     WebP files of the served heightmaps [~/data/squad-heightmaps-webp]
#   DIST         served SquadCalc [~/apps/squadcalc/dist]
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SQUAD_DIR=${SQUAD_DIR:-$HOME/data/squad-server}
SQUADHEIGHT=${SQUADHEIGHT:-$HOME/data/squadheight-v1.3.0/x}
WORK=${WORK:-$HOME/data/squad-extract}
OUT=${OUT:-$HOME/data/squad-heightmaps}
OUT_WEBP=${OUT_WEBP:-$HOME/data/squad-heightmaps-webp}
DIST=${DIST:-$HOME/apps/squadcalc/dist}
CUE4PARSE_COMMIT=808a7d65aea71cf3d58e142692b4f14215b7c79a
DOTNET_IMAGE=mcr.microsoft.com/dotnet/sdk:10.0
PY_IMAGE=squadcalc-heightmaps-py
USER_FLAGS="--user $(id -u):$(id -g) -e HOME=/tmp -e DOTNET_CLI_HOME=/tmp"

game_build() {
    sed -n 's/.*"buildid"[[:space:]]*"\([0-9]*\)".*/\1/p' "$SQUAD_DIR/steamapps/appmanifest_403240.acf"
}

extractor() {
    # shellcheck disable=SC2086
    docker run --rm $USER_FLAGS -v "$WORK:/work" -v "$SQUAD_DIR/SquadGame/Content/Paks:/paks:ro" -w /work/bin \
        "$DOTNET_IMAGE" dotnet SquadExtract.dll /paks "$@"
}

python_tool() {
    # shellcheck disable=SC2086
    docker run --rm $USER_FLAGS -v "$HERE/py:/py:ro" -v "$SQUADHEIGHT:/squadheight:ro" -v "$WORK:/work" -v "$OUT:/out" -w /py \
        "$PY_IMAGE" python -W ignore "$@"
}

case "${1:-}" in
setup)
    mkdir -p "$WORK/nuget"
    if [ ! -d "$WORK/cue4parse/.git" ]; then
        git clone -q https://github.com/FabianFG/CUE4Parse.git "$WORK/cue4parse"
    fi
    git -C "$WORK/cue4parse" fetch -q origin "$CUE4PARSE_COMMIT"
    git -C "$WORK/cue4parse" checkout -q -f "$CUE4PARSE_COMMIT"
    git -C "$WORK/cue4parse" apply "$HERE/extractor/cue4parse.patch"
    rm -rf "$WORK/extractor" && cp -r "$HERE/extractor" "$WORK/extractor"
    # shellcheck disable=SC2086
    docker run --rm $USER_FLAGS -e NUGET_PACKAGES=/work/nuget -v "$WORK:/work" -w /work/extractor "$DOTNET_IMAGE" \
        dotnet build -c Release -o /work/bin -p:CUE4ParseDir=/work/cue4parse
    docker build -q -t "$PY_IMAGE" "$HERE/py"
    ;;
extract)
    mkdir -p "$WORK/landscapes" "$WORK/statics"
    extractor extractall /Maps/ /work/landscapes
    for root in $(python3 -I -c "import sys; sys.path.insert(0, '$HERE/py'); import maps; print('\n'.join(f'{k}={maps.statics_root(k)}' for k in maps.MAPS))"); do
        slug=${root%%=*}
        rm -rf "$WORK/statics/$slug"
        extractor statics "${root#*=}" "/work/statics/$slug"
    done
    ;;
build)
    shift
    mkdir -p "$OUT"
    python_tool build_all.py /squadheight /work /out "$(game_build)" "$@"
    ;;
deploy)
    backup="$DIST/heightmaps.bak.$(date +%Y%m%d-%H%M)"
    if [ -d "$DIST/heightmaps" ]; then cp -a "$DIST/heightmaps" "$backup" && echo "backup: $backup"; fi
    mkdir -p "$DIST/heightmaps"
    rsync -a --delete "$OUT/" "$DIST/heightmaps/"
    echo "deployed $(find "$DIST/heightmaps" -name meta.json | wc -l) heightmaps to $DIST/heightmaps"
    ;;
webp)
    shift
    mkdir -p "$OUT_WEBP"
    # shellcheck disable=SC2086
    docker run --rm $USER_FLAGS -v "$HERE/py:/py:ro" -v "$DIST/heightmaps:/in:ro" -v "$OUT_WEBP:/out" -w /py \
        "$PY_IMAGE" python -W ignore convert_webp.py /in /out "$@"
    ;;
deploy-webp)
    # cp -al: the backup shares the files, and a meta.json is replaced by a new file, never rewritten in place
    backup="$DIST/heightmaps.bak.$(date +%Y%m%d-%H%M)-webp"
    cp -al "$DIST/heightmaps" "$backup" && echo "backup: $backup"
    for dir in "$OUT_WEBP"/*/; do
        map=$(basename "$dir")
        cp "$dir/heightmap.webp" "$DIST/heightmaps/$map/heightmap.webp.new" && mv "$DIST/heightmaps/$map/heightmap.webp.new" "$DIST/heightmaps/$map/heightmap.webp"
    done
    echo "copied $(find "$OUT_WEBP" -name heightmap.webp | wc -l) heightmap.webp to $DIST/heightmaps"
    ;;
switch-webp)
    for dir in "$OUT_WEBP"/*/; do
        map=$(basename "$dir")
        cp "$dir/meta.json" "$DIST/heightmaps/$map/meta.json.new" && mv "$DIST/heightmaps/$map/meta.json.new" "$DIST/heightmaps/$map/meta.json"
    done
    echo "switched $(find "$OUT_WEBP" -name meta.json | wc -l) heightmaps to WebP in $DIST/heightmaps"
    ;;
*)
    sed -n '2,15p' "$0"
    exit 2
    ;;
esac
