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
| LOS pairs judged wrong by the exact reference (3 000 eye-level pairs, 10-60 m, 600 m window) | 9.5 % | 8.4 % | **6.2 %** |
| same, ignoring pairs that flip when the segment moves 0.25 m ("grazing") | 5.1 % | 4.0 % | **1.9 %** |
| false CLEAR (shot/sight passes a wall, building, deck that is there) | 144 | **2** | 16 |
| false BLOCKED (blocked where it is clear) | 141 | 251 | 169 |

The 1.0 m and 0.5 m columns are separate runs on different random pairs; the heightmap column is the 0.5 m run
(the 1.0 m run: heightmap 8.7 % / 5.2 % grazing-free, 134 false clear, 127 false blocked).

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
* Triangle winding is consistent (outward, signed volume > 0 on 332 of the 333 sampled meshes that enclose a volume; 65 more are open shells), which
  gives a free floor/ceiling/wall classification per sample.

## Representation

* Terrain: unchanged landscape heights (+ the hole flag), 1 m.
* Objects: **sparse voxel columns**. A voxel is occupied when a collision triangle blocking the query class
  has a sample point inside it (barycentric lattice at 0.45 x the smallest voxel edge, so thin walls and open
  shells mark the voxels they cross; no closed mesh is needed). Voxels that lie entirely at or under the
  landscape + 0.1 m are dropped. Up-facing samples are kept as a second set (floors) for standable surfaces.
* File `VCOL1` (`py/codec.py`): per occupied column the z-runs, varint packed, gzip. Browser decode with
  `DecompressionStream("gzip")` and about 40 lines (`js/vcol.mjs`, ~100 MB of typed arrays for Fallujah 0.5 m).
* Query: sample the segment every min(cell, dz)/3, test landscape then the column's runs (binary search of the
  column id). A 3D DDA would be exact and cheaper; the sampling is what was measured.

Sizes (Fallujah statics only): 1.0 x 0.25 m 1.57 MB (8.4 M voxels); 1.0 x 0.5 m 1.16 MB; 2.0 x 0.5 m 0.40 MB;
0.5 x 0.25 m 4.73 MB (20.1 M voxels); 0.5 x 0.5 m 3.44 MB. Trees add 0.44 M voxels at 1.0 m.

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
python py/world_tris.py <statics dir> tris.npz
python py/build_columns.py tris.npz <heightmap meta.json> out/fallujah_cols_0.5 0.5 0.25 visibility fallujah
python py/eval_los.py tris.npz out/fallujah_cols_0.5.npz <served heightmap dir> terrain.npz out/eval 3000 600
python py/cases_report.py out/eval/cases.csv tris.npz <statics dir> <served heightmap dir> 10
python py/size_table.py out/fallujah_cols_0.5.npz <heightmaps dir> fallujah
python py/check_ground_truth.py <markers.txt> Fallujah out/fallujah_cols_0.5.npz <heightmap dir> terrain.npz
node js/bench.mjs out/fallujah.vcol 20000
# 4. tests (synthetic bridge, thin wall, codec, collision masks)
python -m unittest discover -s tests
```

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
