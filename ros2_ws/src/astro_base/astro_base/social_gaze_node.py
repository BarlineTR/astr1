#!/usr/bin/env python3
"""Social Gaze ROS 2 Node for ASTRO Robot Head.


Integrates:
  1. Audio Perception & GCC-PHAT Filtering
  2. 3D Visual Face Tracking & Kalman Estimation
  3. Multimodal Audio-Visual Association & Fusion
  4. Dual-Threshold Target Management & Turn-Taking Arbitration
  5. 9-State Social Gaze FSM & Priority Arbiter
  6. Jerk-Limited S-Curve Motion Planner (50 Hz Control Loop)
  7. Closed-Loop Hardware Safety & Watchdog Monitor
"""

import json
import math
import os
import time
from typing import Dict, List, Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, Float32, Header, Int32, String
from sensor_msgs.msg import JointState

try:
    from astro_base.msg import GazeStatus, HeadState
except ImportError:
    GazeStatus = HeadState = None

from astro_base.gaze.audio_filter import AudioFilterCore
from astro_base.gaze.audio_perception import AudioPerceptionCore
from astro_base.gaze.coordinate_frames import CalibrationConfig, CoordinateTransformer
from astro_base.gaze.gaze_state_machine import SocialGazeFSM
from astro_base.gaze.head_controller import HeadControllerCore
from astro_base.gaze.motion_planner import MotionPlannerCore
from astro_base.gaze.sensor_fusion import AudioVisualFusionCore
from astro_base.gaze.target_manager import TargetManagerCore
from astro_base.gaze.types import (
    AudioObservation,
    FilteredAudioState,
    FusedTarget,
    GazeCommand,
    GazeStateEnum,
    HeadFeedback,
    Modality,
    PrioritySource,
    TargetState,
    TrajectoryPoint,
    VisualObservation,
    VisualTargetTrack,
)
from astro_base.gaze.visual_perception import VisualPerceptionCore
from astro_base.gaze.visual_tracker import VisualTrackerCore


class SocialGazeNode(Node):
    """Authoritative Social Gaze Controller Node for ASTRO Robot."""

    def __init__(self):
        super().__init__("social_gaze_node")

        # -------------------------------------------------------------------------
        # 1. Parameter Declaration & Loading
        # -------------------------------------------------------------------------
        self.declare_parameter("control_rate_hz", 50.0)
        self.declare_parameter("config_file", "")
        self.declare_parameter("calibration_file", "")

        self.declare_parameter("max_velocity_deg_s", 75.0)
        self.declare_parameter("max_acceleration_deg_s2", 180.0)
        self.declare_parameter("max_jerk_deg_s3", 360.0)
        self.declare_parameter("gaze_deadband_deg", 3.0)
        self.declare_parameter("min_attention_dwell_s", 2.50)
        self.declare_parameter("turn_taking_min_dwell_s", 0.80)
        self.declare_parameter("spatial_gate_deg", 25.0)
        self.declare_parameter("idle_saccades_enabled", True)
        self.declare_parameter("self_speech_suppression", True)

        # Load Calibration
        calib_file = self.get_parameter("calibration_file").get_parameter_value().string_value
        if calib_file and os.path.exists(calib_file):
            self.calib = CalibrationConfig.from_yaml_file(calib_file)
            self.get_logger().info(f"Loaded calibration from {calib_file}")
        else:
            self.calib = CalibrationConfig()

        self.transformer = CoordinateTransformer(self.calib)

        # -------------------------------------------------------------------------
        # 2. Pipeline Core Modules Initialization
        # -------------------------------------------------------------------------
        self.audio_perception = AudioPerceptionCore(
            transformer=self.transformer,
            self_speech_suppression_factor=0.15,
        )
        self.audio_filter = AudioFilterCore(
            max_jump_deg=35.0,
            outlier_persistence_count=3,
            kalman_q=0.08,
            kalman_r=0.45,
        )
        self.visual_perception = VisualPerceptionCore(
            transformer=self.transformer,
            min_confidence=0.50,
            direct_gaze_max_yaw_deg=22.0,
        )
        self.visual_tracker = VisualTrackerCore(
            transformer=self.transformer,
            gating_distance_m=0.85,
            coasting_timeout_s=0.70,
        )
        self.fusion = AudioVisualFusionCore(
            spatial_gate_deg=float(self.get_parameter("spatial_gate_deg").value),
            audio_freshness_half_life_s=0.80,
            vision_freshness_half_life_s=1.20,
        )
        self.target_manager = TargetManagerCore(
            acquisition_threshold=0.75,
            hold_threshold=0.40,
            target_lost_timeout_s=1.0,
            min_attention_dwell_s=float(self.get_parameter("min_attention_dwell_s").value),
            turn_taking_min_dwell_s=float(self.get_parameter("turn_taking_min_dwell_s").value),
        )
        self.fsm = SocialGazeFSM(
            deadband_deg=float(self.get_parameter("gaze_deadband_deg").value),
            idle_return_timeout_s=20.0,
            min_attention_dwell_s=float(self.get_parameter("min_attention_dwell_s").value),
            idle_saccades_enabled=bool(self.get_parameter("idle_saccades_enabled").value),
            min_limit_deg=self.calib.head.min_angle_deg,
            max_limit_deg=self.calib.head.max_angle_deg,
        )
        self.planner = MotionPlannerCore(
            max_velocity_deg_s=float(self.get_parameter("max_velocity_deg_s").value),
            max_acceleration_deg_s2=float(self.get_parameter("max_acceleration_deg_s2").value),
            max_jerk_deg_s3=float(self.get_parameter("max_jerk_deg_s3").value),
            min_limit_deg=self.calib.head.min_angle_deg,
            max_limit_deg=self.calib.head.max_angle_deg,
        )
        self.head_ctrl = HeadControllerCore(
            ticks_per_deg=self.calib.head.ticks_per_deg,
            min_limit_deg=self.calib.head.min_angle_deg,
            max_limit_deg=self.calib.head.max_angle_deg,
        )

        # -------------------------------------------------------------------------
        # 3. Inter-Module State Variables
        # -------------------------------------------------------------------------
        self.latest_audio_state: Optional[FilteredAudioState] = None
        self.latest_visual_tracks: List[VisualTargetTrack] = []
        self.actual_head_yaw_deg: float = 0.0
        self.actual_head_vel_deg_s: float = 0.0
        self.is_robot_speaking: bool = False

        # -------------------------------------------------------------------------
        # 4. ROS 2 Publishers & Subscriptions
        # -------------------------------------------------------------------------
        qos_best_effort = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)

        # Actuator command topic
        self.pub_head_cmd_pos = self.create_publisher(Float32, "/head/cmd_pos", 10)

        # Typed Gaze Status publisher
        if GazeStatus is not None:
            self.pub_gaze_state = self.create_publisher(GazeStatus, "/gaze/state", 10)
        else:
            self.pub_gaze_state = None

        # Diagnostics & Visualization topics
        self.pub_gaze_debug = self.create_publisher(String, "/gaze/debug", 10)
        self.pub_active_target = self.create_publisher(String, "/gaze/active_target", 10)


        # Subscriptions
        if HeadState is not None:
            self.create_subscription(HeadState, "/head/state", self._on_head_state, 10)
        self.create_subscription(JointState, "/joint_states", self._on_joint_states, qos_best_effort)
        self.create_subscription(Float32, "/audio/doa", self._on_doa_deg, 10)
        self.create_subscription(Float32, "/audio/doa_deg", self._on_doa_deg, 10)
        self.create_subscription(Int32, "/audio/doa_raw", self._on_doa_raw, 10)
        self.create_subscription(String, "/vision/detections_json", self._on_vision_json, 10)
        self.create_subscription(String, "/vision/faces", self._on_vision_json, 10)
        self.create_subscription(String, "/behavior/gesture", self._on_gesture, 10)
        self.create_subscription(Float32, "/behavior/gaze_intent", self._on_gaze_intent, 10)
        self.create_subscription(Float32, "/head/target_yaw", self._on_gaze_intent, 10)
        self.create_subscription(Bool, "/robot/is_speaking", self._on_speaking_status, 10)
        self.create_subscription(Bool, "/audio/playback_active", self._on_speaking_status, 10)
        self.create_subscription(String, "/robot/emotion", self._on_emotion, 10)
        self.create_subscription(Bool, "/safety/emergency_stop", self._on_emergency_stop, 10)
        self.create_subscription(Bool, "/system/sleep", self._on_sleep_mode, 10)

        # 50 Hz Control Loop Timer
        rate_hz = float(self.get_parameter("control_rate_hz").value)
        timer_period_s = 1.0 / max(1.0, rate_hz)
        self.timer = self.create_timer(timer_period_s, self._control_cycle)

        self.get_logger().info(f"SocialGazeNode initialized at {rate_hz:.1f} Hz (Typed GazeStatus & HeadState enabled)")

    # =========================================================================
    # Callbacks
    # =========================================================================

    def _on_head_state(self, msg) -> None:
        """Reads real encoder position and velocity from HeadState message."""
        if hasattr(msg, "position_deg") and not math.isnan(msg.position_deg):
            self.actual_head_yaw_deg = float(msg.position_deg)
        if hasattr(msg, "velocity_deg_s") and not math.isnan(msg.velocity_deg_s):
            self.actual_head_vel_deg_s = float(msg.velocity_deg_s)

    def _on_joint_states(self, msg: JointState) -> None:
        """Fallback reader for head_yaw_joint actual position and velocity."""
        if "head_yaw_joint" in msg.name:
            idx = msg.name.index("head_yaw_joint")
            pos_val = msg.position[idx]
            if not math.isnan(pos_val):
                self.actual_head_yaw_deg = math.degrees(pos_val)
            if len(msg.velocity) > idx:
                vel_val = msg.velocity[idx]
                if not math.isnan(vel_val):
                    self.actual_head_vel_deg_s = math.degrees(vel_val)

    def _on_doa_raw(self, msg: Int32) -> None:
        """Processes raw integer DOA from ReSpeaker firmware."""
        t = time.monotonic()
        obs = self.audio_perception.process_raw_doa(
            raw_doa_deg=float(msg.data),
            timestamp=t,
            actual_head_yaw_deg=self.actual_head_yaw_deg,
            is_robot_speaking=self.is_robot_speaking,
        )
        self.latest_audio_state = self.audio_filter.filter_observation(
            obs=obs,
            head_velocity_deg_s=self.actual_head_vel_deg_s,
        )

    def _on_doa_deg(self, msg: Float32) -> None:
        """Processes float DOA angle in degrees."""
        t = time.monotonic()
        obs = self.audio_perception.process_raw_doa(
            raw_doa_deg=float(msg.data),
            timestamp=t,
            actual_head_yaw_deg=self.actual_head_yaw_deg,
            is_robot_speaking=self.is_robot_speaking,
        )
        self.latest_audio_state = self.audio_filter.filter_observation(
            obs=obs,
            head_velocity_deg_s=self.actual_head_vel_deg_s,
        )

    def _on_vision_json(self, msg: String) -> None:
        """Processes JSON array of detected faces from OAK-D Lite vision pipeline."""
        t = time.monotonic()
        try:
            detections = json.loads(msg.data)
            obs_list: List[VisualObservation] = []
            for d in detections:
                obs = self.visual_perception.process_detection(
                    x=int(d.get("x", 0)),
                    y=int(d.get("y", 0)),
                    w=int(d.get("w", 50)),
                    h=int(d.get("h", 50)),
                    depth_m=float(d.get("depth_m", 1.5)),
                    timestamp=t,
                    actual_head_yaw_deg=self.actual_head_yaw_deg,
                    confidence=float(d.get("confidence", 0.8)),
                    eyes_visible=bool(d.get("eyes_visible", True)),
                    head_yaw_deg=float(d.get("head_yaw_deg", 0.0)),
                    emotion=str(d.get("emotion", "neutral")),
                    person_name=d.get("name"),
                    is_known=bool(d.get("is_known", False)),
                )
                obs_list.append(obs)

            self.latest_visual_tracks = self.visual_tracker.update(
                observations=obs_list,
                timestamp=t,
                actual_head_yaw_deg=self.actual_head_yaw_deg,
            )
        except Exception as exc:
            self.get_logger().error(f"Error parsing vision JSON: {exc}")

    def _on_gesture(self, msg: String) -> None:
        t = time.monotonic()
        ok = self.fsm.trigger_gesture(msg.data, timestamp=t)
        if ok:
            self.get_logger().info(f"Triggered gesture: {msg.data}")

    def _on_gaze_intent(self, msg: Float32) -> None:
        t = time.monotonic()
        self.fsm.set_dialogue_target(yaw_deg=msg.data, duration_s=3.0, timestamp=t)

    def _on_speaking_status(self, msg: Bool) -> None:
        self.is_robot_speaking = msg.data

    def _on_emergency_stop(self, msg: Bool) -> None:
        self.fsm.set_safety_lock(msg.data)

    def _on_sleep_mode(self, msg: Bool) -> None:
        self.fsm.set_sleep_mode(msg.data)

    def _on_emotion(self, msg: String) -> None:
        emo = str(msg.data).strip().lower()
        if emo in ("sleeping", "sleep", "deep_idle"):
            self.fsm.set_sleep_mode(True)
        else:
            self.fsm.set_sleep_mode(False)

    # =========================================================================
    # 50 Hz Synchronous Control Cycle
    # =========================================================================

    def _control_cycle(self) -> None:
        t = time.monotonic()

        # 1. Multimodal Sensor Fusion
        fused_targets = self.fusion.fuse(
            audio_state=self.latest_audio_state,
            visual_tracks=self.latest_visual_tracks,
            timestamp=t,
        )

        # 2. Target Management & Turn-Taking Arbitration
        target_state = self.target_manager.update(
            fused_targets=fused_targets,
            timestamp=t,
        )

        # 3. Behavioral Social Gaze FSM & Priority Arbitration with True Velocity Feedback
        gaze_cmd = self.fsm.update(
            target_state=target_state,
            actual_head_yaw_deg=self.actual_head_yaw_deg,
            timestamp=t,
            actual_head_vel_deg_s=self.actual_head_vel_deg_s,
        )

        # 4. Kinematic Motion Planning & Trajectory Generation
        traj_point = self.planner.plan_step(
            gaze_cmd=gaze_cmd,
            actual_pos_deg=self.actual_head_yaw_deg,
            timestamp=t,
        )

        # 5. Actuator Command Publishing
        cmd_msg = Float32()
        cmd_msg.data = float(traj_point.position_deg)
        self.pub_head_cmd_pos.publish(cmd_msg)

        # 6. Publish Typed GazeStatus Message
        if self.pub_gaze_state is not None:
            status_msg = GazeStatus()
            status_msg.header.stamp = self.get_clock().now().to_msg()
            status_msg.header.frame_id = "base_link"

            state_enum_map = {
                GazeStateEnum.IDLE: 0,
                GazeStateEnum.SEARCHING: 1,
                GazeStateEnum.AUDIO_ACQUIRE: 2,
                GazeStateEnum.ORIENTING: 3,
                GazeStateEnum.VISUAL_ACQUIRE: 4,
                GazeStateEnum.TRACKING: 5,
                GazeStateEnum.HOLD: 6,
                GazeStateEnum.TARGET_LOST: 7,
                GazeStateEnum.RETURNING: 8,
            }
            priority_enum_map = {
                PrioritySource.IDLE: 0,
                PrioritySource.VISUAL_PERSON: 1,
                PrioritySource.ACTIVE_SPEAKER: 2,
                PrioritySource.DIALOGUE: 3,
                PrioritySource.GESTURE: 4,
                PrioritySource.SAFETY: 5,
            }
            status_msg.state = state_enum_map.get(gaze_cmd.gaze_state, 0)
            status_msg.priority = priority_enum_map.get(gaze_cmd.priority_source, 0)
            status_msg.desired_yaw_deg = float(gaze_cmd.target_yaw_deg)
            status_msg.planned_yaw_deg = float(traj_point.position_deg)
            status_msg.actual_yaw_deg = float(self.actual_head_yaw_deg)
            status_msg.target_confidence = float(gaze_cmd.confidence)
            status_msg.target_valid = bool(gaze_cmd.confidence > 0.10)
            status_msg.motion_active = bool(abs(traj_point.velocity_deg_s) > 1.0 or abs(self.actual_head_vel_deg_s) > 1.0)
            status_msg.at_target = bool(self.fsm.at_target and traj_point.is_settled)
            status_msg.active_target_id = str(gaze_cmd.active_target_id or "")
            self.pub_gaze_state.publish(status_msg)

        # 7. Publish JSON Debug Telemetry
        state_diag = {

            "timestamp": t,
            "fsm_state": gaze_cmd.gaze_state.value,
            "priority": gaze_cmd.priority_source.value,
            "desired_yaw_deg": gaze_cmd.target_yaw_deg,
            "planned_pos_deg": traj_point.position_deg,
            "planned_vel_deg_s": traj_point.velocity_deg_s,
            "actual_pos_deg": self.actual_head_yaw_deg,
            "actual_vel_deg_s": self.actual_head_vel_deg_s,
            "at_target": self.fsm.at_target,
            "active_target_id": gaze_cmd.active_target_id,
            "is_speaking": self.is_robot_speaking,
            "is_settled": traj_point.is_settled,
        }
        msg_str = String()
        msg_str.data = json.dumps(state_diag)
        self.pub_gaze_debug.publish(msg_str)


def main(args=None):
    rclpy.init(args=args)
    node = SocialGazeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

