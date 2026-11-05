# Methods and results: ballistic calculator, terrain and object model for Squad

Report for the thesis on computational ballistics. Russian version: [`thesis-methods-and-results.ru.md`](thesis-methods-and-results.ru.md).
Written 2026-11-04 from the evidence that exists in the repositories; nothing in it was measured in a running game.
Updated 2026-11-05: the voxel figures of sections 4, 7 and 8 were measured again with the exact conservative voxelisation
(`AGL` `e34e481`, memory fix `f116a2b`, issue #23) on the final `.vcol` files; the figures of the earlier sample-lattice builder are
kept as "old" next to them.

## 0. How to read this report

Every number carries a source and one of four labels (the fourth, ASSUMED, is used where a number is not in the server files at all).

| Label | Meaning |
|---|---|
| **VERIFIED** | Produced by a committed tool or test from the game files (Squad dedicated server build 26005357, SteamCMD app 403240), and the repository records the command and the output. A dagger (†) means the author of this report re-ran it on 2026-11-04. |
| **INFERRED** | Follows from verified data by an argument that is stated next to it. |
| **UNVERIFIED** | Recorded in a commit message, an issue or a note without a reproducible output, or not measurable from the server files, or not measured. |
| **ASSUMED** | Not in the dedicated-server files at all and used because the model needs a number: Workshop mods, the bore and zoom of handheld weapons (they come from the client's animation), the native C++ explosion defaults, SquadCalc's default lifespan; the reason is stated next to it (`DP`). |

Cells in **PENDING** tables are empty on purpose: the evidence does not exist yet, and the issue item that produces it is named.

### Source key (revisions the figures were read at)

| Key | What | Revision |
|---|---|---|
| `SC` | SquadCalc fork (`deadline-squad/deadline-squadcalc`), branch `dev` | `2f1ae898ed90`, version 45.24.0 |
| `SB` | Squad Ballistics overlay app, branch `dev` | `5f11d21c837b`, version 1.6.0 |
| `AGL` | deployment and tools repository, branch `dev` | `7438c08dbb76` (this report and `tools/release/` are added on top) |
| `#22` | `deadline-squad/deadline-squadcalc#22`, "Completion checklist", items A1-D5 | read 2026-11-04 |
| `V-README` | `AGL:tools/volumetric/README.md` | |
| `H-README` | `AGL:tools/heightmaps/README.md` | |
| `E-README` | `SC:engine/README.md` | |
| `CS` | `AGL:tools/volumetric/docs/collision-semantics.md` | |
| `SDMG` | `AGL:tools/volumetric/docs/structure-damage.md` | |
| `NR` | `AGL:tools/volumetric/docs/native-rules.md` | merged into `dev` as `7438c08`, read at that revision |
| `DP` | `AGL:tools/volumetric/docs/data-provenance.md` and `data-provenance.tsv` | added on the branch `fix/provenance`; counts of 2026-11-05, SC 45.30.0, SB 1.6.1 |

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
| Weapons compared | 104 | `compare.py` output, SC `2f1ae898ed90` + SB `5f11d21c837b`, 2026-11-04 | VERIFIED† |
| Cases compared | 20 178 | same | VERIFIED† |
| Mismatches | 0 | same; also recorded in SB commit `f22e343` | VERIFIED† |
| Max-range differences | none (`{}`) | same | VERIFIED† |

Command: `python3 tools/direct_fire/compare.py <Squad-Ballistics checkout> <SquadCalc checkout>` (20 s).
Scope: the two solvers agree with each other. Agreement with the real game is the next subsection.

### 1.4 Agreement with the game

| Check | Result | Source | Label |
|---|---|---|---|
| Weapon data (velocity, gravity scale, motor, cap) of every weapon of both apps against the cooked Blueprints | `diff.md` lists every difference; the long-verified mortar (110 m/s, x1) and UB-32 (300 m/s, -50 m/s^2 for 2 s, x2) are reproduced | `AGL:tools/game_ballistics/README.md`, `gamecheck.py` | VERIFIED (method); `diff.md` itself is not stored, but `DP` (`data-provenance.tsv`) stores the comparison per weapon and input |
| AGS-17 hold-time model (185 m/s, x1.8) against in-game measurements | 67 measurements, 279-1931 m on level ground, agreement 0.7 % in v^2/g; RMS 5.34 m with refitted speed and top | `AGL:tools/game_ballistics/README.md`; `SB:RELEASE_NOTES.md` (#13) | UNVERIFIED (the 67 measurements are the owner's in-game data, not in the repositories) |
| Simulation with the game's values (muzzle that moves with the elevation) | solutions land within 1 mm; the UB-32 had missed by up to 22 m at short range before | `SC:CHANGELOG.md`, entry 45.7.0 | UNVERIFIED (a changelog statement) |
| Every input of the firing solution (velocity, gravity, motor, cap, rotation, drag, launch point, spread, lifespan, explosion, bore, zoom, limits, minimum distance, scale offset, hold model) of all 104 SB and 135 SC weapons: value used, game value, source asset, label | 2 704 labelled rows: VERIFIED 1 762, INFERRED 367, UNVERIFIED 53, ASSUMED 522; 0 unexplained differences from the game after one fix: the projectile lifespan (`InitialLifeSpan`), which the 108 generated direct-fire weapons of SC had as the default 100 s and SB lacked, is now the game's 4-40 s in both apps; weapons inherited from the upstream table, fitted or from mods are named in `DP` section 6 | `DP`, `AGL:tools/game_ballistics/provenance.py` (run on the existing dump, build 26005357) | VERIFIED† for the equalities; the labels INFERRED / UNVERIFIED / ASSUMED are the point of the table |
| Launch heights of vehicle mounts | taken from the game files for AGS-17, MK19, SPG-9 on listed vehicles | `SB:RELEASE_NOTES.md` | VERIFIED (file data); not checked in game, see section 10 |

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
map (Yehorivka, 48.6 + 13.0 MB) is ready 3.3 to 3.7 s after the setting is turned on and Chora (46 million columns) 4.2 to 4.4 s; the browser's
process tree grows by 1.4 GB (Yehorivka) and 1.8 GB (Chora) (`volume_check.mjs`, engine/README.md "Files served for each map").

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
was chosen. The share sent to the exact pass is 34 % / 22 % at margin 0 against 45 % / 41 % at 0.6 m. 0.6 m is kept because the
published region and the file served today use it; a margin of 0 with 150 m regions was not run (not run on Fallujah either: 45.3 M
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

## 10. Limitations and owner decisions

| Item | Status | Source |
|---|---|---|
| No penetration or through-obstacle calculation, by design | owner decision 2026-11-04 | `#22`, "Owner decisions" 1 |
| Windows: open (no glass, where players can enter) are holes in the geometry and stay holes; closed ones belong to non-playable apartments and are solid; no special glass logic | owner decision | `#22`, decision 2; `CS` section 1 |
| Doors: fully open or absent, so a doorway is always a hole; door leaves not modelled | owner decision | `#22`, decision 2 |
| In-game collision tests T1-T9 | cancelled (O1) | `#22` |
| Which trace (complex or simple) projectiles use; water; foliage vs mortar | UNVERIFIED | `CS` sections 3, 7 |
| Launch heights of the vehicle mounts without data (MK19 M1117, RHIB; AGS-17 on Kozak-2M1 and RHIB) | not measured in game; Squad Ballistics issue #12 | `SB:RELEASE_NOTES.md`; `#22` O2 |
| Launch height of the stationary AGS-17, MK19, SPG-9 (#13): files say 0.347 / 0.368 / 0.637 m, entries use 1 m | unchanged; the 67 measurements cannot tell 0.347 from 1 m (RMS 5.34 m both) | `SB:RELEASE_NOTES.md` |
| C90-CR, DZJ-08, RPG-28: values from the game files, no in-game shots | not measured | `#22` O2; `SB:RELEASE_NOTES.md` (#9) |
| QLZ87 beyond 400 m | not measured | `#22` O2 |
| GPU timings | none: the WGSL kernel was timed on SwiftShader (a CPU, 7 200 and 11 400 segments/s on a loaded host on 2026-11-05, about 19 000 on an idle one before); item C9 is open | `E-README`; `#22` C9 |
| The voxel layer finds about half of the openings on Fallujah (49 %), 29 % on Kohat, 12 % on Logar | measured, section 7.2 | `V-README` |
| Voxel layer is conservative by up to a voxel diagonal; false blocked grows with density | measured | `V-README`, `E-README` |
| Screens other than 16:9 | out of scope (owner decision); the program warns once | `SB:RELEASE_NOTES.md` (#10) |
| Ground truth for terrain: Training server logs, ground traces only | single reference | `H-README` |
| No client pak used; no decryption of the encrypted pak index | scope and licence decision | `CS` section 8 |
| Repositories are private; public release allowed from 2027 | owner decision | task statement |

## 11. Native rules (status)

`NR` (static disassembly of the server binary, owner's installed copy, nothing run; merged into `dev` as `7438c08`)
exists and the figures of section 9.2 that depend on it are cited to it. Its own labels: deployable damage rule, engine radial law, event construction, explosion-to-structure distance, vehicle table:
VERIFIED; `ImpactDamageToApply` path and secondary explosion: INFERRED / NOT RECOVERED; dynamic MOA (AGS-17, MK19,
QLZ87): PARTLY RECOVERED. The static data are verified (curve `FC_MOACurve_GenericGMG`, 15 MOA at 0 s to 50 MOA at
0.75 s, cycle times 0.15 / 0.171 / 0.125 s), how the curve input grows and decays is NOT RECOVERED (`NR` section 2);
the AGS-17 group-size test is the smallest measurement that settles it.

## 12. PENDING tables (filled by the final numbers)

| Table | Content | Produced by | Status |
|---|---|---|---|
| Reverse-position heatmap checked against the exact tracer on a target inside a building: share of heatmap cells wrong, false clear / false blocked, time per heatmap | | `#22` item C5 | PENDING |
| Map coverage: `.vcol` built / 25, build time and size per map, `build_all.log` without FAILED | 25 of 25 built and published (sizes in section 4; build times per map are not tabulated) | `#22` items B2, B5 | VERIFIED for sizes and publication, build times PENDING |
| Heatmap and DDA timings on a real GPU | | `#22` item C9 (a GPU on `tk104`, otherwise "not measured") | PENDING |
| 2D damage/splash footprint on the live site | | `#22` item C6 | PENDING |

## 13. Reproduction

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
| Whole release bundle | `AGL`: `tools/release/build_release.sh` (manifest with commits, versions and SHA-256) |
