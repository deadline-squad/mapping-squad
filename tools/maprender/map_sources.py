"""Per map: the path filter of its levels in the paks and the name of its whole-map texture."""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "heightmaps", "py"))
import maps


def texture_of(slug, table):
    """Most used minimap texture of the map's regular layers in the table of `SquadExtract layerminimaps`."""
    root = maps.statics_root(slug)
    count = collections.Counter()
    with open(table) as lines:
        for line in lines:
            path, texture = line.split("\t")[:2]
            if path.startswith(root) and texture and not any(word in path for word in ("Seed", "Skirmish", "Tutorial", "Training")):
                count[texture.rsplit(".", 1)[-1]] += 1
    return count.most_common(1)[0][0] if count else None


if __name__ == "__main__":
    for slug in maps.MAPS:
        print(slug, maps.statics_root(slug), texture_of(slug, sys.argv[1]))
