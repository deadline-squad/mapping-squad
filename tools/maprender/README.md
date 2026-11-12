# Standard HD map tiles rendered from the game's assets

The "Standard HD" layer of the Deadline SquadCalc: a top-down picture of every map, 0.19 to 0.32 m per pixel, in the look of the
game's own map. Served as 256 px webp tiles from `/maptiles/<map>-hd/<z>/<x>_<y>.webp` with `/maptiles/<map>-hd/meta.json`
(`src/js/squadMinimap.js`, `src/js/mapLayers.js`; a map without tiles falls back on the Detailed layer).

## Why a render

The game stores one 4096 x 4096 BC1 texture for a whole map (1 m per pixel on Gorodok, 0.67 on Mutaha, roofs clipped to white). A Seed
or Skirmish layer stores a finer capture of a part of the map. There is no finer capture of a regular map in the game files, so the
detail has to come from what the capture was made of: the meshes, materials, landscape layers and placements in the client's paks.

Detail comes from the render, colour from the capture:

| Step | What it does | Where |
|---|---|---|
| Scene | Meshes (LOD0), material instances, textures up to 512 px, placements of all art levels, landscape layer weights. Keyless with CUE4Parse on the client paks. A spline mesh is bent along its spline as the engine bends it, with the spline's scale, offset and roll (`spline_mesh.bend_along_spline` of `tools/heightmaps/py`, shared with `tools/maptiles`): the landscape splines stand a mesh that runs along its Y axis up by a roll of -90 degrees (pipelines, crash barriers, railway tracks, fences, foot bridges), and without the roll it is drawn on its side and off its line (Manicouagan's double pipeline as one thin line 3.2 m beside its place). With it the box of a bent mesh is the box of the server's cooked collision of the same component: of the 10 419 rolled components of the 25 maps that the server has (116 meshes, 228 counted per map), 9 943 (213 of the meshes per map) differ by 2 cm or less on the median of their mesh, the others by at most 0.41 m where the collision is not the visible shape, except Skorpo's tunnels and Black Coast's retaining walls, whose collision reaches 4 to 5 m below the visible mesh (without the roll the medians are up to 103 m off). Vista levels (scenery beyond the map) and navmesh levels are left out; the render also skips editor-only levels (`_Editor_Only`, Blackcoast's POI size rings) and the other `SKIPPED_LEVEL_PARTS` of `scene_render.py`, and the lighting's sky dome (`SKY_COMPONENT`: the sky spheres of Black Coast and Yehorivka, which a top-down pass would see from inside over the whole map once the depth range follows the scene). Any failed level fails the map | `maprender.sh scene`, `tools/heightmaps/extractor` mode `scene` |
| Registration | Edges of a first render against the whole-map texture on 25 patches give an offset and a scale per axis. The capture lies on the geometry within a metre (the texture over the game's corners, measured on the world by the edges of the level's features: Kamdesh 0.17 m, Kokan 0.75 m); Skorpo's is at another scale: it shows 6868.8 m where its image corners span 6849 m, 0.1 m off at the west edge and 19.7 m at the east. The texture is warped onto the render; under 1.5 m it is left alone | `registration.py` |
| Layer colours | One colour per landscape layer by robust least squares against the texture on open ground, away from water and the map's dark border. A layer seen on few cells stays near the median colour. The engine's own textures (the grid and cross defaults `BlendFunc_DefBase` and `BlendFunc_DefBlend` that the landscape material lists beside its ground textures) never give a layer its detail pattern | `ground_fit.fit_layer_colours` |
| Ground cover | Foliage meshes the capture does not show (crops, flowers) are left out unless they are tall; the test is the contrast of the texture under their instances | `ground_fit.invisible_foliage` |
| Material gains | Per material, the median ratio of the texture to the render on that material's pixels; leaves are measured on their darkest pixels and limited in luma so sand cannot lift them; roofs that the texture clips to white get the roof colour measured on Mutaha Seed v1 | `ground_fit.calibrate_materials` |
| Crowns | The capture used distant levels of detail, so a tree reads as a solid round crown: a lumpy dome replaces the mesh of foliage of 1 m and more. Palms keep their fronds, crops their stems | `scene_render.crown_dome` |
| Tone field | The ratio of the texture to the render, blurred on open ground only (2 m, 40 m where there is little open ground) and limited to 0.55 to 1.8, carries what the render has no source for: mottling, field stripes, colour patches, the dark border. Water has a field of its own, so neither colours the other across the shore. Light roofs are protected | `render_map.tone_field`, `render_map.apply_tone` |
| Tiles | Orthographic render on the GPU with 2 x SSAA and a contact shadow from depth, in blocks of 4 x 4 tiles that overlap in the depth pass so they agree at their edges. The depth range is -500 m to 1000 m, widened to the lowest and highest object and landscape of the map (Chora lies 770 m below sea level). First zoom with at most 0.33 m per pixel, coarser zooms by 2 x 2 averaging | `scene_render.Scene.render`, `render_map.render_zoom`, `render_map.build_pyramid` |

The sun (azimuth -135, elevation 65) is not fitted. Nothing is generated by a model: every object in a tile is an object of the game
at its place in the game, every colour comes from the game's textures and capture.

## Tile frame

Pixel (px, py) of zoom z is centred at `min + (p + 0.5) * size / (256 * 2 ** z)`, as `tools/maptiles`, with the frame of the prepared
ground of that tool (`$PREP/<map>/meta.json`).

## Use

```sh
./maprender.sh build             # SquadExtract with the scene mode
./maprender.sh scene [map ...]   # assets into $SCENES/<map>; EXTRACT_MEMORY limits the container (default 11g)
./maprender.sh render [map ...]  # tiles into $DIST/<map>-hd; a finished map is skipped unless FORCE=1
./maprender.sh all [map ...]

python -m unittest test_maprender   # MAPRENDER_SCENE=<map> MAPRENDER_TEXTURE=<name> adds the checks on a real scene and the GPU: tile seams and determinism
```

Needs an OpenGL 4.3 GPU with EGL (a GTX 1650 with 4 GB holds every map), `moderngl`, `numpy`, `scipy`, `pillow`, the game client under
`$CLIENT_DIR`, `tools/heightmaps/py` beside this folder (the map list and the spline mesh deformation) and the output of `tools/maptiles`
(`$PREP`) with the texture table of its `layer-minimaps` step. A map takes 4 to 40 minutes.
After a game patch: `FORCE=1 ./maprender.sh all`. The tiles are written beside the old ones and swapped in by a rename, so a failed run
leaves the map as it was.

`meta.json` keeps the provenance of a map: texture, layer colours, material count, texture warp, time of generation.
