#!/usr/bin/env python3
"""ASTRO — Thin ROS 2 Standalone Gaze Wrapper Node.

Direct ROS wrapper for the working standalone gaze engine (GazeRuntimeCore).
Execution Semantics:
  ONE CAMERA FRAME -> ONE GAZE STEP -> ONE GazeResult -> ONE HEAD COMMAND

50Hz Motor Keepalive:
  Passive timer publishing runtime.get_keepalive_yaw() to feed MCU watchdog.
  ZERO tracker steps, ZERO target updates, ZERO visual FSM transitions.
"""

import json
import math
import time
from typing import List, Optional, Tuple

from astro_base.gaze.angle_math import angular_diff_deg
from astro_base.gaze.coordinate_frames import CalibrationConfig
from astro_base.gaze.gaze_runtime import GazeRuntimeCore
from astro_base.gaze.gaze_tracker import Detection, GazeResult, UNSCORED_CONFIDENCE

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from std_msgs.msg import Bool, Float32, String
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
            return logging.getLogger("StandaloneGazeNode")
        def declare_parameter(self, name, value=None, *args, **kwargs):
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
        def __init__(self, data=None, **kwargs):
            self.data = data
            for key, val in kwargs.items():
                setattr(self, key, val)

    Bool = Float32 = String = JointState = _MockMsg
    GazeStatus = HeadCmd = HeadState = None


class StandaloneGazeNode(Node):
    """Thin ROS 2 wrapper hosting GazeRuntimeCore with single-frame visual semantics."""

    def __init__(self, calibration_path: Optional[str] = None):
        super().__init__("standalone_gaze_node")

        # Parameters
        self.declare_parameter("control_rate_hz", 50.0)
        self.declare_parameter("coast_timeout_s", 1.0)
        self.declare_parameter("calibration_file", "")

        calib_file = str(self.get_parameter("calibration_file").value or "")
        if not calib_file and calibration_path:
            calib_file = calibration_path
        coast_timeout = float(self.get_parameter("coast_timeout_s").value or 1.0)
        control_rate = float(self.get_parameter("control_rate_hz").value or 50.0)

        # Core Shared Engine
        self.runtime = GazeRuntimeCore(
            calibration_path=calib_file if calib_file else None,
            coast_timeout_s=coast_timeout,
        )

        # Telemetry & State
        self.cycle_id: int = 0
        self.frame_index: int = 0
        self.last_published_yaw: float = 0.0
        self.latest_result: Optional[GazeResult] = None
        self._head_feedback_seen: bool = False
        self.raw_encoder_deg: float = 0.0

        # Publishers
        if HeadCmd is not None:
            self.pub_head_command = self.create_publisher(HeadCmd, "/head/command", 10)
        else:
            self.pub_head_command = None
        self.pub_head_cmd_pos = self.create_publisher(Float32, "/head/cmd_pos", 10)

        if GazeStatus is not None:
            self.pub_gaze_state = self.create_publisher(GazeStatus, "/gaze/state", 10)
        else:
            self.pub_gaze_state = None

        self.pub_active_target = self.create_publisher(String, "/gaze/active_target", 10)
        self.pub_gaze_debug = self.create_publisher(String, "/gaze/debug", 10)

        # Subscriptions
        qos_best_effort = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
        if HeadState is not None:
            self.create_subscription(HeadState, "/head/state", self._on_head_state, 10)
        self.create_subscription(JointState, "/joint_states", self._on_joint_states, qos_best_effort)
        self.create_subscription(String, "/vision/detections_json", self._on_vision_json, 10)
        self.create_subscription(String, "/vision/faces", self._on_vision_json, 10)
        self.create_subscription(Bool, "/safety/emergency_stop", self._on_emergency_stop, 10)
        self.create_subscription(Bool, "/system/sleep", self._on_sleep_mode, 10)

        # 50Hz Passive Motor Keepalive Timer
        period_s = 1.0 / max(1.0, control_rate)
        self.keepalive_timer = self.create_timer(period_s, self._passive_keepalive_cycle)

        self.get_logger().info(f"StandaloneGazeNode running with shared GazeRuntimeCore (Keepalive: {control_rate:.1f}Hz)")

    # =========================================================================
    # Hardware State Callbacks
    # =========================================================================

    def _on_head_state(self, msg) -> None:
        if hasattr(msg, "position_deg") and not math.isnan(msg.position_deg):
            vel = float(getattr(msg, "velocity_deg_s", 0.0))
            if math.isnan(vel):
                vel = 0.0
            self.raw_encoder_deg = float(msg.position_deg)
            self.runtime.update_head_feedback(msg.position_deg, vel)
            self._head_feedback_seen = True

    def _on_joint_states(self, msg: JointState) -> None:
        if hasattr(msg, "name") and "head_yaw_joint" in msg.name:
            idx = msg.name.index("head_yaw_joint")
            pos_rad = msg.position[idx]
            if not math.isnan(pos_rad):
                vel_rad = msg.velocity[idx] if len(msg.velocity) > idx else 0.0
                vel_deg = math.degrees(vel_rad) if not math.isnan(vel_rad) else 0.0
                deg_pos = math.degrees(pos_rad)
                self.raw_encoder_deg = float(deg_pos)
                self.runtime.update_head_feedback(deg_pos, vel_deg)
                self._head_feedback_seen = True

    def _on_emergency_stop(self, msg: Bool) -> None:
        self.runtime.tracker.fsm.set_safety_lock(bool(msg.data))

    def _on_sleep_mode(self, msg: Bool) -> None:
        self.runtime.tracker.fsm.set_sleep_mode(bool(msg.data))

    # =========================================================================
    # Frame-Synchronous Visual Processing
    # =========================================================================

    def _on_vision_json(self, msg: String) -> None:
        t_arrival = time.monotonic()
        self.cycle_id += 1
        self.frame_index += 1

        try:
            raw_data = json.loads(msg.data)
            if isinstance(raw_data, dict):
                detections = raw_data.get("faces", [])
                capture_ts = float(raw_data.get("timestamp", raw_data.get("capture_stamp", t_arrival)))
            elif isinstance(raw_data, list):
                detections = raw_data
                capture_ts = float(detections[0].get("timestamp", t_arrival)) if detections else t_arrival
            else:
                detections = []
                capture_ts = t_arrival

            frame_w = 640
            frame_h = 480
            det_objs: List[Detection] = []
            for d in detections:
                w_val = int(d.get("w", d.get("width", 50)))
                h_val = int(d.get("h", d.get("height", 50)))
                frame_w = int(d.get("frame_width", d.get("frame_w", frame_w)))
                frame_h = int(d.get("frame_height", d.get("frame_h", frame_h)))
                conf = float(d.get("confidence", UNSCORED_CONFIDENCE))
                det_src = str(d.get("detector_source", d.get("source", "vision_json")))
                det_objs.append(
                    Detection(
                        x=int(d.get("x", 0)),
                        y=int(d.get("y", 0)),
                        w=w_val,
                        h=h_val,
                        confidence=conf,
                        detector_source=det_src,
                    )
                )

            # Step Shared GazeRuntimeCore (ONE FRAME -> ONE STEP -> ONE RESULT)
            t_step_start = time.monotonic()
            res = self.runtime.step(
                faces=det_objs,
                frame_size=(frame_w, frame_h),
                timestamp=capture_ts,
            )
            t_step_end = time.monotonic()

            self.latest_result = res
            target_yaw = float(res.target_yaw_deg)
            self.last_published_yaw = target_yaw

            # Direct Actuator Dispatch
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

            # Forensic Telemetry Formatting
            face_bearing = res.face_bearings_deg[0] if res.face_bearings_deg else None
            face_bearing_str = f"{face_bearing:+.1f}°" if face_bearing is not None else "NONE"
            primary_track_id = res.active_track_at_command
            primary_target_id = res.target_id or "NONE"
            vision_age_ms = round(max(0.0, (t_arrival - capture_ts) * 1000.0), 1)
            bbox_str = f"[{det_objs[0].x},{det_objs[0].y},{det_objs[0].w},{det_objs[0].h}]" if det_objs else "NONE"
            conf_str = f"{det_objs[0].confidence:.2f}" if det_objs else "0.00"

            frame_log = (
                f"FRAME\n"
                f"cycle_id={self.cycle_id}\n"
                f"frame_id={self.frame_index}\n"
                f"capture_ts={capture_ts:.3f}\n"
                f"arrival_ts={t_arrival:.3f}\n"
                f"step_ts={t_step_end:.3f}\n"
                f"vision_age_ms={vision_age_ms:.1f}\n"
                f"bbox={bbox_str}\n"
                f"confidence={conf_str}\n"
                f"visual_bearing={face_bearing_str}\n"
                f"track_id={primary_track_id}\n"
                f"target_id={primary_target_id}"
            )
            tracker_head = self.runtime.tracker.head_angle_deg
            actual_head = self.runtime.actual_head_yaw_deg
            raw_enc = getattr(self, "raw_encoder_deg", actual_head)

            cmd_log = (
                f"COMMAND\n"
                f"cycle_id={self.cycle_id}\n"
                f"frame_id={self.frame_index}\n"
                f"target_id={primary_target_id}\n"
                f"golden_target_yaw={target_yaw:+.1f}°\n"
                f"command_yaw={target_yaw:+.1f}°\n"
                f"actual_head={actual_head:+.1f}°\n"
                f"raw_encoder={raw_enc:+.1f}°\n"
                f"golden_tracker.head_angle_deg={tracker_head:+.1f}°\n"
                f"FEEDBACK_SYNC: command_yaw={target_yaw:+.1f}° actual_head={actual_head:+.1f}° raw_encoder={raw_enc:+.1f}° golden_tracker.head_angle_deg={tracker_head:+.1f}°\n"
                f"source={res.command_source}"
            )
            forensic_msg = f"\n{frame_log}\n{cmd_log}"
            try:
                print(forensic_msg)
            except UnicodeEncodeError:
                print(forensic_msg.encode("ascii", errors="replace").decode("ascii"))
            self.get_logger().info(forensic_msg)

        except Exception as exc:
            self.get_logger().error(f"Error processing vision message: {exc}")

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
    node = StandaloneGazeNode()
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
