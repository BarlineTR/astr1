#!/usr/bin/env python3
"""Regression tests for Head Feedback Parity, Freshness, and Authoritative Pipeline.

Validates:
1. Commanded -20°, head moves dynamically (+17, +10, +5, 0, -5, -10, -15, -20);
   feedback freshness tracked and fails if feedback freezes for > 100ms.
2. /head/state is the sole authoritative source of head feedback; /joint_states is
   strictly diagnostic and cannot clobber authoritative feedback.
3. Feedback freshness metadata: head_feedback_deg, head_feedback_age_ms, head_feedback_source.
4. Visual coast anomaly fix: when bbox == NONE, visual_bearing is NONE while target yaw coasts.
5. SAFETY_ZERO behavior: on target loss (target_id == NONE, source == SAFETY_ZERO),
   target_yaw = current_actual_head (not snapped to 0.0°).
"""

import math
import time
import unittest

from astro_base.gaze.gaze_runtime import GazeRuntimeCore
from astro_base.gaze.gaze_tracker import Detection, GazeResult, GazeTracker
from astro_base.social_gaze_node import SocialGazeNode
from astro_base.standalone_gaze_node import StandaloneGazeNode


class _MockHeadState:
    def __init__(self, position_deg: float, velocity_deg_s: float = 0.0):
        self.position_deg = float(position_deg)
        self.velocity_deg_s = float(velocity_deg_s)


class _MockJointState:
    def __init__(self, name: list, position: list, velocity: list = None):
        self.name = list(name)
        self.position = list(position)
        self.velocity = list(velocity) if velocity is not None else [0.0] * len(position)


class TestHeadFeedbackFreshnessAndAuthority(unittest.TestCase):
    """Verifies feedback freshness, sole authority of /head/state, and parity invariants."""

    def test_dynamic_head_tracking_with_feedback_freshness(self):
        """Dynamic sequence: command -20°, head moves [+17, +10, +5, 0, -5, -10, -15, -20].

        Feedback age must remain < 30ms throughout, source must be /head/state.
        """
        runtime = GazeRuntimeCore(coast_timeout_s=1.0)
        trajectory_steps = [+17.0, +10.0, +5.0, 0.0, -5.0, -10.0, -15.0, -20.0]

        t_sim = 1000.0
        dt = 0.020  # 50Hz

        # Detection centered around -20° in camera coordinates
        # Camera width=640, center is 320. Azimuth ~ (x - 320) * fov_scale
        det = [Detection(x=100, y=200, w=80, h=80, confidence=0.88, detector_source="oak")]

        for pos in trajectory_steps:
            # Authoritative feedback from /head/state arrives
            runtime.update_head_feedback(angle_deg=pos, velocity_deg_s=-50.0, timestamp=t_sim, source="/head/state")

            self.assertTrue(runtime.is_feedback_fresh(max_age_ms=100.0, now=t_sim))
            fb_deg, fb_age, fb_src = runtime.get_feedback_telemetry(now=t_sim)
            self.assertAlmostEqual(fb_deg, pos, places=1)
            self.assertLess(fb_age, 30.0)
            self.assertEqual(fb_src, "/head/state")

            res = runtime.step(
                faces=det,
                frame_size=(640, 480),
                timestamp=t_sim,
            )

            self.assertAlmostEqual(res.head_feedback_deg, pos, places=1)
            self.assertLess(res.head_feedback_age_ms, 30.0)
            self.assertEqual(res.head_feedback_source, "/head/state")

            t_sim += dt

    def test_feedback_freeze_fails_freshness_after_100ms(self):
        """If feedback freezes for > 100ms, freshness check must fail and report staleness."""
        runtime = GazeRuntimeCore(coast_timeout_s=1.0)
        t_feed = 1000.0
        runtime.update_head_feedback(angle_deg=+17.0, velocity_deg_s=0.0, timestamp=t_feed, source="/head/state")

        # 50ms later: still fresh
        t_check_fresh = t_feed + 0.050
        self.assertTrue(runtime.is_feedback_fresh(max_age_ms=100.0, now=t_check_fresh))
        _, age_50, _ = runtime.get_feedback_telemetry(now=t_check_fresh)
        self.assertAlmostEqual(age_50, 50.0, places=1)

        # 120ms later without feedback: MUST FAIL freshness (> 100ms)
        t_check_stale = t_feed + 0.120
        self.assertFalse(runtime.is_feedback_fresh(max_age_ms=100.0, now=t_check_stale))
        _, age_120, src = runtime.get_feedback_telemetry(now=t_check_stale)
        self.assertGreaterEqual(age_120, 100.0)
        self.assertEqual(src, "/head/state")

        # Step at stale time reflects age in GazeResult
        res = runtime.step(faces=[], frame_size=(640, 480), timestamp=t_check_stale)
        self.assertGreaterEqual(res.head_feedback_age_ms, 100.0)

    def test_head_state_is_sole_authority_ignoring_stale_joint_states_in_standalone_node(self):
        """In StandaloneGazeNode, /head/state is authoritative; conflicting /joint_states is ignored."""
        node = StandaloneGazeNode()

        # Send authoritative /head/state
        node._on_head_state(_MockHeadState(position_deg=+17.0, velocity_deg_s=0.0))
        self.assertAlmostEqual(node.runtime.actual_head_yaw_deg, 17.0, places=2)
        self.assertEqual(node.runtime.head_feedback_source, "/head/state")

        # Now send conflicting /joint_states (-45.0 deg)
        rad_val = math.radians(-45.0)
        node._on_joint_states(_MockJointState(name=["head_yaw_joint"], position=[rad_val]))

        # Authoritative runtime must NOT have been changed by /joint_states
        self.assertAlmostEqual(node.runtime.actual_head_yaw_deg, 17.0, places=2)
        self.assertEqual(node.runtime.head_feedback_source, "/head/state")
        # Diagnostic joint yaw recorded separately
        self.assertAlmostEqual(node.diagnostic_joint_yaw_deg, -45.0, places=2)

    def test_head_state_is_sole_authority_ignoring_stale_joint_states_in_social_node(self):
        """In SocialGazeNode, /head/state is authoritative; conflicting /joint_states is ignored."""
        node = SocialGazeNode()

        # Send authoritative /head/state
        node._on_head_state(_MockHeadState(position_deg=+17.0, velocity_deg_s=0.0))
        self.assertAlmostEqual(node.actual_head_yaw_deg, 17.0, places=2)
        self.assertAlmostEqual(node.runtime.actual_head_yaw_deg, 17.0, places=2)
        self.assertEqual(node.runtime.head_feedback_source, "/head/state")

        # Send conflicting /joint_states (+50.0 deg)
        rad_val = math.radians(50.0)
        node._on_joint_states(_MockJointState(name=["head_yaw_joint"], position=[rad_val]))

        # Authoritative runtime and actual_head_yaw_deg must remain +17.0
        self.assertAlmostEqual(node.actual_head_yaw_deg, 17.0, places=2)
        self.assertAlmostEqual(node.runtime.actual_head_yaw_deg, 17.0, places=2)
        self.assertEqual(node.runtime.head_feedback_source, "/head/state")
        self.assertAlmostEqual(node.diagnostic_joint_yaw_deg, 50.0, places=2)

    def test_visual_coast_anomaly_bbox_none_yields_bearing_none(self):
        """When bbox == NONE, visual_bearing must be NONE while target continues coasting."""
        runtime = GazeRuntimeCore(coast_timeout_s=1.0)
        t = 100.0

        # Frame 1: Valid face detection
        det = [Detection(x=200, y=150, w=100, h=100, confidence=0.90, detector_source="oak")]
        runtime.update_head_feedback(angle_deg=0.0, timestamp=t, source="/head/state")
        res1 = runtime.step(faces=det, frame_size=(640, 480), timestamp=t)

        self.assertEqual(res1.command_source, "VISUAL")
        self.assertGreater(len(res1.face_bearings_deg), 0)
        face_bearing_1 = res1.face_bearings_deg[0]
        self.assertIsNotNone(face_bearing_1)
        coasted_target_yaw = res1.target_yaw_deg

        # Frame 2: Face dropout / bbox == NONE (faces=[])
        t += 0.033
        res2 = runtime.step(faces=[], frame_size=(640, 480), timestamp=t)

        # Coast is active, holding last target yaw
        self.assertEqual(res2.command_source, "VISUAL_COAST")
        self.assertAlmostEqual(res2.target_yaw_deg, coasted_target_yaw, places=2)

        # CRITICAL FIX: face_bearings_deg is EMPTY when bbox == NONE
        self.assertEqual(len(res2.face_bearings_deg), 0)
        face_bearing_2 = res2.face_bearings_deg[0] if res2.face_bearings_deg else None
        face_bearing_str = f"{face_bearing_2:+.1f}°" if face_bearing_2 is not None else "NONE"
        self.assertEqual(face_bearing_str, "NONE")

    def test_safety_zero_holds_current_actual_head_on_target_loss(self):
        """When target is lost (SAFETY_ZERO), target_yaw must hold current actual_head position.

        Must NOT snap back to 0.0°.
        """
        runtime = GazeRuntimeCore(coast_timeout_s=0.5)
        t = 200.0

        # Robot head physically turned to -18.5°
        current_actual_head = -18.5
        runtime.update_head_feedback(angle_deg=current_actual_head, timestamp=t, source="/head/state")

        # Step with no detections past the coast timeout
        res = runtime.step(faces=[], frame_size=(640, 480), timestamp=t)
        self.assertEqual(res.command_source, "SAFETY_ZERO")
        self.assertIn(res.target_id, (None, "NONE"))

        # Target yaw MUST equal current actual head position
        self.assertAlmostEqual(res.target_yaw_deg, current_actual_head, places=2)


if __name__ == "__main__":
    unittest.main()
