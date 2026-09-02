#!/usr/bin/env python3
"""Head travel limits, and what happens when the encoder never reports back.

Two things make the head stop following a person who is still standing there.

The first is the soft limit. The firmware clamps at +/-180 deg and the calibration
file documents the encoder scale as 440 ticks over 170 deg of travel, so the
mechanism itself turns +/-85 — but the gaze stack clamped every command to +/-75
and simply stopped short of a person standing further round.

The second is worse because it is silent. Every bearing is computed as
`body_azimuth = actual_head_yaw + camera_azimuth`. When no encoder feedback
arrives, actual_head_yaw stays at 0 while the head physically turns, so a person
centred in the frame after a 20 deg turn is computed to be at 0 deg — and the head
is commanded straight back to centre, where it sits. Nothing in the pipeline said
anything was wrong; the node simply used its default.
"""

import os
import unittest

import yaml

from astro_base.gaze.coordinate_frames import CalibrationConfig
from astro_base.social_gaze_node import SocialGazeNode


CALIBRATION = os.path.join(
    os.path.dirname(__file__), "..", "config", "calibration_params.yaml"
)


class TestHeadTravel(unittest.TestCase):
    """440 ticks / 170 deg is the range the encoder was actually characterised over."""

    DOCUMENTED_HALF_TRAVEL = 85.0

    def _head_config(self) -> dict:
        with open(CALIBRATION, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)["/**"]["ros__parameters"]["head"]

    def test_the_configured_limits_use_the_measured_travel(self):
        head = self._head_config()

        self.assertLessEqual(head["min_angle_deg"], -self.DOCUMENTED_HALF_TRAVEL)
        self.assertGreaterEqual(head["max_angle_deg"], self.DOCUMENTED_HALF_TRAVEL)

    def test_the_limits_stay_inside_what_the_firmware_accepts(self):
        """arduino/astro_firmware clamps to +/-180; never command past it."""
        head = self._head_config()

        self.assertGreaterEqual(head["min_angle_deg"], -180.0)
        self.assertLessEqual(head["max_angle_deg"], 180.0)

    def test_the_code_default_matches_the_configured_travel(self):
        """A node started without the calibration file must not be more timid."""
        head = CalibrationConfig().head

        self.assertLessEqual(head.min_angle_deg, -self.DOCUMENTED_HALF_TRAVEL)
        self.assertGreaterEqual(head.max_angle_deg, self.DOCUMENTED_HALF_TRAVEL)


class _Msg:
    def __init__(self, data):
        self.data = data


class TestMissingHeadFeedbackIsReported(unittest.TestCase):
    """Assuming 0 deg while the head is elsewhere collapses every bearing to centre."""

    def test_a_node_that_never_heard_from_the_encoder_says_so(self):
        node = SocialGazeNode()

        self.assertTrue(node.head_feedback_missing())

    def test_feedback_from_the_head_state_topic_clears_it(self):
        node = SocialGazeNode()

        node._on_head_state(type("S", (), {"position_deg": 12.0, "velocity_deg_s": 0.0})())

        self.assertFalse(node.head_feedback_missing())

    def test_feedback_from_joint_states_clears_it(self):
        node = SocialGazeNode()
        msg = type("J", (), {"name": ["head_yaw_joint"], "position": [0.2], "velocity": [0.0]})()

        node._on_joint_states(msg)

        self.assertFalse(node.head_feedback_missing())

    def test_the_control_cycle_warns_exactly_once_while_feedback_is_absent(self):
        """A per-cycle warning at 50 Hz would bury the log it needs to stand out in."""
        node = SocialGazeNode()
        warnings = []
        node.get_logger().warning = lambda msg, *a, **k: warnings.append(msg)

        for _ in range(120):
            node._control_cycle()

        self.assertEqual(len(warnings), 1)
        self.assertIn("geri besleme", warnings[0].lower())


if __name__ == "__main__":
    unittest.main()
