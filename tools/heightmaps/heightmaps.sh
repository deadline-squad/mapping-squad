#!/bin/sh
# Precise SquadCalc heightmaps from the Squad game files (see README.md).
#
#   heightmaps.sh setup               clone CUE4Parse at the pinned commit, build the extractor and the Python image
#   heightmaps.sh extract             landscape collision and static meshes of every map from the paks
#   heightmaps.sh build [map ...]     fuse them with SquadHeight into $OUT/<map>/{heightmap.png,heightmap.webp,meta.json}; the
#                                     client scenes ($SCENES, "maprender.sh scene" of tools/maprender) say which of
#                                     SquadHeight's objects the game has; then heightmap.detail.bin, the finer grid where
#                                     objects stand, where it fits (build_detail.py)
#   heightmaps.sh deploy              replace those files of each map of $OUT in the served SquadCalc (backup first); the
#                                     map's other files and meta.json keys (the volume layer of tools/volumetric) stay
#   heightmaps.sh webp [map ...]      heightmap.webp and its meta.json for heightmaps already in $DIST/heightmaps, into $OUT_WEBP
#   heightmaps.sh deploy-webp         copy the WebP files of $OUT_WEBP next to the served PNGs (hard-linked backup first, the
#                                     PNGs stay, meta.json is not touched: nothing changes for a page yet)
#   heightmaps.sh switch-webp         then copy each map's meta.json of $OUT_WEBP: the page reads the WebP from now on
#
# Environment (defaults in brackets):
#   SQUAD_DIR    Squad dedicated server install, read only [~/data/squad-server]
#   SQUADHEIGHT  unpacked SquadHeight release: <Map>/heightmap.png + meta.json [~/data/squadheight-v1.3.0/x]
#   WORK         extractor build and extracted data [~/data/squad-extract]
#   SCENES       client scenes of tools/maprender, read only [~/data/squad-scene]
#   CLIENT_DIR   Squad game client install the scenes were extracted from (its build id goes into meta.json) [~/data/squad-client]
#   OUT          built heightmaps [~/data/squad-heightmaps]
#   OUT_WEBP     WebP files of the served heightmaps [~/data/squad-heightmaps-webp]
#   DIST         served SquadCalc [~/apps/squadcalc/dist]
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SQUAD_DIR=${SQUAD_DIR:-$HOME/data/squad-server}
SQUADHEIGHT=${SQUADHEIGHT:-$HOME/data/squadheight-v1.3.0/x}
WORK=${WORK:-$HOME/data/squad-extract}
SCENES=${SCENES:-$HOME/data/squad-scene}
CLIENT_DIR=${CLIENT_DIR:-$HOME/data/squad-client}
OUT=${OUT:-$HOME/data/squad-heightmaps}
OUT_WEBP=${OUT_WEBP:-$HOME/data/squad-heightmaps-webp}
DIST=${DIST:-$HOME/apps/squadcalc/dist}
CUE4PARSE_COMMIT=808a7d65aea71cf3d58e142692b4f14215b7c79a
DOTNET_IMAGE=mcr.microsoft.com/dotnet/sdk:10.0
PY_IMAGE=squadcalc-heightmaps-py
# The heightmaps "build" writes into $OUT/<map>, next to its meta.json
HEIGHTMAP_FILES="heightmap.png heightmap.webp"
USER_FLAGS="--user $(id -u):$(id -g) -e HOME=/tmp -e DOTNET_CLI_HOME=/tmp"

game_build() {
    sed -n 's/.*"buildid"[[:space:]]*"\([0-9]*\)".*/\1/p' "$SQUAD_DIR/steamapps/appmanifest_403240.acf"
}

client_build() {
    sed -n 's/.*"buildid"[^"]*"\([0-9]*\)".*/\1/p' "$CLIENT_DIR/steamapps/appmanifest_393380.acf" | head -1
}

extractor() {
    # shellcheck disable=SC2086
    docker run --rm $USER_FLAGS -v "$WORK:/work" -v "$SQUAD_DIR/SquadGame/Content/Paks:/paks:ro" -w /work/bin \
        "$DOTNET_IMAGE" dotnet SquadExtract.dll /paks "$@"
}

python_tool() {
    # shellcheck disable=SC2086
    docker run --rm $USER_FLAGS -e CLIENT_BUILD="$(client_build)" -v "$HERE/py:/py:ro" -v "$SQUADHEIGHT:/squadheight:ro" -v "$WORK:/work" \
        -v "$SCENES:/scene:ro" -v "$OUT:/out" -w /py "$PY_IMAGE" python -W ignore "$@"
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
    mkdir -p "$OUT" "$SCENES"
    python_tool build_all.py /squadheight /work /scene /out "$(game_build)" "$@"
    python_tool build_detail.py /squadheight /work /scene /out "$@"
    ;;
deploy)
    # Each map of $OUT replaces the files and the meta.json keys that "build" writes (heightmap.detail.bin and "detail" where the
    # build has them); the map's other files (volume.vcol and terrain.bin of tools/volumetric) and meta.json keys ("volume")
    # stay. A map of $OUT without all of its files stops the deploy before anything is touched.
    for dir in "$OUT"/*/; do
        for file in $HEIGHTMAP_FILES meta.json; do
            [ -f "$dir$file" ] || { echo "$dir$file is missing: build the map again" >&2; exit 1; }
        done
    done
    backup="$DIST/heightmaps.bak.$(date +%Y%m%d-%H%M)"
    if [ -d "$DIST/heightmaps" ]; then cp -a "$DIST/heightmaps" "$backup" && echo "backup: $backup"; fi
    for dir in "$OUT"/*/; do
        target="$DIST/heightmaps/$(basename "$dir")"
        mkdir -p "$target"
        # Written beside the served file and renamed over it, meta.json last as in deploy-webp and switch-webp: a page reads
        # whole files, and a page that reads the new meta.json (its new "generated" cache key) gets the new heightmaps
        for file in $HEIGHTMAP_FILES; do
            cp -p "$dir$file" "$target/$file.new" && mv "$target/$file.new" "$target/$file"
        done
        # The detail exists only where it fits (build_detail.py): a map built without one loses the served one and its key
        if [ -f "${dir}heightmap.detail.bin" ]; then
            cp -p "${dir}heightmap.detail.bin" "$target/heightmap.detail.bin.new" && mv "$target/heightmap.detail.bin.new" "$target/heightmap.detail.bin"
        fi
        python3 -c 'import json, os, sys
built, served = sys.argv[1:]
meta = json.load(open(served)) if os.path.exists(served) else {}
fresh = json.load(open(built))
meta.update(fresh)
if "detail" not in fresh:
    meta.pop("detail", None)
with open(served + ".new", "w") as out:
    json.dump(meta, out, indent=1)
os.replace(served + ".new", served)' "${dir}meta.json" "$target/meta.json"
        [ -f "${dir}heightmap.detail.bin" ] || rm -f "$target/heightmap.detail.bin"
    done
    echo "deployed $(find "$OUT" -mindepth 2 -maxdepth 2 -name meta.json | wc -l) heightmaps to $DIST/heightmaps"
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
    sed -n '2,/^set -eu$/{/^#/p;}' "$0"
    exit 2
    ;;
esac
