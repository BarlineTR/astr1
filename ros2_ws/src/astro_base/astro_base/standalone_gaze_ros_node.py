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

import json
import math
import os
import sys
import time
from typing import List, Optional, Sequence, Tuple

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from sensor_msgs.msg import JointState
    from std_msgs.msg import Bool, Float32, String
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

from sources import CameraSource
from astro_base.gaze.gaze_runtime import GazeRuntimeCore
from astro_base.gaze.gaze_tracker import Detection, GazeResult, UNSCORED_CONFIDENCE


class StandaloneGazeRosNode(Node):
    """Thin ROS 2 wrapper mapping CameraSource and ROS topics to the golden 2e0b70c standalone gaze runtime.

    Strict Invariants:
    1. Gaze decisions (face tracking, target selection, gaze angle, coasting,
       reacquisition) are made SOLELY by the golden standalone runtime from 2e0b70c.
    2. CameraSource runs directly inside the ROS process (no /vision/faces topic dependency).
    3. Exactly ONE frame -> ONE detection -> ONE tracker step -> ONE head command.
    4. 50Hz keepalive timer only republishes last target yaw to feed the MCU watchdog without stepping tracker.
    5. /head/state is the sole authoritative feedback source.
    """

    def __init__(self, camera_device: Optional[int] = None, use_camera_source: Optional[bool] = None):
        super().__init__("standalone_gaze_ros_node")

        # Declare parameters
        self.declare_parameter("camera_device", 0)
        self.declare_parameter("use_camera_source", True)
        self.declare_parameter("control_rate_hz", 50.0)
        self.declare_parameter("coast_timeout_s", 1.0)
        self.declare_parameter("calibration_path", "")

        cam_dev = camera_device if camera_device is not None else int(self.get_parameter("camera_device").value)
        use_cam = use_camera_source if use_camera_source is not None else bool(self.get_parameter("use_camera_source").value)
        control_rate = float(self.get_parameter("control_rate_hz").value)
        coast_timeout = float(self.get_parameter("coast_timeout_s").value)
        calib_path = str(self.get_parameter("calibration_path").value) or None

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
        t = time.monotonic()
        if hasattr(msg, "position_deg") and not math.isnan(msg.position_deg):
            vel = float(getattr(msg, "velocity_deg_s", 0.0))
            if math.isnan(vel):
                vel = 0.0
            pos = float(msg.position_deg)
            self.raw_encoder_deg = pos
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

                now = time.monotonic()
                detections = self.camera.detect(frame)
                frame_h, frame_w = frame.shape[:2]

                self._step_frame_and_dispatch(
                    detections=detections,
                    frame_w=frame_w,
                    frame_h=frame_h,
                    capture_ts=now,
                    arrival_ts=now,
                )
            except Exception as exc:
                self.get_logger().error(f"Error in CameraSource worker loop: {exc}")
                time.sleep(0.05)

    # =========================================================================
    # Frame-Synchronous Visual Processing API
    # =========================================================================

    def step_camera_frame(self, frame, timestamp: Optional[float] = None) -> GazeResult:
        """Runs detector on frame and steps tracker (1:1 with standalone/track.py)."""
        if self.camera is not None:
            detections = self.camera.detect(frame)
        else:
            detections = []
        frame_h, frame_w = frame.shape[:2]
        t = timestamp if timestamp is not None else time.monotonic()
        return self._step_frame_and_dispatch(
            detections=detections,
            frame_w=frame_w,
            frame_h=frame_h,
            capture_ts=t,
            arrival_ts=t,
        )

    def step_frame(
        self,
        detections: Sequence[Detection],
        frame_size: Tuple[int, int] = (640, 480),
        timestamp: Optional[float] = None,
    ) -> GazeResult:
        """Direct frame step for testing/replay without ROS topics."""
        t = timestamp if timestamp is not None else time.monotonic()
        return self._step_frame_and_dispatch(
            detections=detections,
            frame_w=frame_size[0],
            frame_h=frame_size[1],
            capture_ts=t,
            arrival_ts=t,
        )

    def _step_frame_and_dispatch(
        self,
        detections: Sequence[Detection],
        frame_w: int,
        frame_h: int,
        capture_ts: float,
        arrival_ts: float,
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
            timestamp=capture_ts,
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
        raw_enc = getattr(self, "raw_encoder_deg", actual_head)
        fb_deg, fb_age, fb_src = self.runtime.get_feedback_telemetry(now=arrival_ts)

        sync_line = (
            f"visual_bearing={face_bearing_str} "
            f"command_yaw={target_yaw:+.1f}° "
            f"actual_head={actual_head:+.1f}° "
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
            f"actual_head={actual_head:+.1f}°\n"
            f"raw_encoder={raw_enc:+.1f}°\n"
            f"FEEDBACK_SYNC: {sync_line}\n"
            f"source={getattr(res, 'command_source', 'VISUAL')}"
        )
        forensic_msg = f"\n{frame_log}\n{cmd_log}"
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
