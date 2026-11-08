"""Where the whole-map texture lies on the render: the capture of some maps is off their frame (Skorpo by 12 m, Kamdesh and Kokan by 3 m).

Colours are fitted to the texture cell by cell, so a capture that lies beside the geometry would print its roofs on the ground. Gradient
magnitudes of a grid of patches are correlated; the shifts of the patches that correlate give an offset and a scale per axis.
"""
import numpy as np
from scipy import ndimage

PATCHES = 5
PATCH_SHARE = 0.2
SEARCH_M = 30.0
MINIMUM_CORRELATION = 0.15
MINIMUM_PATCHES = 3
# A scale needs patches over most of the axis
MINIMUM_PATCHES_FOR_SCALE = 8
OUTLIER_PX = 2.0
# A scale spreads the shifts of a map: Skorpo has -5 to -13 px from west to east
SPREAD_PX = 8.0
# Below this shift (m) a warp changes nothing that can be seen and would only blur the texture
MINIMUM_SHIFT_M = 1.5


def edges(image):
    """Gradient magnitude of the smoothed luminance of an RGB array."""
    smooth = ndimage.gaussian_filter(image.astype(np.float32).mean(-1), 1.0)
    return np.hypot(ndimage.sobel(smooth, 1), ndimage.sobel(smooth, 0))


def measure_shift(reference, moving, search):
    """(dy, dx, correlation): `reference` holds the content of `moving` that far down and to the right, at most `search` px."""
    a, b = reference - reference.mean(), moving - moving.mean()
    product = np.fft.irfft2(np.fft.rfft2(a) * np.conj(np.fft.rfft2(b)), a.shape)
    rows, columns = a.shape
    near = np.zeros(a.shape, bool)
    near[np.ix_(np.r_[0:search + 1, rows - search:rows], np.r_[0:search + 1, columns - search:columns])] = True
    product[~near] = -np.inf
    row, column = np.unravel_index(np.argmax(product), a.shape)
    correlation = product[row, column] / (a.size * a.std() * b.std() + 1e-6)
    return int(row - rows if row > rows // 2 else row), int(column - columns if column > columns // 2 else column), float(correlation)


def patch_shifts(rendered, texture, step_m):
    """Shifts of patches of `texture` against `rendered` (RGB, the same grid of `step_m` m): list of (centre x, centre y as 0..1, dx, dy) in px."""
    a, b = edges(rendered), edges(texture)
    size = a.shape[0]
    side = int(size * PATCH_SHARE)
    search = int(round(SEARCH_M / step_m))
    shifts = []
    for j in range(PATCHES):
        for i in range(PATCHES):
            y, x = (size - side) * j // (PATCHES - 1), (size - side) * i // (PATCHES - 1)
            dy, dx, correlation = measure_shift(b[y:y + side, x:x + side], a[y:y + side, x:x + side], search)
            if correlation >= MINIMUM_CORRELATION:
                shifts.append(((x + side / 2) / size, (y + side / 2) / size, dx, dy))
    return shifts


def fit_axis(positions, shifts, with_scale):
    """(offset, slope) of `shifts` over `positions` by least squares; patches far from the median and then from the fit are left out."""
    median = float(np.median(shifts))
    keep = np.abs(shifts - median) <= (SPREAD_PX if with_scale else OUTLIER_PX)
    if not with_scale:
        return float(shifts[keep].mean()), 0.0
    slope, offset = 0.0, median
    for _ in range(2):
        if keep.sum() < MINIMUM_PATCHES:
            return median, 0.0
        slope, offset = np.polyfit(positions[keep], shifts[keep], 1)
        keep = np.abs(offset + slope * positions - shifts) <= OUTLIER_PX
    return float(offset), float(slope)


def fit_warp(shifts, step_m):
    """(dx offset, dx slope, dy offset, dy slope) in metres over the frame (position 0..1), or None when the texture lies on the render."""
    if len(shifts) < MINIMUM_PATCHES:
        return None
    u, v, dx, dy = (np.array(values, np.float64) for values in zip(*shifts))
    with_scale = len(shifts) >= MINIMUM_PATCHES_FOR_SCALE
    x_offset, x_slope = fit_axis(u, dx, with_scale)
    y_offset, y_slope = fit_axis(v, dy, with_scale)
    largest = max(abs(x_offset), abs(x_offset + x_slope), abs(y_offset), abs(y_offset + y_slope)) * step_m
    if largest < MINIMUM_SHIFT_M:
        return None
    return tuple(float(value * step_m) for value in (x_offset, x_slope, y_offset, y_slope))


def warp_texture(texture, warp, frame_size_m):
    """`texture` (RGB, covering frame_size_m) with its content moved onto the render by the result of `fit_warp`."""
    size = texture.shape[0]
    per_metre = size / frame_size_m
    columns = np.arange(size, dtype=np.float64) + (warp[0] + warp[1] * np.linspace(0, 1, size)) * per_metre
    rows = np.arange(size, dtype=np.float64) + (warp[2] + warp[3] * np.linspace(0, 1, size)) * per_metre
    grid = np.meshgrid(rows, columns, indexing="ij")
    return np.dstack([ndimage.map_coordinates(texture[..., c], grid, order=1, mode="nearest") for c in range(3)])
