# Collision semantics for projectiles (Squad build 26005357)

What the game's collision means for bullets, rockets, mortar and artillery shells and grenades, read only from the
dedicated-server files (`SquadGame/Content/Paks`, `.utoc/.ucas` via CUE4Parse; the client pak is not used). Every
statement carries a label:

* VERIFIED: read directly from game data or the server binary; the evidence is named.
* INFERRED: follows from verified data plus standard Unreal Engine behaviour; the reasoning is stated.
* UNVERIFIED: not decidable from the server files; section 7 gives the in-game test that settles it.

Nothing here was run on any game server (no connection, no RCON). Reproduction commands are in section 8; the
Russian version is `collision-semantics.ru.md`.

## 1. Answers in short

> **Owner decisions (2026-11-04):** no penetration or through-obstacle calculation is made (armour-piercing rounds do not damage structures; HE and HEAT explode on them). Windows and doors in Squad are either open (no glass, no door leaf) where players can enter, or belong to non-playable apartments and are closed: an open window or doorway is a hole in the geometry and stays one, a closed window or door is solid. The in-game tests T1-T9 of section 7 are not planned. Sections 4-6 stay as the record of what the game files contain.


| Question | Answer | Label |
|---|---|---|
| Channel of bullets, rockets, mortar/artillery shells | Collision profile `Projectile` (SQProjectile, SQMortarProjectile, SQGuidedProjectile) | VERIFIED for the profile name, INFERRED for what the profile contains |
| Channel of grenades | Profile `Throwable` (SQGrenadeProjectile, SQSmokeGrenadeProjectile) | VERIFIED name |
| Static meshes block projectiles | Yes for 93 % of the 44528 Fallujah placements (41442 Block); 34 Overlap; 3052 Ignore | VERIFIED |
| Splines (roads, kerbs) | 2852 of 44528 placements Ignore Projectile | VERIFIED |
| Foliage (trees, rocks) | All 11616 collision-enabled foliage placements are BlockAll, Projectile Block | VERIFIED |
| Landscape | Heightfield collision only; no weightmaps in the server files | VERIFIED (absence); response INFERRED Block |
| Glass and windows are collision | Yes: glass sections are enabled in the cooked complex mesh | VERIFIED |
| Shell can enter a building | Only through geometry holes (doors, arches, broken walls). Window glass blocks on the complex mesh | VERIFIED geometry, UNVERIFIED which mesh the projectile trace uses |
| Complex (triangle) or simple (hull) trace | Not decidable from files | UNVERIFIED |
| Doors | No door actors in the non-gameplay levels; doorways are static openings in wall meshes | VERIFIED for statics, UNVERIFIED for gameplay-layer actors |
| Material lethality and splash modifiers | Absent from game data | VERIFIED absence |
| Penetration data per material | Present (`damage_absorbed`, `armor_thickness_mm`, flags) | VERIFIED |

## 2. Channel and profile of projectiles

Evidence: the native constructors in the server binary (`SquadGameServer`, ELF). The class vtable is located with
`nm -D`; the constructor is the place that stores `vtable+0x10`; the call to the collision profile setter
(`0x81fa3d0`, UPrimitiveComponent::SetCollisionProfileName) is found after it and the preceding FName string is
read (`semantics/elf_profiles.py ctor|setter`).

| Class | vtable | Constructor store site | Profile name set |
|---|---|---|---|
| ASQProjectile | 0x23d1ee0 | 0xa731b97 | `Projectile` (sphere component `SphereCollision`, call site 0xa731db0) |
| ASQMortarProjectile | 0x23a8f10 | 0xa735da7 / 0xa735eec | `Projectile` (inherits) |
| ASQGuidedProjectile | 0x235c2a0 | 0xa735e56 | `Projectile` (inherits) |
| ASQGrenadeProjectile | 0x2352a30 | 0xa7318a9 | `Throwable` |
| ASQSmokeGrenadeProjectile | 0x241fbc0 | 0xa74b127 | `Throwable` |
| USQProjectileRootComponent | 0x23d48d8 | 0xa74807c | root, no query of its own |

Blueprint projectiles (138, resolved by `semantics/projectile_profiles.py`): 68 SQMortarProjectile and 29 SQProjectile and 10 SQGuidedProjectile
resolve to `Projectile`; 13 grenade and 8 smoke grenade to `Throwable`; 6 mortar blueprints override to `Custom`, 2 to
`Throwable`, 2 to `NoCollision` (the override is the Blueprint's own CDO template). None of them serialises response
overrides, so the response table of the `Projectile` profile itself is the open item.

The profile table (`DefaultEngine.ini`, `[/Script/Engine.CollisionProfile]`) lives in an AES-encrypted pak index and was
not circumvented. Therefore:

* The channel name `Projectile` and the profile `Projectile`/`Throwable`: VERIFIED.
* The `Projectile` profile's object type and response set: UNVERIFIED as a table, INFERRED from the following verified
  fact: every `BlockAll` static placement serialises `Projectile = Block` (section 3), and the `SQProjectileRootComponent` entries
  with profile `Throwable` serialise a Projectile response of `Ignore`, i.e. throwables do not collide through the
  Projectile channel.

## 3. Response per class of object (Fallujah, all non-gameplay levels)

`semantics/static_semantics.py` resolves, per placed component, the effective response to the Projectile channel:
a `BodyInstance` stores only a delta against the engine default container (unlisted channel = Block), then falls back
to the mesh default instance. Result for the 44528 static placements:

| Component | Profile | Projectile | Trace flag | Placements |
|---|---|---|---|---|
| InstancedStaticMeshComponent | BlockAll | Block | UseDefault | 32677 |
| SplineMeshComponent | BlockAll | Block | UseComplexAsSimple | 3502 |
| InstancedStaticMeshComponent | BlockAll | Block | UseComplexAsSimple | 3131 |
| SplineMeshComponent | BlockAll | **Ignore** | UseDefault | 1603 |
| SplineMeshComponent | BlockAll | **Ignore** | UseComplexAsSimple | 1249 |
| InstancedStaticMeshComponent | Custom | Block | UseDefault | 978 |
| SplineMeshComponent | BlockAll | Block | UseDefault | 757 |
| InstancedStaticMeshComponent | BlockAll | Block | UseSimpleAndComplex | 256 |
| InstancedStaticMeshComponent | BlockAll | Ignore | UseDefault | 145 |
| InstancedStaticMeshComponent | Custom | Block | UseSimpleAndComplex | 131 |
| InstancedStaticMeshComponent | Custom | **Overlap** | UseDefault | 34 |
| StaticMeshComponent | NoCollision | Ignore | UseDefault | 27 |
| others (Custom Ignore 15, BlockAll Block 10, IMC NoCollision 4, IMC BlockAll Ignore ComplexAsSimple 9) | | | | 38 |

All values VERIFIED (levels `Maps/Fallujah/**`). Foliage (`FoliageInstancedStaticMeshComponent`, 11616 placements with
collision): all BlockAll, Projectile Block (6315 convex, 4464 convex+capsule, 837 without simple shapes); no per-body
physical-material overrides (`foliage_fallujah.json`).

Blueprint components under `Blueprints/Items` and `Vehicles` (`semantics/component_profiles.py`): vehicle
wheels and tracks (`VehicleTireMesh`) Block; complex vehicle meshes (`ComplexVehicleMesh`) Block; character
skeletal meshes `Pawn`/`BlockAllDynamic` Block; decorative static meshes `NoCollision` Ignore; interaction and
construction boxes (`InteractZone`, `ConstructionZone`, `OverlapAllNotPawn`) Overlap or Ignore. Deployables
(emplacements, construction pieces) therefore Block with their body meshes, with zone boxes Ignore/Overlap.

Water: the 33 water meshes of Fallujah carry 396 collision triangles in total and are `UseDefault`; the physical
material `PhysMat_Water` has `overlaps_throwable_projectiles = true` (BP_MaterialEffects). Whether bullets or shells
collide with the water surface at all: UNVERIFIED (test T7).

### Trace flag and shapes

| Trace flag / representations | Meshes | Placements | Complex triangles | Simple triangles |
|---|---|---|---|---|
| UseDefault, complex and simple | 3326 | 35240 | 64987180 | 4229584 |
| UseComplexAsSimple, complex and simple | 62 | 2809 | 4348850 | 286658 |
| UseSimpleAndComplex | 17 | 387 | 1571914 | 204186 |
| UseComplexAsSimple, complex only | 4784 | 5090 | 1548469 | 0 |
| UseDefault, complex only | 115 | 646 | 699564 | 0 |
| UseDefault, simple only | 10 | 280 | 0 | 10918 |
| UseDefault, nothing cooked | 39 | 76 | 0 | 0 |

(`semantics/mesh_collision_kinds.py`, all VERIFIED; counts are distinct meshes and placements of the 8353 meshes of
Fallujah.) `UseDefault` lets a complex trace hit the triangles and a simple trace hit the AggGeom hulls. Whether
projectile sweeps use `bTraceComplex` is UNVERIFIED (test T6). Both bounds are given in section 4.

## 4. Windows, glass and building interiors (Fallujah)

### Triangles per object class

Placement-weighted collision triangles (`semantics/class_table.py`, VERIFIED counts; class assignment is by asset path
prefix, see the script):

| Class | Meshes | Placements | Complex triangles x placements | Simple triangles x placements |
|---|---|---|---|---|
| buildings | 457 | 8180 | 24754041 | 2440760 |
| props and infrastructure | 788 | 12433 | 14832225 | 684382 |
| vehicles and wrecks | 70 | 1230 | 14450814 | 143252 |
| walls, fences, barriers | 418 | 11578 | 12182004 | 479104 |
| roads and pavements | 6428 | 6756 | 1689634 | 424830 |
| editor and blockout | 50 | 652 | 1047314 | 9764 |
| other | 109 | 3666 | 4199549 | 549254 |
| water meshes | 33 | 33 | 396 | 0 |

The complex mesh is about 10 times the triangle count of the simple one for buildings.

### Glass is collision

`bEnableCollision` per LOD0 render section and its physical material (`extractor meshsections`, then
`semantics/section_materials.py`): on 97 meshes (65 are buildings) glass sections exist, all of them with collision
enabled. `PhysMat_GlassWindow`: 628628 collision-enabled triangles on 65 meshes, 0 disabled. `PhysMat_Glass`:
191036 on 9 meshes. For these meshes the sum of the collision-enabled render triangles equals the cooked complex
triangle count (e.g. ME_UrbRes_Bld_Med_03: 1533 = 1533), so glass is part of the cooked complex collision:
VERIFIED. Glass in the 65 building meshes: 24348 triangles, 574874 placement-weighted.

Material data for glass (`data/materials.json`): `consider_for_penetration = true`, `allow_penetration = true`,
`damage_absorbed = 20`, `armor_thickness_mm = 1`. Brick: 100 and 10 mm; DryMudWall: 200 and 20 mm; concrete: 120 and
10 mm (no `allow_penetration` entry); metal: 50 and 5 mm. A projectile that uses the complex mesh therefore hits glass
as a surface; whether it penetrates is a gameplay rule driven by these penetration fields (INFERRED).

### Exact tracer through the window

`semantics/window_demo.py` casts, with the exact Moller-Trumbore tracer (`py/reference.py`, float64, no voxels),
a 4 m segment centred on every glass triangle (at least 0.05 m^2) along its normal. The glass section order is the
render section order (INFERRED; the section triangle total equals the cooked count and the script aborts otherwise):

| Mesh | Glass triangles | Segment blocked by glass | Segment passes open wall behind glass | Segment also hits a wall | Hit by simple shapes |
|---|---|---|---|---|---|
| ME_UrbRes_Bld_Med_03 | 158 | 158 | 119 | 39 | 156 |
| SM_ME_UrbRes_Bld_Med_11 | 215 | 215 | 125 | 90 | 215 |

Reading: with the complex mesh every window segment is stopped by its pane; with the glass removed 75 % and 58 % of
the segments go straight through a hole in the wall, so the panes plug real openings and a shell is stopped by the
glass only because the glass is collision. With the simple shapes (a closed hull) nearly all window segments are
stopped by the hull, i.e. under a simple trace windows are walls. The remaining segments hit interior walls or window
frames inside 2 m. VERIFIED geometry; which mesh the projectile uses is UNVERIFIED (T6).

### Interiors and openings

`semantics/building_interiors.py` rasterises the complex collision of the 351 `MiddleEast/Buildings` meshes of
Fallujah into a 0.25 m occupancy grid, takes an enclosed floor region with a virtual ground slab, and fans rays from
three random room points to measure openings (azimuth step 3 degrees, elevation -15..45 degrees, sky components
removed). Because the grid is built from the complex mesh, glazed windows are closed; the openings are unglazed holes
(doors, arches, collapsed walls).

| Quantity | Value |
|---|---|
| Meshes analysed | 351 (7265 placements) |
| With an enclosed room of at least 4 m^2 | 107 meshes (1681 placements) |
| With at least one opening to outside | 83 meshes |
| Openings found | 447 |
| Opening width (m): min / median / max | 0.28 / 2.31 / 34.89 |
| Opening height (m): min / median / max | 0.22 / 1.79 / 8.99 |
| Sill above floor (m): min / median / max | -2.25 / 0.52 / 5.52 |
| Distance origin to opening (m): median | 4.8 |

VERIFIED as measurements of the cooked mesh; the extremes include whole open fronts and ground-level garage doors, so
use the median for doors and windows without glass. Interiors are modelled: rooms with floors, ceilings and inner
walls exist in 30 % of the building meshes. Whether a mortar can fly into them depends on the trace flag again (T6)
and on the roof/ceiling being solid (it is, in the complex mesh).

## 5. Doors and destructibles

* The non-gameplay levels contain 73 door/gate/shutter meshes (2038 placements), all static, `UseDefault`
  (e.g. `ME_WallStd_WallDoor_Medium`: 66 simple, 3246 complex triangles; `ME_WallStd_WallDoor_Small`: 12 and 1183).
  A doorway is a hole in the wall mesh. VERIFIED.
* Operable or destructible door actors in gameplay layers and destructible blueprints were not examined: UNVERIFIED
  (T4, T5). `PhysMat_*` entries with `damage_parent_actor` (17 materials) mark parts that damage their parent actor.
* The Destruction/Coop destructible blueprints' collision profiles are not part of this data set.

## 6. Materials and landscape

* 130 physical materials (`data/materials.json`, `semantics/materials.py`): `consider_for_penetration` 121,
  `allow_penetration` 116, `damage_absorbed` 101, `armor_thickness_mm` 101, `surface_type` 114, `friction` 117,
  `restitution` 97, `overlaps_throwable_projectiles` 65 (from BP_MaterialEffects). **`lethality_modifier` and
  `splash_radius_modifier` are null for every material: the game data has no such fields** (VERIFIED absence;
  nothing was invented).
* Landscape layers: 157 layer-info assets across 27 landscape asset packages map each layer to a physical material
  (e.g. Sand to `PhysMat_Sand`, Soil to `PhysMat_Dirt`, Asphalt to `PhysMat_Asphalt`, Reeds to
  `PhysMat_GrassTall_Rustle`). VERIFIED.
* Weightmaps: the dedicated-server levels contain only landscape heightfield collision (see
  `~/data/semantics/inventory_maps.json`, section 8), no `LandscapeComponent` weightmap textures: across the 3398 non-gameplay levels of all maps the export inventory
  counts 0 `LandscapeComponent` and 9240 `LandscapeHeightfieldCollisionComponent` (34 levels). Therefore no
  `~/data/materials/<map>/` rasters can be extracted from the server files: absent. Per-position terrain
  material is unavailable; only the layer-to-material legend exists. VERIFIED absence.
* Landscape collision response: INFERRED Block (heightfield collision with the default `BlockAll` landscape profile),
  UNVERIFIED as a table (T1).

## 7. In-game test protocol (squad2, DeadLine Training only)

Preconditions: squad2 only, never squad1; the user decides when. Two testers with admin rights on the server, no RCON from outside. Record each test as a short video plus the log
line. Use Fallujah (or the Training layer with the same buildings). Positions: stand 25 m from the target; for each
test do 5 repetitions and note hit or pass for every repetition.

| Id | Question settled | Setup | Action | Reading |
|---|---|---|---|---|
| T1 | Does a bullet hit the landscape and water | Flat open ground; a shallow water body | Fire 10 rounds at the ground and at the water 50 m away | Impact decal or effect at ground (Block) and at water (Block/Overlap/Ignore) |
| T2 | Bullet vs window glass (Projectile channel, complex or simple) | A building with a visible glass window at eye height, no wall behind line of fire | Fire 5 rounds at the pane centre from 25 m with a rifle | Pane breaks and bullet stops, or bullet passes into the room, or hits as a wall |
| T3 | Window that is a hole in a wall (no glass) | A broken window or an open arch of the same building | Fire 5 rounds through the opening at a wall inside | Impact on the inner wall (complex/simple confirmed) |
| T4 | Door | A building with an operable door (open and closed) | Fire at the door closed, then open | Impact on the door or the wall behind |
| T5 | Destructible parts | A destructible fence, barrel or similar | Fire 10 rounds | Object state changes; note whether the bullet continues |
| T6 | Complex vs simple projectile trace | A building whose simple hull differs from its mesh (hollow room, front covered by the hull) | Mortar round (or 40 mm) fired into the window; also into a doorway of a hull building | Detonation at the hull face or inside the room reveals the trace type; compare with section 4 |
| T7 | Water surface | Deep water | Fire 5 rounds, 1 mortar, 1 grenade | Splash/impact at the surface or the round continues |
| T8 | Mortar at roof and foliage | A solid roof and a tree line | 1 mortar round on the roof, 1 on a tree crown | Detonation point on roof/crown vs below |
| T9 | Grenade vs glass and door | A glass window | Throw 3 grenades at the pane from 10 m | Grenade bounces, breaks glass, or passes (Throwable profile) |

Pass criteria: a test settles the labelled item when 5 of 5 repetitions agree. Disagreement is itself evidence of
randomness (spread, penetration chance) and is recorded.

### Simple-collision primitives per map

Primitives of every BodySetup `AggGeom` multiplied by the mesh placements (`semantics/primitive_counts.py`, VERIFIED, all 25 maps; the last column counts distinct meshes that have any shape). Totals are in `data/primitives.json`; the per-mesh rows (path, placements, shapes) are written to `~/data/volumetric/primitives/<map>.json`. Spheres are almost absent and convex hulls dominate.

| map | box | sphere | capsule | convex | meshes |
|---|---:|---:|---:|---:|---:|
| albasrah | 166445 | 2 | 370 | 1392624 | 11989 |
| anvil | 16536 | 6 | 1359 | 76939 | 3395 |
| blackcoast | 18161 | 2 | 105 | 145315 | 2663 |
| chora | 5507 | 0 | 396 | 64719 | 6301 |
| fallujah | 69546 | 2 | 59 | 250916 | 3415 |
| foolsroad | 2521 | 0 | 15 | 10123 | 623 |
| goosebay | 11243 | 0 | 32 | 60865 | 1401 |
| gorodok | 8288 | 0 | 547 | 108795 | 1687 |
| harju | 48538 | 2 | 59 | 166611 | 4413 |
| jensen | 2424 | 0 | 39 | 7536 | 519 |
| kamdesh | 1662 | 0 | 2 | 59655 | 3992 |
| kohat | 2442 | 0 | 817 | 28025 | 2210 |
| kokan | 7037 | 0 | 374 | 10805 | 738 |
| lashkar | 4049 | 5 | 1210 | 70959 | 3083 |
| logar | 1883 | 5 | 111 | 24572 | 957 |
| manicouagan | 17902 | 0 | 33 | 122328 | 3583 |
| mestia | 1515 | 0 | 109 | 27125 | 787 |
| mutaha | 8562 | 0 | 1109 | 59790 | 4871 |
| narva | 48393 | 0 | 79 | 98148 | 4164 |
| pacific | 366 | 2 | 0 | 1529 | 42 |
| sanxian | 24701 | 0 | 89 | 731115 | 2918 |
| skorpo | 8152 | 0 | 87 | 111154 | 7348 |
| sumari | 15300 | 2 | 973 | 32691 | 3302 |
| tallil | 15864 | 0 | 665 | 64624 | 1172 |
| yehorivka | 14498 | 0 | 83 | 340220 | 3642 |


## 8. Reproduction

All commands run from `tools/volumetric/semantics` (`./py.sh` is a Docker wrapper over the `squadcalc-heightmaps-py`
image, with `~/data` at `/data`; heavy runs under `nice`). Data are in `~/data/semantics`.

| Result | Command |
|---|---|
| Projectile profile in the binary | `elf_profiles.py ctor <elf> <class>` and `setter` |
| Blueprint projectile profiles | `projectile_profiles.py` |
| Static and foliage response table | `static_semantics.py <statics dir> <out>` |
| Trace flag and shape counts | `mesh_collision_kinds.py <statics dir> <out>` |
| Simple primitives per map | `primitive_counts.py <statics dir> <out.json>` |
| Glass sections | extractor `meshsections`, `section_materials.py` |
| Class triangle table | `class_table.py kinds_fallujah.json classes_fallujah.json` |
| Window exact tracer | `window_demo.py <statics dir> <sections.ndjson> <mesh path> <out>` |
| Interiors and openings | `building_interiors.py <statics dir> kinds_fallujah.json 'MiddleEast/Buildings/' <out>` |
| Landscape export inventory | extractor `inventory /Maps/ <out.json>` |
| Materials | `materials.py` writing `data/materials.json` |
| Tests | `./py.sh -m unittest discover -s ../tests -p 'test_semantics.py'` |

Legal and scope note: only the dedicated server package was read (the client pak is never used); the encrypted pak
index (including `DefaultEngine.ini`) was not decrypted or circumvented, so the engine-level profile table is the one
piece of evidence that is missing.
