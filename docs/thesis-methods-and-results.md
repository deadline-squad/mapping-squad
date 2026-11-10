# Methods and results: ballistic calculator, terrain and object model for Squad

Report for the thesis on computational ballistics. Russian version: [`thesis-methods-and-results.ru.md`](thesis-methods-and-results.ru.md).
Written 2026-11-04 from the evidence that exists in the repositories; nothing in it was measured in a running game.
Updated 2026-11-05: the voxel figures of sections 4, 7 and 8 were measured again with the exact conservative voxelisation
(`AGL` `e34e481`, memory fix `f116a2b`, issue #23) on the final `.vcol` files; the figures of the earlier sample-lattice builder are
kept as "old" next to them.
Final state 2026-11-05: the report was read again against SquadCalc `dev` 45.33.0, Squad Ballistics 1.6.1 and the agl `dev`
branch; sections 1.5, 2.3, 9.3 and 12 to 15 are new or rewritten, the PENDING tables are filled with the evidence that exists
(only the GPU timings stay PENDING, with the owner action, section 12.4), and every issue number, file path and commit named
in the report is checked by `tools/release/check_report_refs.py` (section 13).

## 0. How to read this report

Every number carries a source and one of four labels (the fourth, ASSUMED, is used where a number is not in the server files at all).

| Label | Meaning |
|---|---|
| **VERIFIED** | Produced by a committed tool or test from the game files (Squad dedicated server build 26005357, SteamCMD app 403240), and the repository records the command and the output. A dagger (†) means the author of this report re-ran it on 2026-11-04. |
| **INFERRED** | Follows from verified data by an argument that is stated next to it. |
| **UNVERIFIED** | Recorded in a commit message, an issue or a note without a reproducible output, or not measurable from the server files, or not measured. |
| **ASSUMED** | Not in the dedicated-server files at all and used because the model needs a number: Workshop mods, the bore and zoom of handheld weapons (they come from the client's animation), the native C++ explosion defaults, SquadCalc's default lifespan; the reason is stated next to it (`DP`). |

A row marked **PENDING** is a measurement that does not exist; it names the action that produces it. After the final pass one is
left: the GPU timings (section 12.4).

**Scope.** The report covers the 25 maps that the Squad dedicated server package can play and holds the files of: `LevelRotation.cfg`
names 25 levels, one of which has no level files in the package and is not covered, and Jensen's Range, which is not in the
rotation, is, so the 25 maps are the 24 playable levels of the inventory plus Jensen's Range (`H-README`, "Map inventory: what
the server package can play", VERIFIED). Terrain, objects and weapon data are all derived from the server package; no
community-made map data is a source of any figure.

### Source key (revisions the figures were read at)

| Key | What | Revision |
|---|---|---|
| `SC` | SquadCalc fork (`deadline-squad/deadline-squadcalc`), branch `dev` | `e18519025de3`, version 45.33.0 (first draft: `2f1ae898ed90`, 45.24.0) |
| `SB` | Squad Ballistics overlay app, branch `main` (identical to `dev` `5ffcec9`) | `f702127`, version 1.6.1 (first draft: `5f11d21c837b`, 1.6.0) |
| `AGL` | deployment and tools repository, branch `dev` | `fc0500c` (first draft: `7438c08dbb76`); this report, `tools/release/` and `tools/release/check_report_refs.py` are added on top |
| `#22` | `deadline-squad/deadline-squadcalc#22`, "Completion checklist", items A1-D5 | read 2026-11-04, comments up to 2026-11-05 22:36 UTC |
| `#20` | `deadline-squad/deadline-squadcalc#20`, voxel evaluation tables | comment of 2026-11-05 (6670455739) |
| `#26`, `#27` | `deadline-squad/deadline-squadcalc#26` (thin openings), `#27` (precision margin) | open, read 2026-11-05 |
| `CL` | `SC:CHANGELOG.md`, entries 45.25.0 to 45.33.0 | |
| `SBS` | `SB:docs/sight-scales.md` | audit of 2026-11-05 |
| `V-README` | `AGL:tools/volumetric/README.md` | |
| `H-README` | `AGL:tools/heightmaps/README.md` | |
| `E-README` | `SC:engine/README.md` | |
| `CS` | `AGL:tools/volumetric/docs/collision-semantics.md` | |
| `SDMG` | `AGL:tools/volumetric/docs/structure-damage.md` | |
| `NR` | `AGL:tools/volumetric/docs/native-rules.md` | merged into `dev` as `7438c08`, read at that revision |
| `DP` | `AGL:tools/volumetric/docs/data-provenance.md` and `data-provenance.tsv` | added on the branch `fix/provenance`; counts of 2026-11-05, SC 45.30.0, SB 1.6.1 |
| `GA` | `AGL:docs/game-data-audit.md`, the calculator's map and weapon tables against the game files; tool `AGL:tools/game_audit/README.md` | audit of 2026-11-10, SC 45.40.0, SB 1.7.2 |

Paths below are relative to the repository named in the key. The equipment: one workstation, 15 GB of RAM, no GPU measurements.

## 1. Ballistic model

### 1.1 Model

The projectile model is the game's own, read from the Linux server binary and the cooked Blueprints (`SB:ballistics.py`
module docstring; evidence in `deadline-squad/squad-ballistics#4`, UNVERIFIED here because the issue was not re-read).

| Element | Value | Source | Label |
|---|---|---|---|
| Air drag | none | `SB:ballistics.py` docstring | VERIFIED (code reading of `USQProjectileMovement`) |
| Gravity | `g = ProjectileGravityScale x 9.80 m/s^2` (`DefaultGravityZ` = -980 cm/s^2) | `SB:ballistics.py` `GRAVITY = 9.80`; commit `f22e343` | VERIFIED |
| Launch speed | `WeaponConfig.MuzzleVelocity`, along the barrel from the socket `Attach_Muzzle` | `SB:ballistics.py`, `AGL:tools/game_ballistics/README.md` | VERIFIED |
| Server step | 20 ms substeps (50 Hz `NetServerMaxTickRate`), velocity Verlet, speed cap `MaxSpeed` from the first substep | `SB:ballistics.py` docstring | VERIFIED (addresses in the docstring); the 50 Hz tick is INFERRED from the net driver setting |
| Rocket motor | constant `acceleration` for `acceleration_time` along the rotation, which follows the velocity (`bRotationFollowsVelocity`) | same | VERIFIED |

"Exact vacuum parabola" is exact for a coasting shell (mortar, grenade, a gun round below its speed cap). The report does
not claim it for all weapons: a motor along the barrel axis is two parabolas (closed form), a shell coasting at its speed
cap has a closed form for the path angle, and a motor that pushes along the path or a launch above the cap has none and
is flown with the game's 20 ms substeps (`SB:ballistics.py` docstring, VERIFIED).

### 1.2 Closed-form solver

For a target at horizontal distance `d` and height `h` above the barrel pivot, speed `v` and gravity `g`, the two
elevations are `theta = atan((v^2 -/+ sqrt(v^4 - g (g d^2 + 2 h v^2))) / (g d))` (low and high arc; `SB:README.md`,
section "How it works"). It is implemented twice, independently of the data: in JavaScript
(`SC:src/js/squadBallistics.js`, `squadFiringSolution.js`) and in Rust (`SC:engine`, `flight`, `weapon`), the latter as a
function-for-function port whose parity test runs the real JS classes (`E-README`, intro and "Building and testing").
The number of cases of the Rust parity test is not recorded in the documents: UNVERIFIED.

### 1.3 Parity of the two implementations

`AGL:tools/direct_fire/compare.py` runs SquadCalc's real `Weapon` and `SquadFiringSolution` under Node and Squad
Ballistics' `solve()` on the same grid (15 distances from 0.5 m to 8000 m x 9 target heights from -300 m to +200 m, plus
fractions 0.5-1.01 of each weapon's own maximum range at -40, 0 and +25 m) for every shell of every weapon both apps have,
low and high arc, time of flight, velocity, minimum distance and elevation limits. Tolerance 1e-6 degree / second.

| Quantity | Value | Source | Label |
|---|---|---|---|
| Weapons compared | 104 | `compare.py` output, SC `e18519025de3` + SB `f702127`, re-run 2026-11-05 | VERIFIED† |
| Cases compared | 20 178 | same (the same count at the first draft and in `CL` 45.31.0) | VERIFIED† |
| Mismatches | 0 | same; also recorded in SB commit `f22e343` | VERIFIED† |
| Max-range differences | none (`{}`) | same | VERIFIED† |

Command: `python3 tools/direct_fire/compare.py <Squad-Ballistics checkout> <SquadCalc checkout>` (7 s on one core on 2026-11-05). The run after the lifespan change (SC 45.31.0, SB 1.6.1) still has 0 mismatches, so the 4-40 s lifespans are the same in the two apps.
Scope: the two solvers agree with each other. Agreement with the real game is the next subsection.

### 1.4 Agreement with the game

| Check | Result | Source | Label |
|---|---|---|---|
| Weapon data (velocity, gravity scale, motor, cap) of every weapon of both apps against the cooked Blueprints | `diff.md` lists every difference; the long-verified mortar (110 m/s, x1) and UB-32 (300 m/s, -50 m/s^2 for 2 s, x2) are reproduced | `AGL:tools/game_ballistics/README.md`, `gamecheck.py` | VERIFIED (method); `diff.md` itself is not stored, but `DP` (`data-provenance.tsv`) stores the comparison per weapon and input |
| AGS-17 hold-time model (185 m/s, x1.8) against in-game measurements | 67 measurements, 279-1931 m on level ground, agreement 0.7 % in v^2/g; RMS 5.34 m with refitted speed and top | `AGL:tools/game_ballistics/README.md`; `SB:RELEASE_NOTES.md` (SB#13) | UNVERIFIED (the 67 measurements are the owner's in-game data, not in the repositories) |
| Simulation with the game's values (muzzle that moves with the elevation) | solutions land within 1 mm; the UB-32 had missed by up to 22 m at short range before | `SC:CHANGELOG.md`, entry 45.7.0 | UNVERIFIED (a changelog statement) |
| Every input of the firing solution (velocity, gravity, motor, cap, rotation, drag, launch point, spread, lifespan, explosion, bore, zoom, limits, minimum distance, scale offset, hold model) of all 104 SB and 135 SC weapons: value used, game value, source asset, label | 2 704 labelled rows: VERIFIED 1 762, INFERRED 367, UNVERIFIED 53, ASSUMED 522; 0 unexplained differences from the game after one fix: the projectile lifespan (`InitialLifeSpan`), which the 108 generated direct-fire weapons of SC had as the default 100 s and SB lacked, is now the game's 4-40 s in both apps (SC 45.31.0, SB 1.6.1); weapons inherited from the upstream table, fitted or from mods are named in `DP` section 6 | `DP`, `AGL:tools/game_ballistics/provenance.py` (run on the existing dump, build 26005357) | VERIFIED† for the equalities; the labels INFERRED / UNVERIFIED / ASSUMED are the point of the table |
| Launch heights of vehicle mounts | taken from the game files for AGS-17, MK19, SPG-9 on listed vehicles | `SB:RELEASE_NOTES.md` | VERIFIED (file data); not checked in game, see section 10 |

### 1.5 Sight scales of the overlay (audit of 2026-11-05)

`SBS` audits every scale the Squad Ballistics overlay draws in a sight against the server package (build 26005357); its own labels
are VERIFIED, COMPUTED (physics from verified inputs, read here as INFERRED), ASSUMED and MEASURED (owner's in-game data, not in the
repositories, read here as UNVERIFIED).

| Scale | Result | Source | Label |
|---|---|---|---|
| Mark offset `focal x tan(angle - bore)` | rectilinear projection with a horizontal FOV; matches an independent integrator pixel by pixel | `SBS`; `SB:tests/test_mark_end_to_end.py` | VERIFIED (committed test) |
| Zoom and bore of the 78 emplaced and vehicle entries | equal to the game files, no difference | `SBS`; `SB:tests/test_game_weapons.py`, `SB:tests/test_sight_data.py` | VERIFIED |
| Zoom and bore of the 26 hand-held launchers | x1 and 0 assumed; the files hold `SeparateAdsFov` (RPG-7V1 61, RPG-28 37, C90-CR 69, Carl Gustav 77, MAAWS 60, NLAW 70, RPG-29 optic 49, grenade launchers 80-90), but whether it replaces or scales the FOV setting is native code; open as `deadline-squad/squad-ballistics#17` (one in-game measurement settles it) | `SBS` "Differences found" 2 | ASSUMED (value), UNVERIFIED (meaning) |
| Range ladder, greatest distance | `LADDER_MAX_DISTANCE` was 5000 m ("no map is wider than 5000 m diagonally"); the game's play areas measure up to 7043 m (Yehorivka) and 9 of 17 maps measured are over 5000 m, so it is 8000 m now (SB 1.6.1) | `SBS`; `SB:tests/test_sight_scales.py`; `SB:tests/data/play_areas.json` | VERIFIED (data and test); the 17 maps are the ones with a play-area spline in the dump, not all 25 |
| Range ladder ticks (25-1000 m steps) | follow the mark; the step set is a display choice | `SBS` | INFERRED |
| Mil scale 6400 per circle | the game names the unit "MILLIRADIAN (mil)"; the earlier formula `x 17.78` differs by 0.012 % (0.2 mil at 1500 mil) | `SBS` | VERIFIED (unit name), UNVERIFIED (formula, its disassembly is no longer on disk) |
| Mortar firetable | 50 m steps up to 1250 m in the game; ours reaches 1236 m | `SBS` | VERIFIED |
| Mortar top elevation | 88.8 degrees (1578.7 mil) since 2026-11-10: the mount pitches the tube 0 to 43.8 degrees (`PitchInterval` of `BP_GenericDeployableMortarVehicle`) above the 45 degrees that the game's own sight adds to the tube pitch (`UMG_MortarControl`, Kismet bytecode). The upstream figure 88.875 (1580 mil), used until SB 1.7.1 and SC 45.37.0 and labelled ASSUMED here, gave a target between 51 m and 51.8 m on level ground a solution the tube cannot be laid on; the minimum distance is now the range at the mount's stop, 51.8 m | `SBS`; `GA` sections 2.2 and 2.4; `AGL:tools/game_audit/data/mount_limits.json` (read by `AGL:tools/game_audit/mounts.py`) | INFERRED (the limit is computed from the mount's pitch; the pitch range and the 45 are each VERIFIED) |
| Reticle marks (mil dots, range marks) | not drawn; the server package keeps widget layout and texture metadata but no pixels | `SBS` | UNVERIFIABLE from the server files |

## 2. Terrain


Source and method: the cooked Chaos heightfields of the landscape levels, placed with the landscape actor's transform
(16-bit per tile, about 0.3 mm; grid 1-1.2 m), fused by maximum with the collision of the placed static meshes and, where
it rises 0.5 m above the game terrain, with the SDK surface of SquadHeight 1.3.0 (1.6 cm). 16-bit PNG and lossless WebP
on SquadCalc's grid, 1 m (0.5 m on Chora and Kokan) (`H-README`, "Sources and fusion", "Grid size").

### 2.1 Interpolation rule

The game splits each quad into two triangles along the diagonal from (x, y) to (x+1, y+1). On points where the other
diagonal would differ by more than 5 mm, this diagonal is the closer in 79 of 89 (17 of 20 above 2 cm) (`H-README`,
"Interpolation: the game's triangles", `py/compare_interpolation.py`): VERIFIED. On the maps whose vertices lie on the 1 m
grid, bilinear against triangle reads RMS 0.3-2.2 cm (up to 0.2-1.1 m on the steepest quads) and triangle 0.0-0.1 cm:
VERIFIED. On maps off the 1 m grid the grid itself is a resample and the read is a small part of an RMS of 0.5-3 cm:
VERIFIED.

### 2.2 Accuracy against the server's own logs

Ground truth: positions the dedicated server wrote in its log (placed map markers, deployables, spawn points, explosions;
the player capsule centre minus 0.88 m), from the Training server only, anonymised by `log_points.awk` to
`<map> <kind> x y z` (`H-README`, "Audit against the game server"; `py/audit_ground_truth.py`).

| Map | bilinear within 2 cm | nearest within 2 cm | triangle within 2 cm | n | Label |
|---|---|---|---|---|---|
| Fallujah | 90 % | 79 % | 92 % (p95 5.5 cm; bilinear 10.1, nearest 8.0) | 107 points that agree with the log or differ by the grid (within 15 cm); 36 of 143 points are more than 15 cm off, each with a static mesh on or beside it, or Z = 0 in the log | VERIFIED |
| Goose Bay | 92 % | 60 % | 92 % | not recorded | VERIFIED (percentages), n UNVERIFIED |
| Yehorivka | 96 % | 63 % | 97 % | not recorded | VERIFIED (percentages), n UNVERIFIED |
| Black Coast | 89 % | 63 % | 91 % | not recorded | VERIFIED (percentages), n UNVERIFIED |

Reading: **89-97 % of the audited points are within 2 cm** for the bilinear and triangle reads (nearest: 60-79 %). The
sample is points that are ground traces in the log; it is not a random sample of the map and the log is the only
reference. The raw log lines are not in the repositories (they contain players' data). Other terrain checks (`H-README`):
game terrain against SquadHeight on open ground, median difference 0.0 mm on every map, RMS 0.5-14 cm; against the
landscape's own vertices on a 0.5 m grid RMS 0.000 (Chora) and 0.017 cm (Kokan) against 8.91 and 0.89 cm for 1 m
(VERIFIED).

### 2.3 Map grid and minimap corners (audit of 2026-11-05)

The in-game grid starts (A1) at the north-west corner of the minimap. The corners are `MapTextureCornerZero` and `MapTextureCornerOne`
in the `SQWorldSettings` of each gameplay layer; `py/minimap_corners.py` reads them for the 219 layers of build 26005357 and reduces
them to metres per map (`H-README`, "Minimap corners and the grid", `py/test_minimap_corners.py`). The game's three grid levels
(scale factors 1, 3, 9 of `W_SQMapGridLines`) are SquadCalc's 300 m keypad, 100 m and 33.3 m sub-keypads, which the grid already had.

| Finding | Value | Source | Label |
|---|---|---|---|
| Image corners of SquadCalc against the game's corners, 24 maps | within 1.00 m (largest: Black Coast 1.00 m); the images' corners are the game's, rounded or truncated | `H-README` table | VERIFIED |
| Skorpo | west edge 9.5 m, east edge 10.5 m off (the image corners were fitted to the upstream image), so every Skorpo grid line was 9.5 m west of the game's | `H-README`; `CL` 45.30.0 | VERIFIED |
| Skirmish and Seed layers with a minimap of their own (Chora, Mutaha, Tallil, Skorpo, Goose Bay, Manicouagan, Black Coast) | their grid starts up to 1.2 km from the map's (Chora Skirmish v1: 1007 m east, 1222 m south); a few regular layers differ by 0.5-1.5 m (Manicouagan RAAS v1/v2) | `CL` 45.30.0 | VERIFIED |
| Fix | the grid starts at the game's corner of the loaded layer, else at `SDK_data.minimap.game`; the image, heightmap, volume and markers keep the image corners; tests `SC:tests/squadGrid.test.mjs` (game corners of all 25 maps within 1 m of the image except Skorpo) | `CL` 45.30.0 | VERIFIED |
| Extent of the upstream map images, and image orientation where `Corner0` is not the north-west one (Fools Road, Gorodok, Jensen, Kokan, Lashkar, Logar, Mestia, Mutaha, Narva, Skorpo, Yehorivka list it swapped on some layers) | cannot be checked from the server package: the minimap textures keep metadata but no pixels; a cross-correlation with our heightmap resolves about 15 m, so it cannot tell a 10 m shift | `H-README` | UNVERIFIED (needs client pixels) |

## 3. Objects


Collision of every placed static mesh (complex triangle meshes from the cooked Chaos data, else boxes, spheres,
capsules, convex hulls) sampled at each grid point (`H-README`, "Sources and fusion").

| Check | Result | Source | Label |
|---|---|---|---|
| Game objects against SquadHeight on Skorpo | recall 98.9 %, precision 99.5 %, heights within 0.5 m on 99.75 % of shared object cells (median 5 mm); 99.99 % of all cells within 0.5 m | `H-README`, `py/compare_objects.py` | VERIFIED |
| Error of the 1 m grid on object cells, dense 1 km window of Fallujah, against the 0.25 m grid as reference | RMS 0.931 m (bilinear read), 0.951 m (triangle read, 2 % worse); equal on terrain | `H-README`, `py/compare_resolution.py` | VERIFIED |
| SquadCalc's old 8-bit heightmap of Skorpo against SquadHeight | error up to 1.05 m (2.09 m steps) | `H-README`, `py/compare_squadcalc.py` | VERIFIED |

**Reading of the RMS 0.93-0.95 m:** it is the resolution error of the 1 m grid on object cells (roofs, walls, trees) with
the 0.25 m grid as reference, not an error against the game. It is the reason for the voxel layer. A reference of 0.25 m
is itself a sample of the same triangles: INFERRED to be adequate because the exact tracer (section 6) is independent of it.

## 4. Voxel layer (`VCOL1`)

A top-surface heightmap cannot represent what is under a bridge deck or behind a wall thinner than a cell. The layer
stores, per occupied column, the z-runs of voxels that a Visibility-blocking collision triangle intersects
(`V-README`, "Representation").

| Property | Value | Source | Label |
|---|---|---|---|
| Format | `VCOL1`: per occupied column the z-runs, varint-packed, gzip; decoder in Rust/wasm (`SC:engine/src/voxel.rs`), JavaScript (`AGL:tools/volumetric/js/vcol.mjs`), WGSL (`SC:engine/wgsl/voxel.wgsl`); writer `py/codec.py` | `V-README` | VERIFIED |
| Voxel | 0.5 m horizontal x 0.25 m vertical for the evaluated files (1.0 m x 0.25 m also built) | `V-README` | VERIFIED |
| A voxel is marked | when a blocking triangle intersects it (exact conservative voxelisation: per row, column and cell the triangle is cut by the slab or rectangle and its z-range marked; half-open voxel boxes); voxels at or under landscape + 0.1 m are dropped; the facing of each triangle (up, down) is kept as separate sets | `V-README`, `py/columns.py` | VERIFIED |
| Fallujah statics, size (gzip) | exact voxeliser, 2026-11-05 (old in brackets): 1.0 x 0.25 m: 1.28 MB, 10.4 M voxels (1.57 MB, 8.4 M); 1.0 x 0.5: 1.01 MB (1.16); 2.0 x 0.5: 0.37 MB (0.40); 0.5 x 0.25: 3.37 MB, 25.4 M voxels (4.73 MB, 20.1 M); 0.5 x 0.5: 2.60 MB (3.44); trees add 0.44 M voxels at 1.0 m (unchanged). More voxels, smaller files, probably because a filled surface is one long run (not checked) | `V-README` | VERIFIED |
| Fallujah whole-map comparison | 7.5 MB PNG heightmap, 1.3 MB voxel 1.0 m (1.6), 3.4 MB voxel 0.5 m statics (4.7); the published-format file with statics and foliage at 0.5 m is 3.72 MB (old 5.07 MB, which held statics and trees) | `V-README` | VERIFIED |
| Decode / one 40 m segment test (Fallujah 0.5 m statics + foliage, Node 26) | 380 ms / 28 us (old 322 ms / 28 us; the old file decoded again now: 337 ms / 26 us) | `V-README`, `js/bench.mjs` | VERIFIED (one run each, shared machine) |
| Memory in the browser (Fallujah 0.5 m) | 101 MB of typed arrays (ids, run starts, runs; old file 99 MB) | `js/bench.mjs` | VERIFIED (the arrays' `byteLength`; not the page's total) |

Files built and published (the exact conservative builder, agl dev `e34e481` + `f116a2b`, issue #22 items B2 and B5; sizes are the gzip
files as served, 2026-11-05, MB = 10^6 bytes): **all 25 maps**.

| map | voxels | columns | volume.vcol MB | terrain.bin MB | total MB |
|---|---:|---:|---:|---:|---:|
| Al Basrah | 30 451 611 | 6 651 616 | 6.7 | 4.0 | 10.6 |
| Anvil | 10 967 659 | 3 799 365 | 3.8 | 3.3 | 7.1 |
| Black Coast | 56 465 424 | 11 436 477 | 29.8 | 5.0 | 34.9 |
| Chora | 91 931 376 | 46 320 086 | 36.9 | 5.1 | 42.0 |
| Fallujah | 26 207 218 | 4 293 607 | 3.7 | 2.2 | 5.9 |
| Fool's Road | 11 313 484 | 1 954 982 | 6.2 | 1.0 | 7.1 |
| Goose Bay | 31 546 317 | 8 328 396 | 15.0 | 3.6 | 18.6 |
| Gorodok | 84 623 955 | 16 190 947 | 39.3 | 5.8 | 45.1 |
| Harju | 83 968 689 | 14 156 430 | 41.2 | 3.9 | 45.1 |
| Jensen | 723 221 | 113 863 | 0.1 | 3.6 | 3.7 |
| Kamdesh | 26 351 783 | 5 611 970 | 14.4 | 5.4 | 19.7 |
| Kohat | 5 294 803 | 2 140 481 | 2.0 | 6.5 | 8.5 |
| Kokan | 2 198 643 | 536 181 | 0.7 | 4.0 | 4.7 |
| Lashkar | 32 899 158 | 12 971 740 | 13.3 | 9.9 | 23.2 |
| Logar | 3 044 202 | 789 524 | 1.3 | 1.1 | 2.4 |
| Manicouagan | 63 760 981 | 9 631 372 | 17.6 | 5.2 | 22.7 |
| Mestia | 13 341 383 | 3 114 491 | 7.6 | 1.2 | 8.8 |
| Mutaha | 4 367 244 | 755 369 | 1.0 | 1.7 | 2.7 |
| Narva | 22 401 380 | 4 478 752 | 6.0 | 1.8 | 7.8 |
| Pacific | 6 432 244 | 1 597 851 | 2.8 | 5.2 | 8.0 |
| Sanxian | 53 268 036 | 7 028 913 | 16.4 | 3.8 | 20.2 |
| Skorpo | 35 144 900 | 10 512 339 | 24.8 | 8.9 | 33.7 |
| Sumari | 5 052 864 | 1 903 765 | 1.0 | 0.4 | 1.3 |
| Tallil | 25 877 723 | 16 031 048 | 5.2 | 4.6 | 9.8 |
| Yehorivka | 122 097 455 | 18 617 851 | 48.6 | 13.0 | 61.6 |

`volume.vcol` 0.1 to 48.6 MB, `terrain.bin` 0.4 to 13.0 MB, 1.3 to 61.6 MB per map, 455 MB in all. In headless Chromium the biggest
map (Yehorivka, 48.6 + 13.0 MB) is ready 3.3 to 3.7 s after the setting is turned on and Chora (46 million columns) 4.2 to 4.4 s; the resident
memory of the browser's whole process tree goes from 1.4 GB (page alone) to 2.8 GB (Yehorivka) and 3.3 GB (Chora), 2.1 to 2.3 GB for Skorpo, Black Coast,
Harju and Gorodok; nothing failed on a 15 GB host (`volume_check.mjs`, `E-README` "Files served for each map"; VERIFIED, one run each). Build times: section 12.2.

### 4.1 What the game files contain (Fallujah)

44 452 static placements (13 856 components), 72.1 M collision triangles, 99.98 % complex (`CTF_UseComplexAsSimple`);
3 012 placements block nothing, 36 do not block Projectile; 274 708 foliage instances of which 11 616 block (VERIFIED,
`V-README`, `extractor inventory`). The collision-profile table of the engine (`DefaultEngine.ini`) is in an encrypted
pak index which was not circumvented; the effective Projectile response of each placed object is read from its own
serialised `BodyInstance` (`CS` section 3). Windows: the glass sections of 97 meshes (65 buildings) have collision enabled
in the cooked complex mesh (628 628 + 191 036 triangles, 0 disabled) (`CS` section 4, VERIFIED).

## 5. Collision primitives

Primitives of every `BodySetup` `AggGeom` multiplied by mesh placements (`AGL:tools/volumetric/semantics/primitive_counts.py`,
`CS` section 7, totals in `AGL:tools/volumetric/data/primitives.json`; VERIFIED, all 25 maps). Convex hulls dominate and
spheres are almost absent.

| map | box | sphere | capsule | convex | meshes with shapes |
|---|---:|---:|---:|---:|---:|
| albasrah | 166 445 | 2 | 370 | 1 392 624 | 11 989 |
| anvil | 16 536 | 6 | 1 359 | 76 939 | 3 395 |
| blackcoast | 18 161 | 2 | 105 | 145 315 | 2 663 |
| chora | 5 507 | 0 | 396 | 64 719 | 6 301 |
| fallujah | 69 546 | 2 | 59 | 250 916 | 3 415 |
| foolsroad | 2 521 | 0 | 15 | 10 123 | 623 |
| goosebay | 11 243 | 0 | 32 | 60 865 | 1 401 |
| gorodok | 8 288 | 0 | 547 | 108 795 | 1 687 |
| harju | 48 538 | 2 | 59 | 166 611 | 4 413 |
| jensen | 2 424 | 0 | 39 | 7 536 | 519 |
| kamdesh | 1 662 | 0 | 2 | 59 655 | 3 992 |
| kohat | 2 442 | 0 | 817 | 28 025 | 2 210 |
| kokan | 7 037 | 0 | 374 | 10 805 | 738 |
| lashkar | 4 049 | 5 | 1 210 | 70 959 | 3 083 |
| logar | 1 883 | 5 | 111 | 24 572 | 957 |
| manicouagan | 17 902 | 0 | 33 | 122 328 | 3 583 |
| mestia | 1 515 | 0 | 109 | 27 125 | 787 |
| mutaha | 8 562 | 0 | 1 109 | 59 790 | 4 871 |
| narva | 48 393 | 0 | 79 | 98 148 | 4 164 |
| pacific | 366 | 2 | 0 | 1 529 | 42 |
| sanxian | 24 701 | 0 | 89 | 731 115 | 2 918 |
| skorpo | 8 152 | 0 | 87 | 111 154 | 7 348 |
| sumari | 15 300 | 2 | 973 | 32 691 | 3 302 |
| tallil | 15 864 | 0 | 665 | 64 624 | 1 172 |
| yehorivka | 14 498 | 0 | 83 | 340 220 | 3 642 |

Which of the two representations (complex triangles or these simple shapes) a projectile trace uses is **UNVERIFIED**
(`CS` section 1, test T6); the owner cancelled the in-game tests (#22, decision 1), so the model uses the complex mesh
as the upper bound and `CS` section 4 gives both bounds.

## 6. Exact reference tracer and its fixed bug

`AGL:tools/volumetric/py/reference.py` is the reference: float64 Moller-Trumbore segment-triangle tests against every
Visibility-blocking triangle of the map, no voxels, no sampling of the geometry. It is independent of the voxel builder,
and a Rust BVH (`SC:engine/src/bvh.rs`, `trace.rs`) is checked against it.

**The bug.** `TriangleIndex.tiles_on` sampled a segment every 2 m over 8 m tiles and skipped tiles that a segment only
clips at a corner, so triangles in those tiles were never tested. Fixed in `AGL` commit `d0ac55a` (merged as `9852b75`,
2026-11-04). Effect, measured by rerunning with the same inputs and seeds:

| Where | Effect | Source | Label |
|---|---|---|---|
| 20 000 Fallujah segments | 22 affected | commit message `d0ac55a` | VERIFIED (commit message; the regression test is in `tests/test_volumetric.py`) |
| Fallujah, 3 000 LOS pairs | five counts moved by one pair each (exact blocks 2 217 instead of 2 216, heightmap false BLOCKED 141 -> 140, voxels 0.5 m false BLOCKED 169 -> 168; 6.17 % -> 6.13 % wrong); the 1.0 m run: heightmap false CLEAR 134 -> 135, voxels false BLOCKED 251 -> 250 | `V-README` | VERIFIED |
| Kohat, Fallujah (window evaluation) | none: `cases.csv` identical before and after | `V-README` | VERIFIED |
| Logar | one pair flips its grazing flag (grazing-free 4.23 % -> 4.20 % heightmap, 2.00 % -> 1.97 % voxels) | `V-README` | VERIFIED |
| Rust BVH against the reference on Fallujah, 100 000 segments | with the stock sampler 21 disagreed (6 reference no-hit, 15 reference later hit); all 21 recomputed against every triangle whose box meets the segment equal the BVH to 1e-15; 0 disagreements afterwards, worst hit-point difference 3.9e-13 m, 29 947 hits | `E-README`, "BVH against the exact tracer on Fallujah" | VERIFIED |

The conclusions of the earlier evaluation did not change. The data set of the BVH test was repaired by the recheck tool
(`SC:engine/tools/recheck_expected.py`) rather than regenerated; the README says so, and this is the only difference
from a regeneration.

## 7. Evaluation of the models against the exact tracer

### 7.1 Line-of-sight pairs (Fallujah, Kohat, Logar)

3 000 eye-level pairs, 10-60 m apart, inside a 600 m window around the densest columns, decided by the exact tracer
(reference.py, fixed). "Grazing" = the exact answer flips when the segment moves 0.25 m. Statics columns 0.5 x 0.25 m for
the voxels; `terrain` from the extracted landscape for Kohat and Logar (`V-README`, "Result on Fallujah"). **Re-measured on
2026-11-05 with the exact voxeliser's columns**, "old" being the sample-lattice builder. The pair draw puts 80 % of its points
near object columns, so new columns change the draw; to compare like with like, the old columns chose the pairs and the new ones
were scored (scratch variants of `eval_los.py`; the heightmap column reproduces the old figures to the pair, which shows the
pairs are the same). All figures VERIFIED.

| Fallujah, 3 000 pairs | 1 m heightmap | voxels 1.0 x 0.25 m, old -> new | voxels 0.5 x 0.25 m, old -> new |
|---|---|---|---|
| judged wrong | 9.5 % | 8.4 % -> 8.4 % | 6.1 % -> **5.8 %** |
| wrong, ignoring grazing | 5.1 % | 4.0 % -> 4.0 % | 1.9 % -> **1.5 %** |
| false CLEAR | 144 | 2 -> **0** | 16 -> **0** |
| false BLOCKED | 140 | 250 -> 252 | 168 -> 174 |

(The 1.0 m and 0.5 m columns are separate runs on different random pairs. Heightmap in the 1.0 m run: 8.7 % / 5.2 %,
135 false clear, 127 false blocked. With the landscape sampled from the extracted heights, the 0.5 m run gives heightmap
9.6 % / 5.7 %, voxels 5.6 % / 1.5 % -> 5.4 % / 1.3 %, false clear 147 / 12 -> 147 / 0, false blocked 156 -> 161. A fresh
draw from the new columns gives other pairs: 0.5 m heightmap 8.3 % / 4.6 %, voxels 5.9 % / 1.8 % (0 false clear, 178 false
blocked); 1.0 m heightmap 9.8 % / 5.6 %, voxels 9.1 % / 4.1 % (0, 272).)

| 3 000 pairs | Kohat heightmap | Kohat voxels, old -> new | Logar heightmap | Logar voxels, old -> new |
|---|---|---|---|---|
| wrong | 2.3 % | 2.2 % -> 2.1 % | 7.9 % | 6.4 % -> **6.8 %** |
| wrong, ignoring grazing | 0.7 % | 0.5 % -> 0.4 % | 4.2 % | 2.0 % -> **2.2 %** |
| false CLEAR | 40 | 3 -> 0 | 76 | 2 -> 0 |
| false BLOCKED | 28 | 63 -> 64 | 162 | 190 -> **204** |

Kohat is dense (8 792 statics placements, 4.3 M triangles), Logar open rural terrain (4 098 placements, 2.6 M triangles); the
old columns of the two maps were rebuilt from the commit before the exact voxeliser and reproduce the old voxel counts
(2 852 236, 1 592 422), which is why the pairs are the same. **Logar got worse** (+14 false blocked, +0.4 points wrong; still 1.1
points better than the heightmap), Kohat and Fallujah got better; the false clear is gone on all three and the cause of the extra
false blocked on Logar was not isolated (its voxel count grew least, +14 % against +22 % and +27 %).
Pattern: the heightmap fails by letting shots through walls, decks and buildings (false CLEAR); the voxels remove that and pay
with blocking up to a voxel diagonal from real geometry (the first builder's 25 checked false blocks lay 0.05-0.55 m from geometry;
with the exact voxeliser every not-grazing false block of the 100 000-segment runs was checked to meet a triangle of the voxel it
names, `V-README`). The gain is largest where objects are dense (Fallujah) and smallest on Kohat, where the terrain
dominates (INFERRED from the three maps; three maps are not a sample of 25).

### 7.2 Windows, doorways and interiors (`py/eval_openings.py`)

Share of cases where the model gives the reference answer (up to 120 cases per category, seed 11, 600 m window, full
`.vcol`; n in brackets) (`V-README`). The voxel column is old -> new on **the same cases** (a scratch variant draws the
points from the old `.vcol` and scores the new one); VERIFIED:

| category (truth) | Fallujah heightmap / voxels | Kohat heightmap / voxels | Logar heightmap / voxels |
|---|---|---|---|
| opening: inside -> outside, clear | 0 % / 49 % -> 49 % (105) | 0 % / 35 % -> **29 %** (51) | 0 % / 12 % -> 12 % (101) |
| room_clear: same roof, clear | 0 % / 73 % -> 71 % (78) | 0 % / 84 % -> **81 %** (120) | 0 % / 65 % -> **62 %** (120) |
| wall: inside -> outside, blocked | 100 % / 100 % -> 100 % (120) | 100 % / 99 % -> 100 % (120) | 100 % / 100 % -> 100 % (120) |
| room_partition: same storey, blocked | 100 % / 99 % -> 100 % (120) | 100 % / 98 % -> 100 % (120) | 100 % / 99 % -> 100 % (120) |
| room_floor: other storey, blocked | 100 % / 100 % -> 100 % (120) | 100 % / 100 % -> 100 % (120) | 100 % / 100 % -> 100 % (120) |

The heightmap treats every roofed space as solid and never sees an opening; the voxels find about half of the openings on
Fallujah and fewer on Kohat and Logar. This is a weakness of the voxel layer and is reported as such. The exact voxeliser finds
the same share on Fallujah and Logar, 6 points fewer on Kohat, and 2-3 points fewer of the open room interiors on all three maps,
and blocks walls and partitions every time (99, 98, 99 % -> 100 %): thin openings are closed (on Jensen a 0.5 m wide gap in a
window wall is filled and the target dialog no longer offers the windows of that building, VERIFIED by decoding both files). A
fresh draw gives openings 39 % / 43 % / 15 % and room_clear 65 % / 58 % / 70 % on other cases.

**Limitation: thin openings (`#26`, open).** A window or doorway about a voxel wide is filled by the conservative voxels of its own frame
(hypothesis, not verified: a gap narrower than about 1.5 voxels on the 0.5 x 0.25 m grid; no run varied the grid). Verified on Jensen by
decoding both files: the wall at y = -205 to -204.5 had a 0.5 m gap at x = 127.0 to 127.5 and is solid across x = 124 to 128 now, so
the target dialog offers `roof +6.30` only at (127, -205), where the old file offered `window +1.57` and `window +4.45`; the exact tracer
still has the opening (1 081 clear positions at the window height). The window of the building at Jensen (131, -199), 1.6 m over the
landscape, is still offered (`window:0`), which is why the browser checks use it. The error is in the blocking direction (a shot
that the game lets through is refused), the opposite of the heightmap's. Options ranked in `#26`: (1) rely on the precision regions, which
recover the windows of a target from the exact triangles (only Jensen has one published); (2) add a sparse "hole" layer for target
heights derived from the exact triangles; (3) a 0.25 m grid near buildings. Recommended there: (1) now, measure (2) before building it.


## 8. Voxel DDA parity, precision pass

### 8.1 Exact voxel-column DDA (Jensen, Kokan)

100 000 random segments per map (70 % start within 3 m of an occupied voxel, 3-500 m long, inside the densest 1 km
window, at least 0.25 m above the landscape); the exact answer is the BVH of `SC:engine` over the Visibility triangles of the same layers; the
voxel file and the triangles agree (0 file voxels missing from a rebuild, 0 above-ground rebuilt voxels missing from the
file). The engine's DDA is a two-dimensional Amanatides-Woo walk over the columns, with a jump to the first run in the
segment's height range (`E-README`, "Voxel DDA against the python model and the exact triangles"; `V-README`):

| 100 000 segments | Jensen old | Jensen (statics, 85 KB) | Kokan old | Kokan (statics + foliage, 697 KB) | Label |
|---|---|---|---|---|---|
| DDA clear, sampled model blocked | 0 | 0 | 0 | 0 | VERIFIED |
| DDA blocked, sampled model clear | 101 | 77 | 193 | 179 | VERIFIED |
| exact blocked / clear | 29 732 / 70 268 | 30 071 / 69 929 | 12 709 / 87 291 | 13 214 / 86 786 | VERIFIED |
| false CLEAR (of them grazing) | 129 (14) | **0** | 83 (9) | **0** | VERIFIED |
| false BLOCKED (of them grazing) | 3 948 (2 637) | 3 922 (2 607) | 8 331 (3 840) | 8 499 (4 055) | VERIFIED |
| wrong, all / without grazing | 4.08 % / 1.43 % | 3.92 % / 1.31 % | 8.41 % / 4.57 % | 8.50 % / 4.44 % | VERIFIED |
| WGSL f32 (SwiftShader, a CPU) wrong, all / without grazing | 4.08 % / 1.43 % | 3.92 % / 1.31 % | 8.41 % / 4.56 % | 8.50 % / 4.44 % | VERIFIED |
| WGSL against native DDA: blocked/clear flips, other first voxel | 1, 9 | 0, 9 | 1, 1 | 0, 0 | VERIFIED |
| wasm against native DDA | equal on all 200 000 | equal on all 200 000 | | | VERIFIED |
| DDA speed (shared machine, load 11 to 13, all threads) | 416 000 seg/s | 518 700 seg/s | 167 000 seg/s | 570 500 seg/s | VERIFIED, not comparable across the two runs (different load) |

"Old" is the first, sample-lattice builder with its own segments; the other columns are the exact conservative voxelisation
(`py/columns.py`, issue #23, `AGL` `e34e481`) on the final `.vcol` files, measured on 2026-11-05 with 100 000 segments drawn again
from those files, so the exact answers differ as well. On the same old segments the new files give 4.04 % (Jensen) and 8.51 %
(Kokan) wrong, false blocked 4 039 and 8 508: the total is slightly better on Jensen and **0.10 points worse on Kokan**, because
the 83 false clear that disappear are fewer than the 177 false blocked that appear.

Explained, per `E-README`: all not-grazing false blocks (1 315 + 4 444) were checked and the reported voxel overlaps a triangle.
There is no false clear to explain: the old builder lost the voxel holding the exact hit in all 115 + 74 not-grazing cases (its
sample lattice missed a clipped corner), the exact voxelisation marks every voxel a triangle meets. The conservative file has more
voxels (673 122 -> 723 221 on Jensen, 2 007 949 -> 2 198 643 on Kokan) but a smaller `.vcol` (112 531 -> 85 476 B, 789 376 ->
696 798 B). Fallujah (statics + foliage, window with 45.3 M triangles, 26.2 M voxels): false clear 0 (old 494), false blocked 5 682,
wrong 5.68 % / 2.29 % without grazing (old 6.10 % / 2.60 %) (VERIFIED).

### 8.2 Precision pass (`RTRI1`)

Around one target, the voxels decide what is far from geometry, and the exact triangles of the 150 m square around the
target decide what comes within 0.6 m of an occupied voxel. Same segments; 16 regions per map; target = end of the segment
(`E-README`, "Precision pass", `SC:engine/tests/last-run-precision.txt`):

| 100 000 segments | Jensen voxel -> precision | Kokan voxel -> precision | Fallujah voxel -> precision | Label |
|---|---|---|---|---|
| false CLEAR | 0 -> 0 (old 129 -> 8) | 0 -> 1 (old 83 -> 4) | 0 -> 0 (old 494 -> 35) | VERIFIED |
| false BLOCKED | 3 922 -> 301 (old 3 948 -> 279) | 8 499 -> 866 (old 8 331 -> 858) | 5 682 -> 428 (old 5 609 -> 409) | VERIFIED |
| wrong, all / without grazing | 3.92 % / 1.31 % -> **0.30 % / 0.11 %** (old 4.08 % / 1.43 % -> 0.29 % / 0.10 %) | 8.50 % / 4.44 % -> **0.87 % / 0.45 %** (old 8.41 % / 4.57 % -> 0.86 % / 0.47 %) | 5.68 % / 2.29 % -> **0.43 % / 0.17 %** (old 6.10 % / 2.60 % -> 0.44 % / 0.17 %) | VERIFIED |
| sent to the exact pass | 42.4 % (old 42.0 %) | 37.4 % (old 37.0 %) | 60.4 % (old 60.1 %) | VERIFIED (not typical: the segments were chosen near geometry) |
| region file min / median / max | 57 B / 100 KB / 5.0 MB | 1.04 / 2.48 / 3.52 MB | 6.48 / 15.9 / 26.0 MB | VERIFIED |
| time per segment, one thread | 3.8 -> 6.2 us | 7.8 -> 10.6 us | 11.0 -> 40.2 us | VERIFIED, shared machine; Fallujah regions answered one at a time, not comparable with the other two (old run: load ~20, 69.8 -> 50.0 us) |
| target at the segment start: wrong / without grazing | 0.01 % / 0.00 % (old 0.00 % / 0.00 %) | 0.11 % / 0.05 % (old 0.10 % / 0.05 %) | 0.03 % / 0.01 % (old 0.04 % / 0.02 %) | VERIFIED |

Fallujah: statics + foliage (the voxel file holds both), densest 1 km window with 45.3 M triangles, 16 regions of 1.8 - 7.3 M
triangles, python under 4 GB and the Rust test under 5 GB (`E-README`, "Precision pass"). The regions were rebuilt from the final
`.vcol`; the Jensen region published on the site is identical to the rebuilt one after gunzip, so it was left as it is.

**Honest reading.** The exact voxelisation removes the false clear (129 / 83 / 494 -> 0) and with it the precision pass's
inherited false clear, but after the pass the wrong share is **0.01 points worse on Jensen and Kokan and 0.01 better on Fallujah**,
and the voxel walk alone is 0.09 points worse on Kokan: what is left is the voxel walk outside the 150 m square, which the
conservative file blocks slightly more often. The one Kokan false clear is a ray 0.04 mm from the shared edge of two 5 cm foliage
triangles; the region file's vertex lattice is 0.1 mm, so it is the file's stated precision (VERIFIED by querying the region:
shifting the segment 1 mm up hits).

With the exact triangles of the whole window available the pass has 0 wrong answers at **every** margin tested (0, 0.25, 0.3, 0.5,
0.6, 1.0 m) on Jensen and Kokan; with the old files margin 0 left 129 / 83 false clear and 0.3 m left one on Kokan, which is why 0.6 m
was chosen. The share sent to the exact pass is 34 % / 22 % at margin 0 against 45 % / 41 % at 0.6 m. 0.6 m is kept because
the published region and the file served today use it (`#27`, open, proposes dropping the margin: about a quarter fewer re-checks); a margin of 0 with 150 m regions was not run (not run on Fallujah either: 45.3 M
triangles do not fit the cap) (VERIFIED for the sweep, not run for the change).

## 9. Structure damage for FOB and HAB

Question: damage of shells to player-built structures (FOB radio, HAB, HESCO, sandbags, bunkers). Owner decision
2026-11-04: no penetration or through-obstacle calculation; armour-piercing rounds do not damage structures; HE and HEAT
explode on them (`#22`, decision 1). Source `SDMG`, data `AGL:tools/volumetric/data/structure_damage.json`, code
`SC:src/js/structureDamage.js`.

### 9.1 Data (VERIFIED, read from the cooked Blueprints)

| Fact | Value |
|---|---|
| Deployable Blueprints with a health | 227 of 235, in 49 groups of (health, damage-type table), 45 with a table |
| FOB radio (`BP_FOBRadio_AFU`) | 300 HP; Frag 0.1, HEAT 0.05, HAT 0.1, Explosives 0.5, Kinetic 0.01 (insurgent radio: HAT 1.0) |
| HAB (`ADF_Hab_Desert`) | 500 HP; Frag 0.01, HEAT 0.031579, HAT 0.008, Explosives 0.1, Kinetic 0.003125 (`BP_Deployable_Hab`: 100 HP; `IMF_hab`: 400; `MEI_Hab`: 300) |
| HESCO barrier (`BP_Hesco_ADF_Forest`) | 200 HP; Frag 0.01, HEAT 0.01, HAT 0.05, Explosives 0.25, Kinetic 0.005 |
| Mortar round (`BP_Mortarround4`) | impact 10 (Fragmentation); explosion 350, 0-40 m, falloff 7; secondary 250, 1-6 m, falloff 3.5 (Explosives) |
| Physical-material fields (`damage_absorbed`, `armor_thickness_mm`, `allow_penetration`) | not connected to explosion damage on structures; they belong to bullet penetration |

Multipliers were authored per structure, not per material. `lethality_modifier` and `splash_radius_modifier` do not exist
in the game data (`CS` section 6).

### 9.2 Calculation

First version (`SDMG` section 4, INFERRED): direct hit `impact x Modifier x direct + R(d) x Modifier x directRadial`, near
miss `R(d) x Modifier x indirect`, plus the secondary explosion, with `R(d) = damage x (1 - (d - inner)/(outer - inner))^falloff`.
Worked result (direct hit, full health; INFERRED because the combination is native code): mortar round on the FOB radio
161 per round, **2 rounds**; on a HAB (500 HP) 28.6 per round, **18 rounds**; on a HESCO barrier 66.1 per round,
**4 rounds**; a 125 mm HEAT round on a HAB 8 rounds, on a HESCO barrier 10 (`SDMG` section 4).

Static disassembly of the server binary (`NR`, VERIFIED by instruction bytes pinned in `tests/test_native_rules.py`)
resolves the combination for `ASQDeployable::TakeDamage` and changes four points of the first version:
the table is matched by exact class and an unlisted damage type does no damage; radial damage on a direct hit uses
`DirectHitDamageMultiplier`, while `DirectHitRadialDamageMultiplier` is read only by vehicles and emplacements; point
damage is `amount x Modifier` without the direct multiplier; and `ExplosiveMinimumDamage` is a floor added after the modifier
(`Lerp(Min, Base x Modifier x m, scale)`), non-zero for ten of the app's projectiles. Where the multiplier is 1 and
`Min` is 0, which includes the mortar examples above, the numbers are unchanged (`NR` section 4). The distance that scales
radial damage is from the explosion origin (impact point + 20 cm along the normal, asset-overridable) to the point where a
ray to the component's bounding-box centre first hits the structure on the Visibility channel (`NR` section 3).

What stays UNVERIFIED: how the Blueprint passes `ImpactDamageToApply` and the secondary explosion to `TakeDamage`
(cooked Kismet bytecode, `NR` 1.4); whether a hit shell is a deployable or an emplaced-vehicle actor for tripod items;
every figure in the shells-to-destroy tables, since none was measured in game (the tests were cancelled, `#22` decision 1;
`NR` section 6 lists the smallest measurements).

### 9.3 Native rules in the app, review fixes and the known deviation

`CL` 45.25.0 moved the app from the first, guessed combination to the rules read from the server (`NR`): the radial part of a direct
hit uses the direct-hit multiplier, the impact has no hit multiplier, `ExplosiveMinimumDamage` is a floor the modifier does not scale (ten
projectiles; 125 mm HEAT 35), a type that passes damage only on a direct hit does nothing to a near miss, the burst is measured from the
impact point moved along the normal (1 m for the mortar round, 0.15 m for tank HEAT), damage types are matched by exact class and health is
clamped to 0..max. The code is `SC:src/js/structureDamage.js`, the data are regenerated by `AGL:tools/volumetric/semantics/structure_damage.py export`,
and `SC:tests/structureDamage.test.mjs` encodes the native-rules cases (all failing against the previous implementation). Shells to destroy at full health,
one shell each, old guess / game rules, for a direct hit and a burst 3, 5 and 10 m away (`CL` 45.25.0; INFERRED, computed from verified
tables and the native rules, none measured in game):

| Shell on structure | direct hit | 3 m | 5 m | 10 m |
|---|---|---|---|---|
| mortar on the FOB radio | 2 / 2 | 8 / 8 | 22 / 22 | 65 / 65 |
| mortar on a HAB | 18 / 18 | 81 / 85 | 342 / 350 | 1071 / 1083 |
| mortar on a HESCO barrier | 4 / 4 | 17 / 17 | 126 / 129 | 429 / 434 |
| 125 mm HEAT on the FOB radio | 3 / 3 | 30 / 30 | 39 / 20 | 131 / 11 |
| 125 mm HEAT on a HAB | 8 / 8 | 80 / 80 | 103 / 40 | 344 / 18 |
| 125 mm HEAT on a HESCO barrier | 10 / 10 | 100 / 100 | 130 / 22 | 435 / 8 |

The 12 x 14 direct-hit table of `SDMG` changed in three cells (mortar on sandbags 9 to 10, BM-21 on the observation tower 51 to 50 and on the
mortar emplacement 10 to 11). The independent review of 45.22 to 45.26 (`CL` 45.27.0) found and fixed, with tests that fail without the fixes:
a *Landscape* target counted as behind an obstacle about half the time (the solver lands the shell up to 2e-6 m under the ground), a doubled
volume-worker load, a buried voxel that hid the ground in front of it, malformed volume and region files accepted (run lengths that wrap
in 64-bit arithmetic, non-finite header values), a skipped or case-sensitive sha256 check of the volume files, the heatmap not recomputed
when the range, elevation limits or gravity scale changed, and a contradiction in the README about open windows and doorways.

**Known deviation, left as it is (`CL` 45.27.0, `SDMG`).** For a structure whose collision box is inside the outer radius but whose ray hit
point is beyond it, the engine's `InternalTakeRadialDamage` returns `Min` (`Lerp(Min, Damage, 0)`), while the app, which has neither collision
nor ray, returns 0 beyond the outer radius. For the ten projectiles with `Min > 0` the game can deal up to `Min` (125 mm HEAT: 35) where the
app shows nothing, at the edge of the radius. The case needs the structure's collision shape, which the data does not hold; the structure
tooltip (six languages) and the source say so. UNVERIFIED in game.

## 10. Limitations and owner decisions


| Item | Status | Source |
|---|---|---|
| No penetration or through-obstacle calculation, by design | owner decision 2026-11-04 | `#22`, "Owner decisions" 1 |
| Windows: open (no glass, where players can enter) are holes in the geometry and stay holes; closed ones belong to non-playable apartments and are solid; no special glass logic | owner decision | `#22`, decision 2; `CS` section 1 |
| Doors: fully open or absent, so a doorway is always a hole; door leaves not modelled | owner decision | `#22`, decision 2 |
| In-game collision tests T1-T9 | cancelled (O1) | `#22` |
| Which trace (complex or simple) projectiles use; water; foliage vs mortar | UNVERIFIED | `CS` sections 3, 7 |
| Launch heights of the vehicle mounts without data (MK19 M1117, RHIB; AGS-17 on Kozak-2M1 and RHIB) | not measured in game; Squad Ballistics SB#12 | `SB:RELEASE_NOTES.md`; `#22` O2 |
| Launch height of the stationary AGS-17, MK19, SPG-9 (SB#13): files say 0.347 / 0.368 / 0.637 m, entries use 1 m | unchanged; the 67 measurements cannot tell 0.347 from 1 m (RMS 5.34 m both) | `SB:RELEASE_NOTES.md` |
| C90-CR, DZJ-08, RPG-28: values from the game files, no in-game shots | not measured | `#22` O2; `SB:RELEASE_NOTES.md` (SB#9) |
| QLZ87 beyond 400 m | not measured | `#22` O2 |
| GPU timings | none: the WGSL kernel was timed on SwiftShader (a CPU emulation, 7 200 and 11 400 segments/s on a loaded host on 2026-11-05, about 19 000 on an idle one before); item C9 is open and needs a machine with a GPU (section 12.4) | `E-README`; `#22` C9 |
| Thin openings (a window or doorway about a voxel wide) are closed by the conservative voxels | open, `#26`; recommended: precision regions now | section 7.2 |
| Hand-held launchers use zoom x1 and bore 0; the game's `SeparateAdsFov` is ignored | open, `deadline-squad/squad-ballistics#17`; needs one in-game measurement | `SBS` |
| Grid of Skirmish and Seed layers and of Skorpo started elsewhere than the game's | fixed in SC 45.30.0; the image orientation for a swapped `Corner0` cannot be checked without pixels | section 2.3 |
| Structure damage at the edge of the outer radius for the ten projectiles with a minimum damage | the app returns 0, the engine up to `Min` (35 for 125 mm HEAT) | section 9.3 |
| Dynamic spread of grenade machine guns (AGS-17, MK19, QLZ87) | the input of the game's curve is not recovered from the binary; the app uses a constant | section 11 |
| The voxel layer finds about half of the openings on Fallujah (49 %), 29 % on Kohat, 12 % on Logar | measured, section 7.2 | `V-README` |
| Voxel layer is conservative by up to a voxel diagonal; false blocked grows with density | measured | `V-README`, `E-README` |
| Screens other than 16:9 | out of scope (owner decision); the program warns once | `SB:RELEASE_NOTES.md` (SB#10) |
| Ground truth for terrain: Training server logs, ground traces only | single reference | `H-README` |
| No client pak used; no decryption of the encrypted pak index | scope and licence decision | `CS` section 8 |
| Repositories are private; public release allowed from 2027 | owner decision | task statement |

## 11. Native rules (status)

`NR` (static disassembly of the server binary, owner's installed copy, nothing run; merged into `dev` as `7438c08`)
exists and the figures of section 9.2 that depend on it are cited to it. Its own labels: deployable damage rule, engine radial law, event construction, explosion-to-structure distance, vehicle table:
VERIFIED; `ImpactDamageToApply` path and secondary explosion: INFERRED / NOT RECOVERED; dynamic MOA (AGS-17, MK19,
QLZ87): PARTLY RECOVERED. The static data are verified (curve `FC_MOACurve_GenericGMG`, 15 MOA at 0 s to 50 MOA at
0.75 s, cycle times 0.15 / 0.171 / 0.125 s) and so is the way the spread is composed from the current MOA, but the rule that makes the curve's
input grow and decay is **not recoverable from the binary**: no code of `ASQWeapon` writes it (62 instruction sites with that offset checked, the
writes belong to an unrelated class), so it is in Blueprint bytecode that was not decoded or acts by property name (`NR` section 2). The app therefore keeps a constant
spread for these weapons (the resting 15 / 3 / 7 MOA for the generated weapons, the sustained 50 for the AGS-17, `DP`), INFERRED. The smallest measurement that settles it is the
AGS-17 group-size test (ten bursts of ten rounds at a wall 100 m away, the radius of the group at shots 1, 5 and 10; Training only, with the owner's go-ahead).
The deviation of section 9.3 is the other finding of the native-rules work that the app does not model.

## 12. Evidence tables that were PENDING (filled 2026-11-05)

### 12.1 Reverse-position heatmap against the exact tracer (`#22` item C5)

For a target at its chosen height, the ground positions up to the weapon's range (at most 2000 m) with a clear line of fire to it
(`SC:src/js/positionHeatmap.js`; method in `E-README`, "Position heatmap"; shipped in SC 45.26.0, `CL`). The check is
`SC:engine/tools/js/heatmap_validate.mjs`: the same classifier with the voxels, with the voxels plus the target's precision region, and in
Node with every line of fire traced against the BVH of the exact collision triangles of the 1 km window; same landscape file in the three, so the
positions differ only by what the objects do. "Wrong" is false CLEAR plus false BLOCKED over the positions; the share is that sum divided by the positions
(INFERRED, arithmetic on the cells). DF_M2A1_50 (3 MOA), range 200 m, cell 2 m, 360 rays.

| Target (Jensen) and height | positions | voxels only: false CLEAR / false BLOCKED (wrong) | with region: false CLEAR / false BLOCKED | Source | Label |
|---|---:|---|---|---|---|
| (127, -205) window +1.57 m, first lattice file | 31 560 | 1 / 275 (0.87 %) | 0 / 0 | `E-README` "Against the exact triangles"; `#22` comment 6643831594 | VERIFIED (file since replaced) |
| (127, -205) window +4.45 m, first lattice file | 31 560 | 1 / 1 337 (4.24 %) | 0 / 0 | same | VERIFIED (file since replaced) |
| (127, -205) roof +6.30 m, exact file | 31 560 | 0 / 2 355 (7.46 %) | 0 / 8 (0.03 %, all beyond 100 m from the target) | `E-README` | VERIFIED |
| (127, -205) landscape, exact file | 31 560 | 0 / 717 (2.27 %) | 0 / 0 | `E-README` | VERIFIED |
| (131, -195) three-storey building, four heights, exact file | not tabulated here | 0 false CLEAR; false BLOCKED 0, 139, 0, 571 (floor +3.30, floor +0.30, roof, landscape) | 0 / 0 at all four | `E-README` | VERIFIED |
| (131, -199) window:0 (1.6 m), exact file, the target of the browser check | 31 089 | 0 / 182 (0.59 %) | 0 / 0 | `#22` comment 6670882449; `#26` update; raw output `~/work/ui-shots/heat-val-volumes2/` on the build host, not in the repositories | UNVERIFIED (issue comment only) |

The page's own run equals the Node run on all but 5 of 36 360 positions (last-bit flips of a line against a voxel face; scores differ by at most 1)
(`#22` comment 6643831594, UNVERIFIED as a count). Reading: with the region of the target the heatmap has no error but eight positions on the
roof; without it the error is false BLOCKED only, lines that graze a voxel corner or a frame, and a window target loses its beams (section 7.2, `#26`). The first lattice
file also had one false CLEAR; the exact file has none. Time per heatmap: section 12.4.

### 12.2 Map coverage: 25 of 25 maps, sizes and build times (`#22` items B2, B5)

All 25 `volume.vcol` + `terrain.bin` are built with the exact conservative builder (agl `e34e481`, memory fix `f116a2b`) and published
(`#22` comment 6670882449, SC 45.32.0); sizes and counts are in the table of section 4 (VERIFIED: sha256 and bytes in `meta.json` equal the
served files, header `VCOL1`, cell 0.5, per map). The 25 per-map `build.log` files of the final builds are empty (0 bytes) and contain no
FAILED; the old `~/data/volumetric/build_all.log` (2026-10-31) still lists FAILED for maps rebuilt since. Build times are not in any
repository: the systemd user journal of the build host (units `volr-a`, `volr-b`, `volr-c`, `volr-d`, `volr-final`, `volr-fix`) has a start and an
end line per map from `build_all.sh`, and the table gives the wall-clock time of the run that ended without FAILED and wrote the file (the time of the file agrees to a minute).
It is wall-clock on a shared host with up to four builds running at once (statics, foliage, columns and encoding together), so it is an
indication of cost, not a benchmark. UNVERIFIED (journal, not reproducible from the repositories).

| map | wall-clock | map | wall-clock | map | wall-clock |
|---|---|---|---|---|---|
| Al Basrah | 1 h 51 min | Kamdesh | 1 h 05 min | Narva | 18 min |
| Anvil | 30 min | Kohat | 9 min | Pacific | 14 min |
| Black Coast | 1 h 07 min | Kokan | 3 min | Sanxian | 1 h 22 min |
| Chora | 15 min (`volr-fix`; two earlier attempts FAILED) | Lashkar | 1 h 02 min | Skorpo (0.5 x 0.5 m) | 58 min |
| Fallujah | 34 min | Logar | 4 min | Sumari | 3 min |
| Fool's Road | 42 min | Manicouagan | 41 min (`volr-final`) | Tallil | 17 min |
| Goose Bay | 49 min | Mestia | 13 min | Yehorivka | about 1 h 44 min (INFERRED) |
| Gorodok | 1 h 55 min (`volr-final`) | Mutaha | 11 min | Jensen | 33 s |
| Harju | 30 min (`volr-final`) | | | | |

Yehorivka has no end line: the unit `volr-fix` was stopped at 20:30 UTC and the build continued outside it; the figure is the time from the unit's start (19:43)
to the `.vcol` file (21:27). Chora, Yehorivka, Harju, Manicouagan and Gorodok each have earlier FAILED attempts in the journal (their cause is not examined here); only the
run that finished is timed. Load times of the biggest files in the browser: section 4.

### 12.3 Damage footprint with voxel cover on the live site (`#22` item C6)

`squadDamage.damageField(heightAt, explosion, cell, progress, objects)`: with the volume layer a soldier is also covered when the voxel
walk finds a voxel between the explosion and him; the round lands at the height chosen for the target (SC 45.26.0, `CL`). Tests that fail on the previous commit and
pass now: `SC:tests/squadDamage.test.mjs`, and `SC:tests/volumeLayer.test.mjs` "cover" through the real wasm engine on a wall with a doorway
(the soldier behind the wall is covered, damage 0; the one in line with the doorway is not; an explosion 6 m up sees over the wall; an impact off the
landscape answers size 0) (VERIFIED, committed tests). Live measurement by `AGL:tools/browser_check/heatmap_check.mjs` on the Jensen window target (2026-11-04, `#22` comment 6643831594):

| Zone of the Jensen window target (pixels) | kill | wound | covered |
|---|---:|---:|---:|
| heightmap cover | 37 | 391 | 1 086 |
| voxel cover | 59 | 214 | 1 516 |

Reading: with the voxels the blast reaches through the openings (more kill, fewer wound pixels) and the rest is covered. UNVERIFIED: the counts are in the
issue comment only, were measured with the first lattice file (the windows of that building at (127, -205) are closed in the exact file, `#26`), and were not
measured again. The hit-probability line (rounds to kill) still reads the heightmap.

### 12.4 Timings: CPU measured, GPU PENDING (`#22` item C9)

| Measurement | Result | Source | Label |
|---|---|---|---|
| Heatmap, all 25 maps, wasm engine in a worker of headless Chromium 153, idle host (load 1.8), 80 480 positions at 600 m and 2000 m | 0.7 to 8.7 s per heatmap (median 2.0 s), 8 to 108 us per position (median 25 us); the earlier 2 to 26 s were measured at load average 22 | `E-README` "Time"; `AGL:tools/browser_check/heatmap_timing.mjs`; raw JSON `~/work/ui-shots/heatmap-timings-volumes2.json` on the build host | VERIFIED (one run, table in the README) |
| With a precision region (Jensen, 36 000 positions at 200 m) | region load 7.1 to 7.7 s (1.93 MB, quiet host), then 1.9 to 2.2 s for the trace against 1.0 to 1.5 s voxel only (Node, wasm) | `E-README` "Time" | VERIFIED (one run each) |
| WGSL voxel kernel on SwiftShader (a **CPU emulation** of a GPU) | 7 200 and 11 400 segments/s on a loaded host, about 19 000 on an idle one before; says nothing about a GPU | `SC:engine/wgsl/test/last-run-voxel.txt`; `E-README` | VERIFIED (CPU emulation only) |
| **WGSL kernels (`trace_segments`, `trace_trajectories`, `heatmap`, `voxel_segments`) and heatmap on a real GPU** | **PENDING** (the build host has no GPU: no `/dev/dri`, no `nvidia-smi`; Chromium's only device is SwiftShader) | | PENDING |

**Owner action for the GPU row.** On a machine with a real GPU (Chrome or Edge 113+; on Linux start Chrome with `--enable-unsafe-webgpu --enable-features=Vulkan`),
run `cd engine/wgsl && python3 -m http.server 8000` in a SquadCalc checkout, open `http://localhost:8000/bench/bench.html` (`SC:engine/wgsl/bench/bench.html`,
instructions in `SC:engine/wgsl/bench/README.md`), keep the tab in front, press **Run** (10-60 s on a discrete GPU) and paste the JSON it prints into
`deadline-squad/deadline-squadcalc#22`. No agent can do this: it needs hardware the build host does not have. Until then the report states no GPU figure.

## 13. Reproducibility

**What is needed.** The dedicated server package (SteamCMD app 403240, build 26005357), the three repositories at the revisions of the key table, the
`squadcalc-heightmaps-py` image (`docker build tools/heightmaps/py`), the .NET SDK image for the extractor, Node 22+ and a Rust toolchain for the engine.
**Rebuild the voxel layer** (the recipes are in `V-README`, "Reproduce" and "Publishing to the site and the browser check"): `tools/heightmaps/heightmaps.sh extract`, then
`tools/volumetric/build_all.sh 0.5 0.25` (Skorpo: `build_all.sh 0.5 0.5 skorpo`), then `python py/publish_volume.py` for the site; a dense map takes about an hour (section 12.2).
**Re-run the evaluations**: `eval_los.py` and `eval_openings.py` (sections 7.1 and 7.2), the `voxel_parity` and `precision_parity` cargo tests (section 8), `heatmap_validate.mjs`
(section 12.1), the rows below. **The release bundle** (`tools/release/build_release.sh`, `tools/release/README.md`) archives the three repositories at one commit each, the built page, the
documents and the evaluation tables, scans for secrets (`tools/release/test_scan.sh` tests the scan) and writes `MANIFEST.json` with commits, versions and SHA-256.
**This report**: `python3 tools/release/check_report_refs.py` checks that every file path, commit and issue number it names resolves (needs `gh`; `--no-issues` skips the issues).

Python runs in the `squadcalc-heightmaps-py` image, the extractor in the .NET SDK image, as in `tools/heightmaps/heightmaps.sh`.



Python runs in the `squadcalc-heightmaps-py` image (`docker build tools/heightmaps/py`), the extractor in the .NET SDK
image, as in `tools/heightmaps/heightmaps.sh`. Game data: the dedicated server, SteamCMD app 403240, build 26005357.

| Result | Command (from the repository root named) |
|---|---|
| Parity SB / SC, 104 weapons | `AGL`: `python3 tools/direct_fire/compare.py <SB checkout> <SC checkout>` |
| Weapon data against the paks | `AGL:tools/game_ballistics/README.md`: `extractor dumpall ...`, `collect.py`, `gamecheck.py` |
| Data provenance of every input per weapon | `AGL`: `python3 tools/game_ballistics/provenance.py --resolved <resolved.json> --dump <dump> --sb <SB> --sc <SC> --check tools/volumetric/docs` (`DP` section 9); test: `tools/volumetric/tests/test_data_provenance.py` |
| Heightmaps | `AGL`: `tools/heightmaps/heightmaps.sh setup / extract / build` |
| Terrain audit against logs | `cat SquadGame*.log \| awk -f tools/heightmaps/log_points.awk \| sort -u > points.txt`; `py/audit_ground_truth.py <heightmaps> <map> points.txt --extract <root>` |
| Interpolation, resolution, objects | `py/compare_interpolation.py`, `py/compare_resolution.py`, `py/compare_objects.py` |
| One voxel map | `AGL`: `tools/volumetric/build_map.sh fallujah 0.5 0.25` (about 1 h for a dense map); all: `build_all.sh 0.5 0.25`; status: `python py/status_table.py` |
| LOS evaluation and openings | `AGL:tools/volumetric/py`: `eval_los.py`, `eval_openings.py` (see `V-README`, "Reproduce") |
| Exact BVH against the reference | `SC:engine`: `cargo test --release --features threads --test fallujah -- --ignored --nocapture` (needs `ENGINE_FALLUJAH_DIR`) |
| Voxel DDA parity | `SC:engine`: `ENGINE_VOXEL_DIR=out ENGINE_VOXEL_MAPS=jensen,kokan cargo test --release --features threads --test voxel_parity -- --ignored --nocapture` |
| Precision pass | `py/build_region.py <map>.vcol out/regions --centre X Y --radius 150 --margin 0.6 <tris.npz>`; `cargo test ... --test precision_parity -- --ignored --nocapture` |
| Collision semantics, primitives | `AGL:tools/volumetric/semantics`: `primitive_counts.py`, `static_semantics.py`, ... (`CS` section 8) |
| Structure damage | `SC`: `npm test` (`tests/structureDamage.test.mjs`); data: `AGL:tools/volumetric/data/structure_damage.json` |
| Native rules | `NR` section 7: `nm -D -C`, `objdump -d`, `python3 -m unittest tests.test_native_rules` |
| Publish the voxel files of a map | `AGL:tools/volumetric/py`: `publish_volume.py`, `publish_regions.py` (`V-README`, "Publishing to the site and the browser check") |
| Heatmap against the exact triangles | `SC`: `node --import ./engine/tools/js/hooks.mjs engine/tools/js/heatmap_validate.mjs --served <heightmaps/jensen> --region region_221_-229.rtri --tris jensen.tris.bin --window=-404,-1104,1000 --target=127,-205 --weapon DF_M2A1_50 --height window:1,window:0 --range 200 --out <dir>` (`E-README`) |
| Heatmap time per map; browser checks | `AGL:tools/browser_check/heatmap_timing.mjs`, `heatmap_check.mjs`, `volume_check.mjs`, `targets_check.mjs`, `grid_check.mjs` (`AGL:tools/browser_check/README.md`) |
| GPU benchmark | `SC:engine/wgsl/bench/bench.html` (section 12.4) |
| Minimap corners and grid audit | `AGL:tools/heightmaps/py`: `minimap_corners.py dump`, `table`; `SC`: `npm test` (`tests/squadGrid.test.mjs`) |
| Game-data audit of the calculator's tables: mount limits, minimum distances, landscapes, minimap corners, FOB radius, protection zones, API layers | `AGL`: `tools/game_audit/game_audit.sh` with `extract-mounts`, `extract-layer-data`, `extract-landscapes`, `extract-layers`, `derive`, `check`, `api` (`AGL:tools/game_audit/README.md`); report `GA`; tests: `python3 -m unittest discover -s tools/game_audit`, `node --test tools/game_audit/` |
| Sight-scale audit | `SB`: `python -m pytest` (`tests/test_sight_scales.py`, `test_game_weapons.py`, `test_sight_data.py`, `test_mark_end_to_end.py`) |
| Provenance counts | `AGL:tools/volumetric/tests/test_data_provenance.py` |
| Reference check of this report | `AGL`: `python3 tools/release/check_report_refs.py` |
| Whole release bundle | `AGL`: `tools/release/build_release.sh` (manifest with commits, versions and SHA-256); scan test: `tools/release/test_scan.sh` |

## 14. Threats to validity

| Threat | What it means for the figures | Source |
|---|---|---|
| **No in-game validation of the whole chain.** The tests T1-T9 were cancelled; agreement is with the game files, with the server's own logs (terrain) and with an exact tracer on the game's own triangles | a projectile may meet other geometry than the complex mesh the model uses as the upper bound; the only in-game data are the owner's 67 AGS-17 measurements, which are not in the repositories | `#22` decision 1, O1; section 1.4, 5 |
| **Open windows and doors are holes, closed windows are solid, no glass logic** (owner decision) | a closed door or a window opened by players in game is not modelled; real glass is ignored | `#22` decision 2; `CS` section 1 |
| **Thin openings are closed by the voxels** | the opposite error: a shot the game allows is refused; 29 % of the openings are found on Kohat, 12 % on Logar | section 7.2; `#26` |
| **The grid origin depends on the layer** | fixed in SC 45.30.0 from the layers' own corners; the image orientation where `Corner0` is swapped and the extent of the upstream images cannot be checked without client pixels | section 2.3 |
| **Native-rules deviation at the outer radius** | structure damage at the edge of the radius is 0 in the app and up to `Min` in the engine for ten projectiles; the impact-damage path and the secondary explosion are INFERRED | section 9.3; `NR` |
| **Dynamic MOA rule not recovered** | the spread of grenade machine guns is a constant in the app, the game's grows with sustained fire (15 to 50 MOA over 0.75 s on the curve) | section 11; `NR` section 2 |
| **No community data as source** | all figures come from the server package; the only external dataset in the terrain fusion is the SDK surface of SquadHeight 1.3.0, used where it lies 0.5 m above the game terrain (`H-README`); the client pak is not used, the encrypted pak index is not circumvented, so client-only content (minimap pixels, reticles) is out of reach | `H-README`; `CS` section 8 |
| **Small and non-random samples** | LOS pairs on three maps (Fallujah, Kohat, Logar), DDA segments on three (Jensen, Kokan, Fallujah), segments chosen near geometry; terrain ground truth from the Training server's logs, n unrecorded for three maps; three maps are not a sample of 25 | sections 2.2, 7, 8 |
| **Paired comparisons** | the old-to-new figures use the same pairs or cases on purpose; a fresh draw gives other figures (listed beside them), so only differences within a pairing are meaningful | sections 7.1, 7.2, 8.1 |
| **The reference tracer is software too** | it had a bug (section 6); it is independent of the voxel builder and agrees with the Rust BVH to 3.9e-13 m on 100 000 segments, but a bug common to both would not show | section 6 |
| **Timings come from one shared machine, one run each**; no GPU figure | cost indications, not benchmarks | sections 4, 8, 12.4 |
| **Provenance: 522 inputs are ASSUMED and 53 UNVERIFIED** of 2 704 | Workshop mods, hand-held bore and zoom, native explosion defaults, launch heights without data | `DP` |
| **Scope limits by owner decision** | Linux only, 16:9 screens only, no penetration calculation | `SB:RELEASE_NOTES.md` (SB#10); `#22` decision 1 |

## 15. Changelog of the evidence (first draft 2026-11-04 to final 2026-11-05)

| What changed | Why | Source |
|---|---|---|
| Reference tracer fixed (tiles that a segment only clips at a corner were never tested) | 22 of 20 000 Fallujah segments affected, the conclusions of the evaluation did not change | section 6; AGL `d0ac55a` |
| Voxel builder replaced by an exact conservative voxelisation; the sample lattice bug found | the Tallil investigation (the statics step never finished: 99.4 % of the sample points belonged to triangles outside the grid; fixed in `columns.py`, AGL `85c93df`) showed that the lattice also skipped half of each triangle (`triu_indices`, about 11 % of voxels missing) and could not prove a voxel hit by a clipped corner (`#23`); the exact builder is AGL `e34e481`, memory `f116a2b`. False CLEAR went to 0 on every evaluated map | section 7, 8; `#22` comments of 2026-11-05 |
| All evaluation tables measured again (old -> new) | the first tables were of the lattice builder; Logar and Kokan came out slightly worse (Logar +14 false blocked, Kokan +0.10 points), the precision pass 0.30 / 0.87 / 0.43 % wrong | sections 7, 8; `#20` comment 6670455739 |
| Thin openings (window thinning) documented as a limitation | the conservative voxels fill gaps of about a voxel: Jensen's windows at (127, -205) are gone, openings found on Kohat 35 -> 29 % | section 7.2; `#26` |
| Voxel files published for all 25 maps (11 before) | `#22` B2, B5: 0.1 to 48.6 MB per map; `terrain_raster.py` made memory-safe for Chora | section 4, 12.2; SC 45.32.0 |
| Projectile lifespan | the provenance table found 108 generated weapons with SC's default 100 s against the game's 4-40 s; both apps carry the game's value and refuse a shot that takes longer | section 1.4; SC 45.31.0, SB 1.6.1; `DP` |
| Provenance table with labels (VERIFIED 1 762, INFERRED 367, UNVERIFIED 53, ASSUMED 522) | every input of the firing solution per weapon with its source | section 1.4; `DP` |
| Ladder limit 5000 -> 8000 m | the sight-scale audit: the game's play areas measure up to 7043 m; the hand-held ADS FOV opened as `deadline-squad/squad-ballistics#17` | section 1.5; SB 1.6.1 |
| Mortar top elevation 88.875 -> 88.8 degrees, minimum distances from the mounts (2026-11-10) | the game-data audit read the pitch range of every artillery mount and what its sight adds (mortar 0..43.8 + 45); the minimum distance of the five weapons their mount stops is the range at that stop (51.8, 51.8, 358, 985.1 and 147.1 m); the same audit corrected, in the calculator, the display range of the BTR-4 AGS, the range circle of the hell cannon (923 -> 924 m), the landscape fields of seven maps, the FOB exclusion radius of 38 layers and the protection zone of two Goose Bay layers | section 1.5; `GA`; SC 45.38.0 (`35e56973b`, `69bd47058`, `cede4aa71`, `d67f8d190`), SB 1.7.2 (`8c3b7cd`) |
| Grid origin | the grid audit against the minimap corners of 219 layers: Skorpo 9.5 m west, Skirmish and Seed layers up to 1.2 km | section 2.3; SC 45.30.0 |
| Structure damage on the native rules; review fixes; the deviation at the outer radius documented | static disassembly of `ASQDeployable::TakeDamage` replaced the guessed combination; the independent review of 45.22 to 45.26 found the defects listed in `CL` 45.27.0 | section 9.3; SC 45.25.0, 45.27.0; `NR` |
| Native rules: dynamic MOA reported as not recoverable | 62 instruction sites searched, none writes the input | section 11; `NR` section 2 |
| Heatmap and damage-footprint tables filled; exact-file re-measure | `#22` C5, C6; (131, -199) replaces the window target the exact file closed | section 12.1, 12.3 |
| Map count: 25 server-derived maps | the inventory of the server package; the scope sentence of section 0 | `H-README`; SC 45.29.0 |
| Browser-check fixes | `targets_check` failure was a stale hover timer, not the data (`deadline-squad/deadline-squadcalc#28`, SC 45.33.0) | `CL` 45.33.0 |

