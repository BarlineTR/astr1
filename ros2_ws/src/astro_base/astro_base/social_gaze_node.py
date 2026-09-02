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

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from std_msgs.msg import Bool, Float32, Header, Int32, String
    from sensor_msgs.msg import JointState
    try:
        from astro_base.msg import GazeStatus, HeadCmd, HeadState
    except ImportError:
        GazeStatus = HeadCmd = HeadState = None
except ImportError:
    class _MockRclpy:
        @staticmethod
        def ok(): return True
        @staticmethod
        def shutdown(): pass
        @staticmethod
        def init(*args, **kwargs): pass
    rclpy = _MockRclpy()

    class _MockParam:
        def __init__(self, val): self.value = val
        def get_parameter_value(self):
            class _Val:
                def __init__(self, v):
                    self.string_value = str(v) if v is not None else ""
                    self.double_value = float(v) if isinstance(v, (int, float)) else 0.0
                    self.integer_value = int(v) if isinstance(v, (int, float)) else 0
                    self.bool_value = bool(v)
            return _Val(self.value)

    class _MockPublisher:
        """Captures published messages so headless tests can assert on node output."""
        def __init__(self, topic): self.topic = topic; self.last_msg = None; self.count = 0
        def publish(self, msg): self.last_msg = msg; self.count += 1

    class _MockClock:
        def now(self):
            class _Time:
                def to_msg(self): return None
            return _Time()

    class Node:
        def __init__(self, *args, **kwargs):
            self._params = {}
        def create_publisher(self, msg_type, topic, *args, **kwargs):
            return _MockPublisher(topic)
        def create_subscription(self, *args, **kwargs): return None
        def create_timer(self, *args, **kwargs): return None
        def get_clock(self): return _MockClock()
        def get_logger(self):
            import logging
            return logging.getLogger("SocialGazeNode")
        def declare_parameter(self, name, value=None, *args, **kwargs):
            # Remembering the declared default is what lets the headless harness
            # exercise the node's real thresholds instead of empty-string stubs.
            self._params[name] = value
            return _MockParam(value)
        def get_parameter(self, name):
            return _MockParam(self._params.get(name))
    class QoSProfile:
        def __init__(self, *args, **kwargs): pass

    class ReliabilityPolicy:
        BEST_EFFORT = 0
        RELIABLE = 1

    class _MockMsg:
        """Assignable stand-in for std_msgs/sensor_msgs types."""
        def __init__(self, data=None, **kwargs):
            self.data = data
            for key, val in kwargs.items():
                setattr(self, key, val)

    Bool = Float32 = Header = Int32 = String = JointState = _MockMsg
    GazeStatus = HeadCmd = HeadState = None

from astro_base.gaze.audio_filter import AudioFilterCore
from astro_base.gaze.audio_perception import AudioPerceptionCore
from astro_base.gaze.coordinate_frames import CalibrationConfig, CoordinateTransformer
from astro_base.gaze.gaze_state_machine import SocialGazeFSM
from astro_base.gaze.head_controller import HeadControllerCore
from astro_base.gaze.motion_planner import MotionPlannerCore
from astro_base.gaze.sensor_fusion import AudioVisualFusionCore
from astro_base.gaze.spatial_memory import EpistemicSpatialMemory
from astro_base.gaze.target_manager import TargetManagerCore
from astro_base.gaze.types import (
    ActuatorStateEnum,
    AudioMeasurement,
    AudioObservation,
    ExplicitGazeIntent,
    FilteredAudioState,
    FusedTarget,
    GazeCommand,
    GazeStateEnum,
    HeadFeedback,
    Modality,
    PrioritySource,
    TargetSelectorType,
    TargetState,
    TrajectoryPoint,
    VisualMeasurement,
    VisualObservation,
    VisualTargetTrack,
)
from astro_base.gaze.visual_perception import VisualPerceptionCore
from astro_base.gaze.visual_tracker import VisualTrackerCore


# Credited to a detection whose publisher reports no confidence of its own.
# It has to clear the target manager's 0.40 hold threshold — an unscored person is
# still a person, and dropping them would be worse than the bug — while staying
# under the 0.75 acquisition threshold, so a lone unscored frame cannot seize the
# head. Corroboration (a detector score, or speech from the same bearing) is what
# lifts such a candidate to active target.
UNSCORED_DETECTION_CONFIDENCE = 0.65


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
        self.declare_parameter("idle_saccades_enabled", False)
        self.declare_parameter("self_speech_suppression", True)

        # Load Calibration
        calib_file = self.get_parameter("calibration_file").get_parameter_value().string_value
        if calib_file and os.path.exists(calib_file):
            self.calib = CalibrationConfig.from_yaml_file(calib_file)
            self.get_logger().info(f"Loaded calibration from {calib_file}")
        else:
            self.calib = CalibrationConfig()

        self.transformer = CoordinateTransformer(self.calib)

        # Epistemic Situational Spatial Memory
        self.spatial_memory = EpistemicSpatialMemory()

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
            spatial_memory=self.spatial_memory,
        )
        self.target_manager = TargetManagerCore(
            acquisition_threshold=0.75,
            hold_threshold=0.40,
            target_lost_timeout_s=2.5,
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
            spatial_memory=self.spatial_memory,
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
        # Last head POSE yaw reported on /vision/head_yaw (see _on_vision_head_yaw).
        self.latest_person_head_yaw_deg: float = 0.0

        # -------------------------------------------------------------------------
        # 4. ROS 2 Publishers & Subscriptions
        # -------------------------------------------------------------------------
        qos_best_effort = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)

        # Canonical Actuator Command Publisher (/head/command -> HeadCmd)
        if HeadCmd is not None:
            self.pub_head_command = self.create_publisher(HeadCmd, "/head/command", 10)
        else:
            self.pub_head_command = None
        # Compatibility topic (/head/cmd_pos -> Float32)
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
        self.create_subscription(Float32, "/vision/head_yaw", self._on_vision_head_yaw, 10)
        self.create_subscription(String, "/behavior/gesture", self._on_gesture, 10)
        self.create_subscription(Float32, "/behavior/gaze_intent", self._on_gaze_intent, 10)
        self.create_subscription(Float32, "/head/target_yaw", self._on_gaze_intent, 10)
        self.create_subscription(String, "/behavior/explicit_gaze", self._on_explicit_gaze, 10)
        self.create_subscription(Bool, "/robot/is_speaking", self._on_speaking_status, 10)
        self.create_subscription(Bool, "/audio/playback_active", self._on_speaking_status, 10)
        self.create_subscription(String, "/robot/emotion", self._on_emotion, 10)
        self.create_subscription(Bool, "/safety/emergency_stop", self._on_emergency_stop, 10)
        self.create_subscription(Bool, "/system/sleep", self._on_sleep_mode, 10)

        # 50 Hz Control Loop Timer
        rate_hz = float(self.get_parameter("control_rate_hz").value)
        timer_period_s = 1.0 / max(1.0, rate_hz)
        self.timer = self.create_timer(timer_period_s, self._control_cycle)

        self.get_logger().info(f"SocialGazeNode initialized at {rate_hz:.1f} Hz (AttentionArbiter enabled)")

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
        raw_val = float(msg.data)
        obs = self.audio_perception.process_raw_doa(
            raw_doa_deg=raw_val,
            timestamp=t,
            actual_head_yaw_deg=self.actual_head_yaw_deg,
            is_robot_speaking=self.is_robot_speaking,
        )
        if not obs.valid:
            self.get_logger().info(
                f"[AUDIO REJECT] raw_angle={raw_val:+.1f}° rel_bearing={obs.relative_azimuth_deg:+.1f}° "
                f"confidence={obs.confidence:.2f} reason=OUT_OF_CONVERSATIONAL_FOV target_created=False "
                f"attention_owner={self.fsm.active_priority.value}"
            )
        else:
            self.get_logger().debug(
                f"[AUDIO ACCEPT] raw_angle={raw_val:+.1f}° rel_bearing={obs.relative_azimuth_deg:+.1f}° "
                f"confidence={obs.confidence:.2f} body_yaw={obs.body_azimuth_deg:+.1f}°"
            )

        self.latest_audio_state = self.audio_filter.filter_observation(
            obs=obs,
            head_velocity_deg_s=self.actual_head_vel_deg_s,
        )

    def _on_vision_head_yaw(self, msg: Float32) -> None:
        """Records the observed person's head POSE yaw — not a bearing to them.

        Every astro_vision publisher fills this topic from `_estimate_head_yaw()`,
        which measures how far the eye midpoint sits from the centre of the face
        ROI: it answers "which way is this person facing", never "where are they".
        Feeding it to the tracker as a camera azimuth fabricated a target out of
        thin air — and since the detectors emit a literal 45.0 whenever they fail
        to find eyes, a lost blink threw the head 45 degrees off to the side.

        Bearings come from /vision/faces alone. This value is kept only as the
        eye-contact cue for detections that carry no per-face yaw of their own.
        """
        self.latest_person_head_yaw_deg = float(msg.data)

    def _on_vision_json(self, msg: String) -> None:
        """Processes JSON array of detected faces from OAK-D Lite vision pipeline."""
        t = time.monotonic()
        try:
            raw_data = json.loads(msg.data)
            if isinstance(raw_data, dict):
                detections = raw_data.get("faces", [])
            elif isinstance(raw_data, list):
                detections = raw_data
            else:
                detections = []

            obs_list: List[VisualObservation] = []
            for d in detections:
                w_val = int(d.get("w", d.get("width", 50)))
                h_val = int(d.get("h", d.get("height", 50)))
                depth_val = float(d.get("depth_m", d.get("distance_m", 1.5)))
                recog_name = d.get("name", d.get("recognized_name"))
                is_known_val = bool(d.get("is_known", recog_name is not None))
                head_yaw_val = float(d.get("yaw_deg", d.get("head_yaw_deg", self.latest_person_head_yaw_deg)))
                eyes_vis = bool(d.get("eyes_visible", d.get("looking_at_robot", True)))
                cam_az_val = d.get("camera_azimuth_deg", d.get("cam_azimuth_deg"))
                if cam_az_val is not None:
                    cam_az_val = float(cam_az_val)
                frame_w_val = int(d.get("frame_width", d.get("frame_w", 640)))
                frame_h_val = int(d.get("frame_height", d.get("frame_h", 480)))

                obs = self.visual_perception.process_detection(
                    x=int(d.get("x", 0)),
                    y=int(d.get("y", 0)),
                    w=w_val,
                    h=h_val,
                    depth_m=depth_val,
                    timestamp=t,
                    actual_head_yaw_deg=self.actual_head_yaw_deg,
                    frame_width=frame_w_val,
                    frame_height=frame_h_val,
                    confidence=float(d.get("confidence", UNSCORED_DETECTION_CONFIDENCE)),
                    eyes_visible=eyes_vis,
                    head_yaw_deg=head_yaw_val,
                    emotion=str(d.get("emotion", "neutral")),
                    person_name=recog_name,
                    is_known=is_known_val,
                    cam_azimuth_deg=cam_az_val,
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

    def _on_explicit_gaze(self, msg: String) -> None:
        """Handles explicit user gaze command (e.g. 'Astro bana dön')."""
        t = time.monotonic()
        text = str(msg.data).strip().lower()
        selector = TargetSelectorType.CURRENT_SPEAKER
        target_yaw: Optional[float] = None

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                sel_str = data.get("selector", "CURRENT_SPEAKER")
                selector = TargetSelectorType(sel_str)
                target_yaw = data.get("target_yaw_deg")
        except Exception:
            pass

        intent = ExplicitGazeIntent(
            selector=selector,
            target_yaw_deg=target_yaw,
            confidence=1.0,
            timestamp=t,
            expiry_time=t + 4.0,
            valid=True,
            reason=f"EXPLICIT_COMMAND_{text}",
        )
        self.fsm.set_explicit_gaze_intent(intent)
        self.get_logger().info(f"Explicit gaze intent received: selector={selector.value}, reason={intent.reason}")

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

        # 1. Multimodal Sensor Fusion (Passive Measurements -> Fused Targets)
        fused_targets = self.fusion.fuse(
            audio_state=self.latest_audio_state,
            visual_tracks=self.latest_visual_tracks,
            timestamp=t,
        )

        # 2. Target Management (Candidate Targets, Track Continuity, Hysteresis)
        target_state = self.target_manager.update(
            fused_targets=fused_targets,
            timestamp=t,
        )

        # Auto-wake social gaze from sleep mode when a person is detected or speaking
        if target_state.active_target is not None and self.fsm.is_sleeping and not self.fsm.safety_lock:
            self.fsm.set_sleep_mode(False)

        # 3. Social Gaze FSM & Attention Arbitration
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

        # 5. Actuator Command Publishing (Direct Authoritative Goal Setpoint to Arduino PID)
        target_goal_deg = float(gaze_cmd.target_yaw_deg)
        if self.pub_head_command is not None:
            hcmd = HeadCmd()
            hcmd.angle_deg = target_goal_deg
            self.pub_head_command.publish(hcmd)

        cmd_msg = Float32()
        cmd_msg.data = target_goal_deg
        self.pub_head_cmd_pos.publish(cmd_msg)

        # 6. Lifecycle Purging on IDLE (Failure 4)
        if self.fsm.state == GazeStateEnum.IDLE and not self.latest_visual_tracks and not (self.latest_audio_state and self.latest_audio_state.valid):
            self.target_manager.reset_lifecycle()

        # 7. TARGET_BIRTH Telemetry Dispatch (Failure 2 & 10)
        if self.target_manager.last_target_birth is not None:
            tb = self.target_manager.last_target_birth
            if tb.get("source") == "AUDIO":
                self.audio_perception.counters.audio_target_births += 1
            tb_msg = String()
            tb_msg.data = json.dumps(tb)
            self.pub_active_target.publish(tb_msg)
            self.get_logger().info(
                f"🎯 [TARGET_BIRTH] id={tb['target_id']} source={tb['source']} "
                f"bearing={tb['bearing']:+.1f}° conf={tb['confidence']:.2f} reason={tb['reason']}"
            )
            self.target_manager.last_target_birth = None

        # 8. Separate Error Metrics Calculation (Failure 7)
        face_bearing_deg = self.latest_visual_tracks[0].body_azimuth_deg if self.latest_visual_tracks else None
        face_to_desired_error_deg = round(float(face_bearing_deg - gaze_cmd.target_yaw_deg), 2) if face_bearing_deg is not None else 0.0
        desired_to_actual_error_deg = round(float(gaze_cmd.target_yaw_deg - self.actual_head_yaw_deg), 2)
        actuator_state_val = "MOVING" if (abs(self.actual_head_vel_deg_s) > 2.0 or abs(desired_to_actual_error_deg) > 2.0) else "SETTLED"

        audio_age_s = round(float(t - self.latest_audio_state.timestamp), 2) if self.latest_audio_state else 999.0
        visual_age_s = round(float(t - self.latest_visual_tracks[0].last_seen_time), 2) if self.latest_visual_tracks else 999.0

        target_identity_correctness = bool(gaze_cmd.active_target_id is not None and target_state.active_target is not None and gaze_cmd.active_target_id == target_state.active_target.target_id)
        attention_owner_correctness = bool(gaze_cmd.priority_source != PrioritySource.IDLE or target_state.active_target is None)

        # 9. Publish Typed GazeStatus Message
        if self.pub_gaze_state is not None:
            status_msg = GazeStatus()
            status_msg.header.stamp = self.get_clock().now().to_msg()
            status_msg.header.frame_id = "base_link"

            state_enum_map = {
                GazeStateEnum.IDLE: 0,
                GazeStateEnum.SEARCHING: 1,
                GazeStateEnum.ACQUIRING: 2,
                GazeStateEnum.ORIENTING: 3,
                GazeStateEnum.TRACKING: 4,
                GazeStateEnum.HOLDING_ATTENTION: 5,
                GazeStateEnum.TARGET_LOST: 6,
                GazeStateEnum.RECOVERING: 7,
            }
            priority_enum_map = {
                PrioritySource.IDLE: 0,
                PrioritySource.VISUAL_TRACKING: 1,
                PrioritySource.ACTIVE_SPEAKER: 2,
                PrioritySource.GESTURE_INTENT: 3,
                PrioritySource.DIRECT_DIALOGUE_INTENT: 4,
                PrioritySource.EXPLICIT_USER_GAZE: 5,
                PrioritySource.EMERGENCY_STOP: 6,
            }
            status_msg.state = state_enum_map.get(gaze_cmd.gaze_state, 0)
            status_msg.priority = priority_enum_map.get(gaze_cmd.priority_source, 0)
            status_msg.desired_yaw_deg = float(gaze_cmd.target_yaw_deg)
            status_msg.planned_yaw_deg = float(traj_point.position_deg)
            status_msg.actual_yaw_deg = float(self.actual_head_yaw_deg)
            status_msg.target_confidence = float(gaze_cmd.confidence)
            status_msg.target_valid = bool(gaze_cmd.confidence > 0.10)
            status_msg.motion_active = bool(actuator_state_val == "MOVING")
            status_msg.at_target = bool(self.fsm.at_target and traj_point.is_settled)
            status_msg.active_target_id = str(gaze_cmd.active_target_id or "")
            self.pub_gaze_state.publish(status_msg)

        # 10. Publish JSON Debug Telemetry
        state_diag = {
            "timestamp": round(t, 3),
            "gaze_state": gaze_cmd.gaze_state.value,
            "actuator_state": actuator_state_val,
            "attention_owner": gaze_cmd.priority_source.value,
            "attention_priority": gaze_cmd.priority_source.value,
            "attention_reason": self.fsm.last_decision.reason if self.fsm.last_decision else "NONE",
            "active_target_id": gaze_cmd.active_target_id,
            "target_confidence": round(gaze_cmd.confidence, 2),
            "desired_yaw_deg": round(gaze_cmd.target_yaw_deg, 2),
            "planned_yaw_deg": round(traj_point.position_deg, 2),
            "actual_yaw_deg": round(self.actual_head_yaw_deg, 2),
            "face_to_desired_error_deg": face_to_desired_error_deg,
            "desired_to_actual_error_deg": desired_to_actual_error_deg,
            "target_identity_correctness": target_identity_correctness,
            "attention_owner_correctness": attention_owner_correctness,
            "audio_valid": bool(self.latest_audio_state.valid) if self.latest_audio_state else False,
            "audio_age_s": audio_age_s,
            "visual_valid": bool(self.latest_visual_tracks[0].confidence > 0.4) if self.latest_visual_tracks else False,
            "visual_age_s": visual_age_s,
            "audio_counters": {
                "raw": self.audio_perception.counters.raw_audio_events,
                "accepted": self.audio_perception.counters.accepted_audio_events,
                "rejected": self.audio_perception.counters.rejected_audio_events,
                "invalid_angle": self.audio_perception.counters.invalid_angle_events,
                "stale": self.audio_perception.counters.stale_audio_events,
                "births": self.audio_perception.counters.audio_target_births,
            },
            "at_target": self.fsm.at_target,
            "is_speaking": self.is_robot_speaking,
            "hold_enter_reason": getattr(self.fsm, "hold_enter_reason", "NONE"),
            "hold_exit_reason": getattr(self.fsm, "hold_exit_reason", "NONE"),
            "last_transition_reason": getattr(self.fsm, "last_transition_reason", "NONE"),
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

