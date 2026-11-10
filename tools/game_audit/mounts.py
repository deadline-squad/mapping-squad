"""Pitch range of the mount of every artillery weapon and what the game adds to it for the angle the gunner reads.

The game has no "elevation limits" of a weapon. It has the pitch range of the mount
(``RotationConstraints.PitchInterval`` of the mount's movement component, inherited along the Blueprint chain) and a
sight that shows the mount's pitch plus something: a constant in the widget's bytecode (mortar + 45, hell cannon
+ 40), the rest pitch of the bone the muzzle socket sits on (BM-21 14.2), the pitch of the muzzle or of the sight
camera on the turret (M1064 50, BTR-4 0.1). The sum is what the calculator calls ``minElevation``, and the range at
the stop of the mount is its minimum distance (``calculator.mjs``, ``check_calculator.py``).

Usage::

    python3 -I mounts.py assets                      # regex of the assets to dump, for SquadExtract dumpbytecode
    python3 -I mounts.py read <dump root> <out.json>  # the mounts of the dump, as data/mount_limits.json

``<dump root>`` is the output folder of ``SquadExtract dumpbytecode`` (it holds ``SquadGame/Content/...``).
"""
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import audit_json  # noqa: E402
import kismet  # noqa: E402

CONTENT = "SquadGame/Content/"
ANGLE_DISPLAY = ("AngleRotationDisplay", "CallFunc_BreakRotator_Pitch")
# Angles are written to 0.001 degree: the cooked values are 32-bit floats (the M1064's muzzle rests at 49.99999)
DECIMALS = 3

# SquadCalc weapon -> the assets the game keeps its mount and sight in. ``blueprints`` is the mount's Blueprint
# chain down to the class that sets the pitch range, the class the weapon sits on first (the parents are listed so
# that they are dumped; the chain itself is followed in the dump). ``sight`` lists what the reading adds to the pitch:
#   ("widget", asset, function, value)  the constant the widget's function adds to ``value`` before showing it
#   ("bone", skeleton, socket)          the rest pitch of the bone the socket is on
#   ("component", name)                 the pitch of that component of the mount's Blueprint
# ``evidence`` lists statements a widget's function must contain for the reading to be what ``sight`` says.
MOUNTS = {
    "Mortar": {
        "blueprints": ["Vehicles/BP_GenericDeployableMortarVehicle"],
        "sight": [("widget", "UI/Widgets/Vehicles/Mortar/UMG_MortarControl", "ExecuteUbergraph_UMG_MortarControl", "CachedTubePitch")],
    },
    "UB-32": {
        "blueprints": ["Vehicles/Emplaced_UB32_RocketArtillery/BP_EmplacedUB32_Tripod", "Vehicles/BP_GenericDeployableTripodVehicle"],
        "sight": [("widget", "Vehicles/Emplaced_UB32_RocketArtillery/Reticles/Emplaced_UB-32_GunnerAngleDisplay", *ANGLE_DISPLAY)],
    },
    "HellCannon": {
        "blueprints": ["Vehicles/Emplaced_HellCannon/BP_Emplaced_HellCannon_Base"],
        "sight": [("widget", "Vehicles/Emplaced_HellCannon/Reticles/UMG_HellCannon_HUD", *ANGLE_DISPLAY)],
    },
    "Tech.Mortar": {
        "blueprints": ["Vehicles/Technical2Seater/Turrets/BP_Technical_MortarTurret"],
        "sight": [("widget", "Vehicles/Technical2Seater/Weapons/UMG_MortarHUD_Technical", *ANGLE_DISPLAY)],
    },
    "Tech.UB-32": {
        "blueprints": ["Vehicles/Technical/Turrets/BP_Technical_Turret_UB32"],
        "sight": [("widget", "Vehicles/Technical/Weapons/UB-32/UB-32_GunnerAngleDisplay", *ANGLE_DISPLAY)],
    },
    "BM-21Grad": {
        "blueprints": ["Vehicles/Ural375_BM21Grad/Turrets/BP_BM21Grad_Turret_MEI", "Vehicles/Ural375_BM21Grad/Turrets/BP_BM21Grad_Turret_INS"],
        "sight": [
            ("bone", "Vehicles/Ural375_BM21Grad/Meshes/SKEL_BM21_Launcher", "Attach_Muzzle"),
            ("widget", "Vehicles/Ural375_BM21Grad/Reticles/BM21_GunnerReticle", *ANGLE_DISPLAY),
        ],
        "evidence": [("Vehicles/Ural375_BM21Grad/Reticles/BM21_GunnerReticle", "AngleRotationDisplay",
                      'CallFunc_GetSocketRotation_ReturnValue := CallFunc_GetMesh_ReturnValue.GetSocketRotation("Attach_Muzzle")')],
    },
    "M1064M121": {
        "blueprints": ["Vehicles/M1064A3/Turrets/BP_M1064A3_MortarTurret"],
        "sight": [("component", "Muzzle")],
    },
    "BTR4-AGS": {
        "blueprints": ["Vehicles/BTR4/Turrets/BP_BTR4_Turret", "Vehicles/BMP1TS_AFU/Turrets/BP_BMP1TS_Turret"],
        "sight": [("component", "FirstPersonCamera")],
        "evidence": [
            ("Vehicles/BTR4/Reticles/BTR4_GunnerReticle", "TurretRotationValues",
             "BreakRotator(Camera Rotation, CallFunc_BreakRotator_Roll_1, CallFunc_BreakRotator_Pitch_1, CallFunc_BreakRotator_Yaw_1)"),
            ("Vehicles/BTR4/Reticles/BTR4_GunnerReticle", "TurretRotationValues",
             "CallFunc_Subtract_DoubleDouble_A_ImplicitCast := cast<CST_FloatToDouble>(CallFunc_BreakRotator_Pitch_1)"),
            ("Vehicles/BTR4/Reticles/BTR4_GunnerReticle", "TurretRotationValues",
             "CallFunc_Subtract_DoubleDouble_B_ImplicitCast := cast<CST_FloatToDouble>(CallFunc_BreakRotator_Pitch)"),
        ],
    },
}


def assets():
    """Every asset ``MOUNTS`` names, as paths under ``SquadGame/Content/`` without extension, sorted."""
    named = set()
    for mount in MOUNTS.values():
        named.update(mount["blueprints"])
        named.update(part[1] for part in mount["sight"] if part[0] in ("widget", "bone"))
        named.update(asset for asset, _, _ in mount.get("evidence", []))
    return sorted(named)


def assets_regex():
    """A regex over pak paths that matches the assets of ``MOUNTS`` and the curves in the folders of their mounts."""
    exact = "|".join(re.escape(asset) for asset in assets())
    curve_folders = "|".join(sorted({re.escape(blueprint.rsplit("/", 2)[0]) for mount in MOUNTS.values() for blueprint in mount["blueprints"] if "/Turrets/" in blueprint}))
    return f"^{re.escape(CONTENT)}(?:(?:{exact})|(?:{curve_folders})/Curves/[^/]*YawToM(?:in|ax)Pitch[^/]*)\\.uasset$"


def load(root, asset):
    """The exports of one dumped asset; FileNotFoundError names the asset the dump lacks."""
    path = os.path.join(root, CONTENT + asset + ".uasset.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"the dump lacks {asset}: add it to MOUNTS and dump again")
    with open(path, encoding="utf-8") as dump:
        return json.load(dump)


def asset_of(reference):
    """Path under ``SquadGame/Content/`` of the asset an object reference of the dump points to, None for a native class."""
    path = (reference or {}).get("ObjectPath", "")
    return path[len("/Game/"):].rsplit(".", 1)[0] if path.startswith("/Game/") else None


def parent(exports):
    """Asset of the Blueprint class the dumped class derives from, None when its parent is native."""
    for export in exports:
        if export["Type"].endswith("BlueprintGeneratedClass"):
            return asset_of(export.get("Super") or export.get("SuperStruct"))
    return None


def chain(root, blueprint):
    """Yield (asset, exports) of ``blueprint`` and then of each Blueprint class above it.

    Lazy: a caller that finds its value stops, so only the classes down to the one that sets it have to be in the
    dump. Reaching a native parent ends the chain; a Blueprint parent the dump lacks raises FileNotFoundError.
    """
    while blueprint:
        exports = load(root, blueprint)
        yield blueprint, exports
        blueprint = parent(exports)


def pitch_interval(root, blueprint):
    """([lowest, highest] degrees, asset, properties of the component) of the pitch range a mount ends up with.

    A class that says nothing about the pitch keeps its parent's range, so the first class along the chain of
    ``blueprint`` with a ``PitchInterval`` decides.
    """
    for asset, exports in chain(root, blueprint):
        found = [export for export in exports if "PitchInterval" in ((export.get("Properties") or {}).get("RotationConstraints") or {})]
        if len(found) > 1:
            raise ValueError(f"{asset}: {len(found)} components with a PitchInterval ({', '.join(e['Name'] for e in found)})")
        if found:
            interval = found[0]["Properties"]["RotationConstraints"]["PitchInterval"]
            return [interval["X"], interval["Y"]], asset, found[0]
    raise ValueError(f"{blueprint}: no PitchInterval along its Blueprint chain")


def yaw_curves(root, movement):
    """{"min": keys, "max": keys} of the curves that move the pitch limits with the turret's yaw, None without them.

    ``movement`` is the properties of the component that holds the pitch range. Keys are [yaw, pitch] pairs in
    degrees (``ParentYawToMinPitch`` / ``ParentYawToMaxPitch``): the M1064's tube cannot be laid below 15 degrees
    over the rear arc of its carrier.
    """
    curves = {}
    for side, key in (("min", "ParentYawToMinPitch"), ("max", "ParentYawToMaxPitch")):
        curve = asset_of(movement.get(key))
        if curve:
            keys = next(e["Properties"]["FloatCurve"]["Keys"] for e in load(root, curve) if e["Type"] == "CurveFloat")
            curves[side] = [[round(k["Time"], 3), round(k["Value"], 3)] for k in keys]
    return curves or None


def component_pitch(root, blueprint, component):
    """(pitch in degrees, asset) of a component of a mount: ``RelativeRotation.Pitch`` of its template.

    A class that overrides the component without a rotation keeps the parent's, as with ``pitch_interval``.
    """
    for asset, exports in chain(root, blueprint):
        for export in exports:
            rotation = (export.get("Properties") or {}).get("RelativeRotation")
            if export["Name"] == component + "_GEN_VARIABLE" and rotation is not None:
                return rotation.get("Pitch", 0.0), asset
    raise ValueError(f"{blueprint}: no component {component} with a rotation along its Blueprint chain")


def quaternion_product(a, b):
    """Hamilton product of two quaternions given as (x, y, z, w): the rotation ``b`` followed by ``a``."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def quaternion_pitch(quaternion):
    """Pitch in degrees of a rotation, as ``FQuat::Rotator`` of the engine gives it (positive raises the X axis)."""
    x, y, z, w = quaternion
    return math.degrees(math.asin(max(-1.0, min(1.0, 2.0 * (z * x - w * y)))))


def bone_pitch(skeleton_exports, socket_name):
    """(pitch in degrees, bone) of the bone a socket sits on, in the reference pose of its skeleton.

    The pose of a bone is relative to its parent bone; the rotations are composed from the root down. The socket's
    own rotation relative to the bone is added by the caller when it has one.
    """
    socket = next((e["Properties"] for e in skeleton_exports if e["Type"] == "SkeletalMeshSocket" and e["Properties"].get("SocketName") == socket_name), None)
    if socket is None:
        raise ValueError(f"no socket {socket_name}")
    if any(abs(value) > 1e-3 for value in (socket.get("RelativeRotation") or {}).values()):
        raise ValueError(f"socket {socket_name} is turned on its bone: {socket['RelativeRotation']}")
    reference = next(e["ReferenceSkeleton"] for e in skeleton_exports if e["Type"] == "Skeleton")
    bones = reference["FinalRefBoneInfo"]
    index = next(i for i, bone in enumerate(bones) if bone["Name"] == socket["BoneName"])
    rotation = (0.0, 0.0, 0.0, 1.0)
    while index >= 0:
        local = reference["FinalRefBonePose"][index]["Rotation"]
        rotation = quaternion_product((local["X"], local["Y"], local["Z"], local["W"]), rotation)
        index = bones[index]["ParentIndex"]
    return quaternion_pitch(rotation), socket["BoneName"]


def sight_parts(root, blueprint, sight):
    """[{"degrees", "source"}] of what the reading adds to the pitch of the mount ``blueprint``, one entry per part of ``sight``."""
    parts = []
    for part in sight:
        if part[0] == "widget":
            _, asset, function, value = part
            degrees = kismet.added_constant(kismet.function_named(load(root, asset), function), value)
            source = f"{asset} {function}: " + (f"adds {degrees:g} to {value}" if degrees else f"shows {value} as it is")
        elif part[0] == "bone":
            _, asset, socket = part
            degrees, bone = bone_pitch(load(root, asset), socket)
            source = f"{asset}: bone {bone} of the socket {socket} rests at this pitch in the reference pose"
        else:
            _, component = part
            degrees, asset = component_pitch(root, blueprint, component)
            source = f"{asset}: RelativeRotation.Pitch of the component {component}"
        parts.append({"degrees": round(degrees, DECIMALS), "source": source})
    return parts


def check_evidence(root, evidence):
    """Raise ValueError unless every statement listed for a widget's function is in its bytecode."""
    for asset, function, statement in evidence:
        if statement not in kismet.statements(kismet.function_named(load(root, asset), function)):
            raise ValueError(f"{asset} {function} no longer contains: {statement}")


def read(root):
    """The mount of every weapon of ``MOUNTS`` from a dump: pitch range, sight offset and the range the gunner reads."""
    result = {}
    for weapon, mount in MOUNTS.items():
        blueprint = mount["blueprints"][0]
        pitch, asset, movement = pitch_interval(root, blueprint)
        check_evidence(root, mount.get("evidence", []))
        parts = sight_parts(root, blueprint, mount["sight"])
        offset = round(sum(part["degrees"] for part in parts), DECIMALS)
        entry = {
            "mount": blueprint,
            "pitch": pitch,
            "pitch_source": f"{asset}: RotationConstraints.PitchInterval of {movement['Name'].removesuffix('_GEN_VARIABLE')}",
            "sight_offset": offset,
            "sight": parts,
            "reading": [round(pitch[0] + offset, DECIMALS), round(pitch[1] + offset, DECIMALS)],
        }
        curves = yaw_curves(root, movement["Properties"])
        if curves:
            entry["pitch_by_yaw"] = curves
        result[weapon] = entry
    return result


def main(argv):
    if argv[1:] == ["assets"]:
        print(assets_regex())
    elif len(argv) == 4 and argv[1] == "read":
        audit_json.write(argv[3], read(argv[2]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
