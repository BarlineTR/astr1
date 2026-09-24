#!/usr/bin/env python3
"""Validation suite for Absolute Target / Relative Correction architectural invariants.

Tests the 8 critical fallback scenarios:
1. Stationary target + ENCODER=UNKNOWN (+15° optical bearing across 100 frames) -> zero runaway.
2. Negative direction (-20° optical bearing across 100 frames) -> zero runaway.
3. Actuator saturation clamp (±75° limit enforced strictly at actuator adapter).
4. Body alignment invariant (desired_body_yaw_deg = 0.0 in UNKNOWN mode).
5. Audio -> Visual handoff (vision takes immediate priority over audio sector).
6. Visual -> Audio reacquisition (grace period protects brief visual dropouts before audio reacquires).
7. Dynamic UNKNOWN -> ENCODER transition (seamless switch to absolute spatial target).
8. Physical position invariant (actual_head_yaw_deg is None and position_source is UNKNOWN).
"""

import sys
import unittest
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core_path  # noqa: F401
from astro_base.gaze.head_state import HeadStateManager, PositionSource, UnknownModeActuatorAdapter
from astro_base.gaze.respeaker_localizer import ReSpeakerAudioLocalizer
from astro_base.gaze.types import GazeStateEnum, PrioritySource
from tracker import Detection, GazeResult, GazeTracker

FRAME = (640, 480)


def _face_at_bearing(bearing_deg: float, confidence: float = 0.92) -> Detection:
    """Generates a face detection whose optical angle equals bearing_deg."""
    w = h = 90
    # In CoordinateTransformer: cam_azimuth = -norm_u * 36.0
    # norm_u = (cx - 320) / 320  =>  cx = 320 - (bearing_deg / 36.0) * 320
    norm_u = -bearing_deg / 36.0
    cx = 320.0 + norm_u * 320.0
    return Detection(x=int(cx - w / 2), y=195, w=w, h=h, confidence=confidence)


class TestRelativeCorrectionInvariants(unittest.TestCase):
    """Verifies that ENCODER=UNKNOWN fallback treats camera bearing as relative correction."""

    def setUp(self):
        self.tracker = GazeTracker()
        self.adapter = UnknownModeActuatorAdapter(min_limit_deg=-75.0, max_limit_deg=75.0)

    def test_scenario_1_stationary_target_unknown_encoder_no_runaway(self):
        """Scenario 1: Stationary target at +15° optical bearing across 100 frames with ENCODER=UNKNOWN.
        Verifies command stays at +15° and does NOT accumulate / runaway to +75°.
        """
        commands: List[float] = []
        target_yaws: List[float] = []
        face = _face_at_bearing(15.0)

        for i in range(100):
            t = 100.0 + i * 0.033  # ~30 fps
            res = self.tracker.step(
                faces=[face],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=None,  # ENCODER is UNKNOWN
                timestamp=t,
            )
            cmd = self.adapter.adapt(
                target_yaw_deg=res.target_yaw_deg,
                relative_head_correction_deg=res.relative_head_correction_deg,
                is_relative_correction=res.is_relative_correction,
                has_encoder=False,
            )
            commands.append(cmd)
            target_yaws.append(res.target_yaw_deg)

            self.assertIsNone(res.actual_head_yaw_deg)
            self.assertEqual(res.position_source, "UNKNOWN")
            self.assertTrue(res.is_relative_correction)

        # Commands must stay at +15° (within optical rounding tolerance ±0.5°)
        # And must NEVER exhibit integrator runaway (e.g. climbing towards 75°)
        self.assertAlmostEqual(commands[0], 15.0, delta=0.5)
        self.assertAlmostEqual(commands[99], 15.0, delta=0.5)
        self.assertLessEqual(max(commands), 16.0, "Runaway detected! Command exceeded target angle.")
        self.assertGreaterEqual(min(commands), 14.0)

    def test_scenario_2_negative_direction_no_runaway(self):
        """Scenario 2: Negative direction (-20° optical bearing across 100 frames) with ENCODER=UNKNOWN.
        Verifies command stays at -20° with zero runaway in the negative direction.
        """
        commands: List[float] = []
        face = _face_at_bearing(-20.0)

        for i in range(100):
            t = 200.0 + i * 0.033
            res = self.tracker.step(
                faces=[face],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=None,
                timestamp=t,
            )
            cmd = self.adapter.adapt(
                target_yaw_deg=res.target_yaw_deg,
                relative_head_correction_deg=res.relative_head_correction_deg,
                is_relative_correction=res.is_relative_correction,
                has_encoder=False,
            )
            commands.append(cmd)

        self.assertAlmostEqual(commands[0], -20.0, delta=0.5)
        self.assertAlmostEqual(commands[99], -20.0, delta=0.5)
        self.assertGreaterEqual(min(commands), -21.0, "Negative runaway detected!")
        self.assertLessEqual(max(commands), -19.0)

    def test_scenario_3_actuator_saturation_clamp(self):
        """Scenario 3: Actuator saturation clamp at ±75° is enforced by actuator adapter."""
        # Test extreme positive target
        cmd_pos = self.adapter.adapt(
            target_yaw_deg=85.0,
            relative_head_correction_deg=85.0,
            is_relative_correction=True,
            has_encoder=False,
        )
        self.assertEqual(cmd_pos, 75.0, "Actuator adapter must clamp positive angles to +75.0°")

        # Test extreme negative target
        cmd_neg = self.adapter.adapt(
            target_yaw_deg=-90.0,
            relative_head_correction_deg=-90.0,
            is_relative_correction=True,
            has_encoder=False,
        )
        self.assertEqual(cmd_neg, -75.0, "Actuator adapter must clamp negative angles to -75.0°")

    def test_scenario_4_body_alignment_disabled_in_unknown_mode(self):
        """Scenario 4: Body alignment is disabled (desired_body_yaw_deg = 0.0) when ENCODER=UNKNOWN."""
        face = _face_at_bearing(25.0)
        res = self.tracker.step(
            faces=[face],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=None,
            timestamp=300.0,
        )
        self.assertEqual(res.desired_body_yaw_deg, 0.0,
                         "desired_body_yaw_deg must be 0.0 when physical head orientation is UNKNOWN")

    def test_scenario_5_audio_to_visual_handoff(self):
        """Scenario 5: Audio -> Visual handoff.
        Audio localizer commands sector (+35°). Once visual face is detected (+10°),
        vision takes primacy, command transitions to +10°, and audio releases.
        """
        localizer = ReSpeakerAudioLocalizer()
        # 1. Audio active on LEFT sector (+35°)
        localizer.update(doa_raw=32.0, voice_activity=True, timestamp=400.0)
        self.assertTrue(localizer.is_tracking(now=400.0))
        audio_target = localizer.target_yaw_deg
        self.assertEqual(audio_target, 35.0)

        # 2. Frame arrives with face at +10°
        face = _face_at_bearing(10.0)
        res = self.tracker.step(
            faces=[face],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=None,
            timestamp=400.05,
        )

        # Vision primacy: visual tracking active
        vision_active = (
            res.owner == PrioritySource.VISUAL_TRACKING
            or res.gaze_state in (
                GazeStateEnum.TRACKING,
                GazeStateEnum.HOLDING_ATTENTION,
                GazeStateEnum.ORIENTING,
                GazeStateEnum.ACQUIRING,
                GazeStateEnum.TARGET_LOST,
            )
        )
        self.assertTrue(vision_active)
        localizer.on_vision_active()

        cmd = self.adapter.adapt(
            target_yaw_deg=res.target_yaw_deg,
            relative_head_correction_deg=res.relative_head_correction_deg,
            is_relative_correction=res.is_relative_correction,
            has_encoder=False,
        )
        self.assertAlmostEqual(cmd, 10.0, delta=0.5)

    def test_scenario_6_visual_to_audio_reacquisition_grace(self):
        """Scenario 6: Visual -> Audio reacquisition with grace period protection."""
        localizer = ReSpeakerAudioLocalizer(hold_timeout_s=1.0)
        face = _face_at_bearing(0.0)

        # 1. Establish confirmed visual attention
        for i in range(5):
            res = self.tracker.step(
                faces=[face],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=None,
                timestamp=500.0 + i * 0.033,
            )
        self.assertEqual(res.owner, PrioritySource.VISUAL_TRACKING)
        self.assertEqual(res.gaze_state, GazeStateEnum.HOLDING_ATTENTION)

        # 2. Face temporarily lost (empty frames)
        res_lost = self.tracker.step(
            faces=[],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=None,
            timestamp=500.20,
        )
        # Should be in grace state (HOLDING_ATTENTION / TARGET_LOST)
        self.assertIn(res_lost.gaze_state, (GazeStateEnum.HOLDING_ATTENTION, GazeStateEnum.TARGET_LOST))

        # 3. Simulate passage of time past attention dwell & target lost timeout -> RECOVERING / IDLE
        for i in range(120):
            res_idle = self.tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=None,
                timestamp=500.25 + i * 0.033,
            )

        # Once grace expires and robot returns to IDLE, audio can reacquire cleanly
        if res_idle.gaze_state in (GazeStateEnum.IDLE, GazeStateEnum.RECOVERING):
            localizer.update(doa_raw=142.0, voice_activity=True, timestamp=505.0)
            self.assertTrue(localizer.is_tracking(now=505.0))
            self.assertEqual(localizer.target_yaw_deg, -35.0)

    def test_scenario_7_dynamic_unknown_to_encoder_handoff(self):
        """Scenario 7: Dynamic UNKNOWN -> ENCODER transition.
        Starts with UNKNOWN encoder (relative correction mode).
        When real hardware feedback arrives, switches smoothly to absolute spatial target.
        """
        face = _face_at_bearing(10.0)

        # Step 1: UNKNOWN mode
        res1 = self.tracker.step(
            faces=[face],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=None,
            timestamp=600.0,
        )
        self.assertTrue(res1.is_relative_correction)
        self.assertEqual(res1.position_source, "UNKNOWN")
        self.assertIsNone(res1.actual_head_yaw_deg)

        cmd1 = self.adapter.adapt(
            target_yaw_deg=res1.target_yaw_deg,
            relative_head_correction_deg=res1.relative_head_correction_deg,
            is_relative_correction=res1.is_relative_correction,
            has_encoder=False,
        )
        self.assertAlmostEqual(cmd1, 10.0, delta=0.5)

        # Step 2: Encoder begins reporting measured head at 20.0°
        # Immediate state transition check on first encoder frame
        res2_first = self.tracker.step(
            faces=[face],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=20.0,
            timestamp=600.033,
        )
        self.assertFalse(res2_first.is_relative_correction)
        self.assertEqual(res2_first.position_source, "ENCODER")
        self.assertEqual(res2_first.actual_head_yaw_deg, 20.0)

        # Allow 3D Kalman filter to settle across a few frames to absolute spatial target (~29.0° body frame)
        res2_settled = res2_first
        for i in range(2, 15):
            res2_settled = self.tracker.step(
                faces=[face],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=20.0,
                timestamp=600.0 + i * 0.033,
            )

        cmd2 = self.adapter.adapt(
            target_yaw_deg=res2_settled.target_yaw_deg,
            relative_head_correction_deg=res2_settled.relative_head_correction_deg,
            is_relative_correction=res2_settled.is_relative_correction,
            has_encoder=True,
        )
        self.assertAlmostEqual(cmd2, 29.0, delta=1.0)


    def test_scenario_8_physical_position_invariant(self):
        """Scenario 8: Physical position invariant.
        When ENCODER is UNKNOWN, actual_head_yaw_deg is None and position_source is UNKNOWN.
        Software estimates must NEVER be reported as physical feedback.
        """
        tracker = GazeTracker()
        res = tracker.step(
            faces=[_face_at_bearing(5.0)],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=None,
            timestamp=700.0,
        )
        self.assertIsNone(res.actual_head_yaw_deg)
        self.assertIsNone(res.head_angle_deg)
        self.assertEqual(res.position_source, "UNKNOWN")
        self.assertTrue(tracker.head_feedback_missing)

    def test_scenario_9_single_tick_noise_rejected_as_unknown(self):
        """Scenario 9: Single-tick noise rejection (stuck at 0 or 1).
        With ticks_per_deg=0.288, 1 tick produces 3.47 deg.
        Verify that raw ticks=1 at boot or noise does NOT claim ENCODER authority!
        """
        mgr = HeadStateManager(ticks_per_deg=0.288, stale_timeout_s=0.50)
        # Packet with 1 tick arrives
        mgr.on_encoder_feedback(head_ticks=1, timestamp=10.0)
        state = mgr.evaluate(timestamp=10.0)

        self.assertEqual(state.position_source, PositionSource.UNKNOWN)
        self.assertIsNone(state.actual_yaw_deg)
        self.assertFalse(state.encoder_available)
        self.assertFalse(state.has_encoder_authority)

    def test_scenario_10_target_lost_safely_terminates_unknown_actuator_command(self):
        """Scenario 10: TARGET_LOST command termination.
        When visual target is lost in UNKNOWN mode, relative_head_correction_deg is None.
        UnknownModeActuatorAdapter must output 0.0, NOT hold a stale setpoint (e.g. 11.1 deg).
        """
        adapter = UnknownModeActuatorAdapter(min_limit_deg=-75.0, max_limit_deg=75.0)

        # Active visual tracking with 11.1 deg correction
        cmd_active = adapter.adapt(
            target_yaw_deg=11.1,
            relative_head_correction_deg=11.1,
            is_relative_correction=True,
            has_encoder=False,
        )
        self.assertEqual(cmd_active, 11.1)

        # Target lost: relative_head_correction_deg is None
        cmd_lost = adapter.adapt(
            target_yaw_deg=11.1,  # stale target from previous frame
            relative_head_correction_deg=None,
            is_relative_correction=True,
            has_encoder=False,
        )
        self.assertEqual(cmd_lost, 0.0)  # Must be safely terminated to 0.0!


if __name__ == "__main__":
    unittest.main()

