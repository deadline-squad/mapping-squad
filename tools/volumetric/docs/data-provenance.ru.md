# Происхождение данных расчёта наводки (сборка Squad 26005357)

Каждый вход расчёта наводки двух приложений, по каждому оружию, с ассетом-источником и меткой. Приложения: Squad
Ballistics (SB, `weapons.json`, 167 оружий, версия 1.7.2) и Deadline SquadCalc (SC, `src/data/weapons.js`, 145 оружий,
версия 45.40.0).
Данные игры — только пакет выделенного сервера (`SquadGame/Content/Paks`; клиентский pak не используется). Английская
версия: `data-provenance.md`. Ничего не запускалось на игровом сервере. У каждого утверждения есть метка (словарь раздела 0
`docs/thesis-methods-and-results.ru.md` плюс ASSUMED):

* **VERIFIED**: прочитано из файлов игры закоммиченным инструментом, воспроизводимо, и значение приложения равно ему.
* **INFERRED**: выведено из проверенных данных с названным доводом (нативное значение по умолчанию, значение кривой
  разброса в покое, предел, вычисленный из наклона станка, «такого поля нет ни в одном Blueprint»).
* **UNVERIFIED**: записано без воспроизводимого вывода (подгонка под замеры владельца, разовое чтение скелета, Blueprint,
  которого нет в имеющемся дампе) или не определяется по файлам сервера.
* **ASSUMED**: в файлах сервера нет совсем: моды из Workshop, bore и zoom ручного оружия (они берутся из анимации клиента),
  нативные значения взрыва по умолчанию в C++ (`NATIVE_EXPLOSION` в `gamecheck.py`), время жизни по умолчанию в SquadCalc
  (100 с), высота плеча в SquadCalc.

Таблицы ниже сгенерированы (`tools/game_ballistics/provenance.py`, раздел 9); длинная форма — по строке на оружие, снаряд
и вход со значением приложения, значением игры, источником и меткой — это `data-provenance.tsv` рядом с этим файлом.

## 1. Ответы коротко

| Вопрос | Ответ | Метка |
|---|---|---|
| Начальная скорость, масштаб гравитации, двигатель ракеты (ускорение, время, без гравитации), `MaxSpeed`, `bRotationFollowsVelocity` каждого оружия, у которого есть класс игры | Равны Blueprint в обоих приложениях, для 167 оружий SB и 135 SC; необъяснённых расхождений нет (одно объяснённое: SC держит один предел скорости для AP и HE снарядов трёх 30-мм оружий, без эффекта при 970 / 950 м/с) | VERIFIED; поле, которое не задаёт ни один Blueprint (гравитация 1, нет двигателя, нет предела, вращение следует за скоростью), — значение движка по умолчанию: INFERRED |
| Сопротивление воздуха | Нет: ни в одном компоненте движения снаряда 797 классов оружия из `resolved.json` нет поля сопротивления (их ключи — в разделе 3), чтение серверного кода `USQProjectileMovement` в `ballistics.py` с этим согласуется | INFERRED (чтение кода здесь не перезапускалось) |
| Время жизни снаряда (`InitialLifeSpan`) | **Расхождение найдено и исправлено**: у 108 сгенерированных оружий прямой наводки SC стояло значение SC по умолчанию 100 с, а игра уничтожает снаряд через 4–40 с; в SB времени жизни не было вовсе. Теперь оба приложения несут значение игры (SB 1.6.1 `lifespan`, SC 45.30.0 `projectileLifespan`) и отказывают, если выстрел длится дольше: цель РПГ-7 на 1500 м (6,6 с) недостижима, ракета пропадает через 4 с, около 900 м | VERIFIED |
| Разброс | SC берёт `WeaponConfig.MOA`. Если у оружия есть и `MOACurve` (автоматические гранатомёты, тяжёлые пулемёты, Kord), игра разбрасывает по кривой, и SC берёт одно её значение: в покое (15 / 3 / 7 MOA) у сгенерированных оружий, устоявшееся (50) у АГС-17 (унаследовано). SB разброс не использует | VERIFIED для `MOA`; INFERRED для значений кривой (ассет в дампе есть для кривой гранатомёта: 15 при 0 и 50 при 0,75); UNVERIFIED для кривых HMG и Kord (ассетов нет в этом дампе) |
| Взрыв (урон, внутренний и внешний радиус, спад, высота) | Равен Blueprint для каждого снаряда SC, у которого есть класс игры. Поля, которых не задаёт ни один Blueprint, — нативные значения `ASQProjectile` по умолчанию, их нет ни в одном файле | VERIFIED там, где задано; ASSUMED там, где нативное (ячейка их перечисляет) |
| Bore, zoom в SB | Прочитаны из Blueprint и скелетов техники и станков для 134 оружий; у 26 ручных гранатомётов bore 0 и zoom 1 приняты | VERIFIED / ASSUMED |
| Точка запуска, пределы возвышения | Из игры для установок на технике (`tools/game_weapons.py`). Для станков (миномёт, UB-32, Hell Cannon): точка запуска — разовое чтение скелетов; пределы — диапазон наклона установки плюс то, что прибавляет прицел игры (миномёт 0..43,8 + 45, Hell Cannon −30..50 + 40, UB-32 −25..35 + 0), их читает `tools/game_audit/mounts.py` в `tools/game_audit/data/mount_limits.json`. У станкового АГС-17 стоит 1 м, хотя по файлам 0,347 м (оставлено намеренно, заметки к выпуску SB 1.6.0, #13) | VERIFIED / INFERRED (пределы по наклону установки) / UNVERIFIED (точки запуска, прочитанные один раз) |
| Скорость удержания и верх удержания у записей АГС-17 | Подогнаны под 67 замеров в игре (их нет в репозиториях); по файлам 9,00 °/с | UNVERIFIED |
| Оружие, значения которого достались от старой таблицы апстрима SquadCalc | Mortar, UB-32, HellCannon, Tech.Mortar, Tech.UB-32, BM-21Grad, M1064M121, Mk19, BTR4-AGS (раздел 6) и десять модовых оружий | игра подтверждает скорость, гравитацию, разброс и взрыв первых девяти (VERIFIED); их пределы возвышения и минимальные дистанции после аудита 2026-11-10 следуют установкам игры (INFERRED, `docs/game-data-audit.md`), кроме Mk19; остальные их поля: ASSUMED / UNVERIFIED |

## 2. Что читают приложения

| Вход | Поле SB | Поле SC | Источник в игре (свойство Blueprint) |
|---|---|---|---|
| начальная скорость | `velocity` | `shells[].velocity` | `WeaponConfig.MuzzleVelocity` класса оружия (см/с) |
| масштаб гравитации снаряда | `gravity` (x 9,80 м/с²) | `gravityScale` | `ProjectileGravityScale` компонента `ProjectileComp` снаряда (1,0, если его не задаёт Blueprint) |
| двигатель ракеты | `acceleration`, `acceleration_time` | `acceleration` / `accelerationTime` или `deceleration` / `decelerationTime` | `ConstantAcceleration.X`, `ConstantAccelerationTimeout`, `bIgnoreGravityDuringConstantAcceleration` |
| предел скорости | `max_speed` | `maxSpeed` | `MaxSpeed` (0 = нет) |
| вращение двигателя | `rotation_follows_velocity` | `rotationFollowsVelocity` | `bRotationFollowsVelocity` (конструктор `ASQProjectile` ставит true) |
| сопротивление воздуха | нет | нет | нет |
| точка запуска | `launch_height`, `muzzle_forward`, `muzzle_up` | `muzzle` {`pivotHeight`, `forward`, `up`}; иначе `heightOffset`; иначе плечо (1,5 м) | гнездо ствола `Attach_Muzzle` на установке (`tools/game_weapons.py`, launch) |
| разброс | не используется | `shells[].moa` | `WeaponConfig.MOA`, `WeaponConfig.MOACurve` |
| время жизни | `lifespan` (1.6.1) | `projectileLifespan` (по умолчанию 100) | `InitialLifeSpan` снаряда |
| взрыв | `warhead` (splash при радиусе поражения больше 10 м) | `explosionDamage`, `explosionRadius`, `explosionDistanceFromImpact`, `damageFallOff` | `ExplosiveBaseDamage`, `...InnerRadius`, `...OuterRadius`, `...Falloff`, `...DistanceFromImpactNormal` и вторичный взрыв |
| прицел | `bore`, `zoom` | нет | наклон гнезда ствола к камере; делитель FOV в `BlueprintOnZoom` |
| пределы возвышения, минимальная дистанция | `elevation_limits`, `min_distance` | `minElevation`, `shells[].minDistance` | `PitchInterval` установки плюс наклон гнезда или то, что прибавляет виджет прицела (пределы); поля игры для минимальной дистанции нет: это дальность на ровной местности на упоре установки |
| сдвиг шкалы | `angle_offset` | `angleOffset` | нет |
| модель удержания | `hold_rate`, `hold_elevation` | `elevationRate`, `holdElevation` | нет (подгонка) |

## 3. Число меток

Строки — оружия для входов оружия и пары «оружие и снаряд» для скорости, разброса и взрыва; вход, которого приложение не
использует (в SB нет разброса, в SC — прицела), и входы, которых у оружия нет, не считаются.

<!-- generated:counts -->
| Вход | SB VERIFIED | SB INFERRED | SB UNVERIFIED | SB ASSUMED | SC VERIFIED | SC INFERRED | SC UNVERIFIED | SC ASSUMED |
|---|---|---|---|---|---|---|---|---|
| начальная скорость | 167 | - | - | - | 151 | - | - | 13 |
| масштаб гравитации | 167 | - | - | - | 151 | - | - | 13 |
| постоянное ускорение, время, без гравитации | 167 | - | - | - | 151 | - | - | 13 |
| MaxSpeed | 167 | - | - | - | 151 | - | - | 13 |
| bRotationFollowsVelocity | 2 | 42 | - | - | 2 | 39 | - | 13 |
| сопротивление воздуха | - | 167 | - | - | - | 151 | - | 13 |
| точка запуска | 131 | - | 6 | 30 | 80 | - | 5 | 60 |
| разброс (MOA) | - | - | - | - | 120 | 18 | 13 | 13 |
| время жизни | 167 | - | - | - | 146 | - | - | 18 |
| взрыв | 84 | 27 | - | - | 50 | 26 | 8 | 80 |
| bore (наклон ствола к камере) | 134 | - | - | 26 | - | - | - | - |
| zoom (кратность) | 134 | - | - | 26 | - | - | - | - |
| пределы возвышения | 138 | 3 | - | 26 | 85 | 4 | - | 56 |
| минимальная дистанция | - | 5 | - | - | - | 6 | - | 11 |
| сдвиг шкалы | - | 1 | - | - | - | 1 | - | 3 |
| модель удержания | - | - | 9 | - | - | - | 8 | - |
| **total** | **1458** | **245** | **15** | **108** | **1087** | **245** | **34** | **319** |
<!-- /generated:counts -->

Утверждение про сопротивление воздуха: ключи компонентов движения снарядов всех 797 классов оружия из `resolved.json` —
`InitialSpeed`, `MaxSpeed`, `ProjectileGravityScale`, `ConstantAcceleration`, `ConstantAccelerationTimeout`, `Bounciness`,
`Friction`, `bBounceAngleAffectsFriction`, `bAutoActivate`, `bRotationFollowsVelocity`, `MovementModes`,
`bIgnoreGravityDuringConstantAcceleration`, `MaxSimulationIterations`, `bUseAdditiveJitter`; ни один не является членом
сопротивления или затухания (`Friction` относится к отскокам).

## 4. Классы игры и оружие, которое их использует

Класс — Blueprint оружия вместе с Blueprint его снаряда; значения — цепочки, слитой по наследованию Blueprint (`collect.py`,
`gamecheck.py`; единицы м, м/с, с). Ячейка взрыва — самый широкий поражающий взрыв (`blast()`); `[native: ...]` перечисляет
поля, которых не задаёт ни один Blueprint (ASSUMED: `NATIVE_EXPLOSION`). Оружие SC с несколькими снарядами (HEAT и HE)
стоит в классе каждого снаряда. Тринадцать записей SB (MK19 на PARS III и TAPV C16 с уровнями увеличения их прицелов, пять
АГС-17 на технике, QLZ87 на ZBL08 в обоих видах) называют Blueprint оружия, которых нет в `resolved.json`; в строке класса стоят значения снимка (`tests/data/game_weapons.json`) без разброса.

<!-- generated:classes -->
| # | Класс игры (Blueprint оружия, Blueprint снаряда) | v m/s | g | Двигатель | cap | Жизнь s | MOA | Взрыв (урон, радиусы м, высота м, спад) | SB | SC |
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

## 5. Входы, которые файлы игры не решают (или которых не читает ни один закоммиченный инструмент)

Всё, что не VERIFIED, по входам и причинам; оружие названо приложением и именем (имена SB — из `weapons.json`, имена
SC — из `weapons.js`; длинный список обрезан, полный — в TSV).

<!-- generated:origins -->
| Вход | Метка | Источник | n | Оружие |
|---|---|---|---|---|
| точка запуска | UNVERIFIED | 1 m chosen with the fit of the hold model; the files say 0.347 m (SB 1.6.0 release notes #13, not reproducible by a committed tool) | 1 | SB AGS-17 · emplacement · optic (RMB ×2.5) |
| точка запуска | UNVERIFIED | one-off read of the weapon's skeletons (Squad build 26005357), recorded in the comment of SC weapons.js; tools/game_weapons.py does not read tripods and deployables | 6 | SB Hell Cannon; SB Mortar (M252 / 2B14 / L16 / Type 63); SB UB-32 (S-5 rockets); SC HellCannon; SC Mortar; SC UB-32 |
| точка запуска | UNVERIFIED | same as the optic entry: 1 m, the files say 0.347 m (#13) | 2 | SB AGS-17 · emplacement · no optic; SB AGS-17 · iron sights emplacement |
| точка запуска | UNVERIFIED | via SB entry: | 2 | SC DF_AGS_17_emplacement_no_optic; SC DF_AGS_17_iron_sights_emplacement |
| точка запуска | ASSUMED | SHOULDER_HEIGHT of squadCoverageRays.js | 47 | SC DF_2A42_2A72_30mm_AP; SC DF_2A42_30mm_BMP_2_HE; SC DF_2A72_30mm_BMD_4M_HE; SC DF_2A72_30mm_BMP_3M_AP_HE; SC DF_AK_40GL_MPT_76; SC DF_AT_4; SC DF_C90_CR; SC DF_CTAS40_40mm_AP; SC DF_CTAS40_40mm_GP; SC DF_Carl_Gustav_M2_FFV441D_HE; SC DF_Carl_Gustav_M2_FFV551_HEAT; SC DF_Carl_Gustav_M2_FFV751_Tandem; SC DF_DShK_M; SC DF_DZJ_08; ... (+33) |
| точка запуска | ASSUMED | handheld or unmodelled mount: no launch point in the files read by game_weapons.py | 30 | SB AK-40GL (MPT-76); SB AT-4; SB C90-CR; SB Carl Gustav M2 · FFV441D HE; SB Carl Gustav M2 · FFV551 HEAT; SB Carl Gustav M2 · FFV751 Tandem; SB DZJ-08; SB M203 / M320 / GP-25 / HK79 / SL40; SB M3 MAAWS · HEAT / Smoke; SB M3 MAAWS · Tandem; SB M72A7 LAW / RPG-26; SB MGL / M32; SB MK153 SMAW; SB MK19; ... (+16) |
| точка запуска | ASSUMED | round figure kept from the upstream table / the mod's table | 13 | SC AGS-17; SC BTR4-AGS; SC HIMARS; SC M109; SC M777; SC MO120RTF1; SC MTLB_FAB500; SC Mk19; SC PZL07; SC T62.DUMP.TRUCK; SC TOS-1A; SC Ural-HellCannon; SC type_63 |
| разброс (MOA) | INFERRED | WeaponConfig.MOACurve /Game/Vehicles/FC_MOACurve_GenericGMG.0 | 18 | SC AGS-17; SC DF_AGS_17_emplacement_no_optic; SC DF_AGS_17_iron_sights_emplacement; SC DF_MK19_M113_open_turret; SC DF_MK19_M113_open_turret_no_sights; SC DF_MK19_M1151_RHIB_open_turret; SC DF_MK19_M1151_open_turret_no_sights; SC DF_MK19_MATV_open_turret; SC DF_MK19_MATV_open_turret_no_sights; SC DF_MK19_RHIB_open_turret; SC DF_MK19_emplacement_C16_L134A1; SC DF_MK19_emplacement_C16_L134A1_no_sights; SC DF_QLZ87; SC DF_QLZ87_CSK131_WZ551_no_optic; ... (+4) |
| разброс (MOA) | UNVERIFIED | WeaponConfig.MOACurve /Game/Vehicles/Emplaced_Kord/Curves/FC_MOACurve_Kord.0 (asset not in the dump here; values from gamecheck.py MOA_CURVES) | 2 | SC DF_Kord_SPP_emplacement; SC DF_NSV |
| разброс (MOA) | UNVERIFIED | WeaponConfig.MOACurve /Game/Vehicles/FC_MOACurve_GenericHMG.0 (asset not in the dump here; values from gamecheck.py MOA_CURVES) | 3 | SC DF_DShK_M; SC DF_M2A1_50; SC DF_M2A1_50_ACOG_emplacement |
| разброс (MOA) | UNVERIFIED | weapon Blueprint not in resolved.json; value from the generator table (read from another dump, no longer on disk) | 8 | SC DF_AGS_17_BTR_D; SC DF_AGS_17_M1151; SC DF_AGS_17_Safir; SC DF_AGS_17_Technical; SC DF_AGS_17_Tigr; SC DF_MK19_PARS_III_RWS; SC DF_MK19_TAPV_C16_RWS; SC DF_QLZ87_ZBL08_no_optic |
| разброс (MOA) | ASSUMED | Workshop mod | 10 | SC HIMARS; SC M109; SC M777; SC MO120RTF1; SC MTLB_FAB500; SC PZL07; SC T62.DUMP.TRUCK; SC TOS-1A; SC Ural-HellCannon; SC type_63 |
| время жизни | ASSUMED | Workshop mod: not in the dedicated-server package; table of the upstream SquadCalc | 10 | SC HIMARS; SC M109; SC M777; SC MO120RTF1; SC MTLB_FAB500; SC PZL07; SC T62.DUMP.TRUCK; SC TOS-1A; SC Ural-HellCannon; SC type_63 |
| время жизни | ASSUMED | the game sets none; SC default 100 s | 4 | SC HellCannon; SC M1064M121; SC Mortar; SC Tech.Mortar |
| взрыв | INFERRED | projectile Blueprint chain sets no Explosive* field | 26 | SC DF_2A42_2A72_30mm_AP; SC DF_2A72_30mm_BMP_3M_AP_HE; SC DF_CTAS40_40mm_AP; SC DF_DShK_M; SC DF_KPVT_14_5mm; SC DF_Kord_SPP_emplacement; SC DF_L21A1_RARDEN_30mm_AP; SC DF_M242_Bushmaster_25mm_AP; SC DF_M2A1_50; SC DF_M2A1_50_ACOG_emplacement; SC DF_NSV; SC DF_Tank_AP_2A46_ZPT98_2A20_2A45_KBA3; SC DF_Tank_AP_L30A1_Challenger_2_M68A2; SC DF_Tank_AP_Leopard_2A6_Rh120; ... (+12) |
| взрыв | INFERRED | the projectile Blueprint chain sets no Explosive* field: it hits with its impact damage | 27 | SB Tank AP · Challenger 2 (L30A1) · gunner sight ×10; SB Tank AP · Challenger 2 (L30A1) · gunner sight ×4; SB Tank AP · L30A1 (Challenger 2) / M68A2; SB Tank AP · Leopard 2A6 (Rh120); SB Tank AP · Leopard 2A6 (Rh120) · gunner sight ×12; SB Tank AP · M1128 MGS (M68A2); SB Tank AP · M1128 MGS (M68A2) · gunner sight ×8; SB Tank AP · M1A1 / M1A2 (M256) · gunner sight ×12; SB Tank AP · M1A1 / M1A2 (M256) · gunner sight ×6; SB Tank AP · M256 / Rh120; SB Tank AP · M60T (MG253); SB Tank AP · M60T (MG253) · gunner sight ×3; SB Tank AP · M60T (MG253) · gunner sight ×8; SB Tank AP · Sprut-SDM1 (2A45) · gunner sight ×12; ... (+13) |
| взрыв | UNVERIFIED | weapon Blueprint not in resolved.json (generator table) | 8 | SC DF_AGS_17_BTR_D; SC DF_AGS_17_M1151; SC DF_AGS_17_Safir; SC DF_AGS_17_Technical; SC DF_AGS_17_Tigr; SC DF_MK19_PARS_III_RWS; SC DF_MK19_TAPV_C16_RWS; SC DF_QLZ87_ZBL08_no_optic |
| взрыв | ASSUMED | Workshop mod | 10 | SC HIMARS; SC M109; SC M777; SC MO120RTF1; SC MTLB_FAB500; SC PZL07; SC T62.DUMP.TRUCK; SC TOS-1A; SC Ural-HellCannon; SC type_63 |
| взрыв | ASSUMED | projectile primary explosion | 64 | SC AGS-17; SC BTR4-AGS; SC DF_2A28_Grom_BMD_1M_FRAG; SC DF_2A28_Grom_BMD_1M_HEAT; SC DF_2A28_Grom_BMP_1_BMD_1_FRAG; SC DF_2A28_Grom_BMP_1_BMD_1_HEAT; SC DF_2A28_Grom_BMP_1_technical_FRAG; SC DF_2A28_Grom_BMP_1_technical_HEAT; SC DF_AGS_17_emplacement_no_optic; SC DF_AGS_17_iron_sights_emplacement; SC DF_AGS_30_BMP_1TS; SC DF_AGS_30_BMP_2M; SC DF_AGS_30_BTR_4_AGS; SC DF_AK_40GL_MPT_76; ... (+50) |
| bore (наклон ствола к камере) | ASSUMED | handheld: the shot leaves along the barrel socket (native ASQWeapon::GetAimDirection and GetProjectileSpawnTransform read WeaponConfig.BarrelSocketName on the weapon mesh | 26 | SB AK-40GL (MPT-76); SB AT-4; SB C90-CR; SB Carl Gustav M2 · FFV441D HE; SB Carl Gustav M2 · FFV551 HEAT; SB Carl Gustav M2 · FFV751 Tandem; SB DZJ-08; SB M203 / M320 / GP-25 / HK79 / SL40; SB M3 MAAWS · HEAT / Smoke; SB M3 MAAWS · Tandem; SB M72A7 LAW / RPG-26; SB MGL / M32; SB MK153 SMAW; SB NLAW; ... (+12) |
| zoom (кратность) | ASSUMED | handheld: the shot leaves along the barrel socket (native ASQWeapon::GetAimDirection and GetProjectileSpawnTransform read WeaponConfig.BarrelSocketName on the weapon mesh | 26 | SB AK-40GL (MPT-76); SB AT-4; SB C90-CR; SB Carl Gustav M2 · FFV441D HE; SB Carl Gustav M2 · FFV551 HEAT; SB Carl Gustav M2 · FFV751 Tandem; SB DZJ-08; SB M203 / M320 / GP-25 / HK79 / SL40; SB M3 MAAWS · HEAT / Smoke; SB M3 MAAWS · Tandem; SB M72A7 LAW / RPG-26; SB MGL / M32; SB MK153 SMAW; SB NLAW; ... (+12) |
| пределы возвышения | INFERRED | mount pitch -25..35 (BP_EmplacedUB32_Tripod) + 0 the sight adds: tools/game_audit/data/mount_limits.json | 1 | SB UB-32 (S-5 rockets) |
| пределы возвышения | INFERRED | mount pitch -30..50 (BP_Emplaced_HellCannon_Base) + 40 the sight adds: tools/game_audit/data/mount_limits.json | 1 | SB Hell Cannon |
| пределы возвышения | INFERRED | mount pitch -5..45 (BP_BTR4_Turret) + 0.1 the sight adds: tools/game_audit/data/mount_limits.json | 1 | SC BTR4-AGS |
| пределы возвышения | INFERRED | mount pitch 0..43.8 (BP_GenericDeployableMortarVehicle) + 45 the sight adds: tools/game_audit/data/mount_limits.json | 1 | SB Mortar (M252 / 2B14 / L16 / Type 63) |
| пределы возвышения | INFERRED | via SB entry: mount pitch -25..35 (BP_EmplacedUB32_Tripod) + 0 the sight adds: tools/game_audit/data/mount_limits.json | 1 | SC UB-32 |
| пределы возвышения | INFERRED | via SB entry: mount pitch -30..50 (BP_Emplaced_HellCannon_Base) + 40 the sight adds: tools/game_audit/data/mount_limits.json | 1 | SC HellCannon |
| пределы возвышения | INFERRED | via SB entry: mount pitch 0..43.8 (BP_GenericDeployableMortarVehicle) + 45 the sight adds: tools/game_audit/data/mount_limits.json | 1 | SC Mortar |
| пределы возвышения | ASSUMED | Workshop mod | 10 | SC HIMARS; SC M109; SC M777; SC MO120RTF1; SC MTLB_FAB500; SC PZL07; SC T62.DUMP.TRUCK; SC TOS-1A; SC Ural-HellCannon; SC type_63 |
| пределы возвышения | ASSUMED | no mount: handheld | 26 | SB AK-40GL (MPT-76); SB AT-4; SB C90-CR; SB Carl Gustav M2 · FFV441D HE; SB Carl Gustav M2 · FFV551 HEAT; SB Carl Gustav M2 · FFV751 Tandem; SB DZJ-08; SB M203 / M320 / GP-25 / HK79 / SL40; SB M3 MAAWS · HEAT / Smoke; SB M3 MAAWS · Tandem; SB M72A7 LAW / RPG-26; SB MGL / M32; SB MK153 SMAW; SB NLAW; ... (+12) |
| пределы возвышения | ASSUMED | unbounded: no mount data for this SquadCalc-only weapon | 19 | SC DF_2A42_2A72_30mm_AP; SC DF_2A42_30mm_BMP_2_HE; SC DF_2A72_30mm_BMD_4M_HE; SC DF_2A72_30mm_BMP_3M_AP_HE; SC DF_CTAS40_40mm_AP; SC DF_CTAS40_40mm_GP; SC DF_DShK_M; SC DF_KPVT_14_5mm; SC DF_Kord_SPP_emplacement; SC DF_L21A1_RARDEN_30mm_AP; SC DF_L21A1_RARDEN_30mm_HE; SC DF_M242_Bushmaster_25mm_AP; SC DF_M242_Bushmaster_25mm_HE; SC DF_M2A1_50; ... (+5) |
| пределы возвышения | ASSUMED | upstream table (Mk19) | 1 | SC Mk19 |
| пределы возвышения | ASSUMED | via SB entry: no mount: handheld | 26 | SC DF_AK_40GL_MPT_76; SC DF_AT_4; SC DF_C90_CR; SC DF_Carl_Gustav_M2_FFV441D_HE; SC DF_Carl_Gustav_M2_FFV551_HEAT; SC DF_Carl_Gustav_M2_FFV751_Tandem; SC DF_DZJ_08; SC DF_M203_M320_GP_25_HK79_SL40; SC DF_M3_MAAWS_HEAT_Smoke; SC DF_M3_MAAWS_Tandem; SC DF_M72A7_LAW_RPG_26; SC DF_MGL_M32; SC DF_MK153_SMAW; SC DF_NLAW; ... (+12) |
| минимальная дистанция | INFERRED | range of the top of the hold (85.85 degrees) from the muzzle, computed by gen_squadcalc_weapons.py lob_min_distance from the fitted hold model | 1 | SC AGS-17 |
| минимальная дистанция | INFERRED | range on level ground at the mount's stop, barrel at 0 degrees: tools/game_audit (mount_limits.json, calculator.mjs, check_calculator.py) | 2 | SB Technical UB-32; SC Tech.UB-32 |
| минимальная дистанция | INFERRED | range on level ground at the mount's stop, barrel at 14.2 degrees: tools/game_audit (mount_limits.json, calculator.mjs, check_calculator.py) | 2 | SB BM-21 Grad; SC BM-21Grad |
| минимальная дистанция | INFERRED | range on level ground at the mount's stop, barrel at 85 degrees: tools/game_audit (mount_limits.json, calculator.mjs, check_calculator.py) | 2 | SB M1064 M121 (120mm); SC M1064M121 |
| минимальная дистанция | INFERRED | range on level ground at the mount's stop, barrel at 88.8 degrees: tools/game_audit (mount_limits.json, calculator.mjs, check_calculator.py) | 4 | SB Mortar (M252 / 2B14 / L16 / Type 63); SB Technical Mortar; SC Mortar; SC Tech.Mortar |
| минимальная дистанция | ASSUMED | inherited from the upstream SquadCalc table (sh4rkman/SquadCalc); not decided by the server files | 11 | SC DF_AGS_17_BTR_D; SC DF_AGS_17_M1151; SC DF_AGS_17_Safir; SC DF_AGS_17_Technical; SC DF_AGS_17_Tigr; SC DF_AGS_17_emplacement_no_optic; SC DF_AGS_17_iron_sights_emplacement; SC M777; SC MTLB_FAB500; SC Mk19; SC type_63 |
| сдвиг шкалы | INFERRED | 5 degrees is the upstream value; the HUD table of the game (readout in degrees against range) puts the barrel 4.8 +- 0.3 degrees above the readout (SB release notes 1.6.0 | 2 | SB Technical Mortar; SC Tech.Mortar |
| сдвиг шкалы | ASSUMED | Workshop mod | 1 | SC M109 |
| сдвиг шкалы | ASSUMED | inherited from the upstream SquadCalc table (sh4rkman/SquadCalc); not decided by the server files | 2 | SC BTR4-AGS; SC Mk19 |
| модель удержания | UNVERIFIED | 9 deg/s read by hand from the game's input settings (keyboard pitch x300/s x turret input x0.03, SB weapons.json note); no committed tool reads it; Calibrate refits it in | 1 | SB Mortar (M252 / 2B14 / L16 / Type 63) |
| модель удержания | UNVERIFIED | fitted to 67 in-game hold-time measurements of the owner (not in the repositories); the game files give 9.00 deg/s (keyboard pitch x15 x turret input x0.6) and fit them a | 16 | SB AGS-17 · BTR-D; SB AGS-17 · M1151; SB AGS-17 · Safir; SB AGS-17 · Technical; SB AGS-17 · Tigr; SB AGS-17 · emplacement · no optic; SB AGS-17 · emplacement · optic (RMB ×2.5); SB AGS-17 · iron sights emplacement; SC AGS-17; SC DF_AGS_17_BTR_D; SC DF_AGS_17_M1151; SC DF_AGS_17_Safir; SC DF_AGS_17_Technical; SC DF_AGS_17_Tigr; ... (+2) |
<!-- /generated:origins -->

## 6. Унаследовано от апстрима, подогнано, измерено

`git blame` файла SC `src/data/weapons.js` (автор строки, которая стоит сейчас; «upstream» — `sh4rkman`, автор
`sh4rkman/SquadCalc`, «fork» — форк Deadline):

<!-- generated:blame -->
| Оружие | Строки апстрима (sh4rkman) | Строки форка |
|---|---|---|
| Mortar | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, moa, velocity | minDistance, minElevation, muzzle |
| UB-32 | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, minDistance, minElevation, moa, projectileLifespan, velocity | maxSpeed, muzzle |
| HellCannon | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, minDistance, minElevation, moa, velocity | muzzle |
| Tech.Mortar | angleOffset, damageFallOff, explosionDamage, explosionRadius, gravityScale, moa, velocity | explosionDistanceFromImpact, minDistance, minElevation, muzzle |
| Tech.UB-32 | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, moa, projectileLifespan, velocity | maxSpeed, minDistance, minElevation, muzzle |
| BM-21Grad | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, moa, velocity | minDistance, minElevation, muzzle, projectileLifespan |
| M1064M121 | damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, moa, velocity | minDistance, minElevation, muzzle |
| Mk19 | angleOffset, damageFallOff, explosionDamage, explosionDistanceFromImpact, explosionRadius, gravityScale, heightOffset, minDistance, minElevation, moa, projectileLifespan, velocity | - |
| BTR4-AGS | angleOffset, damageFallOff, explosionDamage, explosionRadius, gravityScale, heightOffset, minDistance, moa, projectileLifespan, velocity | explosionDistanceFromImpact, minElevation |
| AGS-17 | - | elevationRate, gravityScale, heightOffset, holdElevation, minDistance, minElevation, projectileLifespan, velocity |
<!-- /generated:blame -->

Что это значит по оружиям:

* **Mortar, UB-32, HellCannon, Tech.Mortar, Tech.UB-32, BM-21Grad, M1064M121** (оружия калькулятора `Mortar (M252 / 2B14 / L16 / Type 63)`,
  `UB-32 (S-5 rockets)`, `Hell Cannon`, `Technical Mortar`, `Technical UB-32`, `BM-21 Grad`, `M1064 M121 (120mm)`): скорость,
  гравитацию, разброс, взрыв и время жизни набрал апстрим или взял из SDK, `gamecheck.py` подтверждает их равенство
  игре (VERIFIED, происхождение унаследовано). Точку запуска (`muzzle`), пределы возвышения установок на технике, предел
  скорости и вращение UB-32 / Tech.UB-32 задал форк по файлам игры. Пределы возвышения миномёта (45..88,8°; у апстрима
  было 88,875), Hell Cannon и UB-32 — диапазон наклона установки плюс то, что прибавляет прицел, а минимальные дистанции
  (51,8, 51,8, 358, 985,1 и 147,1 м; у апстрима были 51, 51 и 340 м, а у БМ-21 и UB-32 на «техничке» не было) — дальность на
  ровной местности на упоре установки: то и другое читает и проверяет `tools/game_audit` (INFERRED, `docs/game-data-audit.md`);
  сдвиг шкалы 5° у миномёта «технички» — из апстрима, его поддерживает таблица HUD игры (INFERRED).
* **Mk19, BTR4-AGS**: скорость, гравитация, разброс, взрыв и время жизни согласуются с игрой (`MK19`, `AGS-30 / BTR-4 AGS`
  в `gamecheck.py`); круглые высоты запуска 4 м и 3,4 м, сдвиги шкалы 0,984 и 0,7346°, пределы и минимальная дистанция
  10 м у Mk19 — цифры апстрима, которых не решает ни один файл (ASSUMED); пределы BTR4-AGS (−4,9..45,1°) — диапазон наклона
  его башни плюс 0,1° камеры прицела (INFERRED, `tools/game_audit`). В SB для тех же орудий есть записи лучше (по машинам,
  из файлов); эти две остаются для тех, у кого выбрано прежнее оружие.
* **АГС-17** (SC `AGS-17`, SB `AGS-17 · emplacement · optic (RMB ×2.5)` и пять других записей АГС-17): скорость 185 м/с и
  гравитация ×1,8 из файлов (VERIFIED, совпадают с 67 замерами до 0,7 % по v²/g); скорость удержания 9,08 °/с и диапазон
  удержания **подогнаны** под эти замеры (UNVERIFIED), верх удержания — предел установки, 85,85° (до SB 1.7.1 и SC 45.37.0
  был подогнанный 85,87); минимальная дистанция (280 м) вычислена из этой
  подгонки; высота запуска 1 м оставлена вместе с подгонкой (по файлам 0,347 м).
* **QLZ87**: сдвиг камеры, измеренный в обычном виде, 0,23 м вверх и 0,34 м вправо от оси (даёт −8,5 / −5,6 / −4,2 м
  дальности на 200 / 300 / 400 м), **измерен** и не применяется ни одним приложением (`docs/sight-data.ru.md` SB). Возможный
  источник в игре — свойство Blueprint `ProjectileCameraRelativeOffsetMultiplier` = 0,666667 у 44 Blueprint оружия (семейство
  QLZ-87, 2A70 / 2A72 БМД-4М и БМП-3М, фугасные снаряды KBA3, M68A2, MG253, Mk19 и NSV на RHIB, ...): оно есть в
  `resolved.json`, ни один инструмент его не использует, а что оно умножает, решает нативный код (UNVERIFIED).
* **Моды из Workshop** (SC `MO120RTF1`, `type_63`, `PZL07`, `M109`, `M777`, `T62.DUMP.TRUCK`, `HIMARS`, `TOS-1A`, `Ural-HellCannon`,
  `MTLB_FAB500`): в пакете выделенного сервера нет; все входы ASSUMED из таблицы апстрима (значения авторов модов).
* **Сгенерированное оружие** (записи `DF_...` SC, их 125): получены из `weapons.json` SB скриптом
  `tools/direct_fire/gen_squadcalc_weapons.py`, который берёт разброс и взрыв из таблиц, сверяемых с игрой (`--verify
  resolved.json`); автопушки и пулемёты, убранные из SB в 1.6.0 (`M242`, `2A42 / 2A72`, `L21A1`, `CTAS40`, `ZPT99`, `KPVT`,
  `M2A1 .50`, `NSV`, `DShK-M`, `Kord`: 19 записей), живут только в SC с `SQUADCALC_ONLY`, их классы — из `gamecheck.py`.

## 7. Расхождения с игрой

Найдены сравнением каждого оружия обоих приложений с классами игры (`provenance.py`, на `resolved.json` сборки 26005357;
`gamecheck.py` и `compare.py` как раньше). Проверка сообщает расхождение, когда значение приложения не равно значению
игры; для Squad Ballistics 1.7.2 и SquadCalc 45.40.0 — **0 необъяснённых расхождений** в 3 511 размеченных строках.

| Оружие | Вход | Игра | Приложение до | Изменение |
|---|---|---|---|---|
| 108 сгенерированных оружий прямой наводки SC (у всех есть время жизни в игре) | время жизни | 4 с (РПГ-7, M3 MAAWS, Carl Gustav, SMAW), 5 с (РПГ-29, РПГ-28, автопушки), 8 с (СПГ-9, «Гром», танковые подкалиберные, пулемёты), 10–20 с (остальные) | SC: по умолчанию 100 с; SB: нет | SC `projectileLifespan` из игры через `gen_squadcalc_weapons.py` (45.30.0); SB `lifespan` (1.6.1); тесты: SC `weapons.test.mjs`, `squadBallistics.test.mjs`, SB `test_ballistics.py`, `test_game_weapons.py` |

Задокументированные расхождения, которые не менялись (тот же набор отмечает TSV, и таблица вариантов ниже):

* `M72A7 LAW / RPG-26`: время жизни 20 с от M72A7; у RPG-26 — 5 с.
* У AP и HE снарядов `2A72 30mm (BMP-3M)`, `ZPT99 30mm (ZBD-04A)` и `ZPT99 30mm (ZBL-08 / ZBD-05)` один предел (1385); у
  HE-снаряда — 1000. Без эффекта при 970 / 950 м/с.
* Высота запуска станковых АГС-17 (1 м, в игре 0,347 м), MK19 (нет, в игре 0,368 м) и СПГ-9 (нет, в игре 0,637 м):
  заметки к выпуску SB 1.6.0 (#13); замеры не отличают 0,347 м от 1 м; цифры не воспроизводятся закоммиченным инструментом.
* Максимальная дальность (круг на карте SC, `max_range` в SB) — геометрическая дальность полёта и не учитывает время
  жизни: у РПГ-7 она около 5,7 км, а ракета пропадает примерно через 900 м. Решение за временем жизни отвергается. Текст
  оверлея SB для такой цели — «Out of range (max ... m)» с геометрическим числом (`crosshair.py`, здесь не менялся).
* Разброс автоматических гранатомётов — значение кривой в покое у сгенерированных оружий и устоявшееся у АГС-17
  (унаследовано): динамический MOA игры растёт с каждым выстрелом нативным кодом, который не восстановлен
  (`tools/volumetric/docs/native-rules.ru.md`).

Классы одной записи калькулятора, различающиеся в игре (справочно: запись следует первому классу):

<!-- generated:variants -->
| Оружие | Класс-вариант | Отличается |
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

## 8. Указатель оружия

Каждое оружие обоих приложений с классами из раздела 4 и источником его значений.

<!-- generated:index -->
| Приложение | Оружие | Классы | Происхождение |
|---|---|---|---|
| SB | M203 / M320 / GP-25 / HK79 / SL40 | C01 | из файлов игры |
| SB | MGL / M32 | C02 | из файлов игры |
| SB | AK-40GL (MPT-76) | C03 | из файлов игры |
| SB | QLG10 | C04 | из файлов игры |
| SB | Rifle grenade | C05 | из файлов игры |
| SB | MK19 | C06 | из файлов игры |
| SB | MK19 · M1117 · gunner sight ×4.5 | C06 | из файлов игры |
| SB | MK19 · AAVP-7A1 | C07 | из файлов игры |
| SB | MK19 · AAVP-7A1 · gunner sight ×4.5 | C07 | из файлов игры |
| SB | MK19 · PARS III RWS | C08 | из файлов игры |
| SB | MK19 · PARS III RWS · gunner sight ×3 | C08 | из файлов игры |
| SB | MK19 · PARS III RWS · gunner sight ×9 | C08 | из файлов игры |
| SB | MK19 · TAPV C16 RWS | C09 | из файлов игры |
| SB | MK19 · TAPV C16 RWS · gunner sight ×5 | C09 | из файлов игры |
| SB | MK19 · TAPV C16 RWS · gunner sight ×12 | C09 | из файлов игры |
| SB | MK19 · M113 open turret | C10 | из файлов игры |
| SB | MK19 · M113 open turret · no sights | C10 | из файлов игры |
| SB | MK19 · M1151 open turret | C10 | из файлов игры |
| SB | MK19 · M1151 open turret · no sights | C10 | из файлов игры |
| SB | MK19 · MATV open turret | C10 | из файлов игры |
| SB | MK19 · MATV open turret · no sights | C10 | из файлов игры |
| SB | MK19 · RHIB open turret | C11 | из файлов игры |
| SB | MK19 · RHIB open turret · no sights | C11 | из файлов игры |
| SB | MK19 · emplacement / C16 / L134A1 | C12 | из файлов игры |
| SB | MK19 · emplacement / C16 / L134A1 · no sights | C12 | из файлов игры |
| SB | AGS-17 · emplacement · optic (RMB ×2.5) | C13 | из файлов игры; hold model fitted (67 measurements); launch hand-read |
| SB | AGS-17 · emplacement · no optic | C13 | из файлов игры; hold model fitted (67 measurements); launch hand-read |
| SB | AGS-17 · iron sights emplacement | C14 | из файлов игры; hold model fitted (67 measurements); launch hand-read |
| SB | AGS-17 · Technical | C15 | из файлов игры; hold model fitted (67 measurements) |
| SB | AGS-17 · Tigr | C16 | из файлов игры; hold model fitted (67 measurements) |
| SB | AGS-17 · Safir | C17 | из файлов игры; hold model fitted (67 measurements) |
| SB | AGS-17 · M1151 | C16 | из файлов игры; hold model fitted (67 measurements) |
| SB | AGS-17 · BTR-D | C16 | из файлов игры; hold model fitted (67 measurements) |
| SB | QLZ87 · optic (RMB ×3) | C18 | из файлов игры |
| SB | QLZ87 · no optic | C18 | из файлов игры |
| SB | QLZ87 · bunker tripod · optic (RMB ×3) | C18 | из файлов игры |
| SB | QLZ87 · bunker tripod · no optic | C18 | из файлов игры |
| SB | QLZ87 · CSK131 / WZ551 · optic (RMB ×3) | C19 | из файлов игры |
| SB | QLZ87 · CSK131 / WZ551 · no optic | C19 | из файлов игры |
| SB | QLZ87 · Lynx · optic (RMB ×3) | C20 | из файлов игры |
| SB | QLZ87 · Lynx · no optic | C20 | из файлов игры |
| SB | QLZ87 · ZBL08 · optic (RMB ×3) | C21 | из файлов игры |
| SB | QLZ87 · ZBL08 · no optic | C21 | из файлов игры |
| SB | AGS-30 / BTR-4 AGS | C22 | из файлов игры |
| SB | AGS-30 / BTR-4 AGS · gunner sight ×9 | C22 | из файлов игры |
| SB | AGS-30 (BMP-1TS) | C23 | из файлов игры |
| SB | AGS-30 (BMP-1TS) · gunner sight ×9 | C23 | из файлов игры |
| SB | AGS-30 (BMP-2M) | C24 | из файлов игры |
| SB | AGS-30 (BMP-2M) · gunner sight ×6 | C24 | из файлов игры |
| SB | M72A7 LAW / RPG-26 | C25 | из файлов игры |
| SB | C90-CR | C26 | из файлов игры |
| SB | AT-4 | C27 | из файлов игры |
| SB | MK153 SMAW | C28 | из файлов игры |
| SB | PF98 · Tandem | C29 | из файлов игры |
| SB | PF98 · HE-I | C30 | из файлов игры |
| SB | RPG-29 | C31 | из файлов игры |
| SB | DZJ-08 | C32 | из файлов игры |
| SB | RPG-28 | C33 | из файлов игры |
| SB | RPG-7 · PG-7V HEAT / OG-7V | C34 | из файлов игры |
| SB | RPG-7 · PG-7VR Tandem | C35 | из файлов игры |
| SB | RPG-7V1 · PG-7VR Tandem | C36 | из файлов игры |
| SB | RPG-7V2 · PG-7VR Tandem | C37 | из файлов игры |
| SB | RPG-7 · TBG-7V Thermobaric | C38 | из файлов игры |
| SB | RPG-7V1 · HEAT | C39 | из файлов игры |
| SB | M3 MAAWS · HEAT / Smoke | C40 | из файлов игры |
| SB | M3 MAAWS · Tandem | C41 | из файлов игры |
| SB | Carl Gustav M2 · FFV551 HEAT | C42 | из файлов игры |
| SB | Carl Gustav M2 · FFV441D HE | C43 | из файлов игры |
| SB | Carl Gustav M2 · FFV751 Tandem | C44 | из файлов игры |
| SB | NLAW | C45 | из файлов игры |
| SB | SPG-9 · HEAT | C46 | из файлов игры |
| SB | SPG-9 · HEAT · scope · optic (RMB ×4) | C47 | из файлов игры |
| SB | SPG-9 · HEAT · scope · no optic | C47 | из файлов игры |
| SB | SPG-9 · FRAG | C48 | из файлов игры |
| SB | SPG-9 · FRAG · scope · optic (RMB ×4) | C49 | из файлов игры |
| SB | SPG-9 · FRAG · scope · no optic | C49 | из файлов игры |
| SB | SPG-9 · HEAT · technical · optic (RMB ×4) | C50 | из файлов игры |
| SB | SPG-9 · HEAT · technical · no optic | C50 | из файлов игры |
| SB | SPG-9 · FRAG · technical · optic (RMB ×4) | C51 | из файлов игры |
| SB | SPG-9 · FRAG · technical · no optic | C51 | из файлов игры |
| SB | SPG-9 · HEAT · INS armoured technical · optic (RMB ×4) | C50 | из файлов игры |
| SB | SPG-9 · HEAT · INS armoured technical · no optic | C50 | из файлов игры |
| SB | SPG-9 · FRAG · INS armoured technical · optic (RMB ×4) | C51 | из файлов игры |
| SB | SPG-9 · FRAG · INS armoured technical · no optic | C51 | из файлов игры |
| SB | 2A28 Grom (BMP-1 / BMD-1) · HEAT | C52 | из файлов игры |
| SB | 2A28 Grom (BMP-1) · HEAT · gunner sight ×6 | C52 | из файлов игры |
| SB | 2A28 Grom (BMP-1 technical) · HEAT · gunner sight ×6 | C53 | из файлов игры |
| SB | 2A28 Grom (BMD-1M) · HEAT | C54 | из файлов игры |
| SB | 2A28 Grom (BMP-1 technical) · HEAT | C53 | из файлов игры |
| SB | 2A28 Grom (BMD-1M) · HEAT · gunner sight ×6 | C54 | из файлов игры |
| SB | 2A28 Grom (BMP-1 / BMD-1) · FRAG | C55 | из файлов игры |
| SB | 2A28 Grom (BMP-1) · FRAG · gunner sight ×6 | C55 | из файлов игры |
| SB | 2A28 Grom (BMP-1 technical) · FRAG · gunner sight ×6 | C56 | из файлов игры |
| SB | 2A28 Grom (BMD-1M) · FRAG | C57 | из файлов игры |
| SB | 2A28 Grom (BMP-1 technical) · FRAG | C56 | из файлов игры |
| SB | 2A28 Grom (BMD-1M) · FRAG · gunner sight ×6 | C57 | из файлов игры |
| SB | 2A70 100mm (BMP-3 / BMD-4 / ZBD04A) · FRAG | C58 | из файлов игры |
| SB | 2A70 100mm (BMP-3) · FRAG · gunner sight ×4 | C58 | из файлов игры |
| SB | 2A70 100mm (ZBD-04A) · FRAG | C59 | из файлов игры |
| SB | 2A70 100mm (ZBD-04A) · FRAG · gunner sight ×4 | C59 | из файлов игры |
| SB | 2A70 100mm (ZBD-04A) · FRAG · gunner sight ×14 | C59 | из файлов игры |
| SB | 2A70 100mm (BMD-4M) · FRAG | C60 | из файлов игры |
| SB | 2A70 100mm (BMD-4M) · FRAG · gunner sight ×5 | C60 | из файлов игры |
| SB | 2A70 100mm (BMP-3 / BMD-4M) · FRAG · gunner sight ×14 | C60 | из файлов игры |
| SB | ZiS-3 · optic (RMB ×4) | C61 | из файлов игры |
| SB | ZiS-3 · no optic | C61 | из файлов игры |
| SB | Tank AP · T-72 (2A46) | C62 | из файлов игры |
| SB | Tank AP · T-90A (2A46M) | C63 | из файлов игры |
| SB | Tank AP · Sprut-SDM1 (2A45) · gunner sight ×4 | C64 | из файлов игры |
| SB | Tank AP · Sprut-SDM1 (2A45) · gunner sight ×12 | C64 | из файлов игры |
| SB | Tank AP · T-72 (2A46) · gunner sight ×12 | C65 | из файлов игры |
| SB | Tank AP · T-90A (2A46M) · gunner sight ×12 | C63 | из файлов игры |
| SB | Tank AP · T-62 (2A20) | C66 | из файлов игры |
| SB | Tank AP · T-62 (2A20) · gunner sight ×7 | C66 | из файлов игры |
| SB | Tank AP · T-64BM2 (KBA3) | C67 | из файлов игры |
| SB | Tank AP · T-64BM2 (KBA3) · gunner sight ×12 | C67 | из файлов игры |
| SB | Tank AP · ZTZ-99 (ZPT-98) | C68 | из файлов игры |
| SB | Tank AP · ZTZ-99 (ZPT-98) · gunner sight ×12 | C68 | из файлов игры |
| SB | Tank AP · M256 / Rh120 | C69 | из файлов игры |
| SB | Tank AP · M1A1 / M1A2 (M256) · gunner sight ×6 | C70 | из файлов игры |
| SB | Tank AP · M1A1 / M1A2 (M256) · gunner sight ×12 | C70 | из файлов игры |
| SB | Tank AP · Leopard 2A6 (Rh120) | C71 | из файлов игры |
| SB | Tank AP · Leopard 2A6 (Rh120) · gunner sight ×12 | C71 | из файлов игры |
| SB | Tank AP · M60T (MG253) | C72 | из файлов игры |
| SB | Tank AP · M60T (MG253) · gunner sight ×3 | C72 | из файлов игры |
| SB | Tank AP · M60T (MG253) · gunner sight ×8 | C72 | из файлов игры |
| SB | Tank AP · L30A1 (Challenger 2) / M68A2 | C73 | из файлов игры |
| SB | Tank AP · Challenger 2 (L30A1) · gunner sight ×4 | C73 | из файлов игры |
| SB | Tank AP · Challenger 2 (L30A1) · gunner sight ×10 | C73 | из файлов игры |
| SB | Tank AP · M1128 MGS (M68A2) | C74 | из файлов игры |
| SB | Tank AP · M1128 MGS (M68A2) · gunner sight ×8 | C74 | из файлов игры |
| SB | Tank HEAT/HE · T-72 (2A46) | C75 | из файлов игры |
| SB | Tank HEAT/HE · T-90A (2A46M) | C76 | из файлов игры |
| SB | Tank HEAT/HE · Sprut-SDM1 (2A45) · gunner sight ×4 | C77 | из файлов игры |
| SB | Tank HEAT/HE · Sprut-SDM1 (2A45) · gunner sight ×12 | C77 | из файлов игры |
| SB | Tank HEAT/HE · T-72 (2A46) · gunner sight ×12 | C78 | из файлов игры |
| SB | Tank HEAT/HE · T-90A (2A46M) · gunner sight ×12 | C76 | из файлов игры |
| SB | Tank HEAT/HE · M1A1 / M1A2 (M256) | C79 | из файлов игры |
| SB | Tank HEAT/HE · M1A1 / M1A2 (M256) · gunner sight ×6 | C79 | из файлов игры |
| SB | Tank HEAT/HE · M1A1 / M1A2 (M256) · gunner sight ×12 | C79 | из файлов игры |
| SB | Tank HEAT/HE · Leopard 2A6 (Rh120) | C80 | из файлов игры |
| SB | Tank HEAT/HE · Leopard 2A6 (Rh120) · gunner sight ×12 | C80 | из файлов игры |
| SB | Tank HEAT/HE · M1128 MGS (M68A2) | C81 | из файлов игры |
| SB | Tank HEAT/HE · M1128 MGS (M68A2) · gunner sight ×8 | C81 | из файлов игры |
| SB | Tank HEAT/HE · M60T (MG253) | C82 | из файлов игры |
| SB | Tank HEAT/HE · M60T (MG253) · gunner sight ×3 | C82 | из файлов игры |
| SB | Tank HEAT/HE · M60T (MG253) · gunner sight ×8 | C82 | из файлов игры |
| SB | Tank HEAT/HE · ZTZ-99 (ZPT-98) | C83 | из файлов игры |
| SB | Tank HEAT/HE · ZTZ-99 (ZPT-98) · gunner sight ×12 | C83 | из файлов игры |
| SB | Tank HEAT/HE · T-62 (2A20) | C84 | из файлов игры |
| SB | Tank HEAT/HE · T-62 (2A20) · gunner sight ×7 | C84 | из файлов игры |
| SB | Tank HEAT/HE · T-64BM2 (KBA3) | C85 | из файлов игры |
| SB | Tank HEAT/HE · T-64BM2 (KBA3) · gunner sight ×12 | C85 | из файлов игры |
| SB | Tank HESH · L30A1 (Challenger 2) | C86 | из файлов игры |
| SB | Tank HESH · Challenger 2 (L30A1) · gunner sight ×4 | C86 | из файлов игры |
| SB | Tank HESH · Challenger 2 (L30A1) · gunner sight ×10 | C86 | из файлов игры |
| SB | ZPL-98A 105mm (ZTD-05) · AP | C87 | из файлов игры |
| SB | ZPL-98A 105mm (ZTD-05) · AP · gunner sight ×7 | C87 | из файлов игры |
| SB | ZPL-98A 105mm (ZTD-05) · HEAT / HE | C88 | из файлов игры |
| SB | ZPL-98A 105mm (ZTD-05) · HEAT / HE · gunner sight ×7 | C88 | из файлов игры |
| SB | Mortar (M252 / 2B14 / L16 / Type 63) | C89 | из файлов игры; hold model fitted (67 measurements); launch hand-read; limits from the mount's pitch (tools/game_audit) |
| SB | Technical Mortar | C90 | из файлов игры |
| SB | M1064 M121 (120mm) | C91 | из файлов игры |
| SB | Hell Cannon | C92 | из файлов игры; launch hand-read; limits from the mount's pitch (tools/game_audit) |
| SB | UB-32 (S-5 rockets) | C93 | из файлов игры; launch hand-read; limits from the mount's pitch (tools/game_audit) |
| SB | Technical UB-32 | C94 | из файлов игры |
| SB | BM-21 Grad | C95 | из файлов игры |
| SC | Mortar | C89 | ведётся вручную в SC weapons.js |
| SC | UB-32 | C93 | ведётся вручную в SC weapons.js |
| SC | HellCannon | C92 | ведётся вручную в SC weapons.js |
| SC | Tech.Mortar | C90 | ведётся вручную в SC weapons.js |
| SC | Tech.UB-32 | C94 | ведётся вручную в SC weapons.js |
| SC | BM-21Grad | C95 | ведётся вручную в SC weapons.js |
| SC | M1064M121 | C91, C96 | ведётся вручную в SC weapons.js |
| SC | Mk19 | C06 | ведётся вручную в SC weapons.js; height, angle offset, limits, min distance from upstream |
| SC | BTR4-AGS | C22 | ведётся вручную в SC weapons.js; height and angle offset from upstream, limits from the mount's pitch (tools/game_audit) |
| SC | MO120RTF1 | - | мод из Workshop, нет в файлах сервера |
| SC | type_63 | - | мод из Workshop, нет в файлах сервера |
| SC | PZL07 | - | мод из Workshop, нет в файлах сервера |
| SC | M109 | - | мод из Workshop, нет в файлах сервера |
| SC | M777 | - | мод из Workshop, нет в файлах сервера |
| SC | T62.DUMP.TRUCK | - | мод из Workshop, нет в файлах сервера |
| SC | HIMARS | - | мод из Workshop, нет в файлах сервера |
| SC | TOS-1A | - | мод из Workshop, нет в файлах сервера |
| SC | Ural-HellCannon | - | мод из Workshop, нет в файлах сервера |
| SC | MTLB_FAB500 | - | мод из Workshop, нет в файлах сервера |
| SC | AGS-17 | C13 | ведётся вручную в SC weapons.js; hold model fitted (67 measurements) |
| SC | DF_M203_M320_GP_25_HK79_SL40 | C01 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_QLG10 | C04 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Rifle_grenade | C05, C97 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19 | C06 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_QLZ87 | C18 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_AGS_30_BTR_4_AGS | C22 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_M72A7_LAW_RPG_26 | C25 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_AT_4 | C27 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK153_SMAW | C28, C98 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_PF98_Tandem | C29 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_PF98_HE_I | C30 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_RPG_29 | C31 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_RPG_7_PG_7V_HEAT_OG_7V | C34, C99 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_RPG_7_PG_7VR_Tandem | C35 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_RPG_7V1_HEAT | C39, C100 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_M3_MAAWS_HEAT_Smoke | C40 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_M3_MAAWS_Tandem | C41 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_NLAW | C45 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT | C46 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG | C48 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMP_1_BMD_1_HEAT | C52 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMP_1_BMD_1_FRAG | C55 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_2A70_100mm_BMP_3_BMD_4_ZBD04A_FRAG | C58 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_ZiS_3 | C61, C101 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_2A46_ZPT98_2A20_2A45_KBA3 | C62 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_M256_Rh120 | C69 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_L30A1_Challenger_2_M68A2 | C73 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_M256_Rh120_2A46_ZPT98_2A20_M68A2 | C75, C102 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_HESH_L30A1_Challenger_2 | C86 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_M242_Bushmaster_25mm_AP | C103 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_M242_Bushmaster_25mm_HE | C104 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_2A42_2A72_30mm_AP | C105 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_2A42_30mm_BMP_2_HE | C106 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_L21A1_RARDEN_30mm_AP | C107 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_L21A1_RARDEN_30mm_HE | C108 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_CTAS40_40mm_AP | C109 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_CTAS40_40mm_GP | C110 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_ZPT99_30mm_ZBL_08_APFSDS | C111 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_ZPT99_30mm_ZBD_04A_AP_HE | C112, C113 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_KPVT_14_5mm | C114 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_M2A1_50 | C115 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_NSV | C116 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_DShK_M | C117 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_MGL_M32 | C02 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_AK_40GL_MPT_76 | C03 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_emplacement_C16_L134A1 | C12 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_RPG_7_TBG_7V_Thermobaric | C38 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Carl_Gustav_M2_FFV551_HEAT | C42 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Carl_Gustav_M2_FFV441D_HE | C43 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Carl_Gustav_M2_FFV751_Tandem | C44 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_ZPL_98A_105mm_ZTD_05_AP | C87 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_ZPL_98A_105mm_ZTD_05_HEAT_HE | C88, C118 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_2A72_30mm_BMD_4M_HE | C119 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_2A72_30mm_BMP_3M_AP_HE | C120, C121 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_ZPT99_30mm_ZBL_08_ZBD_05_AP_HE | C122 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_M2A1_50_ACOG_emplacement | C123 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_Kord_SPP_emplacement | C124 | только в SquadCalc, классы игры из gamecheck.py |
| SC | DF_AGS_17_emplacement_no_optic | C13 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_QLZ87_no_optic | C18 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_QLZ87_Lynx_CSK131_no_optic | C20 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_scope_no_optic | C47 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_scope_no_optic | C49 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_ZiS_3_no_optic | C61, C101 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_PARS_III_RWS | C08 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_TAPV_C16_RWS | C09 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_M113_open_turret | C10 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_M1151_RHIB_open_turret | C10 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_AGS_17_iron_sights_emplacement | C14 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_QLZ87_Lynx_CSK131 | C20 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_AGS_30_BMP_2M | C24 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_scope | C47 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_scope | C49 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMD_1M_HEAT | C54 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMD_1M_FRAG | C57 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_2A70_100mm_ZBD_04A_FRAG | C59 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_2A70_100mm_BMD_4M_FRAG | C60 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_T_62_2A20 | C66 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_T_64BM2_KBA3 | C67 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_ZTZ_99_ZPT_98 | C68 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_Leopard_2A6_Rh120 | C71 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_M60T_MG253 | C72 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_M1128_MGS_M68A2 | C74 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_M1A1_M1A2_M256 | C79 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_Leopard_2A6_Rh120 | C80 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_M1128_MGS_M68A2 | C81 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_M60T_MG253 | C82 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_ZTZ_99_ZPT_98 | C83, C125 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_T_62_2A20 | C84, C126 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_T_64BM2_KBA3 | C85, C127 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_emplacement_C16_L134A1_no_sights | C12 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_AGS_30_BMP_1TS | C23 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_AAVP_7A1 | C07 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_M113_open_turret_no_sights | C10 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_M1151_open_turret_no_sights | C10 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_MATV_open_turret | C10 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_MATV_open_turret_no_sights | C10 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_MK19_RHIB_open_turret | C11 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_AGS_17_Technical | C15 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_AGS_17_Tigr | C16 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_AGS_17_Safir | C17 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_AGS_17_M1151 | C16 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_AGS_17_BTR_D | C16 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_C90_CR | C26 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_DZJ_08 | C32 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_RPG_28 | C33 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_RPG_7V1_PG_7VR_Tandem | C36 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_RPG_7V2_PG_7VR_Tandem | C37 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_technical_optic_RMB_4 | C50 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_technical_no_optic | C50 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_technical_optic_RMB_4 | C51 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_technical_no_optic | C51 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_INS_armoured_technical_optic_RMB_4 | C50 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_HEAT_INS_armoured_technical_no_optic | C50 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_INS_armoured_technical_optic_RMB_4 | C51 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_SPG_9_FRAG_INS_armoured_technical_no_optic | C51 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_QLZ87_bunker_tripod_no_optic | C18 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_QLZ87_CSK131_WZ551_no_optic | C19 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_QLZ87_ZBL08_no_optic | C21 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMP_1_technical_HEAT | C53 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_2A28_Grom_BMP_1_technical_FRAG | C56 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_2A70_100mm_BMP_3_BMD_4M_FRAG_gunner_sight_14 | C60 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_T_90A_2A46M | C63 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_AP_Sprut_SDM1_2A45_gunner_sight_4 | C64 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_T_90A_2A46M | C76, C128 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
| SC | DF_Tank_HEAT_HE_Sprut_SDM1_2A45_gunner_sight_4 | C77, C129 | сгенерировано из weapons.json SB скриптом gen_squadcalc_weapons.py |
<!-- /generated:index -->

## 9. Воспроизведение и проверка

Данные игры (сборка 26005357, имеющиеся дампы; экстрактор не запускается): `~/data/squad-weapons/{dump,resolved.json}`.

```sh
# модель и расхождения как раньше
python3 tools/game_ballistics/gamecheck.py resolved.json <SB>/weapons.json squadcalc_weapons.json ballistics.json diff.md
python3 tools/direct_fire/compare.py <каталог SB> <каталог SC>          # 167 оружий, 32 652 случая, 0 расхождений
python3 tools/direct_fire/gen_squadcalc_weapons.py --verify resolved.json

# этот документ: переписать сгенерированные блоки и TSV или проверить их
python3 tools/game_ballistics/provenance.py --resolved resolved.json --dump dump --sb <SB> --sc <SC> --write tools/volumetric/docs
python3 tools/game_ballistics/provenance.py --resolved resolved.json --dump dump --sb <SB> --sc <SC> --check tools/volumetric/docs
python3 -m unittest tests.test_data_provenance                         # из tools/volumetric
```

`--check` падает, если оружия из `weapons.json` или `weapons.js` нет в указателе любого из двух языков, если блок или TSV
устарел или если значение приложения отличается от игры без записи в `KNOWN` в `provenance.py`.
`tests/test_data_provenance.py` запускает его там, где есть каталоги и данные (`SQUAD_BALLISTICS`, `SQUADCALC`,
`SQUAD_WEAPONS_DATA`), а саму проверку всегда проверяет на небольших синтетических данных.

## 10. Чего этот аудит показать не может

* Тринадцать записей SB (MK19 на PARS III и TAPV C16 с уровнями увеличения их прицелов, АГС-17 на Technical, Tigr, Safir,
  M1151, БТР-Д, QLZ87 на ZBL08 в обоих видах) называют Blueprint, которых
  нет в имеющемся дампе: их значения полёта — из снимка (VERIFIED через `tools/game_weapons.py`, которому для перезапуска нужен
  полный дамп), разброс и взрыв — UNVERIFIED.
* Кривых `FC_MOACurve_GenericHMG`, `_GenericGPMG` и `_Kord` в дампе нет; их значения — из `MOA_CURVES` в `gamecheck.py`. Как
  растёт динамический MOA, который питает кривую, решает нативный код, он не восстановлен.
* Нативные значения взрыва по умолчанию (урон 115, внутренний радиус 5 м, внешний 15 м, спад 1, высота 0,2 м) выведены из
  снарядов, которые переопределяют не все поля, и из значений SquadCalc, полученных из SDK; в файлах их нет.
* Bore и zoom ручного оружия берутся из анимации от первого лица, которой нет в пакете сервера.
* Подгонка АГС-17 и сдвиг камеры QLZ87 — замеры владельца в игре, их нет в репозиториях.
* В игре ничего не стреляли: модель — это код и Blueprint игры, а не выстрел в игре.
