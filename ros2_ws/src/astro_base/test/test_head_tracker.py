#!/usr/bin/env python3
"""Unit tests for ASTRO social sound-localization head tracking node."""

import collections
import math
import os
import sys
import time
import unittest

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
astro_base_inner = os.path.join(pkg_dir, "astro_base")
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)
if astro_base_inner not in sys.path:
    sys.path.insert(0, astro_base_inner)

try:
    from astro_base.head_tracker_node import (
        HeadTrackerNode,
        SocialGazeStateMachine,
        doa_to_robot_yaw,
    )
except ImportError:
    from head_tracker_node import (
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


class _FakeClock:
    """The head only reacts to speech that has lasted a while, so tests have to let time
    pass. Real sleeps would make the suite crawl, so the module's clock is swapped out."""

    def __init__(self, start=None):
        # Start from the real clock: fixtures build state out of time.monotonic() (dwell
        # timers, last-seen stamps), and a clock that starts somewhere else would make
        # those look like they happened in the future.
        self.t = time.monotonic() if start is None else start

    def monotonic(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def feed_speech(node, doa_deg, frames=14, dt=0.05):
    """Speak steadily from one direction for `frames` frames at 20 Hz."""
    module = sys.modules[HeadTrackerNode.__module__]
    clock = _FakeClock()
    real_time = module.time
    module.time = clock
    try:
        node._last_update_time = clock.monotonic()
        for _ in range(frames):
            node._on_doa(MockMsg(doa_deg))
            clock.advance(dt)
        return clock.monotonic()
    finally:
        module.time = real_time


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
        self.node.doa_offset_deg = 0.0
        self.node.doa_invert = False
        self.node.lidar_fusion_enabled = True
        self.node._doa_history.clear()
        self.node._target_yaw = 0.0
        self.node._current_yaw = 0.0
        self.node._filtered_target_yaw = 0.0
        self.node._is_speaking = False
        self.node._is_playback_active = False
        self.node._is_sleeping = False
        self.node._vad_active = True
        self.node.vision_fusion_enabled = False
        self.node._vision_person_detected = False

    def test_sleep_mode_locks_head_and_rejects_doa(self):
        """Test that when robot is in sleep mode, DOA is ignored and head target stays 0.0°."""
        self.node._is_sleeping = True
        self.node._latest_rms = 5000.0
        self.node._vad_active = True
        for _ in range(10):
            self.node._on_doa(MockMsg(45.0))
        self.assertEqual(len(self.node._doa_history), 0)
        self.assertEqual(self.node._target_yaw, 0.0)

    def test_180_deg_speech_clamps_to_max_yaw(self):
        """Test that speech from behind (>70°) safely clamps to physical neck limit (+70° or -70°)."""
        self.node._doa_history.clear()
        self.node._current_yaw = 0.0
        self.node._target_yaw = 0.0
        self.node.doa_offset_deg = 0.0
        self.node.doa_invert = False
        self.node._latest_rms = 3000.0
        self.node._vad_active = True
        self.node._last_gaze_switch_time = 0.0
        feed_speech(self.node, 170.0)
        self.assertEqual(self.node._target_yaw, 70.0)

    def test_scattered_bearings_do_not_move_the_head(self):
        """A tilted array in a live room throws bearings all over the place -- the field
        logs show -88, -161, -3, -135 and +45 arriving inside 300 ms. No direction is
        busier than any other there, so the head must stay where it is."""
        self.node._current_yaw = 0.0
        self.node._target_yaw = 0.0
        self.node._latest_rms = 3000.0
        self.node._ambient_rms = 200.0
        self.node._last_gaze_switch_time = 0.0

        module = sys.modules[HeadTrackerNode.__module__]
        clock = _FakeClock()
        real_time = module.time
        module.time = clock
        try:
            for doa in (12.0, 200.0, 88.0, 315.0, 175.0, 44.0, 260.0, 130.0,
                        20.0, 300.0, 95.0, 240.0, 160.0, 60.0):
                self.node._on_doa(MockMsg(doa))
                clock.advance(0.05)
        finally:
            module.time = real_time

        self.assertEqual(
            self.node._target_yaw,
            0.0,
            f"Dagilmis kerterizler kafayi {self.node._target_yaw:.1f} dereceye surdu.",
        )

    def test_a_consistent_direction_does_move_the_head(self):
        """The counterpart: the same gates must not block a real talker."""
        self.node._current_yaw = 0.0
        self.node._target_yaw = 0.0
        self.node._latest_rms = 3000.0
        self.node._ambient_rms = 200.0
        self.node._last_gaze_switch_time = 0.0

        feed_speech(self.node, 45.0)
        self.assertAlmostEqual(
            self.node._target_yaw,
            45.0,
            delta=8.0,
            msg=f"Tutarli bir kaynak kafayi hareket ettirmedi ({self.node._target_yaw:.1f}).",
        )

    def test_gaze_dwell_time(self):
        """Test that a new gaze direction is held for at least min_dwell_time_s."""
        self.node._doa_history.clear()
        self.node._current_yaw = 0.0
        self.node._target_yaw = 0.0
        self.node._latest_rms = 2500.0
        self.node._ambient_rms = 200.0
        self.node._last_gaze_switch_time = 0.0  # Dwell satisfied initially

        # 1. Turn to 45°
        feed_speech(self.node, 45.0)
        self.assertAlmostEqual(self.node._target_yaw, 45.0, delta=6.0)
        held = self.node._target_yaw

        # 2. Immediately try to switch to -45° within the dwell window
        import time
        self.node._last_gaze_switch_time = time.monotonic() - 0.2  # 0.2s < 2.0s dwell
        self.node._speech_map.clear()
        self.node._doa_history.clear()
        feed_speech(self.node, 315.0)  # 315° = -45°

        self.assertAlmostEqual(
            self.node._target_yaw,
            held,
            delta=1.0,
            msg="Bakis suresi dolmadan yeni konusmaciya atlanmamali.",
        )

    def test_slew_rate_velocity_limiting(self):
        """Test that the control loop limits angular step size per cycle (smooth velocity profile)."""
        self.node._current_yaw = 0.0
        self.node._target_yaw = 60.0
        self.node.max_speed_deg_s = 40.0  # 40 deg/sec
        # Prevent idle timeout from resetting _target_yaw to 0° during this test
        self.node._last_speech_time = time.monotonic()
        # Ensure vision fusion doesn't interfere
        self.node._vision_person_detected = False

        # Simulate 1 step of 0.1s (dt = 0.1s -> max step = 4.0 deg)
        self.node._last_update_time = time.monotonic() - 0.1
        self.node._control_loop()
        self.assertAlmostEqual(self.node._current_yaw, 4.0, places=1)

    def test_lidar_radar_gaze_orientation(self):
        """Test that approaching person detected on LiDAR/Radar smoothly steers head target."""
        class MockLaserScan:
            def __init__(self, target_angle_deg=35.0, distance_m=1.5):
                self.angle_min = -math.pi
                self.angle_increment = math.radians(1.0)
                self.range_min = 0.15
                self.range_max = 12.0
                # 360 ranges (index 0 = -180°, index 180 = 0°, index 215 = +35°)
                self.ranges = [10.0] * 360
                idx = int((math.radians(target_angle_deg) - self.angle_min) / self.angle_increment)
                if 0 <= idx < 360:
                    self.ranges[idx] = distance_m

        self.node.enabled = True
        self.node.lidar_fusion_enabled = True
        self.node.lidar_min_dist_m = 0.4
        self.node.lidar_max_dist_m = 2.8
        self.node._is_sleeping = False
        self.node._current_yaw = 0.0
        self.node._target_yaw = 0.0
        self.node._vad_active = False
        self.node._vision_person_detected = False
        self.node._last_gaze_switch_time = time.monotonic() - 5.0  # Dwell satisfied

        scan_msg = MockLaserScan(target_angle_deg=35.0, distance_m=1.5)
        self.node._on_laser_scan(scan_msg)

        self.assertTrue(self.node._lidar_person_detected)
        self.assertAlmostEqual(self.node._lidar_target_yaw, 35.0, places=1)

        # Run control loop tick
        self.node._last_update_time = time.monotonic() - 0.05
        self.node._control_loop()

        self.assertAlmostEqual(self.node._target_yaw, 35.0, places=1)


if __name__ == "__main__":
    unittest.main()
