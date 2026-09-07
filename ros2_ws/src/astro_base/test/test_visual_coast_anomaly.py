"""Regression tests for Visual Coast Anomaly and Zero-Coast Invariant.

Verifies:
  1. Valid detection CANNOT enter VISUAL_COAST.
  2. Active target detection produces VISUAL command.
  3. Visual detection dynamically updates target yaw.
  4. Visual detection never uses stale coast yaw.
  5. Same track ID implies visual lock.
  6. Detection and active track identity match.
  7. Cycle 183-189 stale yaw spike (+43.1° -> +66.8°) regression prevention.
  8. Current detection bearing matches head command target yaw.
  9. Dropout uses coast yaw; fresh vision immediately uses fresh bearing.
  10. Consistency between visual bearing and target yaw across angles.
"""

import math
import os
import sys
import unittest
from typing import List

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)

from astro_base.gaze.angle_math import angular_diff_deg
from astro_base.gaze.coordinate_frames import CalibrationConfig
from astro_base.gaze.gaze_runtime import GazeRuntimeCore
from astro_base.gaze.gaze_tracker import Detection, GazeResult, GazeTracker
from astro_base.gaze.types import TrackingState


class TestVisualCoastAnomalyRegression(unittest.TestCase):
    """10 Critical Regression Tests for Zero-Coast Visual Invariant."""

    def setUp(self):
        self.calib = CalibrationConfig()
        self.tracker = GazeTracker(calibration=self.calib, coast_timeout_s=1.0)
        self.runtime = GazeRuntimeCore(calibration=self.calib, coast_timeout_s=1.0)

    # 1. test_valid_detection_cannot_enter_visual_coast
    def test_valid_detection_cannot_enter_visual_coast(self):
        """Valid detection (confidence >= 0.50) MUST NEVER produce command_source == 'VISUAL_COAST'."""
        det = Detection(x=320, y=240, w=80, h=80, confidence=0.86)
        res = self.tracker.step(
            faces=[det],
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=0.0,
            timestamp=10.0,
        )
        self.assertNotEqual(res.command_source, "VISUAL_COAST")
        self.assertEqual(res.command_source, "VISUAL")
        self.assertEqual(res.target_source, "CAMERA")

    # 2. test_active_target_detection_produces_visual_command
    def test_active_target_detection_produces_visual_command(self):
        """When an active target is tracked, incoming detection MUST produce command_source == 'VISUAL'."""
        t = 10.0
        for _ in range(5):
            det = Detection(x=320, y=240, w=80, h=80, confidence=0.86)
            res = self.tracker.step(
                faces=[det],
                frame_size=(640, 480),
                doa_deg=None,
                measured_head_deg=0.0,
                timestamp=t,
            )
            t += 0.033

        self.assertIsNotNone(res.target_id)
        self.assertEqual(res.command_source, "VISUAL")
        self.assertEqual(res.target_source, "CAMERA")

    # 3. test_visual_detection_updates_target_yaw
    def test_visual_detection_updates_target_yaw(self):
        """Sequential visual detections at changing angles MUST update target_yaw_deg dynamically."""
        t = 20.0
        # Start at centre
        det1 = Detection(x=320, y=240, w=80, h=80, confidence=0.85)
        res1 = self.tracker.step(
            faces=[det1],
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=0.0,
            timestamp=t,
        )
        yaw1 = res1.target_yaw_deg

        # Move to the right (x=450)
        t += 0.033
        det2 = Detection(x=450, y=240, w=80, h=80, confidence=0.85)
        res2 = self.tracker.step(
            faces=[det2],
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=0.0,
            timestamp=t,
        )
        yaw2 = res2.target_yaw_deg

        self.assertNotAlmostEqual(yaw1, yaw2, delta=1.0)
        self.assertLess(yaw2, yaw1, "Moving face to the right of image should decrease yaw (turn right)")

    # 4. test_visual_detection_does_not_use_stale_coast_yaw
    def test_visual_detection_does_not_use_stale_coast_yaw(self):
        """Fresh visual detection MUST NOT use stale coast yaw from earlier position."""
        t = 30.0
        # Prime at x=200
        for _ in range(5):
            det = Detection(x=200, y=240, w=80, h=80, confidence=0.85)
            res_prime = self.tracker.step([det], (640, 480), None, 0.0, t)
            t += 0.033

        old_yaw = res_prime.target_yaw_deg

        # New detection at x=500
        det_new = Detection(x=500, y=240, w=80, h=80, confidence=0.85)
        res_fresh = self.tracker.step([det_new], (640, 480), None, 0.0, t)

        self.assertNotAlmostEqual(res_fresh.target_yaw_deg, old_yaw, delta=2.0)
        self.assertEqual(res_fresh.command_source, "VISUAL")

    # 5. test_same_track_id_means_visual_lock
    def test_same_track_id_means_visual_lock(self):
        """When the active track is maintained across frames, visual lock MUST be True."""
        t = 40.0
        for _ in range(10):
            det = Detection(x=320, y=240, w=80, h=80, confidence=0.85)
            res = self.tracker.step([det], (640, 480), None, 0.0, t)
            t += 0.033

        self.assertTrue(res.visual_target)
        self.assertEqual(res.command_source, "VISUAL")
        self.assertEqual(res.target_source, "CAMERA")

    # 6. test_detection_and_active_track_identity_match
    def test_detection_and_active_track_identity_match(self):
        """Detection target_id and active_track_at_command MUST match during visual tracking."""
        t = 50.0
        for _ in range(5):
            det = Detection(x=320, y=240, w=80, h=80, confidence=0.88)
            res = self.tracker.step([det], (640, 480), None, 0.0, t)
            t += 0.033

        self.assertEqual(res.target_id, res.active_track_at_command)
        self.assertEqual(res.target_id, res.active_target_at_command)

    # 7. test_43_degree_stale_yaw_spike_regression
    def test_43_degree_stale_yaw_spike_regression(self):
        """Cycle 183-189 regression test: Valid visual detection MUST NOT enter VISUAL_COAST with stale +43.1° yaw."""
        t = 100.0
        dt = 0.033

        # Prime target at head=43.1 deg
        for _ in range(10):
            t += dt
            det = Detection(x=283, y=200, w=74, h=80, confidence=0.86)
            res = self.tracker.step(
                faces=[det],
                frame_size=(640, 480),
                doa_deg=None,
                measured_head_deg=43.1,
                timestamp=t,
            )

        self.assertEqual(res.command_source, "VISUAL")
        self.assertAlmostEqual(res.target_yaw_deg, 43.1, delta=5.0)

        # Cycles 183 to 189: face moves across frame with head at 25.0 deg
        for cycle in range(183, 190):
            t += dt
            det = Detection(x=518, y=102, w=74, h=80, confidence=0.86)
            res = self.tracker.step(
                faces=[det],
                frame_size=(640, 480),
                doa_deg=None,
                measured_head_deg=25.0,
                timestamp=t,
            )
            # CRITICAL ASSERTIONS:
            # 1. Under NO circumstances should cycle 183 enter VISUAL_COAST!
            self.assertNotEqual(
                res.command_source,
                "VISUAL_COAST",
                f"Cycle {cycle} incorrectly entered VISUAL_COAST on valid visual detection!",
            )
            self.assertEqual(res.command_source, "VISUAL")
            self.assertEqual(res.target_source, "CAMERA")
            # 2. Target yaw must NEVER spike to +66.8°
            self.assertLess(
                res.target_yaw_deg,
                55.0,
                f"Cycle {cycle} target_yaw spiked abruptly to {res.target_yaw_deg:+.1f}°!",
            )

    # 8. test_current_detection_bearing_matches_command
    def test_current_detection_bearing_matches_command(self):
        """Target yaw in GazeResult MUST accurately track the observed face bearing."""
        t = 200.0
        det = Detection(x=150, y=240, w=80, h=80, confidence=0.85)
        res = self.tracker.step([det], (640, 480), None, 0.0, t)

        self.assertTrue(len(res.face_bearings_deg) > 0)
        face_bearing = res.face_bearings_deg[0]
        # Command yaw should be within deadband of face bearing
        diff = abs(angular_diff_deg(res.target_yaw_deg, face_bearing))
        self.assertLess(diff, 3.0)

    # 9. test_no_visual_command_uses_old_visual_yaw
    def test_no_visual_command_uses_old_visual_yaw(self):
        """During brief visual dropout, system coasts on last visual yaw; once face returns, it resumes live visual."""
        t = 300.0
        # 1. See face at +20 deg
        det = Detection(x=180, y=240, w=80, h=80, confidence=0.85)
        res1 = self.tracker.step([det], (640, 480), None, 0.0, t)
        last_yaw = res1.target_yaw_deg

        # 2. Face drops out for 2 frames (within coast_timeout_s=1.0)
        t += 0.05
        res_drop1 = self.tracker.step([], (640, 480), None, 0.0, t)
        self.assertEqual(res_drop1.command_source, "VISUAL_COAST")
        self.assertAlmostEqual(res_drop1.target_yaw_deg, last_yaw, delta=0.5)

        # 3. Face reappears at different location (x=400)
        t += 0.05
        det_return = Detection(x=400, y=240, w=80, h=80, confidence=0.85)
        res_return = self.tracker.step([det_return], (640, 480), None, 0.0, t)
        self.assertEqual(res_return.command_source, "VISUAL")
        self.assertNotEqual(res_return.command_source, "VISUAL_COAST")
        self.assertNotAlmostEqual(res_return.target_yaw_deg, last_yaw, delta=1.0)

    # 10. test_visual_bearing_and_target_yaw_consistency
    def test_visual_bearing_and_target_yaw_consistency(self):
        """Verify across a sweep of 10 horizontal positions that target_yaw is consistent with bearing."""
        t = 400.0
        for x_px in [80, 140, 200, 260, 320, 380, 440, 500, 560]:
            t += 0.1
            det = Detection(x=x_px, y=240, w=70, h=70, confidence=0.85)
            res = self.runtime.step([det], (640, 480), None, None, 0.0, t)
            self.assertEqual(res.command_source, "VISUAL")
            self.assertTrue(len(res.face_bearings_deg) > 0)
            bearing = res.face_bearings_deg[0]
            err = abs(angular_diff_deg(res.target_yaw_deg, bearing))
            self.assertLess(err, 4.0, f"Error at x={x_px}: target={res.target_yaw_deg}, bearing={bearing}")


if __name__ == "__main__":
    unittest.main()
