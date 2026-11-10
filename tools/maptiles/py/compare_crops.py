"""Before / after crops of two tile folders of a map side by side, as PNG.

Usage: compare_crops.py <out dir> <map> <before folder> <after folder> <x m>,<y m> [<x m>,<y m> ...] [--width M]

Each place gives two pictures: the window of ``--width`` metres at the finest zoom of each folder (``<map>_<n>_native.png``) and the
window of a quarter of that width, two zooms closer, as the browser shows it when it stretches the finest tiles
(``<map>_<n>_close.png``, bilinear like the browser). Left is before, right is after; both show the same world window.
"""

import argparse
import json
import os

from PIL import Image, ImageDraw

OUT_PX = 768


def finest(folder):
    """(max native zoom, bounds of the map in m) from a tile folder's meta.json."""
    meta = json.load(open(os.path.join(folder, "meta.json")))
    return meta["maxNativeZoom"], meta["bounds_m"]


def window(folder, centre, width_m, out_px=OUT_PX):
    """RGB picture [out_px, out_px] of the world window of width_m around centre, from the finest zoom of the folder."""
    zoom, b = finest(folder)
    size_x, size_y = b["max_x"] - b["min_x"], b["max_y"] - b["min_y"]
    pixels = 256 * 2 ** zoom
    x0, y0 = centre[0] - width_m / 2, centre[1] - width_m / 2
    gx0, gx1 = (x0 - b["min_x"]) / size_x * pixels, (x0 + width_m - b["min_x"]) / size_x * pixels
    gy0, gy1 = (y0 - b["min_y"]) / size_y * pixels, (y0 + width_m - b["min_y"]) / size_y * pixels
    tx0, tx1, ty0, ty1 = int(gx0 // 256), int(gx1 // 256), int(gy0 // 256), int(gy1 // 256)
    mosaic = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (128, 128, 128))
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            path = os.path.join(folder, str(zoom), f"{tx}_{ty}.webp")
            if os.path.exists(path):
                mosaic.paste(Image.open(path).convert("RGB"), ((tx - tx0) * 256, (ty - ty0) * 256))
    box = (gx0 - tx0 * 256, gy0 - ty0 * 256, gx1 - tx0 * 256, gy1 - ty0 * 256)
    return mosaic.resize((out_px, out_px), Image.BILINEAR, box=box)


def pair(before, after, centre, width_m, caption):
    """Side-by-side picture of the two folders over the same window."""
    left, right = window(before, centre, width_m), window(after, centre, width_m)
    image = Image.new("RGB", (2 * OUT_PX + 8, OUT_PX + 24), (255, 255, 255))
    image.paste(left, (0, 24))
    image.paste(right, (OUT_PX + 8, 24))
    draw = ImageDraw.Draw(image)
    draw.text((6, 6), f"before  {caption}", fill=(0, 0, 0))
    draw.text((OUT_PX + 14, 6), f"after  {caption}", fill=(0, 0, 0))
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out")
    parser.add_argument("map")
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("places", nargs="+")
    parser.add_argument("--width", type=float, default=60.0)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    for n, place in enumerate(args.places, 1):
        centre = tuple(float(v) for v in place.split(","))
        for name, width in (("native", args.width), ("close", args.width / 4)):
            path = os.path.join(args.out, f"{args.map}_{n}_{name}.png")
            pair(args.before, args.after, centre, width, f"{args.map} {centre[0]:.0f},{centre[1]:.0f}  {width:.0f} m wide").save(path)
            print(path)


if __name__ == "__main__":
    main()
