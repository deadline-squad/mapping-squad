# Data provenance of the firing solution (Squad build 26005357)

Every input of the firing solution of the two apps, per weapon, with the asset it comes from and a label. The apps are
Squad Ballistics (SB, `weapons.json`, 167 weapons, version 1.7.1) and the Deadline SquadCalc (SC, `src/data/weapons.js`,
145 weapons, version 45.39.0). The game data is the dedicated-server package only (`SquadGame/Content/Paks`; the client pak is not used).
Russian version: `data-provenance.ru.md`. Nothing here was run on a game server. Every statement carries a label (the
vocabulary of `docs/thesis-methods-and-results.md` section 0, plus ASSUMED):

* **VERIFIED**: read from the game files by a committed tool, reproducible, and the app's value equals it.
* **INFERRED**: derived from verified data by an argument that is stated (a native default, the resting value of a spread
  curve, a limit computed from the mount's pitch, "no field of this kind exists in any Blueprint").
* **UNVERIFIED**: recorded without a reproducible output (a fit to the owner's in-game measurements, a one-off read of a
  skeleton, a Blueprint this machine's dump lacks) or not decidable from the server files.
* **ASSUMED**: not in the server files at all: Workshop mods, the handheld weapons' bore and zoom (they come from the
  client's first-person animation), the native C++ explosion defaults (`NATIVE_EXPLOSION` in `gamecheck.py`), SquadCalc's
  default lifespan of 100 s, SquadCalc's shoulder height.

The tables below are generated (`tools/game_ballistics/provenance.py`, section 9); the long form, one line per weapon,
shell and input with the value used, the game value, the source and the label, is `data-provenance.tsv` next to this file.

## 1. Answers in short

| Question | Answer | Label |
|---|---|---|
| Muzzle velocity, gravity scale, rocket motor (acceleration, timeout, ignore-gravity), `MaxSpeed`, `bRotationFollowsVelocity` of every weapon that has a game class | Equal to the Blueprints in both apps, for 167 SB and 135 SC weapons; no unexplained difference (the one explained: SC keeps one cap for the AP and HE shells of three 30 mm weapons, no effect at their 970 / 950 m/s) | VERIFIED; a field no Blueprint sets (gravity 1, no motor, no cap, rotation follows) is the engine's default: INFERRED |
| Air drag | None: no projectile movement component of the 797 weapon classes of `resolved.json` has a drag field (their keys are listed in section 3), and the server code reading of `USQProjectileMovement` in `ballistics.py` agrees | INFERRED (the code reading is not re-run here) |
| Projectile lifespan (`InitialLifeSpan`) | **A difference was found and fixed**: the 108 generated direct-fire weapons of SC had SC's default of 100 s while the game destroys the round after 4-40 s; SB had no lifespan at all. Both apps now carry the game's value (SB 1.6.1 `lifespan`, SC 45.30.0 `projectileLifespan`) and refuse a shot that takes longer: an RPG-7 target at 1500 m (6.6 s) is out of reach, the rocket is gone after 4 s, about 900 m | VERIFIED |
| Spread | SC uses `WeaponConfig.MOA`. Where the weapon also names a `MOACurve` (grenade machine guns, heavy machine guns, Kord) the game spreads by the curve, and SC takes a value of it: the resting one (15 / 3 / 7 MOA) for the generated weapons, the sustained one (50) for the AGS-17 (inherited). SB does not use a spread | VERIFIED for `MOA`; INFERRED for the curve values (asset in the dump for the grenade curve, 15 at 0 and 50 at 0.75); UNVERIFIED for the HMG and Kord curves (assets not in this dump) |
| Explosion (damage, inner and outer radius, falloff, height) | Equal to the Blueprints for every SC shell that has a game class. The fields no Blueprint sets are the native C++ defaults of `ASQProjectile`, which no file holds | VERIFIED where set; ASSUMED where native (the cell lists them) |
| Bore, zoom of SB | Read from the vehicle and tripod Blueprints and skeletons for 134 weapons; the 26 handheld launchers have bore 0 and zoom 1 assumed | VERIFIED / ASSUMED |
| Launch point, elevation limits | From the game for the vehicle mounts (`tools/game_weapons.py`); the tripod weapons (mortar, UB-32, Hell Cannon) from one-off skeleton reads; the AGS-17 emplacement uses 1 m although the files say 0.347 m (kept on purpose, SB release notes 1.6.0 #13) | VERIFIED / UNVERIFIED |
| Hold rate and the top of the hold of the AGS-17 entries | Fitted to 67 in-game measurements (not in the repositories); the files give 9.00 deg/s | UNVERIFIED |
| Weapons whose values come from the old upstream SquadCalc table | Mortar, UB-32, HellCannon, Tech.Mortar, Tech.UB-32, BM-21Grad, M1064M121, Mk19, BTR4-AGS (section 6) and the ten Workshop-mod weapons | the game confirms the velocity, gravity, spread and explosion of the first nine (VERIFIED); the rest of their fields: ASSUMED / UNVERIFIED |

## 2. What the apps read

| Input | SB field | SC field | Game source (Blueprint property) |
|---|---|---|---|
| muzzle velocity | `velocity` | `shells[].velocity` | `WeaponConfig.MuzzleVelocity` of the weapon class (cm/s) |
| projectile gravity scale | `gravity` (x 9.80 m/s^2) | `gravityScale` | `ProjectileGravityScale` of the projectile's `ProjectileComp` (1.0 when no Blueprint sets it) |
| rocket motor | `acceleration`, `acceleration_time` | `acceleration` / `accelerationTime`, or `deceleration` / `decelerationTime` | `ConstantAcceleration.X`, `ConstantAccelerationTimeout`, `bIgnoreGravityDuringConstantAcceleration` |
| speed cap | `max_speed` | `maxSpeed` | `MaxSpeed` (0 = none) |
| rotation of the motor | `rotation_follows_velocity` | `rotationFollowsVelocity` | `bRotationFollowsVelocity` (the `ASQProjectile` constructor sets true) |
| drag | none | none | none |
| launch point | `launch_height`, `muzzle_forward`, `muzzle_up` | `muzzle` {`pivotHeight`, `forward`, `up`}; else `heightOffset`; else the shoulder (1.5 m) | the barrel socket `Attach_Muzzle` on the mount (`tools/game_weapons.py` launch) |
| spread | not used | `shells[].moa` | `WeaponConfig.MOA`, `WeaponConfig.MOACurve` |
| lifespan | `lifespan` (1.6.1) | `projectileLifespan` (default 100) | `InitialLifeSpan` of the projectile |
| explosion | `warhead` (splash when the damaging radius is over 10 m) | `explosionDamage`, `explosionRadius`, `explosionDistanceFromImpact`, `damageFallOff` | `ExplosiveBaseDamage`, `...InnerRadius`, `...OuterRadius`, `...Falloff`, `...DistanceFromImpactNormal` and the secondary explosion |
| sight | `bore`, `zoom` | none | barrel socket pitch against the camera; `BlueprintOnZoom` FOV divisor |
| elevation limits, minimum distance | `elevation_limits`, `min_distance` | `minElevation`, `shells[].minDistance` | the mount's `PitchInterval` plus the socket pitch (limits); no game field for the minimum distance |
| sight scale offset | `angle_offset` | `angleOffset` | none |
| hold model | `hold_rate`, `hold_elevation` | `elevationRate`, `holdElevation` | none (fitted) |

## 3. Counts of the labels

Rows are weapons for the inputs of a weapon and weapon-and-shell pairs for velocity, spread and explosion; an input an
app does not use (SB has no spread, SC no sight) and the inputs a weapon does not have are not counted.

<!-- generated:counts -->
| Input | SB VERIFIED | SB INFERRED | SB UNVERIFIED | SB ASSUMED | SC VERIFIED | SC INFERRED | SC UNVERIFIED | SC ASSUMED |
|---|---|---|---|---|---|---|---|---|
| muzzle velocity | 167 | - | - | - | 151 | - | - | 13 |
| gravity scale | 167 | - | - | - | 151 | - | - | 13 |
| constant acceleration, timeout, ignore gravity | 167 | - | - | - | 151 | - | - | 13 |
| MaxSpeed | 167 | - | - | - | 151 | - | - | 13 |
| bRotationFollowsVelocity | 2 | 42 | - | - | 2 | 39 | - | 13 |
| drag | - | 167 | - | - | - | 151 | - | 13 |
| launch point | 131 | - | 6 | 30 | 80 | - | 5 | 60 |
| spread (MOA) | - | - | - | - | 120 | 18 | 13 | 13 |
| lifespan | 167 | - | - | - | 146 | - | - | 18 |
| explosion | 84 | 27 | - | - | 50 | 26 | 8 | 80 |
| bore | 134 | - | - | 26 | - | - | - | - |
| zoom | 134 | - | - | 26 | - | - | - | - |
| elevation limits | 138 | - | - | 29 | 85 | - | - | 60 |
| min distance | - | - | - | 3 | - | 1 | - | 14 |
| angle offset | - | 1 | - | - | - | 1 | - | 3 |
| hold model | - | - | 9 | - | - | - | 8 | - |
| **total** | **1458** | **237** | **15** | **114** | **1087** | **236** | **34** | **326** |
<!-- /generated:counts -->

The air-drag claim: the keys of the projectile movement components of the projectiles of all 797 weapon classes of `resolved.json` are
`InitialSpeed`, `MaxSpeed`, `ProjectileGravityScale`, `ConstantAcceleration`, `ConstantAccelerationTimeout`, `Bounciness`,
`Friction`, `bBounceAngleAffectsFriction`, `bAutoActivate`, `bRotationFollowsVelocity`, `MovementModes`,
`bIgnoreGravityDuringConstantAcceleration`, `MaxSimulationIterations`, `bUseAdditiveJitter`; none is a drag or damping term
(`Friction` belongs to bounces).

## 4. Game classes and the weapons that use them

A class is a weapon Blueprint with its projectile Blueprint; the values are those of the chain merged along the Blueprint
inheritance (`collect.py`, `gamecheck.py`; units m, m/s, s). The explosion cell is the widest damaging explosion
(`blast()`); `[native: ...]` lists the fields no Blueprint sets (ASSUMED: `NATIVE_EXPLOSION`). A weapon of SC with
several shells (HEAT and HE) appears in the class of each shell. Thirteen SB entries (the PARS III and TAPV C16 MK19 with the
zoom levels of their sights, five AGS-17 on vehicles, the QLZ87 on the ZBL08 in both views) name weapon Blueprints that
`resolved.json` lacks; their class row shows the snapshot's values
(`tests/data/game_weapons.json`) and no spread.

<!-- generated:classes -->
| # | Game class (weapon Blueprint, projectile Blueprint) | v m/s | g | Motor | cap | Life s | MOA | Explosion (damage, radii m, height m, falloff) | SB | SC |
|---|---|---|---|---|---|---|---|---|---|---|
| C01 | `Blueprints/Items/GrenadeLaunchers/M4M203_UGL/BP_M4M203_UGL_Parent` -> `BP_40MM_Proj2` | 76 | 1 | - | - | 20 | 30 | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | M203 / M320 / GP-25 / HK79 / SL40 | DF_M203_M320_GP_25_HK79_SL40 |
| C02 | `Blueprints/Items/GrenadeLaunchers/MGL_GL/BP_MGL_Parent` -> `BP_40MM_Proj2` | 75 | 1 | - | - | 20 | 30 | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | MGL / M32 | DF_MGL_M32 |
| C03 | `Blueprints/Items/GrenadeLaunchers/MPT76AK40_UGL/BP_MPT76_AK40GL_UGL_Parent` -> `BP_40MM_Proj2` | 70 | 1 | - | - | 20 | 30 | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | AK-40GL (MPT-76) | DF_AK_40GL_MPT_76 |
| C04 | `Blueprints/Items/GrenadeLaunchers/QBZ-95-1_QLG-10_UGL/BP_QBZ95-1_QLG-10_UGL_Parent` -> `BP_40MM_VOG_Proj2` | 78 | 1 | - | - | 20 | 40 | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | QLG10 | DF_QLG10 |
| C05 | `Blueprints/Items/GrenadeLaunchers/FNFAL_GL/BP_FNFAL_GL_Frag` -> `BP_Projectile_RifleGrenade_FNFAL_Frag` | 76 | 1 | - | - | 20 | 30 | 250, 4-18, 0.08, x1 [native: falloff] | Rifle grenade | DF_Rifle_grenade |
| C06 | `Vehicles/M1117/Weapons/BP_M1117_MK19` -> `BP_40MM_MK19_Proj` | 230 | 1 | - | - | 20 | 50 | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | MK19; MK19 · M1117 · gunner sight ×4.5 | Mk19; DF_MK19 |
| C07 | `Vehicles/AAVP7A1/Weapons/BP_AAVP7A1_MK19` -> `BP_40MM_MK19_Proj` | 230 | 1 | - | - | 20 | 50 | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | MK19 · AAVP-7A1; MK19 · AAVP-7A1 · gunner sight ×4.5 | DF_MK19_AAVP_7A1 |
| C08 | `Vehicles/PARS_III/Sancak_RWS/Weapons/BP_SancakRWS_MK19` -> `BP_40MM_MK19_Proj` | 230 | 1 | - | - | 20 | not in resolved.json | radius 15 (snapshot) | MK19 · PARS III RWS; MK19 · PARS III RWS · gunner sight ×3; MK19 · PARS III RWS · gunner sight ×9 | DF_MK19_PARS_III_RWS |
| C09 | `Vehicles/TAPV/Protector_C16/BP_C16_MK19` -> `BP_40MM_MK19_Proj` | 230 | 1 | - | - | 20 | not in resolved.json | radius 15 (snapshot) | MK19 · TAPV C16 RWS; MK19 · TAPV C16 RWS · gunner sight ×5; MK19 · TAPV C16 RWS · gunner sight ×12 | DF_MK19_TAPV_C16_RWS |
| C10 | `Vehicles/Emplaced_Mk19/BP_Mk19_OpenTurret_Weapon` -> `BP_40MM_MK19_Proj` | 230 | 1 | - | - | 20 | 50 (curve FC_MOACurve_GenericGMG.0) | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | MK19 · M113 open turret; MK19 · M113 open turret · no sights; MK19 · M1151 open turret; MK19 · M1151 open turret · no sights; MK19 · MATV open turret; MK19 · MATV open turret · no sights | DF_MK19_M113_open_turret; DF_MK19_M1151_RHIB_open_turret; DF_MK19_M113_open_turret_no_sights; DF_MK19_M1151_open_turret_no_sights; DF_MK19_MATV_open_turret; DF_MK19_MATV_open_turret_no_sights |
| C11 | `Vehicles/RHIB/Weapons/BP_Mk19_RHIB_Weapon` -> `BP_40MM_MK19_Proj` | 230 | 1 | - | - | 20 | 50 (curve FC_MOACurve_GenericGMG.0) | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | MK19 · RHIB open turret; MK19 · RHIB open turret · no sights | DF_MK19_RHIB_open_turret |
| C12 | `Vehicles/Emplaced_Mk19/BP_Mk19_Weapon` -> `BP_40MM_MK19_Proj` | 235 | 1 | - | - | 20 | 50 (curve FC_MOACurve_GenericGMG.0) | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | MK19 · emplacement / C16 / L134A1; MK19 · emplacement / C16 / L134A1 · no sights | DF_MK19_emplacement_C16_L134A1; DF_MK19_emplacement_C16_L134A1_no_sights |
| C13 | `Vehicles/Emplaced_AGS-17/BP_AGS-17_Weapon_Optic` -> `BP_30mm_VOG19_Proj` | 185 | 1.8 | - | - | 40 | 50 (curve FC_MOACurve_GenericGMG.0) | 115, 1.5-18, 0.08, x1 [native: BaseDamage, falloff] | AGS-17 · emplacement · optic (RMB ×2.5); AGS-17 · emplacement · no optic | AGS-17; DF_AGS_17_emplacement_no_optic |
| C14 | `Vehicles/Emplaced_AGS-17/BP_AGS-17_Weapon` -> `BP_30mm_VOG19_Proj` | 185 | 1.8 | - | - | 40 | 50 (curve FC_MOACurve_GenericGMG.0) | 115, 1.5-18, 0.08, x1 [native: BaseDamage, falloff] | AGS-17 · iron sights emplacement | DF_AGS_17_iron_sights_emplacement |
| C15 | `Vehicles/Kozak_2M1_AFU/Weapons/AGS-17/BP_AGS-17_Technical_Weapon` -> `BP_30mm_VOG19_Proj` | 185 | 1.8 | - | - | 40 | not in resolved.json | radius 18 (snapshot) | AGS-17 · Technical | DF_AGS_17_Technical |
| C16 | `Vehicles/Kozak_2M1_AFU/Turrets/BP_AGS-17_OpenTurret_Weapon` -> `BP_30mm_VOG19_Proj` | 185 | 1.8 | - | - | 40 | not in resolved.json | radius 18 (snapshot) | AGS-17 · Tigr; AGS-17 · M1151; AGS-17 · BTR-D | DF_AGS_17_Tigr; DF_AGS_17_M1151; DF_AGS_17_BTR_D |
| C17 | `Vehicles/Kozak_2M1_AFU/Weapons/AGS-17/BP_AGS-17_Safir_Weapon` -> `BP_30mm_VOG19_Proj` | 185 | 1.8 | - | - | 40 | not in resolved.json | radius 18 (snapshot) | AGS-17 · Safir | DF_AGS_17_Safir |
| C18 | `Vehicles/Emplaced_QLZ87/BP_QLZ87_Weapon` -> `BP_35MM_Proj_QLZ87_HEDP` | 190 | 1 | - | - | 20 | 50 (curve FC_MOACurve_GenericGMG.0) | 115, 1-11, 0.08, x1 [native: BaseDamage, falloff] | QLZ87 · optic (RMB ×3); QLZ87 · no optic; QLZ87 · bunker tripod · optic (RMB ×3); QLZ87 · bunker tripod · no optic | DF_QLZ87; DF_QLZ87_no_optic; DF_QLZ87_bunker_tripod_no_optic |
| C19 | `Vehicles/CSK131/Weapons/BP_QLZ87_OpenTurret_Weapon` -> `BP_35MM_Proj_QLZ87_HEDP` | 190 | 1 | - | - | 20 | 50 (curve FC_MOACurve_GenericGMG.0) | 115, 1-11, 0.08, x1 [native: BaseDamage, falloff] | QLZ87 · CSK131 / WZ551 · optic (RMB ×3); QLZ87 · CSK131 / WZ551 · no optic | DF_QLZ87_CSK131_WZ551_no_optic |
| C20 | `Vehicles/Lynx_8x8/Weapons/BP_QLZ87_Weapon_Lynx8x8` -> `BP_35MM_Proj_QLZ87_HEDP` | 190 | 1 | - | - | 20 | 50 (curve FC_MOACurve_GenericGMG.0) | 115, 1-11, 0.08, x1 [native: BaseDamage, falloff] | QLZ87 · Lynx · optic (RMB ×3); QLZ87 · Lynx · no optic | DF_QLZ87_Lynx_CSK131_no_optic; DF_QLZ87_Lynx_CSK131 |
| C21 | `Vehicles/ZBL08/Turrets/Cupola_QLZ87/BP_QLZ87_Weapon_ZBL08` -> `BP_35MM_Proj_QLZ87_HEDP` | 190 | 1 | - | - | 20 | not in resolved.json | radius 11 (snapshot) | QLZ87 · ZBL08 · optic (RMB ×3); QLZ87 · ZBL08 · no optic | DF_QLZ87_ZBL08_no_optic |
| C22 | `Vehicles/BTR4/Weapons/BP_BTR4_KBA117` -> `BP_AGS30_40MM_VOG_Proj` | 190 | 1 | - | - | 20 | 15 | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | AGS-30 / BTR-4 AGS; AGS-30 / BTR-4 AGS · gunner sight ×9 | BTR4-AGS; DF_AGS_30_BTR_4_AGS |
| C23 | `Vehicles/BMP1TS_AFU/Weapons/BP_BMP1TS_KBA117` -> `BP_AGS30_40MM_VOG_Proj` | 190 | 1 | - | - | 20 | 15 | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | AGS-30 (BMP-1TS); AGS-30 (BMP-1TS) · gunner sight ×9 | DF_AGS_30_BMP_1TS |
| C24 | `Vehicles/BMP-2M/Weapons/Woodland/BP_BMP2M_AGS30` -> `BP_AGS30_40MM_VOG_Proj` | 190 | 1 | - | - | 20 | 15 | 115, 1-15, 0.08, x1 [native: BaseDamage, falloff, outer] | AGS-30 (BMP-2M); AGS-30 (BMP-2M) · gunner sight ×6 | DF_AGS_30_BMP_2M |
| C25 | `Blueprints/Items/RocketLaunchers/BP_M72A7_M72A5_2mags` -> `BP_M72A5_Rocket_Proj` | 144 | 1 | - | - | 20 | 15 | 100, 1.5-7.5, 0.08, x1 [native: falloff] | M72A7 LAW / RPG-26 | DF_M72A7_LAW_RPG_26 |
| C26 | `Blueprints/Items/RocketLaunchers/C90/BP_C90CR` -> `BP_C90_Rocket_Proj` | 160 | 1 | - | - | 20 | 10 | 115, 1.5-7.5, 0.08, x1 [native: BaseDamage, falloff] | C90-CR | DF_C90_CR |
| C27 | `Blueprints/Items/RocketLaunchers/BP_M136AT4` -> `BP_AT4_Rocket_Proj2` | 290 | 1 | - | - | 20 | 10 | 115, 1.5-7.5, 0.08, x1 [native: BaseDamage, falloff] | AT-4 | DF_AT_4 |
| C28 | `Blueprints/Items/RocketLaunchers/SMAW/BP_SMAW_HEAT_2mags` -> `BP_SMAW_Heat_Proj2` | 220 | 1 | 150 x 0.8 s | 220 | 4 | 7 | 200, 2-8, 0.08, x1 [native: falloff] | MK153 SMAW | DF_MK153_SMAW |
| C29 | `Blueprints/Items/RocketLaunchers/PF-98/BP_PF-98_Tandem_2mags` -> `BP_PF-98_Tandem_Proj` | 310 | 1 | 230 x 1.5 s | 310 | 10 | 7 | 200, 2-8, 0.08, x0 | PF98 · Tandem | DF_PF98_Tandem |
| C30 | `Blueprints/Items/RocketLaunchers/PF-98/BP_PF-98_HE_2mags` -> `BP_PF-98_HE_Proj` | 220 | 1 | 180 x 1.5 s | 220 | 20 | 7 | 200, 7-20, 0.15, x2 | PF98 · HE-I | DF_PF98_HE_I |
| C31 | `Blueprints/Items/RocketLaunchers/BP_RPG29` -> `BP_RPG29_Tandem_Heat_Proj2` | 280 | 1 | 80 x 1.1 s | 280 | 5 | 10 | 200, 2-8, 0.08, x1 [native: falloff] | RPG-29 | DF_RPG_29 |
| C32 | `Blueprints/Items/RocketLaunchers/DZJ-08/BP_DZJ-08` -> `BP_DZJ-08_Heat_Proj` | 172 | 1 | 150 x 0.8 s | 172 | 15 | 10 | 130, 2-7, 0.08, x1 [native: falloff] | DZJ-08 | DF_DZJ_08 |
| C33 | `Blueprints/Items/RocketLaunchers/RPG28/BP_RPG28` -> `BP_RPG28_Tandem_Proj` | 250 | 1 | - | 2500 | 5 | 20 | 200, 2-10, 0.08, x1.5 | RPG-28 | DF_RPG_28 |
| C34 | `Blueprints/Items/RocketLaunchers/RPG7/RPG7/BP_RPG7_Heat` -> `BP_RPG7_Heat_Proj2` | 117 | 1 | 150 x 0.8 s | 250 | 4 | 20 | 130, 2-8, 0.08, x1 [native: falloff] | RPG-7 · PG-7V HEAT / OG-7V | DF_RPG_7_PG_7V_HEAT_OG_7V |
| C35 | `Blueprints/Items/RocketLaunchers/RPG7/RPG7/BP_RPG7_Tandem` -> `BP_RPG7_Tandem_Heat_Proj2` | 63 | 1 | 45 x 0.6 s | 160 | 4 | 20 | 200, 2-10, 0.08, x2 | RPG-7 · PG-7VR Tandem | DF_RPG_7_PG_7VR_Tandem |
| C36 | `Blueprints/Items/RocketLaunchers/RPG7/RPG7V1/BP_RPG7V1_Tandem` -> `BP_RPG7_Tandem_Heat_Proj2` | 65 | 1 | 45 x 0.6 s | 160 | 4 | 15 | 200, 2-10, 0.08, x2 | RPG-7V1 · PG-7VR Tandem | DF_RPG_7V1_PG_7VR_Tandem |
| C37 | `Blueprints/Items/RocketLaunchers/RPG7/RPG7V2/BP_RPG7V2_Tandem_2mag` -> `BP_RPG7_Tandem_Heat_Proj2` | 117 | 1 | 45 x 0.6 s | 160 | 4 | 20 | 200, 2-10, 0.08, x2 | RPG-7V2 · PG-7VR Tandem | DF_RPG_7V2_PG_7VR_Tandem |
| C38 | `Blueprints/Items/RocketLaunchers/RPG7/RPG7/BP_RPG7_Thermo` -> `BP_RPG7_Thermo_Proj2` | 63 | 1 | 150 x 0.6 s | 160 | 4 | 20 | 200, 8-24, 0.08, x2 | RPG-7 · TBG-7V Thermobaric | DF_RPG_7_TBG_7V_Thermobaric |
| C39 | `Blueprints/Items/RocketLaunchers/RPG7/RPG7V1/BP_RPG7V1_Heat` -> `BP_RPG7_Heat_Proj2` | 117 | 1 | 150 x 0.8 s | 250 | 4 | 15 | 130, 2-8, 0.08, x1 [native: falloff] | RPG-7V1 · HEAT | DF_RPG_7V1_HEAT |
| C40 | `Blueprints/Items/RocketLaunchers/M3MAAWS/BP_M3MAAWS_Heat` -> `BP_M3MAAWS_Heat_Proj2` | 63 | 1 | 230 x 1.5 s | 230 | 4 | 7 | 130, 2-8, 0.08, x1 [native: falloff] | M3 MAAWS · HEAT / Smoke | DF_M3_MAAWS_HEAT_Smoke |
| C41 | `Blueprints/Items/RocketLaunchers/M3MAAWS/BP_M3MAAWS_Tandem` -> `BP_M3MAAWS_Tandem_Heat_Proj2` | 63 | 1 | 230 x 1.5 s | 230 | 4 | 7 | 200, 2-10, 0.08, x2 | M3 MAAWS · Tandem | DF_M3_MAAWS_Tandem |
| C42 | `Blueprints/Items/RocketLaunchers/BP_CarlGustavM2_Parent` -> `BP_FFV551_Rocket_Proj2` | 310 | 1 | 150 x 0.8 s | 310 | 4 | 7 | 130, 2-8, 0.08, x1 [native: falloff] | Carl Gustav M2 · FFV551 HEAT | DF_Carl_Gustav_M2_FFV551_HEAT |
| C43 | `Blueprints/Items/RocketLaunchers/BP_CarlGustavM2_FFV441D_No78Mk1` -> `BP_FFV441D_Rocket_Proj` | 255 | 1 | - | - | 4 | 7 | 250, 4-16, 0.08, x1 [native: falloff] | Carl Gustav M2 · FFV441D HE | DF_Carl_Gustav_M2_FFV441D_HE |
| C44 | `Blueprints/Items/RocketLaunchers/BP_CarlGustavM2_FFV751_No78Mk1` -> `BP_FFV751_Tandem_Heat_Proj2` | 255 | 1 | 230 x 1.5 s | 230 | 4 | 7 | 200, 2-8, 0.08, x0 | Carl Gustav M2 · FFV751 Tandem | DF_Carl_Gustav_M2_FFV751_Tandem |
| C45 | `Blueprints/Items/RocketLaunchers/NLAW/BP_NLAW` -> `BP_NLAW_Proj` | 40 | 0 | 350 x 0.6 s | 250 | 12 | 1 | 200, 2-8, 0.08, x1 [native: falloff] | NLAW | DF_NLAW |
| C46 | `Vehicles/Emplaced_SPG9/BP_EmplacedSPG9` -> `BP_SPG9_pg9v_Heat_Proj2` | 435 | 1.2 | 100 x 1.1 s | 330 | 8 | 3 | 100, 2-8, 0.08, x1 [native: falloff] | SPG-9 · HEAT | DF_SPG_9_HEAT |
| C47 | `Vehicles/Emplaced_SPG9/BP_EmplacedSPG9Scope` -> `BP_SPG9_pg9v_Heat_Proj2` | 435 | 1.2 | 100 x 1.1 s | 330 | 8 | 3 | 100, 2-8, 0.08, x1 [native: falloff] | SPG-9 · HEAT · scope · optic (RMB ×4); SPG-9 · HEAT · scope · no optic | DF_SPG_9_HEAT_scope_no_optic; DF_SPG_9_HEAT_scope |
| C48 | `Vehicles/Emplaced_SPG9/BP_EmplacedSPG9_Frag` -> `BP_SPG9_og9v_Frag_Proj2` | 315 | 1.2 | 100 x 1.1 s | 250 | 8 | 3 | 200, 2-16, 0.08, x1 [native: falloff] | SPG-9 · FRAG | DF_SPG_9_FRAG |
| C49 | `Vehicles/Emplaced_SPG9/BP_EmplacedSPG9_FragScope` -> `BP_SPG9_og9v_Frag_Proj2` | 315 | 1.2 | 100 x 1.1 s | 250 | 8 | 3 | 200, 2-16, 0.08, x1 [native: falloff] | SPG-9 · FRAG · scope · optic (RMB ×4); SPG-9 · FRAG · scope · no optic | DF_SPG_9_FRAG_scope_no_optic; DF_SPG_9_FRAG_scope |
| C50 | `Vehicles/Technical/Weapons/BP_SPG9` -> `BP_SPG9_pg9v_Heat_Proj2` | 435 | 1.2 | 100 x 1.1 s | 330 | 8 | 3 | 100, 2-8, 0.08, x1 [native: falloff] | SPG-9 · HEAT · technical · optic (RMB ×4); SPG-9 · HEAT · technical · no optic; SPG-9 · HEAT · INS armoured technical · optic (RMB ×4); SPG-9 · HEAT · INS armoured technical · no optic | DF_SPG_9_HEAT_technical_optic_RMB_4; DF_SPG_9_HEAT_technical_no_optic; DF_SPG_9_HEAT_INS_armoured_technical_optic_RMB_4; DF_SPG_9_HEAT_INS_armoured_technical_no_optic |
| C51 | `Vehicles/Technical/Weapons/BP_SPG9_Frag` -> `BP_SPG9_og9v_Frag_Proj2` | 315 | 1.2 | 100 x 1.1 s | 250 | 8 | 1 | 200, 2-16, 0.08, x1 [native: falloff] | SPG-9 · FRAG · technical · optic (RMB ×4); SPG-9 · FRAG · technical · no optic; SPG-9 · FRAG · INS armoured technical · optic (RMB ×4); SPG-9 · FRAG · INS armoured technical · no optic | DF_SPG_9_FRAG_technical_optic_RMB_4; DF_SPG_9_FRAG_technical_no_optic; DF_SPG_9_FRAG_INS_armoured_technical_optic_RMB_4; DF_SPG_9_FRAG_INS_armoured_technical_no_optic |
| C52 | `Vehicles/BMP-1/Weapons/BP_BMP1_2A28_HEAT` -> `BP_SPG9_pg9v_Heat_Proj2` | 435 | 1.2 | 100 x 1.1 s | 330 | 8 | 3 | 100, 2-8, 0.08, x1 [native: falloff] | 2A28 Grom (BMP-1 / BMD-1) · HEAT; 2A28 Grom (BMP-1) · HEAT · gunner sight ×6 | DF_2A28_Grom_BMP_1_BMD_1_HEAT |
| C53 | `Vehicles/Technical2Seater/Weapons/BP_Technical_BMP1_2A28_HEAT` -> `BP_SPG9_pg9v_Heat_Proj2` | 435 | 1.2 | 100 x 1.1 s | 330 | 8 | 3 | 100, 2-8, 0.08, x1 [native: falloff] | 2A28 Grom (BMP-1 technical) · HEAT · gunner sight ×6; 2A28 Grom (BMP-1 technical) · HEAT | DF_2A28_Grom_BMP_1_technical_HEAT |
| C54 | `Vehicles/BMD-1M/Weapons/BP_BMD1M_2A28_HEAT` -> `BP_SPG9_pg9v_Heat_Proj2` | 435 | 1.2 | 100 x 1.1 s | 330 | 8 | 3 | 100, 2-8, 0.08, x1 [native: falloff] | 2A28 Grom (BMD-1M) · HEAT; 2A28 Grom (BMD-1M) · HEAT · gunner sight ×6 | DF_2A28_Grom_BMD_1M_HEAT |
| C55 | `Vehicles/BMP-1/Weapons/BP_BMP1_2A28_Frag` -> `BP_SPG9_og9v_Frag_Proj2` | 290 | 1.2 | 100 x 1.1 s | 250 | 8 | 3 | 200, 2-16, 0.08, x1 [native: falloff] | 2A28 Grom (BMP-1 / BMD-1) · FRAG; 2A28 Grom (BMP-1) · FRAG · gunner sight ×6 | DF_2A28_Grom_BMP_1_BMD_1_FRAG |
| C56 | `Vehicles/Technical2Seater/Weapons/BP_Technical_BMP1_2A28_Frag` -> `BP_SPG9_og9v_Frag_Proj2` | 290 | 1.2 | 100 x 1.1 s | 250 | 8 | 3 | 200, 2-16, 0.08, x1 [native: falloff] | 2A28 Grom (BMP-1 technical) · FRAG · gunner sight ×6; 2A28 Grom (BMP-1 technical) · FRAG | DF_2A28_Grom_BMP_1_technical_FRAG |
| C57 | `Vehicles/BMD-1M/Weapons/BP_BMD1M_2A28_Frag` -> `BP_SPG9_og9v_Frag_Proj2` | 290 | 1.2 | 100 x 1.1 s | 250 | 8 | 3 | 200, 2-16, 0.08, x1 [native: falloff] | 2A28 Grom (BMD-1M) · FRAG; 2A28 Grom (BMD-1M) · FRAG · gunner sight ×6 | DF_2A28_Grom_BMD_1M_FRAG |
| C58 | `Vehicles/BMP-3M/Weapons/BP_BMP3M_2A70_HEFrag` -> `BP_Projectile_100mm_Frag` | 355 | 2 | - | 850 | 20 | 1.6 | 300, 4-35, 0.2, x5 | 2A70 100mm (BMP-3 / BMD-4 / ZBD04A) · FRAG; 2A70 100mm (BMP-3) · FRAG · gunner sight ×4 | DF_2A70_100mm_BMP_3_BMD_4_ZBD04A_FRAG |
| C59 | `Vehicles/ZBD04A/Weapons/BP_ZBD04A_2A70_HEFrag` -> `BP_Projectile_100mm_Frag` | 355 | 2 | - | 850 | 20 | 1.6 | 300, 4-35, 0.2, x5 | 2A70 100mm (ZBD-04A) · FRAG; 2A70 100mm (ZBD-04A) · FRAG · gunner sight ×4; 2A70 100mm (ZBD-04A) · FRAG · gunner sight ×14 | DF_2A70_100mm_ZBD_04A_FRAG |
| C60 | `Vehicles/BMD-4M/Weapons/BP_BMD4M_2A70_HEFrag` -> `BP_Projectile_100mm_Frag` | 355 | 2 | - | 850 | 20 | 1.6 | 300, 4-35, 0.2, x5 | 2A70 100mm (BMD-4M) · FRAG; 2A70 100mm (BMD-4M) · FRAG · gunner sight ×5; 2A70 100mm (BMP-3 / BMD-4M) · FRAG · gunner sight ×14 | DF_2A70_100mm_BMD_4M_FRAG; DF_2A70_100mm_BMP_3_BMD_4M_FRAG_gunner_sight_14 |
| C61 | `Vehicles/Emplaced_ZiS3_Cannon/Weapons/BP_ZiS3_Weapon_HEAT` -> `BP_Projectile_76mm_HEAT` | 700 | 2 | - | 700 | 20 | 3 | 200, 3.5-16, 0.15, x2 | ZiS-3 · optic (RMB ×4); ZiS-3 · no optic | DF_ZiS_3; DF_ZiS_3_no_optic |
| C62 | `Vehicles/T72B3/Weapons/BP_2A46_AP` -> `BP_Projectile_120mm_AP` | 1300 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · T-72 (2A46) | DF_Tank_AP_2A46_ZPT98_2A20_2A45_KBA3 |
| C63 | `Vehicles/T90A/Weapons/BP_2A46M_AP` -> `BP_Projectile_120mm_AP` | 1300 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · T-90A (2A46M); Tank AP · T-90A (2A46M) · gunner sight ×12 | DF_Tank_AP_T_90A_2A46M |
| C64 | `Vehicles/Sprut-SDM1/Weapons/BP_2A45_AP` -> `BP_Projectile_120mm_AP` | 1300 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · Sprut-SDM1 (2A45) · gunner sight ×4; Tank AP · Sprut-SDM1 (2A45) · gunner sight ×12 | DF_Tank_AP_Sprut_SDM1_2A45_gunner_sight_4 |
| C65 | `Vehicles/T72A/Weapons/BP_2A46_T72A_AP` -> `BP_Projectile_120mm_AP` | 1300 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · T-72 (2A46) · gunner sight ×12 | - |
| C66 | `Vehicles/T62/Weapons/BP_2A20_AP` -> `BP_Projectile_120mm_AP` | 1300 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · T-62 (2A20); Tank AP · T-62 (2A20) · gunner sight ×7 | DF_Tank_AP_T_62_2A20 |
| C67 | `Vehicles/T64_BM2/Weapons/BP_KBA3_AP` -> `BP_Projectile_120mm_AP` | 1300 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · T-64BM2 (KBA3); Tank AP · T-64BM2 (KBA3) · gunner sight ×12 | DF_Tank_AP_T_64BM2_KBA3 |
| C68 | `Vehicles/ZTZ99/Weapons/BP_ZPT-98_AP` -> `BP_Projectile_120mm_AP` | 1300 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · ZTZ-99 (ZPT-98); Tank AP · ZTZ-99 (ZPT-98) · gunner sight ×12 | DF_Tank_AP_ZTZ_99_ZPT_98 |
| C69 | `Vehicles/M1A2/Weapons/BP_M256A1_AP` -> `BP_Projectile_120mm_AP` | 1200 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · M256 / Rh120 | DF_Tank_AP_M256_Rh120 |
| C70 | `Vehicles/AUS_M1A1/Weapons/BP_M256A1_AP_ADF` -> `BP_Projectile_120mm_AP` | 1200 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · M1A1 / M1A2 (M256) · gunner sight ×6; Tank AP · M1A1 / M1A2 (M256) · gunner sight ×12 | - |
| C71 | `Vehicles/Leopard2/Weapons/BP_L55_AP` -> `BP_Projectile_120mm_AP` | 1200 | 2.5 | - | 1500 | 8 | 1.2 | none | Tank AP · Leopard 2A6 (Rh120); Tank AP · Leopard 2A6 (Rh120) · gunner sight ×12 | DF_Tank_AP_Leopard_2A6_Rh120 |
| C72 | `Vehicles/M60T/Weapons/BP_MG253_AP` -> `BP_Projectile_120mm_AP` | 1200 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · M60T (MG253); Tank AP · M60T (MG253) · gunner sight ×3; Tank AP · M60T (MG253) · gunner sight ×8 | DF_Tank_AP_M60T_MG253 |
| C73 | `Vehicles/FV4034/Weapons/BP_L30A1_AP` -> `BP_Projectile_120mm_AP` | 1500 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · L30A1 (Challenger 2) / M68A2; Tank AP · Challenger 2 (L30A1) · gunner sight ×4; Tank AP · Challenger 2 (L30A1) · gunner sight ×10 | DF_Tank_AP_L30A1_Challenger_2_M68A2 |
| C74 | `Vehicles/M1128_MGS/Weapons/BP_M68A2_AP` -> `BP_Projectile_120mm_AP` | 1500 | 2.5 | - | 1500 | 8 | 1.5 | none | Tank AP · M1128 MGS (M68A2); Tank AP · M1128 MGS (M68A2) · gunner sight ×8 | DF_Tank_AP_M1128_MGS_M68A2 |
| C75 | `Vehicles/T72B3/Weapons/BP_2A46_HEAT` -> `BP_Projectile_125mm_HEAT` | 1100 | 2 | - | 850 | 20 | 1.5 | 200, 3.5-16, 0.15, x2 | Tank HEAT/HE · T-72 (2A46) | DF_Tank_HEAT_HE_M256_Rh120_2A46_ZPT98_2A20_M68A2 |
| C76 | `Vehicles/T90A/Weapons/BP_2A46M_HEAT` -> `BP_Projectile_125mm_HEAT` | 1100 | 2 | - | 850 | 20 | 1.5 | 200, 3.5-16, 0.15, x2 | Tank HEAT/HE · T-90A (2A46M); Tank HEAT/HE · T-90A (2A46M) · gunner sight ×12 | DF_Tank_HEAT_HE_T_90A_2A46M |
| C77 | `Vehicles/Sprut-SDM1/Weapons/BP_2A45_HEAT` -> `BP_Projectile_125mm_HEAT` | 1100 | 2 | - | 850 | 20 | 1.5 | 200, 3.5-16, 0.15, x2 | Tank HEAT/HE · Sprut-SDM1 (2A45) · gunner sight ×4; Tank HEAT/HE · Sprut-SDM1 (2A45) · gunner sight ×12 | DF_Tank_HEAT_HE_Sprut_SDM1_2A45_gunner_sight_4 |
| C78 | `Vehicles/T72A/Weapons/BP_2A46_T72A_HEAT` -> `BP_Projectile_125mm_HEAT` | 1100 | 2 | - | 850 | 20 | 1.5 | 200, 3.5-16, 0.15, x2 | Tank HEAT/HE · T-72 (2A46) · gunner sight ×12 | - |
| C79 | `Vehicles/M1A2/Weapons/BP_M256A1_HEAT` -> `BP_Projectile_120mm_HEAT` | 1100 | 2 | - | 800 | 20 | 1.5 | 200, 7-20, 0.15, x2 | Tank HEAT/HE · M1A1 / M1A2 (M256); Tank HEAT/HE · M1A1 / M1A2 (M256) · gunner sight ×6; Tank HEAT/HE · M1A1 / M1A2 (M256) · gunner sight ×12 | DF_Tank_HEAT_HE_M1A1_M1A2_M256 |
| C80 | `Vehicles/Leopard2/Weapons/BP_L55_HEAT` -> `BP_Projectile_120mm_HEAT` | 1100 | 2 | - | 800 | 20 | 1.2 | 200, 7-20, 0.15, x2 | Tank HEAT/HE · Leopard 2A6 (Rh120); Tank HEAT/HE · Leopard 2A6 (Rh120) · gunner sight ×12 | DF_Tank_HEAT_HE_Leopard_2A6_Rh120 |
| C81 | `Vehicles/M1128_MGS/Weapons/BP_M68A2_HEAT` -> `BP_Projectile_120mm_HEAT` | 1100 | 2 | - | 800 | 20 | 1.5 | 200, 7-20, 0.15, x2 | Tank HEAT/HE · M1128 MGS (M68A2); Tank HEAT/HE · M1128 MGS (M68A2) · gunner sight ×8 | DF_Tank_HEAT_HE_M1128_MGS_M68A2 |
| C82 | `Vehicles/M60T/Weapons/BP_MG253_Frag` -> `BP_Projectile_125mm_Frag` | 1100 | 2 | - | 850 | 20 | 1.5 | 300, 4-35, 0.2, x5 | Tank HEAT/HE · M60T (MG253); Tank HEAT/HE · M60T (MG253) · gunner sight ×3; Tank HEAT/HE · M60T (MG253) · gunner sight ×8 | DF_Tank_HEAT_HE_M60T_MG253 |
| C83 | `Vehicles/ZTZ99/Weapons/BP_ZPT-98_HEAT` -> `BP_Projectile_125mm_HEAT` | 1100 | 2 | - | 850 | 20 | 1.5 | 200, 3.5-16, 0.15, x2 | Tank HEAT/HE · ZTZ-99 (ZPT-98); Tank HEAT/HE · ZTZ-99 (ZPT-98) · gunner sight ×12 | DF_Tank_HEAT_HE_ZTZ_99_ZPT_98 |
| C84 | `Vehicles/T62/Weapons/BP_2A20_HEAT` -> `BP_Projectile_115mm_HEAT` | 1100 | 2 | - | 850 | 20 | 1.5 | 200, 3.5-16, 0.15, x2 | Tank HEAT/HE · T-62 (2A20); Tank HEAT/HE · T-62 (2A20) · gunner sight ×7 | DF_Tank_HEAT_HE_T_62_2A20 |
| C85 | `Vehicles/T64_BM2/Weapons/BP_KBA3_HEAT` -> `BP_Projectile_125mm_HEAT` | 1100 | 2 | - | 850 | 20 | 1.5 | 200, 3.5-16, 0.15, x2 | Tank HEAT/HE · T-64BM2 (KBA3); Tank HEAT/HE · T-64BM2 (KBA3) · gunner sight ×12 | DF_Tank_HEAT_HE_T_64BM2_KBA3 |
| C86 | `Vehicles/FV4034/Weapons/BP_L30A1_HESH` -> `BP_Projectile_120mm_HEAT` | 670 | 2 | - | 800 | 20 | 1.5 | 200, 7-20, 0.15, x2 | Tank HESH · L30A1 (Challenger 2); Tank HESH · Challenger 2 (L30A1) · gunner sight ×4; Tank HESH · Challenger 2 (L30A1) · gunner sight ×10 | DF_Tank_HESH_L30A1_Challenger_2 |
| C87 | `Vehicles/ZTD05/Weapons/BP_ZTD05_ZPL-98A_AP` -> `BP_Projectile_105mm_AP` | 1110 | 2.5 | - | 1500 | 8 | 1.5 | none | ZPL-98A 105mm (ZTD-05) · AP; ZPL-98A 105mm (ZTD-05) · AP · gunner sight ×7 | DF_ZPL_98A_105mm_ZTD_05_AP |
| C88 | `Vehicles/ZTD05/Weapons/BP_ZTD05_ZPL-98A_HEAT` -> `BP_Projectile_115mm_HEAT` | 730 | 2 | - | 850 | 20 | 1.5 | 200, 3.5-16, 0.15, x2 | ZPL-98A 105mm (ZTD-05) · HEAT / HE; ZPL-98A 105mm (ZTD-05) · HEAT / HE · gunner sight ×7 | DF_ZPL_98A_105mm_ZTD_05_HEAT_HE |
| C89 | `Vehicles/BP_GenericMortarWeapon` -> `BP_Mortarround4` | 110 | 1 | - | - | - | 50 | 350, 0-40, 1, x7 | Mortar (M252 / 2B14 / L16 / Type 63) | Mortar |
| C90 | `Vehicles/Technical2Seater/Weapons/BP_Technical_M1937mortar` -> `BP_Mortarround4` | 110 | 1 | - | - | - | 50 | 350, 0-40, 1, x7 | Technical Mortar | Tech.Mortar |
| C91 | `Vehicles/M1064A3/Weapons/BP_M1064A3_M121mortar` -> `BP_Mortarround_120mm` | 142 | 1 | - | - | - | 40 | 400, 0-40, 1, x7 | M1064 M121 (120mm) | M1064M121 |
| C92 | `Vehicles/Emplaced_HellCannon/BP_Emplaced_HellCannon` -> `BP_Projectile_Hell_Cannon` | 95 | 1 | - | - | - | 100 | 125, 1-50, 2, x1 | Hell Cannon | HellCannon |
| C93 | `Vehicles/Emplaced_UB32_RocketArtillery/BP_EmplacedUB32` -> `BP_S5_Proj2` | 300 | 2 | -50 x 2 s | 300 | 20 | 300 | 115, 5-18, 0.2, x1 [native: BaseDamage, height, falloff, inner] | UB-32 (S-5 rockets) | UB-32 |
| C94 | `Vehicles/Technical/Weapons/BP_UB32` -> `BP_S5_Proj2` | 300 | 2 | -50 x 2 s | 300 | 20 | 300 | 115, 5-18, 0.2, x1 [native: BaseDamage, height, falloff, inner] | Technical UB-32 | Tech.UB-32 |
| C95 | `Vehicles/Ural375_BM21Grad/Weapons/BP_BM21Grad_Weapon_MEI` -> `BP_BM21_Rocket_Proj2` | 200 | 2 | - | - | 20 | 200 | 140, 1-35, 2, x1 | BM-21 Grad | BM-21Grad |
| C96 | `Vehicles/M1064A3/Weapons/BP_M1064A3_M121mortar_Airburst` -> `BP_Mortarround_120mm_Airburst` | 142 | 1 | - | - | - | 50 | 100, 10-60, 10, x1.3 | - | M1064M121 |
| C97 | `Blueprints/Items/GrenadeLaunchers/FNFAL_GL/BP_FNFAL_GL_HEAT` -> `BP_Projectile_RifleGrenade_FNFAL_HEAT` | 76 | 1 | - | - | 20 | 30 | 130, 2-8, 0.08, x1 [native: falloff] | - | DF_Rifle_grenade |
| C98 | `Blueprints/Items/RocketLaunchers/SMAW/BP_SMAW_Tandem_2mags` -> `BP_SMAW_Tandem_Heat_Proj2` | 220 | 1 | 150 x 0.8 s | 220 | 4 | 7 | 80, 2-8, 0.08, x0 | - | DF_MK153_SMAW |
| C99 | `Blueprints/Items/RocketLaunchers/RPG7/RPG7/BP_RPG7_Frag` -> `BP_RPG7_Frag_Proj2` | 117 | 1 | 150 x 0.8 s | 250 | 4 | 20 | 250, 2-16, 0.08, x1 [native: falloff] | - | DF_RPG_7_PG_7V_HEAT_OG_7V |
| C100 | `Blueprints/Items/RocketLaunchers/RPG7/RPG7V1/BP_RPG7V1_Frag` -> `BP_RPG7_Frag_Proj2` | 117 | 1 | 150 x 0.8 s | 250 | 4 | 15 | 250, 2-16, 0.08, x1 [native: falloff] | - | DF_RPG_7V1_HEAT |
| C101 | `Vehicles/Emplaced_ZiS3_Cannon/Weapons/BP_ZiS3_Weapon_Frag` -> `BP_Projectile_76mm_Frag` | 700 | 2 | - | 700 | 20 | 3 | 200, 2-16, 0.08, x1 | - | DF_ZiS_3; DF_ZiS_3_no_optic |
| C102 | `Vehicles/T72B3/Weapons/BP_2A46_Frag` -> `BP_Projectile_125mm_Frag` | 1100 | 2 | - | 850 | 20 | 1.5 | 300, 4-35, 0.2, x5 | - | DF_Tank_HEAT_HE_M256_Rh120_2A46_ZPT98_2A20_M68A2 |
| C103 | `Vehicles/LAV25/Weapons/LAV25_M252_AP` -> `BP_Projectile_30mm_AP` | 1385 | 2 | - | 1385 | 5 | 2 | none | - | DF_M242_Bushmaster_25mm_AP |
| C104 | `Vehicles/LAV25/Weapons/LAV25_M252_HE` -> `BP_Projectile_30mm_HE` | 1000 | 2 | - | 1000 | 5 | 2 | 125, 1-7.5, 0.08, x2 | - | DF_M242_Bushmaster_25mm_HE |
| C105 | `Vehicles/BMP-2/Weapons/BP_BMP2_2A42_AP` -> `BP_Projectile_30mm_AP` | 1004 | 2 | - | 1385 | 5 | 3 | none | - | DF_2A42_2A72_30mm_AP |
| C106 | `Vehicles/BMP-2/Weapons/BP_BMP2_2A42_HE` -> `BP_Projectile_30mm_HE` | 900 | 2 | - | 1000 | 5 | 3 | 125, 1-7.5, 0.08, x2 | - | DF_2A42_30mm_BMP_2_HE |
| C107 | `Vehicles/FV510/Weapons/BP_Warrior_Rarden_AP` -> `BP_Projectile_30mm_AP` | 1300 | 2 | - | 1385 | 5 | 1.5 | none | - | DF_L21A1_RARDEN_30mm_AP |
| C108 | `Vehicles/FV510/Weapons/BP_Warrior_Rarden_HE` -> `BP_Projectile_30mm_HE_Red_Rarden` | 1100 | 2 | - | 1000 | 5 | 1.5 | 125, 1-7.5, 0.08, x2 | - | DF_L21A1_RARDEN_30mm_HE |
| C109 | `Vehicles/FV510_40mm/Weapons/BP_Warrior_CTAS_AP` -> `BP_Projectile_30mm_AP` | 1500 | 2 | - | 1385 | 5 | 1.5 | none | - | DF_CTAS40_40mm_AP |
| C110 | `Vehicles/FV510_40mm/Weapons/BP_Warrior_CTAS_HE` -> `BP_Projectile_40mm_GPR` | 1200 | 2 | - | 1000 | 5 | 1.5 | 175, 1-12.5, 0.08, x2 | - | DF_CTAS40_40mm_GP |
| C111 | `Vehicles/ZBL08/Weapons/BP_ZBL08_ZPT-99_APFSDS` -> `BP_Projectile_30mm_AP` | 1360 | 2 | - | 1385 | 5 | 2.5 | none | - | DF_ZPT99_30mm_ZBL_08_APFSDS |
| C112 | `Vehicles/ZBD04A/Weapons/BP_ZBD04A_ZPT99_AP` -> `BP_Projectile_30mm_AP` | 970 | 2 | - | 1385 | 5 | 1.35 | none | - | DF_ZPT99_30mm_ZBD_04A_AP_HE |
| C113 | `Vehicles/ZBD04A/Weapons/BP_ZBD04A_ZPT99_HEFrag` -> `BP_Projectile_30mm_HE` | 970 | 2 | - | 1000 | 5 | 1.69 | 125, 1-7.5, 0.08, x2 | - | DF_ZPT99_30mm_ZBD_04A_AP_HE |
| C114 | `Vehicles/BRDM-2/Weapons/BP_BRDM2_RUS_KPVT` -> `BP_Projectile_14_5mm` | 1004 | 2 | - | 900 | 5 | 2.3 | none | - | DF_KPVT_14_5mm |
| C115 | `Vehicles/Emplaced50cal/BP_EmplacedM2_Weapon` -> `BP_Projectile_50cal` | 890 | 1.5 | - | 800 | 8 | 65 (curve FC_MOACurve_GenericHMG.0) | none | - | DF_M2A1_50 |
| C116 | `Vehicles/Emplaced_Kord/BP_EmplacedKord` -> `BP_Projectile_50cal` | 860 | 1.5 | - | 800 | 8 | 150 (curve FC_MOACurve_Kord.0) | none | - | DF_NSV |
| C117 | `Vehicles/Emplaced_Dshk/BP_EmplacedDshk` -> `BP_Projectile_50cal` | 850 | 1.5 | - | 800 | 8 | 65 (curve FC_MOACurve_GenericHMG.0) | none | - | DF_DShK_M |
| C118 | `Vehicles/ZTD05/Weapons/BP_ZTD05_ZPL-98A_Frag` -> `BP_Projectile_125mm_Frag` | 730 | 2 | - | 850 | 20 | 1.5 | 300, 4-35, 0.2, x5 | - | DF_ZPL_98A_105mm_ZTD_05_HEAT_HE |
| C119 | `Vehicles/BMD-4M/Weapons/BP_BMD4M_2A72_HE` -> `BP_Projectile_30mm_HE` | 1004 | 2 | - | 1000 | 5 | 4 | 125, 1-7.5, 0.08, x2 | - | DF_2A72_30mm_BMD_4M_HE |
| C120 | `Vehicles/BMP-3M/Weapons/BP_BMP3M_2A72_AP` -> `BP_Projectile_30mm_AP` | 970 | 2 | - | 1385 | 5 | 1.35 | none | - | DF_2A72_30mm_BMP_3M_AP_HE |
| C121 | `Vehicles/BMP-3M/Weapons/BP_BMP3M_2A72_HE` -> `BP_Projectile_30mm_HE` | 970 | 2 | - | 1000 | 5 | 1.69 | 125, 1-7.5, 0.08, x2 | - | DF_2A72_30mm_BMP_3M_AP_HE |
| C122 | `Vehicles/ZBL08/Weapons/BP_ZBL08_ZPT-99_AP` -> `BP_Projectile_30mm_AP` | 950 | 2 | - | 1385 | 5 | 3.5 | none | - | DF_ZPT99_30mm_ZBL_08_ZBD_05_AP_HE |
| C123 | `Vehicles/Emplaced50cal/BP_EmplacedM2_Weapon_ACOG` -> `BP_Projectile_50cal_ACOG` | 890 | 3 | - | 800 | 8 | 65 (curve FC_MOACurve_GenericHMG.0) | none | - | DF_M2A1_50_ACOG_emplacement |
| C124 | `Vehicles/Emplaced_Kord/BP_EmplacedKord_SPP` -> `BP_Projectile_50cal_ACOG` | 860 | 3 | - | 800 | 8 | 150 (curve FC_MOACurve_Kord.0) | none | - | DF_Kord_SPP_emplacement |
| C125 | `Vehicles/ZTZ99/Weapons/BP_ZPT-98_HE` -> `BP_Projectile_125mm_Frag` | 1100 | 2 | - | 850 | 20 | 1.5 | 300, 4-35, 0.2, x5 | - | DF_Tank_HEAT_HE_ZTZ_99_ZPT_98 |
| C126 | `Vehicles/T62/Weapons/BP_2A20_Frag` -> `BP_Projectile_125mm_Frag` | 1100 | 2 | - | 850 | 20 | 1.5 | 300, 4-35, 0.2, x5 | - | DF_Tank_HEAT_HE_T_62_2A20 |
| C127 | `Vehicles/T64_BM2/Weapons/BP_KBA3_Frag` -> `BP_Projectile_125mm_Frag` | 1100 | 2 | - | 850 | 20 | 1.5 | 300, 4-35, 0.2, x5 | - | DF_Tank_HEAT_HE_T_64BM2_KBA3 |
| C128 | `Vehicles/T90A/Weapons/BP_2A46M_Frag` -> `BP_Projectile_125mm_Frag` | 1100 | 2 | - | 850 | 20 | 1.5 | 300, 4-35, 0.2, x5 | - | DF_Tank_HEAT_HE_T_90A_2A46M |
| C129 | `Vehicles/Sprut-SDM1/Weapons/BP_2A45_Frag` -> `BP_Projectile_125mm_Frag` | 1100 | 2 | - | 850 | 20 | 1.5 | 300, 4-35, 0.2, x5 | - | DF_Tank_HEAT_HE_Sprut_SDM1_2A45_gunner_sight_4 |
<!-- /generated:classes -->

## 5. Inputs the game files do not settle (or that no committed tool reads)

Everything that is not VERIFIED, grouped by input and reason; the weapons are listed by app and name (SB names are those
of `weapons.json`, SC names those of `weapons.js`; a long list is cut, the full one is in the TSV).

<!-- generated:origins -->
| Input | Label | Source | n | Weapons |
|---|---|---|---|---|
| launch point | UNVERIFIED | 1 m chosen with the fit of the hold model; the files say 0.347 m (SB 1.6.0 release notes #13, not reproducible by a committed tool) | 1 | SB AGS-17 · emplacement · optic (RMB ×2.5) |
| launch point | UNVERIFIED | one-off read of the weapon's skeletons (Squad build 26005357), recorded in the comment of SC weapons.js; tools/game_weapons.py does not read tripods and deployables | 6 | SB Hell Cannon; SB Mortar (M252 / 2B14 / L16 / Type 63); SB UB-32 (S-5 rockets); SC HellCannon; SC Mortar; SC UB-32 |
| launch point | UNVERIFIED | same as the optic entry: 1 m, the files say 0.347 m (#13) | 2 | SB AGS-17 · emplacement · no optic; SB AGS-17 · iron sights emplacement |
| launch point | UNVERIFIED | via SB entry: | 2 | SC DF_AGS_17_emplacement_no_optic; SC DF_AGS_17_iron_sights_emplacement |
| launch point | ASSUMED | SHOULDER_HEIGHT of squadCoverageRays.js | 47 | SC DF_2A42_2A72_30mm_AP; SC DF_2A42_30mm_BMP_2_HE; SC DF_2A72_30mm_BMD_4M_HE; SC DF_2A72_30mm_BMP_3M_AP_HE; SC DF_AK_40GL_MPT_76; SC DF_AT_4; SC DF_C90_CR; SC DF_CTAS40_40mm_AP; SC DF_CTAS40_40mm_GP; SC DF_Carl_Gustav_M2_FFV441D_HE; SC DF_Carl_Gustav_M2_FFV551_HEAT; SC DF_Carl_Gustav_M2_FFV751_Tandem; SC DF_DShK_M; SC DF_DZJ_08; ... (+33) |
| launch point | ASSUMED | handheld or unmodelled mount: no launch point in the files read by game_weapons.py | 30 | SB AK-40GL (MPT-76); SB AT-4; SB C90-CR; SB Carl Gustav M2 · FFV441D HE; SB Carl Gustav M2 · FFV551 HEAT; SB Carl Gustav M2 · FFV751 Tandem; SB DZJ-08; SB M203 / M320 / GP-25 / HK79 / SL40; SB M3 MAAWS · HEAT / Smoke; SB M3 MAAWS · Tandem; SB M72A7 LAW / RPG-26; SB MGL / M32; SB MK153 SMAW; SB MK19; ... (+16) |
| launch point | ASSUMED | round figure kept from the upstream table / the mod's table | 13 | SC AGS-17; SC BTR4-AGS; SC HIMARS; SC M109; SC M777; SC MO120RTF1; SC MTLB_FAB500; SC Mk19; SC PZL07; SC T62.DUMP.TRUCK; SC TOS-1A; SC Ural-HellCannon; SC type_63 |
| spread (MOA) | INFERRED | WeaponConfig.MOACurve /Game/Vehicles/FC_MOACurve_GenericGMG.0 | 18 | SC AGS-17; SC DF_AGS_17_emplacement_no_optic; SC DF_AGS_17_iron_sights_emplacement; SC DF_MK19_M113_open_turret; SC DF_MK19_M113_open_turret_no_sights; SC DF_MK19_M1151_RHIB_open_turret; SC DF_MK19_M1151_open_turret_no_sights; SC DF_MK19_MATV_open_turret; SC DF_MK19_MATV_open_turret_no_sights; SC DF_MK19_RHIB_open_turret; SC DF_MK19_emplacement_C16_L134A1; SC DF_MK19_emplacement_C16_L134A1_no_sights; SC DF_QLZ87; SC DF_QLZ87_CSK131_WZ551_no_optic; ... (+4) |
| spread (MOA) | UNVERIFIED | WeaponConfig.MOACurve /Game/Vehicles/Emplaced_Kord/Curves/FC_MOACurve_Kord.0 (asset not in the dump here; values from gamecheck.py MOA_CURVES) | 2 | SC DF_Kord_SPP_emplacement; SC DF_NSV |
| spread (MOA) | UNVERIFIED | WeaponConfig.MOACurve /Game/Vehicles/FC_MOACurve_GenericHMG.0 (asset not in the dump here; values from gamecheck.py MOA_CURVES) | 3 | SC DF_DShK_M; SC DF_M2A1_50; SC DF_M2A1_50_ACOG_emplacement |
| spread (MOA) | UNVERIFIED | weapon Blueprint not in resolved.json; value from the generator table (read from another dump, no longer on disk) | 8 | SC DF_AGS_17_BTR_D; SC DF_AGS_17_M1151; SC DF_AGS_17_Safir; SC DF_AGS_17_Technical; SC DF_AGS_17_Tigr; SC DF_MK19_PARS_III_RWS; SC DF_MK19_TAPV_C16_RWS; SC DF_QLZ87_ZBL08_no_optic |
| spread (MOA) | ASSUMED | Workshop mod | 10 | SC HIMARS; SC M109; SC M777; SC MO120RTF1; SC MTLB_FAB500; SC PZL07; SC T62.DUMP.TRUCK; SC TOS-1A; SC Ural-HellCannon; SC type_63 |
| lifespan | ASSUMED | Workshop mod: not in the dedicated-server package; table of the upstream SquadCalc | 10 | SC HIMARS; SC M109; SC M777; SC MO120RTF1; SC MTLB_FAB500; SC PZL07; SC T62.DUMP.TRUCK; SC TOS-1A; SC Ural-HellCannon; SC type_63 |
| lifespan | ASSUMED | the game sets none; SC default 100 s | 4 | SC HellCannon; SC M1064M121; SC Mortar; SC Tech.Mortar |
| explosion | INFERRED | projectile Blueprint chain sets no Explosive* field | 26 | SC DF_2A42_2A72_30mm_AP; SC DF_2A72_30mm_BMP_3M_AP_HE; SC DF_CTAS40_40mm_AP; SC DF_DShK_M; SC DF_KPVT_14_5mm; SC DF_Kord_SPP_emplacement; SC DF_L21A1_RARDEN_30mm_AP; SC DF_M242_Bushmaster_25mm_AP; SC DF_M2A1_50; SC DF_M2A1_50_ACOG_emplacement; SC DF_NSV; SC DF_Tank_AP_2A46_ZPT98_2A20_2A45_KBA3; SC DF_Tank_AP_L30A1_Challenger_2_M68A2; SC DF_Tank_AP_Leopard_2A6_Rh120; ... (+12) |
| explosion | INFERRED | the projectile Blueprint chain sets no Explosive* field: it hits with its impact damage | 27 | SB Tank AP · Challenger 2 (L30A1) · gunner sight ×10; SB Tank AP · Challenger 2 (L30A1) · gunner sight ×4; SB Tank AP · L30A1 (Challenger 2) / M68A2; SB Tank AP · Leopard 2A6 (Rh120); SB Tank AP · Leopard 2A6 (Rh120) · gunner sight ×12; SB Tank AP · M1128 MGS (M68A2); SB Tank AP · M1128 MGS (M68A2) · gunner sight ×8; SB Tank AP · M1A1 / M1A2 (M256) · gunner sight ×12; SB Tank AP · M1A1 / M1A2 (M256) · gunner sight ×6; SB Tank AP · M256 / Rh120; SB Tank AP · M60T (MG253); SB Tank AP · M60T (MG253) · gunner sight ×3; SB Tank AP · M60T (MG253) · gunner sight ×8; SB Tank AP · Sprut-SDM1 (2A45) · gunner sight ×12; ... (+13) |
| explosion | UNVERIFIED | weapon Blueprint not in resolved.json (generator table) | 8 | SC DF_AGS_17_BTR_D; SC DF_AGS_17_M1151; SC DF_AGS_17_Safir; SC DF_AGS_17_Technical; SC DF_AGS_17_Tigr; SC DF_MK19_PARS_III_RWS; SC DF_MK19_TAPV_C16_RWS; SC DF_QLZ87_ZBL08_no_optic |
| explosion | ASSUMED | Workshop mod | 10 | SC HIMARS; SC M109; SC M777; SC MO120RTF1; SC MTLB_FAB500; SC PZL07; SC T62.DUMP.TRUCK; SC TOS-1A; SC Ural-HellCannon; SC type_63 |
| explosion | ASSUMED | projectile primary explosion | 64 | SC AGS-17; SC BTR4-AGS; SC DF_2A28_Grom_BMD_1M_FRAG; SC DF_2A28_Grom_BMD_1M_HEAT; SC DF_2A28_Grom_BMP_1_BMD_1_FRAG; SC DF_2A28_Grom_BMP_1_BMD_1_HEAT; SC DF_2A28_Grom_BMP_1_technical_FRAG; SC DF_2A28_Grom_BMP_1_technical_HEAT; SC DF_AGS_17_emplacement_no_optic; SC DF_AGS_17_iron_sights_emplacement; SC DF_AGS_30_BMP_1TS; SC DF_AGS_30_BMP_2M; SC DF_AGS_30_BTR_4_AGS; SC DF_AK_40GL_MPT_76; ... (+50) |
| bore | ASSUMED | handheld: the shot leaves along the barrel socket (native ASQWeapon::GetAimDirection and GetProjectileSpawnTransform read WeaponConfig.BarrelSocketName on the weapon mesh | 26 | SB AK-40GL (MPT-76); SB AT-4; SB C90-CR; SB Carl Gustav M2 · FFV441D HE; SB Carl Gustav M2 · FFV551 HEAT; SB Carl Gustav M2 · FFV751 Tandem; SB DZJ-08; SB M203 / M320 / GP-25 / HK79 / SL40; SB M3 MAAWS · HEAT / Smoke; SB M3 MAAWS · Tandem; SB M72A7 LAW / RPG-26; SB MGL / M32; SB MK153 SMAW; SB NLAW; ... (+12) |
| zoom | ASSUMED | handheld: the shot leaves along the barrel socket (native ASQWeapon::GetAimDirection and GetProjectileSpawnTransform read WeaponConfig.BarrelSocketName on the weapon mesh | 26 | SB AK-40GL (MPT-76); SB AT-4; SB C90-CR; SB Carl Gustav M2 · FFV441D HE; SB Carl Gustav M2 · FFV551 HEAT; SB Carl Gustav M2 · FFV751 Tandem; SB DZJ-08; SB M203 / M320 / GP-25 / HK79 / SL40; SB M3 MAAWS · HEAT / Smoke; SB M3 MAAWS · Tandem; SB M72A7 LAW / RPG-26; SB MGL / M32; SB MK153 SMAW; SB NLAW; ... (+12) |
| elevation limits | ASSUMED | -25..35 degrees inherited from the upstream SquadCalc table | 1 | SB UB-32 (S-5 rockets) |
| elevation limits | ASSUMED | 10..90 degrees inherited from the upstream SquadCalc table; tripod limits not read by game_weapons.py | 1 | SB Hell Cannon |
| elevation limits | ASSUMED | 45..88.875 degrees (1580 mil) inherited from the upstream SquadCalc table; game_weapons.json records the mount's PitchInterval 0..43.8, no committed tool derives these li | 1 | SB Mortar (M252 / 2B14 / L16 / Type 63) |
| elevation limits | ASSUMED | Workshop mod | 10 | SC HIMARS; SC M109; SC M777; SC MO120RTF1; SC MTLB_FAB500; SC PZL07; SC T62.DUMP.TRUCK; SC TOS-1A; SC Ural-HellCannon; SC type_63 |
| elevation limits | ASSUMED | no mount: handheld | 26 | SB AK-40GL (MPT-76); SB AT-4; SB C90-CR; SB Carl Gustav M2 · FFV441D HE; SB Carl Gustav M2 · FFV551 HEAT; SB Carl Gustav M2 · FFV751 Tandem; SB DZJ-08; SB M203 / M320 / GP-25 / HK79 / SL40; SB M3 MAAWS · HEAT / Smoke; SB M3 MAAWS · Tandem; SB M72A7 LAW / RPG-26; SB MGL / M32; SB MK153 SMAW; SB NLAW; ... (+12) |
| elevation limits | ASSUMED | unbounded: no mount data for this SquadCalc-only weapon | 19 | SC DF_2A42_2A72_30mm_AP; SC DF_2A42_30mm_BMP_2_HE; SC DF_2A72_30mm_BMD_4M_HE; SC DF_2A72_30mm_BMP_3M_AP_HE; SC DF_CTAS40_40mm_AP; SC DF_CTAS40_40mm_GP; SC DF_DShK_M; SC DF_KPVT_14_5mm; SC DF_Kord_SPP_emplacement; SC DF_L21A1_RARDEN_30mm_AP; SC DF_L21A1_RARDEN_30mm_HE; SC DF_M242_Bushmaster_25mm_AP; SC DF_M242_Bushmaster_25mm_HE; SC DF_M2A1_50; ... (+5) |
| elevation limits | ASSUMED | upstream table (Mk19, BTR4-AGS) | 2 | SC BTR4-AGS; SC Mk19 |
| elevation limits | ASSUMED | via SB entry: -25..35 degrees inherited from the upstream SquadCalc table | 1 | SC UB-32 |
| elevation limits | ASSUMED | via SB entry: 10..90 degrees inherited from the upstream SquadCalc table; tripod limits not read by game_weapons.py | 1 | SC HellCannon |
| elevation limits | ASSUMED | via SB entry: 45..88.875 degrees (1580 mil) inherited from the upstream SquadCalc table; game_weapons.json records the mount's PitchIn | 1 | SC Mortar |
| elevation limits | ASSUMED | via SB entry: no mount: handheld | 26 | SC DF_AK_40GL_MPT_76; SC DF_AT_4; SC DF_C90_CR; SC DF_Carl_Gustav_M2_FFV441D_HE; SC DF_Carl_Gustav_M2_FFV551_HEAT; SC DF_Carl_Gustav_M2_FFV751_Tandem; SC DF_DZJ_08; SC DF_M203_M320_GP_25_HK79_SL40; SC DF_M3_MAAWS_HEAT_Smoke; SC DF_M3_MAAWS_Tandem; SC DF_M72A7_LAW_RPG_26; SC DF_MGL_M32; SC DF_MK153_SMAW; SC DF_NLAW; ... (+12) |
| min distance | INFERRED | range of the top of the hold (85.87 degrees) from the muzzle, computed by gen_squadcalc_weapons.py lob_min_distance from the fitted hold model | 1 | SC AGS-17 |
| min distance | ASSUMED | 340 m inherited from the upstream SquadCalc table | 2 | SB M1064 M121 (120mm); SC M1064M121 |
| min distance | ASSUMED | 51 m inherited from the upstream table; this model's range at the barrel's top (83.8 + 5 = 88.8 degrees) is 51.8 m | 2 | SB Technical Mortar; SC Tech.Mortar |
| min distance | ASSUMED | 51 m inherited from the upstream table; this model's range at the top elevation 88.875 degrees is 48.5 m | 2 | SB Mortar (M252 / 2B14 / L16 / Type 63); SC Mortar |
| min distance | ASSUMED | inherited from the upstream SquadCalc table (sh4rkman/SquadCalc); not decided by the server files | 11 | SC DF_AGS_17_BTR_D; SC DF_AGS_17_M1151; SC DF_AGS_17_Safir; SC DF_AGS_17_Technical; SC DF_AGS_17_Tigr; SC DF_AGS_17_emplacement_no_optic; SC DF_AGS_17_iron_sights_emplacement; SC M777; SC MTLB_FAB500; SC Mk19; SC type_63 |
| angle offset | INFERRED | 5 degrees is the upstream value; the HUD table of the game (readout in degrees against range) puts the barrel 4.8 +- 0.3 degrees above the readout (SB release notes 1.6.0 | 2 | SB Technical Mortar; SC Tech.Mortar |
| angle offset | ASSUMED | Workshop mod | 1 | SC M109 |
| angle offset | ASSUMED | inherited from the upstream SquadCalc table (sh4rkman/SquadCalc); not decided by the server files | 2 | SC BTR4-AGS; SC Mk19 |
| hold model | UNVERIFIED | 9 deg/s read by hand from the game's input settings (keyboard pitch x300/s x turret input x0.03, SB weapons.json note); no committed tool reads it; Calibrate refits it in | 1 | SB Mortar (M252 / 2B14 / L16 / Type 63) |
| hold model | UNVERIFIED | fitted to 67 in-game hold-time measurements of the owner (not in the repositories); the game files give 9.00 deg/s (keyboard pitch x15 x turret input x0.6) and fit them a | 16 | SB AGS-17 · BTR-D; SB AGS-17 · M1151; SB AGS-17 · Safir; SB AGS-17 · Technical; SB AGS-17 · Tigr; SB AGS-17 · emplacement · no optic; SB AGS-17 · emplacement · optic (RMB ×2.5); SB AGS-17 · iron sights emplacement; SC AGS-17; SC DF_AGS_17_BTR_D; SC DF_AGS_17_M1151; SC DF_AGS_17_Safir; SC DF_AGS_17_Technical; SC DF_AGS_17_Tigr; ... (+2) |
<!-- /generated:origins -->

## 6. Inherited from the upstream table, fitted, measured

`git blame` of SC `src/data/weapons.js` (author of the line that stands now; "upstream" is `sh4rkman`, the author of
`sh4rkman/SquadCalc`, "fork" is the Deadline fork):

<!-- generated:blame -->
| Weapon | Upstream-authored lines (sh4rkman) | Fork-authored lines |
|---|---|---|
| Mortar | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, minDistance, minElevation, moa, velocity | muzzle |
| UB-32 | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, minDistance, minElevation, moa, projectileLifespan, velocity | maxSpeed, muzzle |
| HellCannon | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, minDistance, minElevation, moa, velocity | muzzle |
| Tech.Mortar | angleOffset, damageFallOff, explosionDamage, explosionRadius, gravityScale, minDistance, moa, velocity | explosionDistanceFromImpact, minElevation, muzzle |
| Tech.UB-32 | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, minDistance, moa, projectileLifespan, velocity | maxSpeed, minElevation, muzzle |
| BM-21Grad | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, minDistance, moa, velocity | minElevation, muzzle, projectileLifespan |
| M1064M121 | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, minDistance, moa, velocity | minElevation, muzzle |
| Mk19 | angleOffset, damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, heightOffset, minDistance, minElevation, moa, projectileLifespan, velocity | - |
| BTR4-AGS | angleOffset, damageFallOff, explosionDamage, explosionRadius, gravityScale, heightOffset, minDistance, minElevation, moa, projectileLifespan, velocity | explosionDistanceFromImpact |
| AGS-17 | - | elevationRate, gravityScale, heightOffset, holdElevation, minDistance, minElevation, projectileLifespan, velocity |
<!-- /generated:blame -->

What that means per weapon:

* **Mortar, UB-32, HellCannon, Tech.Mortar, Tech.UB-32, BM-21Grad, M1064M121** (calculator weapons `Mortar (M252 / 2B14 / L16 / Type 63)`,
  `UB-32 (S-5 rockets)`, `Hell Cannon`, `Technical Mortar`, `Technical UB-32`, `BM-21 Grad`, `M1064 M121 (120mm)`): velocity,
  gravity, spread, explosion and lifespan were typed by upstream or taken from the SDK and are confirmed equal by
  `gamecheck.py` (VERIFIED, origin inherited). The launch point (`muzzle`), the elevation limits of the vehicle mounts, the
  UB-32 / Tech.UB-32 cap and rotation were set by the fork from the game files. The minimum distances (51, 51 and 340 m), the
  elevation limits of the mortar (45..88.875 degrees), Hell Cannon and UB-32 are upstream figures that no committed tool decides (ASSUMED);
  the technical mortar's 5 degree scale offset is upstream too, supported by the game's HUD table (INFERRED).
* **Mk19, BTR4-AGS**: velocity, gravity, spread, explosion, lifespan agree with the game (`MK19`, `AGS-30 / BTR-4 AGS`
  in `gamecheck.py`); the round launch heights 4 m and 3.4 m, the scale offsets 0.984 and 0.7346 degrees, the limits and the
  10 m minimum distance are upstream figures that no file decides (ASSUMED). SB has better entries for the same guns
  (per vehicle, from the files); these two stay for users of the older selection.
* **AGS-17** (SC `AGS-17`, SB `AGS-17 · emplacement · optic (RMB x2.5)` and the five other AGS-17 entries): velocity 185 m/s
  and gravity x1.8 are from the files (VERIFIED, agree with the 67 measurements to 0.7 % in v^2/g); the hold rate 9.08 deg/s,
  the hold range and the top 85.87 degrees are **fitted** to those measurements (UNVERIFIED); the minimum distance (280 m) is
  computed from that fit; the 1 m launch height was kept with the fit (the files say 0.347 m).
* **QLZ87**: the camera offset measured in the normal view, 0.23 m up and 0.34 m right of the pivot (worth -8.5 / -5.6 /
  -4.2 m of range at 200 / 300 / 400 m), is **measured** and not applied by either app (`docs/sight-data.md` of SB). The
  game has a Blueprint property that may be its source, `ProjectileCameraRelativeOffsetMultiplier` = 0.666667 on 44 weapon
  Blueprints (the QLZ-87 family, the 2A70 / 2A72 of BMD-4M and BMP-3M, the KBA3, M68A2, MG253 HE rounds, the RHIB Mk19 and NSV, ...):
  it is read from `resolved.json` and used by no tool, and what it multiplies is native code (UNVERIFIED).
* **Workshop mods** (SC `MO120RTF1`, `type_63`, `PZL07`, `M109`, `M777`, `T62.DUMP.TRUCK`, `HIMARS`, `TOS-1A`, `Ural-HellCannon`,
  `MTLB_FAB500`): not in the dedicated-server package; every input is ASSUMED from the upstream table (the mod authors' values).
* **Generated weapons** (the `DF_...` entries of SC, 125 of them): produced from SB `weapons.json` by
  `tools/direct_fire/gen_squadcalc_weapons.py`, which takes the spread and explosion from tables it verifies against the
  game (`--verify resolved.json`); the autocannons and machine guns SB removed in 1.6.0 (`M242`, `2A42 / 2A72`, `L21A1`, `CTAS40`,
  `ZPT99`, `KPVT`, `M2A1 .50`, `NSV`, `DShK-M`, `Kord`: 19 entries) are kept only in SC with `SQUADCALC_ONLY`, their classes from `gamecheck.py`.

## 7. Differences from the game

Found by comparing every weapon of both apps with the game classes (`provenance.py`, run on `resolved.json` of build
26005357; `gamecheck.py` and `compare.py` as before). The check lists a difference when an app's value is not the
game's; with Squad Ballistics 1.7.1 and SquadCalc 45.39.0 there are **0 unexplained differences** in 3 507 labelled rows.

| Weapon | Input | Game | App before | Change |
|---|---|---|---|---|
| 108 generated direct-fire weapons of SC (all with a game lifespan) | lifespan | 4 s (RPG-7, M3 MAAWS, Carl Gustav, SMAW), 5 s (RPG-29, RPG-28, autocannons), 8 s (SPG-9, Grom, tank AP, machine guns), 10-20 s (others) | SC default 100 s; SB none | SC `projectileLifespan` from the game via `gen_squadcalc_weapons.py` (45.30.0); SB `lifespan` (1.6.1); tests: SC `weapons.test.mjs`, `squadBallistics.test.mjs`, SB `test_ballistics.py`, `test_game_weapons.py` |

Documented differences that are not changed (the same set the TSV marks, and the variants table below):

* `M72A7 LAW / RPG-26`: lifespan 20 s of the M72A7; the RPG-26's is 5 s.
* The AP and HE shells of `2A72 30mm (BMP-3M)`, `ZPT99 30mm (ZBD-04A)` and `ZPT99 30mm (ZBL-08 / ZBD-05)` share one cap
  (1385); the HE round's is 1000. No effect at 970 / 950 m/s.
* Launch height of the stationary AGS-17 (1 m, game 0.347 m), MK19 (none, game 0.368 m) and SPG-9 (none, game 0.637 m):
  SB release notes 1.6.0 (#13); the measurements cannot tell 0.347 m from 1 m; the figures are not reproducible by a committed tool.
* The maximum range (the circle on the SC map, `max_range` of SB) is the geometric range of the flight and ignores the
  lifespan: an RPG-7 shows about 5.7 km while its rocket is gone after about 900 m. A solution past the lifespan is refused.
  SB's overlay text for such a target is "Out of range (max ... m)" with the geometric number (`crosshair.py`, not changed here).
* The spread of the grenade machine guns is the resting value of the curve in the generated weapons and the sustained
  value in the AGS-17 (inherited): the game's dynamic MOA grows with each shot by native code that is not recovered
  (`tools/volumetric/docs/native-rules.md`).

Classes of one calculator entry that differ in the game (informational: the entry follows the first class):

<!-- generated:variants -->
| Weapon | Variant class | Differs |
|---|---|---|
| M203 / M320 / GP-25 / HK79 / SL40 | BP_AK74GP25_UGL_Parent | moa 30 -> 40 |
| Rifle grenade | BP_FNFAL_GL_HEAT | explosion (250.0, (4.0, 18.0), 0.08, 1.0) -> (130.0, (2.0, 8.0), 0.08, 1.0) |
| MK19 | BP_Mk19_RHIB_Weapon | moa 50 -> 1.5 |
| MK19 | BP_Mk19_OpenTurret_Weapon | moa 50 -> 1.5 |
| QLZ87 · optic (RMB ×3) | BP_QLZ87_Weapon | moa 20 -> 1.5 |
| QLZ87 · optic (RMB ×3) | BP_QLZ87_OpenTurret_Weapon | moa 20 -> 1.5 |
| M72A7 LAW / RPG-26 | BP_RPG26_2mags | lifespan 20 -> 5; explosion (100.0, (1.5, 7.5), 0.08, 1.0) -> (115.0, (1.5, 7.5), 0.08, 1.0) |
| MK153 SMAW | BP_SMAW_Tandem_2mags | explosion (200.0, (2.0, 8.0), 0.08, 1.0) -> (80.0, (2.0, 8.0), 0.08, 0.0) |
| RPG-7 · PG-7V HEAT / OG-7V | BP_RPG7_Frag | explosion (130.0, (2.0, 8.0), 0.08, 1.0) -> (250.0, (2.0, 16.0), 0.08, 1.0) |
| RPG-7V1 · HEAT | BP_RPG7V1_Frag | explosion (130.0, (2.0, 8.0), 0.08, 1.0) -> (250.0, (2.0, 16.0), 0.08, 1.0) |
| M3 MAAWS · HEAT / Smoke | BP_M3MAAWS_Smoke | explosion (130.0, (2.0, 8.0), 0.08, 1.0) -> None |
| SPG-9 · FRAG | BP_SPG9_Frag | moa 3 -> 1 |
| ZiS-3 · optic (RMB ×4) | BP_ZiS3_Weapon_Frag | explosion (200.0, (3.5, 16.0), 0.15, 2.0) -> (200.0, (2.0, 16.0), 0.08, 1.0) |
| Tank AP · M256 / Rh120 | BP_L55_AP | moa 1.5 -> 1.2 |
| Tank HEAT/HE · T-72 (2A46) | BP_2A46_Frag | explosion (200.0, (3.5, 16.0), 0.15, 2.0) -> (300.0, (4.0, 35.0), 0.2, 5.0) |
| Tank HESH · L30A1 (Challenger 2) | BP_L30A1_Smoke | explosion (200.0, (7.0, 20.0), 0.15, 2.0) -> (150.0, (2.0, 10.0), 0.08, 1.0) |
| ZPL-98A 105mm (ZTD-05) · HEAT / HE | BP_ZTD05_ZPL-98A_Frag | explosion (200.0, (3.5, 16.0), 0.15, 2.0) -> (300.0, (4.0, 35.0), 0.2, 5.0) |
| 2A42 / 2A72 30mm · AP | BP_BMD4M_2A72_AP | moa 3 -> 6 |
| 2A42 / 2A72 30mm · AP | BP_BTR82A_RUS_2A72_AP | moa 3 -> 6 |
| 2A72 30mm (BMP-3M) · AP / HE | BP_BMP3M_2A72_HE | max_speed 1385 -> 1000; moa 1.35 -> 1.69; explosion (115.0, (5.0, 15.0), 0.2, 1.0) -> (125.0, (1.0, 7.5), 0.08, 2.0) |
| ZPT99 30mm (ZBD-04A) · AP / HE | BP_ZBD04A_ZPT99_HEFrag | max_speed 1385 -> 1000; moa 1.35 -> 1.69; explosion (115.0, (5.0, 15.0), 0.2, 1.0) -> (125.0, (1.0, 7.5), 0.08, 2.0) |
| ZPT99 30mm (ZBL-08 / ZBD-05) · AP / HE | BP_ZBL08_ZPT-99_HEFrag | max_speed 1385 -> 1000; moa 3.5 -> None; explosion (115.0, (5.0, 15.0), 0.2, 1.0) -> (125.0, (1.0, 7.5), 0.08, 2.0) |
| ZPT99 30mm (ZBL-08 / ZBD-05) · AP / HE | BP_ZBD05_ZPT-99_HE | max_speed 1385 -> 1000; moa 3.5 -> None; explosion (115.0, (5.0, 15.0), 0.2, 1.0) -> (125.0, (1.0, 7.5), 0.08, 2.0) |
| M1064 M121 (120mm) | BP_M1064A3_M121mortar_Airburst | moa 40 -> 50; explosion (400.0, (0.0, 40.0), 1.0, 7.0) -> (100.0, (10.0, 60.0), 10.0, 1.3) |
<!-- /generated:variants -->

## 8. Weapon index

Every weapon of both apps with the classes of section 4 and where its values come from.

<!-- generated:index -->
| App | Weapon | Classes | Origin |
|---|---|---|---|
| SB | M203 / M320 / GP-25 / HK79 / SL40 | C01 | from the game files |
| SB | MGL / M32 | C02 | from the game files |
| SB | AK-40GL (MPT-76) | C03 | from the game files |
| SB | QLG10 | C04 | from the game files |
| SB | Rifle grenade | C05 | from the game files |
| SB | MK19 | C06 | from the game files |
| SB | MK19 · M1117 · gunner sight ×4.5 | C06 | from the game files |
| SB | MK19 · AAVP-7A1 | C07 | from the game files |
| SB | MK19 · AAVP-7A1 · gunner sight ×4.5 | C07 | from the game files |
| SB | MK19 · PARS III RWS | C08 | from the game files |
| SB | MK19 · PARS III RWS · gunner sight ×3 | C08 | from the game files |
| SB | MK19 · PARS III RWS · gunner sight ×9 | C08 | from the game files |
| SB | MK19 · TAPV C16 RWS | C09 | from the game files |
| SB | MK19 · TAPV C16 RWS · gunner sight ×5 | C09 | from the game files |
| SB | MK19 · TAPV C16 RWS · gunner sight ×12 | C09 | from the game files |
| SB | MK19 · M113 open turret | C10 | from the game files |
| SB | MK19 · M113 open turret · no sights | C10 | from the game files |
| SB | MK19 · M1151 open turret | C10 | from the game files |
| SB | MK19 · M1151 open turret · no sights | C10 | from the game files |
| SB | MK19 · MATV open turret | C10 | from the game files |
| SB | MK19 · MATV open turret · no sights | C10 | from the game files |
| SB | MK19 · RHIB open turret | C11 | from the game files |
| SB | MK19 · RHIB open turret · no sights | C11 | from the game files |
| SB | MK19 · emplacement / C16 / L134A1 | C12 | from the game files |
| SB | MK19 · emplacement / C16 / L134A1 · no sights | C12 | from the game files |
| SB | AGS-17 · emplacement · optic (RMB ×2.5) | C13 | from the game files; hold model fitted (67 measurements); launch / limits hand-read |
| SB | AGS-17 · emplacement · no optic | C13 | from the game files; hold model fitted (67 measurements); launch / limits hand-read |
| SB | AGS-17 · iron sights emplacement | C14 | from the game files; hold model fitted (67 measurements); launch / limits hand-read |
| SB | AGS-17 · Technical | C15 | from the game files; hold model fitted (67 measurements) |
| SB | AGS-17 · Tigr | C16 | from the game files; hold model fitted (67 measurements) |
| SB | AGS-17 · Safir | C17 | from the game files; hold model fitted (67 measurements) |
| SB | AGS-17 · M1151 | C16 | from the game files; hold model fitted (67 measurements) |
| SB | AGS-17 · BTR-D | C16 | from the game files; hold model fitted (67 measurements) |
| SB | QLZ87 · optic (RMB ×3) | C18 | from the game files |
| SB | QLZ87 · no optic | C18 | from the game files |
| SB | QLZ87 · bunker tripod · optic (RMB ×3) | C18 | from the game files |
| SB | QLZ87 · bunker tripod · no optic | C18 | from the game files |
| SB | QLZ87 · CSK131 / WZ551 · optic (RMB ×3) | C19 | from the game files |
| SB | QLZ87 · CSK131 / WZ551 · no optic | C19 | from the game files |
| SB | QLZ87 · Lynx · optic (RMB ×3) | C20 | from the game files |
| SB | QLZ87 · Lynx · no optic | C20 | from the game files |
| SB | QLZ87 · ZBL08 · optic (RMB ×3) | C21 | from the game files |
| SB | QLZ87 · ZBL08 · no optic | C21 | from the game files |
| SB | AGS-30 / BTR-4 AGS | C22 | from the game files |
| SB | AGS-30 / BTR-4 AGS · gunner sight ×9 | C22 | from the game files |
| SB | AGS-30 (BMP-1TS) | C23 | from the game files |
| SB | AGS-30 (BMP-1TS) · gunner sight ×9 | C23 | from the game files |
| SB | AGS-30 (BMP-2M) | C24 | from the game files |
| SB | AGS-30 (BMP-2M) · gunner sight ×6 | C24 | from the game files |
| SB | M72A7 LAW / RPG-26 | C25 | from the game files |
| SB | C90-CR | C26 | from the game files |
| SB | AT-4 | C27 | from the game files |
| SB | MK153 SMAW | C28 | from the game files |
| SB | PF98 · Tandem | C29 | from the game files |
| SB | PF98 · HE-I | C30 | from the game files |
| SB | RPG-29 | C31 | from the game files |
| SB | DZJ-08 | C32 | from the game files |
| SB | RPG-28 | C33 | from the game files |
| SB | RPG-7 · PG-7V HEAT / OG-7V | C34 | from the game files |
| SB | RPG-7 · PG-7VR Tandem | C35 | from the game files |
| SB | RPG-7V1 · PG-7VR Tandem | C36 | from the game files |
| SB | RPG-7V2 · PG-7VR Tandem | C37 | from the game files |
| SB | RPG-7 · TBG-7V Thermobaric | C38 | from the game files |
| SB | RPG-7V1 · HEAT | C39 | from the game files |
| SB | M3 MAAWS · HEAT / Smoke | C40 | from the game files |
| SB | M3 MAAWS · Tandem | C41 | from the game files |
| SB | Carl Gustav M2 · FFV551 HEAT | C42 | from the game files |
| SB | Carl Gustav M2 · FFV441D HE | C43 | from the game files |
| SB | Carl Gustav M2 · FFV751 Tandem | C44 | from the game files |
| SB | NLAW | C45 | from the game files |
| SB | SPG-9 · HEAT | C46 | from the game files |
| SB | SPG-9 · HEAT · scope · optic (RMB ×4) | C47 | from the game files |
| SB | SPG-9 · HEAT · scope · no optic | C47 | from the game files |
| SB | SPG-9 · FRAG | C48 | from the game files |
| SB | SPG-9 · FRAG · scope · optic (RMB ×4) | C49 | from the game files |
| SB | SPG-9 · FRAG · scope · no optic | C49 | from the game files |
| SB | SPG-9 · HEAT · technical · optic (RMB ×4) | C50 | from the game files |
| SB | SPG-9 · HEAT · technical · no optic | C50 | from the game files |
| SB | SPG-9 · FRAG · technical · optic (RMB ×4) | C51 | from the game files |
| SB | SPG-9 · FRAG · technical · no optic | C51 | from the game files |
| SB | SPG-9 · HEAT · INS armoured technical · optic (RMB ×4) | C50 | from the game files |
| SB | SPG-9 · HEAT · INS armoured technical · no optic | C50 | from the game files |
| SB | SPG-9 · FRAG · INS armoured technical · optic (RMB ×4) | C51 | from the game files |
| SB | SPG-9 · FRAG · INS armoured technical · no optic | C51 | from the game files |
| SB | 2A28 Grom (BMP-1 / BMD-1) · HEAT | C52 | from the game files |
| SB | 2A28 Grom (BMP-1) · HEAT · gunner sight ×6 | C52 | from the game files |
| SB | 2A28 Grom (BMP-1 technical) · HEAT · gunner sight ×6 | C53 | from the game files |
| SB | 2A28 Grom (BMD-1M) · HEAT | C54 | from the game files |
| SB | 2A28 Grom (BMP-1 technical) · HEAT | C53 | from the game files |
| SB | 2A28 Grom (BMD-1M) · HEAT · gunner sight ×6 | C54 | from the game files |
| SB | 2A28 Grom (BMP-1 / BMD-1) · FRAG | C55 | from the game files |
| SB | 2A28 Grom (BMP-1) · FRAG · gunner sight ×6 | C55 | from the game files |
| SB | 2A28 Grom (BMP-1 technical) · FRAG · gunner sight ×6 | C56 | from the game files |
| SB | 2A28 Grom (BMD-1M) · FRAG | C57 | from the game files |
| SB | 2A28 Grom (BMP-1 technical) · FRAG | C56 | from the game files |
| SB | 2A28 Grom (BMD-1M) · FRAG · gunner sight ×6 | C57 | from the game files |
| SB | 2A70 100mm (BMP-3 / BMD-4 / ZBD04A) · FRAG | C58 | from the game files |
| SB | 2A70 100mm (BMP-3) · FRAG · gunner sight ×4 | C58 | from the game files |
| SB | 2A70 100mm (ZBD-04A) · FRAG | C59 | from the game files |
| SB | 2A70 100mm (ZBD-04A) · FRAG · gunner sight ×4 | C59 | from the game files |
| SB | 2A70 100mm (ZBD-04A) · FRAG · gunner sight ×14 | C59 | from the game files |
| SB | 2A70 100mm (BMD-4M) · FRAG | C60 | from the game files |
| SB | 2A70 100mm (BMD-4M) · FRAG · gunner sight ×5 | C60 | from the game files |
| SB | 2A70 100mm (BMP-3 / BMD-4M) · FRAG · gunner sight ×14 | C60 | from the game files |
| SB | ZiS-3 · optic (RMB ×4) | C61 | from the game files |
| SB | ZiS-3 · no optic | C61 | from the game files |
| SB | Tank AP · T-72 (2A46) | C62 | from the game files |
| SB | Tank AP · T-90A (2A46M) | C63 | from the game files |
| SB | Tank AP · Sprut-SDM1 (2A45) · gunner sight ×4 | C64 | from the game files |
| SB | Tank AP · Sprut-SDM1 (2A45) · gunner sight ×12 | C64 | from the game files |
| SB | Tank AP · T-72 (2A46) · gunner sight ×12 | C65 | from the game files |
| SB | Tank AP · T-90A (2A46M) · gunner sight ×12 | C63 | from the game files |
| SB | Tank AP · T-62 (2A20) | C66 | from the game files |
| SB | Tank AP · T-62 (2A20) · gunner sight ×7 | C66 | from the game files |
| SB | Tank AP · T-64BM2 (KBA3) | C67 | from the game files |
| SB | Tank AP · T-64BM2 (KBA3) · gunner sight ×12 | C67 | from the game files |
| SB | Tank AP · ZTZ-99 (ZPT-98) | C68 | from the game files |
| SB | Tank AP · ZTZ-99 (ZPT-98) · gunner sight ×12 | C68 | from the game files |
| SB | Tank AP · M256 / Rh120 | C69 | from the game files |
| SB | Tank AP · M1A1 / M1A2 (M256) · gunner sight ×6 | C70 | from the game files |
| SB | Tank AP · M1A1 / M1A2 (M256) · gunner sight ×12 | C70 | from the game files |
| SB | Tank AP · Leopard 2A6 (Rh120) | C71 | from the game files |
| SB | Tank AP · Leopard 2A6 (Rh120) · gunner sight ×12 | C71 | from the game files |
| SB | Tank AP · M60T (MG253) | C72 | from the game files |
| SB | Tank AP · M60T (MG253) · gunner sight ×3 | C72 | from the game files |
| SB | Tank AP · M60T (MG253) · gunner sight ×8 | C72 | from the game files |
| SB | Tank AP · L30A1 (Challenger 2) / M68A2 | C73 | from the game files |
| SB | Tank AP · Challenger 2 (L30A1) · gunner sight ×4 | C73 | from the game files |
| SB | Tank AP · Challenger 2 (L30A1) · gunner sight ×10 | C73 | from the game files |
| SB | Tank AP · M1128 MGS (M68A2) | C74 | from the game files |
| SB | Tank AP · M1128 MGS (M68A2) · gunner sight ×8 | C74 | from the game files |
| SB | Tank HEAT/HE · T-72 (2A46) | C75 | from the game files |
| SB | Tank HEAT/HE · T-90A (2A46M) | C76 | from the game files |
| SB | Tank HEAT/HE · Sprut-SDM1 (2A45) · gunner sight ×4 | C77 | from the game files |
| SB | Tank HEAT/HE · Sprut-SDM1 (2A45) · gunner sight ×12 | C77 | from the game files |
| SB | Tank HEAT/HE · T-72 (2A46) · gunner sight ×12 | C78 | from the game files |
| SB | Tank HEAT/HE · T-90A (2A46M) · gunner sight ×12 | C76 | from the game files |
| SB | Tank HEAT/HE · M1A1 / M1A2 (M256) | C79 | from the game files |
| SB | Tank HEAT/HE · M1A1 / M1A2 (M256) · gunner sight ×6 | C79 | from the game files |
| SB | Tank HEAT/HE · M1A1 / M1A2 (M256) · gunner sight ×12 | C79 | from the game files |
| SB | Tank HEAT/HE · Leopard 2A6 (Rh120) | C80 | from the game files |
| SB | Tank HEAT/HE · Leopard 2A6 (Rh120) · gunner sight ×12 | C80 | from the game files |
| SB | Tank HEAT/HE · M1128 MGS (M68A2) | C81 | from the game files |
| SB | Tank HEAT/HE · M1128 MGS (M68A2) · gunner sight ×8 | C81 | from the game files |
| SB | Tank HEAT/HE · M60T (MG253) | C82 | from the game files |
| SB | Tank HEAT/HE · M60T (MG253) · gunner sight ×3 | C82 | from the game files |
| SB | Tank HEAT/HE · M60T (MG253) · gunner sight ×8 | C82 | from the game files |
| SB | Tank HEAT/HE · ZTZ-99 (ZPT-98) | C83 | from the game files |
| SB | Tank HEAT/HE · ZTZ-99 (ZPT-98) · gunner sight ×12 | C83 | from the game files |
| SB | Tank HEAT/HE · T-62 (2A20) | C84 | from the game files |
| SB | Tank HEAT/HE · T-62 (2A20) · gunner sight ×7 | C84 | from the game files |
| SB | Tank HEAT/HE · T-64BM2 (KBA3) | C85 | from the game files |
| SB | Tank HEAT/HE · T-64BM2 (KBA3) · gunner sight ×12 | C85 | from the game files |
| SB | Tank HESH · L30A1 (Challenger 2) | C86 | from the game files |
| SB | Tank HESH · Challenger 2 (L30A1) · gunner sight ×4 | C86 | from the game files |
| SB | Tank HESH · Challenger 2 (L30A1) · gunner sight ×10 | C86 | from the game files |
| SB | ZPL-98A 105mm (ZTD-05) · AP | C87 | from the game files |
| SB | ZPL-98A 105mm (ZTD-05) · AP · gunner sight ×7 | C87 | from the game files |
| SB | ZPL-98A 105mm (ZTD-05) · HEAT / HE | C88 | from the game files |
| SB | ZPL-98A 105mm (ZTD-05) · HEAT / HE · gunner sight ×7 | C88 | from the game files |
| SB | Mortar (M252 / 2B14 / L16 / Type 63) | C89 | from the game files; hold model fitted (67 measurements); launch / limits hand-read |
| SB | Technical Mortar | C90 | from the game files |
| SB | M1064 M121 (120mm) | C91 | from the game files |
| SB | Hell Cannon | C92 | from the game files; launch / limits hand-read |
| SB | UB-32 (S-5 rockets) | C93 | from the game files; launch / limits hand-read |
| SB | Technical UB-32 | C94 | from the game files |
| SB | BM-21 Grad | C95 | from the game files |
| SC | Mortar | C89 | hand-kept in SC weapons.js |
| SC | UB-32 | C93 | hand-kept in SC weapons.js |
| SC | HellCannon | C92 | hand-kept in SC weapons.js |
| SC | Tech.Mortar | C90 | hand-kept in SC weapons.js |
| SC | Tech.UB-32 | C94 | hand-kept in SC weapons.js |
| SC | BM-21Grad | C95 | hand-kept in SC weapons.js |
| SC | M1064M121 | C91, C96 | hand-kept in SC weapons.js |
| SC | Mk19 | C06 | hand-kept in SC weapons.js; height, angle offset, limits, min distance from upstream |
| SC | BTR4-AGS | C22 | hand-kept in SC weapons.js; height, angle offset, limits, min distance from upstream |
| SC | MO120RTF1 | - | Workshop mod, not in the server files |
| SC | type_63 | - | Workshop mod, not in the server files |
| SC | PZL07 | - | Workshop mod, not in the server files |
| SC | M109 | - | Workshop mod, not in the server files |
| SC | M777 | - | Workshop mod, not in the server files |
| SC | T62.DUMP.TRUCK | - | Workshop mod, not in the server files |
| SC | HIMARS | - | Workshop mod, not in the server files |
| SC | TOS-1A | - | Workshop mod, not in the server files |
| SC | Ural-HellCannon | - | Workshop mod, not in the server files |
| SC | MTLB_FAB500 | - | Workshop mod, not in the server files |
| SC | AGS-17 | C13 | hand-kept in SC weapons.js; speed and top fitted (67 measurements) |
| SC | DF_M203_M320_GP_25_HK79_SL40 | C01 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_QLG10 | C04 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Rifle_grenade | C05, C97 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19 | C06 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_QLZ87 | C18 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_AGS_30_BTR_4_AGS | C22 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_M72A7_LAW_RPG_26 | C25 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_AT_4 | C27 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK153_SMAW | C28, C98 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_PF98_Tandem | C29 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_PF98_HE_I | C30 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_RPG_29 | C31 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_RPG_7_PG_7V_HEAT_OG_7V | C34, C99 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_RPG_7_PG_7VR_Tandem | C35 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_RPG_7V1_HEAT | C39, C100 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_M3_MAAWS_HEAT_Smoke | C40 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_M3_MAAWS_Tandem | C41 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_NLAW | C45 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT | C46 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG | C48 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMP_1_BMD_1_HEAT | C52 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMP_1_BMD_1_FRAG | C55 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_2A70_100mm_BMP_3_BMD_4_ZBD04A_FRAG | C58 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_ZiS_3 | C61, C101 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_2A46_ZPT98_2A20_2A45_KBA3 | C62 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_M256_Rh120 | C69 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_L30A1_Challenger_2_M68A2 | C73 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_M256_Rh120_2A46_ZPT98_2A20_M68A2 | C75, C102 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_HESH_L30A1_Challenger_2 | C86 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_M242_Bushmaster_25mm_AP | C103 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_M242_Bushmaster_25mm_HE | C104 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_2A42_2A72_30mm_AP | C105 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_2A42_30mm_BMP_2_HE | C106 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_L21A1_RARDEN_30mm_AP | C107 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_L21A1_RARDEN_30mm_HE | C108 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_CTAS40_40mm_AP | C109 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_CTAS40_40mm_GP | C110 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_ZPT99_30mm_ZBL_08_APFSDS | C111 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_ZPT99_30mm_ZBD_04A_AP_HE | C112, C113 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_KPVT_14_5mm | C114 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_M2A1_50 | C115 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_NSV | C116 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_DShK_M | C117 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_MGL_M32 | C02 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_AK_40GL_MPT_76 | C03 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_emplacement_C16_L134A1 | C12 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_RPG_7_TBG_7V_Thermobaric | C38 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Carl_Gustav_M2_FFV551_HEAT | C42 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Carl_Gustav_M2_FFV441D_HE | C43 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Carl_Gustav_M2_FFV751_Tandem | C44 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_ZPL_98A_105mm_ZTD_05_AP | C87 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_ZPL_98A_105mm_ZTD_05_HEAT_HE | C88, C118 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_2A72_30mm_BMD_4M_HE | C119 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_2A72_30mm_BMP_3M_AP_HE | C120, C121 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_ZPT99_30mm_ZBL_08_ZBD_05_AP_HE | C122 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_M2A1_50_ACOG_emplacement | C123 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_Kord_SPP_emplacement | C124 | SquadCalc only, game classes of gamecheck.py |
| SC | DF_AGS_17_emplacement_no_optic | C13 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_QLZ87_no_optic | C18 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_QLZ87_Lynx_CSK131_no_optic | C20 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_scope_no_optic | C47 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_scope_no_optic | C49 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_ZiS_3_no_optic | C61, C101 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_PARS_III_RWS | C08 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_TAPV_C16_RWS | C09 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_M113_open_turret | C10 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_M1151_RHIB_open_turret | C10 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_AGS_17_iron_sights_emplacement | C14 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_QLZ87_Lynx_CSK131 | C20 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_AGS_30_BMP_2M | C24 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_scope | C47 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_scope | C49 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMD_1M_HEAT | C54 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMD_1M_FRAG | C57 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_2A70_100mm_ZBD_04A_FRAG | C59 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_2A70_100mm_BMD_4M_FRAG | C60 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_T_62_2A20 | C66 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_T_64BM2_KBA3 | C67 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_ZTZ_99_ZPT_98 | C68 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_Leopard_2A6_Rh120 | C71 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_M60T_MG253 | C72 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_M1128_MGS_M68A2 | C74 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_M1A1_M1A2_M256 | C79 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_Leopard_2A6_Rh120 | C80 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_M1128_MGS_M68A2 | C81 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_M60T_MG253 | C82 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_ZTZ_99_ZPT_98 | C83, C125 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_T_62_2A20 | C84, C126 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_T_64BM2_KBA3 | C85, C127 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_emplacement_C16_L134A1_no_sights | C12 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_AGS_30_BMP_1TS | C23 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_AAVP_7A1 | C07 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_M113_open_turret_no_sights | C10 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_M1151_open_turret_no_sights | C10 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_MATV_open_turret | C10 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_MATV_open_turret_no_sights | C10 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_MK19_RHIB_open_turret | C11 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_AGS_17_Technical | C15 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_AGS_17_Tigr | C16 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_AGS_17_Safir | C17 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_AGS_17_M1151 | C16 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_AGS_17_BTR_D | C16 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_C90_CR | C26 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_DZJ_08 | C32 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_RPG_28 | C33 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_RPG_7V1_PG_7VR_Tandem | C36 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_RPG_7V2_PG_7VR_Tandem | C37 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_technical_optic_RMB_4 | C50 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_technical_no_optic | C50 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_technical_optic_RMB_4 | C51 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_technical_no_optic | C51 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_INS_armoured_technical_optic_RMB_4 | C50 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_INS_armoured_technical_no_optic | C50 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_INS_armoured_technical_optic_RMB_4 | C51 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_INS_armoured_technical_no_optic | C51 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_QLZ87_bunker_tripod_no_optic | C18 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_QLZ87_CSK131_WZ551_no_optic | C19 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_QLZ87_ZBL08_no_optic | C21 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMP_1_technical_HEAT | C53 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMP_1_technical_FRAG | C56 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_2A70_100mm_BMP_3_BMD_4M_FRAG_gunner_sight_14 | C60 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_T_90A_2A46M | C63 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_Sprut_SDM1_2A45_gunner_sight_4 | C64 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_T_90A_2A46M | C76, C128 | generated from SB weapons.json by gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_Sprut_SDM1_2A45_gunner_sight_4 | C77, C129 | generated from SB weapons.json by gen_squadcalc_weapons.py |
<!-- /generated:index -->

## 9. Reproduction and the check

Game data (build 26005357, existing dumps; the extractor is not run): `~/data/squad-weapons/{dump,resolved.json}`.

```sh
# model and differences as before
python3 tools/game_ballistics/gamecheck.py resolved.json <SB>/weapons.json squadcalc_weapons.json ballistics.json diff.md
python3 tools/direct_fire/compare.py <SB checkout> <SC checkout>       # 167 weapons, 31 194 cases, 0 mismatches
python3 tools/direct_fire/gen_squadcalc_weapons.py --verify resolved.json

# this document: rewrite the generated blocks and the TSV, or check them
python3 tools/game_ballistics/provenance.py --resolved resolved.json --dump dump --sb <SB> --sc <SC> --write tools/volumetric/docs
python3 tools/game_ballistics/provenance.py --resolved resolved.json --dump dump --sb <SB> --sc <SC> --check tools/volumetric/docs
python3 -m unittest tests.test_data_provenance                         # from tools/volumetric
```

`--check` fails when a weapon of `weapons.json` or `weapons.js` is missing from the index of either language, when a block
or the TSV is stale, or when an app's value differs from the game without an entry in `KNOWN` of `provenance.py`.
`tests/test_data_provenance.py` runs it where the checkouts and the data are present (`SQUAD_BALLISTICS`, `SQUADCALC`,
`SQUAD_WEAPONS_DATA`) and always tests the check on small synthetic data.

## 10. What this audit cannot show

* Thirteen SB entries (MK19 on PARS III and TAPV C16 with the zoom levels of their sights, AGS-17 on Technical, Tigr, Safir,
  M1151, BTR-D, QLZ87 on the ZBL08 in both views) name Blueprints that are
  not in the existing dump: their flight values are the snapshot's (VERIFIED by `tools/game_weapons.py`, which needs
  the full dump to re-run), their spread and explosion UNVERIFIED.
* The curves `FC_MOACurve_GenericHMG`, `_GenericGPMG` and `_Kord` are not in the dump; their values are those of
  `gamecheck.py` `MOA_CURVES`. How the dynamic MOA that feeds a curve grows is native code and not recovered.
* The native explosion defaults (115 damage, 5 m inner, 15 m outer, falloff 1, 0.2 m height) are inferred from projectiles
  that override only some fields and from SquadCalc's SDK-derived values; no file holds them.
* Handheld bore and zoom come from the first-person animation, which the server package does not hold.
* The AGS-17 fit and the QLZ87 camera offset are the owner's in-game measurements, which are not in the repositories.
* Nothing was fired in a game: the model is the game's code and Blueprints, not an in-game shot.
