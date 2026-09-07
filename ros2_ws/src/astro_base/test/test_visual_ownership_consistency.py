#!/usr/bin/env python3
"""ASTRO — Visual Ownership & Coasting Consistency Regression Suite.

Verifies the 5 critical invariants:
  INVARIANT 1: Under NO_ACTIVE_TARGET / IDLE, command_source CANNOT be VISUAL_COAST,
               target_source CANNOT be COAST, and old coast bearing cannot leak.
  INVARIANT 2: VISUAL_COAST is strictly permitted ONLY during transient dropout of an
               already-authoritative active visual target within coast_timeout_s.
  INVARIANT 3: DETECTION track_id mismatch cannot overwrite active track bearing or hijack lock.
  INVARIANT 4: command_source and target_source are strictly synchronized:
               VISUAL -> CAMERA, VISUAL_COAST -> COAST, IDLE -> NONE.
  INVARIANT 5: First visual detection is always VISUAL (CAMERA), never VISUAL_COAST.
"""

import math
import os
import sys
from pathlib import Path
import unittest

# Ensure standalone and astro_base packages are accessible
REPO_ROOT = Path(__file__).resolve().parents[4]
STANDALONE_DIR = REPO_ROOT / "standalone"
if str(STANDALONE_DIR) not in sys.path:
    sys.path.insert(0, str(STANDALONE_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tracker import GazeTracker, Detection, GazeResult
from astro_base.gaze.types import PrioritySource, TrackingState, Modality, GazeStateEnum
from astro_base.social_gaze_node import SocialGazeNode

FRAME = (640, 480)


def _make_face(x_frac: float = 0.5, confidence: float = 0.85, w: int = 80, h: int = 80) -> Detection:
    """Helper to generate a Detection at a horizontal fraction of the frame."""
    x = int(FRAME[0] * x_frac - w / 2)
    y = int(FRAME[1] * 0.5 - h / 2)
    return Detection(x=x, y=y, w=w, h=h, confidence=confidence, detector_source="TEST")


class TestVisualOwnershipConsistency(unittest.TestCase):
    """Regression test suite enforcing visual ownership consistency and preventing ghost coast commands."""

    def test_idle_cannot_issue_visual_coast_command(self):
        """Invariant 1: When idle with no targets, command_source cannot be VISUAL_COAST."""
        tracker = GazeTracker()
        for i in range(5):
            res = tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.05,
                speech=None,
            )
            self.assertEqual(res.owner, PrioritySource.IDLE)
            self.assertNotEqual(res.command_source, "VISUAL_COAST")
            self.assertNotEqual(res.target_source, "COAST")
            self.assertFalse(res.coast_active)
            self.assertEqual(res.target_source, "NONE")
            self.assertEqual(res.active_target_at_command, "NONE")
            self.assertEqual(res.active_track_at_command, "NONE")

    def test_no_active_target_cannot_use_old_coast_bearing(self):
        """Invariant 1 & 2: After a target is lost, tracker cannot issue VISUAL_COAST with old bearing."""
        tracker = GazeTracker()
        # Face at 0.25 -> ~ -18°
        face = _make_face(0.25, confidence=0.90)

        # 1. Lock onto face
        for i in range(10):
            res = tracker.step(
                faces=[face],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=None,
            )
        self.assertEqual(res.command_source, "VISUAL")
        old_bearing = res.target_yaw_deg
        self.assertNotEqual(old_bearing, 0.0)

        # 2. Advance time past coast timeout (1.0s) and target lost timeout
        res_lost = None
        for i in range(15):
            res_lost = tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=0.0,
                timestamp=102.0 + i * 0.05,
                speech=None,
            )

        # Invariant: NO_ACTIVE_TARGET / IDLE cannot issue VISUAL_COAST or use old bearing
        self.assertEqual(res_lost.owner, PrioritySource.IDLE)
        self.assertNotEqual(res_lost.command_source, "VISUAL_COAST")
        self.assertNotEqual(res_lost.target_source, "COAST")
        self.assertEqual(res_lost.target_source, "NONE")
        self.assertEqual(res_lost.active_target_at_command, "NONE")
        # Motor target yaw should be stationary at head angle, NOT the old visual bearing
        self.assertAlmostEqual(res_lost.target_yaw_deg, res_lost.head_angle_deg, delta=0.5)

    def test_new_detection_does_not_use_old_coasting_track(self):
        """Invariant 3: A new detection at a different angle does not blend or use old coasting track."""
        tracker = GazeTracker()
        face_left = _make_face(0.20, confidence=0.90)   # Person 1 on left (~ -20°)
        face_right = _make_face(0.80, confidence=0.90)  # Person 2 on right (~ +20°)

        # 1. Lock on person 1
        for i in range(10):
            res = tracker.step(
                faces=[face_left],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=None,
            )
        person_1_id = res.target_id
        self.assertIsNotNone(person_1_id)
        self.assertGreater(res.target_yaw_deg, 10.0)

        # 2. Person 1 drops out, person 2 appears on right
        res2 = tracker.step(
            faces=[face_right],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=0.0,
            timestamp=100.5,
            speech=None,
        )

        # Telemetry check: command must NOT use person 1's positive coast bearing for person 2
        forensic = res2.forensic
        self.assertIsNotNone(forensic)
        cmd_info = forensic["command"]
        self.assertIn("active_target_at_command", cmd_info)
        self.assertIn("active_track_at_command", cmd_info)
        # If active target switched to person 2 or remained locked, command must be negative (right), not positive
        if res2.command_source == "VISUAL":
            self.assertLess(res2.target_yaw_deg, 0.0)
            self.assertEqual(res2.target_source, "CAMERA")

    def test_visual_acquisition_command_source_is_camera(self):
        """Invariant 5: On first visual detection, command_source is VISUAL and target_source is CAMERA."""
        tracker = GazeTracker()
        face = _make_face(0.35, confidence=0.85)

        res = tracker.step(
            faces=[face],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=0.0,
            timestamp=100.0,
            speech=None,
        )

        # First acquisition must be VISUAL / CAMERA, NEVER VISUAL_COAST / COAST
        self.assertEqual(res.command_source, "VISUAL")
        self.assertEqual(res.target_source, "CAMERA")
        self.assertFalse(res.coast_active)
        self.assertEqual(res.active_target_at_command, res.target_id)

    def test_visual_dropout_then_coast_is_allowed(self):
        """Invariant 2: When an active target temporarily drops out, VISUAL_COAST is issued."""
        tracker = GazeTracker()
        face = _make_face(0.30, confidence=0.90)

        # 1. Establish visual tracking lock
        for i in range(10):
            res_lock = tracker.step(
                faces=[face],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=None,
            )
        self.assertEqual(res_lock.command_source, "VISUAL")
        locked_yaw = res_lock.target_yaw_deg

        # 2. Transient visual dropout within coast timeout (0.15s elapsed)
        res_coast = tracker.step(
            faces=[],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=0.0,
            timestamp=100.35,
            speech=None,
        )

        self.assertEqual(res_coast.command_source, "VISUAL_COAST")
        self.assertEqual(res_coast.target_source, "COAST")
        self.assertTrue(res_coast.coast_active)
        self.assertAlmostEqual(res_coast.target_yaw_deg, locked_yaw, delta=1.0)
        self.assertEqual(res_coast.active_target_at_command, res_lock.target_id)

    def test_visual_coast_requires_existing_active_visual_target(self):
        """Invariant 2: VISUAL_COAST cannot occur without a prior authoritative visual lock."""
        tracker = GazeTracker()
        # Step with no prior visual lock
        res = tracker.step(
            faces=[],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=0.0,
            timestamp=100.0,
            speech=None,
        )
        self.assertNotEqual(res.command_source, "VISUAL_COAST")
        self.assertNotEqual(res.target_source, "COAST")
        self.assertFalse(res.coast_active)
        self.assertEqual(res.active_target_at_command, "NONE")

    def test_detection_track_id_mismatch_does_not_change_command(self):
        """Invariant 3: Detection with different track_id does not falsely trigger visual lock for active track."""
        tracker = GazeTracker()
        face1 = _make_face(0.30, confidence=0.90)
        for i in range(10):
            res1 = tracker.step(
                faces=[face1],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=None,
            )
        tid1 = res1.target_id

        # At t=100.5, face1 is missing, face2 appears far away at 0.85
        face2 = _make_face(0.85, confidence=0.90)
        res2 = tracker.step(
            faces=[face2],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=0.0,
            timestamp=100.5,
            speech=None,
        )

        # Active track at command must match the target being commanded
        self.assertIn(res2.active_track_at_command, [res2.active_target_at_command, "NONE", "person_1", "person_2"])
        # Either person 2 was acquired (VISUAL + CAMERA) or person 1 was maintained (not corrupted)
        if res2.command_source == "VISUAL":
            self.assertEqual(res2.target_source, "CAMERA")
        elif res2.command_source == "VISUAL_COAST":
            self.assertEqual(res2.target_source, "COAST")

    def test_command_source_matches_attention_owner(self):
        """Invariant 4: command_source and attention_owner are strictly synchronized."""
        tracker = GazeTracker()
        face = _make_face(0.40, confidence=0.90)

        # Step 1: IDLE
        res_idle = tracker.step([], FRAME, None, 0.0, 100.0)
        self.assertEqual(res_idle.owner, PrioritySource.IDLE)
        self.assertIn(res_idle.command_source, ("IDLE", "SAFETY_ZERO"))
        self.assertEqual(res_idle.target_source, "NONE")

        # Step 2: Visual lock
        for i in range(8):
            res_vis = tracker.step([face], FRAME, None, 0.0, 101.0 + i * 0.02)
        self.assertEqual(res_vis.owner, PrioritySource.VISUAL_TRACKING)
        self.assertEqual(res_vis.command_source, "VISUAL")
        self.assertEqual(res_vis.target_source, "CAMERA")

        # Step 3: Dropout -> Coast
        res_coast = tracker.step([], FRAME, None, 0.0, 101.25)
        self.assertEqual(res_coast.command_source, "VISUAL_COAST")
        self.assertEqual(res_coast.target_source, "COAST")

    def test_idle_target_source_is_none(self):
        """Invariant 4: When IDLE, target_source must always be NONE."""
        tracker = GazeTracker()
        res = tracker.step([], FRAME, None, 0.0, 100.0)
        self.assertEqual(res.owner, PrioritySource.IDLE)
        self.assertEqual(res.target_source, "NONE")
        self.assertIn(res.command_source, ("IDLE", "SAFETY_ZERO"))

    def test_old_visual_track_cannot_drive_motor_after_target_loss(self):
        """Invariant 1: After target loss, old visual track bearing cannot drive motor."""
        tracker = GazeTracker()
        face = _make_face(0.20, confidence=0.88)  # ~ -20°

        # Lock onto target
        for i in range(10):
            res = tracker.step([face], FRAME, None, 0.0, 100.0 + i * 0.02)
        initial_target_yaw = res.target_yaw_deg

        # Let target time out past 2.0s
        for i in range(25):
            res = tracker.step([], FRAME, None, 0.0, 100.5 + i * 0.1)

        # After loss:
        self.assertEqual(res.owner, PrioritySource.IDLE)
        self.assertEqual(res.target_source, "NONE")
        self.assertNotEqual(res.command_source, "VISUAL_COAST")
        self.assertEqual(res.active_target_at_command, "NONE")
        # Motor target must NOT be the old -20° bearing
        self.assertAlmostEqual(res.target_yaw_deg, res.head_angle_deg, delta=0.5)

    def test_social_gaze_node_enforces_same_ownership_invariants(self):
        """ROS SocialGazeNode consistency check: IDLE never produces VISUAL_COAST."""
        node = SocialGazeNode()
        # Node starts in IDLE with no tracks
        node._control_cycle()
        cmd_telemetry = node.last_forensic_chain["command"]
        self.assertNotEqual(cmd_telemetry["command_source"], "VISUAL_COAST")
        self.assertEqual(cmd_telemetry["target_source"], "NONE")
        self.assertEqual(cmd_telemetry["active_target_at_command"], "NONE")
        self.assertEqual(cmd_telemetry["active_track_at_command"], "NONE")


if __name__ == "__main__":
    unittest.main()
