"""Deformation of a static mesh along a spline segment (USplineMeshComponent), for the tools that draw the client scene
(tools/maprender, tools/maptiles).

A spline mesh component lays its mesh along a cubic Hermite segment. Every vertex belongs to the slice of the mesh at its
coordinate along the forward axis, and the engine places a slice by its slice transform
(USplineMeshComponent::CalcSliceTransformAtSplineOffset): the spline's position and direction there, the frame across it
(X vector = up x direction, the spline's right; Y vector = direction x X vector), the offset along that frame, the roll that
turns the frame about the direction, and the scale of the two mesh axes that are laid along the turned frame.

``spline`` is the component's record in instances.ndjson of ``SquadExtract scene``: ``p`` (FSplineMeshParams: StartPos,
StartTangent, StartScale, StartRoll in radians, StartOffset and the same for End), ``axis`` (the forward axis: "X", "Y" or
"Z") and ``up`` (SplineUpDir). Positions are centimetres in the component's space.
"""

import numpy as np

FORWARD_AXIS = {"X": 0, "Y": 1, "Z": 2}
# Per forward axis, the mesh axes laid along the slice's X vector and along its Y vector
SLICE_AXES = [(1, 2), (2, 0), (0, 1)]


def bend_along_spline(positions, spline, bounds, normals=None):
    """(positions [n, 3], normals [n, 3] or None) of a mesh deformed along its spline.

    ``positions`` and ``normals`` are the mesh's own; ``bounds`` is (lowest corner, highest corner) of the mesh, whose extent
    along the forward axis is laid over the whole segment. Scale, offset and roll are blended by smoothstep between the
    segment's ends, as the landscape splines set their components.

    The roll matters wherever the mesh does not lie in the frame as it is modelled. A mesh whose forward axis is Y has its Z
    axis along the frame's X vector and its X axis up, so the landscape splines give it a roll of -90 degrees to stand it up
    (pipelines, crash barriers, railway tracks, fences): without the roll it lies on its side and off its line. With it the box
    of a bent mesh is the box of the server's cooked collision of the same component, to 2 cm on the median of the mesh on a map
    for 9 943 of the 10 419 components the landscape splines of the 25 maps roll (tools/maprender/README.md).
    """
    p = spline["p"]
    vec = lambda v: np.array([v["X"], v["Y"], v["Z"]], np.float64)
    p0, t0, p1, t1 = vec(p["StartPos"]), vec(p["StartTangent"]), vec(p["EndPos"]), vec(p["EndTangent"])
    forward = FORWARD_AXIS[spline["axis"][-1]]
    side, up = SLICE_AXES[forward]
    lo, hi = bounds[0][forward], bounds[1][forward]
    a = np.clip((positions[:, forward] - lo) / max(hi - lo, 1e-3), 0, 1)[:, None]
    a2, a3 = a * a, a * a * a
    origin = (2 * a3 - 3 * a2 + 1) * p0 + (a3 - 2 * a2 + a) * t0 + (-2 * a3 + 3 * a2) * p1 + (a3 - a2) * t1
    direction = (6 * a2 - 6 * a) * p0 + (3 * a2 - 4 * a + 1) * t0 + (-6 * a2 + 6 * a) * p1 + (3 * a2 - 2 * a) * t1
    direction /= np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1e-6)
    world_up = vec(spline["up"]) if any(spline["up"][k] for k in "XYZ") else np.array([0.0, 0.0, 1.0])
    right = np.cross(world_up, direction)
    right /= np.maximum(np.linalg.norm(right, axis=1, keepdims=True), 1e-6)
    upward = np.cross(direction, right)
    start_scale, end_scale = p.get("StartScale", {"X": 1, "Y": 1}), p.get("EndScale", {"X": 1, "Y": 1})
    start_offset, end_offset = p.get("StartOffset", {"X": 0, "Y": 0}), p.get("EndOffset", {"X": 0, "Y": 0})
    blend = a * a * (3 - 2 * a)
    scale_x = start_scale["X"] * (1 - blend) + end_scale["X"] * blend
    scale_y = start_scale["Y"] * (1 - blend) + end_scale["Y"] * blend
    offset_x = start_offset["X"] * (1 - blend) + end_offset["X"] * blend
    offset_y = start_offset["Y"] * (1 - blend) + end_offset["Y"] * blend
    roll = p.get("StartRoll", 0.0) * (1 - blend) + p.get("EndRoll", 0.0) * blend
    x_vector = np.cos(roll) * right - np.sin(roll) * upward
    y_vector = np.cos(roll) * upward + np.sin(roll) * right
    bent = (origin + right * offset_x + upward * offset_y
            + x_vector * (positions[:, side:side + 1] * scale_x) + y_vector * (positions[:, up:up + 1] * scale_y))
    if normals is None:
        return bent, None
    turned = direction * normals[:, forward:forward + 1] + x_vector * normals[:, side:side + 1] + y_vector * normals[:, up:up + 1]
    return bent, turned / np.maximum(np.linalg.norm(turned, axis=1, keepdims=True), 1e-6)

