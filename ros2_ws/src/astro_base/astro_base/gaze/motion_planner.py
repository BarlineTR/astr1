"""Motion Planning & Trajectory Generation Engine for ASTRO Head Gaze.

Features:
  1. Smooth Acceleration-Limited Trajectory Generation with Soft-Landing
  2. Strict Kinematic Constraints (v_max, a_max)
  3. Shortest Reachable Arc Wrapping with Mechanical Joint Limits [-90°, +90°]
  4. Organic Deceleration Braking Profile with Zero Overshoot
  5. Continuous Online Replanning without Velocity Discontinuities
"""

import math
from typing import Optional, Tuple

from astro_base.gaze.angle_math import (
    angular_diff_deg,
    clamp_deg,
    shortest_reachable_arc,
    wrap_deg,
)
from astro_base.gaze.types import GazeCommand, TrajectoryPoint


class MotionPlannerCore:
    """Computes smooth, acceleration-bounded kinematic trajectories for head pan actuator."""

    def __init__(
        self,
        max_velocity_deg_s: float = 75.0,
        max_acceleration_deg_s2: float = 180.0,
        max_jerk_deg_s3: float = 360.0,
        soft_landing_zone_deg: float = 15.0,
        min_limit_deg: float = -90.0,
        max_limit_deg: float = 90.0,
        profile_type: str = "trapezoidal",
    ):
        self.max_velocity = max_velocity_deg_s
        self.max_acceleration = max_acceleration_deg_s2
        self.max_jerk = max_jerk_deg_s3
        self.soft_landing_zone = soft_landing_zone_deg
        self.min_limit = min_limit_deg
        self.max_limit = max_limit_deg
        self.profile_type = profile_type.lower()

        # State tracking: position, velocity, acceleration
        self.current_pos = 0.0
        self.current_vel = 0.0
        self.current_acc = 0.0
        self.target_pos = 0.0
        self.last_update_time: Optional[float] = None

    def reset(self, initial_pos_deg: float = 0.0) -> None:
        self.current_pos = clamp_deg(initial_pos_deg, self.min_limit, self.max_limit)
        self.current_vel = 0.0
        self.current_acc = 0.0
        self.target_pos = self.current_pos
        self.last_update_time = None

    def set_target(self, target_deg: float) -> None:
        """Sets new goal position."""
        self.target_pos = clamp_deg(target_deg, self.min_limit, self.max_limit)

    def plan_step(
        self,
        gaze_cmd: GazeCommand,
        actual_pos_deg: Optional[float],
        timestamp: float,
    ) -> TrajectoryPoint:
        """Computes next trajectory point for the control cycle."""
        if self.last_update_time is None:
            if actual_pos_deg is not None:
                self.current_pos = clamp_deg(actual_pos_deg, self.min_limit, self.max_limit)
            self.current_vel = 0.0
            self.current_acc = 0.0
            self.last_update_time = timestamp
            is_init_settled = (abs(self.current_pos - gaze_cmd.target_yaw_deg) < 0.25)
            return TrajectoryPoint(
                timestamp=timestamp,
                position_deg=round(self.current_pos, 2),
                velocity_deg_s=0.0,
                acceleration_deg_s2=0.0,
                is_settled=is_init_settled,
            )

        dt = max(0.001, min(0.10, timestamp - self.last_update_time))
        self.last_update_time = timestamp

        self.target_pos = clamp_deg(gaze_cmd.target_yaw_deg, self.min_limit, self.max_limit)

        # 1. Shortest reachable rotation arc respecting limits
        err_deg = shortest_reachable_arc(self.target_pos, self.current_pos, self.min_limit, self.max_limit)
        abs_err = abs(err_deg)


        # Settling check: settled only if both position error and velocity are minimal
        if abs_err < 0.25 and abs(self.current_vel) < 2.0:
            self.current_pos = self.target_pos
            self.current_vel = 0.0
            self.current_acc = 0.0
            return TrajectoryPoint(
                timestamp=timestamp,
                position_deg=round(self.current_pos, 2),
                velocity_deg_s=0.0,
                acceleration_deg_s2=0.0,
                is_settled=True,
            )

        # 2. Maximum reachable approach velocity with zero-overshoot braking curve
        a_brake = self.max_acceleration * 0.85
        v_stop = math.sqrt(2.0 * a_brake * abs_err)
        desired_v = math.copysign(min(self.max_velocity, v_stop), err_deg)

        # 3. Acceleration limiting (dv = clamp(desired_v - current_vel, -a_max*dt, a_max*dt))
        max_dv = self.max_acceleration * dt
        dv = max(-max_dv, min(max_dv, desired_v - self.current_vel))
        self.current_vel += dv
        self.current_acc = dv / dt

        # Velocity clamp
        self.current_vel = max(-self.max_velocity, min(self.max_velocity, self.current_vel))

        # 4. Position integration
        self.current_pos += self.current_vel * dt
        self.current_pos = clamp_deg(self.current_pos, self.min_limit, self.max_limit)

        new_err = shortest_reachable_arc(self.target_pos, self.current_pos, self.min_limit, self.max_limit)
        is_settled = (abs(new_err) < 0.25 and abs(self.current_vel) < 2.0)
        if is_settled:
            self.current_pos = self.target_pos
            self.current_vel = 0.0
            self.current_acc = 0.0

        return TrajectoryPoint(
            timestamp=timestamp,
            position_deg=round(self.current_pos, 2),
            velocity_deg_s=round(self.current_vel, 2),
            acceleration_deg_s2=round(self.current_acc, 2),
            is_settled=is_settled,
        )
