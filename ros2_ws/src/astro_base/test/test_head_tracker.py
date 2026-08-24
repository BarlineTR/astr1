#!/usr/bin/env python3
"""Unit tests for ASTRO social sound-localization head tracking node."""

import collections
import math
import os
import sys
import time
import unittest

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)

from astro_base.head_tracker_node import (
    HeadTrackerNode,
    SocialGazeStateMachine,
    doa_to_robot_yaw,
)


class TestDoaConversion(unittest.TestCase):
    def test_standard_angles(self):
        # 0 deg (straight ahead) -> 0.0
        self.assertAlmostEqual(doa_to_robot_yaw(0.0), 0.0)
        # 90 deg (right side) -> 90.0
        self.assertAlmostEqual(doa_to_robot_yaw(90.0), 90.0)
        # 180 deg (back) -> 180.0
        self.assertAlmostEqual(doa_to_robot_yaw(180.0), 180.0)
        # 270 deg (left side) -> -90.0
        self.assertAlmostEqual(doa_to_robot_yaw(270.0), -90.0)
        # 315 deg (front-left) -> -45.0
        self.assertAlmostEqual(doa_to_robot_yaw(315.0), -45.0)
        # 45 deg (front-right) -> 45.0
        self.assertAlmostEqual(doa_to_robot_yaw(45.0), 45.0)

    def test_offset_and_inversion(self):
        # 0 with 90 offset -> 90.0
        self.assertAlmostEqual(doa_to_robot_yaw(0.0, offset_deg=90.0), 90.0)
        # 90 with inversion -> -90.0
        self.assertAlmostEqual(doa_to_robot_yaw(90.0, invert=True), -90.0)


class MockMsg:
    def __init__(self, data):
        self.data = data


class TestSocialGazeLogic(unittest.TestCase):
    def setUp(self):
        # Instantiate HeadTrackerNode with test defaults without requiring live ROS 2 daemon
        self.node = HeadTrackerNode()
        self.node.enabled = True
        self.node.deadband_deg = 12.0
        self.node.min_dwell_time_s = 2.0
        self.node.max_yaw_deg = 70.0
        self.node.min_yaw_deg = -70.0
        self.node.min_rms_threshold = 500.0
        self.node.noise_multiplier = 2.0
        self.node.consensus_threshold = 3
        self.node.consensus_tolerance_deg = 15.0

    def test_consensus_clustering(self):
        """Test that temporal consensus filters out isolated outlier spikes and averages true cluster."""
        # 3 samples around 45° and 2 outlier spikes at -60° and 150°
        self.node._doa_history = collections.deque([
            (1.0, 44.0),
            (1.1, -60.0),  # Outlier
            (1.2, 46.0),
            (1.3, 150.0),  # Outlier
            (1.4, 45.0),
        ], maxlen=5)

        consensus = self.node._evaluate_consensus()
        self.assertIsNotNone(consensus)
        # Average of (44.0, 46.0, 45.0) = 45.0
        self.assertAlmostEqual(consensus, 45.0, places=1)

    def test_consensus_rejects_chaotic_noise(self):
        """Test that when all samples are scattered, no consensus is reached."""
        self.node._doa_history = collections.deque([
            (1.0, 10.0),
            (1.1, 70.0),
            (1.2, -45.0),
            (1.3, 130.0),
            (1.4, -80.0),
        ], maxlen=5)

        consensus = self.node._evaluate_consensus()
        self.assertIsNone(consensus)

    def test_self_voice_suppression(self):
        """Test that DOA is ignored while the robot is speaking (no self-voice feedback loop)."""
        self.node._is_speaking = True
        self.node._current_yaw = 0.0
        self.node._target_yaw = 0.0

        # Feed loud DOA while speaking
        self.node._latest_rms = 5000.0
        self.node._on_doa(MockMsg(45.0))
        self.assertEqual(len(self.node._doa_history), 0)
        self.assertEqual(self.node._target_yaw, 0.0)

    def test_deadband_hysteresis(self):
        """Test that small angle variations (<12°) do not cause head movement."""
        self.node._current_yaw = 0.0
        self.node._target_yaw = 0.0
        self.node._latest_rms = 1500.0
        self.node._ambient_rms = 200.0
        self.node._last_gaze_switch_time = 0.0  # Dwell time satisfied

        # Feed 3 consistent 8° DOA readings (below 12° deadband)
        for _ in range(3):
            self.node._on_doa(MockMsg(8.0))

        self.assertEqual(self.node._target_yaw, 0.0)

    def test_gaze_dwell_time(self):
        """Test that a new gaze direction is held for at least min_dwell_time_s."""
        self.node._current_yaw = 0.0
        self.node._target_yaw = 0.0
        self.node._latest_rms = 1500.0
        self.node._ambient_rms = 200.0
        self.node._last_gaze_switch_time = 0.0  # Dwell satisfied initially

        # 1. Turn to 45°
        for _ in range(3):
            self.node._on_doa(MockMsg(45.0))
        self.assertAlmostEqual(self.node._target_yaw, 45.0, places=1)

        # 2. Immediately try to switch to -45° within dwell window (0.1s later)
        import time
        now = time.monotonic()
        self.node._last_gaze_switch_time = now - 0.2  # only 0.2s elapsed (< 2.0s dwell)
        self.node._doa_history.clear()
        for _ in range(3):
            self.node._on_doa(MockMsg(315.0))  # 315° = -45°

        # Target should still be 45.0°, not -45.0°
        self.assertAlmostEqual(self.node._target_yaw, 45.0, places=1)

    def test_slew_rate_velocity_limiting(self):
        """Test that the control loop limits angular step size per cycle (smooth velocity profile)."""
        self.node._current_yaw = 0.0
        self.node._target_yaw = 60.0
        self.node.max_speed_deg_s = 40.0  # 40 deg/sec

        # Simulate 1 step of 0.1s (dt = 0.1s -> max step = 4.0 deg)
        self.node._last_update_time = time.monotonic() - 0.1
        self.node._control_loop()

        self.assertAlmostEqual(self.node._current_yaw, 4.0, delta=0.5)


if __name__ == "__main__":
    unittest.main()
