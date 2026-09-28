"""ASTRO V1 — Social Escort & Proxemics Controller.

Controls interactive robot accompaniment behavior:
- Monitors guest following distance (ideal 1.5 - 2.5m).
- Detects lagging or lost guests (> 3.5m or dropout > 3s).
- Pauses navigation and looks back to maintain social connection.
- Resumes navigation when guest catches up (< 2.2m).
- Delivers arrival message and faces the guest upon arrival.
"""

from dataclasses import dataclass
from enum import Enum
import math
import time
from typing import Any, Dict, Optional
from .waypoint_manager import Waypoint


class EscortState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    NAVIGATING = "navigating"
    WAITING_FOR_GUEST = "waiting_for_guest"
    ARRIVED = "arrived"
    ABORTED = "aborted"


@dataclass
class EscortStepResult:
    state: EscortState
    desired_speed_factor: float  # 0.0 (stop) to 1.0 (full speed)
    head_yaw_hint_deg: Optional[float] = None  # None = normal gaze, 120.0 = glance back
    speech_prompt: Optional[str] = None
    is_complete: bool = False
    message: str = ""


class SocialEscortController:
    """Manages guest-accompaniment state machine and social proxemics."""

    def __init__(
        self,
        target_follow_min_m: float = 1.4,
        target_follow_max_m: float = 2.6,
        lag_warning_distance_m: float = 3.0,
        stop_wait_distance_m: float = 3.8,
        resume_distance_m: float = 2.2,
        guest_lost_timeout_s: float = 3.0,
        max_wait_timeout_s: float = 40.0,
    ):
        self.target_follow_min_m = target_follow_min_m
        self.target_follow_max_m = target_follow_max_m
        self.lag_warning_distance_m = lag_warning_distance_m
        self.stop_wait_distance_m = stop_wait_distance_m
        self.resume_distance_m = resume_distance_m
        self.guest_lost_timeout_s = guest_lost_timeout_s
        self.max_wait_timeout_s = max_wait_timeout_s

        self.state: EscortState = EscortState.IDLE
        self.current_destination: Optional[Waypoint] = None
        self._start_time: float = 0.0
        self._last_guest_seen_time: float = 0.0
        self._wait_start_time: float = 0.0
        self._last_prompt_time: float = 0.0
        self._prompt_cooldown_s: float = 8.0

    def start_escort(self, destination: Waypoint, now: Optional[float] = None) -> EscortStepResult:
        t = time.monotonic() if now is None else float(now)
        self.state = EscortState.STARTING
        self.current_destination = destination
        self._start_time = t
        self._last_guest_seen_time = t
        self._wait_start_time = 0.0
        self._last_prompt_time = t

        start_msg = f"Lütfen beni takip edin, sizi {destination.name} noktasına götürüyorum."
        return EscortStepResult(
            state=EscortState.NAVIGATING,
            desired_speed_factor=1.0,
            head_yaw_hint_deg=0.0,
            speech_prompt=start_msg,
            is_complete=False,
            message=start_msg,
        )

    def update(
        self,
        human_distance_m: Optional[float],
        nav_reached: bool = False,
        now: Optional[float] = None,
    ) -> EscortStepResult:
        t = time.monotonic() if now is None else float(now)

        if self.state in (EscortState.IDLE, EscortState.ARRIVED, EscortState.ABORTED):
            return EscortStepResult(
                state=self.state,
                desired_speed_factor=0.0,
                is_complete=True,
                message="Refakat aktif değil.",
            )

        # 1. Check arrival at goal
        if nav_reached and self.current_destination:
            self.state = EscortState.ARRIVED
            arrival_text = self.current_destination.arrival_message or f"{self.current_destination.name} noktasına ulaştık."
            return EscortStepResult(
                state=EscortState.ARRIVED,
                desired_speed_factor=0.0,
                head_yaw_hint_deg=0.0,
                speech_prompt=arrival_text,
                is_complete=True,
                message=arrival_text,
            )

        # 2. Track human observer presence
        if human_distance_m is not None and human_distance_m > 0.1:
            self._last_guest_seen_time = t
            guest_dist = float(human_distance_m)
            guest_seen = True
        else:
            guest_seen = False
            guest_dist = None

        time_since_seen = t - self._last_guest_seen_time

        # 3. State transitions
        if self.state in (EscortState.STARTING, EscortState.NAVIGATING):
            self.state = EscortState.NAVIGATING

            # Check if guest fell behind or lost
            needs_wait = False
            if guest_seen and guest_dist is not None and guest_dist >= self.stop_wait_distance_m:
                needs_wait = True
            elif not guest_seen and time_since_seen >= self.guest_lost_timeout_s:
                needs_wait = True

            if needs_wait:
                self.state = EscortState.WAITING_FOR_GUEST
                self._wait_start_time = t
                prompt = "Sizi bekliyorum, arkamdan gelebilirsiniz."
                self._last_prompt_time = t

                return EscortStepResult(
                    state=EscortState.WAITING_FOR_GUEST,
                    desired_speed_factor=0.0,
                    head_yaw_hint_deg=110.0,  # Turn head back to look for guest
                    speech_prompt=prompt,
                    is_complete=False,
                    message="Misafir geride kaldı, duraklayıp bekleniyor.",
                )

            # Guest is following nicely -> modulate speed based on distance
            speed_factor = 1.0
            if guest_seen and guest_dist is not None:
                if guest_dist > self.lag_warning_distance_m:
                    speed_factor = 0.5  # Slow down smoothly
                elif guest_dist < self.target_follow_min_m:
                    speed_factor = 0.8  # Don't rush if too close

            return EscortStepResult(
                state=EscortState.NAVIGATING,
                desired_speed_factor=speed_factor,
                head_yaw_hint_deg=None,
                speech_prompt=None,
                is_complete=False,
                message=f"Refakat devam ediyor (hız={speed_factor:.2f}).",
            )

        elif self.state == EscortState.WAITING_FOR_GUEST:
            # Check wait timeout
            wait_elapsed = t - self._wait_start_time if self._wait_start_time > 0 else 0.0
            if wait_elapsed >= self.max_wait_timeout_s:
                self.state = EscortState.ABORTED
                abort_text = "Misafir uzun süre görünmediği için refakat sonlandırıldı."
                return EscortStepResult(
                    state=EscortState.ABORTED,
                    desired_speed_factor=0.0,
                    head_yaw_hint_deg=0.0,
                    speech_prompt="Sizi göremediğim için refakati durduruyorum. İhtiyacınız olduğunda seslenebilirsiniz.",
                    is_complete=True,
                    message=abort_text,
                )

            # Check if guest re-approached
            if guest_seen and guest_dist is not None and guest_dist <= self.resume_distance_m:
                self.state = EscortState.NAVIGATING
                resume_prompt = "Harika, devam ediyoruz."
                self._last_prompt_time = t

                return EscortStepResult(
                    state=EscortState.NAVIGATING,
                    desired_speed_factor=1.0,
                    head_yaw_hint_deg=0.0,
                    speech_prompt=resume_prompt,
                    is_complete=False,
                    message="Misafir yetişti, refakate devam ediliyor.",
                )

            # Still waiting
            prompt = None
            if (t - self._last_prompt_time) >= self._prompt_cooldown_s and wait_elapsed >= 10.0:
                prompt = "Buradayım, sizi bekliyorum."
                self._last_prompt_time = t

            return EscortStepResult(
                state=EscortState.WAITING_FOR_GUEST,
                desired_speed_factor=0.0,
                head_yaw_hint_deg=110.0,
                speech_prompt=prompt,
                is_complete=False,
                message="Misafir bekleniyor.",
            )

        return EscortStepResult(state=self.state, desired_speed_factor=0.0, is_complete=False)

    def cancel(self, reason: str = "Kullanıcı isteği") -> EscortStepResult:
        self.state = EscortState.ABORTED
        return EscortStepResult(
            state=EscortState.ABORTED,
            desired_speed_factor=0.0,
            head_yaw_hint_deg=0.0,
            speech_prompt="Rehberlik iptal edildi.",
            is_complete=True,
            message=f"Refakat iptal edildi: {reason}",
        )
