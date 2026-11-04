"""Builds data/materials.json from the extractor dumps of the physical materials and landscape layer infos.

Inputs (``SquadExtract dumpall`` JSON, see docs/collision-semantics.md):
  <dump>/SquadGame/Content/Environments/PhysicalMaterials/**   SQPhysicalMaterial assets, BP_MaterialEffects
  <dump>/Engine/Content/EngineMaterials/**                     engine physical materials
  <dump>/SquadGame/**/*LayerInfo*                              LandscapeLayerInfoObject (layer -> PhysMaterial)

Only values present in the game data are written. The game data has no lethality or splash-radius modifier per
material, so those two fields are absent (null) for every material; what exists is the penetration data of
SQPhysicalMaterial and the per-material ``bOverlapsThrowableProjectiles`` flag of BP_MaterialEffects.

Usage: materials.py <dump dir> <out materials.json>
"""
import glob
import json
import os
import re
import sys

PROPERTIES = {
    "SurfaceType": "surface_type",
    "bConsiderForPenetration": "consider_for_penetration",
    "bAllowPenetration": "allow_penetration",
    "DamageAbsorbed": "damage_absorbed",
    "ArmorThicknessMillimeters": "armor_thickness_mm",
    "bDamageParentActor": "damage_parent_actor",
    "Friction": "friction",
    "StaticFriction": "static_friction",
    "Restitution": "restitution",
    "Density": "density",
}


def exports(path):
    data = json.load(open(path))
    return data if isinstance(data, list) else []


def physical_materials(dump):
    result = {}
    for path in glob.glob(os.path.join(dump, "**", "*.uasset.json"), recursive=True):
        for export in exports(path):
            if export.get("Type") in ("SQPhysicalMaterial", "PhysicalMaterial"):
                props = export.get("Properties") or {}
                row = {"package": export.get("Package"), "class": export["Type"], "lethality_modifier": None, "splash_radius_modifier": None}
                row.update({new: props[old] for old, new in PROPERTIES.items() if old in props})
                result[export["Name"]] = row
    return result


def throwable_overlap(dump, materials):
    """bOverlapsThrowableProjectiles per material from every BP_MaterialEffects* table."""
    seen = {}
    for path in glob.glob(os.path.join(dump, "SquadGame", "Content", "Environments", "PhysicalMaterials", "BP_MaterialEffects.uasset.json")):
        for export in exports(path):
            for entry in (export.get("Properties") or {}).get("Effects") or []:
                name = re.search(r"\.([^.']+)'$", entry["Key"])
                if name:
                    seen[name.group(1)] = bool(entry["Value"].get("bOverlapsThrowableProjectiles"))
    for name, flag in seen.items():
        if name in materials:
            materials[name]["overlaps_throwable_projectiles"] = flag


def landscape_layers(dump):
    layers = {}
    for path in glob.glob(os.path.join(dump, "SquadGame", "**", "*LayerInfo*.uasset.json"), recursive=True):
        for export in exports(path):
            if export.get("Type") != "LandscapeLayerInfoObject":
                continue
            props = export.get("Properties") or {}
            material = props.get("PhysMaterial")
            asset_dir = os.path.relpath(os.path.dirname(path), os.path.join(dump, "SquadGame")).replace("Content/Maps/", "").replace("Plugins/", "")
            layers.setdefault(asset_dir, {})[props.get("LayerName", export["Name"])] = (
                re.search(r"'([^']+)'", material["ObjectName"]).group(1) if material else None)
    return layers


def main(dump, out):
    materials = physical_materials(dump)
    throwable_overlap(dump, materials)
    document = {
        "game_build": "26005357",
        "source": "dedicated server paks (SQPhysicalMaterial assets, BP_MaterialEffects, LandscapeLayerInfoObject)",
        "absent_in_game_data": ["lethality_modifier", "splash_radius_modifier"],
        "physical_materials": dict(sorted(materials.items())),
        "landscape_layer_physical_material": dict(sorted(landscape_layers(dump).items())),
    }
    json.dump(document, open(out, "w"), indent=1)
    print(len(materials), "physical materials,", sum(len(v) for v in document["landscape_layer_physical_material"].values()), "landscape layers")


if __name__ == "__main__":
    main(*sys.argv[1:3])
