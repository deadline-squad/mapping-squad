# The calculator's map and weapon data against the game files

Reads from the Squad dedicated server paks what the Deadline SquadCalc keeps by hand in `src/data/maps.js` and
`src/data/weapons.js`, and compares the two. The report of the audit made with it is `docs/game-data-audit.md`;
the flight values of the weapons (velocity, gravity, motor, spread, explosion) are the business of
`tools/game_ballistics`.

| Read from the game | Tool | Data file (`data/`) | Checked in the calculator |
|---|---|---|---|
| Pitch range of the mount of each artillery weapon (`RotationConstraints.PitchInterval`, along the Blueprint chain) and what its sight adds: a constant in the widget's bytecode, the rest pitch of the muzzle's bone, the pitch of the muzzle or of the sight camera | `mounts.py`, `kismet.py` | `mount_limits.json` | `minElevation`; the minimum distance = the range at the mount's stop; the range circles of the mortar and hell cannon markers |
| Landscape of each map: first vertex, size in vertices, scale | `landscapes.py` | `landscapes.json` | `SDK_data.heightmap` |
| Minimap corners of each map (`tools/heightmaps/py/minimap_corners.py` on the layers dumped here) | `layers.py corners` | `minimap_corners.json` | `SDK_data.minimap` |
| FOB exclusion radius of each layer (`FOBRadius` of its data asset, rows of `DT_FOBExclusionRadius`) | `fob_radius.py` | `fob_radius.json` | `radiusExclusion`, `SMALL_FOB_LAYERS` |
| Protection zones of each layer: sphere, scale, radius in the world, lock distance | `layers.py zones` | `protection_zones.json` | through the API comparison below |
| Capture zones, mains, protection zones, factions and tickets of the layers of `data/deadline_pool.txt` | `layers.py reduce`, `api_layers.py` | not committed (`$WORK/audit/api_compare.json`) | the layer the calculator loads from `https://squadcalc.app/api` |

`data/source.json` names the game build the data files were read from. `data/deadline_pool.txt` is the layer
rotation of the Deadline server as the audit of 2026-11-10 was given it; replace it to compare other layers.

## Running

The extractor is the one of `tools/heightmaps` (`heightmaps.sh setup` builds it into `$WORK/bin`; it needs the mode
`dumpbytecode`, which reads the Kismet bytecode of the sight widgets). Everything extracted goes under `$WORK/audit`
and `$WORK/landscapes`; `game_audit.sh` without arguments lists the commands and the environment.

```sh
tools/game_audit/game_audit.sh extract-mounts       # 29 assets, seconds
tools/game_audit/game_audit.sh extract-layer-data   # 250 assets, seconds
tools/game_audit/game_audit.sh extract-landscapes   # 29 levels; skip it after heightmaps.sh extract, which wrote the same files
tools/game_audit/game_audit.sh extract-layers       # 219 layers, about 20 minutes, 8 MB kept
tools/game_audit/game_audit.sh derive               # rewrites data/*.json
tools/game_audit/game_audit.sh check                # SquadCalc against data/*.json, exit 1 on a difference
tools/game_audit/game_audit.sh api                  # 84 requests to the API at 0.6 s, then the comparison
```

`check` prints a `DIFFERS` line per difference and a `KNOWN` line for each one that is open and documented (`KNOWN`
in `check_calculator.py`, the open differences of `docs/game-data-audit.md`). It reads the calculator through
`calculator.mjs`, which also runs the calculator's own solver at the stops of the mounts.

Reading one thing by hand (`run` passes its arguments to the extractor, to dump an asset no reader names yet):

```sh
tools/game_audit/game_audit.sh run dumpbytecode '/Vehicles/BTR4/' /work/audit/look
python3 -I tools/game_audit/bpgrep.py PitchInterval "$WORK"/audit/blueprints/SquadGame/Content/Vehicles/*.json
python3 -I tools/game_audit/kismet.py "$WORK"/audit/blueprints/SquadGame/Content/UI/Widgets/Vehicles/Mortar/UMG_MortarControl.uasset.json Ubergraph
node --import ./tools/direct_fire/register.mjs tools/game_audit/btr4_ags.mjs <SquadCalc> <Squad-Ballistics>   # open difference O1
```

## After a game patch

1. Update the dedicated server (`steamcmd +app_update 403240`) and rerun the four `extract-*` commands and `derive`.
2. `git diff tools/game_audit/data` is what the patch changed in the game: a mount's pitch range, a sight's
   constant, a landscape, a layer's FOB radius or protection zone, a minimap corner, the build number. No diff
   apart from `source.json` means the calculator's data stands.
3. `game_audit.sh check` names every value of the calculator that no longer equals the game's; fix `maps.js` or
   `weapons.js` there, and Squad Ballistics' `weapons.json` for a limit or a minimum distance (the two apps are held
   together by `tools/direct_fire/compare.py`).
4. `game_audit.sh api` shows whether the upstream API already serves the new layers.
5. A mount that moved to another Blueprint, or a widget whose function was rewritten, stops `derive` with the name of
   the asset or of the statement it misses: update `MOUNTS` in `mounts.py`, then `extract-mounts` again.
6. Then the weapon checks of `deploy/README.md` (`gamecheck.py`, `provenance.py --write` and `--check`, `compare.py`).

## Tests

```sh
python3 -m unittest discover -s tools/game_audit   # parsers and comparison rules on made-up dumps, no game data
node --test tools/game_audit/                      # the range on level ground against the closed form
```
