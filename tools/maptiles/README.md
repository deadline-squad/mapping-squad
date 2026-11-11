# Detailed tactical map tiles from the game files

The "Detailed" layer of the Deadline SquadCalc: a topographic map of every map, drawn from the exact
game data of the Squad dedicated server and client paks, with tiles down to 0.07–0.125 m per pixel (see "Tile frame"). Served as 256 px
webp tiles from `/maptiles/<map>/<z>/<x>_<y>.webp` with `/maptiles/<map>/meta.json`
(`src/js/squadMinimap.js` `showDetailedLayer`; a map without tiles shows the upstream basemap).

## What is drawn, and from which data

Two builds feed the layer. **Server** = the Squad dedicated server, build 26005357: landscape collision (ground, physical
materials), foliage collision, landscape splines, water actors, static mesh collision. **Client** = the Squad game client,
build 26234431: the scene of `tools/maprender` (`maprender.sh scene`, `$SCENES/<map>`): LOD 0 meshes, materials and placements, the
same data the Standard HD layer is drawn from. `meta.json` of the tiles names both. The two builds place the same objects
(`py/compare_builds.py`: on Mutaha 99.7 % of the server's static mesh placements, 9 462 of 9 491, have the client's placement of
the same mesh within 0.5 m, the rest are 28 spline editor meshes and one wall; all 383 424 foliage instances match).

| Layer | Source | Resolution |
|---|---|---|
| Ground cover (grass, tall grass, dirt, gravel, mud, rock, sand, forest floor, asphalt, snow) | server: the dominant physical material of every landscape quad, cooked into the landscape collision heightfields (the server build has no render weightmaps) | 1–1.2 m quads, edges softened |
| Hillshade, slope tint | server: bare ground, the landscape collision heightfields, SquadHeight outside the game landscape (`tools/heightmaps`); where the server has nothing there (SquadHeight's floor, e.g. the background mountains of Skorpo and Blackcoast, which only the client has), the top of the client scene's scenery meshes (`py/scene_prep.py` `scenery_ground`, `top_ground.npy`); a void no scenery covers stays at the floor (the open sea). On the landscape the scenery is the ground too where it lies above the landscape, the server collides with it (at least half of the area's cells that rise 0.3 m and more hold the mesh's surface in the server's static collision) and it continues the ground (lifted to the mesh, at least half of the cells along the area's rim step less than 2 m to the ground beside them): along Gorodok's edges the landscape falls away under the `_Vista` mesh, 2 to 3 m below it at the east frame and 15 m in the west, where the served heightmap holds the mesh's height, and its last 16 m repeat one height per row, which the hillshade drew as bars. A mesh without collision, or a block that stands on the ground (Al Basrah's Vista city), stays scenery. The shading is a multi-directional oblique-weighted hillshade (MDOW, Mark 1992: lights from the north, north-west, west and south-west at 45 degrees, each weighted by sin²(aspect − azimuth), the formula of the relief layer), its spread raised 2.5 times to the contrast one light gave (the four lights average out: the ratio of the single light's spread to the four lights' is 1.8 to 2.7 over 21 maps with 2 m gradients, Sanxian 1.83, Al Basrah 2.65, Kamdesh 2.70; 2.5 is a typical value), exaggerated at the overview zooms; the `colour` style keeps one light matched to the game's minimap | 1 m grid, cubic B-spline between samples |
| Contours, labelled | the same ground, heights above the map's lowest point (`z_min_m` of the served heightmap, the scale of SquadCalc's height readouts); minor 1 or 2 m at the finest zoom (2 m on hilly maps), major 10 m, coarser at smaller scales; drawn under water, roads and buildings | per pixel |
| Water | server: ocean actors' sea level (weather layers), static water planes (ponds; not the water meshes laid along splines, whose bounds are the undeformed mesh: `features.water_planes`); client: the lakes and reservoirs, the `BP_Lake*` actors of the weather layers (`py/scene_objects.py` `water_planes`, `top_water.json`), each a flat `SM_env_river` plane scaled to the lake, which the server holds no body for, and the rivers and ponds as the top of their meshes, bent along their splines, on the 1 m grid (`scene_prep.river_surface`, `top_water_surface.npy`: a river's surface is its mesh's, up to 0.5 m above the spline's centre line on Anvil). Water is where the ground lies below a surface, as the game draws it over the landscape, so a dam or a bank that rises above it ends the water and the surface's own edge ends it where the ground stays lower; the colour runs from shallow to deep with the square root of the depth up to 12 m (half of the range in the first 3 m, where a ford differs from a channel); the shore is smoothed over 0.6 m and drawn as a line 1.2 px wide | per pixel, rivers 1 m |
| Roads, tracks, pavements, railways, trenches, hedges | server: `LandscapeSplineSegment` edges (the width the meshes are laid with), classified by the meshes along them. Roads, tracks and pavements are narrowed to the width their meshes show from above (client: `py/road_width.py`, `top_lines.json`; the width is measured across the mesh axis that the spline lays level once its roll has turned the mesh (`spline_mesh.axis_across`: X for a mesh that runs along Y, which the landscape spline stands up by a roll of -90 degrees; 474 of the 102 115 road components of the 25 maps are such, all of them opaque over their whole width); the opacity of the mesh's material across its width: the colour texture's alpha above the clip of 1/3 for a masked material, the `Masks` texture's green channel for road layers, the ramp over a fifth of the width at each side of a road painted into the virtual texture, otherwise all of it; the segment takes the variant its spline mesh components have, so a dirt road of 6 m shows about 5.2 m and a road without a fringe keeps its width) | exact |
| Tracks painted into the landscape | client: the weight of the landscape's path layers (`Path`, `mat05_path`, `mat06_rockpath`, `Grusvei`) from the scene's weightmaps (`py/landscape_paths.py`), drawn in the dirt track's colour where they weigh half and more; a pixel coarser than 2 m takes the highest weight of its metres, so a footpath stays a line a pixel wide at the overview zooms instead of averaging away | 1 m grid, bilinear |
| Crop fields | client: the scene's crop plants (wheat, maize, poppies, cannabis, potatoes by mesh name, `crowns.CROP_NAME`; wild field flowers, field grass and weeds are not crops), each the disc of its mesh's reach, summed on the 1 m grid and smoothed by 1.5 m so a field's rows close into its area (`crowns.crop_fields`, `top_crops.npy`); drawn where they cover 30–70 % of the ground and more, coloured from low crops (0.6 m, wheat and poppies) to tall ones (2 m, maize and cannabis: what hides a soldier), with a diagonal hatch at 1 m per pixel and finer (`render.draw_crops`). The game-colour style leaves them to the game's texture | 1 m grid, bilinear |
| Buildings, walls, rocks, props, bridges | client: the visible LOD 0 meshes seen from above (`py/scene_objects.py`, `py/scene_prep.py`): highest surface and class on a 0.1 m grid sampled 2 x 2 per cell (anti-aliased edges), height above the ground. The highest surface over each sample is found on the GPU (`py/scene_raster_gpu.py`: an orthographic camera looking down with a "greater" depth test, one instanced draw per mesh) or with `SCENE_RASTER=cpu` by the numpy rasterizer of `tools/heightmaps`; the two differ at samples on a triangle's edge (Narva: 26 591 018 against 26 590 909 covered cells, 1 161 covered by one only, 1 004 of them partly; heights equal in 99.83 % of the cells both cover and within 1 cm in 99.99 %; `py/test_scene_gpu.py`); spline meshes are bent as the engine bends them, the component's roll included (`spline_mesh.bend_along_spline` of `tools/heightmaps/py`, the one deformation that this layer and the Standard HD renderer draw: a mesh that runs along its Y axis lies on its side without the quarter turn the landscape splines give it; with the roll the box of a bent mesh is the box of the server's cooked collision of the same component, to 1 cm for the pipelines, crash barriers and railway tracks of Manicouagan, without it 3.2, 0.9 and 1.3 m off); colour by class and, for structures, height over the ground smoothed by a 6 m Gaussian (`scene_prep.GROUND_BASE_SIGMA_M`, `top_ground_base.npy`: the edge of a jetty under a pier's deck or the landscape's 1 m steps do not show through a flat roof), roof ridges and levels by shading the top itself (ground plus height, so a roof on a slope is not shaded as the slope), 1 px outline at every zoom, shadows to the south-east (only from objects at least 2 px wide: a thinner post or wire casts none). The class is the mesh name's (`features.object_class`); a mesh the name leaves a plain structure is vegetation when at least half of its triangles carry a foliage-shaded (`MSM_TwoSidedFoliage`) material with a plant name (hedges, brambles, vineyard rows, orchard trees), drawn green like hedges, while tents, awnings and camouflage nets stay structures. Left out: hidden components, `/Coop/`, `/Tutorials/`, `_Vista` and `_Editor_Only` levels (Blackcoast's POI size rings), translucent (glass, decals), additive and developer materials, water, flowers, crops, low grass, weeds, ivy and leaf litter (by whole-word names: wall corners are kept), and what is narrower than 0.3 m except walls and bridges (cables, wires). Objects that the scene raster does not draw but the server's static collision holds (the frames of unfinished tents, fences, signs and stands thinner than 0.3 m) stay from the old 0.25 m raster of `prep.py` where no scene object lies within 2 m and the scene shows them: at least half of a run's metres hold, in them or beside them, an object of the scene however thin, 0.3 m and more above the ground: a cell of the scene raster as it is before the thin objects are taken out, or an edge of a shown mesh, so that a wire or a fence of one sheet counts wherever it lies between the raster's points (`scene_prep.unthinned_objects`, `shown_runs`). A run of which the scene shows nothing is collision without a mesh over it, and is not kept: the collision of Manicouagan's dam meshes that stands 2 to 3 m above the reservoir where the game shows water (275 m2), the collision of background mountains and terrain meshes along a map's edge (Kamdesh's mountains, 1 905 m2), of river and lake planes (Anvil 1 119 m2, Chora 500 m2), of road meshes, of the gap in a ruined wall. On the 25 maps the two kinds do not meet: of 29 690 m2 of such runs 25 159 m2 in 1 423 runs are shown in at least three quarters of their metres and stay, 4 531 m2 in 119 runs are shown in at most a tenth and go (on 13 maps: Al Basrah 167 m2, Anvil 1 143, Chora 510, Gorodok 117, Harju 30, Jensen 7, Kamdesh 1 905, Kohat 26, Kokan 14, Manicouagan 507, Skorpo 36, Sumari 15, Yehorivka 54). Not kept either (`scene_prep.old_non_objects`): what only SquadHeight holds, the cells in no box of a static mesh placement with collision (SquadHeight was traced in the SDK on another version of the map, and what the game has of its Blueprint buildings is in the client scene: Al Basrah's north edge had blocks of a Vista city that the build does not have, 3 to 12 m high, Black Coast steps across a river); ground cover with collision (Yehorivka's maize plants set by hand); cells off the landscape, where the ground is SquadHeight's surface already (Gorodok's first column stood as a wall 1 m wide and 11 m high along the west edge); a flat sheet the game does not show (`scene_objects.sheet_groups`, `scene_prep.legacy_sheets`: Goose Bay's translucent ice over its ponds, which the server holds as an object standing at the sheet's height over the lowest ground of each metre, to 0.25 m); the railway tracks between the edges of their spline segments, whose collision stands 0.3 to 0.45 m high while the tiles draw the railway from its spline; and what has the top of a mesh the scene has as terrain or water (background mountains, `_Vista` levels, rivers: `scene_objects.surface_groups`). A mesh counts as the old object's top where it rises 2 m and more above the ground, or 0.3 m and more when the cell's top is flush with it within 0.25 m (`scene_prep.legacy_terrain`): the landscape collision can lie flat under a scenery mesh that is the ground along a map's edge (Gorodok: a band 40 to 60 m wide on every side, rising 0.3 to 2.3 m), and the old raster's 'object' there is that terrain, not a building. A road surface mesh that paints the landscape's virtual texture (`_RVT` material) is a bridge: only a bridge deck lifts it above the ground | 0.1 m |
| Summits | the ground's tops that are the highest point within 40 m and stand 4 m and more above the mean ground 60 m around them (`render.summits`, on the ground smoothed by 4 m), not beyond the landscape, under water or within 8 m of the map's edge: a dot and the height, the height contours are labelled with; the highest rise first, never closer than 180 px (`render.summits_of`) | 1 m grid |
| Roof height labels | connected structures of 60 m² and 3 m or more on the scene's 1 m grid, their 98th percentile height above ground, from the zoom before the first Detailed layer's finest (pixel size 0.33 m) on, never overlapping each other or a contour label. Labels and contour lines keep their size on screen: up to that first layer's finest zoom 12 pt (roof) and 11 pt (contour) text with a 2 px halo, then doubled at every finer zoom (`render.label_scale`), as the browser used to stretch them | — |
| Trees, bushes, palms, rocks | client: every foliage instance (flowers, crops, grass and other ground cover left out by the objects' whole-word name rule) drawn as the top-down outline of its mesh's LOD 0 (a stamp taken once per mesh: `py/crowns.py`), turned and scaled with the instance, lit from the map's light and coloured by class and species (a crown at most 8 px across is cut from a cache of stamps turned and scaled to 7.5 degree and quarter pixel steps: its edge moves by at most a quarter of a pixel, and the forests of the overview zooms draw four times faster); trunk dot where the server's collision data says the trunk blocks; forest density where crowns are below a pixel | exact positions |

Symbols, with the measured reason of each (`py/render.py`; contrast figures by `maptiles.sh palette`, `py/palette_contrast.py`: CIEDE2000
of the colours as drawn, under normal vision and the protanopia, deuteranopia and tritanopia of Machado et al. 2009; map colours are
told apart reliably from about 10, Brychtova & Coltekin 2017):

* **Structures are a slate ramp** (CIELAB hue 285 degrees, lightness 74 to 25 in even steps by height), a hue no ground, crown or rock has. The
  earlier grey-brown was 8.5 from a conifer under deuteranopia (21.2 normal) and 9.4 from a shadow; the slate is 25.7 (29.8) and 19.4.
* **Decks and paved surfaces** (`features.BRIDGE`: bridges, piers, wharves, quays, and the pavement, kerb and road line meshes) are light with
  a dark rim; lower than 1 m above the ground (`PAVED_MAX_M`) they lie on it and are drawn flat in the pavement's colour, without rim.
* **Rocks** keep their shape but have a grey rim instead of the buildings' dark one: they were the loudest symbol of Gorodok and Fallujah.
* **Dirt roads have a casing** at half the strength of an asphalt road's: the fill differs from grass mostly in hue (2.6 under deuteranopia),
  the casing by 10 and more on every ground but dirt itself.
* **A railway has cross ties** every 4 m at 1 m per pixel and finer: as a plain dark line it was 2.7 from a wall.
* **Beyond the game's landscape** (cover `NO_COVER`) the ground is drawn towards a grey, with a third of the relief and without contours, labels
  or summits: the low-poly backdrop is never played on.
* **No contour label on water** (`render.under_water`) and none beyond the landscape.
* The page's legend is written by the renderer: `legend` in `meta.json` (`render.legend`) names every symbol's colour as drawn.

Class rules of the objects (`features.object_class`, checked against the 5 143 mesh names of the 25 client scenes): "plant" is no plant in
"PowerPlant" (73 meshes of that set were vegetation), and decks and paved surfaces are one class (164 meshes were structures).

Objects stay legible at every zoom by three rules (`py/render.py`, `draw_objects`), measured on the Goose Bay, Mutaha and
Manicouagan layers against the game's minimap textures (`maptiles.sh outline`):

* **A roof contrasts with the ground around it.** The height ramp (`STRUCTURE_RAMP`: light beige for low buildings, dark for tall
  ones) is squeezed towards its darkest stop until its lightest roof is `ROOF_CONTRAST` (90) grey levels of luma below the ground
  around it, at least down to `ROOF_MIN_SCALE` (a quarter) of the ramp's range (`roof_contrast`); the order of heights stays, hue
  stays, and ground light enough already (nothing in the ramp is within 90 of it) changes nothing. The ground is the cover's
  palette colour (snow 246, sand 225, grass 205, asphalt 168) on a map of 3.2 m cells (`ground_luma_map`, made in `load`), the
  cells an object covers taking the nearest ground cell: a function of the map alone, so a large roof has the same reference in
  every block. Before, a 2 to 5 m roof was luma 196 to 170 on snow of 246: a step of 50 to 76 (median roof against ground at the building
  edges of Goose Bay, zoom 5: 67 in the tiles, 125 in the game's texture, whose roofs are dark). The game-colour style (`FIELDS`) keeps its
  own object colours.
* **Small objects keep a minimum size on screen.** From a pixel of `OBJECT_SOLID_PX_M` (1 m) on, the coverage `c` of the pyramid
  becomes `1 - (1 - c) ** (px / 1 m)` (`visible_coverage`): a 2 x 5 m car covers 0.1 of a 10 m pixel and was drawn at a tenth of
  its colour, now at 0.65. At 1 m and finer the coverage is untouched, so the finest zooms (and the alignment gate with the
  Standard HD layer) are as before.
* **The outline is one pixel at every zoom.** The rim of the footprint is drawn dark from zoom 0 to the finest; the height steps
  inside it only where a pixel is at most `STEP_OUTLINE_PX_M` (1.5 m) (a coarser pixel holds a cluster of objects of every
  height). It stopped at 1.5 m per pixel before, so at the overview zooms a village was beige on white.

Checks (`maptiles.sh check`, results in `$WORK/check/<map>.json` and overlay images):

* tiles vs the Standard HD layer (`tools/maprender`, a camera render of the same client meshes that shares no code with the
  rasterizer above), the gate: eight windows of 76.8 m around the largest roofs (each wholly inside the map), both layers resampled to 0.1 m, median
  offset of the edge images' cross-correlation peak under 0.1 m on both axes over at least four windows;
* tiles vs the served precise heightmap (the server's collision): the dark outlines and walls of buildings in the finest tiles against the
  heightmap's bumps placed with SquadCalc's grid convention; median offset of the four densest windows under 1 px at the
  finest zoom. Its windows are 1 m samples taken at the nearest node and scatter by up to several pixels (Mutaha, zoom 7: -0.22 to
  2.63 px in x; Kokan -5.24 to -0.04 px), so it resolves decimetres, not centimetres, and is the gate only for a map without an HD layer;
* height reference: the contoured ground against the served heightmap on open ground, median
  difference under 1 cm;
* tiles vs the upstream basemap images at zoom 5 (reported in metres; the upstream images are the
  game's minimap texture).

`maptiles.sh measure` (`py/measure_accuracy.py`, results in `$WORK/check/<map>_<measure>.json`, each with the number of samples and the 95 %
bootstrap interval of its median):

* **roads**: at straight stretches of the road splines with no other spline near, the colour profile across the road in the tiles and in HD:
  the centreline offset (cross-correlation of the profiles' edges) and the width (between the half-contrast points);
* **water**: the tiles' water against HD's on the whole map (intersection over union, shoreline distance); HD's water colours are learned
  from the map itself, so it measures the outline, not whether HD has water;
* **crowns**: at trees with no other crown near, the crown is drawn (against the scene's foliage instances), the mean offset of its centroid
  from the instance's pivot, and the offset against HD's crown across the light (along it HD's ground shadow is measured, not the crown);
* **heights**: the roof labels against the served heightmap's rise over the bare ground (another build, another rasterizer);
* **contours**: the heightmap's height under the pixels of the contour lines: the interval they fit and their distance to the true level line.

`maptiles.sh outline` scores the building outlines against the game's own minimap textures of the Seed and Skirmish layers
(the pairs of squad-map-restoration, `$PAIRS`: Black Coast, Goose Bay, Manicouagan, Mutaha, Skorpo, Tallil): the edge F1 at
1, 2 and 3 px of the tiles, of the HD layer and of `OUTLINE_BEFORE` (an earlier build) around the buildings, in
`$WORK/check/<map>_outline_<pair>.json` (`py/outline_accuracy.py`). Each picture's edges are its strongest pixels in the number the
texture has around the buildings, so a picture is not scored on how many lines it draws (contours, forest texture) but on where its
strongest ones lie; the texture's shift is one per layer, kept only when its correlation peak is clear. Sign conventions: the HD
gate's offset is positive where the tiles lie east or south of HD, the outline shift where the texture lies east or south of the tiles.

## Tile frame

Leaflet `CRS.Simple`, the map image spanning LatLng `[0, 0]`–`[-256, 256]` (SquadCalc's `imageBounds`). At
zoom `z` the map is `256 · 2^z` px; pixel `(px, py)` has its centre at
`X = min_x + (px + 0.5) · size_x / (256 · 2^z)`, `Y = min_y + (py + 0.5) · size_y / (256 · 2^z)`, with
`min`/`size` the minimap corners of `src/data/maps.js` (X with `gameToMapScale`, Y with `gameToMapScaleY`,
as `squadGrid.js`). The finest zoom is the first with at most 0.125 m per pixel (the object grid is 0.1 m; the next zoom, 0.11 m or finer, would make the 25 maps about 13 GB instead of about 7 GB). That is zoom 6
for Foolsroad, Logar and Sumari; zoom 7 for Albasrah, Anvil, Chora, Fallujah, Goosebay, Gorodok, Harju, Jensen, Kamdesh, Kokan, Manicouagan,
Mestia, Mutaha, Narva and Pacific; zoom 8 for Blackcoast, Kohat, Lashkar, Sanxian, Skorpo, Tallil and Yehorivka.

## Running

Requirements: the outputs of `tools/heightmaps` (`extract` and `build`: landscapes, statics and the
precise heightmaps, deployed), the SquadHeight release, Docker.

```sh
tools/maptiles/maptiles.sh setup          # extractor with the features mode (needs heightmaps.sh setup's CUE4Parse), Python image
tools/maptiles/maptiles.sh extract        # foliage, landscape splines, water actors of every map (about 15 min)
tools/maptiles/maptiles.sh prep           # ground, cover, 0.25 m collision objects, features into $WORK/prep (1–25 min per map)
tools/maptiles/maptiles.sh scene          # needs tools/maprender/maprender.sh scene: 0.1 m objects (on the GPU), roof labels and crowns into $WORK/prep (2–6 min per map)
tools/maptiles/maptiles.sh render         # tiles into $DIST/maptiles/<map>
tools/maptiles/maptiles.sh check          # alignment checks
tools/maptiles/maptiles.sh measure        # roads, water, crowns, roof heights and contours against HD and the served heightmap
tools/maptiles/maptiles.sh palette        # contrast of the classes under normal and colour-deficient vision
tools/maptiles/maptiles.sh outline        # building outlines against the game's minimap textures (after scene, while its rasters exist)
tools/maptiles/maptiles.sh all skorpo     # extract, prep, scene and render of one map
```

Paths and parallelism are set with `SQUAD_DIR`, `SQUADHEIGHT`, `EXTRACT`, `HEIGHTMAPS`, `WORK`, `DIST`, `SCENES`,
`CUE4PARSE`, `WORKERS`, `MEMORY` (every container is limited to 3 GB, no swap) and `HEIGHTMAPS_SERVED` (see the script header).
Everything runs under `nice` in the Python image, but for the scene raster's GPU step, which runs on the host with `PYTHON`
(numpy, scipy, moderngl and an EGL driver; `SCENE_RASTER=cpu` keeps it in the image on the CPU, about 8 times slower).
`SCENE_ARGS="--keep-raw"` keeps the pre-merge raster (as large as the finest grid) for `--redo-merge` (with `SCENE_RASTER=cpu`).
Blocks of open sea (nothing but sea 13 m and deeper within their reach, under the default style) are not drawn: their tiles
are hard links to one tile of the deep water's colour, the bytes the drawing gives. A test render into another place: `DIST=<dir> maptiles.sh render <map>`
writes `<dir>/maptiles/<map>`. A map's tiles are
rendered into `$DIST/maptiles/.<map>.tmp` and swapped in when complete; the page requests tiles with
`?v=<meta.json generated>`, so the long cache lifetime set by Caddy never serves a stale tile.
After a game patch: `heightmaps.sh extract build deploy`, then `maptiles.sh extract prep scene render check`.

## Layer minimaps

Most layers of a map use one minimap texture of the whole map. Seed and Skirmish layers ship a texture of
their own that covers only the part of the map the layer is played on, so it is several times finer than the
whole-map image (4096 px over the playable strip instead of the whole map). SquadCalc shows it for those layers,
over the corners the game stretches it between.

The game takes a layer's minimap from two places: its level (`SQWorldSettings`: `MapTexture` between the actors
`MapTextureCornerZero` and `MapTextureCornerOne`), replaced by the layer's data asset (`Gameplay_Layer_Data/<layer>`,
class `BP_SQLayer`) where that sets `OveriddenMinimapTexture` (the texture) or `MinimapCornersPosition` with `bIsValid`
(the corners, min/max in cm, which the game turns into the rectangle it draws). The level alone is not enough: Black
Coast Seed v1's level names `Black_Coast_Minimap_Seed_v1`, which shows another part of the island (490 to 861 m off),
where its data asset sets `T_BlackCoast_Seed_v1` over the same corners; the data assets of Narva Skirmish v1, Yehorivka
Skirmish v1, v1 WP and v2 and Fallujah Skirmish v1 give them a texture of their own where their levels show the map's.
The layer API of SquadCalc (`mapTexture`, `mapTextureCorners`) gives the level's.

Source: the Squad game client (not the server files) at `$CLIENT_DIR`, default `~/data/squad-client`; its paks
open without a key. The extractor's `layerminimaps` mode prints one line per `Gameplay_Layers` level: the level,
its `MapTexture` and the two minimap corners in cm (`layers.tsv`); its `dumpall` mode writes the layer data assets
as JSON (`layerdata/`); its `texraw` mode the raw mip 0 of the textures the layers need
(`<package>.<PixelFormat>.<w>x<h>.bin`; DXT1 4096x4096, one B8G8R8A8 2048x2048). `py/layer_minimaps.py` joins
levels and data assets into the table of what each layer shows. The map of a layer is the first `_` token of its
name; the base texture of a map is the one most of its layers show; a layer that shows another texture has a layer
minimap. A layer that shows the base texture over other corners has none: the calculator shows the whole-map image,
which lies where that texture shows the world (the build prints these layers: Manicouagan RAAS v1 and v2, Skorpo
Invasion v1, Sumari Insurgency, Seed and Skirmish v1). With client build 26234431 there are 219 levels and 221 data
assets (83 set a texture, 204 valid corners), and 21 layers with a minimap of their own in 18 textures: Seed and
Skirmish layers of AlBasrah, BlackCoast, Chora, Fallujah, GooseBay, Gorodok, Manicouagan, Mutaha, Narva, Skorpo,
Tallil and Yehorivka.

```sh
tools/maptiles/maptiles.sh setup           # once, and after a change of the extractor
tools/maptiles/maptiles.sh layer-minimaps  # about 3 min
```

Output, next to the tile folders of the maps:

```
$DIST/maptiles/<texture name in lower case>/0/0_0.webp   lossy webp, quality 90, method 4 (1.0 to 5.3 MB each)
$DIST/maptiles/layer-minimaps.json
```

```json
{"generated": "<UTC ISO time>", "build": "<client buildid>",
 "layers": {"BlackCoast_Seed_v1": {"texture": "T_BlackCoast_Seed_v1", "folder": "t_blackcoast_seed_v1", "size": 4096,
                                   "min": [-950.0, -1200.0], "max": [50.0, -200.0]}}}
```

Keyed by the layer's raw name: `texture` the texture's object name, `size` its side in px, `min` and `max` the corners
of the world rectangle it is drawn over, in metres (the game's centimetres over 100, five decimals). The calculator
reads this format (`src/js/mapImages.js`); one that reads the earlier format keyed by texture finds no `layers` and
shows no layer minimap, so the manifest and the calculator are deployed together. The folder names are the texture
names (`T_...` or `..._Minimap_...`), which no map folder has, and `maptiles/<texture>/0/0_0.webp` falls under the
same long cache rule as the tile folders. Files are written under a temporary name and renamed; nothing else under
`$DIST/maptiles` is touched. Table, override and decoding (`py/layer_minimaps.py`: BC1 and B8G8R8A8 to RGB) are covered
by `py/test_layer_minimaps.py`:
`docker run --rm -v "$PWD/tools/maptiles/py:/py" -w /py squadcalc-maptiles-py python -m unittest test_layer_minimaps`.

## Game colours (style `colour`)

A second layer, "Detailed · game colours", draws the same data (hillshade, contours, roads, building footprints
with heights, trees, water) with the colours of the game's own map. It is a style of `py/render.py`
(`--style colour`, tiles in `/maptiles/<map>-colour/`, selectable in SquadCalc next to Detailed, maps with such tiles
only); the Detailed layer itself is unchanged. The colours are fitted to the upstream basemap of the same map
(`https://squadcalc.app/api/img/maps/<map>/basemap.webp`, the game's minimap texture, 1 m per pixel; it is read for the
fit and is not redistributed by the tiles), kept in `py/styles/colour_<map>.json`:

1. `fit_palette.py`: the map is rendered at about 1 m per pixel and each pixel is given the class of its top layer
   (ground cover material, road class, water, tree class, building height band, shadow). Every class colour is multiplied
   by the ratio of the basemap's mean on those pixels to the render's mean until they agree (the `palette` fit: one
   colour per class for the whole map).
2. `fit_fields.py`: the game's colours differ from region to region (sand and rock, a muddy river and a green pond, roofs),
   so for the groups ground, water, road, object, conifer, deciduous and bush the basemap's own pixels of the group are
   averaged under a Gaussian (2-3 px, filled from wider ones where the group is absent) into a colour field
   (`prep/<map>/colour_field_<group>.npy`) that the renderer samples instead of the class colour. Ground pixels clearly
   darker than their surroundings (the game's baked shadows) are left out of the ground field. Geometry, edges,
   hillshade, contours, outlines and labels stay those of the Detailed layer at their own resolution.
3. `fit_relief.py` reports the relief strength and the light direction of the render against the basemap on bare ground
   (regression of the band-passed luminance on the terrain slope) and the direction of the game's building shadows. The
   fitted style uses it for `SHADE_STRENGTH` and, where the relief and the shadows agree (Al Basrah: light from the west),
   `LIGHT_FROM`; elsewhere the north-west light of the Detailed layer stays. The regression is weak (7-11 % of the basemap's
   luminance variance) and on Gorodok and Fallujah it disagrees with the render, so relief there is the default.
4. `colour_distance.py`: mean CIE76 and CIEDE2000 between the cell mean colours (cells of about 64 m) of a zoom 4 tile
   mosaic (about 1 m per pixel) and the basemap, and the best per-channel linear grade; `--write-grade` stores it as the
   style's `GRADE` (the fitted layers darken a few percent through contours, outlines and shadows: 14-25 % of the distance).

The style draws with the same renderer as the Detailed layer (scene objects, crown stamps, shadows); its fitted palette and fields
were made with the earlier circle crowns and collision footprints, so `colour-fit` has to be run again before `colour-render`.

Because the fields are taken from the basemap itself, the distance to it is small by construction; it shows that
nothing is lost in the re-drawing, not that the colours generalise. Commands: `maptiles.sh colour-fit`, `colour-relief`,
`colour-render`, `colour-distance`; the Python image is the one of `setup`.

Files:

* `maptiles.sh` — the steps above;
* `py/features.py` — foliage, splines, water and ground cover from the extracted data, and the
  classification rules (by mesh name) of foliage, splines and objects;
* `py/prep.py` — per map: ground and cover on the 1 m grid, the 0.25 m collision object raster and its pyramid,
  building labels (reuses `tools/heightmaps/py`: landscape, objects, build_heightmap, maps);
* `py/scene_objects.py` — the visible LOD 0 meshes of the client scene rasterized top-down (0.1 m grid, anti-aliased coverage),
  in two halves: the highest surface at the sample points (`block_samples`, CPU `sample_tops` or the GPU sampler) and the
  cells from them (`block_cells`: ground below, 2 x 2 samples, coverage, thin objects);
* `py/scene_raster_gpu.py` — the scene raster's level 0 drawn on the GPU (host Python), the cells made by worker processes meanwhile;
* `py/crowns.py` — the scene's foliage instances and the top-down stamp of every tree, bush, palm and rock mesh;
* `py/road_width.py` — the visible width of road meshes from the client scene's materials and textures, and the narrowed splines
  (`top_lines.json`, written by `scene_prep.py`);
* `py/scene_prep.py` — per map: the scene raster in blocks, the old collision raster's remaining objects, the 7-level pyramid,
  roof labels, crowns, the narrowed splines and the completeness report (`top_meta.json`);
* `py/render.py` — the tile renderer: styles, contour and label placement, layer order;
* `py/worker_pool.py` — the worker processes of `prep.py`, `scene_prep.py`, `scene_raster_gpu.py`, `render.py` and the colour fits: a
  worker whose initializer fails (a source file missing) or that dies (the memory limit) stops the step at once with its error;
* `py/check_alignment.py` — the checks; `py/measure_accuracy.py` — the accuracy measures; `py/palette_contrast.py` — the palette's contrast;
* `py/compare_builds.py` — server build against client build placements; `py/outline_accuracy.py` — building outlines against
  the game's own layer minimap textures (edge F1 at 1, 2, 3 px); `py/compare_crops.py` — before/after crops;
* `py/test_scene.py`, `py/test_cartography.py`, `py/test_layer_minimaps.py` — tests: `docker run --rm -e PYTHONPATH=/py:/hmpy -v "$PWD/tools/maptiles/py:/py:ro"
  -v "$PWD/tools/heightmaps/py:/hmpy:ro" -w /tmp squadcalc-maptiles-py python -B -m unittest test_scene test_cartography` (`test_cartography`: the
  symbol rules above, the class rules, the water surfaces, the summits, the legend, the palette's contrast against published values, and the
  accuracy measures on pictures with a known answer; `test_scene`: the rasterizer on a small scene
  with a known answer, service materials, crown stamps and sprites, the old raster's merge, what of it is no object and what of it the scene shows, the roll of a spline mesh, tiles that do not depend on the
  block size, identical bytes on every run, open-sea blocks linked with the bytes of the drawing, the MDOW relief against the
  published slope-and-aspect formula, the visible width of road meshes for masked, mask-channel, ramped, opaque, hidden and mirrored
  materials and for meshes the spline rolls, and its drawing); `py/test_scene_gpu.py` on the host (`cd tools/maptiles/py && PYTHONPATH=.:../../heightmaps/py
  $PYTHON -m unittest test_scene_gpu`: the GPU raster against the CPU one, skipped without an EGL context); `py/test_worker_pool.py` (in the
  image, as `test_scene`): the pools of `worker_pool.py` and the steps that use them stop at once when a source is missing or a worker is killed;
* `py/fit_palette.py`, `py/fit_fields.py`, `py/fit_relief.py`, `py/colour_distance.py`, `py/styles/` — the game colours above.

## Size and time

Measured on the build of 2026-11-09 (tk104: 15 GB RAM, GTX 1650 4 GB; webp quality 88; the scene of one map, GPU raster then
`scene` with 4 workers, ran while the previous map rendered with 6 workers and 9 GB):

| Map | Finest zoom (m/px) | Tiles | Tiles on disk | GPU raster | `scene` | Render |
|---|---|---|---|---|---|---|
| Sumari | 6 (0.079) | 5 461 | 41 MB | 1 min | 1 min | 4 min |
| Mutaha | 7 (0.084) | 21 845 | 155 MB | 2 min | 1 min | 19 min |
| Goose Bay | 7 (0.123) | 21 845 | 208 MB | 13 min | 9 min | 18 min |
| Tallil | 8 (0.071) | 87 381 | 431 MB | 13 min | 13 min | 51 min |
| Skorpo | 8 (0.105) | 87 381 | 591 MB | 10 min | 20 min | 38 min |
| Lashkar | 8 (0.066) | 87 381 | 991 MB | 6 min | 9 min | 77 min |

All 25 maps (3 to zoom 6, 15 to zoom 7, 7 to zoom 8): 955 725 tiles, 7.3 GB (the build of 2026-10-29: 1.4 GB), GPU raster 2.3 h,
`scene` 2.6 h, render 12.4 h; with the two lanes overlapping, about 15 hours on the one machine. The numpy rasterizer instead of the GPU
(`SCENE_RASTER=cpu`) takes 8 times longer for the raster (Narva: 1990 s on 4 processes against 244 s).

`scene` writes `top_*` (the 0.1 m object grid and its pyramid) into `$WORK/prep/<map>`: 3 GB (Mutaha) to 19 GB (Skorpo), about 185 GB
for 25 maps. When the disk cannot hold all of them, go map by map and drop the grid after the render and the check (tiles do not need it):

```sh
for m in $(python3 -c "import sys; sys.path.insert(0, 'tools/heightmaps/py'); import maps; print(' '.join(maps.MAPS))"); do
    tools/maptiles/maptiles.sh scene "$m" && tools/maptiles/maptiles.sh render "$m" && tools/maptiles/maptiles.sh check "$m" \
        && rm -f "$WORK/prep/$m"/top_*.npy "$WORK/prep/$m"/raw_*.npy
done
```

`render` of a map stops before it draws when `scene` was not run for it: `/prep/<map>/top_meta.json is missing: run maptiles.sh scene <map>
first`; a source file missing besides stops it with the file's name. A worker killed by the memory limit (the container's 3 GB) stops it at
once with `BrokenProcessPool`, the tiles drawn by then left in `$DIST/maptiles/.<map>.tmp`: run `render` again, which starts that folder
afresh, or render the zooms that are missing into it with `render.py <map> --zooms <z> --out <the .tmp folder>`.

## Relief layer (PMTiles)

A grayscale shaded relief of the precise heightmap alone, `$WORK/relief/<map>.pmtiles` (PMTiles v3, 256 px WebP tiles,
the tile frame above, zooms 0 to the first whose pixel is no coarser than the grid cell, plus one: Fallujah 0-5, Chora 0-6),
read by SquadCalc's lazy "Relief" layer with range requests (`src/js/squadReliefLayer.js`; serve it as
`/maptiles/relief/<map>.pmtiles`). Pipeline `py/relief.py` (formulas in its docstring), run with `maptiles.sh relief-setup`
and `maptiles.sh relief [map ...]` (`RELIEF_ARGS="--tint"` multiplies a hypsometric tint, `--extra-zoom N` sets the oversampling):

* Horn gradients, hillshade at the four azimuths 360, 315, 270, 225 (sun 45 degrees), blended by the oblique weights
  `sin^2(aspect - azimuth)` (Mark 1992; Esri's multidirectional hillshade) into the MDOW hillshade;
* RVT anisotropic sky-view factor (level 1, direction 315, 16 directions, 25 m), stretched from its 1st percentile to 1;
* Multiply at 50 % opacity of the SVF over the MDOW hillshade: `MDOW * (0.5 + 0.5 * SVF)`;
* resampled with Lanczos to the finest zoom (heightmap samples on the frame's nodes), coarser zooms average 2 x 2 pixels.

Placement (measured 2026-11-10 with `maptiles.sh register relief` and `register relief --reference heightmap`, see "Where
each map picture lies on the world"; zoom-4 mosaic of the served archives, 0.4 to 1.7 m a pixel): the layer lies in the tile
frame, which `build` checks against the heightmap's. Against a plain MDOW hillshade it reads 0.2 to 1.8 m south-east at the
centre of every map but Skorpo and Sanxian (Jensen +1.80 m east, +0.52 m south; Yehorivka +1.62, +0.66 m; Sanxian +2.28,
+1.03 m against its bare ground, which is not the heightmap the layer shades, and +0.21, +0.27 m against that heightmap),
against the same heightmap shaded with this layer's own formula (`shade_map`, `blend`) within 0.01 to 0.03 m on Al Basrah,
Fallujah, Goose Bay, Jensen, Logar, Mutaha, Narva and Sumari, 0.11 m on Sanxian and 0.25 m on Skorpo, and against the game's
bare ground (`prep/<map>/ground.npy`) with the same formula within 0.19 m on the other maps. The offset is the drawing: the
anisotropic sky-view term (main direction 315 degrees) darkens the slopes facing away from the light and moves the edges a
hillshade alone would show south-east; the frame is right. On towns the bare ground reads 0.30 to 0.66 m off, as the
heightmap's buildings shade and the bare ground has none.

The Python image `py/Dockerfile.relief` installs `rvt-py` without its GDAL dependency (`vis.py` needs only numpy and scipy).
Size: 1.8 to 4 MB for Fallujah, 3 to 11 MB for Chora, depending on the extra zoom.

## Where each map picture lies on the world

`py/register_images.py` measures where each picture the calculator shows lies against the world, and where the game
draws its own minimap textures, with nothing but game data as the reference. A picture is placed over a world rectangle
as the calculator or the game places it, resampled to about one of its pixels over the map's frame, and registered in
8 x 8 overlapping windows: normalised cross-correlation within 30 m (80 m for upstream's relief images), a sub-pixel peak,
windows with a weak or ambiguous peak left out, and an affine fit of the window shifts with outliers over 2.5 px left out.
Two references, independent of each other:

* **features**: the edges of the level's objects (the 0.25 m collision coverage of `prep`), tree crowns (`foliage.npz`,
  rocks left out) and road surfaces (`lines.json`), against the edges of the picture's luminance;
* **shade**: the bare ground's slopes (`ground.npy`) lit from the direction fitted over the map, plus the coastline on
  a map with a sea, against the band-passed log luminance of the picture, the terrain shading it carries.

Every figure is the displacement of the picture's content from the world in metres, + = drawn east or south of where it
is: `W`/`E` in x at the middle of the frame's west and east edges, `N`/`S` in y at its north and south edges, `C` at its
centre, `worst` the largest component at the four corners, `windows` those the fit kept (a figure on fewer than 20 is
weak), `scale` and `rotation_deg` from the fit's linear terms. Displacements under about 0.4 m are below the method: the
Detailed layer, drawn from the same level data, reads 0.08 to 0.40 m on 23 maps (Tallil 0.80 m, Pacific 1.07 m on 6
windows). `py/test_register_images.py` (30 tests) recovers
synthetic shifts, scales, turns, rectangles, orientations and squares, the shading through a sea and a hole in the ground:
`docker run --rm -e PYTHONPATH=/py:/hmpy -v "$PWD/tools/maptiles/py:/py" -v "$PWD/tools/heightmaps/py:/hmpy" -w /py squadcalc-relief-py python -m unittest test_register_images`.

```sh
tools/maptiles/maptiles.sh relief-setup                      # once: the image the tool runs in
tools/maptiles/maptiles.sh layer-minimaps                    # the client's layer table (layers.tsv, layer data) and layer minimaps
tools/maptiles/maptiles.sh register-setup                    # every minimap texture the layers name, the upstream images (about 3 min)
tools/maptiles/maptiles.sh register basemaps skorpo          # one JSON line per picture placed (2 to 5 min a map)
```

| Measure | What it registers |
|---|---|
| `basemaps [map ...]` | by features: `game` the client's base texture between the game's corners (the texture most layers show, over the rectangle most of them give it), `image` the upstream basemap between the image corners (the tile frame, `prep/<map>/meta.json`), `basemap_game` the upstream basemap between the game's corners, `detailed` the served Detailed tiles at the zoom nearest that grid over the image corners |
| `rect <map> <basemap\|texture> <min x> <min y> <max x> <max y> [--reference shade]` | one picture over one rectangle; `fitted` is the rectangle the picture shows: the rectangle less the displacement, carried to its edges |
| `layer-minimaps [map ...]` | the layer minimaps of `$LAYER_TILES/layer-minimaps.json` between their corners, by features; `finer` is the map's base texture's metres per pixel over the layer minimap's |
| `locate <map> <texture> <min x> <min y> <max x> <max y> <sizes> [--crop x0 x1 y0 y1]` | where a texture's picture lies on the map's base texture if it shows a square of each side in `<sizes>` (`a:b:step` or a list, metres), in its 8 orientations (edge-image NCC at 2 m), and the displacement of its content when drawn over the given rectangle; `<texture>` is the package name (the raw file's) |
| `orientation [map ...]` | the upstream basemap against the client's base texture: correlation of the 8 orientations (512 px thumbnails), then 7 x 7 windows of 384 px fitted per axis as an offset and a change across the image (px) |
| `upstream-relief [map ...]` | upstream's 8-bit heightmap (`heightmap.png`, level 255 + red - blue, points from corner to corner) against the ground; the hillshade in `terrainmap.webp` (over `basemap.webp`) and in `topomap.webp` against that heightmap lit from the fitted direction |
| `relief [map ...] [--reference heightmap]` | the relief layer (`relief/<map>.pmtiles`, zoom 4) against `mdow`, the multi-directional hillshade of the bare ground (or of the served heightmap), and `layer`, the layer's own shading of it (`relief.shade_map`, `relief.blend`) |

`register` reads `$WORK/prep`, `$DIST/maptiles` (the relief), `$HEIGHTMAPS_SERVED`, `$WORK/layer-minimaps`, `$WORK/register`
and `$LAYER_TILES`, all read-only, in containers of `$MEMORY` and `$CPUS`; it writes nothing but its output.

### Results of 2026-11-10

Client build 26234431, the pictures of SquadCalc 45.50.0 (`$DIST/maptiles`, the layer minimaps of `layer-minimaps`) and the
upstream images of that day; section 2.5 of `docs/thesis-methods-and-results.md` cites them. Worst corner in metres with the
windows the fit kept; a figure on fewer than 20 windows is weak, `-` is no fit (fewer than 6).

`register layer-minimaps`, the 21 layers whose data asset sets a texture other than their map's, over the corners of the
manifest:

| Layer | Texture | m/px | `finer` | W | E | N | S | worst (windows) |
|---|---|---|---|---|---|---|---|---|
| AlBasrah_Seed_v1 | `T_AlBasrah_Minimap_Seed_v1` | 0.977 | 1.00 | +0.47 | +0.00 | +0.17 | +0.48 | 0.97 (46) |
| AlBasrah_Seed_v2 | `T_AlBasrah_Minimap_Seed_v2` | 0.977 | 1.00 | +0.45 | +0.04 | +0.15 | +0.49 | 0.97 (47) |
| AlBasrah_Skirmish_v1 | `T_AlBasrah_Minimap_Skirmish_v1` | 0.977 | 1.00 | +0.47 | +0.02 | +0.15 | +0.50 | 1.00 (46) |
| AlBasrah_Skirmish_v2 | `T_AlBasrah_Minimap_Skirmish_v2` | 0.977 | 1.00 | +0.50 | -0.02 | +0.21 | +0.46 | 0.97 (45) |
| BlackCoast_Seed_v1 | `T_BlackCoast_Seed_v1` | 0.244 | 4.60 | -0.18 | +0.10 | +0.07 | +0.01 | 0.24 (25) |
| Chora_Skirmish_v1 | `Chora_Minimap_Skirmish_v1` | 0.396 | 2.51 | +0.07 | +0.28 | +0.07 | +0.02 | 0.44 (38) |
| Fallujah_Seed_v1 | `Fallujah_Minimap_Skirmish` | 0.734 | 1.00 | -0.57 | +0.87 | -0.08 | -0.10 | 0.88 (42) |
| Fallujah_Skirmish_v1 | `Fallujah_Minimap_Skirmish` | 0.734 | 1.00 | -0.57 | +0.87 | -0.08 | -0.10 | 0.88 (42) |
| GooseBay_Seed_v1 | `GooseBay_Minimap_Seed_v1_fix` | 0.244 | 4.03 | -0.01 | -0.00 | +0.10 | -0.11 | 0.12 (41) |
| Gorodok_Skirmish_v1 | `Gorodok_Minimap_Skirmish_v1` | 0.992 | 1.00 | +0.92 | -1.31 | +1.30 | -1.41 | 1.54 (25) |
| Manicouagan_Seed_v1 | `T_Manicouagan_Seed_v1_Minimap` | 0.431 | 2.28 | +0.92 | -0.54 | +0.57 | -0.78 | 1.12 (23) |
| Mutaha_Seed_v1 | `Mutaha_Minimap_Seed_v1` | 0.317 | 2.12 | -0.11 | -0.00 | +0.01 | +0.27 | 0.32 (59) |
| Mutaha_Skirmish_v1 | `Mutaha_Minimap_Skirmish_v1` | 0.337 | 2.00 | +0.42 | +0.28 | +0.46 | +0.35 | 0.59 (51) |
| Narva_Skirmish_v1 | `Narva_Minimap_Skirmish_v1` | 0.261 | 2.62 | +0.20 | +0.24 | +0.18 | +0.17 | 0.33 (56) |
| Skorpo_Skirmish_v1 | `Skorpo_Minimap_Skirmish_v1` | 0.347 | 4.82 | +0.09 | +0.11 | -0.05 | +0.29 | 0.32 (35) |
| Tallil_Seed_v1 | `Tallil_Outskirts_Minimap_Skirmish_v1` | 0.276 | 4.14 | +0.25 | -0.07 | +0.29 | +0.25 | 0.42 (42) |
| Tallil_Skirmish_v1 | `Tallil_Outskirts_Minimap_Skirmish_v1` | 0.276 | 4.14 | +0.25 | -0.07 | +0.29 | +0.25 | 0.42 (42) |
| Tallil_Skirmish_v2 | `Tallil_Outskirts_Minimap_Skirmish_v2` | 0.561 | 2.03 | +0.40 | +1.10 | +0.76 | +0.79 | 1.15 (31) |
| Yehorivka_Skirmish_v1 | `Yehorivka_Minimap_Skirmish_v1` | 0.679 | 2.28 | +0.13 | +0.57 | +0.27 | +0.26 | 0.79 (33) |
| Yehorivka_Skirmish_v1_WP | `Yehorivka_Minimap_Skirmish_v1` | 0.679 | 2.28 | +0.13 | +0.57 | +0.27 | +0.26 | 0.79 (33) |
| Yehorivka_Skirmish_v2 | `Yehorivka_Minimap_Skirmish_v2_fix` | 0.527 | 2.94 | -0.35 | +0.42 | -0.03 | +0.22 | 0.53 (13) |

`register locate blackcoast Black_Coast_Minimap_Seed_v1 -950 -1200 50 -200 650:800:25 --crop 0.3 0.85 0.2 0.7` (the
level's corners, which the layer API gave Black Coast Seed v1 before SquadCalc 45.50.0): the texture shows the 725 m
square (-88, -433.5) to (636, 290.5) m, neither turned nor mirrored (NCC 0.66, every other size and orientation 0.24 or
less); drawn over those corners its content lay 586 to 862 m west and 490.5 to 766.5 m north of where it is.

`register basemaps`: on the 13 maps whose image corners are the game's, `image` and `basemap_game` are one placement; on
the 11 whose image corners are rounded and on Skorpo they differ. `detailed`, drawn from the same level data, is the
method's floor:

| Map | `game` | `image` | `basemap_game` | `detailed` |
|---|---|---|---|---|
| Al Basrah | 0.94 (51) | 0.94 (51) | 0.94 (51) | 0.21 (62) |
| Anvil | 0.41 (34) | 0.41 (34) | 0.41 (34) | 0.15 (64) |
| Black Coast | 1.48 (51) | 2.38 (49) | 1.40 (50) | 0.17 (63) |
| Chora | 2.35 (16) | 2.09 (16) | 2.36 (16) | 0.37 (35) |
| Fallujah | 0.44 (36) | 0.44 (37) | 0.44 (37) | 0.12 (53) |
| Fools Road | 0.36 (7) | 0.42 (6) | 0.41 (7) | 0.08 (64) |
| Goose Bay | 0.21 (55) | 0.97 (55) | 0.21 (55) | 0.12 (64) |
| Gorodok | 1.53 (24) | 1.55 (25) | 1.61 (25) | 0.16 (64) |
| Harju | 1.10 (15) | 0.90 (15) | 0.90 (15) | 0.13 (60) |
| Jensen | 2.05 (10) | 2.02 (10) | 2.02 (10) | 0.40 (17) |
| Kamdesh | 0.17 (60) | 0.18 (60) | 0.18 (60) | 0.13 (64) |
| Kohat | 1.02 (42) | 0.91 (39) | 0.91 (39) | 0.24 (45) |
| Kokan | 0.75 (43) | 0.47 (43) | 0.77 (43) | 0.17 (40) |
| Lashkar | 0.25 (29) | 0.26 (29) | 0.26 (29) | 0.19 (64) |
| Logar | 0.31 (30) | 0.76 (30) | 0.33 (30) | 0.17 (43) |
| Manicouagan | 0.69 (63) | 0.65 (58) | 0.66 (61) | 0.11 (64) |
| Mestia | 0.64 (33) | 0.63 (33) | 0.63 (33) | 0.20 (54) |
| Mutaha | 0.49 (35) | 0.50 (35) | 0.50 (35) | 0.22 (57) |
| Narva | 0.50 (60) | 0.49 (60) | 0.50 (60) | 0.15 (59) |
| Pacific | - | - | - | 1.07 (6) |
| Sanxian | 0.66 (40) | 0.70 (38) | 0.70 (38) | 0.25 (48) |
| Skorpo | 9.44 (32) | 19.55 (31) | 9.49 (32) | 0.25 (44) |
| Sumari | 0.70 (28) | 0.77 (29) | 0.67 (28) | 0.12 (40) |
| Tallil | 4.46 (27) | 4.45 (27) | 4.45 (27) | 0.80 (48) |
| Yehorivka | 4.55 (62) | 4.59 (62) | 4.60 (62) | 0.27 (63) |

`register rect skorpo basemap ...`: the upstream basemap over the image corners, over the rectangle that fit gives
(`fitted`), and over that one's fit rounded to 0.1 m, which `src/data/maps.js` of SquadCalc 45.50.0 holds as Skorpo's
`minimap.image`; `--reference shade` for the second method:

| Rectangle | Reference | W | E | N | S | worst (windows) | `fitted` |
|---|---|---|---|---|---|---|---|
| -3611 -3293 3238 3576 | features | -0.18 | -19.53 | -0.93 | +0.11 | 19.57 (31) | -3610.82 -3292.07 3257.53 3575.89 |
| -3611 -3293 3238 3576 | shade | -1.04 | -19.68 | -1.62 | +0.93 | 19.96 (32) | -3609.96 -3291.38 3257.68 3575.07 |
| -3610.82 -3292.07 3257.53 3575.89 | features | +0.31 | -0.18 | -0.28 | +0.11 | 0.50 (33) | -3611.13 -3291.79 3257.71 3575.78 |
| -3611.1 -3291.8 3257.7 3575.8 | features | +0.08 | -0.00 | +0.02 | -0.01 | 0.24 (33) | -3611.18 -3291.82 3257.70 3575.81 |
| -3611.1 -3291.8 3257.7 3575.8 | shade | -0.44 | -0.57 | +0.04 | +0.31 | 0.88 (34) | -3610.66 -3291.84 3258.27 3575.49 |

`register orientation`: on all 25 maps the upstream basemap is the client's base texture at its size, neither turned nor
mirrored (`rot0`, correlation 0.990 to 0.999, the next orientation 0.78 or less); its 7 x 7 windows lie within 0.27 px of
the texture's, with 0.20 px or less of change across the image.

`register upstream-relief`: upstream's 8-bit heightmap against the ground, and the hillshade baked into `terrainmap.webp`
and `topomap.webp` against that heightmap, worst corner (windows):

| Map | `heightmap` | `terrain_shade` | `topo_shade` |
|---|---|---|---|
| Al Basrah | 0.22 (62) | 1.02 (55) | 1.41 (51) |
| Anvil | 0.04 (61) | 0.57 (64) | 1.68 (43) |
| Black Coast | 0.21 (35) | 1.89 (55) | 6.28 (28) |
| Chora | 0.20 (20) | 5.83 (24) | - |
| Fallujah | 0.18 (30) | 1.95 (27) | 1.82 (20) |
| Fools Road | 0.08 (21) | 0.97 (54) | 1.69 (34) |
| Goose Bay | 0.31 (26) | 1.46 (54) | 1.92 (40) |
| Gorodok | 0.14 (54) | 0.65 (64) | 17.78 (11) |
| Harju | 0.06 (42) | 0.98 (56) | 3.66 (43) |
| Jensen | 0.01 (29) | 1.52 (57) | 23.71 (55) |
| Kamdesh | 0.07 (60) | 0.76 (64) | 0.93 (64) |
| Kohat | 0.02 (40) | 1.08 (35) | 1.58 (32) |
| Kokan | 0.14 (25) | 5.64 (58) | 1.25 (22) |
| Lashkar | 0.13 (63) | 1.37 (64) | 1.76 (64) |
| Logar | 0.03 (35) | 1.98 (64) | 1.95 (55) |
| Manicouagan | 0.24 (47) | 1.58 (62) | 2.04 (33) |
| Mestia | 0.00 (6) | 1.86 (24) | 3.37 (13) |
| Mutaha | 0.04 (46) | 3.55 (51) | 11.37 (9) |
| Narva | 0.07 (12) | 10.27 (48) | - |
| Pacific | 0.01 (49) | 2.28 (54) | 2.31 (51) |
| Sanxian | 0.89 (28) | 2.54 (44) | 17.62 (6) |
| Skorpo | 0.07 (29) | 43.10 (29) | 26.21 (19) |
| Sumari | 0.08 (24) | 0.32 (39) | 1.46 (10) |
| Tallil | 0.04 (59) | 6.96 (64) | 7.48 (41) |
| Yehorivka | 0.16 (38) | 0.86 (63) | 0.59 (61) |

`register relief` against the bare ground and `register relief --reference heightmap` against the served heightmap (run
on 10 maps): the centre of the relief layer against `mdow` (x, y; + = east, south) and its worst corner against `layer`:

| Map | `mdow` C, ground | `layer` worst (windows), ground | `layer` worst (windows), served heightmap |
|---|---|---|---|
| Al Basrah | +0.48, +0.32 | 0.66 (57) | 0.03 (64) |
| Anvil | +0.27, +0.19 | 0.08 (63) | - |
| Black Coast | +0.54, +0.49 | 0.18 (57) | - |
| Chora | +0.24, +0.17 | 0.18 (48) | - |
| Fallujah | +0.39, +0.20 | 0.40 (53) | 0.03 (51) |
| Fools Road | +0.31, +0.14 | 0.02 (56) | - |
| Goose Bay | +1.02, +0.53 | 0.35 (58) | 0.02 (63) |
| Gorodok | +0.88, +0.46 | 0.07 (64) | - |
| Harju | +0.79, +0.45 | 0.13 (60) | - |
| Jensen | +1.80, +0.52 | 0.01 (62) | 0.03 (63) |
| Kamdesh | +1.17, +0.44 | 0.08 (64) | - |
| Kohat | +0.22, +0.29 | 0.09 (64) | - |
| Kokan | +0.44, +0.20 | 0.14 (60) | - |
| Lashkar | +0.64, +0.26 | 0.04 (64) | - |
| Logar | +0.34, +0.12 | 0.02 (61) | 0.01 (62) |
| Manicouagan | +0.74, +0.45 | 0.16 (61) | - |
| Mestia | +0.21, +0.17 | 0.12 (37) | - |
| Mutaha | +0.55, +0.25 | 0.37 (53) | 0.01 (64) |
| Narva | +0.52, +0.26 | 0.30 (58) | 0.02 (64) |
| Pacific | +0.22, +0.26 | 0.01 (64) | - |
| Sanxian | +2.28, +1.03 | 3.60 (40) | 0.11 (49) |
| Skorpo | +0.26, -0.05 | 0.34 (52) | 0.25 (53) |
| Sumari | +0.21, +0.18 | 0.39 (30) | 0.02 (44) |
| Tallil | +1.21, +0.57 | 0.19 (64) | - |
| Yehorivka | +1.62, +0.66 | 0.03 (64) | - |
