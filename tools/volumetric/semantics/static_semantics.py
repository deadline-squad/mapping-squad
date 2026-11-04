"""How placed static meshes answer the Projectile channel, from the extracted ``statics`` of one or more maps.

Input: directories written by ``SquadExtract statics`` (instances.ndjson, bodies/<id>.json). For every placement
(an instance of an InstancedStaticMeshComponent, or one static / spline mesh component) the effective answer is
resolved like ``py/collision.py``: component BodyInstance override, then the mesh BodySetup DefaultInstance,
unlisted channels Block (verified: the BlockAll profile lists only AudioOcclusion=Block, the one channel whose
default is Ignore).

Output (JSON, stdout): per map and overall, placements grouped by effective profile, CollisionEnabled, response to
Projectile / Visibility / Pawn, mesh CollisionTraceFlag and which shapes the BodySetup carries, plus the
PhysMaterial overrides of the BodySetup.

Usage: static_semantics.py <statics dir> [<statics dir> ...]
"""
import collections
import json
import os
import sys

NO_QUERY = ("ECollisionEnabled::NoCollision", "ECollisionEnabled::PhysicsOnly")


def responses(instance):
    """{channel: 'Block'|'Overlap'|'Ignore'} listed in a BodyInstance."""
    listed = (instance or {}).get("CollisionResponses") or {}
    return {r["Channel"]: r["Response"][4:] for r in listed.get("ResponseArray", [])}


def effective(component, mesh_default, channel):
    """Response of a placement to ``channel`` (component override beats mesh default; unlisted = Block)."""
    component, mesh_default = component or {}, mesh_default or {}
    enabled = component.get("CollisionEnabled") or mesh_default.get("CollisionEnabled")
    profile = component.get("CollisionProfileName") or mesh_default.get("CollisionProfileName")
    if enabled in NO_QUERY or profile == "NoCollision":
        return "Ignore"
    return {**responses(mesh_default), **responses(component)}.get(channel, "Block")


def shapes(body):
    """Compact description of the BodySetup shapes, e.g. 'convex+box'."""
    agg = ((body or {}).get("Properties") or {}).get("AggGeom") or {}
    names = {"ConvexElems": "convex", "BoxElems": "box", "SphereElems": "sphere", "SphylElems": "capsule"}
    return "+".join(n for k, n in names.items() if agg.get(k)) or "none"


def analyse(directory):
    bodies = {}
    for name in os.listdir(os.path.join(directory, "bodies")):
        if name.endswith(".json"):
            bodies[name[:-5]] = json.load(open(os.path.join(directory, "bodies", name)))
    groups = collections.Counter()
    physmat = collections.Counter()
    for line in open(os.path.join(directory, "instances.ndjson")):
        item = json.loads(line)
        info = bodies.get(item["mesh"], {})
        body = info.get("body") or {}
        props = body.get("Properties") or {}
        default = info.get("meshDefault") or (props.get("DefaultInstance") if isinstance(props.get("DefaultInstance"), dict) else None)
        count = len(item["instances"]) if item.get("instances") is not None else 1
        component = item.get("collision") or {}
        profile = component.get("CollisionProfileName") or (default or {}).get("CollisionProfileName") or "-"
        enabled = (component.get("CollisionEnabled") or (default or {}).get("CollisionEnabled") or "default").split("::")[-1]
        key = (item["type"], profile, enabled,
               effective(component, default, "Projectile"), effective(component, default, "Visibility"), effective(component, default, "Pawn"),
               props.get("CollisionTraceFlag", "CTF_UseDefault").replace("CTF_", ""), shapes(body))
        groups[key] += count
        material = props.get("PhysMaterial")
        if material:
            physmat[material["ObjectName"].split("'")[1]] += count
    return groups, physmat


def main(directories):
    total, total_mat = collections.Counter(), collections.Counter()
    per_map = {}
    for directory in directories:
        groups, physmat = analyse(directory)
        per_map[os.path.basename(directory.rstrip("/"))] = sum(groups.values())
        total.update(groups)
        total_mat.update(physmat)
    columns = ["component", "profile", "collision_enabled", "projectile", "visibility", "pawn", "trace_flag", "shapes", "placements"]
    rows = [dict(zip(columns, key + (n,))) for key, n in total.most_common()]
    print(json.dumps({"placements_per_map": per_map, "groups": rows, "body_physmaterial_overrides": total_mat.most_common()}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
