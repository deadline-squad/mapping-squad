#!/bin/sh
# The calculator's data against the Squad game files (see README.md).
#
#   game_audit.sh extract-mounts      mount Blueprints, sight widgets and skeletons named by mounts.py, with bytecode
#   game_audit.sh extract-layer-data  the data asset of every layer, the FOB radius table, the protection zone Blueprint
#   game_audit.sh extract-landscapes  landscape collision of the levels named by tools/heightmaps/py/maps.py
#   game_audit.sh extract-layers      every gameplay layer, stripped and gzipped (219 layers, about 20 minutes)
#   game_audit.sh derive              data/*.json from what the four steps above extracted
#   game_audit.sh check               SquadCalc's maps.js and weapons.js against data/*.json (exit 1 on a difference)
#   game_audit.sh api                 the layers of data/deadline_pool.txt in the upstream API against the game
#   game_audit.sh run <args>          SquadExtract <paks> <args>, with $WORK as /work
#
# Environment (defaults in brackets):
#   SQUAD_DIR        Squad dedicated server install, read only [~/data/squad-server]
#   WORK             extractor build (heightmaps.sh setup) and extracted data [~/data/squad-extract]
#   SQUADCALC        SquadCalc checkout [~/agl/SquadCalc]
#   API              the API the calculator reads layers from [https://squadcalc.app/api]
#   EXTRACTOR_FLAGS  extra docker run flags, for example "--memory=4g --cpus=2" on a shared host []
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
SQUAD_DIR=${SQUAD_DIR:-$HOME/data/squad-server}
WORK=${WORK:-$HOME/data/squad-extract}
SQUADCALC=${SQUADCALC:-$HOME/agl/SquadCalc}
API=${API:-https://squadcalc.app/api}
AUDIT=$WORK/audit
DATA=$HERE/data
HEIGHTMAPS=$HERE/../heightmaps/py
DOTNET_IMAGE=mcr.microsoft.com/dotnet/sdk:10.0

extractor() {
    # shellcheck disable=SC2086
    docker run --rm ${EXTRACTOR_FLAGS:-} --user "$(id -u):$(id -g)" -e HOME=/tmp -e DOTNET_CLI_HOME=/tmp \
        -v "$WORK:/work" -v "$SQUAD_DIR/SquadGame/Content/Paks:/paks:ro" -w /work/bin \
        "$DOTNET_IMAGE" dotnet SquadExtract.dll /paks "$@"
}

game_build() {
    sed -n 's/.*"buildid"[[:space:]]*"\([0-9]*\)".*/\1/p' "$SQUAD_DIR/steamapps/appmanifest_403240.acf"
}

# SquadCalc's data and its solver's ranges at the stops of the mounts, for check_calculator.py and api_layers.py
calculator_json() {
    node --import "$HERE/../direct_fire/register.mjs" "$HERE/calculator.mjs" "$SQUADCALC" "$DATA/mount_limits.json" > "$AUDIT/calculator.json"
}

case "${1:-}" in
extract-mounts | extract-layer-data | extract-landscapes | extract-layers | derive | check | api | run)
    mkdir -p "$AUDIT"
    ;;
*)
    sed -n '2,18p' "$0"
    exit 2
    ;;
esac

case "$1" in
extract-mounts)
    rm -rf "$AUDIT/blueprints"
    extractor dumpbytecode "$(python3 -I "$HERE/mounts.py" assets)" /work/audit/blueprints
    ;;
extract-layer-data)
    rm -rf "$AUDIT/layerdata"
    extractor dumpall '/Gameplay_Layer_Data/[^/]*\.uasset$|/Gameplay/FOBs/DT_FOBExclusionRadius\.uasset$|/Settings/Maps/BP_SQLayer\.uasset$|/Gameplay/GameplayBorder/Gameplay_TeamZone\.uasset$' /work/audit/layerdata
    ;;
extract-landscapes)
    for level in $(python3 -I -c "import sys; sys.path.insert(0, '$HEIGHTMAPS'); import maps; print('\n'.join(level for _, levels in maps.MAPS.values() for level in levels))"); do
        rm -rf "$WORK/landscapes/$level"
        extractor landscape "$level.umap" "/work/landscapes/$level"
    done
    ;;
extract-layers)
    extractor list Gameplay_Layers/ > "$AUDIT/files.txt"
    grep '\.umap$' "$AUDIT/files.txt" > "$AUDIT/layers.txt"
    rm -rf "$AUDIT/layers"
    # One map folder at a time: a dumped layer is about 55 MB of JSON
    for folder in $(sed 's|/Gameplay_Layers/[^/]*$||' "$AUDIT/layers.txt" | sort -u); do
        rm -rf "$AUDIT/layers-json"
        extractor dumpall "^$folder/Gameplay_Layers/[^/]*\\.umap\$" /work/audit/layers-json
        python3 -I "$HERE/layers.py" strip "$AUDIT/layers-json" "$AUDIT/layers"
    done
    rm -rf "$AUDIT/layers-json"
    ;;
derive)
    printf '{\n "squad_dedicated_server_build": "%s"\n}\n' "$(game_build)" > "$DATA/source.json"
    python3 -I "$HERE/mounts.py" read "$AUDIT/blueprints" "$DATA/mount_limits.json"
    python3 -I "$HERE/fob_radius.py" "$AUDIT/layerdata" "$DATA/fob_radius.json"
    python3 -I "$HERE/landscapes.py" "$WORK/landscapes" "$DATA/landscapes.json"
    python3 -I "$HERE/layers.py" reduce "$AUDIT/layers" "$AUDIT/game_layers.json"
    python3 -I "$HERE/layers.py" corners "$AUDIT/game_layers.json" "$AUDIT/corners.ndjson"
    python3 -I "$HEIGHTMAPS/minimap_corners.py" table "$AUDIT/corners.ndjson" "$DATA/minimap_corners.json"
    python3 -I "$HERE/layers.py" zones "$AUDIT/game_layers.json" \
        "$AUDIT/layerdata/SquadGame/Content/Gameplay/GameplayBorder/Gameplay_TeamZone.uasset.json" "$DATA/protection_zones.json"
    ;;
check)
    calculator_json
    python3 -I "$HERE/check_calculator.py" "$AUDIT/calculator.json" "$DATA"
    ;;
api)
    python3 -I "$HERE/api_layers.py" fetch "$API" "$DATA/deadline_pool.txt" "$AUDIT/api"
    calculator_json
    python3 -I "$HERE/api_layers.py" compare "$DATA/deadline_pool.txt" "$AUDIT/api" "$AUDIT/game_layers.json" "$AUDIT/layerdata" \
        "$AUDIT/calculator.json" "$AUDIT/api_compare.json"
    ;;
run)
    shift
    extractor "$@"
    ;;
esac
