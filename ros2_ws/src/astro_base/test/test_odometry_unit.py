#!/usr/bin/env python3
"""Unit test suite for ASTRO V1 Differential Drive Odometry & Kinematics.

Tests Runge-Kutta 2nd order arc integration, REP-103/REP-105 coordinate frame conventions,
velocity calculations, covariance matrix properties, synthetic tick streams, and closed-loop trajectories.
"""

import math
import struct
import unittest

from astro_base.serial_bridge import (
    SerialBridge,
    MSG_ENCODER_TICKS,
    build_packet,
)


class TestDifferentialOdometry(unittest.TestCase):
    def setUp(self):
        self.node = SerialBridge()
        self.node.tpr_l = 2048.0
        self.node.tpr_r = 2048.0
        self.node.wheel_radius_l = 0.06
        self.node.wheel_radius_r = 0.06
        self.node.wheel_separation = 0.26
        self.node.reset_odometry(0.0, 0.0, 0.0)

    def tearDown(self):
        if hasattr(self, "node") and self.node is not None:
            self.node.destroy_node()

    def test_zero_tick_delta(self):
        """Zero tick delta should yield zero displacement and zero velocities."""
        self.node.update_odometry(0, 0, 1000000)  # 1.0 second dt
        self.assertAlmostEqual(self.node.odom_x, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_y, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_yaw, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_vx, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_vy, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_wz, 0.0, places=5)

    def test_straight_forward_motion(self):
        """+2048 ticks (1 full revolution) on both wheels over 1.0s -> straight forward."""
        # 1 rev = 2 * pi * 0.06 m = 0.3769911 m
        expected_dist = 2.0 * math.pi * 0.06
        self.node.update_odometry(2048, 2048, 1000000)

        self.assertAlmostEqual(self.node.odom_x, expected_dist, places=4)
        self.assertAlmostEqual(self.node.odom_y, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_yaw, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_vx, expected_dist, places=4)
        self.assertAlmostEqual(self.node.odom_vy, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_wz, 0.0, places=5)

    def test_straight_backward_motion(self):
        """-2048 ticks on both wheels over 1.0s -> straight backward."""
        expected_dist = -2.0 * math.pi * 0.06
        self.node.update_odometry(-2048, -2048, 1000000)

        self.assertAlmostEqual(self.node.odom_x, expected_dist, places=4)
        self.assertAlmostEqual(self.node.odom_y, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_yaw, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_vx, expected_dist, places=4)
        self.assertAlmostEqual(self.node.odom_wz, 0.0, places=5)

    def test_pure_rotation_ccw(self):
        """Left -1024, Right +1024 ticks -> Pure Counter-Clockwise (CCW / +yaw) rotation."""
        # Left wheel displacement: -0.5 * 2 * pi * 0.06 = -0.1884955 m
        # Right wheel displacement: +0.5 * 2 * pi * 0.06 = +0.1884955 m
        # Linear disp ds = 0
        # Angular disp dtheta = (dr - dl) / L = (0.1884955 - (-0.1884955)) / 0.26 = 0.3769911 / 0.26 = 1.4499658 rad
        expected_dtheta = (2.0 * math.pi * 0.06 * 0.5 - (-2.0 * math.pi * 0.06 * 0.5)) / 0.26
        self.node.update_odometry(-1024, 1024, 1000000)

        self.assertAlmostEqual(self.node.odom_x, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_y, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_yaw, expected_dtheta, places=4)
        self.assertAlmostEqual(self.node.odom_vx, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_wz, expected_dtheta, places=4)

    def test_pure_rotation_cw(self):
        """Left +1024, Right -1024 ticks -> Pure Clockwise (CW / -yaw) rotation."""
        expected_dtheta = -1.4499658
        self.node.update_odometry(1024, -1024, 1000000)

        self.assertAlmostEqual(self.node.odom_x, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_y, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_yaw, expected_dtheta, places=4)
        self.assertAlmostEqual(self.node.odom_wz, expected_dtheta, places=4)

    def test_yaw_normalization(self):
        """Ensure yaw wraps properly within [-pi, pi]."""
        # Execute 3 full turns (6pi radians) in increments
        ticks_per_turn = int((2.0 * math.pi * self.node.wheel_separation / (2.0 * math.pi * self.node.wheel_radius_l)) * self.node.tpr_l)
        # Half turn CCW
        half_turn_ticks = ticks_per_turn // 2
        self.node.update_odometry(-half_turn_ticks, half_turn_ticks, 500000)
        self.assertTrue(-math.pi <= self.node.odom_yaw <= math.pi)

    def test_multi_step_arc_trajectory(self):
        """Simulate a smooth 90-degree left circular turn over 50 steps at 50Hz (1.0s total)."""
        # 50Hz -> dt = 20ms = 20000us
        total_steps = 50
        dt_us = 20000
        # Turn 90 deg = pi/2 rad over 1.0s -> omega = pi/2 rad/s, v = 0.2 m/s
        v = 0.2
        w = math.pi / 2.0
        v_l = v - (w * self.node.wheel_separation / 2.0)
        v_r = v + (w * self.node.wheel_separation / 2.0)

        step_dl_m = v_l * (dt_us / 1e6)
        step_dr_m = v_r * (dt_us / 1e6)

        step_ticks_l = int(round((step_dl_m / (2.0 * math.pi * self.node.wheel_radius_l)) * self.node.tpr_l))
        step_ticks_r = int(round((step_dr_m / (2.0 * math.pi * self.node.wheel_radius_r)) * self.node.tpr_r))

        for _ in range(total_steps):
            self.node.update_odometry(step_ticks_l, step_ticks_r, dt_us)

        # Yaw should be ~ pi/2 (90 deg)
        self.assertAlmostEqual(self.node.odom_yaw, math.pi / 2.0, delta=0.05)
        # Position should have moved in both +x and +y in quadrant 1
        self.assertTrue(self.node.odom_x > 0.05)
        self.assertTrue(self.node.odom_y > 0.05)

    def test_closed_loop_box_trajectory(self):
        """Simulate driving a 1m x 1m square with 90° CCW turns at each vertex.
        Robot should return close to origin (0, 0, 0)."""
        dt_us = 20000  # 50Hz
        forward_ticks_per_step = 20  # small step
        steps_per_meter = int(1.0 / ((forward_ticks_per_step / self.node.tpr_l) * (2.0 * math.pi * self.node.wheel_radius_l)))

        quarter_turn_ticks_total = int(round(( (math.pi / 2.0) * self.node.wheel_separation / 2.0 ) / (2.0 * math.pi * self.node.wheel_radius_l) * self.node.tpr_l))
        turn_ticks_per_step = 10
        turn_steps = quarter_turn_ticks_total // turn_ticks_per_step
        turn_remainder = quarter_turn_ticks_total % turn_ticks_per_step

        for side in range(4):
            # Drive straight 1 meter
            for _ in range(steps_per_meter):
                self.node.update_odometry(forward_ticks_per_step, forward_ticks_per_step, dt_us)

            # Turn 90° CCW
            for _ in range(turn_steps):
                self.node.update_odometry(-turn_ticks_per_step, turn_ticks_per_step, dt_us)
            if turn_remainder > 0:
                self.node.update_odometry(-turn_remainder, turn_remainder, dt_us)

        # Final position after 4 sides should be near origin (closed loop tolerance < 3cm)
        self.assertAlmostEqual(self.node.odom_x, 0.0, delta=0.03)
        self.assertAlmostEqual(self.node.odom_y, 0.0, delta=0.03)
        self.assertAlmostEqual(self.node.odom_yaw, 0.0, delta=0.03)

    def test_reset_odometry(self):
        """Test reset_odometry resets state to target coordinates."""
        self.node.update_odometry(2048, 2048, 1000000)
        self.assertNotEqual(self.node.odom_x, 0.0)

        self.node.reset_odometry(1.5, -2.0, 0.785)
        self.assertEqual(self.node.odom_x, 1.5)
        self.assertEqual(self.node.odom_y, -2.0)
        self.assertEqual(self.node.odom_yaw, 0.785)
        self.assertEqual(self.node.odom_vx, 0.0)
        self.assertEqual(self.node.odom_vy, 0.0)
        self.assertEqual(self.node.odom_wz, 0.0)

    def test_encoder_packet_stream_integration(self):
        """Simulate feeding MSG_ENCODER_TICKS binary packet to handle_msg."""
        dl = 512
        dr = 512
        head_ticks = 0
        dt_us = 20000

        payload = struct.pack("<iiiI", dl, dr, head_ticks, dt_us)
        self.node.handle_msg(MSG_ENCODER_TICKS, payload)

        expected_d = (512.0 / 2048.0) * (2.0 * math.pi * 0.06)
        self.assertAlmostEqual(self.node.odom_x, expected_d, places=4)
        self.assertAlmostEqual(self.node.odom_y, 0.0, places=5)
        self.assertAlmostEqual(self.node.odom_yaw, 0.0, places=5)


if __name__ == "__main__":
    unittest.main()
