"""Authoritative Shared Gaze Runtime Engine for ASTRO Robot Head.

This module provides the shared runtime execution engine used by
both:
  - standalone/track.py (via standalone/tracker.py)
  - RES 2 gaze nodes (standalone_gaze_node.py and social_gaze_node.py)

Execution Semantics:
  ONE CAMERA FRAME -> ONE GAZE STEP -> ONE GazeResult -> ONE HEAD TARGET

Passive 50Hz Motor Keepalive:
  Returns the last authoritative target_yaw_deg without stepping the tracker,
  modifying targets, or updating visual FSM state.
"""

import time
from typing import List, Optional, Sequence, Tuple

from astro_base.gaze.coordinate_frames import CalibrationConfig
from astro_base.gaze.gaze_tracker import (
    Detection,
    GazeResult,
    GazeTracker,
    _load_calibration,
)


class GazeRuntimeCore:
    """The authoritative shared gaze runtime engine."""

    def __init__(
        self,
        calibration: Optional[CalibrationConfig] = None,
        calibration_path: Optional[str] = None,
        coast_timeout_s: float = 1.0,
    ):
        self.calib = calibration or _load_calibration(calibration_path)
        self.tracker = GazeTracker(
            calibration=self.calib,
            coast_timeout_s=coast_timeout_s,
        )
        self.actual_head_yaw_deg: float = 0.0
        self.actual_head_vel_deg_s: float = 0.0
        self.has_head_feedback: bool = False
        self.last_result: Optional[GazeResult] = None
        self.last_target_yaw_deg: float = 0.0
        self.cycle_count: int = 0

    @property
    def head_feedback_missing(self) -> bool:
        return not self.has_head_feedback

    @property
    def head_angle_deg(self) -> float:
        return self.actual_head_yaw_deg

    def update_head_feedback(
        self,
        angle_deg: float,
        velocity_deg_s: float = 0.0,
    ) -> None:
        """Updates real encoder position and velocity from hardware feedback."""
        self.actual_head_yaw_deg = float(angle_deg)
        self.actual_head_vel_deg_s = float(velocity_deg_s)
        self.has_head_feedback = True
        self.tracker.head_angle_deg = float(angle_deg)
        self.tracker.head_velocity_deg_s = float(velocity_deg_s)
        self.tracker.head_feedback_missing = False

    def step(
        self,
        faces: Sequence[Detection],
        frame_size: Tuple["int", "int"] = (640, 480),
        doa_deg: Optional[float] = None,
        speech= None,
        measured_head_deg: Optional[float] = None,
        timestamp: Optional[float] = None,
        is_robot_speaking: bool = False,
    ) -> GazeResult:
        """Executes exactly ONE authoritative tracker step for ONE camera frame.

        Enforces strict Single Cycle Semantics:
        ONE CAMERA FRAME -> ONE GAZE STEP -> ONE RESULT
        """
        if timestamp is None:
            timestamp = time.monotonic()

        if measured_head_deg is not None:
            self.update_head_feedback(measured_head_deg)

        measured_head = self.actual_head_yaw_deg if self.has_head_feedback else None

        result = self.tracker.step(
            faces=faces,
            frame_size=frame_size,
            doa_deg=doa_deg,
            speech=speech,
            measured_head_deg=measured_head,
            timestamp=timestamp,
            is_robot_speaking=is_robot_speaking,
        )

        self.last_result = result
        self.last_target_yaw_deg = float(result.target_yaw_deg)
        self.cycle_count += 1
        return result

    def get_keepalive_yaw_deg(self) -> float:
        """Returns last target yaw for 50Hz passive motor keepalive.

        DOES NOT step tracker.
        DOES NOT update targets.
        DOES NOT update visual FSM.
        """
        return self.last_target_yaw_deg

    def get_keepalive_yaw(self) -> float:
        """Alias for get_keepalive_yaw_deg."""
        return self.get_keepalive_yaw_deg()

