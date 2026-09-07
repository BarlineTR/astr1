#!/usr/bin/env python3
"""The gaze pipeline, driven directly instead of through ROS topics.

This module re-exports the canonical GazeTracker and data structures from
astro_base.gaze.gaze_tracker for standalone execution.
"""

import core_path  # noqa: F401

from astro_base.gaze.gaze_runtime import GazeRuntimeCore
from astro_base.gaze.gaze_tracker import (
    Detection,
    GazeResult,
    GazeTracker,
    UNSCORED_CONFIDENCE,
    DEFAULT_CALIBRATION_PATH,
    _load_calibration,
)

__all__ = [
    "Detection",
    "GazeResult",
    "GazeTracker",
    "GazeRuntimeCore",
    "UNSCORED_CONFIDENCE",
    "DEFAULT_CALIBRATION_PATH",
    "_load_calibration",
]

