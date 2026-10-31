# Precise heightmaps from the game files

SquadCalc's own heightmaps are 8-bit (up to 2.1 m per level). These are built from the Squad
dedicated server paks and served by the Deadline SquadCalc in `/heightmaps/<map>/`
(`src/js/squadHeightmaps.js` falls back to the 8-bit ones when a map has none).

Each `heightmap.png` is a 16-bit grayscale PNG on SquadCalc's grid (minimap bounds, `resolution_m` of `meta.json`
per pixel: 1 m, 0.5 m for Chora and Kokan, see "Grid size" below; row = world Y min→max, col = world X min→max);
height above the map's lowest point = `value * z_step_m` from `meta.json`, which also holds the sources and
agreement statistics.

## WebP form

Next to each PNG is a `heightmap.webp` of the same grid: lossless WebP, an RGB image with the high byte
of the 16-bit level in red and the low byte in green (`py/heightmap_webp.py`). The browser decodes it
natively, and it is 33 to 53 % smaller than the PNG (326 MB for the 25 maps become 171 MB) because its
step is coarsened to 1 cm, except where the PNG's is already coarser (Skorpo: its 1064 m range does not
fit 16 bits at 1 cm) and Chora (re-quantising it makes the file bigger). `meta.json` announces it:

* `format: "webp-rg16"`, `generated` (UTC build time: the page requests the files with `?v=<generated>`, so a
  rebuild must change it) and `webp: {file, encoding, z_step_m, levels_sum}`; `levels_sum` is the sum of all
  levels modulo 2^32, which the page checks after decoding, so a browser that alters canvas pixels uses the
  PNG instead of showing wrong heights;
* `z_step_m` stays the PNG's step: a SquadCalc bundle that only knows the PNG (an older one in a cached
  page) keeps working. The PNG stays until the owner drops it.

`heightmaps.sh build` writes both files. For heightmaps built before, `heightmaps.sh webp` converts them from
the served copy and checks each result (`py/convert_webp.py`: the WebP decoded again equals the levels it was
made from; the same step must match the PNG in every pixel, a coarsened one must be within half of the new step),
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

Fused height: the highest of the game terrain, the game objects, and SquadHeight where it rises
0.5 m above the game terrain (an object the SDK has, for example a Blueprint actor). Outside the
game landscape SquadHeight's surface is used.

Checks (Squad build 26005357):

* game terrain vs SquadHeight on open ground: median difference 0.0 mm on every map, RMS 0.5–14 cm
  (`compare_squadheight.py`, `meta.json` → `stats`);
* game objects vs SquadHeight on Skorpo: recall 98.9 %, precision 99.5 %, heights within 0.5 m on
  99.75 % of the shared object cells (median 5 mm); 99.99 % of all cells within 0.5 m
  (`compare_objects.py`);
* SquadCalc's 8-bit heightmap of Skorpo is SquadHeight quantized to 2.09 m steps: error up to
  1.05 m (`compare_squadcalc.py`).

Belaya is not in the current game build and has no heightmap here.

## Running

Requirements: Docker, the Squad dedicated server installed with SteamCMD (app 403240, anonymous),
the SquadHeight release unpacked (`heightmap_images_16bit_png.zip` and the `meta.json` files of
`heightmaps_1m_fullres.zip`).

```sh
tools/heightmaps/heightmaps.sh setup     # CUE4Parse at the pinned commit + cue4parse.patch, extractor, Python image
tools/heightmaps/heightmaps.sh extract   # landscapes and static meshes of every map (about 1 h)
tools/heightmaps/heightmaps.sh build     # fused heightmaps into $OUT (about 1–2 h); "build skorpo" for one map
tools/heightmaps/heightmaps.sh deploy    # copy into the served SquadCalc, previous copy kept as heightmaps.bak.<date>
```

Paths are set with `SQUAD_DIR`, `SQUADHEIGHT`, `WORK`, `OUT` and `DIST` (see the script header).
After a game patch: update the server with SteamCMD, then `extract`, `build`, `deploy`; a new map
goes into `py/maps.py` (its SquadHeight name and landscape levels).

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

* `py/compare_native_vertices.py` — the table above; `py/test_build_heightmap.py` — grid arithmetic tests
  (`python -m unittest test_build_heightmap`);
* `extractor/` — SquadExtract (C#, [CUE4Parse](https://github.com/FabianFG/CUE4Parse)): `list`,
  `landscape`/`extractall` (landscape collision), `statics` (static mesh placements and collision),
  `dumpall` (assets as JSON, for `tools/game_ballistics`), `features` (foliage, landscape splines and
  water actors, for `tools/maptiles`). `cue4parse.patch` keeps the cooked
  landscape collision that CUE4Parse skips.
* `py/heightmap_webp.py`, `py/convert_webp.py` — the WebP form above;
* `py/landscape.py` — cooked Chaos heightfield reader and landscape assembly;
  `py/objects.py` — static mesh collision rasterizer; `py/build_heightmap.py`, `py/build_all.py` —
  fusion and output; `py/maps.py` — SquadCalc map → SquadHeight name and landscape levels;
  `py/compare_*.py` — the checks above.
* `py/audit_ground_truth.py`, `log_points.awk`, `py/compare_interpolation.py`, `py/compare_resolution.py`: the
  checks above.
