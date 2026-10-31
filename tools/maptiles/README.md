# Detailed tactical map tiles from the game files

The "Detailed" layer of the Deadline SquadCalc: a topographic map of every map, drawn from the exact
game data of the Squad dedicated server paks, zoomable to about 0.2–0.3 m per pixel. Served as 256 px
webp tiles from `/maptiles/<map>/<z>/<x>_<y>.webp` with `/maptiles/<map>/meta.json`
(`src/js/squadMinimap.js` `showDetailedLayer`; a map without tiles shows the upstream topographic map).

## What is drawn, and from which data

| Layer | Source in the paks | Resolution |
|---|---|---|
| Ground cover (grass, tall grass, dirt, gravel, mud, rock, sand, forest floor, asphalt, snow) | the dominant physical material of every landscape quad, cooked into the landscape collision heightfields (the server build has no render weightmaps) | 1–1.2 m quads, edges softened |
| Hillshade, slope tint | bare ground: the landscape collision heightfields, SquadHeight outside the game landscape (`tools/heightmaps`) | 1 m grid, cubic B-spline between samples |
| Contours, labelled | the same ground, heights above the map's lowest point (`z_min_m` of the served heightmap, the scale of SquadCalc's height readouts); minor 1 or 2 m at the finest zoom (2 m on hilly maps), major 10 m, coarser at smaller scales | per pixel |
| Water | ocean actors' sea level (weather layers), static water planes (lakes, ponds), river splines | per pixel |
| Roads, tracks, pavements, railways, trenches, hedges | `LandscapeSplineSegment` edges (the width the road meshes are laid with), classified by the meshes along them | exact |
| Buildings, walls, rocks, props | collision of every static mesh (the same data and filters as the heightmaps' objects), rasterized at 0.25 m: colour by class and height above ground, roof slope shading, outlines at height steps, shadows; Blueprint buildings the static meshes miss come from SquadHeight's surface (1 m) | 0.25 m |
| Roof height labels | connected buildings of 60 m² and 3 m or more, their 98th percentile height above ground, at the finest two zooms | — |
| Trees, bushes, rocks | every `FoliageInstancedStaticMeshComponent` instance: crown disc of the mesh's render bounds, trunk dot when the tree has collision; forest density where crowns are below a pixel | exact positions |

Checks (`maptiles.sh check`, results in `$WORK/check/<map>.json` and overlay images):

* tiles vs the served precise heightmap: building footprints in the finest tiles against the
  heightmap's bumps placed with SquadCalc's grid convention; offset under 1 px at the finest zoom;
* height reference: the contoured ground against the served heightmap on open ground, median
  difference under 1 cm;
* tiles vs the upstream basemap images at zoom 5 (reported in metres; the upstream images are the
  game's minimap texture).

## Tile frame

Leaflet `CRS.Simple`, the map image spanning LatLng `[0, 0]`–`[-256, 256]` (SquadCalc's `imageBounds`). At
zoom `z` the map is `256 · 2^z` px; pixel `(px, py)` has its centre at
`X = min_x + (px + 0.5) · size_x / (256 · 2^z)`, `Y = min_y + (py + 0.5) · size_y / (256 · 2^z)`, with
`min`/`size` the minimap corners of `src/data/maps.js` (X with `gameToMapScale`, Y with `gameToMapScaleY`,
as `squadGrid.js`). The finest zoom is the first with at most 0.33 m per pixel: zoom 7 for Skorpo and
Yehorivka (0.21 and 0.19 m), 6 for the 4–4.7 km maps, 5 for the small ones.

## Running

Requirements: the outputs of `tools/heightmaps` (`extract` and `build`: landscapes, statics and the
precise heightmaps, deployed), the SquadHeight release, Docker.

```sh
tools/maptiles/maptiles.sh setup          # extractor with the features mode (needs heightmaps.sh setup's CUE4Parse), Python image
tools/maptiles/maptiles.sh extract        # foliage, landscape splines, water actors of every map (about 15 min)
tools/maptiles/maptiles.sh prep           # ground, cover, 0.25 m objects, features into $WORK/prep (1–25 min per map)
tools/maptiles/maptiles.sh render         # tiles into $DIST/maptiles/<map> (1–20 min per map)
tools/maptiles/maptiles.sh check          # alignment checks
tools/maptiles/maptiles.sh all skorpo     # the three steps for one map
```

Paths and parallelism are set with `SQUAD_DIR`, `SQUADHEIGHT`, `EXTRACT`, `HEIGHTMAPS`, `WORK`, `DIST`,
`CUE4PARSE` and `WORKERS` (see the script header). Everything runs under `nice`. A map's tiles are
rendered into `$DIST/maptiles/.<map>.tmp` and swapped in when complete; the page requests tiles with
`?v=<meta.json generated>`, so the long cache lifetime set by Caddy never serves a stale tile.
After a game patch: `heightmaps.sh extract build deploy`, then `maptiles.sh extract prep render check`.

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

Because the fields are taken from the basemap itself, the distance to it is small by construction; it shows that
nothing is lost in the re-drawing, not that the colours generalise. Commands: `maptiles.sh colour-fit`, `colour-relief`,
`colour-render`, `colour-distance`; the Python image is the one of `setup`.

Files:

* `maptiles.sh` — the steps above;
* `py/features.py` — foliage, splines, water and ground cover from the extracted data, and the
  classification rules (by mesh name) of foliage, splines and objects;
* `py/prep.py` — per map: ground and cover on the 1 m grid, the 0.25 m object raster and its pyramid,
  building labels (reuses `tools/heightmaps/py`: landscape, objects, build_heightmap, maps);
* `py/render.py` — the tile renderer: styles, contour and label placement, layer order;
* `py/check_alignment.py` — the checks;
* `py/fit_palette.py`, `py/fit_fields.py`, `py/fit_relief.py`, `py/colour_distance.py`, `py/styles/` — the game colours above.

Sizes (build 26005357): about 13 KB per tile; prepared rasters a few hundred MB to 3 GB per map in
`$WORK/prep` (only needed to re-render).
