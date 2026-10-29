# Weapon ballistics from the game files

Checks every weapon of Squad Ballistics (`weapons.json`) and the Deadline SquadCalc
(`src/data/weapons.js`) against the Squad dedicated server paks.

Model (see the `gamecheck.py` docstring): launch speed `WeaponConfig.MuzzleVelocity`, gravity
`ProjectileGravityScale`, rocket boost `ConstantAcceleration` for `ConstantAccelerationTimeout`
stopped at `MaxSpeed`, lifespan `InitialLifeSpan`; values are merged along the Blueprint
inheritance chain (`resolve.py`). The model reproduces the long-verified mortar (110 m/s, ×1) and
UB-32 (300 m/s, −50 m/s² for 2 s, ×2), and the AGS-17 values (185 m/s, ×1.8) agree with 67 in-game
hold-time/distance measurements to 0.7 % in v²/g.

## Running

With the extractor of `tools/heightmaps` built (`heightmaps.sh setup`), where `extractor` runs
`dotnet SquadExtract.dll <paks> ...` in the .NET image like `heightmaps.sh` does:

```sh
extractor list "" > files.txt                                    # every path in the paks
extractor dumpall '/(Blueprints|Vehicles)/' dump                 # weapon and projectile Blueprints as JSON
python3 collect.py dump files.txt resolved.json                  # prints parent classes missing from the dump
python3 gamecheck.py resolved.json <Squad-Ballistics>/weapons.json squadcalc_weapons.json ballistics.json diff.md
```

`squadcalc_weapons.json` is SquadCalc's WEAPONS array as JSON. `diff.md` lists every value that
differs from the game; fix `weapons.json`, regenerate SquadCalc's direct-fire entries with
`tools/direct_fire/gen_squadcalc_weapons.py`, then check both apps agree with
`tools/direct_fire/compare.py`. A calculator weapon maps to its game classes in `TARGETS` in
`gamecheck.py`.
