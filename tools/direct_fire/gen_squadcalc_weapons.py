"""Generate SquadCalc's Squad Ballistics weapons from Squad Ballistics' weapons.json.

Every weapon aimed with the overlay (`aim` "overlay", not a mod) becomes a SquadCalc weapon
named DF_<name>, with `ballistics` set to its Squad Ballistics name:

* a weapon laid by holding a key (`hold_rate`, the AGS-17 variants) becomes a "deployables"
  weapon built like SquadCalc's "AGS-17": high arc with the hold time (`elevationRate`,
  `holdElevation`), low arc in direct fire, the AGS-17's VOG-17 grenade (`...VOG_17` in
  weapons.js, 40 s projectile lifespan) and its images. Any other hold-laid weapon stops the
  generator: SquadCalc has no grenade data for it;
* any other weapon becomes a "directFire" weapon (low arc only) with the spread of its game weapon (`moa`,
  from GAME_MOA: a weapon missing there stops the generator) and the explosion of its ammunition, a shell
  for each (GAME_EXPLOSION; none for the AP rounds and machine guns: ...NO_EXPLOSION).

The autocannons and machine guns only SquadCalc has are not in weapons.json: --update keeps their ballistics
and rewrites their shells (spread and explosion) from SQUADCALC_ONLY.

    python3 gen_squadcalc_weapons.py --verify <resolved.json>

checks GAME_EXPLOSION and SQUADCALC_ONLY against the game files (resolved.json of game_ballistics/collect.py).

The AGS-17 optic emplacement is skipped: SquadCalc's "AGS-17" is it.

A weapon Squad Ballistics renamed (RENAMED: the RMB sights, "QLZ87" -> "QLZ87 · optic (RMB ×3)") keeps its DF_ identifier, so its position in WEAPONS and its locale key stay, and gets `legacyBallistics` with the old name.

A boosted rocket gets `acceleration`/`accelerationTime`, a projectile with a speed cap `maxSpeed`
(MaxSpeed of its movement component), and one whose motor keeps the barrel's axis
`rotationFollowsVelocity: false` (SquadCalc's squadBallistics.js flies them like Squad Ballistics).

    python3 gen_squadcalc_weapons.py <weapons.json> <entries.js> <names.json> [<SquadCalc weapons.js>]
    python3 gen_squadcalc_weapons.py <weapons.json> --update <SquadCalc weapons.js>

entries.js goes at the end of WEAPONS in src/data/weapons.js (after the existing weapons: the
selected weapon is stored by index); names.json maps DF_<name> to the display name for
public/locales/*/weapons.json. With SquadCalc's src/data/weapons.js, only the weapons whose
Squad Ballistics name it does not have yet are written, in weapons.json order, so an update is
one run and one append. Prints the number of entries written.

--update rewrites, in place and in their positions, the generated entries (DF_<name>) that
SquadCalc's weapons.js already has, from the current weapons.json (its line endings kept), and
prints how many changed; an entry whose weapon weapons.json no longer has is kept as it is and
named on stderr. Run it before the append. Check the result with compare.py.
"""
import json, math, os, re, sys

GRAVITY = 9.80  # m/s², the world gravity of the game files (SquadCalc's app.js, Squad Ballistics)
SKIP = {"AGS-17 · emplacement · optic (RMB ×2.5)"}  # SquadCalc "AGS-17" already is this weapon
# The RMB sights were renamed in Squad Ballistics (old name -> current name) so that the name says which view the
# entry is for: "QLZ87" was the ×3 optic's entry and used from the normal view overshot by hundreds of metres.
# SquadCalc's entry keeps its DF_ identifier (the locale key; the stored weapon is the entry's index) and its old
# name as `legacyBallistics`, which selectBallisticsWeapon still accepts, so an older Squad Ballistics keeps working.
RENAMED = {
    "QLZ87": "QLZ87 · optic (RMB ×3)",
    "QLZ87 · Lynx / CSK131": "QLZ87 · Lynx / CSK131 · optic (RMB ×3)",
    "AGS-17 · emplacement": "AGS-17 · emplacement · optic (RMB ×2.5)",
    "SPG-9 · HEAT · scope": "SPG-9 · HEAT · scope · optic (RMB ×4)",
    "SPG-9 · FRAG · scope": "SPG-9 · FRAG · scope · optic (RMB ×4)",
    "ZiS-3": "ZiS-3 · optic (RMB ×4)",
    # The M1151 and RHIB open turrets were one entry; the M1151 (with its launch point) kept the name's first half.
    "MK19 · M1151 / RHIB open turret": "MK19 · M1151 open turret",
}
OLD_NAME = {new: old for old, new in RENAMED.items()}
# Weapons renamed earlier (when their data was checked against the game files, Squad build 26005357; Squad
# Ballistics' RENAMED_WEAPONS): their DF_ identifier is already the new name's, only the old name is accepted too.
EARLIER_NAME = {
    "M203 / M320 / GP-25 / HK79 / SL40": "M203 / M320 / GP-25 / HK79 / MKE MGL",
    "MK19": "MK19 / AGS-17 / AGS-30",
    "AGS-30 / BTR-4 AGS": "BTR-4 AGS",
    "M3 MAAWS · HEAT / Smoke": "Carl Gustav / M3 MAAWS · HEAT",
    "M3 MAAWS · Tandem": "Carl Gustav / M3 MAAWS · Tandem",
    "Tank AP · 2A46 / ZPT98 / 2A20 / 2A45 / KBA3": "Tank AP · 2A46 / ZPT98 / 2A20 / M68A2",
    "Tank AP · L30A1 (Challenger 2) / M68A2": "Tank AP · L30A1 (Challenger 2)",
}
HOLD_LAID_FAMILY = "AGS-17"  # the only hold-laid weapon whose grenade SquadCalc has (VOG_17)

# Spread of the direct-fire weapons: the cone's full angle in MOA (WeaponConfig.MOA of the weapon the
# overlay view belongs to, Squad build 26005357; the first class of the view's list in Squad Ballistics'
# tools/game_weapons.py ENTRIES, merged views take that one's value: M203 30 (the GP-25's is 40), SPG-9 FRAG 3
# (the technical's is 1), Tank M256 / Rh120 1.5 (the Leopard's is 1.2).
# MOA is the full cone (half-angle MOA / 120 degrees, ConvertMOAToRadians 0xa4252c0).
# The grenade machine guns (MK19 tripod, open turrets and C16, QLZ87) set MOA 1.5 and the curve
# FC_MOACurve_GenericGMG over it: cubic from 15 MOA at 0 to 50 MOA at 0.75 of the weapon's dynamic MOA, a
# value that grows with each shot and decays between bursts. The curve's input rule is native code and no
# game file gives it, so they get 15, the MOA of the first, rested shot; a sustained burst spreads up to
# 50. The vehicle mounts that set a fixed MOA (M1117 and AAV-7 MK19, PARS III MK19: 50; AGS-30: 15) get
# it. The AGS-17 is not here: it keeps the 50 MOA of its grenade (VOG_17 in SquadCalc's weapons.js).
GAME_MOA = {
    "M203 / M320 / GP-25 / HK79 / SL40": 30,
    "MGL / M32": 30,
    "AK-40GL (MPT-76)": 30,
    "QLG10": 40,
    "Rifle grenade": 30,
    "MK19": 50,
    "MK19 · AAVP-7A1": 50,
    "MK19 · PARS III RWS": 50,
    "MK19 · TAPV C16 RWS": 15,
    "MK19 · M113 open turret": 15,
    "MK19 · M113 open turret · no sights": 15,
    "MK19 · M1151 open turret": 15,
    "MK19 · M1151 open turret · no sights": 15,
    "MK19 · MATV open turret": 15,
    "MK19 · MATV open turret · no sights": 15,
    "MK19 · RHIB open turret": 15,
    "MK19 · emplacement / C16 / L134A1": 15,
    "MK19 · emplacement / C16 / L134A1 · no sights": 15,
    "QLZ87 · optic (RMB ×3)": 15,
    "QLZ87 · no optic": 15,
    "QLZ87 · Lynx / CSK131 · optic (RMB ×3)": 15,
    "QLZ87 · Lynx / CSK131 · no optic": 15,
    "AGS-30 / BTR-4 AGS": 15,
    "AGS-30 (BMP-1TS)": 15,
    "AGS-30 (BMP-2M)": 15,
    "M72A7 LAW / RPG-26": 15,
    "C90-CR": 10,
    "AT-4": 10,
    "MK153 SMAW": 7,
    "PF98 · Tandem": 7,
    "PF98 · HE-I": 7,
    "RPG-29": 10,
    "DZJ-08": 10,
    "RPG-28": 20,
    "RPG-7 · PG-7V HEAT / OG-7V": 20,
    "RPG-7 · PG-7VR Tandem": 20,
    "RPG-7V1 · PG-7VR Tandem": 15,
    "RPG-7V2 · PG-7VR Tandem": 20,
    "RPG-7 · TBG-7V Thermobaric": 20,
    "RPG-7V1 · HEAT": 15,
    "M3 MAAWS · HEAT / Smoke": 7,
    "M3 MAAWS · Tandem": 7,
    "Carl Gustav M2 · FFV551 HEAT": 7,
    "Carl Gustav M2 · FFV441D HE": 7,
    "Carl Gustav M2 · FFV751 Tandem": 7,
    "NLAW": 1,
    "SPG-9 · HEAT": 3,
    "SPG-9 · HEAT · scope · optic (RMB ×4)": 3,
    "SPG-9 · HEAT · scope · no optic": 3,
    "SPG-9 · FRAG": 3,
    "SPG-9 · FRAG · scope · optic (RMB ×4)": 3,
    "SPG-9 · FRAG · scope · no optic": 3,
    # The technicals' SPG-9 (BP_SPG9 3 MOA, BP_SPG9_Frag 1 MOA, the tripod FRAG has 3)
    "SPG-9 · HEAT · technical · optic (RMB ×4)": 3,
    "SPG-9 · HEAT · technical · no optic": 3,
    "SPG-9 · FRAG · technical · optic (RMB ×4)": 1,
    "SPG-9 · FRAG · technical · no optic": 1,
    "SPG-9 · HEAT · INS armoured technical · optic (RMB ×4)": 3,
    "SPG-9 · HEAT · INS armoured technical · no optic": 3,
    "SPG-9 · FRAG · INS armoured technical · optic (RMB ×4)": 1,
    "SPG-9 · FRAG · INS armoured technical · no optic": 1,
    "2A28 Grom (BMP-1 / BMD-1) · HEAT": 3,
    "2A28 Grom (BMD-1M) · HEAT": 3,
    "2A28 Grom (BMP-1 / BMD-1) · FRAG": 3,
    "2A28 Grom (BMD-1M) · FRAG": 3,
    "2A70 100mm (BMP-3 / BMD-4 / ZBD04A) · FRAG": 1.6,
    "2A70 100mm (ZBD-04A) · FRAG": 1.6,
    "2A70 100mm (BMD-4M) · FRAG": 1.6,
    "ZiS-3 · optic (RMB ×4)": 3,
    "ZiS-3 · no optic": 3,
    "Tank AP · 2A46 / ZPT98 / 2A20 / 2A45 / KBA3": 1.5,
    "Tank AP · T-62 (2A20)": 1.5,
    "Tank AP · T-64BM2 (KBA3)": 1.5,
    "Tank AP · ZTZ-99 (ZPT-98)": 1.5,
    "Tank AP · M256 / Rh120": 1.5,
    "Tank AP · Leopard 2A6 (Rh120)": 1.2,
    "Tank AP · M60T (MG253)": 1.5,
    "Tank AP · L30A1 (Challenger 2) / M68A2": 1.5,
    "Tank AP · M1128 MGS (M68A2)": 1.5,
    "Tank HEAT/HE · M256 / Rh120 / 2A46 / ZPT98 / 2A20 / M68A2": 1.5,
    "Tank HEAT/HE · M1A1 / M1A2 (M256)": 1.5,
    "Tank HEAT/HE · Leopard 2A6 (Rh120)": 1.2,
    "Tank HEAT/HE · M1128 MGS (M68A2)": 1.5,
    "Tank HEAT/HE · M60T (MG253)": 1.5,
    "Tank HEAT/HE · ZTZ-99 (ZPT-98)": 1.5,
    "Tank HEAT/HE · T-62 (2A20)": 1.5,
    "Tank HEAT/HE · T-64BM2 (KBA3)": 1.5,
    "Tank HESH · L30A1 (Challenger 2)": 1.5,
    "ZPL-98A 105mm (ZTD-05) · AP": 1.5,
    "ZPL-98A 105mm (ZTD-05) · HEAT / HE": 1.5,
}

# Explosion of the direct-fire weapons that have one: per weapon, a shell per ammunition (HEAT, HE, Tandem; a
# weapon with a single one has "default"), each (shell, weapon Blueprint, damage, inner radius m, outer radius m,
# distance from the impact m, falloff exponent), the widest explosion that deals damage of the Blueprint's projectile
# (`blast()` of tools/game_ballistics/gamecheck.py, Squad build 26005357). A weapon that serves several vehicles is
# the first Blueprint of the weapon's `sources.classes` in Squad Ballistics' tests/data/game_weapons.json (the
# same reference as its MOA and speed); when its ammunition differs (HEAT and HE of the T-72's 125 mm gun) there is a
# shell for each ammunition, the first Blueprint of each. Smoke has no damage and gets no shell. A weapon that has no row
# keeps ...NO_EXPLOSION: the AP and APFSDS rounds and the machine guns (their projectile Blueprints override no
# explosion field: they hit with their impact damage and do not explode), and the weapons without ammunition in the table.
# Fields no Blueprint overrides are the native defaults of ASQProjectile (see NATIVE_EXPLOSION in gamecheck.py), marked
# "native default". Not modelled, though in the same Blueprints: ImpactDamageToApply (a round that hits the soldier
# itself) and ExplosiveKillZoneRadius; the zones and rounds SquadCalc shows are those of the blast alone.
# `python3 gen_squadcalc_weapons.py --verify <resolved.json>` checks this table against the game files.
GAME_EXPLOSION = {
    "M203 / M320 / GP-25 / HK79 / SL40": [
        ("default", "BP_M4M203_UGL_Parent", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MGL / M32": [
        ("default", "BP_MGL_Parent", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "AK-40GL (MPT-76)": [
        ("default", "BP_MPT76_AK40GL_UGL_Parent", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "QLG10": [
        ("default", "BP_QBZ95-1_QLG-10_UGL_Parent", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "Rifle grenade": [
        ("HE", "BP_FNFAL_GL_Frag", 250, 4, 18, 0.08, 1),  # native default: falloff
        ("HEAT", "BP_FNFAL_GL_HEAT", 130, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "MK19": [
        ("default", "BP_M1117_MK19", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · AAVP-7A1": [
        ("default", "BP_AAVP7A1_MK19", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · PARS III RWS": [  # BP_SancakRWS_MK19 and BP_C16_MK19 are not in resolved.json: their WeaponConfig.ProjectileClass is BP_40MM_MK19_Proj, the MK19's (/tmp/mech/vdump2)
        ("default", "BP_M1117_MK19", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · TAPV C16 RWS": [
        ("default", "BP_M1117_MK19", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · M113 open turret": [
        ("default", "BP_Mk19_OpenTurret_Weapon", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · M113 open turret · no sights": [
        ("default", "BP_Mk19_OpenTurret_Weapon", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · M1151 open turret": [
        ("default", "BP_Mk19_OpenTurret_Weapon", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · M1151 open turret · no sights": [
        ("default", "BP_Mk19_OpenTurret_Weapon", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · MATV open turret": [
        ("default", "BP_Mk19_OpenTurret_Weapon", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · MATV open turret · no sights": [
        ("default", "BP_Mk19_OpenTurret_Weapon", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · RHIB open turret": [
        ("default", "BP_Mk19_RHIB_Weapon", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · emplacement / C16 / L134A1": [
        ("default", "BP_Mk19_Weapon", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "MK19 · emplacement / C16 / L134A1 · no sights": [
        ("default", "BP_Mk19_Weapon", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "QLZ87 · optic (RMB ×3)": [
        ("default", "BP_QLZ87_Weapon", 115, 1, 11, 0.08, 1),  # native default: damage, falloff
    ],
    "QLZ87 · no optic": [
        ("default", "BP_QLZ87_Weapon", 115, 1, 11, 0.08, 1),  # native default: damage, falloff
    ],
    "QLZ87 · Lynx / CSK131 · optic (RMB ×3)": [
        ("default", "BP_QLZ87_Weapon_Lynx8x8", 115, 1, 11, 0.08, 1),  # native default: damage, falloff
    ],
    "QLZ87 · Lynx / CSK131 · no optic": [
        ("default", "BP_QLZ87_Weapon_Lynx8x8", 115, 1, 11, 0.08, 1),  # native default: damage, falloff
    ],
    "AGS-30 / BTR-4 AGS": [
        ("default", "BP_BTR4_KBA117", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "AGS-30 (BMP-1TS)": [
        ("default", "BP_BMP1TS_KBA117", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "AGS-30 (BMP-2M)": [
        ("default", "BP_BMP2M_AGS30", 115, 1, 15, 0.08, 1),  # native default: damage, falloff, outer radius
    ],
    "M72A7 LAW / RPG-26": [
        ("default", "BP_M72A7_M72A5_2mags", 100, 1.5, 7.5, 0.08, 1),  # native default: falloff
    ],
    "C90-CR": [
        ("default", "BP_C90CR", 115, 1.5, 7.5, 0.08, 1),  # native default: damage, falloff
    ],
    "AT-4": [
        ("default", "BP_M136AT4", 115, 1.5, 7.5, 0.08, 1),  # native default: damage, falloff
    ],
    "MK153 SMAW": [
        ("HEAT", "BP_SMAW_HEAT_2mags", 200, 2, 8, 0.08, 1),  # native default: falloff
        ("Tandem", "BP_SMAW_Tandem_2mags", 80, 2, 8, 0.08, 0),
    ],
    "PF98 · Tandem": [
        ("default", "BP_PF-98_Tandem_2mags", 200, 2, 8, 0.08, 0),
    ],
    "PF98 · HE-I": [
        ("default", "BP_PF-98_HE_2mags", 200, 7, 20, 0.15, 2),
    ],
    "RPG-29": [
        ("default", "BP_RPG29", 200, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "DZJ-08": [
        ("default", "BP_DZJ-08", 130, 2, 7, 0.08, 1),  # native default: falloff
    ],
    "RPG-28": [
        ("default", "BP_RPG28", 200, 2, 10, 0.08, 1.5),
    ],
    "RPG-7 · PG-7V HEAT / OG-7V": [
        ("HEAT", "BP_RPG7_Heat", 130, 2, 8, 0.08, 1),  # native default: falloff
        ("HE", "BP_RPG7_Frag", 250, 2, 16, 0.08, 1),  # native default: falloff
    ],
    "RPG-7 · PG-7VR Tandem": [
        ("default", "BP_RPG7_Tandem", 200, 2, 10, 0.08, 2),
    ],
    "RPG-7 · TBG-7V Thermobaric": [
        ("default", "BP_RPG7_Thermo", 200, 8, 24, 0.08, 2),
    ],
    "RPG-7V1 · PG-7VR Tandem": [
        ("default", "BP_RPG7V1_Tandem", 200, 2, 10, 0.08, 2),
    ],
    "RPG-7V2 · PG-7VR Tandem": [
        ("default", "BP_RPG7V2_Tandem_2mag", 200, 2, 10, 0.08, 2),
    ],
    "RPG-7V1 · HEAT": [
        ("HEAT", "BP_RPG7V1_Heat", 130, 2, 8, 0.08, 1),  # native default: falloff
        ("HE", "BP_RPG7V1_Frag", 250, 2, 16, 0.08, 1),  # native default: falloff
    ],
    "M3 MAAWS · HEAT / Smoke": [
        ("default", "BP_M3MAAWS_Heat", 130, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "M3 MAAWS · Tandem": [
        ("default", "BP_M3MAAWS_Tandem", 200, 2, 10, 0.08, 2),
    ],
    "Carl Gustav M2 · FFV551 HEAT": [
        ("default", "BP_CarlGustavM2_Parent", 130, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "Carl Gustav M2 · FFV441D HE": [
        ("default", "BP_CarlGustavM2_FFV441D_No78Mk1", 250, 4, 16, 0.08, 1),  # native default: falloff
    ],
    "Carl Gustav M2 · FFV751 Tandem": [
        ("default", "BP_CarlGustavM2_FFV751_No78Mk1", 200, 2, 8, 0.08, 0),
    ],
    "NLAW": [
        ("default", "BP_NLAW", 200, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · HEAT": [
        ("default", "BP_EmplacedSPG9", 100, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · HEAT · scope · optic (RMB ×4)": [
        ("default", "BP_EmplacedSPG9Scope", 100, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · HEAT · scope · no optic": [
        ("default", "BP_EmplacedSPG9Scope", 100, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · FRAG": [
        ("default", "BP_EmplacedSPG9_Frag", 200, 2, 16, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · FRAG · scope · optic (RMB ×4)": [
        ("default", "BP_EmplacedSPG9_FragScope", 200, 2, 16, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · FRAG · scope · no optic": [
        ("default", "BP_EmplacedSPG9_FragScope", 200, 2, 16, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · HEAT · technical · optic (RMB ×4)": [
        ("default", "BP_SPG9", 100, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · HEAT · technical · no optic": [
        ("default", "BP_SPG9", 100, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · FRAG · technical · optic (RMB ×4)": [
        ("default", "BP_SPG9_Frag", 200, 2, 16, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · FRAG · technical · no optic": [
        ("default", "BP_SPG9_Frag", 200, 2, 16, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · HEAT · INS armoured technical · optic (RMB ×4)": [
        ("default", "BP_SPG9", 100, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · HEAT · INS armoured technical · no optic": [
        ("default", "BP_SPG9", 100, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · FRAG · INS armoured technical · optic (RMB ×4)": [
        ("default", "BP_SPG9_Frag", 200, 2, 16, 0.08, 1),  # native default: falloff
    ],
    "SPG-9 · FRAG · INS armoured technical · no optic": [
        ("default", "BP_SPG9_Frag", 200, 2, 16, 0.08, 1),  # native default: falloff
    ],
    "2A28 Grom (BMP-1 / BMD-1) · HEAT": [
        ("default", "BP_BMP1_2A28_HEAT", 100, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "2A28 Grom (BMD-1M) · HEAT": [
        ("default", "BP_BMD1M_2A28_HEAT", 100, 2, 8, 0.08, 1),  # native default: falloff
    ],
    "2A28 Grom (BMP-1 / BMD-1) · FRAG": [
        ("default", "BP_BMP1_2A28_Frag", 200, 2, 16, 0.08, 1),  # native default: falloff
    ],
    "2A28 Grom (BMD-1M) · FRAG": [
        ("default", "BP_BMD1M_2A28_Frag", 200, 2, 16, 0.08, 1),  # native default: falloff
    ],
    "2A70 100mm (BMP-3 / BMD-4 / ZBD04A) · FRAG": [
        ("default", "BP_BMP3M_2A70_HEFrag", 300, 4, 35, 0.2, 5),
    ],
    "2A70 100mm (ZBD-04A) · FRAG": [
        ("default", "BP_ZBD04A_2A70_HEFrag", 300, 4, 35, 0.2, 5),
    ],
    "2A70 100mm (BMD-4M) · FRAG": [
        ("default", "BP_BMD4M_2A70_HEFrag", 300, 4, 35, 0.2, 5),
    ],
    "ZiS-3 · optic (RMB ×4)": [
        ("HEAT", "BP_ZiS3_Weapon_HEAT", 200, 3.5, 16, 0.15, 2),
        ("HE", "BP_ZiS3_Weapon_Frag", 200, 2, 16, 0.08, 1),
    ],
    "ZiS-3 · no optic": [
        ("HEAT", "BP_ZiS3_Weapon_HEAT", 200, 3.5, 16, 0.15, 2),
        ("HE", "BP_ZiS3_Weapon_Frag", 200, 2, 16, 0.08, 1),
    ],
    "Tank HEAT/HE · M256 / Rh120 / 2A46 / ZPT98 / 2A20 / M68A2": [
        ("HEAT", "BP_2A46_HEAT", 200, 3.5, 16, 0.15, 2),
        ("HE", "BP_2A46_Frag", 300, 4, 35, 0.2, 5),
    ],
    "Tank HEAT/HE · M1A1 / M1A2 (M256)": [
        ("default", "BP_M256A1_HEAT", 200, 7, 20, 0.15, 2),
    ],
    "Tank HEAT/HE · Leopard 2A6 (Rh120)": [
        ("default", "BP_L55_HEAT", 200, 7, 20, 0.15, 2),
    ],
    "Tank HEAT/HE · M1128 MGS (M68A2)": [
        ("default", "BP_M68A2_HEAT", 200, 7, 20, 0.15, 2),
    ],
    "Tank HEAT/HE · M60T (MG253)": [
        ("default", "BP_MG253_Frag", 300, 4, 35, 0.2, 5),
    ],
    "Tank HEAT/HE · ZTZ-99 (ZPT-98)": [
        ("HEAT", "BP_ZPT-98_HEAT", 200, 3.5, 16, 0.15, 2),
        ("HE", "BP_ZPT-98_HE", 300, 4, 35, 0.2, 5),
    ],
    "Tank HEAT/HE · T-62 (2A20)": [
        ("HEAT", "BP_2A20_HEAT", 200, 3.5, 16, 0.15, 2),
        ("HE", "BP_2A20_Frag", 300, 4, 35, 0.2, 5),
    ],
    "Tank HEAT/HE · T-64BM2 (KBA3)": [
        ("HEAT", "BP_KBA3_HEAT", 200, 3.5, 16, 0.15, 2),
        ("HE", "BP_KBA3_Frag", 300, 4, 35, 0.2, 5),
    ],
    "Tank HESH · L30A1 (Challenger 2)": [
        ("default", "BP_L30A1_HESH", 200, 7, 20, 0.15, 2),
    ],
    "ZPL-98A 105mm (ZTD-05) · HEAT / HE": [
        ("HEAT", "BP_ZTD05_ZPL-98A_HEAT", 200, 3.5, 16, 0.15, 2),
        ("HE", "BP_ZTD05_ZPL-98A_Frag", 300, 4, 35, 0.2, 5),
    ],
}

# The autocannons and machine guns only SquadCalc has (they are not in Squad Ballistics' weapons.json, so --update
# keeps their ballistics and only rewrites their shells from this table), keyed by their `ballistics` name (the
# calculator weapon in gamecheck.py TARGETS): per shell (shell, weapon Blueprint, MOA[, damage, inner radius,
# outer radius, distance from the impact, falloff]), the explosion as in GAME_EXPLOSION, none for AP. The Blueprint is
# the first of the weapon's classes in TARGETS, as for Squad Ballistics' weapons: where the vehicles that share the entry
# differ (the 2A42 of the BMP-2 spreads 3 MOA, the 2A72 of the BMD-4M and BTR-82A 6) the first one is shown.
# MOA is WeaponConfig.MOA; the machine guns set 1.5 and a curve over it (FC_MOACurve_GenericHMG, _Kord): like the
# grenade machine guns, they get the value of the curve for a rested gun, 3 MOA for the .50 and DShK, 7 for the Kord and NSV (a
# sustained burst spreads up to 65 and 150: MOA_CURVES in gamecheck.py). The ZBL-08 / ZBD-05 HE round sets no MOA anywhere
# in its Blueprint chain, and the native default is not in the files: that entry has the AP shell only.
SQUADCALC_ONLY = {
    "M242 Bushmaster 25mm · AP": [("default", "LAV25_M252_AP", 2)],
    "M242 Bushmaster 25mm · HE": [("default", "LAV25_M252_HE", 2, 125, 1, 7.5, 0.08, 2)],
    "2A42 / 2A72 30mm · AP": [("default", "BP_BMP2_2A42_AP", 3)],
    "2A42 30mm (BMP-2) · HE": [("default", "BP_BMP2_2A42_HE", 3, 125, 1, 7.5, 0.08, 2)],
    "2A72 30mm (BMD-4M) · HE": [("default", "BP_BMD4M_2A72_HE", 4, 125, 1, 7.5, 0.08, 2)],
    "2A72 30mm (BMP-3M) · AP / HE": [("AP", "BP_BMP3M_2A72_AP", 1.35), ("HE", "BP_BMP3M_2A72_HE", 1.69, 125, 1, 7.5, 0.08, 2)],
    "L21A1 RARDEN 30mm · AP": [("default", "BP_Warrior_Rarden_AP", 1.5)],
    "L21A1 RARDEN 30mm · HE": [("default", "BP_Warrior_Rarden_HE", 1.5, 125, 1, 7.5, 0.08, 2)],
    "CTAS40 40mm · AP": [("default", "BP_Warrior_CTAS_AP", 1.5)],
    "CTAS40 40mm · GP": [("default", "BP_Warrior_CTAS_HE", 1.5, 175, 1, 12.5, 0.08, 2)],
    "ZPT99 30mm (ZBL-08) · APFSDS": [("default", "BP_ZBL08_ZPT-99_APFSDS", 2.5)],
    "ZPT99 30mm (ZBD-04A) · AP / HE": [("AP", "BP_ZBD04A_ZPT99_AP", 1.35), ("HE", "BP_ZBD04A_ZPT99_HEFrag", 1.69, 125, 1, 7.5, 0.08, 2)],
    "ZPT99 30mm (ZBL-08 / ZBD-05) · AP / HE": [("default", "BP_ZBL08_ZPT-99_AP", 3.5)],
    "KPVT 14.5mm": [("default", "BP_BRDM2_RUS_KPVT", 2.3)],
    "M2A1 .50": [("default", "BP_EmplacedM2_Weapon", 3)],
    "M2A1 .50 · ACOG emplacement": [("default", "BP_EmplacedM2_Weapon_ACOG", 3)],
    "NSV": [("default", "BP_EmplacedKord", 7)],
    "Kord · SPP emplacement": [("default", "BP_EmplacedKord_SPP", 7)],
    "DShK-M": [("default", "BP_EmplacedDshk", 3)],
}


def verify(resolved_path):
    """Check GAME_EXPLOSION and SQUADCALC_ONLY against the game files (resolved.json of tools/game_ballistics/collect.py):
    each Blueprint's projectile gives the row's explosion (or none for a shell without one) and its WeaponConfig the MOA.
    Prints the problems and exits with 1 if there are any."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "game_ballistics"))
    import gamecheck

    resolved = json.load(open(resolved_path))
    paths = {}
    for path in resolved:
        paths.setdefault(path.rsplit("/", 1)[-1], []).append(path)
    problems = []
    checked = 0

    def game_weapon(key, blueprint):
        if len(paths.get(blueprint, [])) != 1:
            problems.append(f"{key}: {blueprint} is not exactly one Blueprint of resolved.json")
            return None

        return resolved[paths[blueprint][0]]

    def check_explosion(key, shell, weapon, explosion):
        blast = None if not (weapon.get("projectile") or {}).get("explosion") else gamecheck.blast(weapon)
        found = None if blast is None else (blast["explosionDamage"], blast["explosionRadius"][0], blast["explosionRadius"][1],
                                            blast["explosionDistanceFromImpact"], blast["damageFallOff"])
        if explosion is None and found is not None:
            problems.append(f"{key}/{shell}: the game has an explosion {found}, the table none")
        elif explosion is not None and (found is None or any(abs(a - b) > 1e-6 for a, b in zip(found, explosion))):
            problems.append(f"{key}/{shell}: the game gives {found}, the table {explosion}")

    for key, rows in GAME_EXPLOSION.items():
        if key not in GAME_MOA:
            problems.append(f"{key}: in GAME_EXPLOSION but not in GAME_MOA")
        for shell, blueprint, *explosion in rows:
            weapon = game_weapon(key, blueprint)
            if weapon:
                check_explosion(key, shell, weapon, tuple(explosion))
                checked += 1

    for key, rows in SQUADCALC_ONLY.items():
        if key not in gamecheck.TARGETS:
            problems.append(f"{key}: not a calculator weapon of gamecheck.py TARGETS")
        for shell, blueprint, moa, *explosion in rows:
            weapon = game_weapon(key, blueprint)
            if not weapon:
                continue
            curve = (weapon["config"].get("MOACurve") or {}).get("ObjectPath")
            game_moa = gamecheck.MOA_CURVES[curve][0] if curve in gamecheck.MOA_CURVES else weapon["config"].get("MOA")
            if game_moa != moa:
                problems.append(f"{key}/{shell}: the game's MOA is {game_moa}, the table {moa}")
            check_explosion(key, shell, weapon, tuple(explosion) or None)
            checked += 1

    print("\n".join(problems) if problems else f"{checked} Blueprints agree with the game files")
    sys.exit(1 if problems else 0)


if sys.argv[1] == "--verify":
    verify(sys.argv[2])

data = json.load(open(sys.argv[1])); data.pop("_comment")
existing = set()
if len(sys.argv) > 4 and sys.argv[2] != "--update":
    source = open(sys.argv[4], encoding="utf-8").read()
    existing = {json.loads(f'"{name}"') for name in re.findall(r'ballistics:\s*"((?:[^"\\]|\\.)*)"', source)}


def ident(key):
    """DF_<name>; a renamed weapon keeps the identifier of its old name."""
    return "DF_" + re.sub(r"_+", "_", re.sub(r"[^A-Za-z0-9]", "_", OLD_NAME.get(key, key))).strip("_")


def legacy_lines(key):
    """The `legacyBallistics` line of a renamed weapon (RENAMED or EARLIER_NAME), none for any other."""
    old_name = OLD_NAME.get(key) or EARLIER_NAME.get(key)

    if old_name is None:
        return []

    return [f"        legacyBallistics: [{json.dumps(old_name, ensure_ascii=False)}],"]


def num(x):
    return json.dumps(x)


def shell_lines(shells, velocity, min_distance):
    """The `shells` property of an entry. A shell is (name, moa, explosion), the explosion being
    (damage, inner radius, outer radius, distance from the impact, falloff) or None for ...NO_EXPLOSION."""
    lines = ["        shells: [{"]
    for i, (name, moa, explosion) in enumerate(shells):
        if i:
            lines.append("        }, {")
        lines += [
            f'            name: "{name}",',
            f"            minDistance: {num(min_distance)},",
            f"            velocity: {num(velocity)},",
        ]
        if explosion is None:
            lines += ["            ...NO_EXPLOSION,", f"            moa: {num(moa)},"]
            continue
        damage, inner, outer, height, falloff = explosion
        lines += [
            f"            moa: {num(moa)},",
            f"            explosionDamage: {num(damage)},",
            f"            explosionRadius: [{num(inner)}, {num(outer)}],",
            f"            explosionDistanceFromImpact: {num(height)},",
            f"            damageFallOff: {num(falloff)},",
        ]
    lines.append("        }]")
    return lines


def game_shells(key):
    """The shells of a weapon Squad Ballistics has: its MOA, and the explosion of each ammunition if the game gives one."""
    if key not in GAME_EXPLOSION:
        return [("default", GAME_MOA[key], None)]

    return [(name, GAME_MOA[key], tuple(explosion)) for name, _, *explosion in GAME_EXPLOSION[key]]


def squadcalc_only_shells(key):
    """The shells of a weapon only SquadCalc has, from SQUADCALC_ONLY."""
    return [(name, moa, tuple(explosion) or None) for name, _, moa, *explosion in SQUADCALC_ONLY[key]]


SHELLS_BLOCK = re.compile(r"^        shells: \[\{\n.*?^        \}\]$", re.M | re.S)


def rewrite_shells(key, text):
    """The entry `text` of a weapon only SquadCalc has, its shells rebuilt from SQUADCALC_ONLY with the speed and
    minimum distance it already has."""
    block = SHELLS_BLOCK.search(text)
    velocity = json.loads(re.search(r"velocity: ([\d.]+)", block.group(0)).group(1))
    min_distance = json.loads(re.search(r"minDistance: ([\d.]+)", block.group(0)).group(1))
    return text[:block.start()] + "\n".join(shell_lines(squadcalc_only_shells(key), velocity, min_distance)) + text[block.end():]


def lob_min_distance(w):
    """Flat-ground range in metres, rounded, of a shot at the top of the hold (no key held): the
    shortest distance the hold can lob to, from the muzzle (`muzzle_forward` along the barrel and
    `muzzle_up` above its axis, the pivot `launch_height` above the ground)."""
    v, g = w["velocity"], GRAVITY * w["gravity"]
    angle = math.radians(w["hold_elevation"][1])
    up, forward = v * math.sin(angle), v * math.cos(angle)
    ahead = w.get("muzzle_forward", 0) * math.cos(angle) - w.get("muzzle_up", 0) * math.sin(angle)
    height = w.get("launch_height", 0) + w.get("muzzle_forward", 0) * math.sin(angle) + w.get("muzzle_up", 0) * math.cos(angle)
    flight = (up + math.sqrt(up * up + 2 * g * height)) / g
    return round(ahead + forward * flight)


def muzzle_lines(w):
    """The `muzzle` line of a weapon whose barrel socket is off its pivot: the shell starts `muzzle_forward`
    along the barrel and `muzzle_up` above its axis, the pivot `launch_height` above the ground (SquadCalc's
    `muzzle`, as the vehicle mortars have it). None of the other weapons has one."""
    if not (w.get("muzzle_forward") or w.get("muzzle_up")):
        return []

    return [f"        muzzle: {{ pivotHeight: {num(w.get('launch_height', 0))}, forward: {num(w.get('muzzle_forward', 0))}, up: {num(w.get('muzzle_up', 0))} }},"]


def hold_laid_entry(key, w):
    """A "deployables" entry built like SquadCalc's "AGS-17"."""
    if not key.startswith(HOLD_LAID_FAMILY):
        sys.exit(f"{key}: hold-laid, but SquadCalc only has the grenade of the {HOLD_LAID_FAMILY}")
    lim = w.get("elevation_limits", [-90, 90])
    hold = w["hold_elevation"]
    lines = [
        "    {",
        f'        name: "{ident(key)}",',
        f"        ballistics: {json.dumps(key, ensure_ascii=False)},",
        "        deceleration: 0,",
        "        decelerationTime: 0,",
        f"        gravityScale: {num(w['gravity'])},",
        f"        minElevation: [{num(lim[0])}, {num(lim[1])}],",
        f"        holdElevation: [{num(hold[0])}, {num(hold[1])}],",
        f"        elevationRate: {num(w['hold_rate'])},",
        "        projectileLifespan: 40,",
        "        heatmap: false,",
        '        unit: "sec",',
        '        type: "deployables",',
        '        angleType: "high",',
        "        elevationPrecision: 2,",
    ]
    if w.get("launch_height"):
        lines.append(f"        heightOffset: {num(w['launch_height'])},")
    lines += [
        *muzzle_lines(w),
        f'        image: "{HOLD_LAID_FAMILY}",',
        "        shells: [{",
        '            name: "default",',
        f"            minDistance: {lob_min_distance(w)},",
        f"            velocity: {num(w['velocity'])},",
        "            ...VOG_17,",
        "        }]",
        "    },",
    ]
    return lines


def direct_fire_entry(key, w):
    """A "directFire" entry: low arc only, the spread of the game weapon and the explosion of its ammunition."""
    if key not in GAME_MOA:
        sys.exit(f"{key}: no MOA in GAME_MOA (WeaponConfig.MOA of its game weapon, see tools/game_weapons.py of Squad Ballistics)")
    lines = [
        "    {",
        f'        name: "{ident(key)}",',
        f"        ballistics: {json.dumps(key, ensure_ascii=False)},",
        *legacy_lines(key),
        "        deceleration: 0,",
        "        decelerationTime: 0,",
    ]
    if w.get("acceleration") and w.get("acceleration_time"):
        lines += [f"        acceleration: {num(w['acceleration'])},", f"        accelerationTime: {num(w['acceleration_time'])},"]
    if w.get("max_speed"):
        lines.append(f"        maxSpeed: {num(w['max_speed'])},")
    if w.get("rotation_follows_velocity") is False:
        lines.append("        rotationFollowsVelocity: false,")
    lim = w.get("elevation_limits", [-90, 90])
    lines += [
        f"        gravityScale: {num(w['gravity'])},",
        f"        minElevation: [{num(lim[0])}, {num(lim[1])}],",
        '        unit: "deg",',
        '        type: "directFire",',
        '        angleType: "low",',
        "        elevationPrecision: 2,",
    ]
    if w.get("launch_height"):
        lines.append(f"        heightOffset: {num(w['launch_height'])},")
    if w.get("angle_offset"):
        lines.append(f"        angleOffset: {num(w['angle_offset'])},")
    lines += [
        *muzzle_lines(w),
        '        image: "DirectFire",',
        "        heatmap: false,",
        *shell_lines(game_shells(key), w["velocity"], w.get("min_distance", 0)),
        "    },",
    ]
    return lines


def entry(key, w):
    return hold_laid_entry(key, w) if w.get("hold_rate") else direct_fire_entry(key, w)


def update(path):
    """Rewrite the generated entries of SquadCalc's weapons.js at `path` in place."""
    raw = open(path, encoding="utf-8", newline="").read()
    newline = "\r\n" if "\r\n" in raw else "\n"
    source = raw.replace("\r\n", "\n")
    # A generated entry: from its "    {" line to the "    }," that closes it
    block = re.compile(r'^    \{\n        name: "DF_[^"]*",\n        ballistics: ("(?:[^"\\]|\\.)*"),\n.*?^    \},$', re.M | re.S)
    changed = 0

    def regenerate(match):
        nonlocal changed
        key = json.loads(match.group(1))
        key = RENAMED.get(key, key)
        if key in SQUADCALC_ONLY:
            text = rewrite_shells(key, match.group(0))
        elif key not in data:
            # A weapon Squad Ballistics no longer has: kept as it is
            print(f"kept, not in {sys.argv[1]}: {key}", file=sys.stderr)
            return match.group(0)
        else:
            text = "\n".join(entry(key, data[key]))
        changed += text != match.group(0)
        return text

    source = block.sub(regenerate, source)
    open(path, "w", encoding="utf-8", newline="").write(source.replace("\n", newline))
    print(changed)


if sys.argv[2] == "--update":
    update(sys.argv[3])
    sys.exit(0)

entries, names = [], {}
for key, w in data.items():
    arc = w.get("arc", "low")
    if w.get("aim", "elevation" if arc == "high" else "overlay") != "overlay" or key in SKIP or w.get("mod"):
        continue
    if key in existing:
        continue
    names[ident(key)] = key
    entries.append("\n".join(entry(key, w)))
open(sys.argv[2], "w").write("\n".join(entries) + "\n" if entries else "")
json.dump(names, open(sys.argv[3], "w"), ensure_ascii=False, indent=4)
print(len(entries))
