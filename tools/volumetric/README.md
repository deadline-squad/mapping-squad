# Volumetric terrain data for SquadCalc (prototype: Fallujah)

A top-surface heightmap (one height per 1 m cell, `tools/heightmaps`) cannot say what is under a bridge deck,
behind a wall thinner than a cell, in a doorway, or under a tree crown. This directory builds, from the Squad
dedicated-server paks, a sparse **voxel-column** map of the collision that objects add above the landscape, and
measures it against exact triangle ray tests. The 1 m heightmap stays the fallback and is not touched.

Everything here reads only the owner's installed dedicated-server files (SteamCMD 403240, build 26005357). The
client pak is not used and no game client is needed.

## Result on Fallujah (3 005 x 3 005 m, build 26005357)

| | status quo: 1 m top-surface heightmap | voxel columns 1.0 m x 0.25 m | voxel columns 0.5 m x 0.25 m |
|---|---|---|---|
| LOS pairs judged wrong by the exact reference (3 000 eye-level pairs, 10-60 m, 600 m window) | 9.5 % | 8.4 % | **6.1 %** |
| same, ignoring pairs that flip when the segment moves 0.25 m ("grazing") | 5.1 % | 4.0 % | **1.9 %** |
| false CLEAR (shot/sight passes a wall, building, deck that is there) | 144 | **2** | 16 |
| false BLOCKED (blocked where it is clear) | 140 | 250 | 168 |

The 1.0 m and 0.5 m columns are separate runs on different random pairs; the heightmap column is the 0.5 m run
(the 1.0 m run: heightmap 8.7 % / 5.2 % grazing-free, 135 false clear, 127 false blocked).

Rerun on 2026-11-04 with the fixed `py/reference.py` (commit 9852b75; the earlier tracer skipped tiles that a segment
only clips at a corner, 22 of 20 000 Fallujah segments). Same inputs and seeds as the first run (3 000 pairs, 600 m
window, `fallujah_terrain_check.npz`). Only five counts moved, each by one pair: 0.5 m run, exact tracer blocks 2 217
pairs instead of 2 216, heightmap false BLOCKED 141 -> 140, voxels 0.5 m false BLOCKED 169 -> 168 (6.17 % -> 6.13 %
wrong); 1.0 m run, heightmap false CLEAR 134 -> 135, voxels 1.0 m false BLOCKED 251 -> 250. Every other figure above is unchanged,
so the conclusions stand. (With the landscape sampled from the extracted heights instead, `terrain/fallujah_exact.npz`, the
0.5 m run gives heightmap 9.6 % / 5.7 % grazing-free, voxels 5.6 % / 1.5 %, false clear 147 / 12; the tracer fix itself changes
nothing there either: old and new `reference.py` give identical `cases.csv`.)

Two more maps with a `.vcol`, statics columns 0.5 x 0.25 m, same method (3 000 pairs, 600 m window around the densest
columns, `terrain` sampled from the extracted landscape), fixed tracer. Kohat is dense (8 792 statics placements, 4.3 M
triangles), Logar is open rural terrain (4 098 placements, 2.6 M triangles):

| | Kohat heightmap | Kohat voxels | Logar heightmap | Logar voxels |
|---|---|---|---|---|
| pairs judged wrong | 2.3 % | 2.2 % | 7.9 % | 6.4 % |
| ignoring grazing pairs | 0.7 % | 0.5 % | 4.2 % | 2.0 % |
| false CLEAR | 40 | 3 | 76 | 2 |
| false BLOCKED | 28 | 63 | 162 | 190 |

The fix moves nothing on Kohat and on Fallujah (identical `cases.csv` before and after); on Logar it flips the grazing
flag of one pair (grazing-free 4.23 % -> 4.20 % heightmap, 2.00 % -> 1.97 % voxels).

### Windows, doorways and interiors (`py/eval_openings.py`)

Eye-level segments between points found by vertical reference rays (inside = floor with a ceiling within 6 m and the served
top surface above it, outside = open sky), decided by the exact tracer; up to 120 cases per category, seed 11, 600 m window,
voxels = the full `.vcol` of the map (statics and trees). Share of cases on which the model gives the reference answer:

| category (truth) | Fallujah heightmap / voxels | Kohat heightmap / voxels | Logar heightmap / voxels |
|---|---|---|---|
| opening: inside -> outside, clear | 0 % / 49 % (105) | 0 % / 35 % (51) | 0 % / 12 % (101) |
| room_clear: same roof, clear | 0 % / 73 % (78) | 0 % / 84 % (120) | 0 % / 65 % (120) |
| wall: inside -> outside, blocked | 100 % / 100 % (120) | 100 % / 99 % (120) | 100 % / 100 % (120) |
| room_partition: same storey, blocked | 100 % / 99 % (120) | 100 % / 98 % (120) | 100 % / 99 % (120) |
| room_floor: other storey, blocked | 100 % / 100 % (120) | 100 % / 100 % (120) | 100 % / 100 % (120) |

(n in brackets.) The heightmap treats every roofed space as solid, so it never sees a window or doorway; the voxels find
about half of the openings on Fallujah and fewer on Kohat and Logar. No openings numbers had been recorded before this rerun; the evaluation with the old `reference.py` gives
byte-identical case files on all three maps, so the tracer fix changed none of them.

| file (gzip), whole map | 7.5 MB PNG | 1.6 MB | 4.7 MB (+ trees) |
| decode (Node 26) / one 40 m segment test | - | - | 322 ms / 28 us |

The voxel model is conservative by half a voxel: its false blocks all lie 0.05-0.55 m from real geometry
(checked on 25 cases), the heightmap's false clears do not. Details, the case list and the method are below.

## What is in the game files (Fallujah, all maps alike)

Verified by `extractor inventory` (export counts per level) and by reading the cooked data:

* Static meshes: 44 452 placements (13 856 components), 72.1 M collision triangles, 99.98 % complex
  (`CTF_UseComplexAsSimple`: the render mesh is the collision). 
* Collision channels per placement (`BodyInstance`): Visibility / Projectile / Pawn responses differ. 3 012 of
  44 452 placements block nothing (NoCollision or every channel Ignore); 36 do not block Projectile. The
  heightmap pipeline's `blocks()` only reads CollisionEnabled and the profile name, so 2 852 road spline meshes
  that Ignore every channel are still rasterised as solid (centimetres on the ground: harmless, but wrong).
* Foliage (HISM) is not in the heightmap pipeline. 274 708 foliage instances in Fallujah, 11 616 with BlockAll:
  date palms, olive, acacia, almond (trunk capsule + one convex crown hull) and 6 315 small rocks. In the served
  heightmap 44 532 cells have such collision more than 0.5 m above the heightmap, up to 13 m (median 5.5 m).
  Two palm types fail to load because the export name differs in case from the file name (`foliage` mode of the
  extractor resolves paths case-insensitively and still fails on 2 of 9 Fallujah tree meshes).
* Landscape holes: the cooked heightfield carries a uint8 material index per quad; 0xFF is a hole. Fallujah has
  323 hole quads (the Euphrates), all maps 0-0.2 % (Sanxian 32 725 quads). Not a volumetric driver.
* No nav-mesh tile data (`ODKRecastNavMesh` actors exist, no data chunks), no distance fields, no voxel or
  visibility data. `*_BuiltData` assets (lighting) exist for 44 maps. Level instances only reference the art
  sublevels already read. `PrefabActor`s (74) reference merged meshes that are already among the statics.
* Missing against the client: texture pixels (`.ubulk` absent), so no landscape layer weights. Collision and
  meshes are complete for what the server simulates. Reading the client pak would be a different licence
  question (the Steam EULA forbids decompiling and deriving works) and was not done.
* What the collision means for projectiles (channels, glass and windows, interiors, materials, in-game test
  protocol): [`docs/collision-semantics.md`](docs/collision-semantics.md) ([ru](docs/collision-semantics.ru.md)).
* Damage of shells to player-built structures (FOB radio, HAB, HESCO, sandbags, bunkers): health, per-damage-type multipliers,
  ammunition fields and what the data lacks: [`docs/structure-damage.md`](docs/structure-damage.md) ([ru](docs/structure-damage.ru.md)),
  data in `data/structure_damage.json`.
* Rules that are native C++ and were read from the dedicated-server binary (damage to a deployable, the explosion distance, the
  weapon MOA path; what could not be recovered and the in-game measurement that would settle it): [`docs/native-rules.md`](docs/native-rules.md)
  ([ru](docs/native-rules.ru.md)), formulas in `semantics/native_rules.py`, pinned by `tests/test_native_rules.py`.
* Triangle winding is consistent (outward, signed volume > 0 on 332 of the 333 sampled meshes that enclose a volume; 65 more are open shells), which
  gives a free floor/ceiling/wall classification per sample.

## Representation

* Terrain: unchanged landscape heights (+ the hole flag), 1 m.
* Objects: **sparse voxel columns**. A voxel is occupied when a collision triangle blocking the query class
  intersects it: exact conservative surface voxelisation (`py/columns.py`), so every voxel a triangle passes through is
  marked, however small the part inside it, and thin walls and open shells mark the voxels they cross; no closed mesh is
  needed. Per triangle the grid rows its y-extent touches, in each row the columns between the x-extent of the triangle cut
  by that row, and per candidate cell the z-range of the triangle cut by the cell's rectangle (a voxel is the half-open box
  `[low, high)` of `Grid.keys`, so a triangle exactly on a voxel face belongs to the voxel above/beside it only). Triangles
  outside the grid are skipped and a huge triangle costs one pass over the cells it covers inside the grid, so meshes reaching
  tens of km beyond the map (Tallil mesh 774) cost nothing. Voxels that lie entirely at or under the
  landscape + 0.1 m are dropped. The facing of each triangle (up: floors, down) is kept as a second set for standable surfaces.
* File `VCOL1` (`py/codec.py`): per occupied column the z-runs, varint packed, gzip. Browser decode with
  `DecompressionStream("gzip")` and about 40 lines (`js/vcol.mjs`, ~100 MB of typed arrays for Fallujah 0.5 m).
* Query: sample the segment every min(cell, dz)/3, test landscape then the column's runs (binary search of the
  column id). The measurements below use this sampling. An exact voxel-column DDA now exists in the engine
  (`engine/src/voxel.rs`, WGSL twin `engine/wgsl/voxel.wgsl`); its parity is in the next section.

Sizes (Fallujah statics only): 1.0 x 0.25 m 1.57 MB (8.4 M voxels); 1.0 x 0.5 m 1.16 MB; 2.0 x 0.5 m 0.40 MB;
0.5 x 0.25 m 4.73 MB (20.1 M voxels); 0.5 x 0.5 m 3.44 MB. Trees add 0.44 M voxels at 1.0 m.

## Exact voxel-column DDA (engine)

`engine/src/voxel.rs` in the SquadCalc repository decodes `VCOL1` and answers a segment with the first occupied voxel
by a 2D Amanatides-Woo walk over the columns (per column a jump to the first run in the segment's height range), in
Rust (native and wasm) and in WGSL. It sees every voxel the segment touches; the sampled walk above steps over corners.
Checked on 100 000 random segments per map, inside the densest 1 km window, at least 0.25 m above the landscape;
exact = BVH over the Visibility triangles of the same layers (the voxel file and the triangles agree: 0 file voxels
missing from a rebuild, 0 above-ground rebuilt voxels missing from the file). Grazing = the exact answer flips for a
0.25 m shift.

| 100 000 segments | Jensen (statics, 117 KB) | Kokan (statics + foliage, 789 KB) |
|---|---|---|
| DDA clear, sampled model blocked | 0 | 0 |
| DDA blocked, sampled model clear (chord under one step) | 101 | 193 |
| exact blocked / clear | 29 732 / 70 268 | 12 709 / 87 291 |
| false CLEAR (14 / 9 grazing) | 129 | 83 |
| false BLOCKED (2 637 / 3 840 grazing) | 3 948 | 8 331 |
| wrong, all / without grazing | 4.08 % / 1.43 % | 8.41 % / 4.57 % |
| WGSL f32 (SwiftShader) wrong, all / without grazing | 4.08 % / 1.43 % | 8.41 % / 4.56 % |

False blocked: a marked voxel can be entered up to a voxel diagonal from the surface (every not-grazing case overlaps a
triangle). False clear: the voxel at the exact hit is empty in the file. The first builder (a sample lattice, 129 / 83 cases)
lost clipped corners, a triangle vertex and half of each lattice; the exact voxelisation marks every voxel a triangle meets
and has 0 false clear on the same 100 000 segments (false blocked 3 948 -> 4 039 on Jensen, 8 331 -> 8 508 on Kokan;
wrong 4.08 -> 4.04 % and 8.41 -> 8.51 %; voxels 673 122 -> 723 221 and 2 007 949 -> 2 198 643; .vcol 112 531 -> 85 476 B and
789 376 -> 696 798 B; issue deadline-squad/deadline-squadcalc#23).
Reproduce and details: `engine/README.md`, section "Voxel columns".

## Precision pass: exact triangles near a target

The voxel walk blocks segments that pass up to a voxel diagonal from a surface (false blocked) and misses hits in voxels
the sampling lost (false clear). `py/build_region.py` writes one small file per target (`RTRI1`: the square
`centre +- 150 m`, the Visibility triangles of the `world_tris.py` shards that a re-checked segment can hit, shared
vertices at 0.1 mm, varint + gzip); the engine (`engine/src/precision.rs`) answers the parts of a segment outside the
square by the voxels, and the part inside by the exact triangles when it comes within 0.6 m (whole voxels, rounded up)
of an occupied voxel. Same 100 000 segments as above, 16 regions per map, target = end of the segment (Fallujah: statics + foliage, 3 GB per process, regions answered one at a time, see `engine/README.md`):

| 100 000 segments | Jensen voxel / precision | Kokan voxel / precision | Fallujah voxel / precision |
|---|---|---|---|
| false CLEAR | 129 / 8 | 83 / 4 | 494 / 35 |
| false BLOCKED | 3 948 / 279 | 8 331 / 858 | 5 609 / 409 |
| wrong, all / without grazing | 4.08 % / 1.43 % -> **0.29 % / 0.10 %** | 8.41 % / 4.57 % -> **0.86 % / 0.47 %** | 6.10 % / 2.60 % -> **0.44 % / 0.17 %** |
| sent to the exact pass | - / 42.0 % | - / 37.0 % | - / 60.1 % |
| region file, min / median / max | 57 B / 100 KB / 5.0 MB | 1.04 / 2.48 / 3.52 MB | 6.48 / 15.9 / 26.0 MB (total 239 MB) |
| time per segment, one thread | 7.7 / 8.9 us | 12.1 / 14.4 us | 69.8 / 50.0 us (load average ~20, regions one at a time: not comparable with the others) |

With the exact triangles of the whole window available the pass has 0 wrong answers at margin 0.6 m on Jensen and Kokan
(0.3 m leaves 1 false clear on Kokan); on Fallujah this was not run (the window holds 45.3 M triangles, over the 3 GB cap). Details, the margin table and how to run it: `engine/README.md`, "Precision pass".

```sh
python py/build_region.py <map>.vcol out/regions --centre X Y --centre X Y --radius 150 --margin 0.6 <tris.npz>...
```

## Reproduce

Python runs in the `squadcalc-heightmaps-py` image (`docker build tools/heightmaps/py`), the extractor in the
dotnet SDK image; both as in `tools/heightmaps/heightmaps.sh`. `py.sh`-style wrapper: mount this directory at
`/vol`, `tools/heightmaps/py` at `/hm`, `PYTHONPATH=/vol/tools/volumetric/py:/hm`.

```sh
# 0. game data (once; the heightmaps pipeline's `extract` writes statics/ and landscapes/)
tools/heightmaps/heightmaps.sh extract
# extractor with inventory / dump / foliage modes (CUE4Parse commit as in heightmaps.sh):
#   dotnet build -c Release -o bin -p:CUE4ParseDir=<cue4parse> tools/volumetric/extractor
#   SquadExtract <paks> inventory Fallujah out.json     # export-type counts per level
#   SquadExtract <paks> foliage Maps/Fallujah_City/ out/foliage/fallujah
# 1. one map, end to end (statics + foliage -> <slug>.vcol); ~1 h for a dense map
tools/volumetric/build_map.sh fallujah 0.5 0.25
# 2. all maps, smallest first (Skorpo's 1 100 m height range needs dz 0.5: build_all.sh 0.5 0.5 skorpo)
tools/volumetric/build_all.sh 0.5 0.25
python py/status_table.py                      # markdown table of built / running / failed / queued maps
# 3. measurements
python py/world_tris.py <statics dir> tris.npz       # statics: one file; add a triangle count (e.g. 20000000) to write shards tris.<i>.npz
python py/build_columns.py tris.npz <heightmap meta.json> out/fallujah_cols_0.5 0.5 0.25 visibility fallujah
python py/eval_los.py tris.npz out/fallujah_cols_0.5.npz <served heightmap dir> terrain.npz out/eval 3000 600
python py/eval_openings.py <slug> tris.npz out/<slug>_cols.npz <slug>.vcol <served heightmap dir> out/openings.json
python py/cases_report.py out/eval/cases.csv tris.npz <statics dir> <served heightmap dir> 10
python py/size_table.py out/fallujah_cols_0.5.npz <heightmaps dir> fallujah
python py/check_ground_truth.py <markers.txt> Fallujah out/fallujah_cols_0.5.npz <heightmap dir> terrain.npz
node js/bench.mjs out/fallujah.vcol 20000
# 4. tests (synthetic bridge, thin wall, codec, collision masks)
python -m unittest discover -s tests
```

## Publishing to the site and the browser check

The SquadCalc page (`src/js/volumeWorker.js`, setting *Object volumes in the line of fire*) reads two files per map from the
served heightmaps directory, announced by a `volume` entry in the map's `meta.json`:

```sh
# landscape-only heights on the served heightmap's grid (terrain.bin, TER1), then both files and the meta.json entry
python py/terrain_raster.py <slug> <served meta.json without the volume entry> <slug>/terrain.bin   # in the py image, as build_map.sh
cp -a ~/apps/squadcalc/dist/heightmaps/<slug>/meta.json ~/apps/squadcalc/dist/heightmaps/<slug>/meta.json.bak.<date>-volume
python py/publish_volume.py <slug> <slug>/<slug>.vcol <slug>/terrain.bin ~/apps/squadcalc/dist/heightmaps
```

The served `meta.json`, not the older one under `~/data/squad-heightmaps`, gives the grid (Kokan and Chora are 0.5 m there).
All 25 maps were published this way on 2026-11-05 (the exact conservative builds): `volume.vcol` 0.1 to 48.6 MB and `terrain.bin` 0.4 to 13.0 MB
per map, the table is in SquadCalc `engine/README.md`, "Files served for each map". The meta.json of each map was copied to
`meta.json.bak.20261105-volumes2` first, the replaced lattice-built files were moved out of the served directory to
`~/data/volumetric/old-lattice-served/<slug>/`, and an existing `terrain.bin` was reused where its header (origin, cell,
width, height) equals the served meta.json grid. `terrain_raster.py` builds its levels in int32 and row blocks, so Chora
(8129 x 8129 vertices) fits in 4 GB (`PY_MEM=4g`); its output is byte-identical after gunzip to the earlier encoder's.
`tools/browser_check/volume_check.mjs <site URL>` checks the result in Chromium: no request before the setting is on, the
files and the engine load, the parity segments of `volume_cases.json` (`py/pick_volume_cases.py`: Jensen and Kokan, walls
block, doorway and window openings pass), the landscape against the heightmap, the line of fire and the fire coverage with
the layer, and a map without volume files.

### Precision regions for the position heatmap

A target of the reverse-position heatmap (SquadCalc 45.26.0, `engine/README.md` "Position heatmap") is traced with the exact
triangles of its region (`RTRI1`, `py/build_region.py`, see the engine README) when `meta.json` lists one that holds it at least
50 m from the edge of its square. `py/publish_regions.py` puts files next to the volume layer and lists them; it copies
`meta.json` to `meta.json.bak.<date>-regions` first, reads the square from each file's header, and keeps the entries of the files
it was not given (`publish_volume.py` keeps the list too):

```sh
python py/publish_regions.py <slug> ~/apps/squadcalc/dist/heightmaps <region.rtri> [<region.rtri> ...]   # no dependency, plain python
```

Under `/heightmaps/<slug>/regions/<file>`, requested as `?v=<generated>` and checked against `sha256` like the other files. Published:
Jensen `region_221_-229.rtri` (1 931 297 bytes, 2026-11-04), the region the heatmap was validated with against the exact triangle
tracer (`engine/tools/js/heatmap_validate.mjs`; `tools/browser_check/heatmap_check.mjs` repeats the comparison in the browser).
A region costs its download and, in the worker, the build of the hierarchy of its triangles (Jensen's: 7 to 10 s in Chromium on a loaded host); build
others only for targets someone validates: the densest Jensen square (`region_-29_-229.rtri`, 5.04 MB, 2.78 M triangles) took 31 s to load
in Node's wasm on the same host.

## How the gain was judged (independent of the builder)

`py/reference.py` shares no code with the builder: exact Moller-Trumbore tests of the segment against the
collision triangles themselves (tile-bucketed), landscape sampled every 0.1 m. Standable points are found by
vertical reference rays (up-facing hit, 1.9 m headroom), not from the voxels. Both models are scored against
that, on identical pairs. The triangles come from the same cooked-Chaos reader as the heightmaps (so a parse
error would be shared); the reader was validated against SquadHeight's SDK trace (98.9 % recall, 99.5 %
precision on Skorpo, `tools/heightmaps/README.md`). Ground truth from logs: 29 Fallujah markers with real ground
Z (`check_ground_truth.py`): the heightmap and the voxel floors both agree within 0.3 m on 28; all 29 stand on
open ground, so they prove no regression but cannot show the gain (none is under a roof or deck). Five
hand-grenade spawn lines exist for Fallujah in the squad2 logs: too few to use.
