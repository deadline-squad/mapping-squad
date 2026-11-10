# Damage of shells to structures (Squad build 26005357)

Question (owner, 2026-11-04, plan item C7 of deadline-squad/deadline-squadcalc#22): how much damage do shells do to
**the structures players build** (FOB radio, HAB, and what is built at them: HESCO, sandbags, bunkers, emplacements,
wire), by material and by ammunition. Armour-piercing rounds are not fired at structures and no penetration
calculation is wanted.

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
   The way the game combines the fields is native code, now read from the server binary (section 4,
   [`native-rules.md`](native-rules.md)): the combination is VERIFIED from the code (section 4) and implemented in SquadCalc 45.25.0, except the
   Blueprint-driven impact damage and secondary explosion (INFERRED); it has not been measured in game.

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
`tools/game_ballistics/gamecheck.py` (`NATIVE_EXPLOSION`) infers (115 damage, 5-15 m, falloff 1): this was INFERRED, since read from the constructor of the native projectile class (native-rules.md 1.3) and VERIFIED for that
field only. "none" = no explosion field in the asset (AP rounds, machine guns): they do not explode and their bullet
damage is not in the projectile asset, so no structure damage is computed for them (consistent with the owner's
statement that AP does not damage structures).

| projectile | damage type | direct hit | explosion (dmg, inner-outer m, falloff) | secondary (type) | used by |
|---|---|---|---|---|---|
| BP_30mm_VOG19_Proj | BasicHeat | 60 | 115, 1.5-18, 1 * | - | AGS-17 · emplacement · optic (RMB ×2.5) |
| BP_35MM_Proj_QLZ87_HEDP | BasicHeat | 60 | 115, 1-11, 1 * | - | QLZ87 · optic (RMB ×3) |
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
| BP_Projectile_115mm_HEAT | BasicHeat | 1900 | 200, 3.5-16, 2 * | - | Tank HEAT/HE · T-62 (2A20); ZPL-98A 105mm (ZTD-05) · HEAT / HE |
| BP_Projectile_120mm_AP | Kinetic | - | none | - | Tank AP · L30A1 (Challenger 2) / M68A2; Tank AP · M256 / Rh120; ... |
| BP_Projectile_120mm_HEAT | BasicHeat | 1900 | 200, 7-20, 2 * | - | Tank HEAT/HE · Leopard 2A6 (Rh120); Tank HEAT/HE · M1128 MGS (M68A2); ... |
| BP_Projectile_120mm_Smoke | Kinetic | 100 | 150, 2-10, 1 * | - | Tank HESH · L30A1 (Challenger 2) |
| BP_Projectile_125mm_Frag | Fragmentation | 200 | 300, 4-35, 5 * | - | Tank HEAT/HE · M60T (MG253); Tank HEAT/HE · T-72 (2A46); ... |
| BP_Projectile_125mm_HEAT | BasicHeat | 1900 | 200, 3.5-16, 2 * | - | Tank HEAT/HE · T-72 (2A46); Tank HEAT/HE · ZTZ-99 (ZPT-98) |
| BP_Projectile_14_5mm | Kinetic | - | none | - | KPVT 14.5mm |
| BP_Projectile_30mm_AP | Kinetic | - | none | - | 2A42 / 2A72 30mm · AP; 2A72 30mm (BMP-3M) · AP / HE; ... |
| BP_Projectile_30mm_HE | Fragmentation | 100 | 125, 1-7.5, 2 * | - | 2A42 30mm (BMP-2) · HE; 2A72 30mm (BMD-4M) · HE; ... |
| BP_Projectile_30mm_HE_Red_Rarden | Fragmentation | 100 | 125, 1-7.5, 2 * | - | L21A1 RARDEN 30mm · HE |
| BP_Projectile_40mm_GPR | Fragmentation | 100 | 175, 1-12.5, 2 * | - | CTAS40 40mm · GP |
| BP_Projectile_50cal | Kinetic | - | none | - | DShK-M; M2A1 .50; ... |
| BP_Projectile_50cal_ACOG | Kinetic | - | none | - | Kord · SPP emplacement; M2A1 .50 · ACOG emplacement |
| BP_Projectile_76mm_Frag | Fragmentation | 100 | 200, 2-16, 1 * | - | ZiS-3 · optic (RMB ×4) |
| BP_Projectile_76mm_HEAT | BasicHeat | 1900 | 200, 3.5-16, 2 * | - | ZiS-3 · optic (RMB ×4) |
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

## 4. The calculation (VERIFIED from the server binary, see `native-rules.md`; implemented in SquadCalc 45.25.0)

For a deployable (`ASQDeployable::TakeDamage`, 0xa4970d0, and the engine's radial damage, [`native-rules.md`](native-rules.md)
section 1; the instruction bytes are pinned by `tests/test_native_rules.py`). `t` is the structure's entry for the shell's
damage type (`modifier`, `direct`, `indirect`, `onlyDirect`), `scale(d)` the engine's falloff law (1 up to the inner radius,
`(1 - (d - inner) / (outer - inner)) ^ falloff` up to the outer radius, 0 beyond; `squadDamage.js damageAtDistance`):

* the first `AllowableDamageTypes` element whose class equals the damage type class **exactly** is used (no parent walk); no
  element = no health change;
* radial event (the explosion): `loss = Lerp(Min, Base * t.modifier * m, scale(d))` with `m = t.direct` on a direct hit and
  `t.indirect` otherwise (0 on a near miss when `t.onlyDirect`); `Min` is the projectile's `ExplosiveMinimumDamage`, applied
  after and **not multiplied by the modifier**; a structure outside the outer radius is not in the burst at all;
* point event (the direct hit's impact): `loss = ImpactDamageToApply * t.modifier`, no hit multiplier;
* `DirectHitRadialDamageMultiplier` is not read by deployables (only by vehicles and emplaced guns); the app's data no longer carries it;
* `Health = clamp(Health - loss, 0, MaxHealth)`, so the shells to destroy are `ceil(MaxHealth / loss)`;
* `d`: the explosion origin is the impact point moved `ExplosiveDamageDistanceFromImpactNormal` along the impact normal. A
  direct hit therefore bursts that far off the struck surface (`d` = that distance); a near miss on level ground has a vertical
  normal, so `d = hypot(distance on the ground, that distance)`, with the structure taken at ground level (an approximation of
  the ray distance of native-rules.md section 3, which needs the structure's collision; occlusion is not modelled);
* the secondary explosion (mortar family, Hell Cannon, BM-21) is one more radial event with the modifier of its own damage type, its own
  `SecondaryExplosionMinDamage` and distance.

**Known deviation of the app (SquadCalc 45.27.0).** The engine's `InternalTakeRadialDamage` returns `Lerp(Min, Damage, scale)` with
`scale = 0` at and beyond the outer radius ([`native-rules.md`](native-rules.md) 1.2), i.e. `Min`, not 0. Which structures it is called for
is decided on the distance from the burst to the structure's collision (box), while `d` in the formula is the distance to the closest
point the ray hit on its components. A structure whose box is inside the outer radius but whose ray hit point is beyond it therefore takes
`Min` in the game. The app has neither collision nor ray, only the ground distance, and returns 0 for `reach >= outer`; for the ten
projectiles with `Min > 0` ([`native-rules.md`](native-rules.md) section 5) the game can deal up to `Min` (125 mm HEAT: 35) where the app shows nothing, at the edge of the
radius. Kept as is: the case needs the structure's collision shape, which the data does not hold, and no in-game measurement exists.

INFERRED (Blueprint bytecode, not in the binary): that a direct hit's `ImpactDamageToApply` is point damage of the projectile's
damage type, and the secondary explosion's path to `TakeDamage`. Still UNVERIFIED: which actor class the emplaced guns' shells hit,
health regeneration or repair, `bForwardDamageToSoldier`. No in-game measurement exists (native-rules.md section 6).

What changed in the app against the earlier INFERRED form (45.24.0): the radial part of a direct hit used `directRadial` (zero on
ammunition crates, so a crate took no radial damage; now full) and the impact term was multiplied by `direct`; `ExplosiveMinimumDamage`
was ignored (ten projectiles have it > 0: 125 mm HEAT 35, which now makes a near miss at 10 m cost a HESCO barrier 27 health, not 0.5);
a near miss of an `onlyDirect` type was not zero; the burst distance ignored `distanceFromImpact` (1 m for the mortar round, so a direct
hit took 84 % of the explosion, not 100 %).

Implementation: `damageToStructure(structure, ammo, {directHit, distance, secondary})` returns the damage by part and
`shellsToDestroy(...)` the whole shells from full health (Infinity when the damage type is not listed or nothing is lost). Pure
functions; `findStructure(className)` finds a structure by Blueprint class name. The data (`src/data/structureDamage.js`) is
regenerated with `python3 semantics/structure_damage.py export data/structure_damage.json <SquadCalc>/src/data/structureDamage.js`
(adds `minimum` and `onlyDirect`, drops `directRadial`; structures with identical health and used fields share an entry).

### Worked example (full health, `shellsToDestroy`)

Mortar round (`BP_Mortarround4`: M252 / 2B14 / L16 / Type 63) on a direct hit against the FOB radio (300 health):
impact 10 * 0.1 (Frag) = 1, explosion 350 * 0.1 * 0.838 (1 m off the surface, `(1 - 1/40)^7`) = 29.3, secondary 250 * 0.5 (Explosives on the
radio, 0.5 m, inside its inner radius) = 125, total 155.3 per round, so **2 rounds**. Against a HAB (500): 0.1 + 2.9 + 25 = 28.0, **18 rounds**.
Against a HESCO barrier (200): 0.1 + 2.9 + 62.5 = 65.5, **4 rounds**. A 125 mm HEAT round (1900 impact) hits a HAB for 1900 * 0.031579 = 60, plus 6.3 of
explosion, 66 in all: **8 rounds**; the same round against a HESCO: 19 + 2, **10 rounds**.

Shells to destroy, old form (45.24.0) against native rules (45.25.0), full health, one shell per count:

| shell, structure | direct hit | 3 m | 5 m | 10 m |
|---|---|---|---|---|
| mortar, FOB radio | 2 / 2 | 8 / 8 | 22 / 22 | 65 / 65 |
| mortar, HAB | 18 / 18 | 81 / 85 | 342 / 350 | 1071 / 1083 |
| mortar, HESCO barrier | 4 / 4 | 17 / 17 | 126 / 129 | 429 / 434 |
| 125 mm HEAT, FOB radio | 3 / 3 | 30 / 30 | 39 / 20 | 131 / 11 |
| 125 mm HEAT, HAB | 8 / 8 | 80 / 80 | 103 / 40 | 344 / 18 |
| 125 mm HEAT, HESCO barrier | 10 / 10 | 100 / 100 | 130 / 22 | 435 / 8 |

(old / new). The HEAT near misses fall because `Min` 35 is a floor of its own beyond the 3.5 m inner radius.

Shells to destroy, direct hit (native rules):

| structure (HP) | Mortar 81/82 mm | Mortar 120 mm | Hell Cannon | UB-32 S-5 | BM-21 | Tank HEAT 125 | Tank HE 125 | RPG-7 HEAT | RPG-7 OG-7V | SPG-9 HEAT | Carl Gustav HE | 40 mm GL HEAT | 30 mm HE | ZiS-3 HEAT |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FOB radio (300) | 2 | 2 | 2 | 17 | 2 | 3 | 6 | 6 | 12 | 4 | 3 | 35 | 14 | 3 |
| HAB (500) | 18 | 13 | 11 | 44 | 39 | 8 | 100 | 15 | 193 | 9 | 42 | 91 | 223 | 8 |
| HESCO barrier (200) | 4 | 3 | 2 | 55 | 3 | 10 | 40 | 19 | 77 | 11 | 17 | 115 | 89 | 10 |
| HESCO wall (420) | 7 | 5 | 4 | 116 | 6 | 20 | 84 | 39 | 162 | 23 | 35 | 240 | 187 | 20 |
| Sandbag wall (250) | 10 | 7 | 8 | 7 | 1 | 2 | 10 | 3 | 20 | 2 | 5 | 15 | 23 | 2 |
| Small bunker (500) | 8 | 6 | 5 | 137 | 7 | 24 | 100 | 46 | 193 | 27 | 42 | 286 | 223 | 24 |
| M2 bunker (600) | 10 | 7 | 6 | 165 | 9 | 29 | 120 | 56 | 231 | 32 | 50 | 343 | 267 | 29 |
| Observation tower (800) | 13 | 9 | 7 | 220 | 50 | 39 | 160 | 74 | 308 | 43 | 67 | 458 | 356 | 39 |
| Razorwire (100) | 4 | 3 | 3 | 28 | 2 | 5 | 20 | 10 | 39 | 6 | 9 | 58 | 45 | 5 |
| Concrete barrier (160) | 3 | 2 | 2 | 15 | 3 | 3 | 11 | 5 | 21 | 3 | 5 | 31 | 24 | 3 |
| Vehicle repair station (500) | 3 | 2 | 2 | 14 | 2 | 3 | 5 | 5 | 10 | 3 | 3 | 29 | 12 | 3 |
| Mortar emplacement (420) | 2 | 1 | 1 | 5 | 11 | 1 | 3 | 2 | 6 | 1 | 2 | 10 | 7 | 1 |

Classes used: `BP_FOBRadio_Woodland`, `US_Hab_Desert`, `BP_Hesco_USA_Desert`, `BP_HescoWall_DesertCam`,
`BP_SandBagWall_2`, `BP_smallbunker_Desert`, `BP_M2_BAF_Bunker_Desert`, `BP_ObservationTower_ADF_Desert`,
`BP_Razorwire_clean_2`, `BP_ConcreteBarrier`, `BP_vehicle_repair_ADF_Desert`, `BP_m252mortar_Deployable`. The full
matrix (any class, any distance) is `shellsToDestroy` over `STRUCTURES` x `AMMO`.

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
* The way `Modifier` and the three multipliers are combined and the distance used for a structure were native code: now read
  from the binary (section 4, native-rules.md). The damage of AP and machine-gun bullets to structures (bullet damage is in the
  weapon, not in the projectile asset) remains UNVERIFIED. Not needed for the owner's HE/HEAT question.

## 6b. In the SquadCalc UI (45.24.0, C7b; native rules since 45.25.0)

* Clicking a deployable marker (FOB radio, HAB, mortar, HMG, GMG, AA gun, ammo crate, repair station) opens a popup with
  the shells of the selected ammunition that destroy the structure from full health; the target dialog shows the same line
  for a target within 5 m of such a marker (`src/js/structureInfo.js`). Each count is `shellsToDestroy` with a direct hit
  when the burst is within 1 m of the structure (`DIRECT_HIT_RADIUS`), else a near miss at the distance; one shell per count,
  each landing where aimed, the spread is not included. The tooltip of the row says the combination is the game's, read from the
  server code, except the direct hit's impact damage and the mortars' secondary explosion (INFERRED); nothing is measured in game.
* The link from an app shell to a projectile is `src/data/structureLinks.js` (`SHELL_AMMO`: weapon name / shell name ->
  projectile of this document's section 3; `MARKER_STRUCTURES`: marker icon -> structure class). It was found by the weapon's
  ballistics label, then by the shell's explosion (damage, radii, falloff) against the projectile's, and kept only where the
  candidates agree on damage type, impact damage and secondary explosion; `tests/structureDamage.test.mjs` checks every entry
  and lists the 22 shells without one (howitzers, rocket artillery, modded weapons, the 40 mm grenades that fit two
  projectiles, three tank HE shells and the C90-CR, DZJ-08, RPG-28 and Type 63 whose class is not named in the data). Nothing
  is shown for them.
* A shell that does not explode (AP, APFSDS, machine guns: `explosionRadius [0, 0]`) says "no structure damage", which is
  what the data gives (impact damage 0 for every kinetic projectile, section 3); so does a shell whose damage type the
  structure does not list.
* HAB markers are the 500-health HAB most factions build (the IMF and MEI ones have 400 and 300); the marker has no
  faction. Markers without a table in the data (helipad, anti-tank, UB-32, Hell Cannon) show nothing.
* Browser check: `tools/browser_check/targets_check.mjs`.

## 7. Reproduction

Extractor: `tools/heightmaps/extractor` modes `list` and `dumpall` (and `tools/volumetric/extractor` `meshsections`),
dedicated-server package only. Work dir `~/data/structdmg` (outside the repo), memory capped at 3 GB per container.

| Result | Command |
|---|---|
| Every pak path | `SquadExtract <paks> list ""` > `files.txt` |
| Deployable, FOB, damage-type Blueprints | `dumpall 'Content/Gameplay/(DamageTypes\|Deployables)/\|Gameplay/FOBs/' dump` |
| Projectile Blueprints | the `dump` of `tools/game_ballistics` (README) merged into the same directory |
| Mesh and override materials | `python3 structure_damage.py meshes dump files.txt out`, then `meshsections out/meshes.txt sections.ndjson` and `dumpall` of `out/materials.txt` and their parent instances |
| Data file | `python3 structure_damage.py build dump files.txt sections.ndjson ../data/materials.json ballistics.json ../data/structure_damage.json` |
| SquadCalc data module | `python3 structure_damage.py export ../data/structure_damage.json <SquadCalc>/src/data/structureDamage.js` |
| Calculation tests | `npm test` in SquadCalc (`tests/structureDamage.test.mjs`) |
