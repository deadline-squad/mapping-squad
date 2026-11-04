# Damage of shells to structures (Squad build 26005357)

Question (owner, 2026-11-04, plan item C7 of deadline-squad/deadline-squadcalc#22): how much damage do shells do to
**the structures players build** (FOB radio, HAB, and what is built at them: HESCO, sandbags, bunkers, emplacements,
wire), by material and by ammunition. Armour-piercing rounds are not fired at structures and no penetration
calculation is wanted. Map buildings are a short separate section (B).

Labels: **VERIFIED** = read from the cooked dedicated-server assets (the client pak was not used; nothing was
decrypted or circumvented); **INFERRED** = follows from verified field names or values but the rule that
applies them is native code that is not in the paks; **UNVERIFIED** = needs an in-game test or the engine
source. All asset names are `/Game/...` paths of the server package. Russian version: [`structure-damage.ru.md`](structure-damage.ru.md).

## 1. Answers in short

1. Structures have **health and a per-damage-type multiplier table in the deployable's own Blueprint**, not in the
   material. `MaxHealth`, `InitialHealth` and `AllowableDamageTypes` (a list of `{DamageTypeClass, Modifier,
   DirectHitDamageMultiplier, IndirectHitDamageMultiplier, DirectHitRadialDamageMultiplier, ...}`) are properties of
   `/Game/Gameplay/Deployables/BP_Deployable` and its children. 227 of 235 deployable Blueprints resolve to a
   health, in 49 distinct (health, table) groups below (45 with a damage-type table, the ones in SquadCalc). VERIFIED.
2. Every projectile Blueprint names the damage type it applies (`DamageTypeToApply`), a direct-hit damage
   (`ImpactDamageToApply`) and an explosion (`ExplosiveBaseDamage`, inner/outer radius, falloff); mortars, the Hell
   Cannon and the BM-21 have a **secondary explosion with its own damage type** (`SecondaryExplosionDamageType`,
   `SecondaryOnlyDamageMeshes`). VERIFIED. Mortar rounds: primary Fragmentation, secondary **Explosives** (modifier
   25 times larger on HESCO: 0.25 against 0.01), which is where most of a mortar's structure damage comes from.
3. The physical-material fields (`damage_absorbed`, `armor_thickness_mm`, `allow_penetration`) are **not connected
   to explosion damage on structures**: no deployable, damage type or projectile asset refers to a physical
   material for damage (key lists in section 6). They belong to bullet penetration. VERIFIED absence.
   Materials do tell what a structure is made of (section 5), so "by material" is answered by the
   structure's own table, which was authored per structure (HESCO and bunkers: 0.01 frag, 0.25 explosives;
   sandbags 0.05 / 0.05; metal tripods 0.3 / 1.0).
4. A calculation is supported and implemented: `damageToStructure` and `shellsToDestroy` in SquadCalc
   (`src/js/structureDamage.js`, data `src/data/structureDamage.js`, `tests/structureDamage.test.mjs`).
   The way the game combines the fields is native code: the formula is INFERRED (section 4) and has not been checked in game.

## 2. Structures: health and multipliers (VERIFIED values)

Health: `MaxHealth` (`InitialHealth` is the health when the deployable is placed and starts being built; the
FOB radio starts at full health, HAB 25, HESCO 5, bunkers 5-20). `HalfBuiltTransitionHealth` /
`FullyBuiltTransitionHealth` (fractions of `MaxHealth`) mark the build states. Cells are `Modifier`; `(d/i/r)` shows
the three hit multipliers when any differs from 1 (`DirectHitDamageMultiplier`, `IndirectHitDamageMultiplier`,
`DirectHitRadialDamageMultiplier`); `-` = the damage type is not listed. The groups are in `data/structure_damage.json`
(`deployables`, every class with its chain, meshes and materials). Frag = `BP_Fragmentation_DamageType`, HEAT =
`BP_BasicHeatDamageType`, HAT = `BP_HAT_DamageType`, Explosives = `BP_Explosives_Damagetype`, Kinetic = `BP_Kinetic_DamageType`.

| first class (n classes) | HP | Frag | HEAT | HAT | Explosives | Kinetic | other |
|---|---|---|---|---|---|---|---|
| ADF_Hab_Desert (17) | 500 | 0.01 | 0.031579 | 0.008 | 0.1 | 0.003125 | - |
| BP_2b14podnosmortar_Deployable (1) | 420 | 0.3 | 1 (d1/i0.2/r1) | - | 1 | 0.0268 | SQDamageType_Thermite 10 |
| BP_AFU_smallbunker_Woodland (12) | 500 | 0.01 | 0.01 | 0.05 | 0.25 | 0.005 | - |
| BP_AGS17_Tripod (7) | 320 | 0.3 | 1 (d1/i0.2/r1) | - | 1 | 0.0224 | SQDamageType_Thermite 10 |
| BP_Ammocrate (12) | 150 | 1 (d1/i0.05/r0) | 1 (d1/i0.5/r0) | 1.75 (d1/i0.5/r0) | 1 (d1/i1/r0) | 0.01 (d1/i1/r0) | - |
| BP_Ammocrate_AFU (4) | 100 | - | - | - | - | - | - |
| BP_Ammocrate_IMF (1) | 150 | 1 (d1/i0.05/r1) | 1 (d1/i0.5/r1) | 1.75 (d1/i0.5/r1) | 1 | 0.01 | - |
| BP_Ammocrate_MEI (1) | 150 | 0.5 (d0.5/i0.5/r1) | 0.5 (d0.5/i0.5/r1) | - | 0.01 | 0.01 (d0.1/i0.1/r1) | BP_Melee 0, BP_SmallArms_DamageType 0 |
| BP_Ammocrate_RGF_Desert (2) | 150 | 0.5 (d0.5/i0.5/r1) | 0.5 (d0.5/i0.5/r1) | - | 1 | 0.5 (d0.5/i0.5/r1) | BP_Melee 0, BP_SmallArms_DamageType 0.01 |
| BP_BGM71TOW_Tripod_USA (1) | 450 | 0.01 (d0.01/i0.01/r1) | 0.5 (d0.5/i0.5/r1) | - | 1 (d0.5/i0.5/r1) | 0.3 (d0.3/i0.3/r1) | BP_Melee 0, BP_SmallArms_DamageType 0, SQDamageType_Thermite 10 |
| BP_BaseFobCreator (1) | 300 | - | - | - | - | - | - |
| BP_CamoNetCanopy_IMF (3) | 50 | 0.05 | 0.1 | 0.2 | 0.05 | - | - |
| BP_ConcreteBarrier (1) | 160 | 0.03 | 0.03 | 0.05 | 0.25 | 0.005 | - |
| BP_DShK (2) | 320 | 0.01 (d0.01/i0.01/r1) | 0.3 (d0.3/i0.3/r1) | - | 1 | 0.5 (d0.5/i0.5/r1) | BP_Melee 0, BP_SmallArms_DamageType 0, SQDamageType_Thermite 10 |
| BP_Deployable_CommandTent_IMF (2) | 1000 | - | - | - | - | - | - |
| BP_Deployable_Hab (1) | 100 | 0.01 | 0.031579 | 0.008 | 0.1 | 0.003125 | - |
| BP_DesertSandbag (7) | 225 | 0.05 | 0.1 | 0.2 | 0.05 | 0.02 | - |
| BP_FOBRadio_AFU (8) | 300 | 0.1 | 0.05 | 0.1 | 0.5 | 0.01 | - |
| BP_FobRadio_INS (1) | 300 | 0.1 | 0.05 | 1 | 0.5 | 0.05 | - |
| BP_HedgehogTankTrap (1) | 300 | 0.4 (d0.4/i0.4/r1) | 0.65 (d0.65/i0.65/r1) | - | 0.6 | 0.2 (d0.2/i0.2/r1) | BP_Melee 0, BP_SmallArms_DamageType 0 |
| BP_HescoWall_ADF_Desert (1) | 420 | 0.03 | 0.03 | 0.05 | 0.75 | 0.005 | - |
| BP_HescoWall_ADF_Forest (16) | 420 | 0.01 | 0.01 | 0.05 | 0.25 | 0.005 | - |
| BP_Hesco_ADF_Desert (1) | 200 | 0.03 | 0.03 | 0.05 | 0.6 | 0.005 | - |
| BP_Hesco_ADF_Forest (16) | 200 | 0.01 | 0.01 | 0.05 | 0.25 | 0.005 | - |
| BP_HullDownBase (3) | 450 | 0.01 | 0.01 | 0.05 | 0.5 | 0.005 | - |
| BP_I_Sandbag_GFI (5) | 225 | 0.05 | 0.1 | 0.2 | 0.05 | 0.05 | - |
| BP_I_Sandbag_murder_hole_GFI (1) | 200 | 0.2 | 0.1 | 0.2 | 0.5 | 0.05 | - |
| BP_Indirect_Mortar_Shelter (5) | 450 | 0 (d0/i0/r0) | 0.001 | 0.001 | 0.001 | 0.005 (d1/i0/r1) | - |
| BP_Kord_AFU_Bunker (26) | 600 | 0.01 | 0.01 | 0.05 | 0.25 | 0.005 | - |
| BP_Kord_GFI_Bunker (5) | 600 | 0.03 | 0.01 | 0.05 | 0.25 | 0.005 | - |
| BP_Kord_Tripod (1) | 320 | 0.3 | 1 (d1/i0.2/r1) | - | 1 | 0.0268 | SQDamageType_Thermite 10 |
| BP_Kornet_Tripod_GFI (2) | 450 | 0.3 | 1 (d1/i0.2/r1) | - | 1 | 0.0268 | SQDamageType_Thermite 10 |
| BP_L16mortar_Deployable (2) | 420 | 0.3 | 0.25 (d1/i0/r1) | - | 1 (d1/i0.2/r1) | 1 (d1/i0.2/r1) | - |
| BP_LogWall (3) | 300 | 0.03 | 0.03 | 0.05 | 0.25 | 0.005 | - |
| BP_M2HB_Tripod_Shielded (1) | 500 | 0.3 | 1 (d1/i0.2/r1) | - | 1 | 0.0224 | SQDamageType_Thermite 10 |
| BP_M2_ADF_Bunker_Desert (3) | 600 | 0.03 | 0.03 | 0.05 | 0.25 | 0.005 | - |
| BP_ObservationTower_ADF_Desert (16) | 800 | 0.01 | 0.01 | 0.01 | 0.25 | 0.005 | - |
| BP_ObservationTower_ADF_Woodland (1) | 800 | 0.03 | 0.03 | 0.05 | 0.75 | 0.005 | - |
| BP_ObservationTower_IMF_Desert (3) | 400 | 0.01 | 0.01 | 0.05 | 0.25 | 0.005 | - |
| BP_Razorwire_Dirty_2 (2) | 100 | 0.01 | 0.01 | 0.05 | 0.1 | 0.005 | - |
| BP_SPG9_Tripod (1) | 320 | 0.3 | 1 (d1/i0.2/r1) | - | 1 | 0.0268 (d1/i0.2/r1) | SQDamageType_Thermite 10 |
| BP_SandBagWall_2 (5) | 250 | 0.05 | 0.1 | 0.2 | 0.05 | 0.05 | - |
| BP_TestLadder_Metal (2) | 50 | 0.4 (d0.4/i0.4/r1) | 0.65 (d0.65/i0.65/r1) | - | 1 | 0.2 (d0.2/i0.2/r1) | BP_Melee 0, BP_SmallArms_DamageType 0 |
| BP_Vehicle_Repair_RGF (15) | 500 | 0.2 | 0.1 | 0.2 | 0.5 | 0.05 | - |
| BP_ZU-23_Emplacement (2) | 420 | 1 (d1/i0.3/r1) | 3.75 (d1/i0.2/r1) | - | 1 | 0.0268 | SQDamageType_Thermite 10 |
| BP_helicopter_repair_pad (1) | 500 | - | - | - | - | - | - |
| BP_m1937mortar_Deployable (1) | 420 | 0.3 | 0.25 (d1/i0/r1) | - | 0.7 (d1/i0.2/r1) | 1 (d1/i0.2/r1) | - |
| IMF_hab (1) | 400 | 0.01 | 0.031579 | 0.008 | 0.1 | 0.003125 | - |
| MEI_Hab (1) | 300 | 0.01 | 0.031579 | 0.008 | 0.1 | 0.003125 | - |

Notes. The FOB radios (`/Game/Gameplay/Deployables/Radios/<faction>/BP_FOBRadio_*`, parent `BP_BaseFobCreator`, parent
`/Game/Gameplay/FOBs/BP_ForwardBase`) have 300 health and the row "BP_FOBRadio_AFU" in the table; the insurgent
radio `BP_FobRadio_INS` has HAT 1.0 instead of 0.1. `DirectHitRadialDamageMultiplier` is 0 for the ammunition crates, the DShK, the hedgehog and the test ladders. The indirect-fire
shelters (`BP_Indirect_Mortar_Shelter*`, 450 health) take 0 from fragmentation and 0.001 from HEAT, HAT and explosives: practically
indestructible by shells. `SQDamageType_Thermite` is a native class. Classes whose table is empty
(`BP_Deployable`, `BP_SmartDeployable`, `BP_BaseFobCreator`, the command tents, the helicopter pad, `BP_Ammocrate_AFU`):
the data has a health but no damage-type table, so what damages them is UNVERIFIED and they are not in SquadCalc's data.

## 3. Ammunition: damage fields (VERIFIED values, from the projectile Blueprints of the weapons in `weapons.js`)

Lengths in metres (the assets are in centimetres), merged along each Blueprint's `Super` chain
(`tools/game_ballistics/resolve.py`). `*` = a field the Blueprint does not override, taken from the C++ default that
`tools/game_ballistics/gamecheck.py` (`NATIVE_EXPLOSION`) infers (115 damage, 5-15 m, falloff 1): INFERRED for that
field only. "none" = no explosion field in the asset (AP rounds, machine guns): they do not explode and their bullet
damage is not in the projectile asset, so no structure damage is computed for them (consistent with the owner's
statement that AP does not damage structures).

| projectile | damage type | direct hit | explosion (dmg, inner-outer m, falloff) | secondary (type) | used by |
|---|---|---|---|---|---|
| BP_30mm_VOG19_Proj | BasicHeat | 60 | 115, 1.5-18, 1 * | - | AGS-17 · emplacement |
| BP_35MM_Proj_QLZ87_HEDP | BasicHeat | 60 | 115, 1-11, 1 * | - | QLZ87 |
| BP_40MM_MK19_Proj | BasicHeat | 60 | 115, 1-15, 1 * | - | MK19; MK19 · emplacement / C16 / L134A1 |
| BP_40MM_Proj2 | BasicHeat | 60 | 115, 1-15, 1 * | - | AK-40GL (MPT-76); M203 / M320 / GP-25 / HK79 / SL40; ... |
| BP_40MM_VOG_Proj2 | Fragmentation | 10 | 115, 1-15, 1 * | - | M203 / M320 / GP-25 / HK79 / SL40; QLG10 |
| BP_AGS30_40MM_VOG_Proj | Fragmentation | 10 | 115, 1-15, 1 * | - | AGS-30 / BTR-4 AGS |
| BP_AT4_Rocket_Proj2 | BasicHeat | 960 | 115, 1.5-7.5, 1 * | - | AT-4 |
| BP_BM21_Rocket_Proj2 | HAT | 1200 | 250, 2-10, 1 | 140, 1-35, 1 (Fragmentation) | BM-21 Grad |
| BP_FFV441D_Rocket_Proj | Fragmentation | 960 | 250, 4-16, 1 * | - | Carl Gustav M2 · FFV441D HE |
| BP_FFV551_Rocket_Proj2 | BasicHeat | 960 | 130, 2-8, 1 * | - | Carl Gustav M2 · FFV551 HEAT |
| BP_FFV751_Tandem_Heat_Proj2 | HAT | 1400 | 200, 2-8, 0 * | - | Carl Gustav M2 · FFV751 Tandem |
| BP_M3MAAWS_Heat_Proj2 | BasicHeat | 960 | 130, 2-8, 1 * | - | M3 MAAWS · HEAT / Smoke |
| BP_M3MAAWS_Smoke_Proj2 | - | 100 | 0, 0-0, 2 * | - | M3 MAAWS · HEAT / Smoke |
| BP_M3MAAWS_Tandem_Heat_Proj2 | HAT | 1400 | 200, 2-10, 2 * | - | M3 MAAWS · Tandem |
| BP_M72A5_Rocket_Proj | BasicHeat | 960 | 100, 1.5-7.5, 1 * | - | M72A7 LAW / RPG-26 |
| BP_M72A7_Rocket_Proj2 | BasicHeat | 960 | 100, 1.5-7.5, 1 * | - | M72A7 LAW / RPG-26 |
| BP_Mortarround4 | Fragmentation | 10 | 350, 0-40, 7 | 250, 1-6, 3.5 (Explosives_) | Mortar (M252 / 2B14 / L16 / Type 63); Technical Mortar |
| BP_Mortarround_120mm | Fragmentation | 10 | 400, 0-40, 7 | 375, 1.5-10, 3.5 (Explosives_) | M1064 M121 (120mm) |
| BP_Mortarround_120mm_Airburst | Fragmentation | 0 | 0, 0-20, 7 | 100, 10-60, 1.3 (Fragmentation) | M1064 M121 (120mm) |
| BP_NLAW_Proj | HAT | 1400 | 200, 2-8, 1 * | - | NLAW |
| BP_PF-98_HE_Proj | BasicHeat | 960 | 200, 7-20, 2 * | - | PF98 · HE-I |
| BP_PF-98_Tandem_Proj | HAT | 1400 | 200, 2-8, 0 * | - | PF98 · Tandem |
| BP_Projectile_100mm_Frag | Fragmentation | 200 | 300, 4-35, 5 * | - | 2A70 100mm (BMP-3 / BMD-4 / ZBD04A) · FRAG |
| BP_Projectile_105mm_AP | Kinetic | - | none | - | ZPL-98A 105mm (ZTD-05) · AP |
| BP_Projectile_115mm_HEAT | BasicHeat | 1900 | 200, 3.5-16, 2 * | - | Tank HEAT/HE · M256 / Rh120 / 2A46 / ZPT98 / 2A20 / M68A2; ZPL-98A 105mm (ZTD-05) · HEAT / HE |
| BP_Projectile_120mm_AP | Kinetic | - | none | - | Tank AP · 2A46 / ZPT98 / 2A20 / 2A45 / KBA3; Tank AP · L30A1 (Challenger 2) / M68A2; ... |
| BP_Projectile_120mm_HEAT | BasicHeat | 1900 | 200, 7-20, 2 * | - | Tank HEAT/HE · M256 / Rh120 / 2A46 / ZPT98 / 2A20 / M68A2; Tank HESH · L30A1 (Challenger 2) |
| BP_Projectile_120mm_Smoke | Kinetic | 100 | 150, 2-10, 1 * | - | Tank HESH · L30A1 (Challenger 2) |
| BP_Projectile_125mm_Frag | Fragmentation | 200 | 300, 4-35, 5 * | - | Tank HEAT/HE · M256 / Rh120 / 2A46 / ZPT98 / 2A20 / M68A2; ZPL-98A 105mm (ZTD-05) · HEAT / HE |
| BP_Projectile_125mm_HEAT | BasicHeat | 1900 | 200, 3.5-16, 2 * | - | Tank HEAT/HE · M256 / Rh120 / 2A46 / ZPT98 / 2A20 / M68A2 |
| BP_Projectile_14_5mm | Kinetic | - | none | - | KPVT 14.5mm |
| BP_Projectile_30mm_AP | Kinetic | - | none | - | 2A42 / 2A72 30mm · AP; 2A72 30mm (BMP-3M) · AP / HE; ... |
| BP_Projectile_30mm_HE | Fragmentation | 100 | 125, 1-7.5, 2 * | - | 2A42 30mm (BMP-2) · HE; 2A72 30mm (BMD-4M) · HE; ... |
| BP_Projectile_30mm_HE_Red_Rarden | Fragmentation | 100 | 125, 1-7.5, 2 * | - | L21A1 RARDEN 30mm · HE |
| BP_Projectile_40mm_GPR | Fragmentation | 100 | 175, 1-12.5, 2 * | - | CTAS40 40mm · GP |
| BP_Projectile_50cal | Kinetic | - | none | - | DShK-M; M2A1 .50; ... |
| BP_Projectile_50cal_ACOG | Kinetic | - | none | - | Kord · SPP emplacement; M2A1 .50 · ACOG emplacement |
| BP_Projectile_76mm_Frag | Fragmentation | 100 | 200, 2-16, 1 * | - | ZiS-3 |
| BP_Projectile_76mm_HEAT | BasicHeat | 1900 | 200, 3.5-16, 2 * | - | ZiS-3 |
| BP_Projectile_Hell_Cannon | Fragmentation | 100 | 125, 1-50, 1 | 450, 3-10, 3.5 (Explosives_) | Hell Cannon |
| BP_Projectile_RifleGrenade_FNFAL_Frag | Fragmentation | 0 | 250, 4-18, 1 * | - | Rifle grenade |
| BP_Projectile_RifleGrenade_FNFAL_HEAT | BasicHeat | 900 | 130, 2-8, 1 * | - | Rifle grenade |
| BP_RPG26_Rocket_Proj2 | BasicHeat | 960 | 115, 1.5-7.5, 1 * | - | M72A7 LAW / RPG-26 |
| BP_RPG29_Tandem_Heat_Proj2 | HAT | 1400 | 200, 2-8, 1 * | - | RPG-29 |
| BP_RPG7_Frag_Proj2 | Fragmentation | 10 | 250, 2-16, 1 * | - | RPG-7 · PG-7V HEAT / OG-7V; RPG-7V1 · HEAT |
| BP_RPG7_Heat_Proj2 | BasicHeat | 960 | 130, 2-8, 1 * | - | RPG-7 · PG-7V HEAT / OG-7V; RPG-7V1 · HEAT |
| BP_RPG7_Tandem_Heat_Proj2 | HAT | 1400 | 200, 2-10, 2 * | - | RPG-7 · PG-7VR Tandem |
| BP_RPG7_Thermo_Proj2 | Fragmentation | 240 | 200, 8-24, 2 * | - | RPG-7 · TBG-7V Thermobaric |
| BP_S5_Proj2 | BasicHeat | 250 | 115, 5-18, 1 * | - | Technical UB-32; UB-32 (S-5 rockets) |
| BP_SMAW_Heat_Proj2 | BasicHeat | 960 | 200, 2-8, 1 * | - | MK153 SMAW |
| BP_SMAW_Tandem_Heat_Proj2 | HAT | 1400 | 80, 2-8, 0 * | - | MK153 SMAW |
| BP_SPG9_og9v_Frag_Proj2 | Fragmentation | 100 | 200, 2-16, 1 * | - | 2A28 Grom (BMP-1 / BMD-1) · FRAG; SPG-9 · FRAG |
| BP_SPG9_pg9v_Heat_Proj2 | BasicHeat | 1800 | 100, 2-8, 1 * | - | 2A28 Grom (BMP-1 / BMD-1) · HEAT; SPG-9 · HEAT |

Also in the assets and not used by the calculation: `ExplosiveMinimumDamage`, `ExplosiveKillZoneRadius` (soldier
damage), `ArmorPenetrationDepthMillimeters` and `TraceDistanceAfterPenetrationMeters` (bullet penetration),
`SpecificImpactEffects` (a table keyed by physical material that holds only particles, sounds and decals).

## 4. The calculation (INFERRED combination of VERIFIED fields)

For a structure with `maxHealth` and a table entry `t` for the shell's damage type (`modifier`, `direct`, `indirect`,
`directRadial`), and `R(d)` the radial damage at distance `d` (full inside the inner radius, then
`damage * (1 - (d - inner) / (outer - inner)) ^ falloff`, zero beyond the outer radius: the same law SquadCalc uses
for soldiers, `squadDamage.js damageAtDistance`):

* direct hit on the structure: `impact * t.modifier * t.direct + R(d) * t.modifier * t.directRadial`
* near miss: `R(d) * t.modifier * t.indirect`
* plus the same radial term for the secondary explosion, with the modifier of the secondary's own damage type
* a damage type not in the table: nothing (INFERRED from the name `AllowableDamageTypes`)

Why INFERRED: the property names and their values (modifier 0.01 for fragmentation against HESCO, 0.25 for explosives,
1.0-1.75 for HEAT/HAT against the ammo crate, whose `DirectHitRadialDamageMultiplier` of 0 stops the radial damage
from doubling the direct hit) fit this reading, but the C++ that applies them is not in the paks and no in-game
measurement of structure health was made (the in-game tests were cancelled by the owner). UNVERIFIED: the distance
the game measures to a structure (nearest collision point or origin), whether the secondary explosion damages a
deployable the same way as a "mesh" (`SecondaryOnlyDamageMeshes`), health regeneration or repair, the build state's
effect on damage, and what `bForwardDamageToSoldier` does when a shell hits an emplacement with a gunner.

Implementation: `damageToStructure(structure, ammo, {directHit, distance, secondary})` returns the damage by part and
`shellsToDestroy(...)` the whole shells from full health (Infinity when the damage type is not listed). Pure
functions, no UI, not wired into the map yet. `findStructure(className)` finds a structure by Blueprint class name.

### Worked example (full health, `shellsToDestroy`)

Mortar round (`BP_Mortarround4`: M252 / 2B14 / L16 / Type 63) on a direct hit against the FOB radio (300 health):
impact 10 * 0.1 (Frag) = 1, explosion 350 * 0.1 = 35, secondary 250 * 0.5 (Explosives on the radio) = 125, total 161 per
round, so **2 rounds**. Against a HAB (500): 0.1 + 3.5 + 25 = 28.6 per round, **18 rounds**. Against a HESCO barrier (200):
0.1 + 3.5 + 62.5 = 66.1, **4 rounds**. A 125 mm HEAT round (1900 impact) hits a HAB for 1900 * 0.031579 = 60, plus 6.3 of
explosion, 66 in all: **8 rounds**; the same round against a HESCO: 19 + 2, **10 rounds**. A near miss 3 m away needs far more
(HAB: 81 mortar rounds, 80 tank HEAT rounds).

Shells to destroy, direct hit (`distance` 0):

| structure (HP) | Mortar 81/82 mm | Mortar 120 mm | Hell Cannon | UB-32 S-5 | BM-21 | Tank HEAT 125 | Tank HE 125 | RPG-7 HEAT | RPG-7 OG-7V | SPG-9 HEAT | Carl Gustav HE | 40 mm GL HEAT | 30 mm HE | ZiS-3 HEAT |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FOB radio (300) | 2 | 2 | 2 | 17 | 2 | 3 | 6 | 6 | 12 | 4 | 3 | 35 | 14 | 3 |
| HAB (500) | 18 | 13 | 11 | 44 | 39 | 8 | 100 | 15 | 193 | 9 | 42 | 91 | 223 | 8 |
| HESCO barrier (200) | 4 | 3 | 2 | 55 | 3 | 10 | 40 | 19 | 77 | 11 | 17 | 115 | 89 | 10 |
| HESCO wall (420) | 7 | 5 | 4 | 116 | 6 | 20 | 84 | 39 | 162 | 23 | 35 | 240 | 187 | 20 |
| Sandbag wall (250) | 9 | 7 | 8 | 7 | 1 | 2 | 10 | 3 | 20 | 2 | 5 | 15 | 23 | 2 |
| Small bunker (500) | 8 | 6 | 5 | 137 | 7 | 24 | 100 | 46 | 193 | 27 | 42 | 286 | 223 | 24 |
| M2 bunker (600) | 10 | 7 | 6 | 165 | 9 | 29 | 120 | 56 | 231 | 32 | 50 | 343 | 267 | 29 |
| Observation tower (800) | 13 | 9 | 7 | 220 | 51 | 39 | 160 | 74 | 308 | 43 | 67 | 458 | 356 | 39 |
| Razorwire (100) | 4 | 3 | 3 | 28 | 2 | 5 | 20 | 10 | 39 | 6 | 9 | 58 | 45 | 5 |
| Concrete barrier (160) | 3 | 2 | 2 | 15 | 3 | 3 | 11 | 5 | 21 | 3 | 5 | 31 | 24 | 3 |
| Vehicle repair station (500) | 3 | 2 | 2 | 14 | 2 | 3 | 5 | 5 | 10 | 3 | 3 | 29 | 12 | 3 |
| Mortar emplacement (420) | 2 | 1 | 1 | 5 | 10 | 1 | 3 | 2 | 6 | 1 | 2 | 10 | 7 | 1 |

Classes used: `BP_FOBRadio_Woodland`, `US_Hab_Desert`, `BP_Hesco_USA_Desert`, `BP_HescoWall_DesertCam`,
`BP_SandBagWall_2`, `BP_smallbunker_Desert`, `BP_M2_BAF_Bunker_Desert`, `BP_ObservationTower_ADF_Desert`,
`BP_Razorwire_clean_2`, `BP_ConcreteBarrier`, `BP_vehicle_repair_ADF_Desert`, `BP_m252mortar_Deployable`. The full
matrix (any class, any distance) is `shellsToDestroy` over `STRUCTURES` x `AMMO`. These counts hold only as far as
section 4's combination does (INFERRED).

## 5. Material of each structure (VERIFIED)

`data/structure_damage.json` lists, per deployable, the static meshes under its `Completed` scene component and the
share of render triangles per physical material (mesh slot material, or the component's `OverrideMaterials` instance
with its parent chain). Examples: FOB radio `PhysMat_MetalThin` 76 %, `PhysMat_Sandbag` 24 %; HAB (`SM_US_HAB`)
`PhysMat_Dirt` 42 %, `PhysMat_Rock_Deployable` 41 %, `PhysMat_Sandbag` 14 %, `PhysMat_WoodSolid` 3 %; HESCO
(`SM_Hesco_V3_1_Deployable`) `PhysMat_Dirt` 66 %, `PhysMat_Rock_Deployable` 34 %; sandbag wall `PhysMat_Sandbag` 100 %;
observation tower `PhysMat_Rock_Deployable` 79 %. Mortar/AA emplacements are skeletal meshes: not resolved here (22 of 235
classes have no resolved mesh material).

| material | damage_absorbed | armor_thickness_mm | allow_penetration |
|---|---|---|---|
| PhysMat_Sandbag | 120 | 12 | true |
| PhysMat_Rock_Deployable (HESCO fill, bunker walls) | not set | 100 | true |
| PhysMat_Dirt | not set | 5000 | true |
| PhysMat_Concrete | 120 | 10 | not set |
| PhysMat_WoodSolid | 30 | 3 | true |
| PhysMat_MetalThin | 20 | 1 | true |
| PhysMat_Razorwire | 5 | not set | true |

(`data/materials.json`; "not set" = absent from the asset, i.e. the native default.) These values describe how much a
**bullet** loses passing a surface. Nothing connects them to explosion damage on structures (section 6), and the
structure multipliers do not follow them: sandbag (damage_absorbed 120) takes 0.05 of fragmentation, HESCO (dirt and rock)
0.01, a metal tripod 0.3.

## 6. What the data does not contain (VERIFIED absences)

* No link from `AllowableDamageTypes`, the damage-type Blueprints (`/Game/Gameplay/DamageTypes/BP_*`, no overridden
  properties) or the projectile Blueprints to a physical material: the projectile property list is `DamageTypeToApply,
  ImpactDamageToApply, Explosive*, Secondary*, ArmorPenetrationDepthMillimeters, TraceDistanceAfterPenetrationMeters,
  SpecificImpactEffects (cosmetic), ...`; `lethality_modifier` and `splash_radius_modifier` do not exist (`materials.json`).
* No per-material structure damage multiplier, and no separate "structure damage" or "vehicle damage" multiplier in the
  damage types or projectiles beyond the per-structure table above.
* The way `Modifier` and the three multipliers are combined, the distance used for a structure, and the damage of
  AP and machine-gun bullets to structures (bullet damage is in the weapon, not in the projectile asset): native code or
  other assets, UNVERIFIED. Not needed for the owner's HE/HEAT question except the combination.

## 7. Reading B and map buildings

**Map buildings (static meshes).** Not destructible in the server data: the export inventory of all levels
(`~/data/semantics/inventory_maps.json`, 3398 levels) has no destructible or geometry-collection component type and no health
on static mesh actors; the only destructible actors are `BP_Coop_Destructable_C` (5), `_AmmoCache_C` (78), `_MortarCache_C` (10),
`_AAGun_C` (3), `Destructable_RadioSet_C` (3, tutorial). Static buildings are rigid collision (collision-semantics.md
section 3), so no shell damages them. VERIFIED. Coop destructibles (`/Game/Coop/Blueprints/BP_Coop_Destructable`,
`_AAGun` 150 health, `_AmmoCache` 100, `_MortarCache` 125, `BP_HedgehogTankTrap_Coop` 150, `BP_Tirefire_Coop` 200) have a
`Health` and, for the caches, an explosion on death (`ExplosionBaseDamage` 200, 5-25 m); no damage-type table: how shells
damage them is UNVERIFIED.

**Attenuation of explosion damage by a wall for a player behind it.** The game data has no material-based reduction:
no field in the projectile, damage type or physical material assets scales explosion damage by what lies between
explosion and soldier (`damage_absorbed` and `armor_thickness_mm` are read for bullets, section 5). What exists is a
binary rule of the engine, `UGameplayStatics::ApplyRadialDamage` visibility (a component is damaged only if a trace
from the explosion reaches it): SquadCalc already models it as cover in `squadDamage.js isCovered` (INFERRED, existing).
Nothing in the data supports a per-material attenuation, so none was implemented.

## 8. Reproduction

Extractor: `tools/heightmaps/extractor` modes `list` and `dumpall` (and `tools/volumetric/extractor` `meshsections`),
dedicated-server package only. Work dir `~/data/structdmg` (outside the repo), memory capped at 3 GB per container.

| Result | Command |
|---|---|
| Every pak path | `SquadExtract <paks> list ""` > `files.txt` |
| Deployable, FOB, damage-type Blueprints | `dumpall 'Content/Gameplay/(DamageTypes\|Deployables)/\|Gameplay/FOBs/\|Coop/Blueprints/BP_(Coop_Destr\|Hedgehog\|Tirefire)' dump` |
| Projectile Blueprints | the `dump` of `tools/game_ballistics` (README) merged into the same directory |
| Mesh and override materials | `python3 structure_damage.py meshes dump files.txt out`, then `meshsections out/meshes.txt sections.ndjson` and `dumpall` of `out/materials.txt` and their parent instances |
| Data file | `python3 structure_damage.py build dump files.txt sections.ndjson ../data/materials.json ballistics.json ../data/structure_damage.json` |
| SquadCalc data module | `python3 structure_damage.py export ../data/structure_damage.json <SquadCalc>/src/data/structureDamage.js` |
| Calculation tests | `npm test` in SquadCalc (`tests/structureDamage.test.mjs`) |
