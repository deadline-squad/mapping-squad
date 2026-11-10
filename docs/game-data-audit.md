# Game data audit: Deadline SquadCalc against Squad build 26005357

What the calculator keeps by hand (`src/data/maps.js`, `src/data/weapons.js` and a few constants of
`deadline-squad/deadline-squadcalc`) compared with the Squad dedicated server build 26005357 (`~/data/squad-server`,
`steamapps/appmanifest_403240.acf`), and the 64 layers of the Deadline pool as the calculator loads them from the
upstream API compared with the same layers of that build.

**History.** The audit was made on 2026-11-10 on SquadCalc `dev` `cb98bbef1` (45.35.0) with one-off scripts. Its seven
differences were fixed in SquadCalc 45.38.0 and Squad Ballistics 1.7.2 (section 0). The same day the scripts became
`tools/game_audit` (`tools/game_audit/README.md`) and everything they read was read again from the paks with it, with the
extractor built from this repository: the figures below are those of that rerun, against SquadCalc 45.40.0
(`955d1ab2e`) and Squad Ballistics 1.7.2 (`7c3ac7c`). Where the rerun did not give the audit's figure, section 5 says so.
Nothing was measured in a running game and no game server was contacted; the upstream API
`https://squadcalc.app/api` was read with 84 requests at 0.6 s intervals by the audit and again, twice, by the rerun.

**How a statement can be checked.** Each row names its evidence:

* **tool**: read from the game files by a committed tool; the command is in section 6 and the value in
  `tools/game_audit/data/` or in the generated file named. These are VERIFIED in the vocabulary of
  `docs/thesis-methods-and-results.md` (section 0), and INFERRED where the row says the value is computed from them.
* **one-off**: read once during the audit with a command that was not kept; no committed tool reads it. UNVERIFIED in
  that vocabulary until a tool does.

## 0. Result

### Coverage (checked / total)

| Section | Checked | Not checked, and why | Evidence |
|---|---|---|---|
| 1. `maps.js`, 25 maps | 125 / 175 fields: `game` corners 25, image corners 25, landscape origin 25, size 25, scale 25 | `heightmap.BWlevels` (25) and `heightmapPNG.scale` (25) describe upstream's 8-bit heightmap image (the fallback when the precise heightmap cannot be loaded), not the game; checking them needs that image compared with the game's heights for each map (done for Skorpo only, `tools/heightmaps/py/compare_squadcalc.py`) | tool: `game_audit.sh check` |
| 2. `weapons.js`, weapons aimed by elevation | 10 / 10 hand-kept weapons (Mortar, UB-32, HellCannon, Tech.Mortar, Tech.UB-32, BM-21Grad, M1064M121, Mk19, BTR4-AGS, AGS-17), 135 / 135 inputs: 90 flight and blast rows, 10 elevation ranges, 11 minimum distances, 10 maximum ranges, 10 launch points, 3 scale offsets, 1 hold model | 10 Workshop mod weapons (MO120RTF1, type_63, PZL07, M109, M777, T62.DUMP.TRUCK, HIMARS, TOS-1A, Ural-HellCannon, MTLB_FAB500): not in the game build. The 125 `DF_` entries generated from Squad Ballistics: out of scope, the existing check was rerun on them (section 2.6) | tool: the 90 flight and blast rows and the AGS-17's limits (`provenance.py`), 8 elevation ranges (`mounts.py`), 9 minimum distances and 9 maximum ranges of those 8 weapons (`calculator.mjs`, `check_calculator.py`), 4 launch points (`provenance.py` from Squad Ballistics' snapshot). One-off: 3 launch points (Mortar, UB-32, HellCannon). No game value to compare: the Mk19 entry (O2), the launch height and barrel offset of the BTR4-AGS (O1) and of the AGS-17 (O4), the scale offsets |
| 3. Layers of the Deadline pool | 64 / 64 exist in the API; 64 / 64 compared in depth (asked: at least 10) | - | tool: `game_audit.sh api` |
| 4. Constants | 6 / 10 fully, 1 partly: FOB construction and exclusion radius, the two marker circles, protection zones, structure-damage tables; gravity for the layers only | soldier height 1.8 m and health 100 (native C++ defaults, not in the paks); the 300 m circle of the UAV marker (no such radius in the UAV Blueprints read); the grid's 300 m (native, earlier audit, not read again); the engine config's gravity (not readable with the extractor, section 4) | tool, except the gravity keys of the layers and the UAV Blueprints (one-off) |

### Differences found

"Calculator" is the state the audit found (45.35.0). D1 to D7 are fixed and stay fixed in 45.40.0: `game_audit.sh check`
reports 0 differences and the four known ones listed as open below.

| # | Item | Calculator (45.35.0) | Game (26005357) | Status | Evidence |
|---|---|---|---|---|---|
| D1 | Mortar, top elevation | 88.875 deg (1580 mil) | 88.8 deg (1578.7 mil): mount 0..43.8 + 45 | **fixed** `35e56973b` | tool (2.2) |
| D2 | Minimum distance on level ground | Mortar 51, Tech.Mortar 51, M1064M121 340 (both shells), BM-21Grad 0, Tech.UB-32 0 | 51.8, 51.8, 358, 985.1, 147.1 m: the range at the mount's stop, 51.77, 51.76, 357.96, 985.09 and 147.05 m | **fixed** `35e56973b` | tool (2.4); INFERRED: computed with the calculator's solver from the stop |
| D3 | BTR4-AGS, elevation range on the gunner's display | -45..135 deg | -4.9..45.1 deg: turret -5..45, camera +0.1 | **fixed** `35e56973b` | tool (2.2) |
| D4 | Range circle of a hell cannon marker | 923 m | 924 m (the weapon's longest shot with the game's values, 924.43 m) | **fixed** `35e56973b` | tool (2.4) |
| D5 | `SDK_data.heightmap` origin / size of 7 maps (Chora, Mestia, Narva, Harju, Kokan, Sumari, Tallil) | up to 762 m off (Chora), 98 m (Mestia), 16 m and 32 vertices (Narva) | landscape actors of the levels | **fixed** `69bd47058` (no calculation read these fields) | tool (1.2) |
| D6 | FOB exclusion radius | one value per map (300 or 400 m) | per layer: 38 layers of 400 m maps play with 300 m; in the pool: `AlBasrah_RAAS_v3` | **fixed** `cede4aa71` | tool (4) |
| D7 | Protection zone of the first main, `GooseBay_AAS_v1` and `GooseBay_RAAS_v1` (both in the pool) | radius -236 m, no-deploy -86 m (the API gives a negative radius) | 236 m and 386 m (sphere 150 m; the zone's scale is 31149.6, 31149.6, -1.5759 and the engine takes the smallest size) | **fixed** `d67f8d190` | tool (3.2) |
| O1 | BTR4-AGS, barrel above the display reading and launch height | +0.7346 deg, 3.4 m (upstream commit `312099165`, "BTR4-AGS final") | +1.6 deg (socket `BarrelStart_AGS` 1.7 - camera 0.1), 2.626 m, muzzle 0.437 m forward | **open**: the two give 765 m and 864 m for a reading of 5 deg; one shot on level ground decides (section 2.3) | tool for the two ranges (`btr4_ags.mjs`); the game side is Squad Ballistics' entry, from its snapshot of client build 26234431 |
| O2 | Mk19 (upstream entry) | -45..85.3 deg, +0.984 deg, 4 m, minimum 10 m | no Mk19 mount of the game has these values; six mounts, six ranges (section 2.2) | **open**: the entry names no vehicle, so no game value can replace it without a guess | one-off |
| O3 | Maximum-range circle | longest shot at any elevation: UB-32 2184 m, M1064M121 2063 m | reachable with the mount: 2082 m (35 deg), 2031 m (50 deg) | **open**: Squad Ballistics defines maximum range the same way and `tools/direct_fire/compare.py` checks the two apps agree; changing one side breaks that check. Solutions are right (a target beyond the reach gets none), only the circle is too wide | tool (2.4), `KNOWN` in `check_calculator.py` |
| O4 | AGS-17 (hand-kept and generated entries) | top 85.87 deg, 9.08 deg/s, launch 1 m | 85.85 deg (mount -13..85 + socket 0.85), 9.00 deg/s, 0.347 m | top: **fixed by 45.37.0** (85.85 in both apps); rate and launch height **open**, known: fitted to the owner's 67 in-game measurements (`tools/volumetric/docs/data-provenance.md`); the files fit them as well (RMS 5.5 m against 5.34 m) | tool for the top (`provenance.py`); the rest is recorded in `provenance.py` as UNVERIFIED |
| O5 | Explosion fields a projectile Blueprint does not set (UB-32, Tech.UB-32, Mk19, BTR4-AGS, AGS-17) | 115 damage, inner 5 m, outer 15 m, falloff 1, 0.2 m | C++ defaults of `ASQProjectile`, not in the paks | **open**: needs the constructor of `ASQProjectile` in the server binary; the calculator's values are the ones every partially overriding Blueprint is consistent with | tool: `provenance.py` marks the five rows ASSUMED |
| O6 | Secondary explosions (Mortar, Tech.Mortar, HellCannon, BM-21Grad, M1064M121) | one explosion per shell, the wider one | two explosions | **open**, small: the 100 and 25 damage radii are set by the wider explosion; only for the M121 impact shell would 100 damage reach 7.4 m instead of 7.2 m, if the two damages add (native code, not read) | one-off (values in `resolved.json`, section 2.5) |
| O7 | Capture-area shapes in the upstream API | 8 zones on 3 layers displaced 4.7 to 73 m (zones with pitch or roll), 4 zones on 2 layers with the unscaled radius | section 3.2 | **open**, upstream data: the objective positions themselves agree to 0.02 cm; no firing solution uses the shapes | tool (3.2) |
| O8 | World gravity | 9.80 m/s^2 | `DefaultGravityZ` -980 (engine default); no layer overrides it | **not re-proven**: the engine config is not readable with the extractor; section 4 | one-off |
| O9 | `SDK_data.heightmap.origin` of Skorpo | [-4811, -3947]: the location of the landscape actor | the terrain starts 508 x 1524 quads from the actor, which is turned by -2.006 deg: first vertex at (-4138.02, -2141.58) | **fixed** in SquadCalc 45.44.0: `origin` [-4138, -2142], the first vertex as on the other 24 maps, so that `origin` and `size` describe one rectangle (found by the rerun, section 5; no calculation reads the field) | tool (1.2), `check_calculator.py` |

No other difference was found. Weapon velocities, gravity scales, motors, speed caps, spreads and explosions of the ten
hand-kept weapons, the game corners of the 25 maps, the objectives, mains, factions, tickets and game modes of the 64
layers, the FOB construction radius, the lock distance of protection zones and the structure-damage tables are equal.

### What followed in the other repositories

* **Squad Ballistics 1.7.2** (`8c3b7cd`) took the values of D1 and D2: the mortar's `elevation_limits` and
  `hold_elevation` 45..88.8 and the minimum distances 51.8, 51.8, 358, 985.1 and 147.1 m.
  `python3 tools/direct_fire/compare.py ~/dev/Squad-Ballistics ~/agl/SquadCalc` gives "weapons: 167 checked: 32652
  mismatches: 0 missing: 0" (exit 0, rerun 2026-11-10 with the tool of `dev` `cf8c7bd`).
* **`tools/game_ballistics/provenance.py`**: the rows for the limits of the mortar, Hell Cannon, UB-32 and BTR4-AGS and
  for the minimum distances of the five weapons are computed from `tools/game_audit/data/mount_limits.json` and
  labelled INFERRED (they were ASSUMED "inherited from the upstream table"); `--check` compares the apps' limits with
  the mounts. `--write` gives "5163 rows, 3511 labelled, 0 differ from the game" and `--check` exits 0. The launch
  points of Mortar, UB-32 and Hell Cannon stay UNVERIFIED there: the audit read them again by hand and no tool does.
* **`docs/thesis-methods-and-results.md` and `.ru.md`**, section 1.5: the row "Mortar top elevation" states 88.8 and
  where the 45 comes from. Section 2.3 is confirmed as written (0 differences on a fresh read of 219 layers).

## 1. Maps (`src/data/maps.js`)

### 1.1 Minimap corners

Source: `MapTextureCornerZero` / `MapTextureCornerOne` of the `SQWorldSettings` of every gameplay layer
(`Maps/<map>/Gameplay_Layers/*.umap`), the location of the two actors they name. All 219 layers of the build are dumped
(`game_audit.sh extract-layers`), reduced (`layers.py reduce`, `corners`) and put through
`tools/heightmaps/py/minimap_corners.py table`. Result `tools/game_audit/data/minimap_corners.json`.

Verdict: `SDK_data.minimap.game` of the 25 maps is equal to the table, 0 differences. `corner0/1` (the extent of the
map image, the heightmap and the markers) is the game's rounded or truncated to whole metres on 24 maps (largest 1.00 m,
Black Coast); on Skorpo the image was fitted 9.5 m (west) and 10.5 m (east) off, which is known and why the grid takes
`game`. A layer with a minimap of its own (Skirmish, Seed) gets its corners from the API; they agree with the game to
0.006 cm on the 64 pool layers (section 3).

| Map | Image corners `corner0/1` (min / max) | `game` in maps.js | Game (modal corners of its layers) | Image against game, worst edge | Layers read / with the modal corners | Verdict |
|---|---|---|---|---|---|---|
| AlBasrah | [-2000, -2000] / [2000, 2000] | [-2000, -2000] / [2000, 2000] | [-2000, -2000] / [2000, 2000] | 0.00 m | 14 / 14 | EQUAL |
| Anvil | [-2040, -2040] / [1020, 1020] | [-2040, -2040] / [1020, 1020] | [-2040, -2040] / [1020, 1020] | 0.00 m | 5 / 5 | EQUAL |
| BlackCoast | [-2299, -2127] / [2299, 2472] | [-2300, -2127.47] / [2299.98, 2472.51] | [-2300, -2127.47] / [2299.98, 2472.51] | 1.00 m | 9 / 8 | EQUAL |
| Chora | [-2464, -2664] / [1600, 1400] | [-2464, -2664] / [1599.9, 1400] | [-2464, -2664] / [1599.9, 1400] | 0.10 m | 9 / 8 | EQUAL |
| Fallujah | [-1315, -1545] / [1690, 1460] | [-1315, -1545] / [1690, 1460] | [-1315, -1545] / [1690, 1460] | 0.00 m | 11 / 11 | EQUAL |
| FoolsRoad | [-1326, -1326] / [448, 448] | [-1325.77, -1325.77] / [448.05, 448.05] | [-1325.77, -1325.77] / [448.05, 448.05] | 0.23 m | 8 / 8 | EQUAL |
| GooseBay | [-2016, -2016] / [2015, 2015] | [-2016.58, -2016.75] / [2015.23, 2015.03] | [-2016.58, -2016.75] / [2015.23, 2015.03] | 0.75 m | 7 / 6 | EQUAL |
| Gorodok | [-2032, -2032] / [2032, 2032] | [-2031.99, -2032] / [2032.01, 2032] | [-2031.99, -2032] / [2032.01, 2032] | 0.01 m | 11 / 11 | EQUAL |
| Harju | [-2016, -2016] / [2016, 2016] | [-2016, -2016] / [2016, 2016] | [-2016, -2016] / [2016, 2016] | 0.00 m | 14 / 14 | EQUAL |
| Jensen | [-2004, -2004] / [2004, 2004] | [-2004, -2004] / [2004, 2004] | [-2004, -2004] / [2004, 2004] | 0.00 m | 8 / 8 | EQUAL |
| Kamdesh | [-2016, -2016] / [2016, 2016] | [-2016, -2016] / [2016, 2016] | [-2016, -2016] / [2016, 2016] | 0.00 m | 6 / 6 | EQUAL |
| Kohat | [-2300, -2300] / [2317, 2317] | [-2300, -2300] / [2317, 2317] | [-2300, -2300] / [2317, 2317] | 0.00 m | 8 / 8 | EQUAL |
| Kokan | [-1076, -1076] / [1420, 1420] | [-1076.35, -1075.67] / [1420.14, 1420.14] | [-1076.35, -1075.67] / [1420.14, 1420.14] | 0.35 m | 7 / 7 | EQUAL |
| Lashkar | [-2167, -2167] / [2167, 2167] | [-2167, -2167] / [2167, 2167] | [-2167, -2167] / [2167, 2167] | 0.00 m | 8 / 8 | EQUAL |
| Logar | [-881, -1132] / [880, 629] | [-881.45, -1132.39] / [879.78, 629.22] | [-881.45, -1132.39] / [879.78, 629.22] | 0.45 m | 6 / 6 | EQUAL |
| Manicouagan | [-2016, -2016] / [2015, 2015] | [-2016.58, -2016.75] / [2015.23, 2015.03] | [-2016.58, -2016.75] / [2015.23, 2015.03] | 0.75 m | 12 / 9 | EQUAL |
| Mestia | [-1200, -1100] / [1200, 1300] | [-1200, -1100] / [1200, 1300] | [-1200, -1100] / [1200, 1300] | 0.00 m | 6 / 6 | EQUAL |
| Mutaha | [-935, -1140] / [1820, 1615] | [-935, -1140] / [1820, 1615] | [-935, -1140] / [1820, 1615] | 0.00 m | 8 / 6 | EQUAL |
| Narva | [-1390, -1402] / [1410, 1398] | [-1389.71, -1402.07] / [1410.29, 1397.93] | [-1389.71, -1402.07] / [1410.29, 1397.93] | 0.29 m | 9 / 9 | EQUAL |
| Pacific | [-2016, -2016] / [2016, 2016] | [-2016, -2016] / [2016, 2016] | [-2016, -2016] / [2016, 2016] | 0.00 m | 4 / 4 | EQUAL |
| Sanxian | [-2300, -2050] / [2300, 2550] | [-2300, -2050] / [2300, 2550] | [-2300, -2050] / [2300, 2550] | 0.00 m | 11 / 11 | EQUAL |
| Skorpo | [-3611, -3293] / [3238, 3576] | [-3601.5, -3293] / [3248.5, 3576.08] | [-3601.5, -3293] / [3248.5, 3576.08] | 10.50 m | 5 / 4 | EQUAL; image fitted 9.5 / 10.5 m off, the grid uses `game` |
| Sumari | [-640, -447] / [660, 853] | [-639.74, -447.28] / [660.34, 852.97] | [-639.74, -447.28] / [660.34, 852.97] | 0.34 m | 9 / 6 | EQUAL |
| Tallil | [-2340, -2340] / [2340, 2340] | [-2340, -2340] / [2340, 2340] | [-2340, -2340] / [2340, 2340] | 0.00 m | 9 / 6 | EQUAL |
| Yehorivka | [-3302, -3302] / [3048, 3048] | [-3301.97, -3301.99] / [3048.03, 3048] | [-3301.97, -3301.99] / [3048.03, 3048] | 0.03 m | 15 / 15 | EQUAL |

### 1.2 Landscape origin, size and scale (`SDK_data.heightmap`)

Source: the `Landscape` / `LandscapeStreamingProxy` actors of each map's landscape levels (`tools/heightmaps/py/maps.py`
names the levels): `RelativeLocation`, `RelativeRotation` and `RelativeScale3D` of the actor's root, and the extent of
its `LandscapeHeightfieldCollisionComponent`s (offset from the actor in quads and `CollisionSizeQuads`), extracted by
`game_audit.sh extract-landscapes`. `landscapes.py` writes `tools/game_audit/data/landscapes.json`. Origin = the first
vertex of the components in metres (the actor's location plus the offset of its lowest component, scaled and turned
with the actor), size = vertices, scale = metres per vertex and per height unit. Fallujah is the rectangle its six
streaming proxies cover.

No calculation of the calculator reads these fields: heights come from `/heightmaps/<map>/` (built from the same
landscapes by `tools/heightmaps`, bounds = the image corners), and `origin` / `size` / `scale` only feed the helper
`npm run mapinfo`, which takes `origin` as the place of the heightmap's first pixel against the minimap corner. They
were wrong on seven maps and are corrected (D5), with a test in the calculator that holds the game's table
(`tests/maps.test.mjs`). `maps.js` keeps the origin in whole metres, so EQUAL means within 1 m.

| Map | maps.js `heightmap` origin / size / scale (45.40.0) | Game: first vertex (m) / size (vertices) / scale | Actor (level / name, first component in quads from the actor) | Verdict |
|---|---|---|---|---|
| AlBasrah | [-2040, -2040] / [4081, 4081] / [1, 1, 1] | [-2040.01, -2040.00] / [4081, 4081] / [1.0, 1.0, 1.0] | `L_070_Landscape_AlBasrah_01` / `Landscape_0`, [0, 0] | EQUAL |
| Anvil | [-2040, -2040] / [4081, 4081] / [0.75, 0.75, 0.45] | [-2040.00, -2040.00] / [4081, 4081] / [0.75, 0.75, 0.45] | `Anvil_GEO` / `Landscape_1`, [0, 0] | EQUAL |
| BlackCoast | [-2040, -2142] / [4065, 4065] / [1.003937, 1.003937, 0.8] | [-2040.01, -2142.50] / [4065, 4065] / [1.0039, 1.0039, 0.8] | `Black_Coast_Geo` / `Landscape_1`, [0, 0] | EQUAL |
| Chora | [-2464, -1902] / [8129, 4827] / [0.5, 0.5, 4] | [-2464.00, -1902.00] / [8129, 4827] / [0.5, 0.5, 4.0] | `Chora` / `Landscape_0`, [0, 1524] | EQUAL since 45.38.0 (D5; was origin [-2464, -2664]) |
| Fallujah | [-2040, -2040] / [4081, 4081] / [1, 1, 1] | [-2040.00, -2040.00] / [4081, 4081] / [1.0, 1.0, 1.0] | `L_070_Landscape_Fallujah_00` / `LandscapeStreamingProxy`, [-1530, 0] and 5 more proxies | EQUAL |
| FoolsRoad | [-1598, -1866] / [2806, 2806] / [1, 1, 3.2] | [-1598.10, -1866.30] / [2806, 2806] / [1.0, 1.0, 3.2] | `Fools_Road_Landscape_and_Geo` / `Landscape_0`, [1020, 765] | EQUAL |
| GooseBay | [-2032, -2032] / [4065, 4065] / [1, 1, 0.4] | [-2032.57, -2032.75] / [4065, 4065] / [1.0, 1.0, 0.4] | `Goose_Bay` / `Landscape_1`, [0, 0] | EQUAL |
| Gorodok | [-2032, -2032] / [4065, 4065] / [1, 1, 10] | [-2031.99, -2032.00] / [4065, 4065] / [1.0, 1.0, 10.0] | `L_070_Landscape_Gorodok` / `Landscape_1`, [0, 0] | EQUAL |
| Harju | [-2016, -2016] / [4033, 4033] / [1, 1, 1] | [-2015.99, -2016.01] / [4033, 4033] / [1.0, 1.0, 1.0] | `Harju_Landscape` / `Landscape_1`, [0, 0] | EQUAL since 45.38.0 (D5; was size [4032, 4032]) |
| Jensen | [-2040, -2040] / [4081, 4081] / [1, 1, 1] | [-2040.51, -2040.14] / [4081, 4081] / [1.0, 1.0, 1.0] | `Jensens_Range_Geo` / `Landscape_0`, [0, 0] | EQUAL |
| Kamdesh | [-2016, -2016] / [4033, 4033] / [1, 1, 1.35] | [-2016.00, -2016.00] / [4033, 4033] / [1.0, 1.0, 1.35] | `Kamdesh_Highlands` / `Landscape_0`, [0, 0] | EQUAL |
| Kohat | [-2016, -2016] / [4065, 4065] / [1, 1, 0.75] | [-2016.02, -2016.00] / [4065, 4065] / [1.0, 1.0, 0.75] | `Kohat_landscape` / `Landscape_0`, [0, 0] | EQUAL |
| Kokan | [-1333, -1714] / [6097, 7367] / [0.5, 0.5, 1] | [-1333.00, -1714.00] / [6097, 7367] / [0.5, 0.5, 1.0] | `Kokan_Valley_Landscape` / `Landscape_0`, [-508, -1270] | EQUAL since 45.38.0 (D5; was origin [-1334, -1715]) |
| Lashkar | [-2167, -2167] / [4336, 4336] / [1, 1, 1.5] | [-2167.00, -2167.00] / [4336, 4336] / [1.0, 1.0, 1.5] | `Lashkar_GEO` / `Landscape_0`, [0, 0] | EQUAL |
| Logar | [-1386, -1260] / [2773, 1891] / [1, 1, 0.5] | [-1386.04, -1260.06] / [2773, 1891] / [0.9999, 0.9999, 0.4999] | `Logar_Valley_landscape` / `Landscape3`, [630, 756] | EQUAL |
| Manicouagan | [-2032, -2032] / [4065, 4065] / [1, 1, 3] | [-2032.22, -2032.10] / [4065, 4065] / [1.0, 1.0, 3.0] | `Manicouagan_geo` / `Landscape_0`, [0, 0] | EQUAL |
| Mestia | [-1545, -1162] / [3061, 2551] / [1, 1, 1.2] | [-1545.00, -1161.95] / [3061, 2551] / [1.0, 1.0, 1.2] | `Mestia_Geo` / `Landscape_0`, [765, 765] | EQUAL since 45.38.0 (D5; was origin [-1545, -1260]) |
| Mutaha | [-1785, -1785] / [4081, 4081] / [1, 1, 0.3] | [-1785.02, -1785.00] / [4081, 4081] / [1.0, 1.0, 0.3] | `L_070_Mutaha_Landscape` / `Landscape_1`, [2040, 2040] | EQUAL |
| Narva | [-2032, -2032] / [4065, 4065] / [1, 1, 1] | [-2032.00, -2032.00] / [4065, 4065] / [1.0, 1.0, 1.0] | `L_070_Landscape_Narva` / `Landscape_1`, [0, 0] | EQUAL since 45.38.0 (D5; was origin [-2016, -2016], size [4033, 4033]) |
| Pacific | [-2016, -2016] / [4033, 4033] / [1, 1, 0.28] | [-2016.00, -2016.00] / [4033, 4033] / [1.0, 1.0, 0.28] | `PacificProvingGrounds_Geo` / `Landscape_0`, [0, 0] | EQUAL |
| Sanxian | [-2040, -2040] / [4081, 4081] / [1, 1, 1] | [-2040.00, -2040.00] / [4081, 4081] / [1.0, 1.0, 1.0] | `L_070_Landscape_Sanxian_01` / `Landscape_0`, [0, 0] | EQUAL |
| Skorpo | [-4138, -2142] / [7113, 5081] / [1.2, 1.2, 3.5] | [-4138.02, -2141.58] / [7113, 5081] / [1.2, 1.2, 3.5] | `Skorpo_Baselayer` / `Uskedal`, [508, 1524], yaw -2.006 deg | EQUAL since 45.44.0 (O9; was origin [-4811, -3947]) |
| Sumari | [-682, -372] / [1427, 1055] / [1, 1, 0.75] | [-682.01, -371.99] / [1427, 1055] / [1.0, 1.0, 0.75] | `Sumari_master` / `Landscape_0`, [310, 620] | EQUAL since 45.38.0 (D5; was origin [-683, -373]) |
| Tallil | [-2286, -2286] / [4573, 4573] / [1, 1, 1.25] | [-2285.91, -2285.77] / [4573, 4573] / [1.0, 1.0, 1.25] | `Tallil_Outskirts` / `Landscape_1`, [-254, -254] | EQUAL since 45.38.0 (D5; was origin [-2287, -2287]) |
| Yehorivka | [-3302, -3302] / [6351, 6351] / [1, 1, 4] | [-3301.97, -3302.00] / [6351, 6351] / [1.0, 1.0, 4.0] | `L_070_Landscape_Yehorivka` / `Landscape_0`, [762, 762] | EQUAL |

Skorpo (O9): its actor is the only one that is turned, and its components begin 508 x 1524 quads (610 m, 1829 m) from
it. `maps.js` has the actor's location as `origin` and the extent of the components as `size`, so the two fields do not
describe one rectangle. The audit called this row equal by taking the actor's location for a turned landscape; by the
rule of the other 24 rows it is not. SquadCalc 45.44.0 takes the first vertex, as for the other maps. `heightmap.BWlevels` and `heightmapPNG.scale` were not checked (see Coverage).

## 2. Weapons (`src/data/weapons.js`)

### 2.1 Velocity, gravity, motor, speed cap, drag, spread, explosion, lifespan

`python3 tools/game_ballistics/provenance.py --resolved ... --dump ... --sb <SB> --sc <SC> --write tools/volumetric/docs`
on the dump of build 26005357 (`~/data/squad-weapons`, made 2026-10-29) compares every input of every weapon of both
apps with the weapon and projectile Blueprints: "5163 rows, 3511 labelled, 0 differ from the game". Its rows for the ten
hand-kept weapons are in `tools/volumetric/docs/data-provenance.tsv` (`app` SC, `weapon` one of the ten names): 90 rows for
these inputs, all equal to the game. 68 are VERIFIED, 12 INFERRED (no projectile movement component has a drag field:
11 rows; the AGS-17 uses the sustained value of its spread curve), 10 ASSUMED: the mortar, hell cannon and M121 shells
have no `InitialLifeSpan` in the game (5 rows; the calculator's 100 s is longer than any of their flights), and 5
explosions have fields the Blueprint leaves to the C++ default (O5).

The game has no drag and no deceleration other than the motor of the S-5 rocket (`ConstantAcceleration` -5000 cm/s^2
for 2 s): no projectile movement component of the dump has a drag field.

### 2.2 Elevation ranges

Source: `RotationConstraints.PitchInterval` of the movement component of each mount, found along the Blueprint chain of
the mount (a class that sets none keeps its parent's), and what the reading adds to it: the constant the sight widget
adds in its Kismet bytecode, the rest pitch of the bone the muzzle socket sits on, or the pitch of a component of the
mount. `game_audit.sh extract-mounts` dumps the 29 assets with `SquadExtract dumpbytecode`; `mounts.py` reads them into
`tools/game_audit/data/mount_limits.json` and fails when a widget no longer contains the statements it relies on.

| Weapon | `minElevation` (45.40.0) | Mount pitch in the game | What the reading adds | Game range | Verdict |
|---|---|---|---|---|---|
| Mortar | 45..88.8 | 0..43.8, Vehicles/BP_GenericDeployableMortarVehicle: RotationConstraints.PitchInterval of SQTurretMovement | 45: UI/Widgets/Vehicles/Mortar/UMG_MortarControl ExecuteUbergraph_UMG_MortarControl: adds 45 to CachedTubePitch | 45..88.8 | EQUAL |
| UB-32 | -25..35 | -25..35, Vehicles/BP_GenericDeployableTripodVehicle: RotationConstraints.PitchInterval of SQTurretMovement | 0: Vehicles/Emplaced_UB32_RocketArtillery/Reticles/Emplaced_UB-32_GunnerAngleDisplay AngleRotationDisplay: shows CallFunc_BreakRotator_Pitch as it is | -25..35 | EQUAL |
| HellCannon | 10..90 | -30..50, Vehicles/Emplaced_HellCannon/BP_Emplaced_HellCannon_Base: RotationConstraints.PitchInterval of SQTurretMovement | 40: Vehicles/Emplaced_HellCannon/Reticles/UMG_HellCannon_HUD AngleRotationDisplay: adds 40 to CallFunc_BreakRotator_Pitch | 10..90 | EQUAL |
| Tech.Mortar | 40..83.8 | 0..43.8, Vehicles/Technical2Seater/Turrets/BP_Technical_MortarTurret: RotationConstraints.PitchInterval of SQTurretMovement | 40: Vehicles/Technical2Seater/Weapons/UMG_MortarHUD_Technical AngleRotationDisplay: adds 40 to CallFunc_BreakRotator_Pitch | 40..83.8 | EQUAL |
| Tech.UB-32 | 0..50 | 0..50, Vehicles/Technical/Turrets/BP_Technical_Turret_UB32: RotationConstraints.PitchInterval of SQTurretMovement | 0: Vehicles/Technical/Weapons/UB-32/UB-32_GunnerAngleDisplay AngleRotationDisplay: shows CallFunc_BreakRotator_Pitch as it is | 0..50 | EQUAL |
| BM-21Grad | 14.2..55 | 0..40.8, Vehicles/Ural375_BM21Grad/Turrets/BP_BM21Grad_Turret_INS: RotationConstraints.PitchInterval of PitchMovement | 14.2: Vehicles/Ural375_BM21Grad/Meshes/SKEL_BM21_Launcher: bone pitch_swivel of the socket Attach_Muzzle rests at this pitch in the reference pose; 0: Vehicles/Ural375_BM21Grad/Reticles/BM21_GunnerReticle AngleRotationDisplay: shows CallFunc_BreakRotator_Pitch as it is | 14.2..55 | EQUAL |
| M1064M121 | 50..85 | 0..35, Vehicles/M1064A3/Turrets/BP_M1064A3_MortarTurret: RotationConstraints.PitchInterval of SQTurretMovement | 50: Vehicles/M1064A3/Turrets/BP_M1064A3_MortarTurret: RelativeRotation.Pitch of the component Muzzle | 50..85 | EQUAL |
| BTR4-AGS | -4.9..45.1 | -5..45, Vehicles/BMP1TS_AFU/Turrets/BP_BMP1TS_Turret: RotationConstraints.PitchInterval of TurretMovement | 0.1: Vehicles/BMP1TS_AFU/Turrets/BP_BMP1TS_Turret: RelativeRotation.Pitch of the component FirstPersonCamera | -4.9..45.1 | EQUAL |
| Mk19 | -45..85.3 | M1117 -15..30 (-5 to the front), AAVP-7A1 -10..30, RHIB -20..30, tripod -35..20 (this build); M1151 -20..30, PARS III -25..40, TAPV -10..45 (Squad Ballistics' snapshot) | 0 to 1.7 | none matches | **DIFFERS, open (O2)**; one-off |
| AGS-17 | -12.15..85.85 | -13..85, `BP_RHIB_Turret_AGS17` and the tripod | +0.85 socket pitch | -12.15..85.85 | EQUAL since 45.37.0 (O4); tool: `provenance.py` from Squad Ballistics' snapshot |

At the audit (45.35.0) three of these rows differed: Mortar 45..88.875 (D1), BTR4-AGS -45..135 (D3) and AGS-17
-12.15..85.87 (O4). The M1064's tube cannot be laid below 15 degrees over the rear arc of its carrier, beyond 130 to
140 degrees of yaw (`pitch_by_yaw` of the data file, `FC_M1064A3_YawToMinPitch`); its top is 35 degrees at every yaw.
The technical mortar's sight adds 40 where the deployable mortar's adds 45: the calculator's 5 degree scale offset
(`angleOffset`) for it is the difference, and the barrel elevation of its stop is 83.8 + 5 = 88.8 degrees.

### 2.3 Launch point, scale offset, hold model

| Weapon | Calculator | Game | Source | Verdict | Evidence |
|---|---|---|---|---|---|
| Mortar | pivot 0.0245 m, muzzle 1.569 m forward, 0.002 m up | 2.448 cm, 156.863 cm, 0.211 cm | sockets `GunMount` of `m252mortar_baseplate_Skeleton`, `Attach_Muzzle` of `m252mortar_tube_Skeleton` | EQUAL | one-off |
| UB-32 | 1.3075 / 1.430 / 0.251 | 126.026 cm above a swivel bone at -0.06 cm (+4.85 cm of the deployable, not read again) = 130.82 cm, 143.029 cm, 25.133 cm | `UB32_Swivel_Skeleton`, `UB-32_Gun_Skeleton` | EQUAL within 1 mm | one-off |
| HellCannon | 0.155 / 2.373 / 0.002 | 15.505 cm, 237.348 cm, 0.212 cm | `SK_HellCannon_Tripod_Skeleton`, `SK_HellCannon_Gun_Skeleton` | EQUAL | one-off |
| Tech.Mortar, Tech.UB-32, BM-21Grad, M1064M121 | 1.1789 / 1.6137 / 0.0388; 2.2659 / 1.4303 / 0.2513; 1.7694 / 2.7346 / 0.6366; 0.8174 / 3.4618 / 0.0035 | the same | Squad Ballistics' snapshot `tests/data/game_weapons.json` (its `tools/game_weapons.py`, client build 26234431): hull bone, turret socket, wheel radius | EQUAL | tool: `provenance.py` (VERIFIED rows `launch`) |
| Tech.Mortar scale offset | 5 deg | 5 deg: its sight shows mount + 40, the deployable mortar's mount + 45 | section 2.2 | EQUAL | tool for the 40 and the 45; INFERRED that the tubes are the same |
| BTR4-AGS | barrel 0.7346 deg above the reading, launch 3.4 m | 1.6 deg (socket `BarrelStart_AGS` pitch 1.7 in `SK_BTR4_Gun_Skeleton`, `BarrelSocketName` of `BP_BTR4_KBA117`; camera 0.1), launch 2.6264 m, muzzle 0.437 m forward, 0.0444 m up | Squad Ballistics' entry `AGS-30 / BTR-4 AGS` (snapshot); the camera's 0.1 by `mounts.py` | **DIFFERS, open (O1)** | tool for the camera and for the ranges below |
| Mk19 | 0.984 deg, 4 m, minimum 10 m | bore 0 (M1117, AAVP-7A1), 1.72 (M1151, RHIB), launch 2.31 to 3.22 m | Squad Ballistics' snapshot | **DIFFERS, open (O2)** | one-off |
| AGS-17 | launch 1 m, 9.08 deg/s, hold 47.81..85.85 | 0.347 m, 9.00 deg/s | `provenance.py` | DIFFERS, open (O4) | recorded UNVERIFIED in `provenance.py` |

O1 in numbers (`btr4_ags.mjs`, the calculator's solver): for a reading of 0, 2, 5, 10 and 20 degrees on level ground the
calculator's entry lands at 212, 412, 765, 1366 and 2448 m, the game files at 277, 502, 864, 1465 and 2529 m. The
calculator's values are upstream's fit; the generated entry `DF_AGS_30_BTR_4_AGS` of the same weapon uses the files'
values, so the two entries of one weapon disagree by 0.87 degrees. What is missing to decide: one shot in the game at a
known reading on level ground.

### 2.4 Minimum and maximum range

The game has no number for either: they follow from the muzzle velocity, the gravity and the mount's stop. Computed with
the calculator's own solver and launch points (`calculator.mjs`; `check_calculator.py` holds the rule): a weapon fired on
the high arc lands nearer the steeper it is laid, so its minimum distance is the range at the top of its mount when
that is below the vertical; one fired on the low arc lands nearer the flatter, so its minimum is the range at the bottom
of its mount when that is not below the horizon. Elevations are of the barrel (the reading plus the scale offset).

| Weapon, shell | Arc | Minimum distance (45.40.0) | Range at the low stop | Range at the high stop | Longest shot the mount allows | Longest at any elevation |
|---|---|---|---|---|---|---|
| Mortar, default | high | 51.8 m | 1236.94 m at 45 | 51.77 m at 88.8 | 1236.94 m | 1236.94 m |
| UB-32, default | low | 0 m | 3.40 m at -25 | 2082.44 m at 35 | 2082.44 m | 2184.33 m |
| HellCannon, default | high | 0 m | 320.50 m at 10 | 0.00 m at 90 | 924.43 m | 924.43 m |
| Tech.Mortar, default | high | 51.8 m | 1238.15 m at 45 | 51.76 m at 88.8 | 1238.15 m | 1238.15 m |
| Tech.UB-32, default | low | 147.1 m | 147.05 m at 0 | 2139.94 m at 50 | 2185.25 m | 2185.25 m |
| BM-21Grad, default | low | 985.1 m | 985.09 m at 14.2 | 1921.85 m at 55 | 2046.45 m | 2046.45 m |
| M1064M121, impact | high | 358 m | 2031.42 m at 50 | 357.96 m at 85 | 2031.42 m | 2063.26 m |
| M1064M121, nearSurface | high | 358 m | 2031.42 m at 50 | 357.96 m at 85 | 2031.42 m | 2063.26 m |
| BTR4-AGS, default | low | 0 m | 43.19 m at -4.1654 | 3685.41 m at 45.8346 | 3687.07 m | 3687.07 m |

Minimum distances: Mortar, Tech.Mortar, M1064M121 (both shells), BM-21Grad and Tech.UB-32 are stopped by their mounts and
carry the range at the stop to 0.1 m (D2). The UB-32 emplacement reaches the ground 3.4 m in front of it and the hell
cannon the vertical: no minimum. The BTR4-AGS depends on O1. Maximum: the mortar's 1236.94 m and the hell cannon's
924.43 m are the marker circles 1237 and 924 m (D4); the game's own table `UMG_MortarControl` lists 50 m steps to 1250 m.
The UB-32 and the M1064M121 fly further at an elevation their mounts do not allow than at any they do (O3). Mk19 and
AGS-17 are open with O2 and O4.

### 2.5 Explosion fields that are not in the files, and second explosions

`ASQProjectile` has C++ defaults for the explosion; a Blueprint that sets only some fields leaves the others to them
(`gamecheck.py` `NATIVE_EXPLOSION`: 115 damage, inner 5 m, outer 15 m, falloff 1, 0.2 m above the impact). S-5 (UB-32)
sets only the outer radius, the MK19, AGS-30 and VOG-17 grenades the inner radius and the height. The calculator's values
for those weapons are these defaults. Missing to prove them: the constructor of `ASQProjectile` in the Linux server
binary.

Primary and secondary explosion in the game (`resolved.json`, read once; damage, inner m, outer m, falloff, height m):
Mortar and Tech.Mortar 350, 0, 40, 7, 1 and 250, 1, 6, 3.5, 0.5; HellCannon 125, 1, 50, 1, 2 and 450, 3, 10, 3.5, 2;
BM-21 250, 2, 10, 1, 2 and 140, 1, 35, 1, 2; M121 impact 400, 0, 40, 7, 1 and 375, 1.5, 10, 3.5, 0.5; M121 airburst
0 damage and 100, 10, 60, 1.3, 10. The calculator keeps the wider one of each (O6).

### 2.6 Outside the scope: the generated entries

The run of `provenance.py` covers the 125 `DF_` entries (1423 rows: VERIFIED 1010, INFERRED 222, ASSUMED 161,
UNVERIFIED 30), none of which differs from the game. At the audit two rows did (`DF_AGS_17_emplacement_no_optic` and
`DF_AGS_17_iron_sights_emplacement`, the fitted top of the hold, O4); 45.37.0 set the game's 85.85 and 89.5.

## 3. Layers of the Deadline pool

### 3.1 Method and result

`game_audit.sh api`: `api_layers.py fetch` asks `get/layer?name=` for the 64 layers of
`tools/game_audit/data/deadline_pool.txt` and `get/layers?map=` for their 20 maps (84 answers, all 200), and
`api_layers.py compare` sets each answer against the game. Game side: the layer's `.umap` (capture zones, mains,
protection zones, corners; world positions composed along the attachment chain, `layers.py reduce`) and its data asset
`Gameplay_Layer_Data/<layer>` (`BP_SQLayer`: game mode, `TeamConfigs`, `FactionsList`, `FOBRadius`).

| Check | Result |
|---|---|
| API answers 200 and `rawName` is the layer | 64 / 64 |
| The layer is in the list of its map (`get/layers?map=`) | 64 / 64 |
| `mapId` is a map of `maps.js` | 64 / 64 |
| Minimap corners and texture | 64 / 64, largest difference 0.006 cm |
| Capture zones and mains | 1826 in the API, 1827 in the game; the one missing is `B2-IgorsHomestead` of `Gorodok_RAAS_v2`, an actor of the level that no lane or cluster names, so it is not played |
| Objective and main positions | largest difference 0.018 cm |
| Game mode, default faction unit and tickets of both teams | 64 / 64 |
| Faction units offered | 64 / 64 (14 to 86 units a layer, the same names) |
| Protection zones: 133, lock distance for deployables | 133 / 133 (150 m unless the layer sets another) |
| Protection zone shape (component of the same name and kind) | 27 / 27 boxes; 104 / 106 spheres, the other 2 negative in the API (D7) |

53 layers have no difference at all; the 11 others are in section 3.2.

### 3.2 Differences

* **D7, fixed in the calculator.** `GooseBay_AAS_v1` and `GooseBay_RAAS_v1`, "Team1 Protection Zone": the API gives
  `sphereRadius` -23637.88; the game's sphere is 15000 cm and the zone's scale 31149.6, 31149.6, -1.5759
  (`USphereComponent::GetScaledSphereRadius` takes the smallest size: 23637.9 cm).
  `tools/game_audit/data/protection_zones.json` holds the sphere, scale, radius and lock distance of the 270 round
  protection zones of 132 layers.
* **O7, upstream data.** Capture-area shapes of zones whose actor is pitched or rolled sit elsewhere in the API than
  in the game: `Harju_RAAS_v1` `A2-AmmunitionBunker` box 73.1 m and `C1-MimisMarsh` capsule 15.8 m; `Yehorivka_RAAS_v1`
  `B5-EastMogilyovo`, `B5-WestMogilyovo`, `C4-EastMogilyovo`, `C5-WestMogilyovo` capsules 4.7 m; `Yehorivka_RAAS_v2`
  `B3-EastMogilyovo`, `B3-WestMogilyovo` 4.7 m. Both offsets have the same length; the API's is the level's relative
  offset turned with pitch and roll of the opposite sign to the engine's `FRotator` convention (positive pitch raises
  the X axis, positive roll lowers the Y axis), which is what `layers.py` applies (`rotation_axes`). Which of the two the
  game shows was not checked in a running game. Zones with an uneven scale: `Lashkar_RAAS_v1` `A2-KumbarMaidanUpper`
  capsule radius 50 m in the API, 31.25 m in the game (25 m times the smaller of the scales 1.25 and 2.0), `B5-Lashkar`
  and `D4-Lashkar` sphere 60 m against 45 m (scale 0.75), `Mutaha_RAAS_v2` `C4-BarakaMarket` 60 m against 45 m. The
  positions of these objectives are exact; the shapes are only drawn.
* Names: the mains of `Harju_AAS_v3`, `Mestia_RAAS_v1` and `Narva_AAS_v3` are "US Main", "USA Main", "RUS Main",
  "MIL Main" in the game and "Main" in the API. Not used in any calculation.

### 3.3 Per layer

"FOB exclusion" is the game's radius of the layer and what the calculator draws for it (45.40.0), in metres.

| Layer | Corners, cm | Zones API / game (+mains) | Worst objective position, cm | Protection zones | Units API / game | FOB exclusion game / calculator | Differences |
|---|---|---|---|---|---|---|---|
| AlBasrah_AAS_v1 | 0.000 | 9 / 7+2 | 0.005 | 2 | 86 / 86 | 400 / 400 | - |
| AlBasrah_AAS_v2 | 0.000 | 9 / 7+2 | 0.004 | 2 | 86 / 86 | 400 / 400 | - |
| AlBasrah_AAS_v3_CL | 0.000 | 9 / 7+2 | 0.004 | 2 | 86 / 86 | 400 / 400 | - |
| AlBasrah_RAAS_v1 | 0.000 | 156 / 154+2 | 0.01 | 3 | 86 / 86 | 400 / 400 | - |
| AlBasrah_RAAS_v2 | 0.000 | 111 / 109+2 | 0.009 | 2 | 86 / 86 | 400 / 400 | - |
| AlBasrah_RAAS_v3 | 0.000 | 32 / 30+2 | 0.008 | 2 | 86 / 86 | 300 / 300 | - |
| Anvil_AAS_v1 | 0.000 | 7 / 5+2 | 0.003 | 2 | 80 / 80 | 400 / 400 | - |
| Anvil_RAAS_v1 | 0.000 | 38 / 36+2 | 0.008 | 2 | 80 / 80 | 400 / 400 | - |
| Anvil_RAAS_v2 | 0.000 | 39 / 37+2 | 0.008 | 2 | 80 / 80 | 400 / 400 | - |
| BlackCoast_AAS_v1 | 0.004 | 7 / 5+2 | 0.003 | 2 | 79 / 79 | 400 / 400 | - |
| BlackCoast_AAS_v2 | 0.004 | 7 / 5+2 | 0.003 | 2 | 79 / 79 | 400 / 400 | - |
| BlackCoast_RAAS_v1 | 0.004 | 78 / 76+2 | 0.005 | 3 | 79 / 79 | 400 / 400 | - |
| BlackCoast_RAAS_v2 | 0.004 | 50 / 48+2 | 0.005 | 2 | 79 / 79 | 400 / 400 | - |
| Chora_AAS_v1 | 0.000 | 8 / 6+2 | 0.004 | 2 | 15 / 15 | 300 / 300 | - |
| Chora_AAS_v2 | 0.000 | 7 / 5+2 | 0.003 | 2 | 15 / 15 | 300 / 300 | - |
| Chora_AAS_v3 | 0.000 | 8 / 6+2 | 0.004 | 2 | 15 / 15 | 300 / 300 | - |
| Chora_RAAS_v1 | 0.000 | 31 / 29+2 | 0.008 | 2 | 15 / 15 | 300 / 300 | - |
| Fallujah_AAS_v1 | 0.000 | 9 / 7+2 | 0.006 | 2 | 77 / 77 | 400 / 400 | - |
| Fallujah_RAAS_v1 | 0.000 | 55 / 53+2 | 0.004 | 2 | 77 / 77 | 400 / 400 | - |
| Fallujah_RAAS_v2 | 0.000 | 46 / 44+2 | 0.003 | 2 | 77 / 77 | 400 / 400 | - |
| FoolsRoad_AAS_v1 | 0.002 | 7 / 5+2 | 0.002 | 2 | 15 / 15 | 300 / 300 | - |
| FoolsRoad_AAS_v2 | 0.002 | 9 / 7+2 | 0.004 | 2 | 15 / 15 | 300 / 300 | - |
| FoolsRoad_RAAS_v1 | 0.002 | 21 / 19+2 | 0.006 | 2 | 15 / 15 | 300 / 300 | - |
| GooseBay_AAS_v1 | 0.004 | 8 / 6+2 | 0.011 | 2 | 67 / 67 | 400 / 400 | protection zone Team1 Protection Zone: radius -23637.9 in the API is negative, 23637.9 in the game |
| GooseBay_RAAS_v1 | 0.004 | 54 / 52+2 | 0.011 | 2 | 67 / 67 | 400 / 400 | protection zone Team1 Protection Zone: radius -23637.9 in the API is negative, 23637.9 in the game |
| Gorodok_AAS_v1 | 0.000 | 8 / 6+2 | 0.006 | 2 | 79 / 79 | 400 / 400 | - |
| Gorodok_RAAS_v1 | 0.000 | 45 / 43+2 | 0.006 | 2 | 79 / 79 | 400 / 400 | - |
| Gorodok_RAAS_v2 | 0.000 | 38 / 37+2 | 0.008 | 2 | 79 / 79 | 400 / 400 | game zones missing in the API: ['B2-IgorsHomestead'] |
| Harju_AAS_v1 | 0.000 | 9 / 7+2 | 0.004 | 2 | 74 / 74 | 400 / 400 | - |
| Harju_AAS_v2 | 0.000 | 7 / 5+2 | 0.006 | 2 | 14 / 14 | 400 / 400 | - |
| Harju_AAS_v3 | 0.000 | 7 / 5+2 | 0.004 | 2 | 14 / 14 | 400 / 400 | flag names differ (API, game): [['Main', 'US Main']] |
| Harju_RAAS_v1 | 0.000 | 71 / 69+2 | 0.003 | 2 | 74 / 74 | 400 / 400 | capture-area positions differ: A2-AmmunitionBunker/Box 7305.4 cm (zone tilted), C1-MimisMarsh/Capsule 1582.0 cm (zone tilted) |
| Harju_RAAS_v2 | 0.000 | 16 / 14+2 | 0.005 | 2 | 74 / 74 | 400 / 400 | - |
| Kohat_AAS_v1 | 0.000 | 10 / 8+2 | 0.005 | 4 | 80 / 80 | 400 / 400 | - |
| Kokan_AAS_v2 | 0.003 | 7 / 5+2 | 0.001 | 2 | 15 / 15 | 300 / 300 | - |
| Kokan_RAAS_v1 | 0.003 | 28 / 26+2 | 0.001 | 2 | 15 / 15 | 300 / 300 | - |
| Lashkar_AAS_v1 | 0.000 | 9 / 7+2 | 0.005 | 2 | 80 / 80 | 400 / 400 | - |
| Lashkar_AAS_v2 | 0.000 | 9 / 7+2 | 0.004 | 2 | 80 / 80 | 400 / 400 | - |
| Lashkar_RAAS_v1 | 0.000 | 51 / 49+2 | 0.004 | 2 | 80 / 80 | 400 / 400 | capture-area shapes: ['A2-KumbarMaidanUpper/Capsule: capsule radius 5000 in the API, 3125 in the game', 'B5-Lashkar/Sphere: radius 6000 in the API, 4500 in the game', 'D4-Lashkar/Sphere: radius 6000 in the API, 4500 in the game'] |
| Logar_AAS_v1 | 0.002 | 10 / 8+2 | 0.002 | 2 | 15 / 15 | 300 / 300 | - |
| Manicouagan_AAS_v1 | 0.004 | 9 / 7+2 | 0.012 | 2 | 67 / 67 | 400 / 400 | - |
| Manicouagan_AAS_v2 | 0.004 | 9 / 7+2 | 0.014 | 2 | 67 / 67 | 400 / 400 | - |
| Manicouagan_AAS_v3 | 0.004 | 9 / 7+2 | 0.018 | 2 | 67 / 67 | 400 / 400 | - |
| Manicouagan_RAAS_v1 | 0.004 | 49 / 47+2 | 0.008 | 2 | 67 / 67 | 400 / 400 | - |
| Manicouagan_RAAS_v2 | 0.004 | 54 / 52+2 | 0.007 | 2 | 67 / 67 | 400 / 400 | - |
| Mestia_AAS_v1 | 0.000 | 9 / 7+2 | 0.003 | 2 | 15 / 15 | 400 / 400 | - |
| Mestia_AAS_v2 | 0.000 | 7 / 5+2 | 0.003 | 2 | 15 / 15 | 400 / 400 | - |
| Mestia_RAAS_v1 | 0.000 | 12 / 10+2 | 0.004 | 2 | 15 / 15 | 400 / 400 | flag names differ (API, game): [['Main', 'USA Main'], ['Main', 'MIL Main']] |
| Mutaha_AAS_v1 | 0.000 | 7 / 5+2 | 0.007 | 2 | 77 / 77 | 400 / 400 | - |
| Mutaha_AAS_v2 | 0.000 | 7 / 5+2 | 0.007 | 2 | 77 / 77 | 400 / 400 | - |
| Mutaha_RAAS_v1 | 0.000 | 38 / 36+2 | 0.006 | 2 | 77 / 77 | 400 / 400 | - |
| Mutaha_RAAS_v2 | 0.000 | 42 / 40+2 | 0.003 | 2 | 77 / 77 | 400 / 400 | capture-area shapes: ['C4-BarakaMarket/Sphere: radius 6000 in the API, 4500 in the game'] |
| Narva_AAS_v1 | 0.005 | 8 / 6+2 | 0.005 | 2 | 74 / 74 | 400 / 400 | - |
| Narva_AAS_v2 | 0.005 | 8 / 6+2 | 0.004 | 2 | 74 / 74 | 400 / 400 | - |
| Narva_AAS_v3 | 0.005 | 7 / 5+2 | 0.006 | 2 | 74 / 74 | 400 / 400 | flag names differ (API, game): [['Main', 'RUS Main'], ['Main', 'USA Main']] |
| Narva_RAAS_v1 | 0.005 | 64 / 62+2 | 0.006 | 2 | 74 / 74 | 400 / 400 | - |
| Skorpo_RAAS_v1 | 0.000 | 60 / 58+2 | 0.018 | 3 | 74 / 74 | 400 / 400 | - |
| Tallil_AAS_v1 | 0.004 | 9 / 7+2 | 0.006 | 2 | 77 / 77 | 400 / 400 | - |
| Tallil_RAAS_v1 | 0.004 | 67 / 65+2 | 0.005 | 2 | 77 / 77 | 400 / 400 | - |
| Tallil_RAAS_v2 | 0.004 | 69 / 67+2 | 0.004 | 2 | 77 / 77 | 400 / 400 | - |
| Yehorivka_AAS_v1 | 0.006 | 9 / 7+2 | 0.005 | 2 | 79 / 79 | 400 / 400 | - |
| Yehorivka_AAS_v2 | 0.006 | 9 / 7+2 | 0.013 | 2 | 79 / 79 | 400 / 400 | - |
| Yehorivka_RAAS_v1 | 0.006 | 62 / 60+2 | 0.008 | 2 | 79 / 79 | 400 / 400 | capture-area positions differ: B5-EastMogilyovo/Capsule 472.3 cm (zone tilted), B5-WestMogilyovo/Capsule 472.3 cm (zone tilted), C4-EastMogilyovo/Capsule 472.3 cm (zone tilted), C5-WestMogilyovo/Capsule 472.3 cm (zone tilted) |
| Yehorivka_RAAS_v2 | 0.006 | 62 / 60+2 | 0.005 | 2 | 79 / 79 | 400 / 400 | capture-area positions differ: B3-EastMogilyovo/Capsule 472.3 cm (zone tilted), B3-WestMogilyovo/Capsule 472.3 cm (zone tilted) |

## 4. Constants

| Constant | Calculator | Game | Source | Verdict | Evidence |
|---|---|---|---|---|---|
| World gravity | 9.80 m/s^2 (`src/app.js`) | -980 cm/s^2 engine default; none of the 219 `SQWorldSettings` has a gravity key (their scalar keys: sea level, kill Z, helicopter altitude threshold, lighting and navigation flags) | `world` of each layer in `game_layers.json` (`layers.py reduce`) | EQUAL for the layers; the engine config of the package is not exposed by the extractor (it lists `.uasset`, `.umap`, `.ubulk` only) and was not found as text in `pakchunk0-LinuxServer.pak`, so the absence of an override in `DefaultEngine.ini` is the earlier reading of the server binary (thesis 1.1), not re-proven. The game's own tables use 9.81 (`UMG_MortarControl`, `BM21_GunnerReticle`, `W_MortarControl_M121_Advanced`): display only | tool for the layers' keys; one-off for the rest |
| FOB construction radius | 150 m | 150 m in every row a layer uses | `DT_FOBExclusionRadius` rows `01_Small`, `02_Medium` (`tools/game_audit/data/fob_radius.json`) | EQUAL | tool |
| FOB exclusion radius | per layer since 45.38.0: 300 m on Chora, Fools Road, Kokan, Logar, Sumari and on the 38 layers of `SMALL_FOB_LAYERS`; 400 m elsewhere | per layer: `FOBRadius` of `BP_SQLayer` (default `02_Medium` 400 m; 77 of the 221 layers `01_Small` 300 m, 38 of them on maps whose other layers have 400 m) | 247 layer data assets, `tools/game_audit/data/fob_radius.json` | EQUAL (D6: at the audit one radius per map) | tool |
| Mortar marker circle | 1237 m | 1236.94 m | section 2.4 | EQUAL | tool |
| Hell cannon marker circle | 924 m | 924.43 m | section 2.4 | EQUAL (D4: 923 m at the audit) | tool |
| Protection zone and no-deploy circle | from the API: radius, radius + lock distance; a negative radius is taken by its size since 45.38.0 | `Gameplay_TeamZone` sphere and `DeployableLockDistance` (default 15000) | section 3.1 | EQUAL (D7) | tool |
| Structure damage (`src/data/structureDamage.js`: 44 structure groups, 53 ammunition entries) | generated | regenerated with `tools/volumetric/semantics/structure_damage.py export`: byte-identical. The audit also rebuilt the data file from the dump `~/data/structdmg` (`build`): health, damage-type tables and explosion fields identical, only the Squad Ballistics names of four ammunition rows differed (renamed sights) | `tools/volumetric/data/structure_damage.json` | EQUAL | tool for the export (rerun 2026-11-10); the rebuild was not rerun |
| Grid: 300 m keypads, 3 x 3 sub-keypads | 300 / 100 / 33.3 m | scale factors 1, 3, 9 in `W_SQMapGridLines`; the 300 m is native | thesis 2.3, not read again | EQUAL (earlier audit) | - |
| UAV marker circle | 300 m | `BP_CommandActor_UAVMaster` and its four children hold a flight height of 400 m, `UAV_MQ9_ADF` a placement distance of 100 to 250 m; no radius of 300 m | Blueprints dumped once | **not checked**: the orbit is not in the properties read | one-off |
| Soldier height 1.8 m and 100 health in the damage radii | `squadWeapons.js`, `squadDamage.js` | native defaults of the soldier class | - | **not checked**: not in the paks | - |

## 5. The rerun of 2026-11-10

Everything marked "tool" above was produced by `tools/game_audit` (worktree of the commit that adds it) on a fresh
extraction of build 26005357, not on the audit's saved dumps: the extractor was built from `tools/heightmaps/extractor`
at CUE4Parse `808a7d65`, and `extract-mounts` (29 assets), `extract-layer-data` (250), `extract-layers` (219) and
`extract-landscapes` (29 levels) were run in full, then `derive`, `check` and `api` (84 new requests).

| Value | The audit | The rerun | Path |
|---|---|---|---|
| Mortar mount pitch and what the sight adds | 0..43.8, +45 | 0..43.8, +45: reading 45..88.8 | `mounts.py`: `PitchInterval` of `BP_GenericDeployableMortarVehicle`; `Add_DoubleDouble(CachedTubePitch, 45.0)` in `UMG_MortarControl` |
| The other mounts (UB-32, HellCannon, Tech.Mortar, Tech.UB-32, BM-21Grad, M1064M121, BTR4-AGS) | section 2.2 | the same | `mounts.py` |
| Minimum distances | 51.77, 51.76, 357.96, 985.09, 147.12 m | 51.77, 51.76, 357.96, 985.09, **147.05** m | `calculator.mjs` |
| BTR4-AGS display range | -4.9..45.1 | -4.9..45.1 | `mounts.py`: `PitchInterval` -5..45 of `BP_BMP1TS_Turret`, `FirstPersonCamera` pitch 0.1 |
| Hell cannon's longest shot | 924.43 m | 924.43 m | `calculator.mjs` |
| Landscape of the seven corrected maps | section 1.2 | the same to the centimetre | `landscapes.py` |
| Landscape of the other maps | equal on all 18 | equal on 17; **Skorpo differs** (O9, fixed in SquadCalc 45.44.0) | `landscapes.py` |
| Minimap corners, 25 maps | `game_corners.json` | identical file | `layers.py`, `minimap_corners.py table` |
| FOB radius per layer | 221 layers, 77 small, 38 of them on 400 m maps | the same rows for all 221 | `fob_radius.py` |
| Protection zone of Goose Bay AAS v1 and RAAS v1 | sphere 15000 cm, scale 31149.6, 31149.6, -1.5759 | the same: 23637.9 cm | `layers.py zones` |
| Layers of the pool against the API | section 3.1 | the same counts and the same 11 layers with a difference | `api_layers.py` |
| O1 in numbers | 212 to 2448 m, 277 to 2529 m | the same | `btr4_ags.mjs` |

What the rerun changed in the audit's statements:

1. **Technical UB-32, 147.12 m.** The audit computed the range at 0.001 degrees; at the stop, 0 degrees, the
   calculator's solver gives 147.05 m (the range grows by 71 m per degree there). Both apps carry 147.1 m, which is
   147.05 m to 0.1 m and inside the tolerance of their tests (0.05 m and 0.1 m), so no value changes.
2. **Skorpo's landscape (O9).** One rule for all 25 maps makes the Skorpo row a difference the audit did not list.
3. **M1064M121, the tube's rest.** The audit took the 50 degrees from Squad Ballistics' snapshot of the client build.
   The server build has it: the component `Muzzle` of `BP_M1064A3_MortarTurret` is pitched 49.99999 degrees.
4. **BM-21, the rail's rest.** Read from the reference pose of `SKEL_BM21_Launcher` (the root bone is pitched 14.2
   degrees, the socket `Attach_Muzzle` sits unturned on its child `pitch_swivel`); the reticle's own table agrees
   (`MinAngle` 14.2, `AngleToCover` 55.0 = 40.8 + 14.2).
5. **Versions.** The calculator moved from 45.38.0 to 45.40.0 and the generated entries from 115 to 125; the two
   AGS-17 rows that differed are equal.

Not rerun, and marked "one-off" above: the skeleton reads of the three tripod launch points, the Mk19 mounts, the
second explosions, the gravity keys beyond the layers, the UAV Blueprints, the rebuild of the structure-damage data.

## 6. Reproduction

Needs the dedicated server (SteamCMD app 403240) in `~/data/squad-server`, Docker with the .NET SDK image, Node 22+ and
the checkouts of SquadCalc and Squad Ballistics. Environment and defaults: `tools/game_audit/game_audit.sh` without
arguments.

```sh
tools/heightmaps/heightmaps.sh setup                 # builds the extractor into $WORK/bin
tools/game_audit/game_audit.sh extract-mounts        # $WORK/audit/blueprints
tools/game_audit/game_audit.sh extract-layer-data    # $WORK/audit/layerdata
tools/game_audit/game_audit.sh extract-landscapes    # $WORK/landscapes (the same files as heightmaps.sh extract)
tools/game_audit/game_audit.sh extract-layers        # $WORK/audit/layers, 219 x .json.gz
tools/game_audit/game_audit.sh derive                # tools/game_audit/data/*.json; git diff shows a change
tools/game_audit/game_audit.sh check                 # sections 1, 2.2, 2.4 and 4: 0 differences, 3 known
tools/game_audit/game_audit.sh api                   # section 3
node --import ./tools/direct_fire/register.mjs tools/game_audit/btr4_ags.mjs ~/agl/SquadCalc ~/dev/Squad-Ballistics   # O1
python3 tools/game_ballistics/provenance.py --resolved ~/data/squad-weapons/resolved.json --dump ~/data/squad-weapons/dump \
    --sb ~/dev/Squad-Ballistics --sc ~/agl/SquadCalc --check tools/volumetric/docs                                  # sections 2.1, 2.6
python3 tools/direct_fire/compare.py ~/dev/Squad-Ballistics ~/agl/SquadCalc                                         # the two apps agree
```

| File | What |
|---|---|
| `tools/game_audit/data/source.json` | the build the data was read from |
| `tools/game_audit/data/mount_limits.json` | pitch range, sight offset and reading of the 8 mounts (section 2.2) |
| `tools/game_audit/data/landscapes.json` | landscape actors of the 25 maps (section 1.2) |
| `tools/game_audit/data/minimap_corners.json` | the corner table of `minimap_corners.py` (section 1.1) |
| `tools/game_audit/data/fob_radius.json` | the rows of `DT_FOBExclusionRadius` and the row of each of the 221 layers (section 4) |
| `tools/game_audit/data/protection_zones.json` | the round protection zones of every layer (section 3.2) |
| `tools/game_audit/data/deadline_pool.txt` | the 64 layers of section 3 |
| `$WORK/audit/game_layers.json`, `api/`, `api_compare.json` | not committed (3 MB, 35 MB): zones and corners per layer, the API's answers, the comparison per layer |

The fixes in the calculator and the test that fails without each:

| Commit | Change | Test |
|---|---|---|
| `35e56973b` | D1 to D4: `src/data/weapons.js` (mortar top elevation, five minimum distances, BTR4-AGS range), `src/js/squadMinimap.js` (hell cannon circle) | `tests/weapons.test.mjs`: "the elevation range of an artillery weapon is the pitch range of its mount in the game plus the sight's offset", "the minimum distance of a weapon stopped by its mount is the range on level ground at that stop", "the range circle of a mortar or hell cannon marker is the longest shot of that weapon on level ground" |
| `69bd47058` | D5: `SDK_data.heightmap` of seven maps | `tests/maps.test.mjs`: "the landscape origin, size and scale of every map are the game's (origin in whole metres)" |
| `cede4aa71` | D6: `SMALL_FOB_LAYERS`, `fobExclusionRadius` in `src/data/maps.js`, used by the FOB marker in `src/js/squadMinimap.js` | `tests/maps.test.mjs`: "the FOB exclusion radius is the loaded layer's, and the map's without a layer", "every layer listed with the small FOB radius belongs to a map whose regular layers have the medium one" |
| `d67f8d190` | D7: `src/js/protectionZone.js` (`protectionRadii`), used by `src/js/squadLayer.js` | `tests/protectionZone.test.mjs`: "Goose Bay's first main base: the zone's negative scale gives a negative radius, the game's is 236 m" |
