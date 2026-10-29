# Precise heightmaps from the game files

SquadCalc's own heightmaps are 8-bit (up to 2.1 m per level). These are built from the Squad
dedicated server paks and served by the Deadline SquadCalc in `/heightmaps/<map>/`
(`src/js/squadHeightmaps.js` falls back to the 8-bit ones when a map has none).

Each `heightmap.png` is a 16-bit grayscale PNG on SquadCalc's grid (minimap bounds, 1 m per pixel,
row = world Y min→max, col = world X min→max); height above the map's lowest point =
`value * z_step_m` from `meta.json`, which also holds the sources and agreement statistics.

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

Files:

* `extractor/` — SquadExtract (C#, [CUE4Parse](https://github.com/FabianFG/CUE4Parse)): `list`,
  `landscape`/`extractall` (landscape collision), `statics` (static mesh placements and collision),
  `dumpall` (assets as JSON, for `tools/game_ballistics`), `features` (foliage, landscape splines and
  water actors, for `tools/maptiles`). `cue4parse.patch` keeps the cooked
  landscape collision that CUE4Parse skips.
* `py/landscape.py` — cooked Chaos heightfield reader and landscape assembly;
  `py/objects.py` — static mesh collision rasterizer; `py/build_heightmap.py`, `py/build_all.py` —
  fusion and output; `py/maps.py` — SquadCalc map → SquadHeight name and landscape levels;
  `py/compare_*.py` — the checks above.
