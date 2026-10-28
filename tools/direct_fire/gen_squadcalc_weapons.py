"""Generate SquadCalc's direct-fire weapons from Squad Ballistics' weapons.json.

Every weapon aimed with the overlay (`aim` "overlay", not a mod) becomes a SquadCalc
weapon of type "directFire" named DF_<name>, with `ballistics` set to its Squad
Ballistics name. The AGS-17 emplacement is skipped: SquadCalc's "AGS-17" is it.

    python3 gen_squadcalc_weapons.py <weapons.json> <entries.js> <names.json>

entries.js goes at the end of WEAPONS in src/data/weapons.js (after the existing
weapons: the selected weapon is stored by index); names.json maps DF_<name> to the
display name for public/locales/*/weapons.json. Check the result with compare.py.
"""
import json, re, sys
data = json.load(open(sys.argv[1])); data.pop("_comment")
SKIP = {"AGS-17 · emplacement"}  # SquadCalc "AGS-17" already is this weapon
def ident(key):
    return "DF_" + re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]", "_", key)).strip("_")
def num(x):
    return json.dumps(x)
entries, names = [], {}
for key, w in data.items():
    arc = w.get("arc", "low")
    if w.get("aim", "elevation" if arc == "high" else "overlay") != "overlay" or key in SKIP or w.get("mod"):
        continue
    i = ident(key)
    names[i] = key
    lines = [
        "    {",
        f'        name: "{i}",',
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
    entries.append("\n".join(lines))
open(sys.argv[2], "w").write("\n".join(entries) + "\n")
json.dump(names, open(sys.argv[3], "w"), ensure_ascii=False, indent=4)
print(len(entries))
