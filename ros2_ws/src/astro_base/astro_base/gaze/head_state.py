"""ASTRO Head State Abstraction & Fallback Management.

Provides unified head position authority handling:
- ENCODER: Real hardware encoder is alive and authoritative.
- ESTIMATED: Software-only estimation based strictly on accepted commands.
- UNKNOWN: No encoder and no accepted command; position is NOT assumed to be 0.0.

CRITICAL INVARIANTS:
1. `actual_yaw_deg` and `position_deg` are ONLY populated from real encoder feedback.
   They are NEVER secretly filled with estimated values.
2. `estimated_yaw_deg` is a software heuristic estimate and must never be treated
   as guaranteed physical head position.
3. `UNKNOWN` indicates absence of knowledge, distinctly separated from 0.0°.
4. Emergency stop and hardware safety must NEVER rely on `ESTIMATED` position.
"""

from enum import Enum
import math
import time
from dataclasses import dataclass
from typing import Optional


class PositionSource(str, Enum):
    """Authority source for head position."""
    ENCODER = "ENCODER"                  # Physical hardware encoder feedback
    VIRTUAL_ENCODER = "VIRTUAL_ENCODER"  # Software trajectory/command-based estimation
    UNKNOWN = "UNKNOWN"                  # Position is completely unknown (not assumed to be 0.0)

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str) and value.upper() == "ESTIMATED":
            return cls.VIRTUAL_ENCODER
        return super()._missing_(value)

PositionSource.ESTIMATED = PositionSource.VIRTUAL_ENCODER


@dataclass
class HeadState:
    """Unified head state telemetry and authority model."""
    position_source: PositionSource = PositionSource.UNKNOWN
    encoder_available: bool = False
    encoder_stale: bool = True
    actual_yaw_deg: Optional[float] = None
    estimated_yaw_deg: Optional[float] = None
    canonical_yaw_deg: Optional[float] = None  # Sole centrally resolved canonical yaw
    position_deg: float = float("nan")       # Physical encoder angle only (NaN if absent/stale)
    velocity_deg_s: float = 0.0
    target_position_deg: float = 0.0
    moving: bool = False
    at_target: bool = False
    enabled: bool = True
    watchdog_healthy: bool = True
    encoder_valid: bool = False
    fault_code: int = 0
    timestamp: float = 0.0

    @property
    def has_valid_position(self) -> bool:
        """True if any valid position (physical or estimated) is known."""
        return self.position_source in (PositionSource.ENCODER, PositionSource.VIRTUAL_ENCODER)

    @property
    def has_encoder_authority(self) -> bool:
        """True if physical encoder feedback is actively valid and fresh."""
        return self.position_source == PositionSource.ENCODER and self.actual_yaw_deg is not None

    @property
    def is_virtual(self) -> bool:
        """True if operating in virtual encoder mode."""
        return self.position_source == PositionSource.VIRTUAL_ENCODER


class HeadStateManager:
    """Manages head position authority, encoder freshness, stuck-at-zero detection, and software estimation."""

    def __init__(
        self,
        ticks_per_deg: float = 2.5882,
        stale_timeout_s: float = 0.50,
        software_max_vel_deg_s: float = 20.0,
        min_limit_deg: float = -90.0,
        max_limit_deg: float = 90.0,
        stuck_timeout_s: float = 0.50,
    ):
        self.ticks_per_deg = ticks_per_deg
        self.stale_timeout_s = stale_timeout_s
        self.software_max_vel_deg_s = software_max_vel_deg_s
        self.min_limit_deg = min_limit_deg
        self.max_limit_deg = max_limit_deg
        self.stuck_timeout_s = stuck_timeout_s

        # Authority & telemetry state
        self.position_source: PositionSource = PositionSource.UNKNOWN
        self.encoder_available: bool = False
        self.encoder_stale: bool = True
        self.encoder_responsive: bool = False  # True only if real tick dynamics / changes seen
        self.encoder_stuck: bool = False       # True if commanded to move but ticks remain stuck

        # Physical encoder state
        self.actual_yaw_deg: Optional[float] = None
        self.last_known_encoder_deg: Optional[float] = None
        self.last_valid_encoder_time: float = 0.0
        self.encoder_ticks: int = 0
        self._initial_ticks: Optional[int] = None
        self._last_ticks_value: Optional[int] = None
        self._last_ticks_change_time: float = 0.0

        # Software estimation state
        self.estimated_yaw_deg: Optional[float] = None
        self.last_accepted_target_deg: Optional[float] = None
        self.last_estimate_update_time: float = 0.0
        self.last_command_time: float = 0.0

        # Dynamics
        self.velocity_deg_s: float = 0.0
        self._last_vel_calc_time: float = 0.0
        self._last_vel_calc_pos: Optional[float] = None

        # General status
        self.enabled: bool = True
        self.watchdog_healthy: bool = True
        self.fault_code: int = 0

    def on_encoder_feedback(
        self,
        head_ticks: int,
        timestamp: Optional[float] = None,
        dt_s: Optional[float] = None,
        wheel_ticks_l: int = 0,
        wheel_ticks_r: int = 0,
    ) -> None:
        """Called when encoder ticks packet arrives from hardware.

        CRITICAL RULE: Receiving an encoder packet does NOT mean the encoder
        measurement is valid! Continuously receiving head_ticks=0 is NEVER
        automatically accepted as 0.0° real position.
        """
        now = time.monotonic() if timestamp is None else float(timestamp)
        ticks = int(head_ticks)
        self.encoder_ticks = ticks

        # Baseline ticks initialization
        if self._initial_ticks is None:
            self._initial_ticks = ticks
            self._last_ticks_value = ticks
            self._last_ticks_change_time = now
            # If initial ticks is already non-zero, it indicates previous tick activity
            if ticks != 0:
                self.encoder_responsive = True
                self.encoder_stuck = False

        # Detect dynamic tick change from last seen
        if ticks != self._last_ticks_value:
            self._last_ticks_value = ticks
            self._last_ticks_change_time = now
            self.encoder_responsive = True
            self.encoder_stuck = False

        # Check for stuck-at-zero / unresponsive condition:
        # If a movement command was accepted and enough time elapsed,
        # but ticks have not changed from baseline or stay frozen at 0:
        is_command_moving = False
        if self.last_accepted_target_deg is not None:
            current_pos = self.estimated_yaw_deg if self.estimated_yaw_deg is not None else 0.0
            if abs(self.last_accepted_target_deg) > 2.0 or abs(self.last_accepted_target_deg - current_pos) > 2.0:
                is_command_moving = True

        if is_command_moving and (now - self.last_command_time > self.stuck_timeout_s) and not self.encoder_responsive:
            self.encoder_stuck = True

        # If encoder is not responsive or stuck, DO NOT accept as ENCODER authority
        if not self.encoder_responsive or self.encoder_stuck:
            self.encoder_available = False
            self.encoder_stale = True
            self.actual_yaw_deg = None
            if self.last_accepted_target_deg is not None or self.estimated_yaw_deg is not None:
                self.position_source = PositionSource.VIRTUAL_ENCODER
            else:
                self.position_source = PositionSource.UNKNOWN
            return

        # When encoder is responsive and verified:
        deg = round(float(ticks / self.ticks_per_deg), 2)
        if abs(deg) > max(abs(self.min_limit_deg), abs(self.max_limit_deg)):
            self.encoder_available = False
            self.encoder_stale = True
            self.actual_yaw_deg = None
            self.position_source = PositionSource.VIRTUAL_ENCODER
            return

        # Calculate physical velocity if previous measurement exists
        if self.actual_yaw_deg is not None and self.last_valid_encoder_time > 0.0:
            effective_dt = dt_s if dt_s is not None else (now - self.last_valid_encoder_time)
            if effective_dt > 0.001:
                raw_vel = (deg - self.actual_yaw_deg) / effective_dt
                self.velocity_deg_s = round(0.85 * self.velocity_deg_s + 0.15 * raw_vel, 2)

        # VIRTUAL_ENCODER -> ENCODER transition with zero-jump rebase:
        # Physical reality becomes authoritative. Software estimate is rebased to physical deg.
        # Commanded target (last_accepted_target_deg) is preserved; first encoder sample is NOT
        # silently reinterpreted as a new target frame.
        self.actual_yaw_deg = deg
        self.last_known_encoder_deg = deg
        self.last_valid_encoder_time = now
        self.encoder_available = True
        self.encoder_stale = False
        self.position_source = PositionSource.ENCODER

        self.estimated_yaw_deg = deg
        self.last_estimate_update_time = now

    def on_command_accepted(self, target_yaw_deg: float, timestamp: Optional[float] = None) -> None:
        """Called ONLY when a head command has been successfully accepted/transmitted to hardware."""
        now = time.monotonic() if timestamp is None else float(timestamp)
        clamped_target = max(self.min_limit_deg, min(self.max_limit_deg, float(target_yaw_deg)))
        self.last_accepted_target_deg = clamped_target
        self.last_command_time = now

        if self.position_source == PositionSource.UNKNOWN:
            # First accepted command initializes software estimation from 0.0 reference
            self.position_source = PositionSource.VIRTUAL_ENCODER
            self.estimated_yaw_deg = 0.0
            self.last_estimate_update_time = now
            self._update_estimate_step(now)
        elif self.position_source == PositionSource.VIRTUAL_ENCODER:
            if self.estimated_yaw_deg is None:
                self.estimated_yaw_deg = 0.0
            self._update_estimate_step(now)
        elif self.position_source == PositionSource.ENCODER:
            # Physical encoder is running; command is noted for target_position_deg
            self.last_estimate_update_time = now

    def on_command_rejected(self, target_yaw_deg: float, reason: str = "") -> None:
        """Called when a command could not be sent (link down, rejected, etc.).

        Maintains invariant: unaccepted command NEVER causes estimated movement.
        """
        # No change in estimated_yaw_deg or position_source
        pass

    def _update_estimate_step(self, now: float) -> None:
        """Advances software estimate towards last accepted target using software max velocity."""
        if self.estimated_yaw_deg is None or self.last_accepted_target_deg is None:
            return

        dt = max(0.001, min(0.5, now - self.last_estimate_update_time)) if self.last_estimate_update_time > 0.0 else 0.02
        self.last_estimate_update_time = now

        diff = self.last_accepted_target_deg - self.estimated_yaw_deg
        max_step = self.software_max_vel_deg_s * dt

        if abs(diff) <= max_step:
            self.estimated_yaw_deg = self.last_accepted_target_deg
            self.velocity_deg_s = 0.0
        else:
            step = max_step if diff > 0 else -max_step
            self.estimated_yaw_deg += step
            self.velocity_deg_s = round(self.software_max_vel_deg_s if diff > 0 else -self.software_max_vel_deg_s, 2)

    def evaluate(self, timestamp: Optional[float] = None) -> HeadState:
        """Evaluates current state, applies stale timeout, and returns a HeadState snapshot."""
        now = time.monotonic() if timestamp is None else float(timestamp)

        # 1. Check for stuck-at-zero / unresponsive condition during active command
        is_command_moving = False
        if self.last_accepted_target_deg is not None:
            current_pos = self.estimated_yaw_deg if self.estimated_yaw_deg is not None else 0.0
            if abs(self.last_accepted_target_deg) > 2.0 or abs(self.last_accepted_target_deg - current_pos) > 2.0:
                is_command_moving = True

        if is_command_moving and (now - self.last_command_time > self.stuck_timeout_s) and not self.encoder_responsive:
            self.encoder_stuck = True
            self.encoder_available = False
            self.encoder_stale = True
            if self.position_source == PositionSource.ENCODER:
                self.position_source = PositionSource.VIRTUAL_ENCODER
                if self.estimated_yaw_deg is None and self.last_known_encoder_deg is not None:
                    self.estimated_yaw_deg = self.last_known_encoder_deg
                self.last_estimate_update_time = now
            self.actual_yaw_deg = None

        # 2. Evaluate encoder freshness for previously responsive encoder
        if self.encoder_available and self.encoder_responsive:
            if (now - self.last_valid_encoder_time) > self.stale_timeout_s:
                self.encoder_stale = True
                if self.position_source == PositionSource.ENCODER:
                    # ENCODER -> VIRTUAL_ENCODER transition with zero-jump rebase:
                    # Seed virtual estimate with last known physical encoder angle so motion begins seamlessly
                    self.position_source = PositionSource.VIRTUAL_ENCODER
                    self.actual_yaw_deg = None
                    if self.last_known_encoder_deg is not None:
                        self.estimated_yaw_deg = self.last_known_encoder_deg
                    elif self.estimated_yaw_deg is None:
                        self.estimated_yaw_deg = 0.0
                    self.last_estimate_update_time = now

        # 3. Advance software estimate if in VIRTUAL_ENCODER state
        if self.position_source == PositionSource.VIRTUAL_ENCODER:
            self._update_estimate_step(now)

        # 4. Determine moving / at_target indicators
        target_pos = self.last_accepted_target_deg if self.last_accepted_target_deg is not None else 0.0
        is_moving = abs(self.velocity_deg_s) > 1.0

        current_eval_pos = self.actual_yaw_deg if self.position_source == PositionSource.ENCODER else self.estimated_yaw_deg
        if current_eval_pos is not None and self.last_accepted_target_deg is not None:
            at_target = abs(current_eval_pos - target_pos) <= 2.0 and not is_moving
        else:
            at_target = False

        # 5. Centrally resolve sole canonical yaw
        if self.position_source == PositionSource.ENCODER and self.actual_yaw_deg is not None:
            canonical_yaw = float(self.actual_yaw_deg)
        elif self.position_source == PositionSource.VIRTUAL_ENCODER and self.estimated_yaw_deg is not None:
            canonical_yaw = float(self.estimated_yaw_deg)
        else:
            canonical_yaw = None

        # 6. Construct HeadState
        # Invariant: position_deg is ONLY physical encoder angle; NaN if absent/stale/unresponsive
        pos_deg = float(self.actual_yaw_deg) if (self.position_source == PositionSource.ENCODER and self.actual_yaw_deg is not None) else float("nan")

        return HeadState(
            position_source=self.position_source,
            encoder_available=self.encoder_available and self.encoder_responsive,
            encoder_stale=self.encoder_stale,
            actual_yaw_deg=self.actual_yaw_deg,
            estimated_yaw_deg=self.estimated_yaw_deg,
            canonical_yaw_deg=canonical_yaw,
            position_deg=pos_deg,
            velocity_deg_s=float(self.velocity_deg_s),
            target_position_deg=float(target_pos),
            moving=is_moving,
            at_target=at_target,
            enabled=self.enabled,
            watchdog_healthy=self.watchdog_healthy,
            encoder_valid=(self.position_source == PositionSource.ENCODER and not self.encoder_stale and self.encoder_responsive),
            fault_code=self.fault_code,
            timestamp=now,
        )
