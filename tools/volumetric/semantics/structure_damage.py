"""Damage of shells to player-built structures (deployables), from the dedicated-server data (build 26005357).

Inputs (``SquadExtract dumpall`` JSON, see docs/structure-damage.md section 8):
  <dump>/SquadGame/Content/Gameplay/{Deployables,FOBs,DamageTypes}, Blueprints/Items/Projectiles, Vehicles/...  Blueprints
  <files.txt>                  ``SquadExtract list ""`` (every pak path)
Class defaults are merged along the Blueprint ``Super`` chain by ``tools/game_ballistics/resolve.py``.

Subcommands
  meshes <dump> <files> <out dir>     writes meshes.txt (object paths for ``SquadExtract meshsections``) and
                                      materials.txt (override material instances to dump)
  build  <dump> <files> <sections.ndjson> <materials.json> <ballistics.json> <out json>
                                      writes data/structure_damage.json (a field a projectile Blueprint does not override
                                      is absent from its row; ``native_defaults_used`` names the explosion fields that fall
                                      back to the C++ defaults of game_ballistics/gamecheck.py NATIVE_EXPLOSION, INFERRED)
  export <structure_damage.json> <out js>
                                      writes SquadCalc's src/data/structureDamage.js (deployables grouped by identical
                                      health and damage-type table, projectiles with their native defaults filled in)
"""
import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "game_ballistics"))
from gamecheck import NATIVE_EXPLOSION  # noqa: E402
from resolve import Dump, class_path  # noqa: E402

DEPLOYABLE_DIRS = ("Gameplay/Deployables/", "Gameplay/FOBs/")
DAMAGE_TYPE_FIELDS = ("Modifier", "DirectHitDamageMultiplier", "IndirectHitDamageMultiplier", "DirectHitRadialDamageMultiplier",
                      "bOnlyPassDamageIfDirectHit", "bForwardDamageToSoldier", "ForwardDamageToSoldierModifier")
PROJECTILE_FIELDS = ("DamageTypeToApply", "ImpactDamageToApply", "ExplosiveBaseDamage", "ExplosiveMinimumDamage",
                     "ExplosiveKillZoneRadius", "ExplosiveDamageInnerRadius", "ExplosiveDamageOuterRadius",
                     "ExplosiveDamageFalloff", "ExplosiveDamageDistanceFromImpactNormal", "bUseSecondaryExplosion",
                     "SecondaryExplosionBaseDmg", "SecondaryExplosionMinDamage", "SecondaryExplosionInnerRadius",
                     "SecondaryExplosionOuterRadius", "SecondaryExplosionDamageFalloff", "SecondaryExplosionDistanceFromImpact",
                     "SecondaryOnlyDamageMeshes")


def short(reference):
    """'/Game/Gameplay/DamageTypes/BP_X.0' reference -> 'BP_X'; a native class ('/Script/Squad') -> its class name."""
    if not reference:
        return None
    if reference["ObjectPath"].startswith("/Script/"):
        return re.search(r"'([^']+)'$", reference["ObjectName"]).group(1)
    return reference["ObjectPath"].rsplit("/", 1)[-1].rsplit(".", 1)[0]


def deployable_classes(dump):
    """Package paths (/Game/...) of every Blueprint under the deployable directories."""
    classes = []
    for pak in dump.files:
        if pak.startswith("SquadGame/Content/") and any(d in pak for d in DEPLOYABLE_DIRS) \
                and os.path.exists(os.path.join(dump.root, pak + ".json")):
            exports = dump.exports(pak)
            if any(e.get("Type") == "BlueprintGeneratedClass" for e in exports):
                classes.append("/Game/" + pak[len("SquadGame/Content/"):-len(".uasset")])
    return sorted(classes)


def completed_meshes(dump, class_package):
    """Static meshes under the ``Completed`` scene component along the class chain.

    Returns [{"mesh": object path, "overrides": [material object path or None], "component": name}].
    """
    result = []
    for package, _ in dump.chain(class_package):
        exports = dump.exports(dump.file_of(package)) or []
        nodes = {}
        for e in exports:
            if e.get("Type") == "SCS_Node":
                p = e.get("Properties", {})
                template = (p.get("ComponentTemplate") or {}).get("ObjectName", "")
                nodes[p.get("InternalVariableName")] = (p.get("ParentComponentOrVariableName"), template.rsplit(":", 1)[-1].rstrip("'"))
        templates = {e["Name"]: e.get("Properties", {}) for e in exports if e.get("Type") == "StaticMeshComponent"}
        for variable, (_, template) in nodes.items():
            if template not in templates or not templates[template].get("StaticMesh"):
                continue
            ancestor, seen = variable, set()
            while ancestor in nodes and ancestor not in seen:
                seen.add(ancestor)
                ancestor = nodes[ancestor][0]
            if ancestor != "Completed":
                continue
            p = templates[template]
            result.append({"mesh": p["StaticMesh"]["ObjectPath"].rsplit(".", 1)[0], "component": variable,
                           "overrides": [(m or {}).get("ObjectPath", "").rsplit(".", 1)[0] or None for m in p.get("OverrideMaterials") or []]})
    return result


def meshes_command(dump_dir, files, out_dir):
    dump = Dump(dump_dir, files)
    meshes, materials = set(), set()
    for cls in deployable_classes(dump):
        for item in completed_meshes(dump, cls):
            name = item["mesh"].rsplit("/", 1)[-1]
            meshes.add(f"{item['mesh']}.{name}")
            materials.update(m for m in item["overrides"] if m)
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "meshes.txt"), "w").write("\n".join(sorted(meshes)) + "\n")
    open(os.path.join(out_dir, "materials.txt"), "w").write("\n".join(sorted(materials)) + "\n")
    print(len(meshes), "meshes,", len(materials), "override materials")


def material_physics(dump_dir, path):
    """Physical material object path of a material instance: its own, else the nearest parent's (dumped JSON)."""
    seen = set()
    while path and path not in seen:
        seen.add(path)
        pak = "SquadGame/Content/" + path[len("/Game/"):] + ".uasset.json"
        target = os.path.join(dump_dir, pak)
        if not os.path.exists(target):
            return None
        for e in json.load(open(target)):
            p = e.get("Properties") or {}
            if e.get("Type") in ("MaterialInstanceConstant", "Material") and e.get("Name") == os.path.basename(path):
                if p.get("PhysMaterial"):
                    return short(p["PhysMaterial"])
                path = class_path(p.get("Parent")) if p.get("Parent") else None
                break
        else:
            return None
    return None


def damage_table(cdo):
    table = {}
    for entry in cdo.get("AllowableDamageTypes") or []:
        table[short(entry["DamageTypeClass"])] = {k: entry[k] for k in DAMAGE_TYPE_FIELDS if k in entry}
    return table


def mesh_materials(sections_file):
    meshes = {}
    for line in open(sections_file):
        row = json.loads(line)
        if "error" not in row:
            meshes[row["path"].rsplit(".", 1)[0]] = row
    return meshes


def physical_triangles(dump_dir, mesh_row, overrides):
    """{physical material: render triangles} of a mesh, with the component's material overrides applied."""
    result = collections.Counter()
    for section in mesh_row["sections"]:
        index = section["MaterialIndex"]
        slot = mesh_row["materials"][index] if index < len(mesh_row["materials"]) else {}
        override = overrides[index] if index < len(overrides) else None
        physical = material_physics(dump_dir, override) if override else None
        physical = physical or short_path(slot.get("physMaterial")) or short_path(mesh_row.get("bodyPhysMaterial")) or "(none)"
        result[physical] += section["NumTriangles"]
    return result


def short_path(path):
    return path.rsplit(".", 1)[-1] if path else None


def deployable_row(dump, dump_dir, package, meshes):
    cdo, _, chain = dump.resolved(package)
    triangles = collections.Counter()
    mesh_names = []
    for item in completed_meshes(dump, package):
        row = meshes.get(item["mesh"])
        if row:
            mesh_names.append(item["mesh"].rsplit("/", 1)[-1])
            triangles.update(physical_triangles(dump_dir, row, item["overrides"]))
    total = sum(triangles.values())
    return {
        "chain": [c.rsplit("/", 1)[-1].rsplit(".", 1)[0] for c in chain],
        "max_health": cdo.get("MaxHealth"),
        "initial_health": cdo.get("InitialHealth"),
        "half_built_transition_health": cdo.get("HalfBuiltTransitionHealth"),
        "fully_built_transition_health": cdo.get("FullyBuiltTransitionHealth"),
        "damage_types": damage_table(cdo),
        "completed_meshes": sorted(set(mesh_names)),
        "physical_material_share": {k: round(v / total, 4) for k, v in triangles.most_common()} if total else {},
    }


def projectile_rows(dump, ballistics):
    """Damage fields of every projectile class used by a weapon of the ballistics file, with the weapon names."""
    users = collections.defaultdict(set)
    for name, weapon in ballistics["weapons"].items():
        for source in weapon["sources"]:
            users[source["projectile_class"]].add(name)
    rows = {}
    for projectile, names in sorted(users.items()):
        cdo, _, _ = dump.resolved(projectile)
        row = {k: cdo[k] for k in PROJECTILE_FIELDS if k in cdo and k != "DamageTypeToApply"}
        row["damage_type"] = short(cdo.get("DamageTypeToApply"))
        row["secondary_damage_type"] = short(cdo.get("SecondaryExplosionDamageType"))
        row["native_defaults_used"] = sorted(k for k in NATIVE_EXPLOSION if k not in cdo)
        row["weapons"] = sorted(names)
        rows[projectile.rsplit("/", 1)[-1]] = row
    return rows


def build_command(dump_dir, files, sections_file, materials_file, ballistics_file, out):
    dump = Dump(dump_dir, files)
    meshes = mesh_materials(sections_file)
    deployables = {cls.rsplit("/", 1)[-1]: deployable_row(dump, dump_dir, cls, meshes) | {"package": cls} for cls in deployable_classes(dump)}
    physical = json.load(open(materials_file))["physical_materials"]
    for row in deployables.values():
        row["physical_materials"] = {k: {f: physical[k][f] for f in ("damage_absorbed", "armor_thickness_mm", "allow_penetration", "consider_for_penetration") if f in physical[k]}
                                     for k in row["physical_material_share"] if k in physical}
    data = {"game_build": "26005357", "deployables": deployables, "projectiles": projectile_rows(dump, json.load(open(ballistics_file)))}
    json.dump(data, open(out, "w"), indent=1)
    print(len(deployables), "deployables,", len(data["projectiles"]), "projectiles; missing parents:", sorted(dump.missing))


def js_number(value):
    return repr(round(value, 6)).rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def explosion_js(damage, inner_cm, outer_cm, falloff, height_cm, damage_type=None):
    typed = f", damageType: {json.dumps(damage_type)}" if damage_type else ""
    return (f"{{ damage: {js_number(damage)}, inner: {js_number(inner_cm / 100)}, outer: {js_number(outer_cm / 100)}, "
            f"falloff: {js_number(falloff)}, distanceFromImpact: {js_number(height_cm / 100)}{typed} }}")


def export_command(data_file, out):
    """SquadCalc's src/data/structureDamage.js: structures grouped by identical health and damage-type table."""
    data = json.load(open(data_file))
    groups = collections.defaultdict(list)
    for name, row in sorted(data["deployables"].items()):
        if row["max_health"] is None or not row["damage_types"]:
            continue
        key = json.dumps([row["max_health"], row["damage_types"]], sort_keys=True)
        groups[key].append(name)
    lines = [HEADER, "export const STRUCTURES = {"]
    for key, names in sorted(groups.items(), key=lambda kv: kv[1][0]):
        max_health, damage_types = json.loads(key)
        lines.append(f'    "{names[0]}": {{')
        lines.append(f"        classes: {json.dumps(names)},")
        lines.append(f"        maxHealth: {js_number(max_health)},")
        lines.append("        damageTypes: {")
        for damage_type, v in damage_types.items():
            lines.append(f'            "{damage_type}": {{ modifier: {js_number(v["Modifier"])}, direct: {js_number(v["DirectHitDamageMultiplier"])}, '
                         f'indirect: {js_number(v["IndirectHitDamageMultiplier"])}, directRadial: {js_number(v["DirectHitRadialDamageMultiplier"])} }},')
        lines += ["        },", "    },"]
    lines += ["};", "", AMMO_HEADER, "export const AMMO = {"]
    for name, row in sorted(data["projectiles"].items()):
        native = {**NATIVE_EXPLOSION, **{k: v for k, v in row.items() if k in NATIVE_EXPLOSION}}
        exploding = any(k.startswith("Explosive") for k in row)
        primary = "null" if not exploding else explosion_js(native["ExplosiveBaseDamage"], native["ExplosiveDamageInnerRadius"], native["ExplosiveDamageOuterRadius"],
                               native["ExplosiveDamageFalloff"], native["ExplosiveDamageDistanceFromImpactNormal"])
        secondary = "null"
        if native["bUseSecondaryExplosion"]:
            secondary = explosion_js(row["SecondaryExplosionBaseDmg"], row["SecondaryExplosionInnerRadius"], row["SecondaryExplosionOuterRadius"],
                                     row["SecondaryExplosionDamageFalloff"], row["SecondaryExplosionDistanceFromImpact"],
                                     row["secondary_damage_type"])
        lines.append(f'    "{name}": {{')
        lines.append(f"        weapons: {json.dumps(row['weapons'], ensure_ascii=False)},")
        lines.append(f"        damageType: {json.dumps(row['damage_type'])},")
        lines.append(f"        impactDamage: {js_number(row.get('ImpactDamageToApply', 0.0))},")
        lines.append(f"        explosion: {primary},")
        lines.append(f"        secondary: {secondary},")
        if exploding and row["native_defaults_used"]:
            lines.append(f"        nativeDefaults: {json.dumps(row['native_defaults_used'])},")
        lines.append("    },")
    lines.append("};")
    open(out, "w", newline="").write(("\n".join(lines) + "\n").replace("\n", "\r\n"))  # the repo's JavaScript uses CRLF
    print(len(groups), "structure groups,", len(data["projectiles"]), "ammunition entries")


HEADER = """/**
 * Health and damage-type multipliers of the structures players build, and the damage fields of the
 * projectiles, from the Squad dedicated-server files (build 26005357). Generated by
 * tools/volumetric/semantics/structure_damage.py export (deployables' AllowableDamageTypes, MaxHealth;
 * the projectile Blueprints' DamageTypeToApply, ImpactDamageToApply and explosion fields); see
 * tools/volumetric/docs/structure-damage.md. Lengths in meters.
 *
 * STRUCTURES: deployables with the same health and multipliers are one entry, named after its first
 * class (`classes` lists all). `damageTypes[type]` is the game's FSQAllowableDamageType: `modifier`,
 * `direct` (DirectHitDamageMultiplier), `indirect` (IndirectHitDamageMultiplier), `directRadial`
 * (DirectHitRadialDamageMultiplier). A damage type that is not listed does not damage the structure.
 */
""".replace("\n", "\n")
AMMO_HEADER = """/**
 * AMMO: projectile class -> the damage type it applies, direct-hit damage (ImpactDamageToApply), the
 * explosion and, for mortars, rockets and the Hell Cannon, the secondary explosion with its own damage type
 * (SecondaryExplosionDamageType). A field the projectile
 * Blueprint does not override has the native default (`nativeDefaults` lists them): inferred, not in the paks.
 * A projectile with no explosion field at all (AP rounds, machine-gun bullets) has `explosion: null` and no
 * direct-hit damage: its bullet damage is not in its projectile asset.
 */"""


if __name__ == "__main__":
    {"meshes": meshes_command, "build": build_command, "export": export_command}[sys.argv[1]](*sys.argv[2:])
