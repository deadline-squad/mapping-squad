"""Effective collision profile of every projectile Blueprint in the weapon dump.

A projectile Blueprint inherits the SphereCollision component of its native class. The native default profile
comes from the constructors in the server binary (``elf_profiles.py``): ASQProjectile -> "Projectile",
ASQGrenadeProjectile -> "Throwable"; ASQMortarProjectile, ASQGuidedProjectile and ASQSmokeGrenadeProjectile call
those constructors and set no profile of their own. A Blueprint's ``SQProjectileRootComponent`` BodyInstance
overrides it (most derived wins).

Usage: projectile_profiles.py <weapon dump dir> <out.json>
"""
import json
import os
import sys

NATIVE_PROFILE = {
    "SQProjectile": "Projectile",
    "SQMortarProjectile": "Projectile",
    "SQGuidedProjectile": "Projectile",
    "SQGrenadeProjectile": "Throwable",
    "SQSmokeGrenadeProjectile": "Throwable",
}


def load_blueprints(dump):
    """Map '/Game/...' package path -> (super class, super path, BodyInstance of SQProjectileRootComponent)."""
    result = {}
    content = os.path.join(dump, "SquadGame", "Content")
    for root, _, files in os.walk(content):
        for name in files:
            if not name.endswith(".uasset.json"):
                continue
            path = os.path.join(root, name)
            exports = json.load(open(path))
            if not isinstance(exports, list):
                continue
            klass = next((e for e in exports if e.get("Type") == "BlueprintGeneratedClass"), None)
            if klass is None:
                continue
            body = next(((e.get("Properties") or {}).get("BodyInstance") for e in exports if e.get("Type") == "SQProjectileRootComponent"), None)
            parent = klass.get("SuperStruct") or {}
            if not parent:
                cdo = next((e for e in exports if e.get("Name", "").startswith("Default__")), {})
                parent = cdo.get("Template") or {}
            key = "/Game" + path[len(content):-len(".uasset.json")]
            result[key] = (parent.get("ObjectName", ""), (parent.get("ObjectPath") or "").rsplit(".", 1)[0], body)
    return result


def resolve(blueprints):
    """Rows of {bp, native, profile, source, overrides} for blueprints that descend from a projectile class."""
    rows = []
    for bp in sorted(blueprints):
        profile, source, overrides, node, native = None, "native", [], bp, None
        while node in blueprints:
            parent_name, parent_path, body = blueprints[node]
            if body and body.get("CollisionProfileName") and profile is None:
                profile, source = body["CollisionProfileName"], node
            if body and body.get("CollisionResponses") and not overrides:
                overrides = [f"{r['Channel']}={r['Response'][4:]}" for r in body["CollisionResponses"]["ResponseArray"]]
            if parent_path.startswith("/Script"):
                native = parent_name.split("'")[1]
                break
            if not parent_path:
                break
            node = parent_path
        if native in NATIVE_PROFILE:
            rows.append({"bp": bp, "native": native, "profile": profile or NATIVE_PROFILE[native],
                         "source": source, "responses_in_blueprint": overrides})
    return rows


if __name__ == "__main__":
    table = resolve(load_blueprints(sys.argv[1]))
    json.dump(table, open(sys.argv[2], "w"), indent=1)
    counts = {}
    for row in table:
        key = (row["native"], row["profile"], row["source"] == "native")
        counts[key] = counts.get(key, 0) + 1
    for key, n in sorted(counts.items()):
        print(n, key)
