#!/usr/bin/env python3
"""Thin ROS 2 Transport Wrapper for Standalone 2e0b70c Gaze Engine.

Architecture:
  ONE CAMERA FRAME -> ONE DETECTION -> ONE GAZE ENGINE STEP -> ONE HEAD TARGET

Strict Invariants:
1. Gaze decisions (face tracking, target selection, gaze angle, coasting,
   reacquisition) are made SOLELY by the golden standalone runtime from 2e0b70c.
2. ROS 2 provides only transport (camera input, encoder feedback, command dispatch).
3. 50Hz keepalive timer only republishes last target yaw to feed the MCU watchdog;
   it never steps the tracker or alters visual state.
4. /head/state is the sole authoritative feedback source.
"""

import collections
import json
import math
import os
import sys
import time
from typing import Any, List, Optional, Sequence, Tuple
import numpy as np

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import JointState
    from std_msgs.msg import Bool, Float32, String
    try:
        from astro_base.msg import GazeStatus, HeadCmd, HeadState
    except ImportError:
        try:
            from astro_interfaces.msg import GazeStatus, HeadCmd, HeadState
        except ImportError:
            HeadState = HeadCmd = GazeStatus = None
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
        def __init__(self, topic): self.topic = topic; self.last_msg = None; self.count = 0
        def publish(self, msg): self.last_msg = msg; self.count += 1

    class _MockClock:
        def now(self):
            class _Time:
                def to_msg(self): return None
            return _Time()

    class Node:
        def __init__(self, node_name="node", *args, **kwargs):
            self._node_name = node_name
            self._params = {}
        def get_name(self): return self._node_name
        def create_publisher(self, msg_type, topic, *args, **kwargs):
            return _MockPublisher(topic)
        def create_subscription(self, *args, **kwargs): return None
        def create_timer(self, *args, **kwargs): return None
        def get_clock(self): return _MockClock()
        def get_logger(self):
            import logging
            return logging.getLogger(self._node_name)
        def declare_parameter(self, name, value=None, *args, **kwargs):
            self._params[name] = value
            return _MockParam(value)
        def get_parameter(self, name):
            return _MockParam(self._params.get(name))
        def destroy_node(self): pass

    class QoSProfile:
        def __init__(self, *args, **kwargs): pass

    class ReliabilityPolicy:
        BEST_EFFORT = 0
        RELIABLE = 1

    class _MockMsg:
        def __init__(self, data=None, **kwargs):
            self.data = data
            for key, val in kwargs.items():
                setattr(self, key, val)

    Bool = Float32 = String = JointState = _MockMsg
    GazeStatus = HeadCmd = HeadState = None

if HeadCmd is None:
    class HeadCmd:  # type: ignore
        def __init__(self, angle_deg: float = 0.0, velocity_deg_s: float = 0.0):
            self.angle_deg = float(angle_deg)
            self.velocity_deg_s = float(velocity_deg_s)

from pathlib import Path
import threading


def _resolve_standalone_dir() -> str:
    cur = Path(__file__).resolve().parent
    while cur.parent != cur:
        cand = cur / "standalone"
        if (cand / "tracker.py").exists():
            return str(cand)
        cur = cur.parent
    return str(Path(__file__).resolve().parents[5] / "standalone")


_STANDALONE_DIR = _resolve_standalone_dir()
if _STANDALONE_DIR not in sys.path:
    sys.path.insert(0, _STANDALONE_DIR)

from sources import CameraSource, AudioSource
from stereo_doa import DEFAULT_MIC_SPACING_M
from astro_base.gaze.gaze_runtime import GazeRuntimeCore
from astro_base.gaze.gaze_tracker import Detection, GazeResult, UNSCORED_CONFIDENCE


class StandaloneGazeRosNode(Node):
    """Thin ROS 2 wrapper mapping CameraSource, AudioSource, and ROS topics to the golden 2e0b70c standalone gaze runtime.

    Strict Invariants:
    1. Gaze decisions (face tracking, target selection, gaze angle, coasting,
       reacquisition) are made SOLELY by the golden standalone runtime from 2e0b70c.
    2. CameraSource & AudioSource run directly inside the ROS process (no /vision/faces topic dependency).
    3. Exactly ONE frame -> ONE detection -> ONE tracker step -> ONE head command.
    4. Visual target has absolute priority over audio; audio reacquisition activates only when target_id == NONE.
    5. 50Hz keepalive timer only republishes last target yaw to feed the MCU watchdog without stepping tracker.
    6. /head/state is the sole authoritative feedback source.
    """

    def __init__(
        self,
        camera_device: Optional[int] = None,
        use_camera_source: Optional[bool] = None,
        enable_audio: Optional[bool] = None,
        enable_voice: Optional[bool] = None,
    ):
        super().__init__("standalone_gaze_ros_node")

        # Declare parameters
        self.declare_parameter("camera_device", 0)
        self.declare_parameter("use_camera_source", True)
        self.declare_parameter("control_rate_hz", 50.0)
        self.declare_parameter("coast_timeout_s", 1.0)
        self.declare_parameter("calibration_path", "")
        self.declare_parameter("camera_latency_s", 0.050)
        self.declare_parameter("enable_audio", True)
        self.declare_parameter("audio_device", -1)
        self.declare_parameter("mic_channels", "")
        self.declare_parameter("mic_spacing", DEFAULT_MIC_SPACING_M)
        self.declare_parameter("audio_freshness_s", 1.0)
        self.declare_parameter("enable_voice", True)
        self.declare_parameter("enable_edge_tts", True)

        cam_dev = camera_device if camera_device is not None else int(self.get_parameter("camera_device").value)
        use_cam = use_camera_source if use_camera_source is not None else bool(self.get_parameter("use_camera_source").value)
        control_rate = float(self.get_parameter("control_rate_hz").value)
        coast_timeout = float(self.get_parameter("coast_timeout_s").value)
        calib_path = str(self.get_parameter("calibration_path").value) or None
        self.camera_latency_s = float(self.get_parameter("camera_latency_s").value)

        use_audio = enable_audio if enable_audio is not None else bool(self.get_parameter("enable_audio").value)
        audio_dev = int(self.get_parameter("audio_device").value)
        audio_dev = None if audio_dev < 0 else audio_dev
        mic_ch_str = str(self.get_parameter("mic_channels").value).strip()
        mic_channels = [int(c.strip()) for c in mic_ch_str.split(",") if c.strip().isdigit()] if mic_ch_str else None
        mic_spacing = float(self.get_parameter("mic_spacing").value)
        self.audio_freshness_s = float(self.get_parameter("audio_freshness_s").value)
        self.enable_voice = enable_voice if enable_voice is not None else bool(self.get_parameter("enable_voice").value)
        self.enable_edge_tts = bool(self.get_parameter("enable_edge_tts").value)

        # The Golden Standalone Runtime Core (Immutable 2e0b70c baseline)
        self.runtime = GazeRuntimeCore(
            calibration_path=calib_path,
            coast_timeout_s=coast_timeout,
        )

        # Feedback & Telemetry State
        self.cycle_id: int = 0
        self.frame_index: int = 0
        self.last_published_yaw: float = 0.0
        self.latest_result: Optional[GazeResult] = None
        self._head_feedback_seen: bool = False
        self._head_state_received: bool = False
        self.raw_encoder_deg: float = 0.0
        self.diagnostic_joint_yaw_deg: float = 0.0
        self.diagnostic_joint_vel_deg_s: float = 0.0
        self._running: bool = True
        self.camera: Optional[CameraSource] = None
        self._cam_thread: Optional[threading.Thread] = None
        self.audio: Optional[AudioSource] = None
        self.voice_loop = None

        # Initialize AudioSource and VoiceLoop (Non-blocking background workers)
        if use_audio:
            try:
                self.audio = AudioSource(
                    device=audio_dev,
                    mic_spacing_m=mic_spacing,
                    mic_channels=mic_channels,
                    max_age_s=self.audio_freshness_s,
                )
                self.audio.start()
                if self.audio.available:
                    self.get_logger().info(
                        f"🎤 AudioSource initialized ({self.audio.mode} mode, {self.audio.device_name} @{self.audio.sample_rate}Hz)"
                    )
                    if self.enable_voice:
                        try:
                            import voice as voice_module
                            self.voice_loop = voice_module.build_default_loop(
                                self.audio, edge_tts_enabled=self.enable_edge_tts
                            )
                            if self.voice_loop is not None:
                                self.get_logger().info(f"🗣️ VoiceLoop active — wake word: '{self.voice_loop.wake_word}'")
                            else:
                                self.get_logger().info(f"🗣️ VoiceLoop inactive: {voice_module.LAST_SETUP_ERROR}")
                        except Exception as v_exc:
                            self.get_logger().warning(f"🗣️ VoiceLoop setup skipped: {v_exc}")
                else:
                    self.get_logger().warning(f"🎤 AudioSource unavailable ({self.audio.error}) — continuing in vision-only mode")
            except Exception as a_exc:
                self.get_logger().warning(f"🎤 AudioSource setup error: {a_exc} — continuing in vision-only mode")

        # 100-sample Diagnostic Ring Buffers for Center Isolation
        self._diag_raw_bearings: collections.deque = collections.deque(maxlen=100)
        self._diag_target_yaws: collections.deque = collections.deque(maxlen=100)
        self._diag_measured_heads: collections.deque = collections.deque(maxlen=100)
        self.latest_head_state_pos_deg: float = 0.0
        self.latest_head_state_target_pos_deg: float = 0.0

        # Actuator Publishers
        if HeadCmd is not None:
            self.pub_head_command = self.create_publisher(HeadCmd, "/head/command", 10)
        else:
            self.pub_head_command = None
        self.pub_head_cmd_pos = self.create_publisher(Float32, "/head/cmd_pos", 10)

        # Diagnostic Publishers
        if GazeStatus is not None:
            self.pub_gaze_state = self.create_publisher(GazeStatus, "/gaze/state", 10)
        else:
            self.pub_gaze_state = None
        self.pub_active_target = self.create_publisher(String, "/gaze/active_target", 10)
        self.pub_gaze_debug = self.create_publisher(String, "/gaze/debug", 10)

        # Subscriptions (Authoritative Feedback & Diagnostic Only - NO ROS Vision Topics)
        qos_best_effort = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
        if HeadState is not None:
            self.create_subscription(HeadState, "/head/state", self._on_head_state, 10)
        self.create_subscription(JointState, "/joint_states", self._on_joint_states, qos_best_effort)
        self.create_subscription(Bool, "/safety/emergency_stop", self._on_emergency_stop, 10)
        self.create_subscription(Bool, "/system/sleep", self._on_sleep_mode, 10)

        # Direct CameraSource Integration (Hardware pipeline)
        if use_cam:
            try:
                self.camera = CameraSource(device=cam_dev)
                if self.camera.available:
                    self.get_logger().info(
                        f"📷 CameraSource initialized ({self.camera.backend}) | detector: {self.camera.detector_name}"
                    )
                    self._cam_thread = threading.Thread(target=self._camera_worker_loop, daemon=True)
                    self._cam_thread.start()
                else:
                    self.get_logger().info(
                        f"📷 CameraSource device {cam_dev} not available ({self.camera.error or 'no camera'}) — headless test mode"
                    )
            except Exception as exc:
                self.get_logger().warn(f"📷 Could not start CameraSource: {exc}")

        # 50Hz Passive Motor Keepalive Timer (WATCHDOG FEED ONLY - NO TRACKER STEPS)
        period_s = 1.0 / max(1.0, control_rate)
        self.keepalive_timer = self.create_timer(period_s, self._passive_keepalive_cycle)

        self.get_logger().info(
            f"StandaloneGazeRosNode active — Sole visual authority: standalone 2e0b70c runtime (Keepalive: {control_rate:.1f}Hz)"
        )

    def destroy_node(self):
        self._running = False
        if self.camera is not None:
            try:
                self.camera.close()
            except Exception:
                pass
        super().destroy_node()

    # =========================================================================
    # Hardware State Callbacks (Authoritative Feedback)
    # =========================================================================

    def _on_head_state(self, msg) -> None:
        """Authoritative reader for encoder position from HeadState message."""
        if hasattr(msg, "timestamp") and msg.timestamp is not None:
            t = float(msg.timestamp)
        elif hasattr(msg, "header") and hasattr(msg.header, "stamp") and getattr(msg.header.stamp, "sec", 0) > 0:
            t = float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9
        else:
            t = time.monotonic()
        if hasattr(msg, "position_deg") and not math.isnan(msg.position_deg):
            vel = float(getattr(msg, "velocity_deg_s", 0.0))
            if math.isnan(vel):
                vel = 0.0
            pos = float(msg.position_deg)
            self.raw_encoder_deg = pos
            self.latest_head_state_pos_deg = pos
            self.latest_head_state_target_pos_deg = float(getattr(msg, "target_position_deg", 0.0))
            self.runtime.update_head_feedback(pos, vel, timestamp=t, source="/head/state")
            self._head_feedback_seen = True
            self._head_state_received = True

    def _on_joint_states(self, msg: JointState) -> None:
        """Diagnostic reader for head_yaw_joint actual position and velocity.

        /head/state is the sole authoritative source. When /head/state is active,
        /joint_states is strictly diagnostic and will not overwrite authoritative feedback.
        """
        if hasattr(msg, "name") and "head_yaw_joint" in msg.name:
            idx = msg.name.index("head_yaw_joint")
            pos_rad = msg.position[idx]
            if not math.isnan(pos_rad):
                vel_rad = msg.velocity[idx] if len(msg.velocity) > idx else 0.0
                vel_deg = math.degrees(vel_rad) if not math.isnan(vel_rad) else 0.0
                deg_pos = math.degrees(pos_rad)
                self.diagnostic_joint_yaw_deg = float(deg_pos)
                self.diagnostic_joint_vel_deg_s = float(vel_deg)
                if not self._head_state_received:
                    t = time.monotonic()
                    self.raw_encoder_deg = float(deg_pos)
                    self.runtime.update_head_feedback(deg_pos, vel_deg, timestamp=t, source="/joint_states")
                    self._head_feedback_seen = True

    def _on_emergency_stop(self, msg: Bool) -> None:
        self.runtime.tracker.fsm.set_safety_lock(bool(msg.data))

    def _on_sleep_mode(self, msg: Bool) -> None:
        self.runtime.tracker.fsm.set_sleep_mode(bool(msg.data))

    # =========================================================================
    # CameraSource Worker Loop
    # =========================================================================

    def _camera_worker_loop(self) -> None:
        """Continuously reads from CameraSource, runs detector, and steps gaze runtime."""
        while self._running and self.camera is not None and self.camera.available:
            try:
                ok, frame = self.camera.read()
                if not ok or frame is None:
                    time.sleep(0.01)
                    continue

                t_read_done = time.monotonic()
                detections = self.camera.detect(frame)
                t_detect_done = time.monotonic()
                frame_h, frame_w = frame.shape[:2]

                capture_ts = t_read_done - self.camera_latency_s
                arrival_ts = t_detect_done

                # Sample latest acoustic state
                doa_deg = self.audio.latest_doa_deg(arrival_ts) if (self.audio and self.audio.available) else None
                speech = self.audio.latest_speech(arrival_ts) if (self.audio and self.audio.available) else None
                if self.voice_loop is not None:
                    self.voice_loop.pump(arrival_ts)
                is_speaking = self.voice_loop.is_speaking_at(arrival_ts) if self.voice_loop else False

                self._step_frame_and_dispatch(
                    detections=detections,
                    frame_w=frame_w,
                    frame_h=frame_h,
                    capture_ts=capture_ts,
                    arrival_ts=arrival_ts,
                    doa_deg=doa_deg,
                    speech=speech,
                    is_robot_speaking=is_speaking,
                )
            except Exception as exc:
                self.get_logger().error(f"Error in CameraSource worker loop: {exc}")
                time.sleep(0.05)

    # =========================================================================
    # Frame-Synchronous Visual Processing API
    # =========================================================================

    def step_camera_frame(
        self,
        frame,
        timestamp: Optional[float] = None,
        doa_deg: Optional[float] = None,
        speech: Optional[Any] = None,
        is_robot_speaking: Optional[bool] = None,
    ) -> GazeResult:
        """Runs detector on frame and steps tracker (1:1 with standalone/track.py)."""
        t_start = time.monotonic()
        if self.camera is not None:
            detections = self.camera.detect(frame)
        else:
            detections = []
        t_end = time.monotonic()
        frame_h, frame_w = frame.shape[:2]
        if timestamp is not None:
            capture_ts = float(timestamp)
            arrival_ts = float(timestamp)
        else:
            capture_ts = t_start - self.camera_latency_s
            arrival_ts = t_end

        if doa_deg is None and self.audio and self.audio.available:
            doa_deg = self.audio.latest_doa_deg(arrival_ts)
        if speech is None and self.audio and self.audio.available:
            speech = self.audio.latest_speech(arrival_ts)
        if self.voice_loop is not None:
            self.voice_loop.pump(arrival_ts)
        if is_robot_speaking is None:
            is_robot_speaking = self.voice_loop.is_speaking_at(arrival_ts) if self.voice_loop else False

        return self._step_frame_and_dispatch(
            detections=detections,
            frame_w=frame_w,
            frame_h=frame_h,
            capture_ts=capture_ts,
            arrival_ts=arrival_ts,
            doa_deg=doa_deg,
            speech=speech,
            is_robot_speaking=bool(is_robot_speaking),
        )

    def step_frame(
        self,
        detections: Sequence[Detection],
        frame_size: Tuple[int, int] = (640, 480),
        timestamp: Optional[float] = None,
        doa_deg: Optional[float] = None,
        speech: Optional[Any] = None,
        is_robot_speaking: bool = False,
    ) -> GazeResult:
        """Direct frame step for testing/replay without ROS topics."""
        t = timestamp if timestamp is not None else time.monotonic()
        return self._step_frame_and_dispatch(
            detections=detections,
            frame_w=frame_size[0],
            frame_h=frame_size[1],
            capture_ts=t,
            arrival_ts=t,
            doa_deg=doa_deg,
            speech=speech,
            is_robot_speaking=is_robot_speaking,
        )

    def _step_frame_and_dispatch(
        self,
        detections: Sequence[Detection],
        frame_w: int,
        frame_h: int,
        capture_ts: float,
        arrival_ts: float,
        doa_deg: Optional[float] = None,
        speech: Optional[Any] = None,
        is_robot_speaking: bool = False,
    ) -> GazeResult:
        """Executes strictly ONE gaze engine step for ONE camera frame.

        ONE FRAME -> ONE DETECTION -> ONE GAZE STEP -> ONE RESULT -> ONE HEAD TARGET
        """
        self.cycle_id += 1
        self.frame_index += 1

        t_step_start = time.monotonic()
        res = self.runtime.step(
            faces=detections,
            frame_size=(frame_w, frame_h),
            doa_deg=doa_deg,
            speech=speech,
            timestamp=capture_ts,
            is_robot_speaking=is_robot_speaking,
        )
        t_step_end = time.monotonic()

        self.latest_result = res
        target_yaw = float(res.target_yaw_deg)
        self.last_published_yaw = target_yaw

        # Direct Actuator Dispatch (ONE RESULT -> ONE AUTHORITATIVE TARGET)
        if self.pub_head_command is not None:
            hcmd = HeadCmd()
            hcmd.angle_deg = target_yaw
            self.pub_head_command.publish(hcmd)

        cmd_pos = Float32()
        cmd_pos.data = target_yaw
        self.pub_head_cmd_pos.publish(cmd_pos)

        if self.pub_active_target is not None:
            tgt_msg = String()
            tgt_msg.data = res.target_id or "NONE"
            self.pub_active_target.publish(tgt_msg)

        # Synchronized Telemetry
        face_bearing = res.face_bearings_deg[0] if res.face_bearings_deg else None
        face_bearing_str = f"{face_bearing:+.1f}°" if face_bearing is not None else "NONE"
        primary_target_id = res.target_id or "NONE"
        vision_age_ms = round(max(0.0, (arrival_ts - capture_ts) * 1000.0), 1)
        bbox_str = f"[{detections[0].x},{detections[0].y},{detections[0].w},{detections[0].h}]" if detections else "NONE"
        conf_str = f"{detections[0].confidence:.2f}" if detections else "0.00"

        tracker_head = self.runtime.tracker.head_angle_deg
        actual_head = self.runtime.actual_head_yaw_deg
        aligned_head, aligned_vel = self.runtime.get_head_position_at(capture_ts)
        temporal_skew_ms = max(0.0, (arrival_ts - capture_ts) * 1000.0)
        raw_enc = getattr(self, "raw_encoder_deg", actual_head)
        fb_deg, fb_age, fb_src = self.runtime.get_feedback_telemetry(now=arrival_ts)

        doa_str = f"{doa_deg:+.1f}°" if doa_deg is not None else "NONE"
        owner_str = res.owner.value if hasattr(res.owner, "value") else str(res.owner)
        sync_line = (
            f"visual_bearing={face_bearing_str} "
            f"audio_doa={doa_str} "
            f"owner={owner_str} "
            f"command_yaw={target_yaw:+.1f}° "
            f"aligned_head={aligned_head:+.1f}° "
            f"actual_head={actual_head:+.1f}° "
            f"temporal_skew_ms={temporal_skew_ms:.1f}ms "
            f"head_feedback_deg={fb_deg:+.1f}° "
            f"head_feedback_age_ms={fb_age:.1f}ms "
            f"head_feedback_source={fb_src}"
        )

        frame_log = (
            f"FRAME\n"
            f"cycle_id={self.cycle_id}\n"
            f"frame_id={self.frame_index}\n"
            f"capture_ts={capture_ts:.3f}\n"
            f"arrival_ts={arrival_ts:.3f}\n"
            f"step_ts={t_step_end:.3f}\n"
            f"vision_age_ms={vision_age_ms:.1f}\n"
            f"bbox={bbox_str}\n"
            f"confidence={conf_str}\n"
            f"visual_bearing={face_bearing_str}\n"
            f"target_id={primary_target_id}"
        )

        cmd_log = (
            f"COMMAND\n"
            f"cycle_id={self.cycle_id}\n"
            f"frame_id={self.frame_index}\n"
            f"target_id={primary_target_id}\n"
            f"command_yaw={target_yaw:+.1f}°\n"
            f"aligned_head={aligned_head:+.1f}°\n"
            f"actual_head={actual_head:+.1f}°\n"
            f"raw_encoder={raw_enc:+.1f}°\n"
            f"FEEDBACK_SYNC: {sync_line}\n"
            f"source={getattr(res, 'command_source', 'VISUAL')}"
        )
        # Center Forensic Diagnostic Telemetry
        if detections:
            bbox_cx = float(detections[0].x + (detections[0].w / 2.0))
            bbox_cy = float(detections[0].y + (detections[0].h / 2.0))
            raw_bearing, _ = self.runtime.tracker.transformer.camera_pixel_to_optical_angles(
                bbox_cx, bbox_cy, frame_w, frame_h
            )
        else:
            bbox_cx = frame_w / 2.0
            raw_bearing = 0.0

        diag_err = target_yaw - aligned_head
        self._diag_raw_bearings.append(raw_bearing)
        self._diag_target_yaws.append(target_yaw)
        self._diag_measured_heads.append(aligned_head)

        std_raw = float(np.std(self._diag_raw_bearings)) if len(self._diag_raw_bearings) > 1 else 0.0
        std_tgt = float(np.std(self._diag_target_yaws)) if len(self._diag_target_yaws) > 1 else 0.0
        std_head = float(np.std(self._diag_measured_heads)) if len(self._diag_measured_heads) > 1 else 0.0

        center_diag_line = (
            f"CENTER_DIAG: bbox_cx={bbox_cx:.1f} frame_cx={frame_w / 2.0:.1f} "
            f"raw_bearing={raw_bearing:+.2f}° measured_head={aligned_head:+.2f}° "
            f"target_yaw={target_yaw:+.2f}° error={diag_err:+.2f}° "
            f"sigma_raw={std_raw:.2f} sigma_tgt={std_tgt:.2f} sigma_head={std_head:.2f}"
        )

        # Structured Instrumentation for Forensic Isolation
        sign_vis = 0 if abs(raw_bearing) < 1e-3 else (1 if raw_bearing > 0 else -1)
        sign_tgt = 0 if abs(target_yaw - aligned_head) < 1e-3 else (1 if (target_yaw - aligned_head) > 0 else -1)
        sign_pub = 0 if abs(self.last_published_yaw - aligned_head) < 1e-3 else (1 if (self.last_published_yaw - aligned_head) > 0 else -1)

        instrumentation_log = (
            f"RAW:\n"
            f"bbox_center_x={bbox_cx:.1f}\n"
            f"frame_center_x={frame_w / 2.0:.1f}\n"
            f"\n"
            f"VISION:\n"
            f"visual_bearing_deg={raw_bearing:+.2f}\n"
            f"\n"
            f"FEEDBACK:\n"
            f"aligned_head_deg={aligned_head:+.2f}\n"
            f"measured_head_deg={actual_head:+.2f}\n"
            f"temporal_skew_ms={temporal_skew_ms:.1f}\n"
            f"head_feedback_timestamp={self.runtime.last_feedback_time:.3f}\n"
            f"head_feedback_age_ms={fb_age:.1f}\n"
            f"head_feedback_source={fb_src}\n"
            f"\n"
            f"CONTROL:\n"
            f"visual_error_deg={diag_err:+.2f}\n"
            f"target_yaw_deg={target_yaw:+.2f}\n"
            f"published_command_deg={target_yaw:+.2f}\n"
            f"\n"
            f"ACTUATOR:\n"
            f"actual_head_deg={self.latest_head_state_pos_deg:+.2f}\n"
            f"target_position_deg={self.latest_head_state_target_pos_deg:+.2f}\n"
            f"\n"
            f"SIGNS:\n"
            f"sign(visual_bearing)={sign_vis:+d}\n"
            f"sign(target_yaw - measured_head)={sign_tgt:+d}\n"
            f"sign(published_command - measured_head)={sign_pub:+d}"
        )

        speech_conf = f"{speech.confidence:.2f}" if (speech and hasattr(speech, "confidence")) else "0.00"
        audio_log = (
            f"AUDIO:\n"
            f"doa_deg={doa_str}\n"
            f"speech_confidence={speech_conf}\n"
            f"is_robot_speaking={is_robot_speaking}\n"
            f"gaze_owner={owner_str}"
        )

        forensic_msg = f"\n{frame_log}\n{cmd_log}\n{center_diag_line}\n{instrumentation_log}\n\n{audio_log}"
        try:
            print(forensic_msg)
        except UnicodeEncodeError:
            print(forensic_msg.encode("ascii", errors="replace").decode("ascii"))
        self.get_logger().info(sync_line)

        return res

    # =========================================================================
    # Passive 50Hz Keepalive
    # =========================================================================

    def _passive_keepalive_cycle(self) -> None:
        """Streams last authoritative target yaw to keep MCU watchdog fed.

        DOES NOT step tracker.
        DOES NOT update targets.
        DOES NOT update visual FSM.
        """
        target_yaw = self.runtime.get_keepalive_yaw_deg()
        cmd_pos = Float32()
        cmd_pos.data = float(target_yaw)
        self.pub_head_cmd_pos.publish(cmd_pos)

        if self.pub_head_command is not None:
            hcmd = HeadCmd()
            hcmd.angle_deg = float(target_yaw)
            self.pub_head_command.publish(hcmd)

    def destroy_node(self) -> bool:
        self._running = False
        if self._cam_thread is not None and self._cam_thread.is_alive():
            self._cam_thread.join(timeout=1.0)
        if self.camera is not None:
            try:
                self.camera.close()
            except Exception:
                pass
        if self.audio is not None:
            try:
                self.audio.close()
            except Exception:
                pass
        if self.voice_loop is not None:
            try:
                self.voice_loop.stop()
            except Exception:
                pass
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = StandaloneGazeRosNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
