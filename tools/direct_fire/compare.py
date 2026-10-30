"""Check that SquadCalc and Squad Ballistics give the same firing solutions.

Runs SquadCalc's real Weapon and SquadFiringSolution under Node (solve.mjs) and
Squad Ballistics' solve() on the same distances and heights, for every SquadCalc
weapon with a `ballistics` name. Direct-fire weapons are compared on the low arc
(elevation, angle over the line of sight shown for them, time of flight), the
AGS-17 (laid by holding S, aimed with the overlay) on both arcs and the hold time (a
SquadCalc direct-fire copy of such a weapon, as the AGS-17 "· no optic", only on the low arc); the
mortars and rockets keep their own SquadCalc data and are not compared (the mortar's
hold model in Squad Ballistics is its auto-lay, SquadCalc shows mils).

    python3 compare.py <Squad-Ballistics checkout> <SquadCalc checkout>

Exits with 1 on any difference above 1e-6 degree / second.
"""
import json, math, os, subprocess, sys
sys.path.insert(0, sys.argv[1])
from ballistics import load_weapons, solve
weapons = load_weapons(sys.argv[1] + "/weapons.json")
cases = [(d, h) for d in (15, 60, 150, 300, 450, 700, 1000, 1500, 2500) for h in (-40, 0, 25)]
here = os.path.dirname(os.path.abspath(__file__))
js = json.loads(subprocess.check_output(
    ["node", "--import", os.path.join(here, "register.mjs"), os.path.join(here, "solve.mjs"), os.path.abspath(sys.argv[2]), json.dumps(cases)]
))
worst = {}
checked = mismatch = 0
for row in js:
    w = weapons.get(row["name"])
    if w is None:
        continue  # a weapon Squad Ballistics no longer has (mods, machine guns, autocannons)
    # Laid by holding a key and compared on both arcs (AGS-17); mortars only use it for the auto-lay.
    # A SquadCalc direct-fire entry of such a weapon has no hold: it is compared as direct fire.
    laid_by_hold = w.has_hold and w.aim == "overlay" and row["type"] != "directFire"
    for arc in ("low", "high"):
        s = solve(w, row["distance"], row["height"], arc)
        sb = s.angle if s.reachable else math.nan
        sc = row[arc] if row[arc] is not None else math.nan
        if not laid_by_hold and (row["type"] != "directFire" or arc == "high"):
            continue  # elevation weapons keep SquadCalc's own data (heightOffset, deceleration model)
        checked += 1
        if math.isnan(sb) != math.isnan(sc) or (not math.isnan(sb) and abs(sb - sc) > 1e-6):
            mismatch += 1
            if mismatch <= 15:
                print("MISMATCH", row["name"], arc, row["distance"], row["height"], sb, sc)
        if arc == "low" and not math.isnan(sb):
            if abs(s.sight_angle - row["sight"]) > 1e-6:
                mismatch += 1
                print("SIGHT", row["name"], row["distance"], row["height"], s.sight_angle, row["sight"])
            sb_tof = s.time_of_flight
            if (row["type"] == "directFire" or w.g == 0) and abs(sb_tof - row["tofLow"]) > 1e-6:
                mismatch += 1
                print("TOF", row["name"], row["distance"], row["height"], sb_tof, row["tofLow"])
        if laid_by_hold and arc == "high" and not math.isnan(sb):
            if abs(s.hold_time - row["hold"]) > 1e-9:
                mismatch += 1
                print("HOLD", row["distance"], row["height"], s.hold_time, row["hold"])
    if row["type"] == "directFire" or laid_by_hold:
        sb_max = w.max_range() if w.g else 10000
        if not laid_by_hold and abs(sb_max - row["max"]) > 1e-3 * max(1, sb_max):
            worst[row["name"]] = (sb_max, row["max"])
print("weapons:", len({r['name'] for r in js}), "checked:", checked, "mismatches:", mismatch)
print("max range differences:", worst)
sys.exit(1 if mismatch or worst else 0)
