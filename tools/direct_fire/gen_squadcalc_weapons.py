"""Generate SquadCalc's Squad Ballistics weapons from Squad Ballistics' weapons.json.

Every weapon aimed with the overlay (`aim` "overlay", not a mod) becomes a SquadCalc weapon
named DF_<name>, with `ballistics` set to its Squad Ballistics name:

* a weapon laid by holding a key (`hold_rate`, the AGS-17 variants) becomes a "deployables"
  weapon built like SquadCalc's "AGS-17": high arc with the hold time (`elevationRate`,
  `holdElevation`), low arc in direct fire, the AGS-17's VOG-17 grenade (`...VOG_17` in
  weapons.js, 40 s projectile lifespan) and its images. Any other hold-laid weapon stops the
  generator: SquadCalc has no grenade data for it;
* any other weapon becomes a "directFire" weapon (low arc only, no explosion) with the spread of its
  game weapon (`moa`, from GAME_MOA: a weapon missing there stops the generator).

The AGS-17 emplacement is skipped: SquadCalc's "AGS-17" is it.

A boosted rocket gets `acceleration`/`accelerationTime`, a projectile with a speed cap `maxSpeed`
(MaxSpeed of its movement component), and one whose motor keeps the barrel's axis
`rotationFollowsVelocity: false` (SquadCalc's squadBallistics.js flies them like Squad Ballistics).

    python3 gen_squadcalc_weapons.py <weapons.json> <entries.js> <names.json> [<SquadCalc weapons.js>]
    python3 gen_squadcalc_weapons.py <weapons.json> --update <SquadCalc weapons.js>

entries.js goes at the end of WEAPONS in src/data/weapons.js (after the existing weapons: the
selected weapon is stored by index); names.json maps DF_<name> to the display name for
public/locales/*/weapons.json. With SquadCalc's src/data/weapons.js, only the weapons whose
Squad Ballistics name it does not have yet are written, in weapons.json order, so an update is
one run and one append. Prints the number of entries written.

--update rewrites, in place and in their positions, the generated entries (DF_<name>) that
SquadCalc's weapons.js already has, from the current weapons.json (its line endings kept), and
prints how many changed; an entry whose weapon weapons.json no longer has is kept as it is and
named on stderr. Run it before the append. Check the result with compare.py.
"""
import json, math, re, sys

GRAVITY = 9.80  # m/s², the world gravity of the game files (SquadCalc's app.js, Squad Ballistics)
SKIP = {"AGS-17 · emplacement"}  # SquadCalc "AGS-17" already is this weapon
HOLD_LAID_FAMILY = "AGS-17"  # the only hold-laid weapon whose grenade SquadCalc has (VOG_17)

# Spread of the direct-fire weapons: the cone's full angle in MOA (WeaponConfig.MOA of the weapon the
# overlay view belongs to, Squad build 26005357; the first class of the view's list in Squad Ballistics'
# tools/game_weapons.py ENTRIES, merged views take that one's value: M203 30 (the GP-25's is 40), SPG-9 FRAG 3
# (the technical's is 1), Tank M256 / Rh120 1.5 (the Leopard's is 1.2).
# MOA is the full cone (half-angle MOA / 120 degrees, ConvertMOAToRadians 0xa4252c0).
# The grenade machine guns (MK19 tripod, open turrets and C16, QLZ87) set MOA 1.5 and the curve
# FC_MOACurve_GenericGMG over it: cubic from 15 MOA at 0 to 50 MOA at 0.75 of the weapon's dynamic MOA, a
# value that grows with each shot and decays between bursts. The curve's input rule is native code and no
# game file gives it, so they get 15, the MOA of the first, rested shot; a sustained burst spreads up to
# 50. The vehicle mounts that set a fixed MOA (M1117 and AAV-7 MK19, PARS III MK19: 50; AGS-30: 15) get
# it. The AGS-17 is not here: it keeps the 50 MOA of its grenade (VOG_17 in SquadCalc's weapons.js).
GAME_MOA = {
    "M203 / M320 / GP-25 / HK79 / SL40": 30,
    "MGL / M32": 30,
    "AK-40GL (MPT-76)": 30,
    "QLG10": 40,
    "Rifle grenade": 30,
    "MK19": 50,
    "MK19 · PARS III RWS": 50,
    "MK19 · TAPV C16 RWS": 15,
    "MK19 · M113 open turret": 15,
    "MK19 · M1151 / RHIB open turret": 15,
    "MK19 · emplacement / C16 / L134A1": 15,
    "MK19 · emplacement / C16 / L134A1 · no sights": 15,
    "QLZ87": 15,
    "QLZ87 · no optic": 15,
    "QLZ87 · Lynx / CSK131": 15,
    "QLZ87 · Lynx / CSK131 · no optic": 15,
    "AGS-30 / BTR-4 AGS": 15,
    "AGS-30 (BMP-1TS)": 15,
    "AGS-30 (BMP-2M)": 15,
    "M72A7 LAW / RPG-26": 15,
    "AT-4": 10,
    "MK153 SMAW": 7,
    "PF98 · Tandem": 7,
    "PF98 · HE-I": 7,
    "RPG-29": 10,
    "RPG-7 · PG-7V HEAT / OG-7V": 20,
    "RPG-7 · PG-7VR Tandem": 20,
    "RPG-7 · TBG-7V Thermobaric": 20,
    "RPG-7V1 · HEAT": 15,
    "M3 MAAWS · HEAT / Smoke": 7,
    "M3 MAAWS · Tandem": 7,
    "Carl Gustav M2 · FFV551 HEAT": 7,
    "Carl Gustav M2 · FFV441D HE": 7,
    "Carl Gustav M2 · FFV751 Tandem": 7,
    "NLAW": 1,
    "SPG-9 · HEAT": 3,
    "SPG-9 · HEAT · scope": 3,
    "SPG-9 · HEAT · scope · no optic": 3,
    "SPG-9 · FRAG": 3,
    "SPG-9 · FRAG · scope": 3,
    "SPG-9 · FRAG · scope · no optic": 3,
    "2A28 Grom (BMP-1 / BMD-1) · HEAT": 3,
    "2A28 Grom (BMD-1M) · HEAT": 3,
    "2A28 Grom (BMP-1 / BMD-1) · FRAG": 3,
    "2A28 Grom (BMD-1M) · FRAG": 3,
    "2A70 100mm (BMP-3 / BMD-4 / ZBD04A) · FRAG": 1.6,
    "2A70 100mm (ZBD-04A) · FRAG": 1.6,
    "2A70 100mm (BMD-4M) · FRAG": 1.6,
    "ZiS-3": 3,
    "ZiS-3 · no optic": 3,
    "Tank AP · 2A46 / ZPT98 / 2A20 / 2A45 / KBA3": 1.5,
    "Tank AP · T-62 (2A20)": 1.5,
    "Tank AP · T-64BM2 (KBA3)": 1.5,
    "Tank AP · ZTZ-99 (ZPT-98)": 1.5,
    "Tank AP · M256 / Rh120": 1.5,
    "Tank AP · Leopard 2A6 (Rh120)": 1.2,
    "Tank AP · M60T (MG253)": 1.5,
    "Tank AP · L30A1 (Challenger 2) / M68A2": 1.5,
    "Tank AP · M1128 MGS (M68A2)": 1.5,
    "Tank HEAT/HE · M256 / Rh120 / 2A46 / ZPT98 / 2A20 / M68A2": 1.5,
    "Tank HEAT/HE · M1A1 / M1A2 (M256)": 1.5,
    "Tank HEAT/HE · Leopard 2A6 (Rh120)": 1.2,
    "Tank HEAT/HE · M1128 MGS (M68A2)": 1.5,
    "Tank HEAT/HE · M60T (MG253)": 1.5,
    "Tank HEAT/HE · ZTZ-99 (ZPT-98)": 1.5,
    "Tank HEAT/HE · T-62 (2A20)": 1.5,
    "Tank HEAT/HE · T-64BM2 (KBA3)": 1.5,
    "Tank HESH · L30A1 (Challenger 2)": 1.5,
    "ZPL-98A 105mm (ZTD-05) · AP": 1.5,
    "ZPL-98A 105mm (ZTD-05) · HEAT / HE": 1.5,
}

data = json.load(open(sys.argv[1])); data.pop("_comment")
existing = set()
if len(sys.argv) > 4 and sys.argv[2] != "--update":
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
    """A "directFire" entry: low arc only, no explosion, the spread of the game weapon."""
    if key not in GAME_MOA:
        sys.exit(f"{key}: no MOA in GAME_MOA (WeaponConfig.MOA of its game weapon, see tools/game_weapons.py of Squad Ballistics)")
    lines = [
        "    {",
        f'        name: "{ident(key)}",',
        f"        ballistics: {json.dumps(key, ensure_ascii=False)},",
        "        deceleration: 0,",
        "        decelerationTime: 0,",
    ]
    if w.get("acceleration") and w.get("acceleration_time"):
        lines += [f"        acceleration: {num(w['acceleration'])},", f"        accelerationTime: {num(w['acceleration_time'])},"]
    if w.get("max_speed"):
        lines.append(f"        maxSpeed: {num(w['max_speed'])},")
    if w.get("rotation_follows_velocity") is False:
        lines.append("        rotationFollowsVelocity: false,")
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
        f"            moa: {num(GAME_MOA[key])},",
        "        }]",
        "    },",
    ]
    return lines


def entry(key, w):
    return hold_laid_entry(key, w) if w.get("hold_rate") else direct_fire_entry(key, w)


def update(path):
    """Rewrite the generated entries of SquadCalc's weapons.js at `path` in place."""
    raw = open(path, encoding="utf-8", newline="").read()
    newline = "\r\n" if "\r\n" in raw else "\n"
    source = raw.replace("\r\n", "\n")
    # A generated entry: from its "    {" line to the "    }," that closes it
    block = re.compile(r'^    \{\n        name: "DF_[^"]*",\n        ballistics: ("(?:[^"\\]|\\.)*"),\n.*?^    \},$', re.M | re.S)
    changed = 0

    def regenerate(match):
        nonlocal changed
        key = json.loads(match.group(1))
        if key not in data:
            # A weapon Squad Ballistics no longer has (autocannons): kept as it is
            print(f"kept, not in {sys.argv[1]}: {key}", file=sys.stderr)
            return match.group(0)
        text = "\n".join(entry(key, data[key]))
        changed += text != match.group(0)
        return text

    source = block.sub(regenerate, source)
    open(path, "w", encoding="utf-8", newline="").write(source.replace("\n", newline))
    print(changed)


if sys.argv[2] == "--update":
    update(sys.argv[3])
    sys.exit(0)

entries, names = [], {}
for key, w in data.items():
    arc = w.get("arc", "low")
    if w.get("aim", "elevation" if arc == "high" else "overlay") != "overlay" or key in SKIP or w.get("mod"):
        continue
    if key in existing:
        continue
    names[ident(key)] = key
    entries.append("\n".join(entry(key, w)))
open(sys.argv[2], "w").write("\n".join(entries) + "\n" if entries else "")
json.dump(names, open(sys.argv[3], "w"), ensure_ascii=False, indent=4)
print(len(entries))
