"""Relay message parsing of the AGS-17 timer overlay."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ags17_timer import Target, parse_targets  # noqa: E402


def test_targets_and_unreachable_lines():
    message = "1.25s | 123.4° | 1500m | +12m\n--- | 10.0° | 2500m\nNaNs | 5.0° | 100m"

    assert parse_targets(message) == [
        Target(1.25, 123.4, 1500),
        Target(None, 10.0, 2500),
        Target(None, 5.0, 100),
    ]


def test_weapon_line_is_not_a_target():
    # SquadCalc Deadline adds the Squad Ballistics weapon after the targets.
    message = "1.25s | 123.4° | 1500m | +12m\nweapon: AGS-17 · emplacement"

    assert parse_targets(message) == [Target(1.25, 123.4, 1500)]
    assert parse_targets("weapon: NSV") == []
    assert parse_targets("") == []
