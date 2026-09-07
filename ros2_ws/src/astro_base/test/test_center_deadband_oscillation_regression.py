#!/usr/bin/env python3
"""Regression test for 3.00° SocialGazeFSM command deadband.

Verifies:
1. An angular fluctuation just below 3.00° (e.g. peak-to-peak 2.60°) does NOT cause
   alternating reference updates or limit-cycle hunting.
2. An angular step of error >= 3.00° permits a legitimate gaze correction.
3. Dynamic continuous tracking of left/right moving subjects remains completely unchanged.
"""

import os
import sys
from pathlib import Path
import pytest
import numpy as np

# Resolve standalone and ros package paths
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
_STANDALONE_DIR = os.path.join(_REPO_ROOT, "standalone")
_ASTRO_BASE_DIR = os.path.join(_REPO_ROOT, "ros2_ws", "src", "astro_base")

for p in (_STANDALONE_DIR, _ASTRO_BASE_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from tracker import GazeTracker, Detection
from astro_base.gaze.types import GazeStateEnum


def test_sub_deadband_jitter_does_not_alternate():
    """Proves that sensor/feedback jitter below 3.00° does not cause alternating setpoint updates."""
    tracker = GazeTracker()
    assert tracker.fsm.deadband_deg == 3.00, f"Expected 3.00° deadband, got {tracker.fsm.deadband_deg}"

    # Initial frame to acquire and lock center target at 0.0°
    t = 0.0
    det_center = [Detection(x=270, y=190, w=100, h=100, confidence=0.90)]  # cx = 320.0 (0.0°)
    res0 = tracker.step(
        faces=det_center,
        frame_size=(640, 480),
        doa_deg=None,
        measured_head_deg=0.0,
        timestamp=t,
    )
    initial_target = res0.target_yaw_deg
    assert abs(initial_target) <= 0.5

    # Simulate alternating fluctuations between -1.3° (cx=331.6) and +1.3° (cx=308.4)
    # The peak-to-peak span is 2.60°, which previously triggered limit cycles with 2.50° deadband.
    target_history = []
    head_pos = initial_target

    for i in range(1, 30):
        t += 0.033
        # Alternate between -1.3° and +1.3°
        jitter_deg = -1.3 if (i % 2 == 0) else +1.3
        # Invert: positive image cx = negative optical yaw
        cx = 320.0 - (jitter_deg / 36.0) * 320.0
        det = [Detection(x=int(cx - 50), y=190, w=100, h=100, confidence=0.90)]

        res = tracker.step(
            faces=det,
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=head_pos,
            timestamp=t,
        )
        target_history.append(res.target_yaw_deg)

    # With 3.00° deadband, the setpoint must remain perfectly steady without flip-flops
    unique_targets = set(np.round(target_history, 2))
    assert len(unique_targets) == 1, (
        f"Target yaw fluctuated across deadband: unique values = {unique_targets}"
    )
    assert target_history[0] == pytest.approx(initial_target, abs=0.1)


def test_super_deadband_error_permits_legitimate_correction():
    """Proves that a legitimate target displacement >= 3.00° updates the target yaw."""
    tracker = GazeTracker()
    t = 0.0

    # Acquire initial target at 0.0°
    det0 = [Detection(x=270, y=190, w=100, h=100, confidence=0.90)]
    res0 = tracker.step(
        faces=det0,
        frame_size=(640, 480),
        doa_deg=None,
        measured_head_deg=0.0,
        timestamp=t,
    )
    initial_target = res0.target_yaw_deg

    # Subject steps by +4.0° (to the left in robot body frame: positive yaw)
    # Optical bearing = +4.0°, cx = 320 - (4.0/36)*320 = 284.4
    for i in range(1, 10):
        t += 0.033
        det_step = [Detection(x=int(284.4 - 50), y=190, w=100, h=100, confidence=0.90)]
        res_step = tracker.step(
            faces=det_step,
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=0.0,
            timestamp=t,
        )

    # Legitimate shift exceeding 3.00° deadband must update target_yaw_deg
    assert abs(res_step.target_yaw_deg - initial_target) >= 3.00
    assert res_step.target_yaw_deg > initial_target


def test_dynamic_left_right_tracking_unchanged():
    """Proves that smooth left and right dynamic pursuit tracking functions identically."""
    tracker = GazeTracker()
    t = 0.0
    head_pos = 0.0

    # 1. Sweep right to -20.0°
    for az in np.linspace(0.0, -20.0, 30):
        t += 0.033
        optical = az - head_pos
        cx = 320.0 - (optical / 36.0) * 320.0
        det = [Detection(x=int(cx - 50), y=190, w=100, h=100, confidence=0.90)]
        res = tracker.step(
            faces=det,
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=head_pos,
            timestamp=t,
        )
        err = res.target_yaw_deg - head_pos
        step = np.clip(err, -40.0 * 0.033, 40.0 * 0.033)
        head_pos += step

    # 2. Sweep left from -20.0° to +20.0°
    for az in np.linspace(-20.0, 20.0, 60):
        t += 0.033
        optical = az - head_pos
        cx = 320.0 - (optical / 36.0) * 320.0
        det = [Detection(x=int(cx - 50), y=190, w=100, h=100, confidence=0.90)]
        res = tracker.step(
            faces=det,
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=head_pos,
            timestamp=t,
        )
        err = res.target_yaw_deg - head_pos
        step = np.clip(err, -40.0 * 0.033, 40.0 * 0.033)
        head_pos += step

    # 3. Settle at +20.0°
    for _ in range(15):
        t += 0.033
        optical = 20.0 - head_pos
        cx = 320.0 - (optical / 36.0) * 320.0
        det = [Detection(x=int(cx - 50), y=190, w=100, h=100, confidence=0.90)]
        res = tracker.step(
            faces=det,
            frame_size=(640, 480),
            doa_deg=None,
            measured_head_deg=head_pos,
            timestamp=t,
        )
        err = res.target_yaw_deg - head_pos
        step = np.clip(err, -40.0 * 0.033, 40.0 * 0.033)
        head_pos += step

    assert res.target_yaw_deg == pytest.approx(20.0, abs=2.5)
    assert res.gaze_state in (GazeStateEnum.TRACKING, GazeStateEnum.HOLDING_ATTENTION)
