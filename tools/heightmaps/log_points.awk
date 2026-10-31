# Ground-truth candidates from a Squad dedicated server log: prints one anonymous line per point,
#   <MapFolder> <Kind> x y z        (world centimetres)
# Only a map folder, a fixed vocabulary of kinds and three numbers leave the log: no player name,
# ID or address is ever copied. Usage: awk -f log_points.awk SquadGame*.log > points.txt
#
# The map folder is the /Game/Maps/<folder>/ of the loaded world, or the map named by a plugin
# layer (SEC_26_<Map>_*, *BlackCoast*, <Map>_*). Kinds: the type of a placed map marker (BP_MapMarker_*), "Deployable:<name>" (deployable spawned at
# its placement), "SpawnPoint:<name>" (cached spawn location), "Explosion:<damage causer>" (explosion
# that hit no actor, grenade or mine detonating on the ground).
function folder(path,    parts, n, layer, tokens) {
    if (match(path, /\/Game\/Maps\/[^\/]+\//)) {
        return substr(path, RSTART + 11, RLENGTH - 12)
    }
    n = split(path, parts, "/")
    layer = parts[n]
    sub(/\..*/, "", layer)
    if (layer ~ /^SEC_[0-9]+_/) {
        split(layer, tokens, "_")
        return tokens[3]
    }
    if (layer ~ /BlackCoast/) return "BlackCoast"
    sub(/_.*/, "", layer)
    return layer
}
function number(text,    value) { value = text; sub(/,$/, "", value); return value }
{ sub(/\r$/, "") }
/LogWorld: Bringing World/ {
    if ($0 !~ /TransitionMap/ && match($0, /World [^ ]+/)) current = folder(substr($0, RSTART + 6, RLENGTH - 6))
    next
}
current == "" { next }
/placed a new map marker/ && match($0, /Type: [A-Za-z_0-9]+ ; Location: -?[0-9.]+, -?[0-9.]+, -?[0-9.]+/) {
    split(substr($0, RSTART + 6, RLENGTH - 6), f, /[ ;,:]+/)
    print current, f[1], f[3], f[4], f[5]
    next
}
/LogSquad: Deployable [A-Za-z_0-9]+ spawned for team/ && match($0, /location \{[^}]+\}/) {
    split($0, w, " ")
    split(substr($0, RSTART + 10, RLENGTH - 11), c, /, */)
    for (i in w) if (w[i] == "Deployable") name = w[i + 1]
    print current, "Deployable:" name, c[1], c[2], c[3]
    next
}
/Found a valid cached spawn location at V\(/ && match($0, /V\(X=-?[0-9.]+, Y=-?[0-9.]+, Z=-?[0-9.]+\)/) {
    split(substr($0, RSTART + 2, RLENGTH - 3), c, /, */)
    name = $0
    sub(/.* for /, "", name)
    sub(/_C_[0-9]+.*/, "", name)
    sub(/[0-9]+_[0-9]+$/, "", name)
    sub(/[0-9]+$/, "", name)
    print current, "SpawnPoint:" name, substr(c[1], 3), substr(c[2], 3), substr(c[3], 3)
    next
}
/ApplyExplosiveDamage\(\): HitActor=nullptr/ && match($0, /ExplosionLocation=V\(X=-?[0-9.]+, Y=-?[0-9.]+, Z=-?[0-9.]+\)/) {
    split(substr($0, RSTART + 20, RLENGTH - 21), c, /, */)
    causer = $0
    sub(/.*DamageCauser=/, "", causer)
    sub(/_C_[0-9]+.*/, "", causer)
    print current, "Explosion:" causer, substr(c[1], 3), substr(c[2], 3), substr(c[3], 3)
}
