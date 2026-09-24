#!/usr/bin/env python3
"""Canonical GazeTracker (Golden Reference 2e0b70c).

This module exports the core GazeTracker classes. 
The cyclic dependency to `standalone/tracker.py` has been eliminated.
"""

from .tracker import (
    DEFAULT_CALIBRATION_PATH,
    UNSCORED_CONFIDENCE,
    Detection,
    GazeResult,
    GazeTracker,
    _load_calibration,
)

__all__ = [
    "Detection",
    "GazeResult",
    "GazeTracker",
    "UNSCORED_CONFIDENCE",
    "DEFAULT_CALIBRATION_PATH",
    "_load_calibration",
]
