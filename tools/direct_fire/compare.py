"""Check that SquadCalc and Squad Ballistics give the same firing solutions.

Runs SquadCalc's real Weapon and SquadFiringSolution under Node (solve.mjs) and
Squad Ballistics' solve() on the same distances and heights, for every SquadCalc
weapon with a `ballistics` name that Squad Ballistics has, every shell of it, and
again for every name of its `ballisticsViews` (the views of a weapon that share the
entry: Squad Ballistics' solution for the view against SquadCalc's for the entry):

* direct-fire weapons: the low arc (elevation, angle over the line of sight shown
  for them, time of flight);
* the AGS-17 entries (laid by holding S, aimed with the overlay: "AGS-17" and the
  generated hold-laid DF_AGS_17_* entries): both arcs and the hold time;
* the weapons aimed by elevation (mortars, UB-32, BM-21, Hell Cannon, the technical's
  mortar and UB-32, M1064): both arcs, the time of flight of both, the shell's velocity,
  the minimum distance (Squad Ballistics must refuse closer targets) and the elevation
  limits.

Every weapon is also checked on its maximum range. A projectile that the game destroys before it arrives
(`lifespan` of Squad Ballistics, `projectileLifespan` of SquadCalc, the game's InitialLifeSpan) is a shot both must refuse.

The grid (documented here, so that a regression in any corner shows up):

* distances (m): DISTANCES, 15 values from 0.5 m (closer than any minimum distance) to 8000 m
  (past every maximum range), with the M252's 51 m minimum and the M1064's 340 m one on the grid;
* heights of the target above the weapon's ground (m): HEIGHTS, 9 values from -300 to +200;
* near the maximum range: solve.mjs adds, for every weapon that has gravity, the fractions
  0.5, 0.9, 0.99, 0.999, 1.001 and 1.01 of SquadCalc's own getMaxDistance() at -40, 0 and
  +25 m.

A weapon Squad Ballistics aims with the overlay that SquadCalc has neither as an entry nor
as a view (`selectWeapon` would refuse its name) is reported as MISSING.

    python3 compare.py <Squad-Ballistics checkout> <SquadCalc checkout>

Prints a summary table and exits with 1 on any difference above 1e-6 degree / second or
any missing weapon.
"""
import json, math, os, subprocess, sys
sys.path.insert(0, sys.argv[1])
from ballistics import load_weapons, solve
weapons = load_weapons(sys.argv[1] + "/weapons.json")

DISTANCES = (0.5, 5, 15, 51, 150, 340, 450, 700, 1000, 1236, 1500, 2060, 2500, 5000, 8000)
HEIGHTS = (-300, -100, -40, -10, 0, 10, 25, 100, 200)
TOLERANCE = 1e-6

cases = [(d, h) for d in DISTANCES for h in HEIGHTS]
here = os.path.dirname(os.path.abspath(__file__))
js = json.loads(subprocess.check_output(
    ["node", "--import", os.path.join(here, "register.mjs"), os.path.join(here, "solve.mjs"), os.path.abspath(sys.argv[2]), json.dumps(cases)]
))
worst = {}
checked = mismatch = 0
per_weapon = {}


def report(*fields):
    """Print a mismatch (the first 15 in full) and count it."""
    global mismatch
    mismatch += 1
    if mismatch <= 15:
        print("MISMATCH", *fields)


def differ(a, b):
    """Whether two numbers (NaN = unreachable) differ by more than TOLERANCE."""
    return math.isnan(a) != math.isnan(b) or (not math.isnan(a) and abs(a - b) > TOLERANCE)


seen = set()


def compare(row, name):
    """Check SquadCalc's solution `row` (one case of one shell of an entry) against Squad Ballistics' weapon
    `name`: the entry's own name or one of its views."""
    global checked
    w = weapons.get(name)
    if w is None:
        return  # a weapon Squad Ballistics no longer has (mods, machine guns, autocannons)
    # Laid by holding a key and compared on both arcs (AGS-17); mortars only use it for the auto-lay
    laid_by_hold = w.has_hold and w.aim == "overlay"
    direct = row["type"] == "directFire"
    elevation = not direct and not laid_by_hold
    stats = per_weapon.setdefault(name, [0, 0])
    before = mismatch

    key = (name, row["shell"])
    if elevation and key not in seen:
        seen.add(key)
        if abs(w.velocity - row["velocity"]) > 1e-9:
            report("VELOCITY", name, row["shell"], w.velocity, row["velocity"])
        if abs(w.min_distance - row["minDistance"]) > 1e-9:
            report("MIN DISTANCE", name, row["shell"], w.min_distance, row["minDistance"])
        if any(abs(a - b) > 1e-9 for a, b in zip(w.elevation_limits, row["minElevation"])):
            report("ELEVATION LIMITS", name, w.elevation_limits, row["minElevation"])

    for arc in ("low", "high"):
        if direct and arc == "high":
            continue  # a direct-fire weapon is aimed on its low arc only
        s = solve(w, row["distance"], row["height"], arc)
        if elevation and row["distance"] < w.min_distance:
            # SquadCalc draws the minimum-distance circle instead; Squad Ballistics must refuse the shot
            checked += 1
            stats[0] += 1
            if s.reachable or s.reason_code != "too_close":
                report("TOO CLOSE", name, arc, row["distance"], row["height"], s.reachable, s.reason_code)
            continue
        sb = s.angle if s.reachable else math.nan
        sc = row[arc] if row[arc] is not None else math.nan
        checked += 1
        stats[0] += 1
        if differ(sb, sc):
            report(name, row["shell"], arc, row["distance"], row["height"], sb, sc)
        if not s.reachable or math.isnan(sc):
            continue
        if arc == "low" and not elevation:
            if abs(s.sight_angle - row["sight"]) > TOLERANCE:
                report("SIGHT", name, row["distance"], row["height"], s.sight_angle, row["sight"])
            if (direct or w.g == 0) and abs(s.time_of_flight - row["tofLow"]) > TOLERANCE:
                report("TOF", name, row["distance"], row["height"], s.time_of_flight, row["tofLow"])
        if elevation:
            tof = row["tofLow" if arc == "low" else "tofHigh"]
            if tof is None or abs(s.time_of_flight - tof) > TOLERANCE:
                report("TOF", name, arc, row["distance"], row["height"], s.time_of_flight, tof)
        if laid_by_hold and arc == "high" and abs(s.hold_time - row["hold"]) > 1e-9:
            report("HOLD", name, row["distance"], row["height"], s.hold_time, row["hold"])
    stats[1] += mismatch - before

    if direct or laid_by_hold or elevation:
        sb_max = w.max_range() if w.g else 10000
        if not laid_by_hold and abs(sb_max - row["max"]) > 1e-3 * max(1, sb_max):
            worst[name] = (sb_max, row["max"])


known = set()
for row in js:
    for name in (row["name"], *row["views"]):
        known.add(name)
        compare(row, name)
missing = [name for name, w in weapons.items() if w.aim == "overlay" and name not in known]

print(f"{'weapon':<45}{'checks':>8}{'mismatches':>12}")
for name, (count, bad) in sorted(per_weapon.items()):
    print(f"{name:<45}{count:>8}{bad:>12}")
for name in missing:
    print("MISSING", name)
print("weapons:", len(per_weapon), "checked:", checked, "mismatches:", mismatch, "missing:", len(missing))
print("max range differences:", worst)
sys.exit(1 if mismatch or worst or missing else 0)
