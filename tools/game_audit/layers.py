"""Gameplay layers of the game: a stripped copy of each dump, and the part of it the audit compares.

A gameplay layer (``Gameplay_Layers/<layer>.umap``) dumps to about 55 MB of JSON, 20 MB of it the play-area mask
(``SQMapBoundary.BoundaryMaskData``), so the 219 layers are dumped one map folder at a time and kept without the
mask, gzipped (8 MB in all). ``reduce`` then keeps, per layer: the two minimap corners and the minimap texture of
``SQWorldSettings``, every capture zone and main base with its world position and collision shapes, and the
protection zones of the mains. Positions are in cm on the engine's axes (+Y south).

Usage::

    python3 -I layers.py strip   <dump root> <layers dir>        # every *.umap.json under the dump, without the mask
    python3 -I layers.py reduce  <layers dir> <game_layers.json>
    python3 -I layers.py corners <game_layers.json> <corners.ndjson>
    python3 -I layers.py zones   <game_layers.json> <Gameplay_TeamZone.uasset.json> <protection_zones.json>

``corners`` writes the records ``tools/heightmaps/py/minimap_corners.py table`` reads, so the corner table of the
maps comes from the same dumps. ``zones`` writes ``data/protection_zones.json``; the dumped Blueprint of the zone
gives the lock distance of a zone whose level sets none.
"""
import glob
import gzip
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import audit_json  # noqa: E402

SHAPES = ("SphereComponent", "BoxComponent", "CapsuleComponent")
PROTECTION_ZONE = "Gameplay_TeamZone_C"
ZONE_ACTOR = re.compile(r"BP_CaptureZone|BP_.*Main")
# An attachment chain longer than this is a cycle in broken data, not a level
MAX_CHAIN = 16


def strip(dump_root, layers_dir):
    """Copy every dumped layer under ``dump_root`` to ``layers_dir/<layer>.json.gz`` without the play-area mask.

    Returns the number of layers written. The record keeps the layer's path in the paks next to its exports.
    """
    os.makedirs(layers_dir, exist_ok=True)
    written = 0
    for path in sorted(glob.glob(os.path.join(dump_root, "**", "*.umap.json"), recursive=True)):
        with open(path, encoding="utf-8") as dump:
            exports = json.load(dump)
        for export in exports:
            if export["Type"] == "SQMapBoundary":
                (export.get("Properties") or {}).pop("BoundaryMaskData", None)
        layer = os.path.relpath(path, dump_root)[: -len(".json")]
        target = os.path.join(layers_dir, os.path.basename(layer)[: -len(".umap")] + ".json.gz")
        with gzip.open(target + ".tmp", "wt", encoding="utf-8") as out:
            json.dump({"path": layer, "exports": exports}, out)
        os.replace(target + ".tmp", target)
        written += 1
    return written


def rotation_axes(rotation):
    """The X, Y and Z axes of a frame turned by an ``FRotator`` (degrees), as ``FRotationMatrix`` builds them."""
    pitch, yaw, roll = (math.radians(rotation.get(key, 0.0)) for key in ("Pitch", "Yaw", "Roll"))
    sp, cp, sy, cy, sr, cr = math.sin(pitch), math.cos(pitch), math.sin(yaw), math.cos(yaw), math.sin(roll), math.cos(roll)
    return [
        [cp * cy, cp * sy, sp],
        [sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp],
        [-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp],
    ]


def to_parent(point, location, rotation, scale):
    """A point of a component's frame in the frame of its parent: scaled, turned, then moved."""
    axes = rotation_axes(rotation)
    scaled = [point[i] * scale[i] for i in range(3)]
    return [scaled[0] * axes[0][i] + scaled[1] * axes[1][i] + scaled[2] * axes[2][i] + location[i] for i in range(3)]


def vector(value, default):
    """[X, Y, Z] of a dumped vector, ``default`` when the property is not set."""
    return [value.get("X", 0.0), value.get("Y", 0.0), value.get("Z", 0.0)] if value else list(default)


def export_index(reference):
    """Index into the level's exports of the object a reference points to, None for no reference."""
    return int(reference["ObjectPath"].rsplit(".", 1)[1]) if reference and "ObjectPath" in reference else None


class Level:
    """The exports of one layer with the transforms of its components composed along their attachment chains."""

    def __init__(self, exports):
        self.exports = exports
        self.children = {}
        for index, export in enumerate(exports):
            self.children.setdefault(export_index(export.get("Outer")), []).append(index)

    def properties(self, index):
        """The properties of export ``index``, empty for an export without any."""
        return self.exports[index].get("Properties") or {}

    def chain(self, index):
        """Indices of a component and of the components it is attached to, the component first."""
        indices = []
        while index is not None and len(indices) < MAX_CHAIN:
            indices.append(index)
            index = export_index(self.properties(index).get("AttachParent"))
        return indices

    def world(self, index, point=(0.0, 0.0, 0.0)):
        """World position of ``point`` given in the frame of component ``index``.

        A component with ``bAbsoluteLocation`` holds a world location already; its parents are not applied.
        """
        position = list(point)
        for link in self.chain(index):
            properties = self.properties(link)
            position = to_parent(position, vector(properties.get("RelativeLocation"), (0.0, 0.0, 0.0)),
                                 properties.get("RelativeRotation") or {}, vector(properties.get("RelativeScale3D"), (1.0, 1.0, 1.0)))
            if properties.get("bAbsoluteLocation"):
                break
        return position

    def scale(self, index):
        """Product of the scales of component ``index`` and of what it is attached to, per axis."""
        result = [1.0, 1.0, 1.0]
        for link in self.chain(index):
            scale = vector(self.properties(link).get("RelativeScale3D"), (1.0, 1.0, 1.0))
            result = [result[axis] * scale[axis] for axis in range(3)]
        return result

    def tilted(self, index):
        """Whether component ``index`` or something it is attached to is pitched or rolled."""
        for link in self.chain(index):
            rotation = self.properties(link).get("RelativeRotation") or {}
            if abs(rotation.get("Pitch", 0.0)) > 1e-3 or abs(rotation.get("Roll", 0.0)) > 1e-3:
                return True
        return False

    def shapes(self, actor):
        """The collision shapes owned by actor ``actor``: kind, name, world position, size, scale."""
        shapes = []
        for child in self.children.get(actor, []):
            export, properties = self.exports[child], self.properties(child)
            if export["Type"] not in SHAPES:
                continue
            parent = export_index(properties.get("AttachParent"))
            shapes.append({
                "kind": export["Type"], "name": export["Name"], "loc": self.world(child),
                "radius": properties.get("SphereRadius", properties.get("CapsuleRadius")), "extent": properties.get("BoxExtent"),
                "half_height": properties.get("CapsuleHalfHeight"), "scale": self.scale(child),
                "parent_tilted": self.tilted(parent) if parent is not None else False,
            })
        return shapes


def scalars(properties):
    """The properties that are plain values, without the structures and references."""
    return {key: value for key, value in properties.items() if isinstance(value, (int, float, bool, str))}


def reduce_layer(record):
    """What the audit compares of one stripped layer (a record of ``strip``)."""
    level = Level(record["exports"])
    reduced = {"path": record["path"], "zones": [], "protection": []}
    for index, export in enumerate(level.exports):
        properties, kind = level.properties(index), export["Type"]
        if kind == "SQWorldSettings":
            for key in ("MapTextureCornerZero", "MapTextureCornerOne"):
                actor = export_index(properties.get(key))
                root = export_index(level.properties(actor).get("RootComponent")) if actor is not None else None
                reduced[key] = level.world(root) if root is not None else None
            reduced["texture"] = (properties.get("MapTexture") or {}).get("ObjectName")
            reduced["world"] = scalars(properties)
        elif ZONE_ACTOR.match(kind) or kind == PROTECTION_ZONE:
            root = export_index(properties.get("RootComponent"))
            capture = export_index(properties.get("SQCaptureZone"))
            capture_properties = level.properties(capture) if capture is not None else {}
            flag = capture_properties.get("FlagName") or properties.get("FlagName") or {}
            entry = {
                "type": kind, "name": export["Name"], "loc": level.world(root) if root is not None else None,
                "shapes": level.shapes(index), "flag": flag.get("SourceString") or flag.get("CultureInvariantString"),
                "scalars": scalars({**capture_properties, **properties}),
            }
            reduced["protection" if kind == PROTECTION_ZONE else "zones"].append(entry)
    return reduced


def reduce(layers_dir, out_file):
    """Reduce every stripped layer of ``layers_dir`` into one JSON file keyed by layer name; returns the count."""
    result = {}
    for path in sorted(glob.glob(os.path.join(layers_dir, "*.json.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as layer:
            result[os.path.basename(path)[: -len(".json.gz")]] = reduce_layer(json.load(layer))
    with open(out_file, "w", encoding="utf-8") as out:
        json.dump(result, out)
    return len(result)


def corner_records(game_layers):
    """One record per layer in the form ``minimap_corners.py table`` reads: path, the two corners, the texture."""
    records = []
    for layer in game_layers.values():
        record = {"layer": layer["path"], "texture": layer.get("texture")}
        for key, corner in (("c0", layer.get("MapTextureCornerZero")), ("c1", layer.get("MapTextureCornerOne"))):
            record[key] = {"X": corner[0], "Y": corner[1], "Z": corner[2]} if corner else None
        records.append(record)
    return records


def scaled_radius(radius, scale):
    """Radius of a sphere component in the world: the engine multiplies it by the smallest size of the scale.

    ``USphereComponent::GetScaledSphereRadius`` takes the absolute value of each axis first, so a mirrored
    component (a negative scale) has a positive radius.
    """
    return radius * min(abs(axis) for axis in scale)


def protection_zones(game_layers, default_lock):
    """{layer: {zone: sizes}} of the round protection zones: sphere radius, scale, radius in the world, lock distance.

    Lengths in cm. ``default_lock`` is the lock distance of a zone whose level sets none. The sphere is a component
    the level adds to the zone, so its radius is the level's; a sphere without one is listed with nulls.
    """
    result = {}
    for name, layer in sorted(game_layers.items()):
        zones = {}
        for zone in layer["protection"]:
            sphere = next((shape for shape in zone["shapes"] if shape["kind"] == "SphereComponent"), None)
            if sphere is None:
                continue
            radius = sphere["radius"]
            zones[zone["name"]] = {
                "sphere_cm": radius, "scale": [round(axis, 4) for axis in sphere["scale"]],
                "radius_cm": None if radius is None else round(scaled_radius(radius, sphere["scale"]), 1),
                "lock_cm": zone["scalars"].get("DeployableLockDistance", default_lock),
            }
        if zones:
            result[name] = zones
    return result


def default_lock_distance(blueprint_exports):
    """``DeployableLockDistance`` (cm) of the class defaults in the dumped ``Gameplay_TeamZone`` Blueprint."""
    return next(e["Properties"]["DeployableLockDistance"] for e in blueprint_exports if e["Name"].startswith("Default__"))


def main(argv):
    command, arguments = (argv[1], argv[2:]) if len(argv) > 1 else (None, [])
    if command == "strip" and len(arguments) == 2:
        print(strip(*arguments), "layers")
    elif command == "reduce" and len(arguments) == 2:
        print(reduce(*arguments), "layers")
    elif command == "corners" and len(arguments) == 2:
        with open(arguments[0], encoding="utf-8") as layers, open(arguments[1], "w", encoding="utf-8") as out:
            out.write("".join(json.dumps(record) + "\n" for record in corner_records(json.load(layers))))
    elif command == "zones" and len(arguments) == 3:
        with open(arguments[0], encoding="utf-8") as layers, open(arguments[1], encoding="utf-8") as blueprint:
            audit_json.write(arguments[2], protection_zones(json.load(layers), default_lock_distance(json.load(blueprint))))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
