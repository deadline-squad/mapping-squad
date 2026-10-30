"""Generate SquadCalc's Squad Ballistics weapons from Squad Ballistics' weapons.json.

Every weapon aimed with the overlay (`aim` "overlay", not a mod) becomes a SquadCalc weapon
named DF_<name>, with `ballistics` set to its Squad Ballistics name:

* a weapon laid by holding a key (`hold_rate`, the AGS-17 variants) becomes a "deployables"
  weapon built like SquadCalc's "AGS-17": high arc with the hold time (`elevationRate`,
  `holdElevation`), low arc in direct fire, the AGS-17's VOG-17 grenade (`...VOG_17` in
  weapons.js, 40 s projectile lifespan) and its images. Any other hold-laid weapon stops the
  generator: SquadCalc has no grenade data for it;
* any other weapon becomes a "directFire" weapon (low arc only, no explosion).

The AGS-17 emplacement is skipped: SquadCalc's "AGS-17" is it.

    python3 gen_squadcalc_weapons.py <weapons.json> <entries.js> <names.json> [<SquadCalc weapons.js>]

entries.js goes at the end of WEAPONS in src/data/weapons.js (after the existing weapons: the
selected weapon is stored by index); names.json maps DF_<name> to the display name for
public/locales/*/weapons.json. With SquadCalc's src/data/weapons.js, only the weapons whose
Squad Ballistics name it does not have yet are written, in weapons.json order, so an update is
one run and one append. Prints the number of entries written. Check the result with compare.py.
"""
import json, math, re, sys

GRAVITY = 9.80  # m/s², the world gravity of the game files (SquadCalc's app.js, Squad Ballistics)
SKIP = {"AGS-17 · emplacement"}  # SquadCalc "AGS-17" already is this weapon
HOLD_LAID_FAMILY = "AGS-17"  # the only hold-laid weapon whose grenade SquadCalc has (VOG_17)

data = json.load(open(sys.argv[1])); data.pop("_comment")
existing = set()
if len(sys.argv) > 4:
    source = open(sys.argv[4], encoding="utf-8").read()
    existing = {json.loads(f'"{name}"') for name in re.findall(r'ballistics:\s*"((?:[^"\\]|\\.)*)"', source)}


def ident(key):
    return "DF_" + re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]", "_", key)).strip("_")


def num(x):
    return json.dumps(x)


def lob_min_distance(w):
    """Flat-ground range in metres, rounded, of a shot at the top of the hold (no key held): the
    shortest distance the hold can lob to, from launch_height above the ground."""
    v, g = w["velocity"], GRAVITY * w["gravity"]
    angle = math.radians(w["hold_elevation"][1])
    up, forward = v * math.sin(angle), v * math.cos(angle)
    flight = (up + math.sqrt(up * up + 2 * g * w.get("launch_height", 0))) / g
    return round(forward * flight)


def hold_laid_entry(key, w):
    """A "deployables" entry built like SquadCalc's "AGS-17"."""
    if not key.startswith(HOLD_LAID_FAMILY):
        sys.exit(f"{key}: hold-laid, but SquadCalc only has the grenade of the {HOLD_LAID_FAMILY}")
    lim = w.get("elevation_limits", [-90, 90])
    hold = w["hold_elevation"]
    lines = [
        "    {",
        f'        name: "{ident(key)}",',
        f"        ballistics: {json.dumps(key, ensure_ascii=False)},",
        "        deceleration: 0,",
        "        decelerationTime: 0,",
        f"        gravityScale: {num(w['gravity'])},",
        f"        minElevation: [{num(lim[0])}, {num(lim[1])}],",
        f"        holdElevation: [{num(hold[0])}, {num(hold[1])}],",
        f"        elevationRate: {num(w['hold_rate'])},",
        "        projectileLifespan: 40,",
        "        heatmap: false,",
        '        unit: "sec",',
        '        type: "deployables",',
        '        angleType: "high",',
        "        elevationPrecision: 2,",
    ]
    if w.get("launch_height"):
        lines.append(f"        heightOffset: {num(w['launch_height'])},")
    lines += [
        f'        image: "{HOLD_LAID_FAMILY}",',
        "        shells: [{",
        '            name: "default",',
        f"            minDistance: {lob_min_distance(w)},",
        f"            velocity: {num(w['velocity'])},",
        "            ...VOG_17,",
        "        }]",
        "    },",
    ]
    return lines


def direct_fire_entry(key, w):
    """A "directFire" entry: low arc only, no explosion."""
    lines = [
        "    {",
        f'        name: "{ident(key)}",',
        f"        ballistics: {json.dumps(key, ensure_ascii=False)},",
        "        deceleration: 0,",
        "        decelerationTime: 0,",
    ]
    if w.get("acceleration") and w.get("acceleration_time"):
        lines += [f"        acceleration: {num(w['acceleration'])},", f"        accelerationTime: {num(w['acceleration_time'])},"]
    lim = w.get("elevation_limits", [-90, 90])
    lines += [
        f"        gravityScale: {num(w['gravity'])},",
        f"        minElevation: [{num(lim[0])}, {num(lim[1])}],",
        '        unit: "deg",',
        '        type: "directFire",',
        '        angleType: "low",',
        "        elevationPrecision: 2,",
    ]
    if w.get("launch_height"):
        lines.append(f"        heightOffset: {num(w['launch_height'])},")
    if w.get("angle_offset"):
        lines.append(f"        angleOffset: {num(w['angle_offset'])},")
    lines += [
        '        image: "DirectFire",',
        "        heatmap: false,",
        "        shells: [{",
        '            name: "default",',
        f"            minDistance: {num(w.get('min_distance', 0))},",
        f"            velocity: {num(w['velocity'])},",
        "            ...NO_EXPLOSION,",
        "        }]",
        "    },",
    ]
    return lines


entries, names = [], {}
for key, w in data.items():
    arc = w.get("arc", "low")
    if w.get("aim", "elevation" if arc == "high" else "overlay") != "overlay" or key in SKIP or w.get("mod"):
        continue
    if key in existing:
        continue
    names[ident(key)] = key
    entries.append("\n".join(hold_laid_entry(key, w) if w.get("hold_rate") else direct_fire_entry(key, w)))
open(sys.argv[2], "w").write("\n".join(entries) + "\n" if entries else "")
json.dump(names, open(sys.argv[3], "w"), ensure_ascii=False, indent=4)
print(len(entries))
