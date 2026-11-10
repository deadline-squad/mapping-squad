"""Contrast of the Detailed layer's classes against the ground they are drawn on and against each other, under normal colour
vision and the three dichromacies.

Usage: palette_contrast.py [--json FILE]   (prints the lowest contrasts; the Python image of maptiles.sh)

Colours are the ones drawn: a class's colour blended over a ground cover colour with the opacity render.py uses. Colour vision
deficiency: Machado, Oliveira & Fernandes (2009), "A Physiologically-based Model for Simulation of Color Vision Deficiency", IEEE
TVCG 15(6), the severity 1.0 matrices of their table 1 (https://www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html),
applied to linear RGB. Colour difference: CIEDE2000 (Sharma, Wu & Dalal 2005). Brychtova & Coltekin (2017, "The effect of spatial
distance on the discriminability of colors in maps", CaGIS 44(3)) found map colours told apart reliably from a difference of about
10; DISTINCT is that threshold. Graphics next to each other also need a luminance step: WCAG 2.1 (1.4.11) asks a ratio of 3 for
graphical objects, which the dark outlines and casings carry, not the fills.
"""

import json
import sys

import numpy as np

import features
import render

DISTINCT = 10.0
MACHADO = {
    "normal": np.eye(3),
    "protanopia": np.array([[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]]),
    "deuteranopia": np.array([[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]]),
    "tritanopia": np.array([[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]]),
}
GROUNDS = {"grass": "PhysMat_Grass", "tall grass": "PhysMat_GrassTall", "dirt": "PhysMat_Dirt", "sand": "PhysMat_Sand", "rock": "PhysMat_Rock",
           "snow": "PhysMat_Snow", "asphalt": "PhysMat_Asphalt", "forest floor": "PhysMat_Leafs", "gravel": "PhysMat_Gravel", "mud": "PhysMat_Mud_deep"}
# Classes a reader must tell apart where they meet
PAIRS = [("building 5 m", "conifer"), ("building 5 m", "deciduous"), ("building 2 m", "bush"), ("building 5 m", "rock"), ("building 5 m", "shadow"),
         ("wall", "conifer"), ("rock", "asphalt road"), ("dirt road", "contour major"), ("crop low", "crop tall"), ("water shallow", "asphalt road"),
         ("conifer", "deciduous"), ("trench", "contour major")]


def to_linear(rgb):
    c = np.asarray(rgb, np.float64) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def simulate(rgb, kind):
    """sRGB 0..255 [..., 3] as seen with a colour vision of MACHADO."""
    c = np.clip(to_linear(rgb) @ MACHADO[kind].T, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055) * 255


def lab(rgb):
    """CIE L*a*b* (D65) of sRGB 0..255 [..., 3]."""
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = to_linear(rgb) @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def delta_e2000(rgb1, rgb2):
    """CIEDE2000 colour difference of two sRGB colours."""
    l1, a1, b1 = np.moveaxis(lab(rgb1), -1, 0)
    l2, a2, b2 = np.moveaxis(lab(rgb2), -1, 0)
    c_mean = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2
    g = 0.5 * (1 - np.sqrt(c_mean ** 7 / (c_mean ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p, h2p = np.degrees(np.arctan2(b1, a1p)) % 360, np.degrees(np.arctan2(b2, a2p)) % 360
    dl, dc = l2 - l1, c2p - c1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(c1p * c2p == 0, 0, dh)
    dhp = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh) / 2)
    l_mean, cp_mean = (l1 + l2) / 2, (c1p + c2p) / 2
    h_sum = h1p + h2p
    h_mean = np.where(np.abs(h1p - h2p) > 180, np.where(h_sum < 360, h_sum + 360, h_sum - 360), h_sum) / 2
    h_mean = np.where(c1p * c2p == 0, h_sum, h_mean)
    t = (1 - 0.17 * np.cos(np.radians(h_mean - 30)) + 0.24 * np.cos(np.radians(2 * h_mean))
         + 0.32 * np.cos(np.radians(3 * h_mean + 6)) - 0.20 * np.cos(np.radians(4 * h_mean - 63)))
    sl = 1 + 0.015 * (l_mean - 50) ** 2 / np.sqrt(20 + (l_mean - 50) ** 2)
    sc, sh = 1 + 0.045 * cp_mean, 1 + 0.015 * cp_mean * t
    rt = -2 * np.sqrt(cp_mean ** 7 / (cp_mean ** 7 + 25.0 ** 7)) * np.sin(np.radians(60 * np.exp(-((h_mean - 275) / 25) ** 2)))
    return float(np.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhp / sh) ** 2 + rt * (dc / sc) * (dhp / sh)))


def wcag_contrast(rgb1, rgb2):
    """WCAG 2 contrast ratio (1..21) of two sRGB colours."""
    weights = np.array([0.2126, 0.7152, 0.0722])
    y1, y2 = to_linear(rgb1) @ weights, to_linear(rgb2) @ weights
    return float((max(y1, y2) + 0.05) / (min(y1, y2) + 0.05))


def over(colour, alpha, ground):
    return np.asarray(colour, np.float64) * alpha + np.asarray(ground, np.float64) * (1 - alpha)


def drawn_colours(ground):
    """{class: colour as drawn} on a ground colour: structures through render.roof_contrast, the others at the renderer's opacity."""
    g = np.asarray(ground, np.float64)
    luma = np.array([float(g @ render.LUMA)])
    out = {f"building {h:g} m": np.asarray(render.roof_contrast(render.structure_colour(np.array([h])), luma)[0], np.float64) for h in (2.0, 5.0, 10.0, 20.0)}
    out["building outline"] = over(render.OUTLINE_RGB, 0.85, out["building 5 m"])
    out["wall"] = np.asarray(render.OBJECT_RGB[features.WALL], np.float64)
    out["bridge deck"] = np.asarray(render.OBJECT_RGB[features.BRIDGE], np.float64)
    names = {features.CONIFER: "conifer", features.DECIDUOUS: "deciduous", features.BUSH: "bush", features.ROCK: "rock", features.PALM: "palm"}
    for cls, name in names.items():
        fill, alpha, _ = render.FOLIAGE_STYLE[cls]
        out[name] = over(fill, alpha, g)
    for cls in ("dirt", "asphalt", "pavement", "rail", "trench"):
        out[f"{cls} road" if cls in render.ROAD_CLASSES else cls] = over(render.SPLINE_STYLE[cls][0], 0.75 if cls == "dirt" else 0.92, g)
    casing = render.SPLINE_STYLE["dirt"][1]
    if casing is not None:
        out["dirt road casing"] = over(casing, render.CASING_ALPHA.get("dirt", render.CASING_ALPHA_DEFAULT), g)
    out["water shallow"] = np.asarray(render.WATER_RGB, np.float64)
    out["water deep"] = np.asarray(render.WATER_DEEP_RGB, np.float64)
    out["contour major"] = over(render.CONTOUR_RGB, render.CONTOUR_ALPHA[1], g)
    out["contour minor"] = over(render.CONTOUR_RGB, render.CONTOUR_ALPHA[0], g)
    (_, low), (_, tall) = render.CROP_RGB
    out["crop low"] = over(low, render.CROP_ALPHA, g)
    out["crop tall"] = over(tall, render.CROP_ALPHA, g)
    out["shadow"] = g * render.SHADOW_FACTOR
    return out


def difference(rgb1, rgb2):
    """{vision: CIEDE2000} of two colours under every vision of MACHADO."""
    return {kind: round(delta_e2000(simulate(rgb1, kind), simulate(rgb2, kind)), 1) for kind in MACHADO}


def report():
    """{"vs_ground": {class: {ground: {vision: dE, "wcag": ratio}}}, "pairs": {"a | b": {ground: {vision: dE}}}, "labels": WCAG on the halo}."""
    result = {"vs_ground": {}, "pairs": {}}
    for ground_name, material in GROUNDS.items():
        ground = np.asarray(render.COVER_RGB[material], np.float64)
        drawn = drawn_colours(ground)
        for name, colour in drawn.items():
            result["vs_ground"].setdefault(name, {})[ground_name] = difference(colour, ground) | {"wcag": round(wcag_contrast(colour, ground), 2)}
        for a, b in PAIRS:
            result["pairs"].setdefault(f"{a} | {b}", {})[ground_name] = difference(drawn[a], drawn[b])
    result["labels"] = {"contour": round(wcag_contrast(render.CONTOUR_LABEL_RGB, render.HALO_RGB), 2),
                        "roof": round(wcag_contrast(render.LABEL_TEXT_RGB, render.HALO_RGB), 2), "summit": round(wcag_contrast(render.SUMMIT_RGB, render.HALO_RGB), 2)}
    return result


def lowest(by_ground):
    """(ground, {vision: dE}) of the ground on which the smallest difference over the visions is lowest."""
    ground = min(by_ground, key=lambda g: min(by_ground[g][kind] for kind in MACHADO))
    return ground, by_ground[ground]


def main():
    result = report()
    if "--json" in sys.argv:
        json.dump(result, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)
    print("Lowest CIEDE2000 of each class against a ground: normal / protanopia / deuteranopia / tritanopia, WCAG ratio there")
    for name, by_ground in result["vs_ground"].items():
        ground, v = lowest(by_ground)
        print(f"  {name:18s} on {ground:12s} {v['normal']:5.1f} {v['protanopia']:5.1f} {v['deuteranopia']:5.1f} {v['tritanopia']:5.1f}   {v['wcag']}")
    print("Class pairs, lowest over the grounds")
    for pair, by_ground in result["pairs"].items():
        ground, v = lowest(by_ground)
        print(f"  {pair:32s} on {ground:12s} {v['normal']:5.1f} {v['protanopia']:5.1f} {v['deuteranopia']:5.1f} {v['tritanopia']:5.1f}")
    print("Labels on their halo (WCAG):", result["labels"])


if __name__ == "__main__":
    main()
