# Precise heightmaps from the game files

SquadCalc's own heightmaps are 8-bit (up to 2.1 m per level). These are built from the Squad
dedicated server paks and served by the Deadline SquadCalc in `/heightmaps/<map>/`
(`src/js/squadHeightmaps.js` falls back to the 8-bit ones when a map has none).

Each `heightmap.png` is a 16-bit grayscale PNG on SquadCalc's grid (minimap bounds, `resolution_m` of `meta.json`
per pixel: 1 m, 0.5 m for Chora and Kokan, see "Grid size" below; row = world Y min→max, col = world X min→max);
height above the map's lowest point = `value * z_step_m` from `meta.json`, which also holds the sources and
agreement statistics.

## WebP form

Next to each PNG is a `heightmap.webp` of the same levels: lossless WebP, an RGB image with the high byte of the 16-bit
level in red and the low byte in green (`py/heightmap_webp.py`). The browser decodes it natively, in about half the time
of the PNG in JavaScript. It holds the PNG's step; heightmaps built before 2026-11-10 coarsened it to 1 cm (except on
Skorpo and Chora), up to 0.5 cm off on bare ground.
At the PNG's step the WebP is 68 to 85 % of the PNG (262.6 against 336.9 MB for the 25 maps built on 2026-11-10;
the served ones of 2026-10-30, coarsened, take 183.2 MB). `meta.json` announces it:

* `format: "webp-rg16"`, `generated` (UTC build time: the page requests the files with `?v=<generated>`, so a
  rebuild must change it) and `webp: {file, encoding, z_step_m, levels_sum}`; `levels_sum` is the sum of all
  levels modulo 2^32, which the page checks after decoding, so a browser that alters canvas pixels uses the
  PNG instead of showing wrong heights;
* `z_step_m` is the PNG's step, and the WebP's own `z_step_m` the same.

`heightmaps.sh build` writes both files. For heightmaps built before, `heightmaps.sh webp` converts them from the
served copy and checks each result (`py/convert_webp.py`: the WebP decoded again equals the PNG in every pixel),
`heightmaps.sh deploy-webp` copies the WebP files next to the PNGs (nothing changes for a page), and
`heightmaps.sh switch-webp` then replaces each map's `meta.json`: the switch, last.
In a browser, `tools/browser_check/heightmap_exact.mjs` compares the WebP and PNG paths of the site's worker.

## Grid size

The landscapes of Chora and Kokan have a vertex every 0.5 m (landscape scale 50); every other map's vertices are 1 m or
more apart. `py/maps.py` holds the cell size of each map (`CELL_M`, default 1 m) and the pipeline builds the map on that
grid: samples at the bounds' min corner and every cell from it (Chora 8129 x 8129, Kokan 4993 x 4993), the landscape and
the static meshes sampled at those points, `meta.json` `resolution_m` 0.5. SquadHeight only exports a 1 m grid, so on a
finer grid its surface is read as follows (`build_heightmap.upsample_surface`): over the landscape each cell takes the
nearest SquadHeight sample's height above the terrain on top of its own terrain (a building keeps its height, a slope
does not turn into steps); outside the landscape it is read along the game's triangles. `fuse` is the same code and its
statistics keep their meaning (for example `terrain_rms_diff_m` is unchanged, the object cell counts are four times as
many). SquadCalc takes the grid from `resolution_m` and the image size, so no page setting names the map.

Against the landscape's own vertices (`py/compare_native_vertices.py`, terrain only, read with the page's triangle
rule), 1 m grid against 0.5 m grid:

| map | vertices | 1 m RMS / p99 / max | 0.5 m RMS / p99 / max |
|---|---|---|---|
| Chora | 22.0 M | 8.91 cm / 9.37 cm / 31.4 m | 0.000 / 0.000 / 0.00 cm |
| Kokan | 23.6 M | 0.89 cm / 3.12 cm / 114 cm | 0.017 / 0.065 / 1.59 cm |

The files are three times as big (heightmap.webp: Chora 4.9 → 14.2 MB, Kokan 2.6 → 6.4 MB; 171 → about 184 MB for the
25 maps) and the worker decodes them in about three times the time (Chora 0.6 → 1.8 s, Kokan 0.2 → 0.7 s in Chromium),
so a map is still loaded only when it is selected. `tools/browser_check/heightmap_native.mjs` loads these maps in the
page and checks their grid, decode time and page heights at the game's vertices.

## Sources and fusion

| Layer | Source | Precision |
|---|---|---|
| Terrain | landscape collision heightfields (`LandscapeHeightfieldCollisionComponent` cooked Chaos heightfield) of the map's landscape levels, placed with the landscape actor's transform (location, yaw, scale) | 16-bit per tile, ~0.3 mm; grid 1–1.2 m |
| Objects | collision of every static mesh placed on the map (`StaticMeshComponent`, instanced components, spline meshes with their bent BodySetup): complex triangle meshes from the cooked Chaos data, else the simple shapes (boxes, spheres, capsules, convex hulls) | the collision itself, sampled at each grid point |
| SDK surface | [SquadHeight](https://github.com/Metroseksuaali/SquadHeight) 1.3.0: top-most trace of the Squad SDK collision | 1.6 cm |
| Placements | which of SquadHeight's objects the game has (`py/evidence.py`): the collision boxes of the server's static mesh placements, and the mesh placements that the client scene shows (`SquadExtract scene` of `tools/maprender`, `$SCENES`) | a box and 1 m around it; the mesh's own surface, within 1 m, for a placement wider and longer than 800 m |

Fused height: the highest of the game terrain, the game objects, and SquadHeight where it rises
0.5 m above the game terrain (an object the SDK has) and a placement of the game explains it.
Outside the game landscape SquadHeight's surface is used.

### Which of SquadHeight's objects are taken

SquadHeight was traced in the Squad SDK, whose version of a map is not the installed build's, so what it holds above the
terrain is a height of the game only where the game has something there. The server's static collision cannot say so alone:
`SquadExtract statics` has no foliage (trees, rocks) and none of the components whose mesh is set in their Blueprint (the lake
planes of Manicouagan, the houses of Al Basrah's village clusters, Fools Road's barns and village houses), and for those
SquadHeight is the heightmap's only source. `py/evidence.py` therefore asks both builds. A grid point keeps SquadHeight's surface
when

* it lies under the collision box of a static mesh placement of the server, or under the box of a mesh placement that the client
  scene shows (static, instanced, foliage and spline meshes, Blueprint components, water planes; not hidden, not in a `_Vista`,
  `/Coop/`, `/Tutorials/` or editor level), 1 m around the box included, and its height lies between the box's bottom and top,
  1 m beyond them included: a block standing on a road mesh or over the sea is not explained by them;
* or a mesh of the client scene wider and longer than 800 m passes within 1 m of it, above or below. Such a placement is no
  object over a point (its box holds the whole map) but terrain or water that the game shows: Kamdesh's background mountains
  `Mountain1Final`, whose foot stands on the landscape and which SquadHeight follows to 0.25 m over 381 093 m2; the ocean plane,
  143 km wide; the lakes. A sky sphere passes near nothing.

Everywhere else SquadHeight's object is one that only the SDK's map has, and the game's own surfaces stand: its terrain, its
static collision, and the terrain or water of a client mesh wider than 800 m under SquadHeight's surface there (48 of Al Basrah's
blocks' points stand in the river: they take the water's level, not the river bed under it).
`meta.json` counts those points (`stats.sdk_unexplained_cells`) and names the builds (`sources.sdk_objects_kept`). A map without a
client scene keeps every object of SquadHeight, as before, and `build` prints that.

Measured on the 25 maps, the served heightmaps of server build 26005357 against this rule with the client scenes of build
26234431: SquadHeight stands 0.5 m and more above the terrain at 28 515 530 grid points; a placement explains 27 949 202 of them
(20 946 035 only one of the client: 18 713 366 the water and the mountains of a mesh wider than 800 m, the rest foliage and
Blueprint components; 25 566 only one of the server). Of the 566 328 others, 554 201 lie on the server's own static collision at
the same height and do not change (Gorodok 405 962, Narva 148 238: a mesh wider than 800 m that SquadHeight traced too), and
12 127 points, 11 480 m2, change:

| Map | Points lowered | m2 | of them by 2 m and more | Largest, m (median) | What SquadHeight held there, and what stands now |
|---|---|---|---|---|---|
| Al Basrah | 11 226 | 11 226 | 10 086 | 22.48 (6.17) | the background city of the `_Vista` level along the map's edge (largest regions 1 311, 1 138 and 1 108 m2, 3.5 to 6.6 m above the ground on the median and up to 13.4 m) and walls in open sand; the server has that level with collision switched off on 300 of its 338 static mesh components. Now the terrain (11 166 points), the river's water (48) and the server's collision (12) |
| Chora (0.5 m grid) | 792 | 198 | 259 | 8.44 (1.59) | strips 1.4 and 3.5 m above the terrain on the median (the largest 57.5 and 30 m2) and objects above the server's collision of a river plane; now the terrain (473 points), that collision (254) and the water (65) |
| Kokan (0.5 m grid) | 71 | 17.8 | 59 | 9.41 (5.91) | objects that the game's collision has lower (its three largest regions 6.9, 8.6 and 7.6 m above the ground on the median, the game's collision there at most 0.7, 3.1 and 6.4 m), which they now take (58 points; the terrain at 13) |
| Skorpo | 16 | 16 | 4 | 30.70 (0.61) | single points, and a tree crown 30.7 m above the terrain (3 m2) that no tree of the game reaches; now the terrain |
| Anvil | 17 | 17 | 0 | 0.72 (0.53) | single points 0.5 to 0.7 m above the terrain; now the terrain |
| Gorodok | 5 | 5 | 0 | 1.84 (1.15) | single points 0.5 to 1.8 m above the terrain; now the terrain |

The other 19 maps do not change. At every changed point the client's landscape collision (build 26234431, extracted like the
server's) is the server's (largest difference 0.00 m) and nowhere comes within 0.5 m of SquadHeight's surface, so none of it is
terrain of the game; no mesh of the client's own levels passes within 1 m of it either (on Al Basrah a mesh of the `_Vista` level
does at 4 299 of the 11 226 points: scenery the game shows and the server does not collide with).
`build` of the six maps writes exactly this: their heightmaps differ from the served ones at the points above, by the measured
lowering to 1 cm, and nowhere else but at 12 764 points of Gorodok, one 16-bit level (1.4 mm) lower, where the server's collision
holds SquadHeight's surface to the millimetre.

Checks (Squad build 26005357):

* game terrain vs SquadHeight on open ground: median difference 0.0 mm on every map, RMS 0.5–14 cm
  (`compare_squadheight.py`, `meta.json` → `stats`);
* game objects vs SquadHeight on Skorpo: recall 98.9 %, precision 99.5 %, heights within 0.5 m on
  99.75 % of the shared object cells (median 5 mm); 99.99 % of all cells within 0.5 m
  (`compare_objects.py`);
* SquadCalc's 8-bit heightmap of Skorpo is SquadHeight quantized to 2.09 m steps: error up to
  1.05 m (`compare_squadcalc.py`).

## Map inventory: what the server package can play

Evidence is the Squad dedicated server build 26005357 (`steamapps/appmanifest_403240.acf`): its `ServerConfig/LayerVoting.cfg`
and `LevelRotation.cfg`, `Manifest_UFSFiles_Linux.txt` (88727 `.uasset`/`.umap` entries, the same 88727 that the pak
index lists with `SquadExtract list`, so the install is complete) and the pak contents. A level is *playable* when it is in
`LevelRotation.cfg` and its gameplay layers (`Content/Maps/<dir>/Gameplay_Layers/<Layer_Id>.umap`, or the plugin's
`Content/Maps/Gameplay_Layers`) are shipped.

| Level | Layers in LayerVoting.cfg | of them with a layer `.umap` in the build | in LevelRotation.cfg | heightmap here |
|---|---|---|---|---|
| AlBasrah | 7 | 6 | yes | yes |
| Anvil | 4 | 4 | yes | yes |
| BlackCoast | 6 | 6 | yes | yes |
| Chora | 8 | 8 | yes | yes |
| Fallujah | 7 | 7 | yes | yes |
| FoolsRoad | 8 | 6 | yes | yes |
| GooseBay | 4 | 4 | yes | yes |
| Gorodok | 8 | 8 | yes | yes |
| Harju | 9 | 9 | yes | yes |
| Kamdesh | 5 | 5 | yes | yes |
| Kohat | 5 | 5 | yes | yes |
| Kokan | 7 | 6 | yes | yes |
| Lashkar | 7 | 7 | yes | yes |
| Logar | 4 | 4 | yes | yes |
| Manicouagan | 6 | 6 | yes | yes |
| Mestia | 5 | 5 | yes | yes |
| Mutaha | 6 | 6 | yes | yes |
| Narva | 8 | 8 | yes | yes |
| PacificProvingGrounds | 1 | 1 | yes | yes |
| Sanxian | 7 | 7 | yes | yes |
| Skorpo | 3 | 3 | yes | yes |
| Sumari | 7 | 7 | yes | yes |
| Tallil | 5 | 5 | yes | yes |
| Yehorivka | 9 | 9 | yes | yes |

* `LevelRotation.cfg` names 25 levels, one of which has no level files in the package and is not listed here; `Jensen` (Jensen's
  Range) is not among them (`ExcludedLevels.cfg` excludes `JensensRange`; its layers are in `ExcludedLayers.cfg`), so our 25 maps
  are the 24 playable levels of the table plus Jensen's Range.
* Layers named in `LayerVoting.cfg` without a `.umap` in the build: `AlBasrah_Insurgency_v1`, `FoolsRoad_RAAS_v2`,
  `FoolsRoad_RAAS_v3`, `Kokan_RAAS_v2` (the voting list is longer than the shipped layers; the maps themselves are complete).
  `Skirmish`/`Seed` layers commented out with `//` are not counted.
* **Not playable, a plugin descriptor only:** `Plugins/Expansions/{Aussie,EastAsia,Haiyan,MijinHighway,OperationDragonfly,
  OskilRiver,Saaremaa,Yehorivka_Remaster,PCG_Test}` are one `.uplugin` file each (no `.umap`, no asset), and so are the
  `Expansions/{Gorodok,Mestia,Narva,Yehorivka}` descriptors whose content lives under `Content/Maps`. `Content/Maps/Forest` is 42
  texture/material files without a level. None of these names is in `LayerVoting.cfg` or `LevelRotation.cfg`.
  The content-bearing plugins are `Al_Basrah` (347 files), `Expansions/BlackCoast` (353), `Expansions/Harju` (287) and
  `Expansions/SanxianIslands` (309).
* **Yehorivka_Remaster does not supersede Yehorivka.** The remaster plugin has no content in this build (one `.uplugin`
  file), and the nine playable Yehorivka layers stream `Maps/Yehorivka/Sublevels/070_Landscape/L_070_Landscape_Yehorivka`
  (`SquadExtract json <layer>.umap LevelStreamingAlwaysLoaded` on `Yehorivka_AAS_v1`, `_RAAS_v1`, `_Invasion_v2`; no
  streaming level names the remaster). That is the landscape `py/maps.py` extracts, so the Yehorivka data is current.
  It would become stale only when a build ships the remaster's content and its layers.

## Running

Requirements: Docker, the Squad dedicated server installed with SteamCMD (app 403240, anonymous),
the SquadHeight release unpacked (`heightmap_images_16bit_png.zip` and the `meta.json` files of
`heightmaps_1m_fullres.zip`), and for `build` the client scenes of `tools/maprender` (`maprender.sh scene`, which
needs the game client): `$SCENES/<map>` says which of SquadHeight's objects the game has.

```sh
tools/heightmaps/heightmaps.sh setup     # CUE4Parse at the pinned commit + cue4parse.patch, extractor, Python image
tools/heightmaps/heightmaps.sh extract   # landscapes and static meshes of every map (about 1 h)
tools/heightmaps/heightmaps.sh build     # fused heightmaps into $OUT (about 1–2 h); "build skorpo" for one map
tools/heightmaps/heightmaps.sh deploy    # replace the built files in the served SquadCalc, previous copy kept as heightmaps.bak.<date>
```

Paths are set with `SQUAD_DIR`, `SQUADHEIGHT`, `WORK`, `SCENES`, `CLIENT_DIR`, `OUT` and `DIST` (see the script header).
After a game patch: update the server with SteamCMD and the client scenes (`tools/maprender/maprender.sh scene`), then
`extract`, `build`, `deploy`; a new map goes into `py/maps.py` (its SquadHeight name and landscape levels).
`deploy` replaces in each served map folder only what `build` wrote for it (`heightmap.png`, `heightmap.webp` and the keys of
`meta.json`); the volume layer of `tools/volumetric` (`volume.vcol`, `terrain.bin` and the `volume` key of `meta.json`) stays,
and so do the maps `$OUT` does not hold. A map of `$OUT` that lacks one of its three files stops it before anything is touched.

## Interpolation: the game's triangles

The game's landscape collision splits every quad of four vertices into two triangles along the diagonal
from vertex (x, y) to (x + 1, y + 1) of the landscape grid. This was found with ground truth from the
server log (below): on points where the other diagonal would differ by more than 5 mm the diagonal above
is the closer one in 79 of 89 (17 of 20 above 2 cm), and it is Unreal's landscape render mesh diagonal.
`landscape.triangle_surface` reads it; SquadCalc's `getHeight` reads the served grid the same way (its quads
split from (row, col) to (row + 1, col + 1), the same diagonal in world axes), where it used bilinear
interpolation. `py/compare_interpolation.py <extract root> <heightmaps dir> <map>` measures a grid against the
game's surface at random points (terrain only). Bilinear against triangle on a grid whose nodes sit on the
game's vertices (Al Basrah, Fallujah, Gorodok, Harju, Kamdesh, Lashkar, Mestia, Mutaha, Narva, Pacific, Sanxian,
Sumari): RMS 0.3 to 2.2 cm and up to 0.2 to 1.1 m on the steepest quads, triangle 0.0 to 0.1 cm. On maps
whose vertices are not on the 1 m grid (Goose Bay, Jensen, Manicouagan, Tallil, Black Coast, Skorpo, Anvil, Chora, Kokan)
the grid itself is a resample of the vertices and the read is a small part of an error of 0.5 to 3 cm RMS.
On static objects the mesh heights are not triangle surfaces: in the object-dense 1 km window of Fallujah
(`py/compare_resolution.py`) the triangle read is 2 % worse than bilinear on object cells (RMS 0.951 against 0.931 m)
and equal on terrain, an accepted cost of being exact on terrain.

## Audit against the game server

`log_points.awk` turns dedicated server logs into anonymous lines `<MapFolder> <Kind> x y z` (world cm): placed map
markers, deployables at their placement, spawn points (the player capsule centre, 0.88 m above the ground),
explosions. Nothing else is copied; the sample comes from the Training server only.

```sh
cat SquadGame*.log | awk -f tools/heightmaps/log_points.awk | sort -u > points.txt
py/audit_ground_truth.py <heightmaps dir> <map> points.txt [--extract <extract root>] [--objects] [--csv table.csv]
```

It prints, for every point that does not agree, the logged Z, the served heightmap read bilinear / nearest / triangle,
the landscape surface, the highest static mesh above the point and the nearest object, with a verdict
(`ok`, `no-trace`, `sub-cell`, `grid-object`, `object`, `above-terrain`, `below-terrain`), then summaries per kind.
Result on the Training server's logs (build 26005357, served heightmaps; points that agree with the log or only
differ by the grid, within 15 cm): bilinear / nearest / triangle within 2 cm of the log on Fallujah 90 / 79 / 92 %
(p95 10.1 / 8.0 / 5.5 cm, 107 points), Goose Bay 92 / 60 / 92 %, Yehorivka 96 / 63 / 97 %, Black Coast 89 / 63 / 91 %.
Every Fallujah point more than 15 cm off (36 of 143) has a static mesh on it or beside it (a roof, wall, tent or
truck: `object`, `above-terrain`, `grid-object` name the mesh), or the log has Z = 0 (`no-trace`: markers the
server did not trace). The river bed at -44.20 m is the landscape's own flat floor (spawn points stand on it); the
water actor of Fallujah is a box volume at -48.43 m, not a collision plane.
`py/test_audit_ground_truth.py` tests it on synthetic grids (`python -m unittest test_audit_ground_truth`).
Kinds that are ground traces: placed markers except those with Z = 0 and the types logged at odd heights,
deployables, spawn points. `tools/direct_fire/precision_check.mjs` (B2) and `tools/browser_check/precision_browser.mjs`
check SquadCalc's read against the triangle rule; `tools/direct_fire/los_resolution.mjs` compares obstacle
verdicts for 1, 0.5 and 0.25 m grids written by `py/compare_resolution.py`.

Files:

* `py/compare_native_vertices.py` — the table above; `py/test_build_heightmap.py` — grid arithmetic and fusion tests
  (`python -m unittest test_build_heightmap`);
* `extractor/` — SquadExtract (C#, [CUE4Parse](https://github.com/FabianFG/CUE4Parse)): `list`,
  `landscape`/`extractall` (landscape collision), `statics` (static mesh placements and collision),
  `dumpall` (assets as JSON, for `tools/game_ballistics`), `dumpbytecode` (the same with the Kismet bytecode of
  every Blueprint function, for `tools/game_audit`), `features` (foliage, landscape splines and
  water actors, for `tools/maptiles`). `cue4parse.patch` keeps the cooked
  landscape collision that CUE4Parse skips.
* `py/heightmap_webp.py`, `py/convert_webp.py` — the WebP form above;
* `py/landscape.py` — cooked Chaos heightfield reader and landscape assembly;
  `py/objects.py` — static mesh collision rasterizer; `py/evidence.py` — the placements of the server and the
  client that explain SquadHeight's objects (`py/test_evidence.py`); `py/build_heightmap.py`, `py/build_all.py` —
  fusion and output; `py/maps.py` — SquadCalc map → SquadHeight name and landscape levels;
  `py/compare_*.py` — the checks above.
* `py/spline_mesh.py` — the deformation of a mesh along a spline segment as the engine does it, with the spline's scale,
  offset and roll (`py/test_spline_mesh.py`): the one implementation that `tools/maprender` and `tools/maptiles` draw their
  spline meshes with, and that `py/evidence.py` boxes them with.
* `py/audit_ground_truth.py`, `log_points.awk`, `py/compare_interpolation.py`, `py/compare_resolution.py`: the
  checks above.

## Topographic metrics

`py/topometrics.py` computes slope, aspect, profile and plan curvature, TPI, TRI, roughness, sky-view factor and openness
per cell from a heightmap (float64; Horn gradients and Zevenbergen-Thorne second derivatives, definitions and sign
conventions in its docstring); `py/topometrics_cli.py` writes `topometrics/<map>.json` (min, max, mean, std, percentiles,
slope class shares) and the Markdown tables `topometrics/README.md`. `py/test_topometrics.py` checks every metric against
a plane, a paraboloid and a sphere patch with exact slope, aspect and curvature (relative error below 1e-6):
`python -m unittest test_topometrics` in `py/` (numpy, scipy, Pillow; sky metrics need `rvt-py`, see `../maptiles/py/Dockerfile.relief`).


## Minimap corners and the grid (audit of 2026-11-05)

The in-game map grid starts (A1) at the north-west corner of the minimap. The corners are the two actors named by `MapTextureCornerZero` and `MapTextureCornerOne` in the `SQWorldSettings` of every gameplay layer (`Content/Maps/<map>/Gameplay_Layers/*.umap`); their root component's `RelativeLocation` is the corner in cm (UE axes: +X east, +Y south). `py/minimap_corners.py dump` reads them for the 219 layers of build 26005357, `table` reduces them to metres per map (`py/test_minimap_corners.py`). The game's grid lines have three levels, `W_SQMapGridLines` `GridLineLevels` scale factors 1, 3 and 9 (`UI/Widgets/Map/Grids/`), which is SquadCalc's 300 m keypad, 100 m and 33.3 m sub-keypads; the widget `W_SQMapBody` has a function `Map Corner Bounds`, the grid is laid out from the corners.

Game corners (min / max, m) against SquadCalc's image corners (`SDK_data.minimap.corner0/corner1`, normalised to min / max), the difference of each of the four edges (game minus image) and the verdict. "Layers that differ" are layers whose corners are not the map's usual ones (their own, smaller minimap for Skirmish and Seed layers, or a metre of difference).

| Map | Game min / max | maps.js min / max | Difference W / N / E / S, m | Largest, m | Verdict | Layers that differ |
|---|---|---|---|---|---|---|
| AlBasrah | -2000, -2000 / 2000, 2000 | -2000, -2000 / 2000, 2000 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | - |
| Anvil | -2040, -2040 / 1020, 1020 | -2040, -2040 / 1020, 1020 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | - |
| BlackCoast | -2300, -2127.47 / 2299.98, 2472.51 | -2299, -2127 / 2299, 2472 | -1.00 / -0.47 / 0.98 / 0.51 | 1.00 | image corners are the game's, rounded | Seed_v1 |
| Chora | -2464, -2664 / 1599.9, 1400 | -2464, -2664 / 1600, 1400 | 0.00 / 0.00 / -0.10 / 0.00 | 0.10 | image corners are the game's, rounded | Skirmish_v1 |
| Fallujah | -1315, -1545 / 1690, 1460 | -1315, -1545 / 1690, 1460 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | - |
| FoolsRoad | -1325.77, -1325.77 / 448.05, 448.05 | -1326, -1326 / 448, 448 | 0.23 / 0.23 / 0.05 / 0.05 | 0.23 | image corners are the game's, rounded | - |
| GooseBay | -2016.58, -2016.75 / 2015.23, 2015.03 | -2016, -2016 / 2015, 2015 | -0.58 / -0.75 / 0.23 / 0.03 | 0.75 | image corners are the game's, rounded | Seed_v1 |
| Gorodok | -2031.99, -2032 / 2032.01, 2032 | -2032, -2032 / 2032, 2032 | 0.01 / 0.00 / 0.01 / 0.00 | 0.01 | image corners are the game's, rounded | - |
| Harju | -2016, -2016 / 2016, 2016 | -2016, -2016 / 2016, 2016 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | - |
| Jensen | -2004, -2004 / 2004, 2004 | -2004, -2004 / 2004, 2004 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | - |
| Kamdesh | -2016, -2016 / 2016, 2016 | -2016, -2016 / 2016, 2016 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | - |
| Kohat | -2300, -2300 / 2317, 2317 | -2300, -2300 / 2317, 2317 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | - |
| Kokan | -1076.35, -1075.67 / 1420.14, 1420.14 | -1076, -1076 / 1420, 1420 | -0.35 / 0.33 / 0.14 / 0.14 | 0.35 | image corners are the game's, rounded | - |
| Lashkar | -2167, -2167 / 2167, 2167 | -2167, -2167 / 2167, 2167 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | - |
| Logar | -881.45, -1132.39 / 879.78, 629.22 | -881, -1132 / 880, 629 | -0.45 / -0.39 / -0.22 / 0.22 | 0.45 | image corners are the game's, rounded | - |
| Manicouagan | -2016.58, -2016.75 / 2015.23, 2015.03 | -2016, -2016 / 2015, 2015 | -0.58 / -0.75 / 0.23 / 0.03 | 0.75 | image corners are the game's, rounded | RAAS_v1, RAAS_v2, Seed_v1 |
| Mestia | -1200, -1100 / 1200, 1300 | -1200, -1100 / 1200, 1300 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | - |
| Mutaha | -935, -1140 / 1820, 1615 | -935, -1140 / 1820, 1615 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | Seed_v1, Skirmish_v1 |
| Narva | -1389.71, -1402.07 / 1410.29, 1397.93 | -1390, -1402 / 1410, 1398 | 0.29 / -0.07 / 0.29 / -0.07 | 0.29 | image corners are the game's, rounded | - |
| Pacific | -2016, -2016 / 2016, 2016 | -2016, -2016 / 2016, 2016 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | - |
| Sanxian | -2300, -2050 / 2300, 2550 | -2300, -2050 / 2300, 2550 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | - |
| Skorpo | -3601.5, -3293 / 3248.5, 3576.08 | -3611, -3293 / 3238, 3576 | 9.50 / 0.00 / 10.50 / 0.08 | 10.50 | DIFFERENT: image fitted, grid uses the game's | Skirmish_v1 |
| Sumari | -639.74, -447.28 / 660.34, 852.97 | -640, -447 / 660, 853 | 0.26 / -0.28 / 0.34 / -0.03 | 0.34 | image corners are the game's, rounded | Insurgency_v1, Seed_v1, Skirmish_v1 |
| Tallil | -2340, -2340 / 2340, 2340 | -2340, -2340 / 2340, 2340 | 0.00 / 0.00 / 0.00 / 0.00 | 0.00 | image corners are the game's, rounded | Seed_v1, Skirmish_v1, Skirmish_v2 |
| Yehorivka | -3301.97, -3301.99 / 3048.03, 3048 | -3302, -3302 / 3048, 3048 | 0.03 / 0.01 / 0.03 / 0.00 | 0.03 | image corners are the game's, rounded | - |

Result: 24 maps' image corners are the game's, rounded or truncated to whole metres (largest 1.00 m, Black Coast). **Skorpo** is 9.5 m (west edge) and 10.5 m (east edge) off: its image corners were fitted to the upstream image (`maps.js` comment "perfect for setting map assets, but the ingame grid is more ..."), so the grid used to be 9.5 m west of the game's. The image, heightmap and volume stay on the image corners (they are keyed to them); the grid starts at `SDK_data.minimap.game`, and at the layer's own corners once a layer is loaded (SquadCalc 45.30.0).

What cannot be checked from the dedicated server package, and why:

* The extent of the upstream map images (basemap, terrain, topographic maps): they are client renders; the minimap `Texture2D` assets keep their metadata (for example `Anvil_Minimap` 4096 x 4096) but no pixels (the server cook strips the mips; the package has two `.ubulk` files in 88727 entries). A cross-correlation of the upstream terrain image with our heightmap resolves about 15 m (Anvil, whose corners are exact, reads 12 m), so it cannot tell a 10 m shift on Skorpo.
* How the image is oriented when the game's `Corner0` is not the north-west one (Fools Road, Gorodok, Jensen, Kokan, Lashkar, Logar, Mestia, Mutaha, Narva, Skorpo, Yehorivka list it swapped on some or all layers): needs the pixels.
* The 300 m cell and the lettering rule: the grid widget's cell size and `MapLocationToGridCoordinateString` / `GetNumGridLines` are native C++ functions; the Blueprint dumps give the scale factors 1, 3, 9 only, the Kismet bytecode was not read. 300 m, A to the east and 1 to the south from the corner are the behaviour SquadCalc shipped, consistent with the files, not read from them.

Playable area (`SQMapBoundary.XYBoundary`, spline control points of the first regular layer of each map that has one; width x height of their bounding box and the longest distance between two points, m):

| Layer | Box | Longest |
|---|---|---|
| Anvil_AAS_v1 | 2966 x 2868 | 3860 |
| Fallujah_AAS_v1 | 2963 x 2700 | 3572 |
| GooseBay_AAS_v1 | 3942 x 4024 | 5566 |
| Gorodok_AAS_v1 | 3975 x 3958 | 5322 |
| Kamdesh_AAS_v1 | 3525 x 3479 | 4201 |
| Kohat_AAS_v1 | 3900 x 3447 | 4817 |
| Lashkar_AAS_v1 | 4036 x 3735 | 4698 |
| Manicouagan_AAS_v1 | 4020 x 3991 | 5664 |
| Mutaha_AAS_v1 | 2805 x 2810 | 3970 |
| Narva_AAS_v1 | 2661 x 2514 | 3014 |
| Skorpo_Invasion_v1 | 6427 x 4495 | 6503 |
| Tallil_AAS_v1 | 4078 x 4187 | 5803 |
| Yehorivka_AAS_v1_WP | 4980 x 4980 | 7043 |
| AlBasrah_AAS_v1 | 3785 x 3709 | 4923 |
| BlackCoast_AAS_v1 | 4044 x 4593 | 5877 |
| Harju_AAS_v1 | 3959 x 3950 | 5582 |
| Sanxian_AAS_v1 | 4925 x 4373 | 6425 |
