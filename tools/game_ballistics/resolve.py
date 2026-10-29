"""Resolve Blueprint inheritance in SquadExtract ``dumpall`` output.

A Blueprint class default object (CDO) and its default subobjects (ProjectileComp, ...) only store
the properties that differ from the parent class, so a value is the deepest override along the
Super chain, merged struct by struct. Native (/Script/) parents are not in the paks: a property
nobody overrides keeps the engine default, which `ENGINE_DEFAULTS` supplies where it matters.
"""

import json
import os
import re

ENGINE_DEFAULTS = {
    # UProjectileMovementComponent defaults (Engine/Source/Runtime/Engine/Private/GameFramework/ProjectileMovementComponent.cpp)
    "ProjectileComp": {"InitialSpeed": 0.0, "MaxSpeed": 0.0, "ProjectileGravityScale": 1.0,
                       "ConstantAcceleration": {"X": 0.0, "Y": 0.0, "Z": 0.0}, "ConstantAccelerationTimeout": 0.0},
}


class Dump:
    def __init__(self, root, files_txt):
        self.root = root
        self.files = [line.strip() for line in open(files_txt) if line.strip().endswith(".uasset")]
        self.by_name = {}
        for path in self.files:
            self.by_name.setdefault(os.path.basename(path)[:-len(".uasset")], []).append(path)
        self.cache = {}
        self.missing = set()

    def file_of(self, object_path):
        """Pak path of a /Game/... or /<Plugin>/... object path (class or package)."""
        package = object_path.split(".")[0]
        name = package.rsplit("/", 1)[-1]
        mount = package.split("/")[1]
        for candidate in self.by_name.get(name, []):
            if mount == "Game" and candidate.startswith("SquadGame/Content/") and candidate[len("SquadGame/Content/"):-7] == package[len("/Game/"):]:
                return candidate
            if mount != "Game" and candidate.endswith(package[len(mount) + 2:] + ".uasset") and f"/{mount}/" in "/" + candidate:
                return candidate
        candidates = self.by_name.get(name, [])
        return candidates[0] if len(candidates) == 1 else None

    def exports(self, pak_path):
        if pak_path not in self.cache:
            target = os.path.join(self.root, pak_path + ".json")
            if not os.path.exists(target):
                self.missing.add(pak_path)
                self.cache[pak_path] = None
            else:
                self.cache[pak_path] = json.load(open(target))
        return self.cache[pak_path]

    def class_info(self, object_path):
        """(super object path or None, CDO properties, {component name: properties}) of a class."""
        pak = self.file_of(object_path)
        exports = self.exports(pak) if pak else None
        if not exports:
            if pak is None and not object_path.startswith("/Script/"):
                self.missing.add(object_path)
            return None
        bgc = next((e for e in exports if e.get("Type") == "BlueprintGeneratedClass"), None)
        if bgc is None:
            return None
        sup = (bgc.get("Super") or {}).get("ObjectPath")
        cdo_name = "Default__" + bgc["Name"]
        cdo = next((e for e in exports if e.get("Name") == cdo_name), {})
        components = {}
        for e in exports:
            outer = (e.get("Outer") or {}).get("ObjectName", "")
            if cdo_name in outer and e.get("Name") != cdo_name:
                components[e["Name"]] = e.get("Properties", {})
            elif e.get("Name", "").endswith("_GEN_VARIABLE"):
                components[e["Name"][:-len("_GEN_VARIABLE")]] = e.get("Properties", {})
        return sup, cdo.get("Properties", {}), components

    def chain(self, object_path):
        """Class infos from the root ancestor down to the class itself."""
        out = []
        seen = set()
        while object_path and not object_path.startswith("/Script/") and object_path not in seen:
            seen.add(object_path)
            info = self.class_info(object_path)
            if info is None:
                break
            out.append((object_path, info))
            object_path = info[0]
        return list(reversed(out))

    def resolved(self, object_path):
        """(merged CDO properties, {component: merged properties}, [class paths root->leaf])."""
        cdo, components, paths = {}, {}, []
        for path, (_, props, comps) in self.chain(object_path):
            cdo = merge(cdo, props)
            for name, value in comps.items():
                components[name] = merge(components.get(name, ENGINE_DEFAULTS.get(name, {})), value)
            paths.append(path)
        return cdo, components, paths


def merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for key, value in override.items():
            out[key] = merge(base.get(key), value) if key in base else value
        return out
    return override


def class_path(ref):
    """'/Game/X/BP_Y.0' object reference -> '/Game/X/BP_Y' package path."""
    if not ref:
        return None
    return re.sub(r"\.\d+$", "", ref["ObjectPath"])
