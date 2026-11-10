"""Tracks painted into the game landscape: the weight of its path layers on the map's 1 m grid, from the client scene.

Several maps paint their footpaths and tracks into the landscape instead of laying spline meshes (Kamdesh, Kohat, Lashkar, Logar
and Al Basrah "Path", Sumari "mat05_path" and "mat06_rockpath", Skorpo "Grusvei", gravel road). The weightmaps are read as
tools/maprender/scene_render.py Scene.load_weights reads them: component placement from its actor and relative position,
subsection texels, BGRA channel order, and a component repeated by another level writes only where it has paint. That module
needs a GPU context to import, so the reading is repeated here.
"""

import json
import math
import os
import re

import numpy as np

PATH_LAYER = re.compile(r"(^|_)(path|rockpath|grusvei)(_|$)", re.IGNORECASE)
# Memory order of a weightmap texel: logical channel -> byte (BGRA)
CHANNEL_BYTE = (2, 1, 0, 3)


def path_weights(scene_dir, bounds, shape):
    """uint8 [rows, cols]: the highest weight (0..255) of the path layers at each point of the 1 m grid of ground.npy
    (point [r, c] at min_x + c, min_y + r metres), bilinear between the landscape's vertices; zeros on a map without them."""
    result = np.zeros(shape, np.uint8)
    root = os.path.join(scene_dir, "landscape")
    if not os.path.isdir(root):
        return result
    rows, cols = shape
    for level in sorted(os.listdir(root)):
        for c in json.load(open(os.path.join(root, level, "components.json"))):
            if not any(PATH_LAYER.search(layer["layer"]) for layer in c["layers"]):
                continue
            quads, sub = c["componentSizeQuads"], c["subsectionSizeQuads"]
            scale = np.array(c["scale"][:2], np.float64)
            yaw = math.radians(c["yaw"])
            cos, sin = math.cos(yaw), math.sin(yaw)
            base = np.array(c["relative"], np.float64)
            corners = []
            for u, v in ((0, 0), (quads, 0), (0, quads), (quads, quads)):
                lx, ly = (base[0] + u) * scale[0], (base[1] + v) * scale[1]
                corners.append((c["location"][0] + cos * lx - sin * ly, c["location"][1] + sin * lx + cos * ly))
            corners = np.array(corners) / 100
            i0, j0 = np.floor(corners.min(0) - (bounds["min_x"], bounds["min_y"])).astype(int)
            i1, j1 = np.ceil(corners.max(0) - (bounds["min_x"], bounds["min_y"])).astype(int) + 1
            i0, j0, i1, j1 = max(i0, 0), max(j0, 0), min(i1, cols), min(j1, rows)
            if i0 >= i1 or j0 >= j1:
                continue
            gx, gy = np.meshgrid(bounds["min_x"] + np.arange(i0, i1), bounds["min_y"] + np.arange(j0, j1))
            dx, dy = gx * 100 - c["location"][0], gy * 100 - c["location"][1]
            u = (cos * dx + sin * dy) / scale[0] - base[0]
            v = (-sin * dx + cos * dy) / scale[1] - base[1]
            inside = (u >= -0.5) & (u <= quads + 0.5) & (v >= -0.5) & (v <= quads + 0.5)
            if not inside.any():
                continue
            u_low = np.clip(np.floor(u).astype(np.int64), 0, quads)
            v_low = np.clip(np.floor(v).astype(np.int64), 0, quads)
            u_high, v_high = np.minimum(u_low + 1, quads), np.minimum(v_low + 1, quads)
            u_share, v_share = np.clip(u - u_low, 0, 1), np.clip(v - v_low, 0, 1)

            def texel(a):
                return np.where(a <= sub, a, sub + 1 + (a - sub)) if c["numSubsections"] == 2 else a

            size = (sub + 1) * c["numSubsections"]
            maps = [np.fromfile(os.path.join(root, level, "wm", t + ".bin"), np.uint8).reshape(size, size, 4) for t in c["weightmapTextures"]]
            paint = np.zeros(u.shape)
            path = np.zeros(u.shape)
            for layer in c["layers"]:
                plane = maps[layer["texture"]][..., CHANNEL_BYTE[layer["channel"]]]
                top = plane[texel(v_low), texel(u_low)] * (1 - u_share) + plane[texel(v_low), texel(u_high)] * u_share
                bottom = plane[texel(v_high), texel(u_low)] * (1 - u_share) + plane[texel(v_high), texel(u_high)] * u_share
                value = top * (1 - v_share) + bottom * v_share
                paint += value
                if PATH_LAYER.search(layer["layer"]):
                    path = np.maximum(path, value)
            painted = inside & (paint > 0)
            result[j0:j1, i0:i1][painted] = np.clip(np.rint(path[painted]), 0, 255).astype(np.uint8)
    return result
