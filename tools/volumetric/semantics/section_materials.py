"""Physical material and collision flag of the render sections of every placed mesh (Fallujah).

Input: ``SquadExtract meshsections`` NDJSON and ``mesh_collision_kinds.py`` JSON (placements per mesh path).
Per physical material: render triangles in sections with bEnableCollision on / off, weighted by placements.
The complex collision mesh is cooked from the LOD0 sections that have collision enabled, so a glass section with
the flag on is in the collision mesh and one with the flag off is not.

Usage: section_materials.py <sections.ndjson> <kinds.json> <out.json>
"""
import collections
import json
import sys


def physical_name(path):
    return path.rsplit(".", 1)[-1] if path else "(none)"


def main(sections_file, kinds_file, out):
    kinds = {m["path"]: m for m in json.load(open(kinds_file))["meshes"] if m.get("path")}
    placements = {path: m["placements"] for path, m in kinds.items()}
    by_material = collections.defaultdict(lambda: {"collision_on": 0, "collision_off": 0, "meshes": set()})
    glass_meshes = []
    for line in open(sections_file):
        mesh = json.loads(line)
        if "error" in mesh:
            continue
        weight = placements.get(mesh["path"], 0)
        enabled = sum(s["NumTriangles"] for s in mesh["sections"] if s["bEnableCollision"])
        for section in mesh["sections"]:
            materials = mesh["materials"]
            material = materials[section["MaterialIndex"]] if section["MaterialIndex"] < len(materials) else {}
            name = physical_name(material.get("physMaterial") or mesh.get("bodyPhysMaterial"))
            row = by_material[name]
            row["collision_on" if section["bEnableCollision"] else "collision_off"] += section["NumTriangles"] * weight
            row["meshes"].add(mesh["path"])
            if "Glass" in name:
                glass_meshes.append({"mesh": mesh["path"], "material_slot": material.get("slot"), "physical_material": name,
                                     "triangles": section["NumTriangles"], "collision_enabled": section["bEnableCollision"],
                                     "placements": weight,
                                     "mesh_collision_enabled_render_triangles": enabled,
                                     "cooked_complex_triangles": kinds[mesh["path"]]["complex_triangles"] if mesh["path"] in kinds else None,
                                     "trace_flag": kinds[mesh["path"]]["trace_flag"] if mesh["path"] in kinds else None})
    table = {k: {"collision_on": v["collision_on"], "collision_off": v["collision_off"], "meshes": len(v["meshes"])} for k, v in by_material.items()}
    json.dump({"by_physical_material": table, "glass_sections": glass_meshes}, open(out, "w"), indent=1)
    for name, v in sorted(table.items(), key=lambda kv: -(kv[1]["collision_on"] + kv[1]["collision_off"]))[:25]:
        print(f"{name:32} on={v['collision_on']:>10} off={v['collision_off']:>10} meshes={v['meshes']}")
    print("glass sections:", len(glass_meshes), "collision on:", sum(1 for g in glass_meshes if g["collision_enabled"]))


if __name__ == "__main__":
    main(*sys.argv[1:4])
