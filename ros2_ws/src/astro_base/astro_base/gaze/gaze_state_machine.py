"""Social Gaze Finite State Machine (FSM) and Priority Arbitration Engine.

Implements the 9-State Social Gaze Machine:
  IDLE | SEARCHING | AUDIO_ACQUIRE | ORIENTING | VISUAL_ACQUIRE | TRACKING | HOLD | TARGET_LOST | RETURNING

Priority Arbitration Hierarchy:
  SAFETY > GESTURE > DIALOGUE > ACTIVE_SPEAKER > VISUAL_PERSON > IDLE
"""

import math
from typing import Dict, List, Optional, Tuple

from astro_base.gaze.angle_math import (
    angular_diff_deg,
    circular_distance_deg,
    clamp_deg,
    wrap_deg,
)
from astro_base.gaze.types import (
    FusedTarget,
    GazeCommand,
    GazeStateEnum,
    Modality,
    PrioritySource,
    TargetState,
    TrackingState,
)


class SocialGazeFSM:
    """Central authoritative behavioral Gaze Manager."""

    GESTURE_PROFILES: Dict[str, List[float]] = {
        "nod": [12.0, -8.0, 0.0],
        "shake": [20.0, -20.0, 10.0, 0.0],
        "tilt": [14.0, 0.0],
        "scan": [-35.0, 35.0, 0.0],
        "center": [0.0],
        "look_left": [35.0],
        "look_right": [-35.0],
    }

    GESTURE_ALIASES: Dict[str, str] = {
        "yes": "nod", "onayla": "nod",
        "no": "shake", "reddet": "shake",
        "merak": "tilt", "curious": "tilt",
        "ara": "scan", "search": "scan",
        "sifirla": "center", "reset": "center",
    }

    def __init__(
        self,
        deadband_deg: float = 3.0,
        idle_return_timeout_s: float = 25.0,
        min_attention_dwell_s: float = 2.50,
        target_lost_timeout_s: float = 1.0,
        idle_saccades_enabled: bool = True,
        idle_saccade_interval_s: float = 8.0,
        min_limit_deg: float = -90.0,
        max_limit_deg: float = 90.0,
        position_tolerance_deg: float = 2.5,
        velocity_tolerance_deg_s: float = 3.0,
        settling_persistence_required: int = 3,
    ):
        self.deadband_deg = deadband_deg
        self.idle_return_timeout_s = idle_return_timeout_s
        self.min_attention_dwell_s = min_attention_dwell_s
        self.target_lost_timeout_s = target_lost_timeout_s
        self.idle_saccades_enabled = idle_saccades_enabled
        self.idle_saccade_interval_s = idle_saccade_interval_s
        self.min_limit_deg = min_limit_deg
        self.max_limit_deg = max_limit_deg
        self.position_tolerance_deg = position_tolerance_deg
        self.velocity_tolerance_deg_s = velocity_tolerance_deg_s
        self.settling_persistence_required = settling_persistence_required

        # Internal FSM state
        self.state = GazeStateEnum.IDLE
        self.target_yaw_deg: float = 0.0
        self.target_pitch_deg: float = 0.0
        self.active_priority: PrioritySource = PrioritySource.IDLE
        self.active_target_id: Optional[str] = None
        self.at_target: bool = True
        self._settling_persistence_count: int = 0

        # Safety & sleep locks
        self.is_sleeping: bool = False
        self.safety_lock: bool = False

        # Gesture execution state
        self._active_gesture: Optional[str] = None
        self._gesture_steps: List[float] = []
        self._gesture_step_idx: int = 0
        self._gesture_step_start_time: float = 0.0
        self._gesture_step_duration_s: float = 0.35

        # Explicit intent overrides
        self._dialogue_target_yaw: Optional[float] = None
        self._dialogue_expiry_time: float = 0.0

        # Timing tracking
        self._state_entry_time: float = 0.0
        self._last_speech_time: float = 0.0
        self._last_target_observed_time: float = 0.0
        self._last_idle_saccade_time: float = 0.0
        self._saccade_direction: int = 1

    def set_safety_lock(self, locked: bool) -> None:
        """Emergency stop or hardware safety lock."""
        self.safety_lock = locked
        if locked:
            self._active_gesture = None
            self._gesture_steps = []
            self.state = GazeStateEnum.IDLE
            self.target_yaw_deg = 0.0
            self.active_priority = PrioritySource.SAFETY

    def set_sleep_mode(self, sleeping: bool) -> None:
        """Sets robot sleep state; locks head at center during deep sleep."""
        self.is_sleeping = sleeping
        if sleeping:
            self._active_gesture = None
            self._gesture_steps = []
            self.state = GazeStateEnum.IDLE
            self.target_yaw_deg = 0.0
            self.active_priority = PrioritySource.SAFETY

    def trigger_gesture(self, gesture_name: str, timestamp: float) -> bool:
        """Queues a social head gesture sequence."""
        if self.safety_lock or self.is_sleeping:
            return False

        canonical = self.GESTURE_ALIASES.get(gesture_name.lower().strip(), gesture_name.lower().strip())
        if canonical not in self.GESTURE_PROFILES:
            return False

        self._active_gesture = canonical
        self._gesture_steps = list(self.GESTURE_PROFILES[canonical])
        self._gesture_step_idx = 0
        self._gesture_step_start_time = timestamp
        self.active_priority = PrioritySource.GESTURE
        self.target_yaw_deg = clamp_deg(self._gesture_steps[0], self.min_limit_deg, self.max_limit_deg)
        return True

    def set_dialogue_target(self, yaw_deg: float, duration_s: float, timestamp: float) -> None:
        """Sets explicit cognitive dialogue gaze intent (e.g. looking at interlocutor)."""
        if self.safety_lock or self.is_sleeping:
            return
        self._dialogue_target_yaw = clamp_deg(yaw_deg, self.min_limit_deg, self.max_limit_deg)
        self._dialogue_expiry_time = timestamp + max(0.5, duration_s)

    def _transition_to(self, new_state: GazeStateEnum, timestamp: float) -> None:
        """Executes FSM state transition."""
        if self.state != new_state:
            self.state = new_state
            self._state_entry_time = timestamp
            self._settling_persistence_count = 0

    def update(
        self,
        target_state: TargetState,
        actual_head_yaw_deg: float,
        timestamp: float,
        actual_head_vel_deg_s: float = 0.0,
    ) -> GazeCommand:
        """Evaluates sensory inputs, priority arbitration, and FSM state transitions."""
        active_target = target_state.active_target

        # Physical settling detection at commanded target_yaw_deg
        pos_err = abs(angular_diff_deg(actual_head_yaw_deg, self.target_yaw_deg))
        pos_ok = (pos_err <= self.position_tolerance_deg)
        vel_ok = (abs(actual_head_vel_deg_s) <= self.velocity_tolerance_deg_s)

        if pos_ok and vel_ok:
            self._settling_persistence_count += 1
        else:
            self._settling_persistence_count = 0

        self.at_target = (self._settling_persistence_count >= self.settling_persistence_required)

        # =========================================================================
        # 1. PRIORITY ARBITRATION: SAFETY > GESTURE > DIALOGUE
        # =========================================================================

        # Priority 1: SAFETY / SLEEP
        if self.safety_lock or self.is_sleeping:
            self.active_priority = PrioritySource.SAFETY
            self.target_yaw_deg = 0.0
            self.active_target_id = None
            if abs(actual_head_yaw_deg) > 1.5:
                self._transition_to(GazeStateEnum.RETURNING, timestamp)
            else:
                self._transition_to(GazeStateEnum.IDLE, timestamp)
            return GazeCommand(
                target_yaw_deg=0.0,
                priority_source=PrioritySource.SAFETY,
                gaze_state=self.state,
                confidence=1.0,
                timestamp=timestamp,
            )

        # Priority 2: GESTURE SEQUENCE
        if self._active_gesture and self._gesture_steps:
            self.active_priority = PrioritySource.GESTURE
            elapsed_step = timestamp - self._gesture_step_start_time
            step_target = self._gesture_steps[self._gesture_step_idx]
            head_settled = (abs(angular_diff_deg(actual_head_yaw_deg, step_target)) <= 2.0 and
                            abs(actual_head_vel_deg_s) <= self.velocity_tolerance_deg_s)

            if elapsed_step >= self._gesture_step_duration_s or head_settled:
                self._gesture_step_idx += 1
                if self._gesture_step_idx < len(self._gesture_steps):
                    self.target_yaw_deg = clamp_deg(
                        self._gesture_steps[self._gesture_step_idx], self.min_limit_deg, self.max_limit_deg
                    )
                    self._gesture_step_start_time = timestamp
                else:
                    self._active_gesture = None
                    self._gesture_steps = []
                    self._last_speech_time = timestamp
                    self._transition_to(GazeStateEnum.IDLE, timestamp)

            return GazeCommand(
                target_yaw_deg=self.target_yaw_deg,
                priority_source=PrioritySource.GESTURE,
                gaze_state=self.state,
                confidence=1.0,
                timestamp=timestamp,
            )

        # Priority 3: COGNITIVE DIALOGUE INTENT
        if self._dialogue_target_yaw is not None:
            if timestamp < self._dialogue_expiry_time:
                self.active_priority = PrioritySource.DIALOGUE
                self.target_yaw_deg = self._dialogue_target_yaw
                self._transition_to(GazeStateEnum.HOLD, timestamp)
                self._last_speech_time = timestamp
                return GazeCommand(
                    target_yaw_deg=self.target_yaw_deg,
                    priority_source=PrioritySource.DIALOGUE,
                    gaze_state=self.state,
                    confidence=0.90,
                    timestamp=timestamp,
                )
            else:
                self._dialogue_target_yaw = None

        # =========================================================================
        # 2. MULTIMODAL TARGET FSM (ACTIVE_SPEAKER & VISUAL_PERSON)
        # =========================================================================

        if active_target is not None:
            self._last_target_observed_time = timestamp
            self.active_target_id = active_target.target_id
            target_yaw = clamp_deg(active_target.body_azimuth_deg, self.min_limit_deg, self.max_limit_deg)
            err_deg = abs(angular_diff_deg(target_yaw, actual_head_yaw_deg))

            if active_target.is_speaking:
                self._last_speech_time = timestamp
                self.active_priority = PrioritySource.ACTIVE_SPEAKER
            else:
                self.active_priority = PrioritySource.VISUAL_PERSON

            if self.state == GazeStateEnum.ORIENTING:
                # Saccade in progress: update target if shifted by more than deadband
                if abs(angular_diff_deg(target_yaw, self.target_yaw_deg)) >= self.deadband_deg:
                    self.target_yaw_deg = target_yaw

                # Complete orientation ONLY when physically arrived and settled
                if self.at_target or (timestamp - self._state_entry_time) >= 2.5:
                    if active_target.modality in (Modality.FUSED, Modality.VISION):
                        self._transition_to(GazeStateEnum.TRACKING, timestamp)
                    else:
                        self._transition_to(GazeStateEnum.VISUAL_ACQUIRE, timestamp)
            elif self.state in (GazeStateEnum.TRACKING, GazeStateEnum.HOLD) and active_target.modality == Modality.VISION:
                # Smooth Visual Pursuit: Human face in view -> smoothly update setpoint without abrupt orienting saccades
                if abs(angular_diff_deg(target_yaw, self.target_yaw_deg)) >= self.deadband_deg:
                    self.target_yaw_deg = target_yaw
                self._transition_to(GazeStateEnum.TRACKING, timestamp)
            else:
                # Initiate orienting saccade if outside narrow tracking window (>15°)
                if err_deg > 15.0:
                    self.target_yaw_deg = target_yaw
                    self._settling_persistence_count = 0
                    self.at_target = False
                    self._transition_to(GazeStateEnum.ORIENTING, timestamp)
                else:
                    if abs(angular_diff_deg(target_yaw, self.target_yaw_deg)) >= self.deadband_deg:
                        self.target_yaw_deg = target_yaw

                    if active_target.modality in (Modality.FUSED, Modality.VISION):
                        self._transition_to(GazeStateEnum.TRACKING, timestamp)
                    else:
                        self._transition_to(GazeStateEnum.VISUAL_ACQUIRE, timestamp)

        else:
            # Active target is absent (no speech / no face)
            self.active_target_id = None
            self.active_priority = PrioritySource.IDLE

            if self.state == GazeStateEnum.ORIENTING:
                # Do NOT abort orientation mid-flight! Wait for head to arrive and settle
                if self.at_target or (timestamp - self._state_entry_time) >= 3.0:
                    self._transition_to(GazeStateEnum.VISUAL_ACQUIRE, timestamp)

            elif self.state == GazeStateEnum.VISUAL_ACQUIRE:
                scan_elapsed = timestamp - self._state_entry_time
                if scan_elapsed >= 0.80:
                    self._transition_to(GazeStateEnum.HOLD, timestamp)

            elif self.state == GazeStateEnum.TRACKING:
                self._transition_to(GazeStateEnum.HOLD, timestamp)

            elif self.state == GazeStateEnum.HOLD:
                dwell_elapsed = timestamp - self._state_entry_time
                if dwell_elapsed >= self.min_attention_dwell_s:
                    self._transition_to(GazeStateEnum.TARGET_LOST, timestamp)


            elif self.state == GazeStateEnum.TARGET_LOST:
                time_lost = timestamp - self._state_entry_time
                if time_lost >= self.target_lost_timeout_s:
                    self._transition_to(GazeStateEnum.RETURNING, timestamp)

            elif self.state == GazeStateEnum.RETURNING:
                self.target_yaw_deg = 0.0
                if abs(actual_head_yaw_deg) <= 1.5 and abs(actual_head_vel_deg_s) <= self.velocity_tolerance_deg_s:
                    self._transition_to(GazeStateEnum.IDLE, timestamp)

            elif self.state == GazeStateEnum.IDLE:
                self.target_yaw_deg = 0.0

                if self.idle_saccades_enabled:
                    time_since_saccade = timestamp - self._last_idle_saccade_time
                    if time_since_saccade >= self.idle_saccade_interval_s:
                        self._saccade_direction *= -1
                        self.target_yaw_deg = float(self._saccade_direction * 3.5)
                        self._last_idle_saccade_time = timestamp

        return GazeCommand(
            target_yaw_deg=self.target_yaw_deg,
            target_pitch_deg=self.target_pitch_deg,
            priority_source=self.active_priority,
            gaze_state=self.state,
            active_target_id=self.active_target_id,
            confidence=round(active_target.confidence if active_target else 0.0, 2),
            timestamp=timestamp,
        )

