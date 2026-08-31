"""Unit tests for Motion Planner & Trajectory Kinematics."""

import unittest
from astro_base.gaze.motion_planner import MotionPlannerCore
from astro_base.gaze.types import GazeCommand, GazeStateEnum, PrioritySource


class TestMotionPlannerKinematics(unittest.TestCase):
    def setUp(self):
        self.planner = MotionPlannerCore(
            max_velocity_deg_s=75.0,
            max_acceleration_deg_s2=180.0,
            max_jerk_deg_s3=360.0,
            soft_landing_zone_deg=12.0,
            min_limit_deg=-90.0,
            max_limit_deg=90.0,
            profile_type="s_curve",
        )

    def test_trajectory_obeys_velocity_and_acceleration_limits(self):
        """Tests that a 0° -> 60° saccade trajectory strictly adheres to v_max and a_max."""
        cmd = GazeCommand(target_yaw_deg=60.0, timestamp=1.0)
        self.planner.reset(initial_pos_deg=0.0)

        t = 1.0
        dt = 0.02  # 50 Hz control loop
        positions = []
        velocities = []
        accelerations = []

        for _ in range(150):  # Simulate 3.0 seconds
            pt = self.planner.plan_step(cmd, actual_pos_deg=None, timestamp=t)
            positions.append(pt.position_deg)
            velocities.append(pt.velocity_deg_s)
            accelerations.append(pt.acceleration_deg_s2)

            # Strict kinematic limits assertions
            self.assertLessEqual(abs(pt.velocity_deg_s), 75.0 + 0.1)
            self.assertLessEqual(abs(pt.acceleration_deg_s2), 180.0 + 1.0)

            if pt.is_settled:
                break
            t += dt

        # Final position must be settled at 60.0°
        self.assertAlmostEqual(positions[-1], 60.0, delta=0.25)
        self.assertAlmostEqual(velocities[-1], 0.0, delta=0.5)

    def test_mechanical_limit_clamping(self):
        """Tests that commanding an out-of-bounds target (120°) clamps smoothly to +90°."""
        cmd = GazeCommand(target_yaw_deg=120.0, timestamp=1.0)
        self.planner.reset(initial_pos_deg=0.0)

        t = 1.0
        for _ in range(150):
            pt = self.planner.plan_step(cmd, actual_pos_deg=None, timestamp=t)
            self.assertLessEqual(pt.position_deg, 90.0)
            t += 0.02
            if pt.is_settled:
                break

        self.assertAlmostEqual(self.planner.current_pos, 90.0, delta=0.25)

    def test_online_replanning_smooth_transition(self):
        """Tests changing target mid-flight (from +45° to -45°) reverses smoothly without velocity spikes."""
        cmd1 = GazeCommand(target_yaw_deg=45.0, timestamp=1.0)
        self.planner.reset(initial_pos_deg=0.0)

        t = 1.0
        # Run towards +45° for ~0.30s (head reaches velocity ~25°/s)
        for _ in range(15):
            self.planner.plan_step(cmd1, actual_pos_deg=None, timestamp=t)
            t += 0.02



        mid_vel = self.planner.current_vel
        self.assertGreater(mid_vel, 10.0)

        # Mid-flight target change to -45°
        cmd2 = GazeCommand(target_yaw_deg=-45.0, timestamp=t)
        prev_vel = mid_vel
        for _ in range(150):
            pt = self.planner.plan_step(cmd2, actual_pos_deg=None, timestamp=t)
            # Ensure velocity change per step is bounded by acceleration limit
            dv = abs(pt.velocity_deg_s - prev_vel)
            max_allowed_dv = (180.0 * 0.02) + 0.5  # a_max * dt + margin
            self.assertLessEqual(dv, max_allowed_dv)
            prev_vel = pt.velocity_deg_s
            t += 0.02
            if pt.is_settled:
                break


        self.assertAlmostEqual(self.planner.current_pos, -45.0, delta=0.25)


if __name__ == "__main__":
    unittest.main()
