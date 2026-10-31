"""Ballistics of Squad Ballistics' and SquadCalc's weapons from the game files.

Reads resolved.json (collect.py: every weapon Blueprint with its WeaponConfig and projectile
movement merged along the Blueprint inheritance chain) and writes:
    ballistics.json  per calculator weapon: game classes, raw game values, effective model values;
    diff.md          game vs Squad Ballistics weapons.json vs SquadCalc weapons.js: ballistics of every
                     weapon, spread, explosion and lifespan of SquadCalc's own weapons.

Effective model (the game's projectile movement as Squad Ballistics and SquadCalc fly it:
20 ms substeps, deadline-squad/squad-ballistics#4):
    v0       WeaponConfig.MuzzleVelocity (the launch speed: MK19 fires its 76 m/s UGL shell at
             230 m/s, the range everybody uses; InitializeComponent does not clamp it);
    cap      ProjectileComp.MaxSpeed when > 0 (max_speed), applied on every substep, the first one
             too: a weapon that fires faster than its projectile's cap (tank HEAT/HE 1100 m/s, cap
             850) is slowed to it at once (UProjectileMovementComponent::ComputeVelocity 0x7cf08a0);
    boost    ProjectileComp.ConstantAcceleration.X during ConstantAccelerationTimeout
             (acceleration_time), along the projectile's rotation, which follows the velocity unless
             bRotationFollowsVelocity is false (rotation_follows_velocity; ASQProjectile sets it,
             the S-5 clears it). A timeout of 0 is the whole flight; such a motor is compared as
             the time it takes to reach the cap, after which the cap holds the speed (NLAW);
    gravity  ProjectileGravityScale, 0 while bIgnoreGravityDuringConstantAcceleration boosts for
             the whole flight (NLAW).
Units: game cm -> m.
"""

import json
import math
import sys

# Calculator weapon -> game weapon classes (first is the reference; the others must agree).
TARGETS = {
    "M203 / M320 / GP-25 / HK79 / SL40": ["Blueprints/Items/GrenadeLaunchers/M4M203_UGL/BP_M4M203_UGL_Parent", "Blueprints/Items/GrenadeLaunchers/M320/BP_M320_Parent", "Blueprints/Items/GrenadeLaunchers/AK74GP25_UGL/BP_AK74GP25_UGL_Parent", "Blueprints/Items/GrenadeLaunchers/G3A3HK79_UGL/BP_G3A3HK79_UGL_HE", "Blueprints/Items/GrenadeLaunchers/EF88SL40_UGL/BP_EF88_SL40_UGL_Parent"],
    "MGL / M32": ["Blueprints/Items/GrenadeLaunchers/MGL_GL/BP_MGL_Parent", "Blueprints/Items/GrenadeLaunchers/M32/BP_M32_Parent"],
    "AK-40GL (MPT-76)": ["Blueprints/Items/GrenadeLaunchers/MPT76AK40_UGL/BP_MPT76_AK40GL_UGL_Parent"],
    "QLG10": ["Blueprints/Items/GrenadeLaunchers/QBZ-95-1_QLG-10_UGL/BP_QBZ95-1_QLG-10_UGL_Parent"],
    "Rifle grenade": ["Blueprints/Items/GrenadeLaunchers/FNFAL_GL/BP_FNFAL_GL_Frag", "Blueprints/Items/GrenadeLaunchers/FNFAL_GL/BP_FNFAL_GL_HEAT"],
    "MK19": ["Vehicles/M1117/Weapons/BP_M1117_MK19", "Vehicles/AAVP7A1/Weapons/BP_AAVP7A1_MK19", "Vehicles/RHIB/Weapons/BP_Mk19_RHIB_Weapon", "Vehicles/Emplaced_Mk19/BP_Mk19_OpenTurret_Weapon"],
    "MK19 · emplacement / C16 / L134A1": ["Vehicles/Emplaced_Mk19/BP_Mk19_Weapon", "Vehicles/Emplaced_Mk19/BP_Weapon_C16", "Vehicles/Emplaced_Mk19/BP_Weapon_L134A1"],
    "AGS-17 · emplacement · optic (RMB ×2.5)": ["Vehicles/Emplaced_AGS-17/BP_AGS-17_Weapon", "Vehicles/Emplaced_AGS-17/BP_AGS-17_Weapon_Optic"],
    "QLZ87 · optic (RMB ×3)": ["Blueprints/Items/GrenadeLaunchers/QLZ-87/BP_QLZ-87_AGL_Parent", "Vehicles/Emplaced_QLZ87/BP_QLZ87_Weapon", "Vehicles/CSK131/Weapons/BP_QLZ87_OpenTurret_Weapon"],
    "AGS-30 / BTR-4 AGS": ["Vehicles/BTR4/Weapons/BP_BTR4_KBA117", "Vehicles/BMP-2M/Weapons/Woodland/BP_BMP2M_AGS30", "Vehicles/BMP1TS_AFU/Weapons/BP_BMP1TS_KBA117"],
    "M72A7 LAW / RPG-26": ["Blueprints/Items/RocketLaunchers/BP_M72A7_M72A5_2mags", "Blueprints/Items/RocketLaunchers/BP_RPG26_2mags", "Blueprints/Items/RocketLaunchers/BP_HAR66_2mags"],
    "AT-4": ["Blueprints/Items/RocketLaunchers/BP_M136AT4"],
    "MK153 SMAW": ["Blueprints/Items/RocketLaunchers/SMAW/BP_SMAW_HEAT_2mags", "Blueprints/Items/RocketLaunchers/SMAW/BP_SMAW_Tandem_2mags"],
    "PF98 · Tandem": ["Blueprints/Items/RocketLaunchers/PF-98/BP_PF-98_Tandem_2mags"],
    "PF98 · HE-I": ["Blueprints/Items/RocketLaunchers/PF-98/BP_PF-98_HE_2mags"],
    "RPG-29": ["Blueprints/Items/RocketLaunchers/BP_RPG29"],
    "RPG-7 · PG-7V HEAT / OG-7V": ["Blueprints/Items/RocketLaunchers/BP_RPG7_Heat", "Blueprints/Items/RocketLaunchers/BP_RPG7_Frag"],
    "RPG-7 · PG-7VR Tandem": ["Blueprints/Items/RocketLaunchers/BP_RPG7_Tandem"],
    "RPG-7 · TBG-7V Thermobaric": ["Blueprints/Items/RocketLaunchers/BP_RPG7_Thermo"],
    "RPG-7V1 · HEAT": ["Blueprints/Items/RocketLaunchers/BP_RPG7V1_Heat", "Blueprints/Items/RocketLaunchers/BP_RPG7V1_Frag"],
    "M3 MAAWS · HEAT / Smoke": ["Blueprints/Items/RocketLaunchers/M3MAAWS/BP_M3MAAWS_Heat", "Blueprints/Items/RocketLaunchers/M3MAAWS/BP_M3MAAWS_Smoke"],
    "M3 MAAWS · Tandem": ["Blueprints/Items/RocketLaunchers/M3MAAWS/BP_M3MAAWS_Tandem"],
    "Carl Gustav M2 · FFV551 HEAT": ["Blueprints/Items/RocketLaunchers/BP_CarlGustavM2_Parent"],
    "Carl Gustav M2 · FFV441D HE": ["Blueprints/Items/RocketLaunchers/BP_CarlGustavM2_FFV441D_No78Mk1"],
    "Carl Gustav M2 · FFV751 Tandem": ["Blueprints/Items/RocketLaunchers/BP_CarlGustavM2_FFV751_No78Mk1"],
    "NLAW": ["Blueprints/Items/RocketLaunchers/NLAW/BP_NLAW"],
    "SPG-9 · HEAT": ["Vehicles/Emplaced_SPG9/BP_EmplacedSPG9", "Vehicles/Technical/Weapons/BP_SPG9"],
    "SPG-9 · FRAG": ["Vehicles/Emplaced_SPG9/BP_EmplacedSPG9_Frag", "Vehicles/Technical/Weapons/BP_SPG9_Frag"],
    "2A28 Grom (BMP-1 / BMD-1) · HEAT": ["Vehicles/BMP-1/Weapons/BP_BMP1_2A28_HEAT", "Vehicles/BMD-1M/Weapons/BP_BMD1M_2A28_HEAT"],
    "2A28 Grom (BMP-1 / BMD-1) · FRAG": ["Vehicles/BMP-1/Weapons/BP_BMP1_2A28_Frag", "Vehicles/BMD-1M/Weapons/BP_BMD1M_2A28_Frag"],
    "2A70 100mm (BMP-3 / BMD-4 / ZBD04A) · FRAG": ["Vehicles/BMP-3M/Weapons/BP_BMP3M_2A70_HEFrag", "Vehicles/BMD-4M/Weapons/BP_BMD4M_2A70_HEFrag", "Vehicles/ZBD04A/Weapons/BP_ZBD04A_2A70_HEFrag"],
    "ZiS-3 · optic (RMB ×4)": ["Vehicles/Emplaced_ZiS3_Cannon/Weapons/BP_ZiS3_Weapon_HEAT", "Vehicles/Emplaced_ZiS3_Cannon/Weapons/BP_ZiS3_Weapon_Frag"],
    "Tank AP · 2A46 / ZPT98 / 2A20 / 2A45 / KBA3": ["Vehicles/T72B3/Weapons/BP_2A46_AP", "Vehicles/T90A/Weapons/BP_2A46M_AP", "Vehicles/ZTZ99/Weapons/BP_ZPT-98_AP", "Vehicles/T62/Weapons/BP_2A20_AP", "Vehicles/Sprut-SDM1/Weapons/BP_2A45_AP", "Vehicles/T64_BM2/Weapons/BP_KBA3_AP"],
    "Tank AP · M256 / Rh120": ["Vehicles/M1A2/Weapons/BP_M256A1_AP", "Vehicles/Leopard2/Weapons/BP_L55_AP", "Vehicles/M60T/Weapons/BP_MG253_AP"],
    "Tank AP · L30A1 (Challenger 2) / M68A2": ["Vehicles/FV4034/Weapons/BP_L30A1_AP", "Vehicles/M1128_MGS/Weapons/BP_M68A2_AP"],
    "Tank HEAT/HE · M256 / Rh120 / 2A46 / ZPT98 / 2A20 / M68A2": ["Vehicles/T72B3/Weapons/BP_2A46_HEAT", "Vehicles/M1A2/Weapons/BP_M256A1_HEAT", "Vehicles/Leopard2/Weapons/BP_L55_HEAT", "Vehicles/T72B3/Weapons/BP_2A46_Frag", "Vehicles/ZTZ99/Weapons/BP_ZPT-98_HEAT", "Vehicles/T62/Weapons/BP_2A20_HEAT", "Vehicles/M1128_MGS/Weapons/BP_M68A2_HEAT", "Vehicles/M1128_MGS/Weapons/BP_M68A2_HESH", "Vehicles/M60T/Weapons/BP_MG253_Frag"],
    "Tank HESH · L30A1 (Challenger 2)": ["Vehicles/FV4034/Weapons/BP_L30A1_HESH", "Vehicles/FV4034/Weapons/BP_L30A1_Smoke"],
    "ZPL-98A 105mm (ZTD-05) · AP": ["Vehicles/ZTD05/Weapons/BP_ZTD05_ZPL-98A_AP"],
    "ZPL-98A 105mm (ZTD-05) · HEAT / HE": ["Vehicles/ZTD05/Weapons/BP_ZTD05_ZPL-98A_HEAT", "Vehicles/ZTD05/Weapons/BP_ZTD05_ZPL-98A_Frag"],
    "M242 Bushmaster 25mm · AP": ["Vehicles/LAV25/Weapons/LAV25_M252_AP", "Vehicles/BFV/Weapons/BFV_M252_AP", "Vehicles/ACV-15/Weapons/ACV_M252_AP"],
    "M242 Bushmaster 25mm · HE": ["Vehicles/LAV25/Weapons/LAV25_M252_HE", "Vehicles/BFV/Weapons/BFV_M252_HE", "Vehicles/ACV-15/Weapons/ACV_M252_HE"],
    "2A42 / 2A72 30mm · AP": ["Vehicles/BMP-2/Weapons/BP_BMP2_2A42_AP", "Vehicles/BMD-4M/Weapons/BP_BMD4M_2A72_AP", "Vehicles/BTR80/82A/Weapons/BP_BTR82A_RUS_2A72_AP"],
    "2A42 30mm (BMP-2) · HE": ["Vehicles/BMP-2/Weapons/BP_BMP2_2A42_HE", "Vehicles/BMP-2/Weapons/BP_BMP2_GFI_2A42_HE"],
    "2A72 30mm (BMD-4M) · HE": ["Vehicles/BMD-4M/Weapons/BP_BMD4M_2A72_HE"],
    "2A72 30mm (BMP-3M) · AP / HE": ["Vehicles/BMP-3M/Weapons/BP_BMP3M_2A72_AP", "Vehicles/BMP-3M/Weapons/BP_BMP3M_2A72_HE"],
    "L21A1 RARDEN 30mm · AP": ["Vehicles/FV510/Weapons/BP_Warrior_Rarden_AP", "Vehicles/FV107/Weapons/BP_Scimitar_Rarden_AP"],
    "L21A1 RARDEN 30mm · HE": ["Vehicles/FV510/Weapons/BP_Warrior_Rarden_HE", "Vehicles/FV107/Weapons/BP_Scimitar_Rarden_HE"],
    "CTAS40 40mm · AP": ["Vehicles/FV510_40mm/Weapons/BP_Warrior_CTAS_AP"],
    "CTAS40 40mm · GP": ["Vehicles/FV510_40mm/Weapons/BP_Warrior_CTAS_HE"],
    "ZPT99 30mm (ZBL-08) · APFSDS": ["Vehicles/ZBL08/Weapons/BP_ZBL08_ZPT-99_APFSDS"],
    "ZPT99 30mm (ZBD-04A) · AP / HE": ["Vehicles/ZBD04A/Weapons/BP_ZBD04A_ZPT99_AP", "Vehicles/ZBD04A/Weapons/BP_ZBD04A_ZPT99_HEFrag"],
    "ZPT99 30mm (ZBL-08 / ZBD-05) · AP / HE": ["Vehicles/ZBL08/Weapons/BP_ZBL08_ZPT-99_AP", "Vehicles/ZBL08/Weapons/BP_ZBL08_ZPT-99_HEFrag", "Vehicles/ZBD05/Weapons/BP_ZBD05_ZPT-99_HE"],
    "KPVT 14.5mm": ["Vehicles/BRDM-2/Weapons/BP_BRDM2_RUS_KPVT", "Vehicles/BTR80/Attachments/BP_BTR80_RUS_KPVT"],
    "M2A1 .50": ["Vehicles/Emplaced50cal/BP_EmplacedM2_Weapon", "Vehicles/M1151/Weapons/BP_50Cal_M1151", "Vehicles/Technical/Weapons/BP_M2_Technical"],
    "M2A1 .50 · ACOG emplacement": ["Vehicles/Emplaced50cal/BP_EmplacedM2_Weapon_ACOG"],
    "NSV": ["Vehicles/Emplaced_Kord/BP_EmplacedKord", "Vehicles/RHIB/Weapons/BP_NSV_RHIB_Weapon", "Vehicles/T72B3/Weapons/BP_Kord_Cupola_Weapon"],
    "Kord · SPP emplacement": ["Vehicles/Emplaced_Kord/BP_EmplacedKord_SPP"],
    "DShK-M": ["Vehicles/Emplaced_Dshk/BP_EmplacedDshk", "Vehicles/Technical/Weapons/BP_DShK_Technical", "Vehicles/Emplaced_QJZ-89/BP_EmplacedQJZ-89"],
    "Mortar (M252 / 2B14 / L16 / Type 63)": ["Vehicles/BP_GenericMortarWeapon"],
    "Technical Mortar": ["Vehicles/Technical2Seater/Weapons/BP_Technical_M1937mortar", "Vehicles/Technical2Seater_WPMC/Weapons/BP_Technical_M252mortar"],
    "M1064 M121 (120mm)": ["Vehicles/M1064A3/Weapons/BP_M1064A3_M121mortar", "Vehicles/M1064A3/Weapons/BP_M1064A3_M121mortar_Airburst"],
    "Hell Cannon": ["Vehicles/Emplaced_HellCannon/BP_Emplaced_HellCannon"],
    "UB-32 (S-5 rockets)": ["Vehicles/Emplaced_UB32_RocketArtillery/BP_EmplacedUB32", "Vehicles/BRDM-2/Weapons/BP_BRDM2_GFI_UB32"],
    "Technical UB-32": ["Vehicles/Technical/Weapons/BP_UB32"],
    "BM-21 Grad": ["Vehicles/Ural375_BM21Grad/Weapons/BP_BM21Grad_Weapon_MEI"],
}

# Squad Ballistics names before this check, for the diff against the current files.
RENAMED = {
    "M203 / M320 / GP-25 / HK79 / SL40": "M203 / M320 / GP-25 / HK79 / MKE MGL",
    "MK19": "MK19 / AGS-17 / AGS-30",
    "AGS-30 / BTR-4 AGS": "BTR-4 AGS",
    "M3 MAAWS · HEAT / Smoke": "Carl Gustav / M3 MAAWS · HEAT",
    "M3 MAAWS · Tandem": "Carl Gustav / M3 MAAWS · Tandem",
    "Tank AP · 2A46 / ZPT98 / 2A20 / 2A45 / KBA3": "Tank AP · 2A46 / ZPT98 / 2A20 / M68A2",
    "Tank AP · L30A1 (Challenger 2) / M68A2": "Tank AP · L30A1 (Challenger 2)",
    "2A42 30mm (BMP-2) · HE": "2A42 / 2A72 30mm · HE",
    "ZPT99 30mm (ZBL-08) · APFSDS": "ZPT99 30mm · AP",
    "ZPT99 30mm (ZBD-04A) · AP / HE": "ZPT99 30mm · HE",
}

# SquadCalc weapons that are not generated from Squad Ballistics (name -> calculator weapon).
SQUADCALC = {
    "Mortar": "Mortar (M252 / 2B14 / L16 / Type 63)",
    "UB-32": "UB-32 (S-5 rockets)",
    "HellCannon": "Hell Cannon",
    "Tech.Mortar": "Technical Mortar",
    "Tech.UB-32": "Technical UB-32",
    "BM-21Grad": "BM-21 Grad",
    "M1064M121": "M1064 M121 (120mm)",
    "Mk19": "MK19",
    "BTR4-AGS": "AGS-30 / BTR-4 AGS",
    "AGS-17": "AGS-17 · emplacement · optic (RMB ×2.5)",
}


def effective(weapon):
    """Model values of one resolved weapon, see the module docstring."""
    config = weapon["config"]
    projectile = weapon.get("projectile") or {}
    move = projectile.get("movement") or {}
    v0 = config["MuzzleVelocity"] / 100
    max_speed = (move.get("MaxSpeed") or 0) / 100
    accel = ((move.get("ConstantAcceleration") or {}).get("X") or 0) / 100
    timeout = move.get("ConstantAccelerationTimeout") or 0
    gravity = move.get("ProjectileGravityScale", 1.0)
    follows = move.get("bRotationFollowsVelocity", True)
    boost_time = 0.0
    if accel:
        boost_time = timeout if timeout > 0 else math.inf
        if timeout <= 0 and accel > 0 and max_speed:
            boost_time = max(0.0, (max_speed - v0) / accel)
    if move.get("bIgnoreGravityDuringConstantAcceleration") and accel and timeout == 0:
        gravity = 0.0
    if boost_time <= 0 or not accel:
        accel, boost_time = 0.0, 0.0
    return {
        "velocity": round(v0, 3),
        "gravity": gravity,
        "acceleration": round(accel, 3),
        "acceleration_time": round(boost_time, 4) if math.isfinite(boost_time) else None,
        "max_speed": round(max_speed, 3),
        # Only a motor turns with the projectile: compared for boosted ones
        "rotation_follows_velocity": bool(follows) if accel else None,
        "lifespan_s": projectile.get("life") or None,
        "moa": config.get("MOA"),
        "moa_curve": (config.get("MOACurve") or {}).get("ObjectPath"),
    }


# ASQProjectile explosion defaults: native (C++) values that no Blueprint in the paks shows. Inferred from
# the projectiles that override only some fields, whose remaining values in SquadCalc (taken from the SDK)
# all agree on these: the S-5 rocket overrides only the outer radius (SquadCalc 115, 5-18 m, falloff 1,
# 0.2 m), the MK19 grenade only the inner radius and the height (115, 1-15 m, falloff 1, 0.08 m).
NATIVE_EXPLOSION = {"ExplosiveBaseDamage": 115.0, "ExplosiveDamageInnerRadius": 500.0, "ExplosiveDamageOuterRadius": 1500.0,
                    "ExplosiveDamageFalloff": 1.0, "ExplosiveDamageDistanceFromImpactNormal": 20.0,
                    "bUseSecondaryExplosion": False}


# WeaponConfig.MOACurve assets (CurveFloat, Squad build 26005357): MOA from the weapon's dynamic MOA
# (0 at rest, grown by each shot, decayed between bursts; native code) -> (at rest, sustained). A weapon
# with a curve spreads by it, not by its base MOA; SquadCalc draws the sustained value, the envelope of a burst.
MOA_CURVES = {
    "/Game/Vehicles/FC_MOACurve_GenericGMG.0": (15.0, 50.0),
    "/Game/Vehicles/FC_MOACurve_GenericGPMG.0": (3.0, 65.0),
    "/Game/Vehicles/FC_MOACurve_GenericHMG.0": (3.0, 65.0),
    "/Game/Vehicles/Emplaced_Kord/Curves/FC_MOACurve_Kord.0": (7.0, 150.0),
}


def blast(weapon):
    """Spread and the explosion SquadCalc draws (the widest one that deals damage), in SquadCalc's units.

    Returns {"moa" (the sustained value of the MOACurve when the weapon has one), "explosionDamage", "explosionRadius" [inner, outer] m, "explosionDistanceFromImpact" m,
    "damageFallOff", "lifespan_s", "native": [fields taken from NATIVE_EXPLOSION]}.
    """
    projectile = weapon.get("projectile") or {}
    found = projectile.get("explosion") or {}
    values = {**NATIVE_EXPLOSION, **found}
    explosions = [(values["ExplosiveBaseDamage"], values["ExplosiveDamageInnerRadius"], values["ExplosiveDamageOuterRadius"],
                   values["ExplosiveDamageDistanceFromImpactNormal"], values["ExplosiveDamageFalloff"], "primary")]
    if values["bUseSecondaryExplosion"]:
        explosions.append((values["SecondaryExplosionBaseDmg"], values["SecondaryExplosionInnerRadius"],
                           values["SecondaryExplosionOuterRadius"], values["SecondaryExplosionDistanceFromImpact"],
                           values["SecondaryExplosionDamageFalloff"], "secondary"))
    damage, inner, outer, height, falloff, which = max((e for e in explosions if e[0] > 0), key=lambda e: e[2])
    prefix = "Explosive" if which == "primary" else "SecondaryExplosion"
    curve = (weapon["config"].get("MOACurve") or {}).get("ObjectPath")
    return {
        "moa": MOA_CURVES[curve][1] if curve in MOA_CURVES else weapon["config"].get("MOA"),
        "explosionDamage": damage,
        "explosionRadius": [inner / 100, outer / 100],
        "explosionDistanceFromImpact": height / 100,
        "damageFallOff": round(falloff, 4),
        "lifespan_s": projectile.get("life") or None,
        "explosion": which,
        "native": sorted(k for k in NATIVE_EXPLOSION if k not in found and k.startswith(prefix)),
    }


def blast_rows(name, classes, resolved, calc_weapon):
    """Markdown rows where SquadCalc's spread, explosion or lifespan differ from the game.

    Shell i of the SquadCalc weapon is compared with game class i when both have as many entries
    (M1064: impact and airburst), otherwise every shell with the first class and the other classes
    are listed where they differ from it (MK19: the RHIB and open turret spread less than the RWS).
    """
    rows = []
    shells = calc_weapon["shells"]
    for i, shell in enumerate(shells):
        cls = classes[i] if len(shells) == len(classes) else classes[0]
        game = blast(resolved[cls])
        native = f" (native default: {', '.join(game['native'])})" if game["native"] else ""
        for field in ("moa", "explosionDamage", "explosionRadius", "explosionDistanceFromImpact", "damageFallOff"):
            g, c = game[field], shell.get(field)
            pairs = list(zip(g, c)) if isinstance(g, list) else [(g, c)]
            if all(c is not None and abs(float(b) - float(a)) <= max(1e-3, abs(a) * 1e-3) for a, b in pairs):
                continue
            rows.append(f"| {name} | {shell['name']} | {field} | {g} ({game['explosion']}){native} | {c} |")
        life = calc_weapon.get("projectileLifespan")
        if i == 0 and game["lifespan_s"] and life != game["lifespan_s"]:
            rows.append(f"| {name} | | projectileLifespan | {game['lifespan_s']} | {life if life is not None else '— (100)'} |")
    if len(shells) == len(classes):
        return rows
    for cls in classes[1:]:
        if blast(resolved[cls]) != blast(resolved[classes[0]]):
            differing = {k: v for k, v in blast(resolved[cls]).items() if blast(resolved[classes[0]])[k] != v}
            rows.append(f"| {name} | | variant `{cls}` | {json.dumps(differing)} | |")
    return rows


def raw(weapon):
    config = weapon["config"]
    projectile = weapon.get("projectile") or {}
    move = projectile.get("movement") or {}
    return {
        "weapon_class": weapon["chain"][-1],
        "projectile_class": (projectile.get("chain") or [None])[-1],
        "MuzzleVelocity_cm_s": config.get("MuzzleVelocity"),
        "MOA": config.get("MOA"),
        "InitialSpeed_cm_s": move.get("InitialSpeed"),
        "MaxSpeed_cm_s": move.get("MaxSpeed"),
        "ProjectileGravityScale": move.get("ProjectileGravityScale"),
        "ConstantAcceleration_cm_s2": (move.get("ConstantAcceleration") or {}).get("X"),
        "ConstantAccelerationTimeout_s": move.get("ConstantAccelerationTimeout"),
        "bIgnoreGravityDuringConstantAcceleration": move.get("bIgnoreGravityDuringConstantAcceleration", False),
        "InitialLifeSpan_s": projectile.get("life"),
        "explosion": projectile.get("explosion"),
    }


# The model values compared between the game, Squad Ballistics and SquadCalc
BALLISTIC_FIELDS = ("velocity", "gravity", "acceleration", "acceleration_time", "max_speed", "rotation_follows_velocity")


def main(resolved_path, sb_path, squadcalc_path, out_json, out_md):
    resolved = {k.replace("/Game/", "", 1): v for k, v in json.load(open(resolved_path)).items()}
    by_base = {}
    for key in resolved:
        by_base.setdefault(key.rsplit("/", 1)[-1], []).append(key)
    for name, classes in TARGETS.items():
        # Targets may name a class by its file name alone when it is unique in the game
        TARGETS[name] = [c if c in resolved or len(by_base.get(c.rsplit("/", 1)[-1], [])) != 1
                         else by_base[c.rsplit("/", 1)[-1]][0] for c in classes]
    sb = json.load(open(sb_path))
    calc = {w["name"]: w for w in json.load(open(squadcalc_path))}
    calc_by_ballistics = {w.get("ballistics"): w for w in calc.values() if w.get("ballistics") and w["name"].startswith("DF_")}
    report = {}
    for name, classes in TARGETS.items():
        missing = [c for c in classes if c not in resolved]
        if missing:
            raise SystemExit(f"{name}: not in resolved.json: {missing}")
        values = [effective(resolved[c]) for c in classes]
        ballistic = BALLISTIC_FIELDS
        disagree = [classes[i] for i, v in enumerate(values) if any(v[k] != values[0][k] for k in ballistic)]
        report[name] = {"game": values[0], "variants_differing": {c: effective(resolved[c]) for c in disagree},
                        "sources": [raw(resolved[c]) for c in classes]}
    json.dump({"build": "Squad dedicated server 26005357 (2026-10-17 manifest)", "model": __doc__, "weapons": report},
              open(out_json, "w"), indent=1, ensure_ascii=False)

    rows = []
    for name, entry in report.items():
        game = entry["game"]
        old = sb.get(name) or sb.get(RENAMED.get(name, name)) or {}
        sc = (calc_by_ballistics.get(name) or calc_by_ballistics.get(RENAMED.get(name, name))) or next((calc[k] for k, v in SQUADCALC.items() if v == name and k in calc), None)
        sc_vals = {}
        if sc:
            sc_vals = {"velocity": sc["shells"][0]["velocity"], "gravity": sc.get("gravityScale"),
                       "acceleration": sc.get("acceleration", 0) or (-sc.get("deceleration", 0) if sc.get("deceleration") else 0),
                       "acceleration_time": sc.get("accelerationTime", 0) or sc.get("decelerationTime", 0) or 0,
                       "max_speed": sc.get("maxSpeed", 0),
                       "rotation_follows_velocity": sc.get("rotationFollowsVelocity", True)}
        sb_vals = {"velocity": old.get("velocity"), "gravity": old.get("gravity"),
                   "acceleration": old.get("acceleration", 0), "acceleration_time": old.get("acceleration_time", 0),
                   "max_speed": old.get("max_speed", 0),
                   "rotation_follows_velocity": old.get("rotation_follows_velocity", True)}
        for field in BALLISTIC_FIELDS:
            if field == "rotation_follows_velocity":
                if game[field] is None:
                    continue
                if game[field] == sb_vals[field] and (not sc or game[field] == sc_vals[field]):
                    continue
                rows.append(f"| {name} | {field} | {game[field]} | {sb_vals[field] if old else '—'} | {sc_vals[field] if sc else '—'} |")
                continue
            g = game[field] if game[field] is not None else "∞"
            s = sb_vals.get(field) if old else "—"
            c = sc_vals.get(field, "—") if sc else "—"
            same = lambda x: x != "—" and x is not None and isinstance(g, (int, float)) and abs(float(x) - g) <= max(1e-3, abs(g) * 1e-3)
            if same(s) and (c == "—" or same(c)):
                continue
            if not old and field != "velocity" and g in (0, 0.0):
                continue
            rows.append(f"| {name} | {field} | {g} | {s} | {c} |")
    lines = [
        "# Game ballistics vs Squad Ballistics and SquadCalc",
        "",
        "Generated by `~/tools/squadweapons/py/gamecheck.py` from the Squad dedicated server build 26005357.",
        "Only rows that differ are listed; `—` = the calculator has no such weapon/field.",
        "Squad Ballistics names on the left are the corrected ones; renamed entries are compared with their old name:",
        "",
        *[f"- {new} ← {old}" for new, old in RENAMED.items()],
        "",
        "| Weapon | Field | Game | Squad Ballistics | SquadCalc |",
        "|---|---|---|---|---|",
        *rows,
        "",
        "## Variants inside one calculator weapon that differ in the game",
        "",
    ]
    for name, entry in report.items():
        for cls, v in entry["variants_differing"].items():
            lines.append(f"- {name}: `{cls}` → {json.dumps({k: v[k] for k in BALLISTIC_FIELDS})}")
    lines += [
        "",
        "## Spread, explosion and lifespan of SquadCalc's own weapons",
        "",
        "Explosion = the widest one that deals damage (`blast()`); radii and height in metres.",
        "",
        "| Weapon | Shell | Field | Game | SquadCalc |",
        "|---|---|---|---|---|",
    ]
    blast_count = 0
    for calc_name, name in SQUADCALC.items():
        if calc_name in calc:
            found = blast_rows(name, TARGETS[name], resolved, calc[calc_name])
            blast_count += len(found)
            lines += found
    open(out_md, "w").write("\n".join(lines) + "\n")
    print(f"{len(report)} weapons, {len(rows)} differing ballistic fields, {blast_count} differing blast fields")


if __name__ == "__main__":
    main(*sys.argv[1:])
