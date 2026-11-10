# Урон снарядов по сооружениям (Squad, сборка 26005357)

Вопрос владельца (2026-11-04, пункт C7 плана deadline-squad/deadline-squadcalc#22): сколько урона наносят снаряды
**сооружениям, которые строят игроки** (радио FOB, HAB и то, что строят рядом: HESCO, мешки с песком, бункеры,
позиции, колючая проволока), по материалам и боеприпасам. Бронебойные снаряды по сооружениям не стреляют, расчёт
пробития не нужен.

Метки: **VERIFIED** — прочитано из собранных ассетов серверного пакета (клиентский пак не использовался, ничего не
расшифровывалось и не обходилось); **INFERRED** — следует из проверенных имён и значений полей, но правило их
применения лежит в нативном коде, которого в паках нет; **UNVERIFIED** — нужен тест в игре или исходники движка.
Имена ассетов — пути `/Game/...` серверного пакета. Английская версия: [`structure-damage.md`](structure-damage.md).

## 1. Коротко

1. Здоровье и таблица множителей по типам урона лежат **в Blueprint самого развёртываемого объекта**, а не в материале.
   `MaxHealth`, `InitialHealth` и `AllowableDamageTypes` (список `{DamageTypeClass, Modifier, DirectHitDamageMultiplier,
   IndirectHitDamageMultiplier, DirectHitRadialDamageMultiplier, ...}`) — свойства `/Game/Gameplay/Deployables/BP_Deployable`
   и его потомков. У 227 из 235 Blueprint есть здоровье; групп (здоровье, таблица) 49, из них 45 с таблицей типов урона
   (они есть в SquadCalc). VERIFIED.
2. Blueprint снаряда задаёт тип урона (`DamageTypeToApply`), урон прямого попадания (`ImpactDamageToApply`) и взрыв
   (`ExplosiveBaseDamage`, радиусы, спад); у миномётов, Hell Cannon и БМ-21 есть **вторичный взрыв со своим типом урона**
   (`SecondaryExplosionDamageType`, `SecondaryOnlyDamageMeshes`). VERIFIED. Мины: основной взрыв Fragmentation, вторичный
   **Explosives** (множитель по HESCO в 25 раз больше: 0,25 против 0,01), и именно он даёт большую часть урона мины по сооружениям.
3. Поля физматериалов (`damage_absorbed`, `armor_thickness_mm`, `allow_penetration`) **не связаны с уроном взрыва по
   сооружениям**: ни один ассет сооружения, типа урона или снаряда не ссылается на физматериал для урона (списки полей в
   разделе 6). Они относятся к пробитию пулями. VERIFIED (отсутствие). Материал сооружения известен (раздел 5), но
   «урон по материалу» задан таблицей самого сооружения (HESCO и бункеры: 0,01 осколочный, 0,25 взрывчатка; мешки
   0,05 / 0,05; металлические станки 0,3 / 1,0).
4. Расчёт опирается на данные и реализован: `damageToStructure` и `shellsToDestroy` в SquadCalc
   (`src/js/structureDamage.js`, данные `src/data/structureDamage.js`, `tests/structureDamage.test.mjs`). Как игра
   складывает поля — нативный код; теперь он прочитан из бинарника сервера (раздел 4, [`native-rules.ru.md`](native-rules.ru.md)): сочетание VERIFIED по коду (раздел 4) и реализовано в SquadCalc 45.25.0, кроме урона удара и вторичного взрыва из Blueprint (INFERRED); в игре не измерялось.

## 2. Сооружения: здоровье и множители (значения VERIFIED)

Здоровье — `MaxHealth` (`InitialHealth` — здоровье при установке и начале стройки; радио FOB стартует с полным, HAB 25,
HESCO 5, бункеры 5–20). `HalfBuiltTransitionHealth` / `FullyBuiltTransitionHealth` — доли `MaxHealth` для стадий стройки.
В ячейках `Modifier`; `(d/i/r)` — три множителя попадания, если какой-то не равен 1 (`DirectHitDamageMultiplier`,
`IndirectHitDamageMultiplier`, `DirectHitRadialDamageMultiplier`); `-` — тип урона не перечислен. Группы — в
`data/structure_damage.json` (`deployables`: каждый класс с цепочкой, мешами и материалами). Frag =
`BP_Fragmentation_DamageType`, HEAT = `BP_BasicHeatDamageType`, HAT = `BP_HAT_DamageType`, Explosives =
`BP_Explosives_Damagetype`, Kinetic = `BP_Kinetic_DamageType`.

| первый класс (число классов) | HP | Frag | HEAT | HAT | Explosives | Kinetic | другое |
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

Примечания. Радио FOB (`/Game/Gameplay/Deployables/Radios/<фракция>/BP_FOBRadio_*`, родитель `BP_BaseFobCreator`, его
родитель `/Game/Gameplay/FOBs/BP_ForwardBase`) имеют 300 здоровья (строка «BP_FOBRadio_AFU»); радио повстанцев
`BP_FobRadio_INS` получает HAT 1,0 вместо 0,1. `DirectHitRadialDamageMultiplier` равен 0 у ящиков с боеприпасами, DShK, ежа и
тестовых лестниц. Миномётные укрытия (`BP_Indirect_Mortar_Shelter*`, 450 здоровья) получают 0 от осколочного и 0,001 от HEAT,
HAT и взрывчатки: снарядами практически не разрушаются. `SQDamageType_Thermite` — нативный класс. У классов с пустой
таблицей (`BP_Deployable`, `BP_SmartDeployable`, `BP_BaseFobCreator`, командные палатки, вертолётная площадка,
`BP_Ammocrate_AFU`) есть здоровье, но нет таблицы типов урона: чем их можно повредить, UNVERIFIED, в данные SquadCalc они не вошли.

## 3. Боеприпасы: поля урона (значения VERIFIED, из Blueprint снарядов оружия из `weapons.js`)

Метры (в ассетах сантиметры), значения слиты по цепочке `Super` каждого Blueprint (`tools/game_ballistics/resolve.py`).
`*` — поле, которое Blueprint не переопределяет: взято нативное значение по умолчанию, выведенное
`tools/game_ballistics/gamecheck.py` (`NATIVE_EXPLOSION`: 115 урона, 5–15 м, спад 1); было INFERRED, теперь прочитано из конструктора нативного класса снаряда (native-rules.ru.md 1.3) и VERIFIED только для этого поля.
«нет» — в ассете нет полей взрыва (бронебойные, пулемёты): не взрываются, урон их пуль в ассете снаряда не лежит, поэтому
урон по сооружениям не считается (согласуется с решением владельца, что бронебойные сооружения не повреждают).

| снаряд | тип урона | прямое попадание | взрыв (урон, внутр.-внешн. м, спад) | вторичный (тип) | оружие |
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
| BP_Projectile_105mm_AP | Kinetic | - | нет | - | ZPL-98A 105mm (ZTD-05) · AP |
| BP_Projectile_115mm_HEAT | BasicHeat | 1900 | 200, 3.5-16, 2 * | - | Tank HEAT/HE · T-62 (2A20); ZPL-98A 105mm (ZTD-05) · HEAT / HE |
| BP_Projectile_120mm_AP | Kinetic | - | нет | - | Tank AP · L30A1 (Challenger 2) / M68A2; Tank AP · M256 / Rh120; ... |
| BP_Projectile_120mm_HEAT | BasicHeat | 1900 | 200, 7-20, 2 * | - | Tank HEAT/HE · Leopard 2A6 (Rh120); Tank HEAT/HE · M1128 MGS (M68A2); ... |
| BP_Projectile_120mm_Smoke | Kinetic | 100 | 150, 2-10, 1 * | - | Tank HESH · L30A1 (Challenger 2) |
| BP_Projectile_125mm_Frag | Fragmentation | 200 | 300, 4-35, 5 * | - | Tank HEAT/HE · M60T (MG253); Tank HEAT/HE · T-72 (2A46); ... |
| BP_Projectile_125mm_HEAT | BasicHeat | 1900 | 200, 3.5-16, 2 * | - | Tank HEAT/HE · T-72 (2A46); Tank HEAT/HE · ZTZ-99 (ZPT-98) |
| BP_Projectile_14_5mm | Kinetic | - | нет | - | KPVT 14.5mm |
| BP_Projectile_30mm_AP | Kinetic | - | нет | - | 2A42 / 2A72 30mm · AP; 2A72 30mm (BMP-3M) · AP / HE; ... |
| BP_Projectile_30mm_HE | Fragmentation | 100 | 125, 1-7.5, 2 * | - | 2A42 30mm (BMP-2) · HE; 2A72 30mm (BMD-4M) · HE; ... |
| BP_Projectile_30mm_HE_Red_Rarden | Fragmentation | 100 | 125, 1-7.5, 2 * | - | L21A1 RARDEN 30mm · HE |
| BP_Projectile_40mm_GPR | Fragmentation | 100 | 175, 1-12.5, 2 * | - | CTAS40 40mm · GP |
| BP_Projectile_50cal | Kinetic | - | нет | - | DShK-M; M2A1 .50; ... |
| BP_Projectile_50cal_ACOG | Kinetic | - | нет | - | Kord · SPP emplacement; M2A1 .50 · ACOG emplacement |
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

Есть в ассетах, но не используются в расчёте: `ExplosiveMinimumDamage`, `ExplosiveKillZoneRadius` (урон по солдатам),
`ArmorPenetrationDepthMillimeters` и `TraceDistanceAfterPenetrationMeters` (пробитие пулей), `SpecificImpactEffects`
(таблица по физматериалу, только частицы, звуки и декали).

## 4. Расчёт (VERIFIED по бинарнику сервера, см. `native-rules.ru.md`; реализован в SquadCalc 45.25.0)

Для развёртываемого объекта (`ASQDeployable::TakeDamage`, 0xa4970d0, и радиальный урон движка, [`native-rules.ru.md`](native-rules.ru.md)
раздел 1; байты инструкций закреплены `tests/test_native_rules.py`). `t` - запись сооружения для типа урона снаряда
(`modifier`, `direct`, `indirect`, `onlyDirect`), `scale(d)` - закон спада движка (1 до внутреннего радиуса,
`(1 - (d - inner) / (outer - inner)) ^ falloff` до внешнего, 0 за ним; `squadDamage.js damageAtDistance`):

* берётся первый элемент `AllowableDamageTypes`, чей класс **в точности** равен классу типа урона (по родителям не ищется); нет
  элемента - здоровье не меняется;
* радиальное событие (взрыв): `потеря = Lerp(Min, Base * t.modifier * m, scale(d))`, где `m = t.direct` при прямом попадании и
  `t.indirect` иначе (0 при промахе, если `t.onlyDirect`); `Min` - `ExplosiveMinimumDamage` снаряда, применяется после и
  **на модификатор не умножается**; сооружение за внешним радиусом во взрыв не попадает вообще;
* точечное событие (удар при прямом попадании): `потеря = ImpactDamageToApply * t.modifier`, без множителя попадания;
* `DirectHitRadialDamageMultiplier` развёртываемые объекты не читают (только техника и огневые точки); в данных приложения его больше нет;
* `Health = clamp(Health - потеря, 0, MaxHealth)`, поэтому снарядов до разрушения `ceil(MaxHealth / потеря)`;
* `d`: точка взрыва - точка удара, сдвинутая на `ExplosiveDamageDistanceFromImpactNormal` вдоль нормали. При прямом попадании
  взрыв поэтому происходит на этом расстоянии от поражённой поверхности (`d` = оно); при промахе по ровной земле нормаль
  вертикальна, `d = hypot(расстояние по земле, это расстояние)`, сооружение берётся на уровне земли (приближение к лучу из
  native-rules.ru.md раздел 3, для которого нужна коллизия сооружения; перекрытие не учитывается);
* вторичный взрыв (мины, Hell Cannon, BM-21) - ещё одно радиальное событие с множителем своего типа урона, своим
  `SecondaryExplosionMinDamage` и расстоянием.

**Известное отклонение приложения (SquadCalc 45.27.0).** `InternalTakeRadialDamage` движка возвращает `Lerp(Min, Damage, scale)` при
`scale = 0` на внешнем радиусе и за ним, то есть `Min`, а не 0 ([`native-rules.ru.md`](native-rules.ru.md) 1.2). Для каких сооружений
эта функция вызывается, решает расстояние от взрыва до коллизии сооружения (бокса), а `d` в формуле - расстояние до ближайшей точки,
в которую попал луч по его компонентам. Сооружение, чей бокс внутри внешнего радиуса, а точка попадания луча за ним, в игре получает
`Min`. У приложения нет ни коллизии, ни луча, только расстояние по земле, и при `reach >= outer` оно возвращает 0; у десяти снарядов
с `Min > 0` ([`native-rules.ru.md`](native-rules.ru.md) раздел 5) игра может нанести до `Min` (125 мм HEAT: 35) там, где приложение показывает ноль, на краю радиуса. Оставлено
как есть: для этого нужна форма коллизии сооружения, которой в данных нет, и измерений в игре нет.

INFERRED (байткод Blueprint, в бинарнике нет): что `ImpactDamageToApply` прямого попадания - точечный урон типа урона снаряда, и путь
вторичного взрыва к `TakeDamage`. По-прежнему UNVERIFIED: какой класс актора попадает под снаряды огневых точек, восстановление
и ремонт, `bForwardDamageToSoldier`. Замеров в игре нет (native-rules.ru.md раздел 6).

Что изменилось в приложении против прежней INFERRED-формы (45.24.0): радиальный член прямого попадания использовал `directRadial` (у
ящиков с боеприпасами 0, то есть ящик не получал радиального урона; теперь полный), а ударный член умножался на `direct`;
`ExplosiveMinimumDamage` игнорировался (у десяти снарядов он > 0: HEAT 125 мм - 35, из-за чего промах в 10 м по HESCO-барьеру
стоит 27 здоровья, а не 0,5); промах по типу `onlyDirect` не был нулевым; расстояние взрыва не учитывало `distanceFromImpact` (1 м у
мины, то есть прямое попадание давало 84 % взрыва, а не 100 %).

Реализация: `damageToStructure(structure, ammo, {directHit, distance, secondary})` возвращает урон по частям, `shellsToDestroy(...)` -
целое число снарядов от полного здоровья (Infinity, если типа урона нет в таблице или потерь нет). Чистые функции;
`findStructure(className)` находит сооружение по имени класса Blueprint. Данные (`src/data/structureDamage.js`) создаются заново командой
`python3 semantics/structure_damage.py export data/structure_damage.json <SquadCalc>/src/data/structureDamage.js` (добавлены `minimum` и
`onlyDirect`, убран `directRadial`; сооружения с одинаковым здоровьем и используемыми полями образуют одну запись).

### Пример расчёта (полное здоровье, `shellsToDestroy`)

Мина (`BP_Mortarround4`: M252 / 2B14 / L16 / Type 63), прямое попадание в радио FOB (300 здоровья): удар 10 * 0,1 (Frag) = 1, взрыв
350 * 0,1 * 0,838 (1 м от поверхности, `(1 - 1/40)^7`) = 29,3, вторичный 250 * 0,5 (Explosives у радио, 0,5 м, внутри внутреннего радиуса) = 125,
итого 155,3 за мину, то есть **2 мины**. По HAB (500): 0,1 + 2,9 + 25 = 28,0, **18 мин**. По HESCO-барьеру (200): 0,1 + 2,9 + 62,5 = 65,5, **4 мины**.
Танковый HEAT 125 мм (1900 удара) по HAB: 1900 * 0,031579 = 60 плюс 6,3 взрыва, 66: **8 снарядов**; по HESCO: 19 + 2, **10 снарядов**.

Снарядов до разрушения, прежняя форма (45.24.0) против нативных правил (45.25.0), полное здоровье, один снаряд на единицу:

| снаряд, сооружение | прямое попадание | 3 м | 5 м | 10 м |
|---|---|---|---|---|
| мина, радио FOB | 2 / 2 | 8 / 8 | 22 / 22 | 65 / 65 |
| мина, HAB | 18 / 18 | 81 / 85 | 342 / 350 | 1071 / 1083 |
| мина, HESCO-барьер | 4 / 4 | 17 / 17 | 126 / 129 | 429 / 434 |
| HEAT 125 мм, радио FOB | 3 / 3 | 30 / 30 | 39 / 20 | 131 / 11 |
| HEAT 125 мм, HAB | 8 / 8 | 80 / 80 | 103 / 40 | 344 / 18 |
| HEAT 125 мм, HESCO-барьер | 10 / 10 | 100 / 100 | 130 / 22 | 435 / 8 |

(было / стало). Промахи HEAT становятся лучше, потому что `Min` 35 - собственная нижняя граница за внутренним радиусом 3,5 м.

Снарядов до разрушения, прямое попадание (нативные правила):

| Сооружение (HP) | Миномёт 81/82 мм | Миномёт 120 мм | Hell Cannon | UB-32 S-5 | BM-21 | Танк HEAT 125 | Танк ОФ 125 | RPG-7 HEAT | RPG-7 OG-7V | SPG-9 HEAT | Carl Gustav HE | 40 мм ГП HEAT | 30 мм ОФ | ZiS-3 HEAT |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Радио FOB (300) | 2 | 2 | 2 | 17 | 2 | 3 | 6 | 6 | 12 | 4 | 3 | 35 | 14 | 3 |
| HAB (500) | 18 | 13 | 11 | 44 | 39 | 8 | 100 | 15 | 193 | 9 | 42 | 91 | 223 | 8 |
| HESCO-барьер (200) | 4 | 3 | 2 | 55 | 3 | 10 | 40 | 19 | 77 | 11 | 17 | 115 | 89 | 10 |
| HESCO-стена (420) | 7 | 5 | 4 | 116 | 6 | 20 | 84 | 39 | 162 | 23 | 35 | 240 | 187 | 20 |
| Стена из мешков (250) | 10 | 7 | 8 | 7 | 1 | 2 | 10 | 3 | 20 | 2 | 5 | 15 | 23 | 2 |
| Малый бункер (500) | 8 | 6 | 5 | 137 | 7 | 24 | 100 | 46 | 193 | 27 | 42 | 286 | 223 | 24 |
| Бункер M2 (600) | 10 | 7 | 6 | 165 | 9 | 29 | 120 | 56 | 231 | 32 | 50 | 343 | 267 | 29 |
| Наблюдательная вышка (800) | 13 | 9 | 7 | 220 | 50 | 39 | 160 | 74 | 308 | 43 | 67 | 458 | 356 | 39 |
| Колючая проволока (100) | 4 | 3 | 3 | 28 | 2 | 5 | 20 | 10 | 39 | 6 | 9 | 58 | 45 | 5 |
| Бетонный барьер (160) | 3 | 2 | 2 | 15 | 3 | 3 | 11 | 5 | 21 | 3 | 5 | 31 | 24 | 3 |
| Станция ремонта техники (500) | 3 | 2 | 2 | 14 | 2 | 3 | 5 | 5 | 10 | 3 | 3 | 29 | 12 | 3 |
| Миномётная позиция (420) | 2 | 1 | 1 | 5 | 11 | 1 | 3 | 2 | 6 | 1 | 2 | 10 | 7 | 1 |

Использованные классы: `BP_FOBRadio_Woodland`, `US_Hab_Desert`, `BP_Hesco_USA_Desert`, `BP_HescoWall_DesertCam`,
`BP_SandBagWall_2`, `BP_smallbunker_Desert`, `BP_M2_BAF_Bunker_Desert`, `BP_ObservationTower_ADF_Desert`,
`BP_Razorwire_clean_2`, `BP_ConcreteBarrier`, `BP_vehicle_repair_ADF_Desert`, `BP_m252mortar_Deployable`. Полная матрица (любой
класс, любое расстояние) — `shellsToDestroy` по `STRUCTURES` x `AMMO`.

## 5. Материал сооружений (VERIFIED)

`data/structure_damage.json` для каждого объекта хранит статические меши под компонентом `Completed` и долю
треугольников по физматериалам (материал слота меша или экземпляр из `OverrideMaterials` компонента вместе с цепочкой
родителей). Примеры: радио FOB `PhysMat_MetalThin` 76 %, `PhysMat_Sandbag` 24 %; HAB (`SM_US_HAB`) `PhysMat_Dirt` 42 %,
`PhysMat_Rock_Deployable` 41 %, `PhysMat_Sandbag` 14 %, `PhysMat_WoodSolid` 3 %; HESCO (`SM_Hesco_V3_1_Deployable`)
`PhysMat_Dirt` 66 %, `PhysMat_Rock_Deployable` 34 %; стена из мешков `PhysMat_Sandbag` 100 %; вышка `PhysMat_Rock_Deployable` 79 %.
Миномётные и зенитные позиции — скелетные меши, здесь не разобраны (у 22 из 235 классов материал меша не определён).

| material | damage_absorbed | armor_thickness_mm | allow_penetration |
|---|---|---|---|
| PhysMat_Sandbag | 120 | 12 | да |
| PhysMat_Rock_Deployable (HESCO fill, bunker walls) | не задано | 100 | да |
| PhysMat_Dirt | не задано | 5000 | да |
| PhysMat_Concrete | 120 | 10 | не задано |
| PhysMat_WoodSolid | 30 | 3 | да |
| PhysMat_MetalThin | 20 | 1 | да |
| PhysMat_Razorwire | 5 | не задано | да |

(`data/materials.json`; «не задано» — поля нет в ассете, то есть нативное значение по умолчанию.) Эти значения описывают,
сколько теряет **пуля**, проходя поверхность. С уроном взрыва по сооружениям они не связаны (раздел 6), и множители
сооружений им не следуют: мешки (damage_absorbed 120) получают 0,05 осколочного, HESCO (земля и камень) 0,01,
металлический станок 0,3.

## 6. Чего в данных нет (VERIFIED — отсутствие)

* Нет связи от `AllowableDamageTypes`, Blueprint типов урона (`/Game/Gameplay/DamageTypes/BP_*`, без переопределённых
  свойств) или Blueprint снарядов с физматериалом: свойства снаряда — `DamageTypeToApply, ImpactDamageToApply, Explosive*,
  Secondary*, ArmorPenetrationDepthMillimeters, TraceDistanceAfterPenetrationMeters, SpecificImpactEffects (косметика), ...`;
  `lethality_modifier` и `splash_radius_modifier` не существуют (`materials.json`).
* Нет множителя урона по материалу и нет отдельного множителя «урон по сооружениям» или «по технике» в типах урона и
  снарядах, кроме таблицы каждого сооружения выше.
* Способ сочетания `Modifier` и трёх множителей, расстояние до сооружения и урон бронебойных и пулемётных пуль по
  сооружениям (урон пули хранит оружие, не ассет снаряда) — нативный код или другие ассеты, UNVERIFIED. Для вопроса
  владельца про HE/HEAT нужно только сочетание.

## 6b. В интерфейсе SquadCalc (45.24.0, C7b; нативные правила с 45.25.0)

* Клик по маркеру деплоя (радио FOB, HAB, миномёт, HMG, GMG, зенитка, ящик с боеприпасами, ремонтная станция) открывает
  окошко со снарядами выбранного боеприпаса, которые разрушают сооружение с полного здоровья; диалог цели показывает ту же
  строку для цели в пределах 5 м от такого маркера (`src/js/structureInfo.js`). Каждое число — `shellsToDestroy`: прямое
  попадание, если разрыв в пределах 1 м от сооружения (`DIRECT_HIT_RADIUS`), иначе промах на этом расстоянии; один снаряд
  на единицу, каждый падает туда, куда наведён, разброс не учитывается. Подсказка строки говорит, что сочетание взято из игры и прочитано из кода сервера, кроме урона удара при прямом попадании и
  вторичного взрыва мин (INFERRED); в игре ничего не измерялось.
* Связь снаряда приложения со снарядом игры — `src/data/structureLinks.js` (`SHELL_AMMO`: имя оружия / имя снаряда -> снаряд
  из раздела 3; `MARKER_STRUCTURES`: значок маркера -> класс сооружения). Найдена по метке баллистики оружия, затем по
  взрыву снаряда (урон, радиусы, спад) против взрыва снаряда игры, оставлена только там, где кандидаты совпадают по типу
  урона, урону удара и вторичному взрыву; `tests/structureDamage.test.mjs` проверяет каждую запись и перечисляет 22 снаряда
  без неё (гаубицы, РСЗО, модовое оружие, 40-мм гранаты, подходящие под два снаряда, три танковых фугасных, C90-CR, DZJ-08,
  RPG-28 и Type 63, чей класс в данных не назван). Для них ничего не показывается.
* Снаряд без взрыва (AP, APFSDS, пулемёты: `explosionRadius [0, 0]`) даёт «нет урона постройкам», что и следует из данных
  (урон удара 0 у всех кинетических снарядов, раздел 3); так же для снаряда, тип урона которого сооружение не перечисляет.
* Маркер HAB — это HAB на 500 здоровья, который строит большинство фракций (у IMF и MEI 400 и 300); у маркера нет фракции.
  Маркеры без таблицы в данных (вертолётная площадка, ПТ, UB-32, Hell Cannon) ничего не показывают.
* Проверка в браузере: `tools/browser_check/targets_check.mjs`.

## 7. Воспроизведение

Экстрактор: `tools/heightmaps/extractor`, режимы `list` и `dumpall` (и `meshsections` из `tools/volumetric/extractor`),
только пакет выделенного сервера. Рабочая папка `~/data/structdmg` (вне репозитория), память контейнера до 3 ГБ.

| Результат | Команда |
|---|---|
| Все пути пака | `SquadExtract <paks> list ""` > `files.txt` |
| Blueprint сооружений, FOB, типов урона | `dumpall 'Content/Gameplay/(DamageTypes\|Deployables)/\|Gameplay/FOBs/' dump` |
| Blueprint снарядов | `dump` из `tools/game_ballistics` (README), слитый в ту же папку |
| Меши и материалы-переопределения | `python3 structure_damage.py meshes dump files.txt out`, затем `meshsections out/meshes.txt sections.ndjson` и `dumpall` для `out/materials.txt` и их родителей |
| Файл данных | `python3 structure_damage.py build dump files.txt sections.ndjson ../data/materials.json ballistics.json ../data/structure_damage.json` |
| Модуль данных SquadCalc | `python3 structure_damage.py export ../data/structure_damage.json <SquadCalc>/src/data/structureDamage.js` |
| Тесты расчёта | `npm test` в SquadCalc (`tests/structureDamage.test.mjs`) |
