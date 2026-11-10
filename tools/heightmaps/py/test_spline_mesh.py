"""Tests of the spline mesh deformation: python -m unittest test_spline_mesh

A slab 10 m long, 4 m wide and 0.5 m thick is laid along a straight spline that runs east (+X), so the spline's right is south
(+Y, up x direction) and the bent slab can be read off its box.
"""

import itertools
import math
import unittest

import numpy as np

import spline_mesh

LENGTH, WIDTH, THICKNESS = 1000.0, 400.0, 50.0
EAST = {"X": LENGTH, "Y": 0.0, "Z": 0.0}


def spline(axis, roll=0.0, scale=(1.0, 1.0), offset=(0.0, 0.0), end_roll=None):
    """A straight segment from the origin 10 m east, with the same scale and offset at both ends."""
    pair = lambda values: {"X": values[0], "Y": values[1]}
    return {"p": {"StartPos": {"X": 0.0, "Y": 0.0, "Z": 0.0}, "StartTangent": EAST, "StartScale": pair(scale), "StartRoll": roll, "StartOffset": pair(offset),
                  "EndPos": EAST, "EndTangent": EAST, "EndScale": pair(scale), "EndRoll": roll if end_roll is None else end_roll, "EndOffset": pair(offset)},
            "axis": axis, "up": {"X": 0.0, "Y": 0.0, "Z": 1.0}}


def slab(forward, across, upward):
    """Corners [8, 3] of the slab with its length from 0 along mesh axis ``forward``, its width centred on ``across`` and its thickness from 0 along ``upward``."""
    corners = np.zeros((8, 3))
    for row, (along, side, height) in enumerate(itertools.product((0.0, LENGTH), (-WIDTH / 2, WIDTH / 2), (0.0, THICKNESS))):
        corners[row, forward], corners[row, across], corners[row, upward] = along, side, height
    return corners


def bent(corners, record, normals=None):
    return spline_mesh.bend_along_spline(corners, record, (corners.min(0), corners.max(0)), normals)


class BendAlongSpline(unittest.TestCase):
    def test_a_mesh_that_runs_along_x_lies_as_it_is_modelled(self):
        positions, normals = bent(slab(0, 1, 2), spline("X"))
        np.testing.assert_allclose(positions.min(0), (0, -WIDTH / 2, 0), atol=1e-6)
        np.testing.assert_allclose(positions.max(0), (LENGTH, WIDTH / 2, THICKNESS), atol=1e-6)
        self.assertIsNone(normals)

    def test_a_quarter_turn_stands_a_mesh_that_runs_along_y_up(self):
        # Manicouagan's pipeline, crash barriers and railway tracks: the landscape splines give every such mesh this roll
        positions, _ = bent(slab(1, 0, 2), spline("Y", roll=-math.pi / 2))
        np.testing.assert_allclose(positions.min(0), (0, -WIDTH / 2, 0), atol=1e-6)
        np.testing.assert_allclose(positions.max(0), (LENGTH, WIDTH / 2, THICKNESS), atol=1e-6)

    def test_without_the_roll_its_x_axis_is_up(self):
        positions, _ = bent(slab(1, 0, 2), spline("Y"))
        np.testing.assert_allclose(positions.min(0), (0, 0, -WIDTH / 2), atol=1e-6)
        np.testing.assert_allclose(positions.max(0), (LENGTH, THICKNESS, WIDTH / 2), atol=1e-6)

    def test_the_roll_puts_the_positive_x_of_a_y_mesh_on_the_left(self):
        corners = slab(1, 0, 2)
        positions, _ = bent(corners, spline("Y", roll=-math.pi / 2))
        np.testing.assert_allclose(positions[:, 1], -corners[:, 0], atol=1e-6)
        np.testing.assert_allclose(positions[:, 2], corners[:, 2], atol=1e-6)

    def test_the_offset_is_not_turned_by_the_roll(self):
        # The engine moves the slice along the unrolled frame and then rolls the mesh about its direction
        positions, _ = bent(slab(1, 0, 2), spline("Y", roll=-math.pi / 2, offset=(300.0, 20.0)))
        np.testing.assert_allclose(positions.min(0), (0, 300 - WIDTH / 2, 20), atol=1e-6)
        np.testing.assert_allclose(positions.max(0), (LENGTH, 300 + WIDTH / 2, 20 + THICKNESS), atol=1e-6)

    def test_the_scales_follow_the_frame_not_the_mesh_axes(self):
        # Scale X is that of the mesh axis along the frame's X vector: Z for a mesh that runs along Y, its thickness
        positions, _ = bent(slab(1, 0, 2), spline("Y", roll=-math.pi / 2, scale=(2.0, 0.5)))
        np.testing.assert_allclose(positions.min(0), (0, -WIDTH / 4, 0), atol=1e-6)
        np.testing.assert_allclose(positions.max(0), (LENGTH, WIDTH / 4, 2 * THICKNESS), atol=1e-6)

    def test_a_roll_that_changes_along_the_segment_is_blended_by_smoothstep(self):
        corners = np.array([[0.0, 100.0, 0.0], [LENGTH / 4, 100.0, 0.0], [LENGTH / 2, 100.0, 0.0], [LENGTH, 100.0, 0.0]])
        positions, _ = spline_mesh.bend_along_spline(corners, spline("X", roll=0.0, end_roll=math.pi / 2), (np.zeros(3), np.array([LENGTH, 0.0, 0.0])))
        angles = np.degrees(np.arctan2(-positions[:, 2], positions[:, 1]))
        np.testing.assert_allclose(angles, (0.0, 90 * (3 / 16 - 2 / 64), 45.0, 90.0), atol=1e-6)

    def test_normals_turn_with_the_mesh(self):
        corners = slab(1, 0, 2)
        up = np.tile((0.0, 0.0, 1.0), (len(corners), 1))
        _, rolled = bent(corners, spline("Y", roll=-math.pi / 2), up)
        _, unrolled = bent(corners, spline("Y"), up)
        np.testing.assert_allclose(rolled, up, atol=1e-6)
        np.testing.assert_allclose(unrolled, np.tile((0.0, 1.0, 0.0), (len(corners), 1)), atol=1e-6)


class AxisAcross(unittest.TestCase):
    def test_the_axis_and_its_direction_are_those_of_the_bent_mesh(self):
        # One point a metre out on every mesh axis: the axis named must be the one that lands level beside the spline, on the side named
        for axis, roll, scale in itertools.product("XYZ", (0.0, -math.pi / 2, math.pi / 2, math.pi, 0.2, -1.4), ((1.0, 1.0), (-1.0, 1.0), (1.0, -1.0))):
            with self.subTest(axis=axis, roll=roll, scale=scale):
                record = spline(axis, roll=roll, scale=scale)
                across, towards_right = spline_mesh.axis_across(record)
                point = np.zeros((1, 3))
                point[0, across] = 100.0
                positions, _ = spline_mesh.bend_along_spline(point, record, (np.zeros(3), np.ones(3)))
                self.assertGreater(towards_right * positions[0, 1], abs(positions[0, 2]))

    def test_the_landscape_splines_cases(self):
        self.assertEqual(spline_mesh.axis_across(spline("X")), (1, 1))
        self.assertEqual(spline_mesh.axis_across(spline("X", scale=(-1.0, 1.0))), (1, -1))
        self.assertEqual(spline_mesh.axis_across(spline("Y", roll=-math.pi / 2)), (0, -1))
        self.assertEqual(spline_mesh.axis_across(spline("Y", roll=-math.pi / 2, scale=(1.0, -1.0))), (0, 1))
        self.assertEqual(spline_mesh.axis_across(spline("Z", roll=-math.pi / 2)), (1, -1))

    def test_a_banked_road_keeps_its_axis(self):
        self.assertEqual(spline_mesh.axis_across(spline("X", roll=math.radians(37), end_roll=math.radians(28))), (1, 1))

    def test_missing_parameters_are_the_engines_defaults(self):
        record = spline("X")
        for key in ("StartScale", "EndScale", "StartRoll", "EndRoll", "StartOffset", "EndOffset"):
            del record["p"][key]
        self.assertEqual(spline_mesh.axis_across(record), (1, 1))
        positions, _ = bent(slab(0, 1, 2), record)
        np.testing.assert_allclose(positions.max(0), (LENGTH, WIDTH / 2, THICKNESS), atol=1e-6)


if __name__ == "__main__":
    unittest.main()
