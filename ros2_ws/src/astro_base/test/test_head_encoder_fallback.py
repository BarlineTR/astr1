#!/usr/bin/env python3
"""Comprehensive Unit Tests for Head Encoder Fallback Abstraction.

Verifies the 8 mandatory test cases:
  A. valid encoder -> ENCODER
  B. stale encoder -> ESTIMATED
  C. no encoder + accepted command -> ESTIMATED
  D. no encoder + rejected command -> position unchanged
  E. no known position -> UNKNOWN (distinct from 0.0)
  F. encoder recovery -> ENCODER
  G. emergency stop -> does not trust fallback position
  H. dialogue/cognition continues working in absence of encoder
"""

import math
import unittest

from astro_base.gaze.head_state import HeadState, HeadStateManager, PositionSource
from astro_base.gaze.gaze_state_machine import SocialGazeFSM
from astro_base.gaze.gaze_runtime import GazeRuntimeCore
from astro_base.gaze.types import (
    DialogueGazeIntent,
    GazeStateEnum,
    PrioritySource,
    SafetyGazeIntent,
    TargetState,
)


class TestHeadEncoderFallback(unittest.TestCase):
    def setUp(self):
        self.mgr = HeadStateManager(
            ticks_per_deg=2.5882,
            stale_timeout_s=0.50,
            software_max_vel_deg_s=75.0,
            min_limit_deg=-90.0,
            max_limit_deg=90.0,
        )

    # -------------------------------------------------------------------------
    # Test A: valid encoder -> ENCODER
    # -------------------------------------------------------------------------
    def test_a_valid_encoder_reports_encoder_authority(self):
        """Rule 1 & 12.A: Real encoder feedback must yield ENCODER authority."""
        t0 = 100.0
        # 259 ticks / 2.5882 = 100.07 deg (clamped/rounded to 100.07)
        self.mgr.on_encoder_feedback(head_ticks=50, timestamp=t0)
        state = self.mgr.evaluate(timestamp=t0)

        expected_deg = round(50 / 2.5882, 2)  # ~19.32
        self.assertEqual(state.position_source, PositionSource.ENCODER)
        self.assertTrue(state.encoder_available)
        self.assertFalse(state.encoder_stale)
        self.assertTrue(state.encoder_valid)
        self.assertAlmostEqual(state.actual_yaw_deg, expected_deg, places=2)
        self.assertAlmostEqual(state.position_deg, expected_deg, places=2)
        self.assertAlmostEqual(state.estimated_yaw_deg, expected_deg, places=2)
        self.assertTrue(state.has_encoder_authority)
        self.assertTrue(state.has_valid_position)

    # -------------------------------------------------------------------------
    # Test B: stale encoder -> ESTIMATED
    # -------------------------------------------------------------------------
    def test_b_stale_encoder_transitions_to_estimated(self):
        """Rule 2 & 12.B: When encoder stops arriving past timeout, transition to ESTIMATED."""
        t0 = 100.0
        self.mgr.on_encoder_feedback(head_ticks=50, timestamp=t0)
        state0 = self.mgr.evaluate(timestamp=t0)
        self.assertEqual(state0.position_source, PositionSource.ENCODER)

        # Advance time past stale_timeout_s (0.50s) -> 100.60s
        t_stale = 100.60
        state_stale = self.mgr.evaluate(timestamp=t_stale)

        self.assertEqual(state_stale.position_source, PositionSource.ESTIMATED)
        self.assertTrue(state_stale.encoder_available)
        self.assertTrue(state_stale.encoder_stale)
        self.assertFalse(state_stale.encoder_valid)
        # Invariant: actual_yaw_deg and position_deg are NOT filled with estimate
        self.assertIsNone(state_stale.actual_yaw_deg)
        self.assertTrue(math.isnan(state_stale.position_deg))
        # Last known position is preserved in software estimate
        expected_deg = round(50 / 2.5882, 2)
        self.assertAlmostEqual(state_stale.estimated_yaw_deg, expected_deg, places=2)
        self.assertFalse(state_stale.has_encoder_authority)
        self.assertTrue(state_stale.has_valid_position)

    # -------------------------------------------------------------------------
    # Test C: no encoder + accepted command -> ESTIMATED
    # -------------------------------------------------------------------------
    def test_c_no_encoder_with_accepted_command_yields_estimated(self):
        """Rule 2, 10 & 12.C: Accepted command in absence of encoder produces ESTIMATED position."""
        t0 = 10.0
        # No encoder feedback given
        self.mgr.on_command_accepted(target_yaw_deg=30.0, timestamp=t0)
        # Advance time to allow software slew rate (20 deg/s) to reach target
        state = self.mgr.evaluate(timestamp=t0 + 2.0)

        self.assertEqual(state.position_source, PositionSource.ESTIMATED)
        self.assertFalse(state.encoder_available)
        self.assertTrue(state.encoder_stale)
        self.assertFalse(state.encoder_valid)
        self.assertIsNone(state.actual_yaw_deg)
        self.assertTrue(math.isnan(state.position_deg))
        self.assertIsNotNone(state.estimated_yaw_deg)
        self.assertAlmostEqual(state.estimated_yaw_deg, 30.0, places=1)

    # -------------------------------------------------------------------------
    # Test D: no encoder + rejected command -> position unchanged
    # -------------------------------------------------------------------------
    def test_d_no_encoder_with_rejected_command_leaves_position_unchanged(self):
        """Rule 10 & 12.D: Unaccepted/rejected command must NEVER produce estimated movement."""
        t0 = 10.0
        self.mgr.on_command_rejected(target_yaw_deg=45.0, reason="serial port closed")
        state = self.mgr.evaluate(timestamp=t0)

        self.assertEqual(state.position_source, PositionSource.UNKNOWN)
        self.assertIsNone(state.actual_yaw_deg)
        self.assertIsNone(state.estimated_yaw_deg)
        self.assertTrue(math.isnan(state.position_deg))
        self.assertFalse(state.has_valid_position)

    # -------------------------------------------------------------------------
    # Test E: no known position -> UNKNOWN
    # -------------------------------------------------------------------------
    def test_e_no_known_position_is_unknown_not_assumed_zero(self):
        """Rule 3 & 12.E: When no encoder and no command exists, state is UNKNOWN, not 0.0."""
        state = self.mgr.evaluate(timestamp=1.0)

        self.assertEqual(state.position_source, PositionSource.UNKNOWN)
        self.assertIsNone(state.actual_yaw_deg)
        self.assertIsNone(state.estimated_yaw_deg)
        self.assertTrue(math.isnan(state.position_deg))
        self.assertFalse(state.has_valid_position)
        self.assertFalse(state.has_encoder_authority)

    # -------------------------------------------------------------------------
    # Test F: encoder recovery -> ENCODER
    # -------------------------------------------------------------------------
    def test_f_encoder_recovery_restores_encoder_authority(self):
        """Rule 5 & 12.F: When encoder feedback resumes, authority immediately returns to ENCODER."""
        t = 10.0
        # 1. Start with accepted command -> ESTIMATED
        self.mgr.on_command_accepted(target_yaw_deg=40.0, timestamp=t)
        # Advance time in discrete steps to allow software slew rate (20 deg/s) to reach target
        for _ in range(25):
            t += 0.1
            state_est = self.mgr.evaluate(timestamp=t)
        self.assertEqual(state_est.position_source, PositionSource.ESTIMATED)
        self.assertAlmostEqual(state_est.estimated_yaw_deg, 40.0, places=1)

        # 2. Hardware encoder recovers and produces ticks
        t += 0.10
        self.mgr.on_encoder_feedback(head_ticks=100, timestamp=t)
        state_rec = self.mgr.evaluate(timestamp=t)

        expected_deg = round(100 / 2.5882, 2)  # ~38.64
        self.assertEqual(state_rec.position_source, PositionSource.ENCODER)
        self.assertTrue(state_rec.encoder_available)
        self.assertFalse(state_rec.encoder_stale)
        self.assertTrue(state_rec.encoder_valid)
        self.assertAlmostEqual(state_rec.actual_yaw_deg, expected_deg, places=2)
        self.assertAlmostEqual(state_rec.estimated_yaw_deg, expected_deg, places=2)
        self.assertAlmostEqual(state_rec.position_deg, expected_deg, places=2)

    # -------------------------------------------------------------------------
    # Test G: emergency stop -> fallback position not trusted
    # -------------------------------------------------------------------------
    def test_g_emergency_stop_does_not_trust_fallback_position(self):
        """Rule 7 & 12.G: Emergency stop must NOT trust ESTIMATED position for safety gates."""
        # 1. In ESTIMATED mode:
        self.mgr.on_command_accepted(target_yaw_deg=45.0, timestamp=10.0)
        state = self.mgr.evaluate(timestamp=10.0)
        self.assertEqual(state.position_source, PositionSource.ESTIMATED)

        # A safety verifier checks if hardware encoder authority is present
        self.assertFalse(state.has_encoder_authority)
        self.assertTrue(math.isnan(state.position_deg))

        # SocialGazeFSM emergency stop behavior
        fsm = SocialGazeFSM()
        fsm.set_safety_lock(True)
        self.assertTrue(fsm.safety_lock)

        # When safety locked, FSM transitions to IDLE with EMERGENCY_STOP priority
        cmd = fsm.update(
            target_state=TargetState(active_target=None),
            actual_head_yaw_deg=0.0,
            timestamp=10.0,
            safety_intent=SafetyGazeIntent(is_locked=True, timestamp=10.0),
        )
        self.assertEqual(cmd.priority_source, PrioritySource.EMERGENCY_STOP)
        self.assertEqual(cmd.gaze_state, GazeStateEnum.IDLE)
        self.assertEqual(cmd.target_yaw_deg, 0.0)

    # -------------------------------------------------------------------------
    # Test H: dialogue/cognition continues working in absence of encoder
    # -------------------------------------------------------------------------
    def test_h_dialogue_and_cognition_continue_without_encoder(self):
        """Rule 6, 8 & 12.H: Dialogue and cognition must not break when encoder is absent."""
        runtime = GazeRuntimeCore()

        # In absence of encoder, update estimated feedback
        t = 50.0
        runtime.update_estimated_feedback(estimated_deg=25.0, velocity_deg_s=0.0, timestamp=t)
        self.assertEqual(runtime.position_source, PositionSource.ESTIMATED)
        self.assertTrue(runtime.is_position_known)
        self.assertFalse(runtime.has_head_feedback)
        # Tracker uses estimated angle for spatial transforms
        self.assertAlmostEqual(runtime.tracker.head_angle_deg, 25.0, places=1)

        # Set dialogue intent (e.g., looking at user during conversation)
        runtime.tracker.fsm.set_dialogue_target(yaw_deg=15.0, duration_s=2.0, timestamp=t)

        # Step FSM with active dialogue intent
        cmd = runtime.tracker.fsm.update(
            target_state=TargetState(active_target=None),
            actual_head_yaw_deg=runtime.tracker.head_angle_deg,
            timestamp=t,
            dialogue_intent=DialogueGazeIntent(target_yaw_deg=15.0, timestamp=t, expiry_time=t + 2.0),
        )

        # Dialogue intent must be accepted and steer head towards 15.0°
        self.assertEqual(cmd.priority_source, PrioritySource.DIRECT_DIALOGUE_INTENT)
        self.assertAlmostEqual(cmd.target_yaw_deg, 15.0, places=1)

    # -------------------------------------------------------------------------
    # Test I: Continuous zero ticks at startup never produces fake actual_yaw
    # -------------------------------------------------------------------------
    def test_i_continuous_zero_ticks_never_produces_fake_actual_yaw(self):
        """0 tick alone must NEVER be blindly accepted as physical 0.0° position."""
        t = 1.0
        for _ in range(10):
            self.mgr.on_encoder_feedback(head_ticks=0, timestamp=t)
            t += 0.02
        state = self.mgr.evaluate(timestamp=t)

        self.assertEqual(state.position_source, PositionSource.UNKNOWN)
        self.assertIsNone(state.actual_yaw_deg)
        self.assertIsNone(state.estimated_yaw_deg)
        self.assertTrue(math.isnan(state.position_deg))
        self.assertFalse(state.has_encoder_authority)
        self.assertFalse(state.encoder_available)

    # -------------------------------------------------------------------------
    # Test J: Stuck-at-zero with active command transitions to ESTIMATED
    # -------------------------------------------------------------------------
    def test_j_stuck_at_zero_with_command_transitions_to_estimated(self):
        """When commanded to move and head_ticks stays 0, position_source must be ESTIMATED with actual_yaw_deg=None."""
        t = 1.0
        # Command head to 30.0 deg
        self.mgr.on_command_accepted(target_yaw_deg=30.0, timestamp=t)

        # head_ticks continues to arrive as 0 for > 0.5s
        for _ in range(35):
            t += 0.02
            self.mgr.on_encoder_feedback(head_ticks=0, timestamp=t)

        state = self.mgr.evaluate(timestamp=t)
        self.assertEqual(state.position_source, PositionSource.ESTIMATED)
        self.assertIsNone(state.actual_yaw_deg)
        self.assertTrue(math.isnan(state.position_deg))
        self.assertIsNotNone(state.estimated_yaw_deg)
        self.assertAlmostEqual(state.estimated_yaw_deg, 30.0, places=1)
        self.assertFalse(state.encoder_available)
        self.assertTrue(state.encoder_stale)
        self.assertFalse(state.has_encoder_authority)

    # -------------------------------------------------------------------------
    # Test K: Dynamic tick change activates encoder authority
    # -------------------------------------------------------------------------
    def test_k_dynamic_ticks_change_activates_encoder_authority(self):
        """When head_ticks actually changes dynamically, encoder responsiveness is confirmed."""
        t = 1.0
        self.mgr.on_encoder_feedback(head_ticks=0, timestamp=t)
        self.assertFalse(self.mgr.encoder_responsive)

        # Ticks actually change (e.g. motor turned or head moved by hand)
        t += 0.05
        self.mgr.on_encoder_feedback(head_ticks=25, timestamp=t)
        self.assertTrue(self.mgr.encoder_responsive)

        state = self.mgr.evaluate(timestamp=t)
        self.assertEqual(state.position_source, PositionSource.ENCODER)
        self.assertIsNotNone(state.actual_yaw_deg)
        self.assertAlmostEqual(state.actual_yaw_deg, round(25 / 2.5882, 2), places=2)
        self.assertTrue(state.has_encoder_authority)

    # -------------------------------------------------------------------------
    # Test L: Wheel ticks active while head_ticks=0 confirms stuck encoder
    # -------------------------------------------------------------------------
    def test_l_wheel_ticks_active_while_head_ticks_zero_confirms_stuck(self):
        """When wheel encoders are streaming deltas but head_ticks is 0, head encoder is stuck."""
        t = 1.0
        self.mgr.on_command_accepted(target_yaw_deg=-45.0, timestamp=t)

        # Wheels are rolling, head commanded, but head_ticks remains 0
        for _ in range(30):
            t += 0.02
            self.mgr.on_encoder_feedback(head_ticks=0, timestamp=t, wheel_ticks_l=10, wheel_ticks_r=10)

        state = self.mgr.evaluate(timestamp=t)
        self.assertEqual(state.position_source, PositionSource.ESTIMATED)
        self.assertIsNone(state.actual_yaw_deg)
        self.assertTrue(math.isnan(state.position_deg))
        self.assertFalse(state.encoder_available)


if __name__ == "__main__":
    unittest.main()

