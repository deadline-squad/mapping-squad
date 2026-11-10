"""FOB exclusion radius of every layer of the game: how far from a FOB the next one has to be placed.

The game sets it per layer, not per map: ``FOBRadius`` of the layer's data asset (``Gameplay_Layer_Data/<layer>``,
class ``BP_SQLayer``) names a row of the table ``DT_FOBExclusionRadius``. An asset that does not set it keeps the
row of the class defaults of ``BP_SQLayer``. The rows also hold the construction radius of a FOB.

Usage::

    python3 -I fob_radius.py <dump root> <fob_radius.json>

``<dump root>`` is the output folder of ``game_audit.sh extract-layer-data``. Written: the rows of the table in
metres, the default row, and the row of every layer.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import audit_json  # noqa: E402

TABLE = "SquadGame/Content/Gameplay/FOBs/DT_FOBExclusionRadius.uasset.json"
LAYER_CLASS = "SquadGame/Content/Settings/Maps/BP_SQLayer.uasset.json"


def field(row, name):
    """Value of a field of a user-defined struct row, whose keys carry a generated suffix (``Name_4_<guid>``)."""
    return next(value for key, value in row.items() if key == name or key.startswith(name + "_"))


def rows(table_exports):
    """{row: {"exclusion_m", "construction_m"}} of the dumped ``DT_FOBExclusionRadius`` (the game keeps cm)."""
    table = next(export for export in table_exports if export["Type"] == "DataTable")
    return {name: {"exclusion_m": field(row, "FOBExclusionRadius") / 100, "construction_m": field(row, "FOBConstructionRadius") / 100}
            for name, row in table["Rows"].items()}


def default_row(class_exports):
    """The row a layer has when its data asset sets none: ``FOBRadius`` of the class defaults of ``BP_SQLayer``."""
    defaults = next(export for export in class_exports if export["Name"].startswith("Default__"))
    return defaults["Properties"]["FOBRadius"]["RowName"]


def layer_row(asset_exports, default):
    """(layer name, row) of a dumped layer data asset, None for an asset that is not a layer (a layer table)."""
    layer = next((export for export in asset_exports if export["Type"] == "BP_SQLayer_C"), None)
    if layer is None:
        return None
    return layer["Name"], (layer["Properties"].get("FOBRadius") or {}).get("RowName", default)


def read(root):
    """The table, the default row and the row of every layer under a dump root."""
    def load(path):
        with open(path, encoding="utf-8") as dump:
            return json.load(dump)

    default = default_row(load(os.path.join(root, LAYER_CLASS)))
    layers = {}
    for path in glob.glob(os.path.join(root, "**", "Gameplay_Layer_Data", "*.uasset.json"), recursive=True):
        found = layer_row(load(path), default)
        if found:
            layers[found[0]] = found[1]
    return {"rows": rows(load(os.path.join(root, TABLE))), "default_row": default, "layers": dict(sorted(layers.items()))}


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    audit_json.write(argv[2], read(argv[1]))


if __name__ == "__main__":
    main(sys.argv)
