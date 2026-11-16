# Weapon ballistics from the game files

Checks every weapon of Squad Ballistics (`weapons.json`) and the Deadline SquadCalc
(`src/data/weapons.js`) against the Squad dedicated server paks.

Model (see the `gamecheck.py` docstring): launch speed `WeaponConfig.MuzzleVelocity`, gravity
`ProjectileGravityScale`, speed cap `MaxSpeed` (applied from the first step, one per 1/49.87 s server frame), rocket motor
`ConstantAcceleration` for `ConstantAccelerationTimeout` T (it acts on ceil(T / dt) − 1 steps) along the projectile's rotation
(`bRotationFollowsVelocity`), lifespan `InitialLifeSpan`; values are merged along the Blueprint
inheritance chain (`resolve.py`). The model reproduces the long-verified mortar (110 m/s, ×1) and
UB-32 (300 m/s, −50 m/s² for 2 s, ×2), and the AGS-17 values (185 m/s, ×1.8) agree with 67 in-game
hold-time/distance measurements to 0.7 % in v²/g.

SquadCalc's own (artillery) weapons are also checked for what the map draws: spread
(`WeaponConfig.MOA`), the damage circles (the projectile's explosion, or its secondary explosion when
that one reaches further: base damage, inner and outer radius, falloff, height above the impact) and
the projectile lifespan. A projectile with a native parent class leaves the fields it does not override
at the C++ defaults, which are not in the paks; `NATIVE_EXPLOSION` in `gamecheck.py` holds them and
explains how they were inferred, and `diff.md` marks every value that depends on them.

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

## Provenance of every input

`provenance.py` compares every input of the firing solution of every weapon of both apps with the game classes
(velocity, gravity, motor, cap, rotation, drag, launch point, spread, lifespan, explosion, bore, zoom, limits, minimum
distance, scale offset, hold model) and writes the generated tables of `tools/volumetric/docs/data-provenance.md` (and `.ru.md`)
and `data-provenance.tsv`; `--check` fails when a weapon is missing from the documents, a table is stale or an app differs from
the game without a `KNOWN` entry. It reads `resolved.json`, the existing dump, Squad Ballistics' `weapons.json` and
`tests/data/game_weapons.json` and SquadCalc's `weapons.js` (through `tools/direct_fire/weapons_json.mjs`):

```sh
python3 provenance.py --resolved resolved.json --dump dump --sb <Squad-Ballistics> --sc <SquadCalc> --check ../volumetric/docs
python3 provenance.py --resolved resolved.json --dump dump --sb <Squad-Ballistics> --sc <SquadCalc> --write ../volumetric/docs
```

