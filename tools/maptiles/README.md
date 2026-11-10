# Detailed tactical map tiles from the game files

The "Detailed" layer of the Deadline SquadCalc: a topographic map of every map, drawn from the exact
game data of the Squad dedicated server and client paks, with tiles down to 0.07–0.125 m per pixel (see "Tile frame"). Served as 256 px
webp tiles from `/maptiles/<map>/<z>/<x>_<y>.webp` with `/maptiles/<map>/meta.json`
(`src/js/squadMinimap.js` `showDetailedLayer`; a map without tiles shows the upstream topographic map).

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
| Roads, tracks, pavements, railways, trenches, hedges | server: `LandscapeSplineSegment` edges (the width the meshes are laid with), classified by the meshes along them. Roads, tracks and pavements are narrowed to the width their meshes show from above (client: `py/road_width.py`, `top_lines.json`; the opacity of the mesh's material across its width: the colour texture's alpha above the clip of 1/3 for a masked material, the `Masks` texture's green channel for road layers, the ramp over a fifth of the width at each side of a road painted into the virtual texture, otherwise all of it; the segment takes the variant its spline mesh components have, so a dirt road of 6 m shows about 5.2 m and a road without a fringe keeps its width) | exact |
| Tracks painted into the landscape | client: the weight of the landscape's path layers (`Path`, `mat05_path`, `mat06_rockpath`, `Grusvei`) from the scene's weightmaps (`py/landscape_paths.py`), drawn in the dirt track's colour where they weigh half and more; a pixel coarser than 2 m takes the highest weight of its metres, so a footpath stays a line a pixel wide at the overview zooms instead of averaging away | 1 m grid, bilinear |
| Crop fields | client: the scene's crop plants (wheat, maize, poppies, cannabis, potatoes by mesh name, `crowns.CROP_NAME`; wild field flowers, field grass and weeds are not crops), each the disc of its mesh's reach, summed on the 1 m grid and smoothed by 1.5 m so a field's rows close into its area (`crowns.crop_fields`, `top_crops.npy`); drawn where they cover 30–70 % of the ground and more, coloured from low crops (0.6 m, wheat and poppies) to tall ones (2 m, maize and cannabis: what hides a soldier), with a diagonal hatch at 1 m per pixel and finer (`render.draw_crops`). The game-colour style leaves them to the game's texture | 1 m grid, bilinear |
| Buildings, walls, rocks, props, bridges | client: the visible LOD 0 meshes seen from above (`py/scene_objects.py`, `py/scene_prep.py`): highest surface and class on a 0.1 m grid sampled 2 x 2 per cell (anti-aliased edges), height above the ground. The highest surface over each sample is found on the GPU (`py/scene_raster_gpu.py`: an orthographic camera looking down with a "greater" depth test, one instanced draw per mesh) or with `SCENE_RASTER=cpu` by the numpy rasterizer of `tools/heightmaps`; the two differ at samples on a triangle's edge (Narva: 26 591 018 against 26 590 909 covered cells, 1 161 covered by one only, 1 004 of them partly; heights equal in 99.83 % of the cells both cover and within 1 cm in 99.99 %; `py/test_scene_gpu.py`); spline meshes are bent as the engine bends them, the component's roll included (`scene_objects.bend_along_spline`: a mesh that runs along its Y axis lies on its side without the quarter turn the landscape splines give it; with the roll the box of a bent mesh is the box of the server's cooked collision of the same component, to 1 cm for the pipelines, crash barriers and railway tracks of Manicouagan, without it 3.2, 0.9 and 1.3 m off; the Standard HD renderer leaves the roll out and draws those on their side); colour by class and, for structures, height over the ground smoothed by a 6 m Gaussian (`scene_prep.GROUND_BASE_SIGMA_M`, `top_ground_base.npy`: the edge of a jetty under a pier's deck or the landscape's 1 m steps do not show through a flat roof), roof ridges and levels by shading the top itself (ground plus height, so a roof on a slope is not shaded as the slope), 1 px outline at every zoom, shadows to the south-east (only from objects at least 2 px wide: a thinner post or wire casts none). The class is the mesh name's (`features.object_class`); a mesh the name leaves a plain structure is vegetation when at least half of its triangles carry a foliage-shaded (`MSM_TwoSidedFoliage`) material with a plant name (hedges, brambles, vineyard rows, orchard trees), drawn green like hedges, while tents, awnings and camouflage nets stay structures. Left out: hidden components, `/Coop/`, `/Tutorials/`, `_Vista` and `_Editor_Only` levels (Blackcoast's POI size rings), translucent (glass, decals), additive and developer materials, water, flowers, crops, low grass, weeds, ivy and leaf litter (by whole-word names: wall corners are kept), and what is narrower than 0.3 m except walls and bridges (cables, wires). Objects that the scene raster does not draw but the server's static collision holds (frames and fences thinner than 0.3 m, collision-only props) stay from the old 0.25 m raster of `prep.py` where no scene object lies within 2 m. Not kept (`scene_prep.old_non_objects`): what only SquadHeight holds, the cells in no box of a static mesh placement with collision (SquadHeight was traced in the SDK on another version of the map, and what the game has of its Blueprint buildings is in the client scene: Al Basrah's north edge had blocks of a Vista city that the build does not have, 3 to 12 m high, Black Coast steps across a river); ground cover with collision (Yehorivka's maize plants set by hand); cells off the landscape, where the ground is SquadHeight's surface already (Gorodok's first column stood as a wall 1 m wide and 11 m high along the west edge); a flat sheet the game does not show (`scene_objects.sheet_groups`, `scene_prep.legacy_sheets`: Goose Bay's translucent ice over its ponds, which the server holds as an object standing at the sheet's height over the lowest ground of each metre, to 0.25 m); the railway tracks between the edges of their spline segments, whose collision stands 0.3 to 0.45 m high while the tiles draw the railway from its spline; and what has the top of a mesh the scene has as terrain or water (background mountains, `_Vista` levels, rivers: `scene_objects.surface_groups`). A mesh counts as the old object's top where it rises 2 m and more above the ground, or 0.3 m and more when the cell's top is flush with it within 0.25 m (`scene_prep.legacy_terrain`): the landscape collision can lie flat under a scenery mesh that is the ground along a map's edge (Gorodok: a band 40 to 60 m wide on every side, rising 0.3 to 2.3 m), and the old raster's 'object' there is that terrain, not a building. A road surface mesh that paints the landscape's virtual texture (`_RVT` material) is a bridge: only a bridge deck lifts it above the ground | 0.1 m |
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
whole-map image (4096 px over the playable strip instead of the whole map). SquadCalc can show it for those
layers.

Source: the Squad game client (not the server files) at `$CLIENT_DIR`, default `~/data/squad-client`; its paks
open without a key. The extractor's `layerminimaps` mode prints one line per `Gameplay_Layers` level: the level,
its `MapTexture` and the two minimap corners in cm (`layers.tsv`). The `texraw` mode writes the raw mip 0 of the
minimap textures (`<name>.<PixelFormat>.<w>x<h>.bin`; DXT1 4096x4096, one B8G8R8A8 2048x2048). The map of a layer
is the first `_` token of its name; the base texture of a map is the one most of its layers use; a texture used
by a layer of that map but different from the base is a layer minimap. Layers that use the base texture with
other corners (Yehorivka Skirmish, Sumari, Mestia) are not layer minimaps. With client build 26234431 there are
15 of them: Seed and Skirmish textures of AlBasrah, BlackCoast, Chora, Fallujah, GooseBay, Gorodok, Manicouagan,
Mutaha, Skorpo and Tallil.

```sh
tools/maptiles/maptiles.sh setup           # once, and after a change of the extractor
tools/maptiles/maptiles.sh layer-minimaps  # about 2.5 min
```

Output, next to the tile folders of the maps:

```
$DIST/maptiles/<texture name in lower case>/0/0_0.webp   lossy webp, quality 90, method 4 (1-4.5 MB each)
$DIST/maptiles/layer-minimaps.json
```

```json
{"generated": "<UTC ISO time>", "build": "<client buildid>",
 "textures": {"Mutaha_Minimap_Seed_v1": {"folder": "mutaha_minimap_seed_v1", "size": 4096, "layers": ["Mutaha_Seed_v1"]}}}
```

`size` is the texture's side in px, `layers` the layers that use it. The corners of each layer are in
`$WORK/layer-minimaps/layers.tsv`. The folder names contain `_minimap_`, so they cannot collide with the map
folders, and `maptiles/<texture>/0/0_0.webp` falls under the same long cache rule as the tile folders. Files are
written under a temporary name and renamed; nothing else under `$DIST/maptiles` is touched. Decoding
(`py/layer_minimaps.py`: BC1 and B8G8R8A8 to RGB) is covered by `py/test_layer_minimaps.py`:
`docker run --rm -v tools/maptiles/py:/py -w /py squadcalc-maptiles-py python -m unittest test_layer_minimaps`.

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
* `py/check_alignment.py` — the checks; `py/measure_accuracy.py` — the accuracy measures; `py/palette_contrast.py` — the palette's contrast;
* `py/compare_builds.py` — server build against client build placements; `py/outline_accuracy.py` — building outlines against
  the game's own layer minimap textures (edge F1 at 1, 2, 3 px); `py/compare_crops.py` — before/after crops;
* `py/test_scene.py`, `py/test_cartography.py`, `py/test_layer_minimaps.py` — tests: `docker run --rm -e PYTHONPATH=/py:/hmpy -v tools/maptiles/py:/py:ro
  -v tools/heightmaps/py:/hmpy:ro -w /tmp squadcalc-maptiles-py python -B -m unittest test_scene test_cartography` (`test_cartography`: the
  symbol rules above, the class rules, the water surfaces, the summits, the legend, the palette's contrast against published values, and the
  accuracy measures on pictures with a known answer; `test_scene`: the rasterizer on a small scene
  with a known answer, service materials, crown stamps and sprites, the old raster's merge and what of it is no object, the roll of a spline mesh, tiles that do not depend on the
  block size, identical bytes on every run, open-sea blocks linked with the bytes of the drawing, the MDOW relief against the
  published slope-and-aspect formula, the visible width of road meshes for masked, mask-channel, ramped, opaque, hidden and mirrored
  materials and its drawing); `py/test_scene_gpu.py` on the host (`cd tools/maptiles/py && PYTHONPATH=.:../../heightmaps/py
  $PYTHON -m unittest test_scene_gpu`: the GPU raster against the CPU one, skipped without an EGL context);
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

`render` of a map stops with a Python error when `scene` was not run for it (its `top_*` files missing). A worker killed by the memory limit
(the container's 3 GB) makes `render.py` wait forever on its last block: stop that container and render the missing tiles with
`render.py <map> --zooms <z> --out <the .tmp folder>`.

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

The Python image `py/Dockerfile.relief` installs `rvt-py` without its GDAL dependency (`vis.py` needs only numpy and scipy).
Size: 1.8 to 4 MB for Fallujah, 3 to 11 MB for Chora, depending on the extra zoom.
