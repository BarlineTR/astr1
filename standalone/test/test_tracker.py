#!/usr/bin/env python3
"""Tests for the ROS-free tracker.

This is the same brain the ROS node runs — the fusion, target manager and FSM are
imported, not reimplemented — so what is tested here is the wiring around them, and
that the guarantees the ROS side already has survive the move: bearings that account
for where the head is, audio that says who rather than where, and a head estimate
that does not collapse to centre when the encoder stays silent.

If behaviour here and under ROS ever differ, the difference is the plumbing. That is
the whole reason this exists.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core_path  # noqa: F401
from astro_base.gaze.types import GazeStateEnum, PrioritySource  # noqa: E402

from tracker import Detection, GazeTracker  # noqa: E402


FRAME = (640, 480)


def _face_at(u_fraction: float, confidence: float = 0.92) -> Detection:
    """A face box centred at the given fraction across the frame (0 left, 1 right)."""
    w = h = 90
    cx = u_fraction * FRAME[0]
    return Detection(x=int(cx - w / 2), y=195, w=w, h=h, confidence=confidence)


class TestAFaceMovesTheHead(unittest.TestCase):
    def setUp(self):
        self.tracker = GazeTracker()

    def _settle(self, faces, cycles=40, t0=100.0, head=0.0):
        result = None
        for i in range(cycles):
            result = self.tracker.step(
                faces=faces, frame_size=FRAME, doa_deg=None,
                measured_head_deg=head, timestamp=t0 + i * 0.02,
            )
        return result

    def test_a_face_on_the_left_is_answered_with_a_leftward_command(self):
        """Image left is positive yaw in REP-103, which is the convention the whole
        stack uses and the easiest thing to get backwards."""
        result = self._settle([_face_at(0.15)])

        self.assertGreater(result.target_yaw_deg, 5.0)

    def test_a_face_on_the_right_is_answered_with_a_rightward_command(self):
        result = self._settle([_face_at(0.85)])

        self.assertLess(result.target_yaw_deg, -5.0)

    def test_a_centred_face_leaves_the_head_where_it_is(self):
        result = self._settle([_face_at(0.5)])

        self.assertAlmostEqual(result.target_yaw_deg, 0.0, delta=4.0)

    def test_a_visible_face_owns_the_attention(self):
        result = self._settle([_face_at(0.3)])

        self.assertIn(
            result.owner, (PrioritySource.VISUAL_TRACKING, PrioritySource.ACTIVE_SPEAKER)
        )

    def test_an_empty_scene_stays_idle_at_centre(self):
        result = self._settle([])

        self.assertEqual(result.owner, PrioritySource.IDLE)
        self.assertEqual(result.gaze_state, GazeStateEnum.IDLE)
        self.assertAlmostEqual(result.target_yaw_deg, 0.0, delta=0.1)


class TestBearingsAccountForWhereTheHeadIs(unittest.TestCase):
    """`body_azimuth = head_yaw + camera_azimuth`. Getting this wrong is what made
    the ROS version drive back to centre the moment the head moved."""

    def test_a_centred_face_seen_from_a_turned_head_is_not_at_zero(self):
        tracker = GazeTracker()
        result = None
        for i in range(40):
            result = tracker.step(
                faces=[_face_at(0.5)], frame_size=FRAME, doa_deg=None,
                measured_head_deg=30.0, timestamp=100.0 + i * 0.02,
            )

        self.assertGreater(result.target_yaw_deg, 25.0)


class TestTheHeadEstimateWithoutAnEncoder(unittest.TestCase):
    def test_a_silent_encoder_is_reported_rather_than_assumed_to_be_zero(self):
        tracker = GazeTracker()

        tracker.step(faces=[], frame_size=FRAME, doa_deg=None,
                     measured_head_deg=None, timestamp=100.0)

        self.assertTrue(tracker.head_feedback_missing)

    def test_the_estimate_follows_the_command_instead_of_sitting_at_zero(self):
        tracker = GazeTracker()
        for i in range(400):
            tracker.step(faces=[_face_at(0.05)], frame_size=FRAME, doa_deg=None,
                         measured_head_deg=None, timestamp=100.0 + i * 0.02)

        self.assertGreater(tracker.head_angle_deg, 5.0)

    def test_a_real_reading_takes_over_from_the_estimate(self):
        tracker = GazeTracker()
        for i in range(20):
            tracker.step(faces=[_face_at(0.05)], frame_size=FRAME, doa_deg=None,
                         measured_head_deg=None, timestamp=100.0 + i * 0.02)

        tracker.step(faces=[], frame_size=FRAME, doa_deg=None,
                     measured_head_deg=-12.0, timestamp=101.0)

        self.assertEqual(tracker.head_angle_deg, -12.0)
        self.assertFalse(tracker.head_feedback_missing)


class TestAudioSaysWhoNotWhere(unittest.TestCase):
    """The same guarantee the ROS side has: a wandering DOA must not drag the aim."""

    def test_the_aim_is_unchanged_across_the_doa_spread(self):
        aims = set()
        for raw_doa in (0.0, 15.0, 330.0, 345.0):
            tracker = GazeTracker()
            result = None
            for i in range(40):
                result = tracker.step(
                    faces=[_face_at(0.3)], frame_size=FRAME, doa_deg=raw_doa,
                    measured_head_deg=0.0, timestamp=100.0 + i * 0.02,
                )
            aims.add(round(result.target_yaw_deg, 1))

        self.assertEqual(len(aims), 1, f"audio moved the aim: {aims}")


if __name__ == "__main__":
    unittest.main()
