#!/usr/bin/env python3
"""ASTRO Robot — Real-Time Audiovisual Social Gaze Live Monitor & Flight Recorder.

Subscribes to all perception, fusion, state machine, actuator, and camera stream topics to provide:
  1. Live interactive dashboard (10 Hz in-place ANSI display)
  2. Camera Fluidity & Stream Telemetry (FPS, Frame Jitter, Resolution, Latency)
  3. Background Flight Recorder tracking all acoustic orienting, face tracking, and FSM events
  4. Formatted Summary Report with Detailed Acoustic Saccade Audit Table printed to stdout and saved to JSON on Ctrl+C exit

Usage:
  python3 scripts/test_social_gaze_live.py
"""

from collections import deque
import json
import math
import os
import sys
import time
from typing import Dict, List, Optional

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import Image, JointState
    from std_msgs.msg import Bool, Float32, Int32, String
    try:
        from astro_base.msg import GazeStatus, HeadCmd, HeadState
    except ImportError:
        GazeStatus = HeadCmd = HeadState = None
except ImportError as exc:
    print(f"Error importing ROS 2 packages: {exc}")
    sys.exit(1)


STATE_NAMES = {
    0: "IDLE",
    1: "SEARCHING",
    2: "ACQUIRING",
    3: "ORIENTING",
    4: "TRACKING",
    5: "HOLDING_ATTENTION",
    6: "TARGET_LOST",
    7: "RECOVERING",
}

PRIORITY_NAMES = {
    0: "IDLE",
    1: "VISUAL_TRACKING",
    2: "ACTIVE_SPEAKER",
    3: "GESTURE_INTENT",
    4: "DIRECT_DIALOGUE_INTENT",
    5: "EXPLICIT_USER_GAZE",
    6: "EMERGENCY_STOP",
}


def wrap_deg(deg: float) -> float:
    return ((deg + 180.0) % 360.0) - 180.0


class SocialGazeLiveMonitor(Node):
    def __init__(self):
        super().__init__("social_gaze_live_monitor")

        self.start_time = time.monotonic()

        # =====================================================================
        # 1. Camera Stream Fluidity & Latency Telemetry
        # =====================================================================
        self.camera_frame_count: int = 0
        self.camera_resolution: str = "Unknown"
        self.camera_encoding: str = "Unknown"
        self.camera_last_frame_time: float = 0.0
        self.camera_frame_deltas: deque = deque(maxlen=60)
        self.camera_timestamps: deque = deque(maxlen=60)
        self.camera_latencies_ms: deque = deque(maxlen=60)
        self.camera_fps_rolling: float = 0.0

        # =====================================================================
        # 2. Vision & Face Detection Telemetry
        # =====================================================================
        self.vision_msg_count: int = 0
        self.vision_timestamps: deque = deque(maxlen=60)
        self.vision_fps_rolling: float = 0.0
        self.visual_yaw_deg: Optional[float] = None
        self.visual_conf: float = 0.0
        self.visual_faces_count: int = 0
        self.visual_last_time: float = 0.0
        self.visual_user_distance: float = 0.0
        self.visual_user_emotion: str = "neutral"
        self.visual_recognized_name: str = "None"
        self.visual_looking_at_robot: bool = False

        # =====================================================================
        # 3. Acoustic DOA & Speech Telemetry
        # =====================================================================
        self.audio_doa_deg: Optional[float] = None
        self.audio_doa_conf: float = 0.0
        self.audio_last_time: float = 0.0
        self.audio_total_events: int = 0
        self.audio_accepted_events: int = 0
        self.audio_rejected_events: int = 0
        self.latest_stt_transcript: str = ""
        self.latest_stt_time: float = 0.0

        # =====================================================================
        # 4. Gaze FSM & Trajectory Telemetry
        # =====================================================================
        self.gaze_state: str = "IDLE"
        self.prev_gaze_state: str = "IDLE"
        self.gaze_priority: str = "IDLE"
        self.gaze_desired_yaw: float = 0.0
        self.gaze_planned_yaw: float = 0.0
        self.gaze_at_target: bool = True
        self.gaze_target_valid: bool = False
        self.gaze_target_conf: float = 0.0
        self.gaze_target_id: str = "None"
        self.active_target_json: str = "{}"

        # FSM State Dwell Time Accumulator
        self.state_dwell_times: Dict[str, float] = {name: 0.0 for name in STATE_NAMES.values()}
        self._last_fsm_dwell_stamp: float = time.monotonic()

        # =====================================================================
        # 5. Actuator Closed-Loop Feedback
        # =====================================================================
        self.cmd_head_yaw: float = 0.0
        self.act_head_yaw: float = 0.0
        self.act_head_vel: float = 0.0
        self.head_moving: bool = False
        self.head_stall: bool = False
        self.robot_speaking: bool = False

        # =====================================================================
        # 6. Flight Recorder Event History
        # =====================================================================
        self.state_transitions: List[Dict] = []
        self.audio_events: List[Dict] = []
        self.visual_events: List[Dict] = []
        self.tracking_errors: List[float] = []
        self.sample_count: int = 0
        self.max_abs_vel: float = 0.0

        qos_be = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )

        # =====================================================================
        # Topic Subscriptions
        # =====================================================================
        # Camera Stream
        self.create_subscription(Image, "/oak/rgb/image_raw", self._on_camera_image, qos_profile_sensor_data)
        self.create_subscription(Image, "/camera/color/image_raw", self._on_camera_image, qos_profile_sensor_data)
        self.create_subscription(Image, "/vision/face_image", self._on_debug_face_image, qos_profile_sensor_data)

        # Vision Pipeline
        self.create_subscription(String, "/vision/faces", self._on_vision_json, 10)
        self.create_subscription(String, "/vision/detections_json", self._on_vision_json, 10)
        self.create_subscription(Float32, "/vision/head_yaw", self._on_vision_head_yaw, 10)
        self.create_subscription(Float32, "/vision/user_distance", self._on_user_distance, 10)
        self.create_subscription(String, "/vision/user_emotion", self._on_user_emotion, 10)
        self.create_subscription(String, "/vision/recognized_person", self._on_recognized_person, 10)
        self.create_subscription(Bool, "/vision/looking_at_robot", self._on_looking_at_robot, 10)
        self.create_subscription(Bool, "/vision/person_detected", self._on_person_detected, 10)

        # Audio DOA & STT
        self.create_subscription(Float32, "/audio/doa", self._on_audio_doa, 10)
        self.create_subscription(Float32, "/audio/doa_deg", self._on_audio_doa, 10)
        self.create_subscription(Float32, "/audio/doa_confidence", self._on_doa_confidence, 10)
        self.create_subscription(String, "/stt/transcript", self._on_stt_text, 10)
        self.create_subscription(String, "/speech/text", self._on_stt_text, 10)
        self.create_subscription(String, "/voice/text", self._on_stt_text, 10)
        self.create_subscription(String, "/stt_text", self._on_stt_text, 10)

        # Speech & Gaze State
        self.create_subscription(String, "/gaze/active_target", self._on_active_target, 10)
        self.create_subscription(Float32, "/head/cmd_pos", self._on_cmd_pos, 10)
        self.create_subscription(Bool, "/robot/is_speaking", self._on_speaking, 10)
        self.create_subscription(Bool, "/audio/playback_active", self._on_speaking, 10)

        if HeadCmd is not None:
            self.create_subscription(HeadCmd, "/head/command", self._on_head_cmd, 10)
        if HeadState is not None:
            self.create_subscription(HeadState, "/head/state", self._on_head_state, 10)
        if GazeStatus is not None:
            self.create_subscription(GazeStatus, "/gaze/state", self._on_gaze_state, 10)
        self.create_subscription(JointState, "/joint_states", self._on_joint_states, qos_be)

    # -------------------------------------------------------------------------
    # Camera Stream Callback
    # -------------------------------------------------------------------------
    def _on_camera_image(self, msg: Image):
        now = time.monotonic()
        self.camera_frame_count += 1
        self.camera_resolution = f"{msg.width}x{msg.height}"
        self.camera_encoding = msg.encoding

        if self.camera_last_frame_time > 0.0:
            delta = (now - self.camera_last_frame_time) * 1000.0  # ms
            self.camera_frame_deltas.append(delta)

        self.camera_last_frame_time = now
        self.camera_timestamps.append(now)

        # Calculate Rolling Camera FPS
        if len(self.camera_timestamps) >= 2:
            dt = self.camera_timestamps[-1] - self.camera_timestamps[0]
            if dt > 0.01:
                self.camera_fps_rolling = (len(self.camera_timestamps) - 1) / dt

        # Measure transport latency if stamp is populated
        if msg.header.stamp.sec > 0:
            now_ns = self.get_clock().now().nanoseconds
            msg_ns = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
            latency_ms = (now_ns - msg_ns) / 1_000_000.0
            if 0.0 <= latency_ms < 5000.0:
                self.camera_latencies_ms.append(latency_ms)

    def _on_debug_face_image(self, msg: Image):
        if self.camera_frame_count == 0:
            self._on_camera_image(msg)

    # -------------------------------------------------------------------------
    # Vision Callbacks
    # -------------------------------------------------------------------------
    def _on_vision_json(self, msg: String):
        now = time.monotonic()
        self.vision_msg_count += 1
        self.vision_timestamps.append(now)

        if len(self.vision_timestamps) >= 2:
            dt = self.vision_timestamps[-1] - self.vision_timestamps[0]
            if dt > 0.01:
                self.vision_fps_rolling = (len(self.vision_timestamps) - 1) / dt

        try:
            raw_data = json.loads(msg.data)
            faces = raw_data.get("faces", []) if isinstance(raw_data, dict) else (raw_data if isinstance(raw_data, list) else [])
            self.visual_faces_count = len(faces)
            if faces:
                primary = faces[0]
                self.visual_yaw_deg = float(primary.get("camera_azimuth_deg", primary.get("azimuth_deg", primary.get("yaw_deg", 0.0))))
                self.visual_conf = float(primary.get("confidence", 0.85))
                self.visual_last_time = now
                dist_val = float(primary.get("distance_m", self.visual_user_distance))
                self.visual_events.append({
                    "time": round(now - self.start_time, 2),
                    "face_yaw_deg": round(self.visual_yaw_deg, 2),
                    "confidence": round(self.visual_conf, 2),
                    "distance_m": round(dist_val, 2),
                    "tracking_error": round(self.cmd_head_yaw - self.act_head_yaw, 2),
                })
                # Check if this face detection confirms any recent acoustic orientation
                for ev in reversed(self.audio_events[-5:]):
                    if (now - (ev["time"] + self.start_time)) <= 2.5:
                        face_body_yaw = wrap_deg(self.act_head_yaw + self.visual_yaw_deg)
                        if abs(wrap_deg(face_body_yaw - ev["target_body_yaw"])) <= 18.0:
                            ev["face_seen"] = True
                            ev["face_distance_m"] = round(dist_val, 2)
            else:
                self.visual_conf = 0.0
        except Exception:
            pass

    def _on_vision_head_yaw(self, msg: Float32):
        self.visual_yaw_deg = float(msg.data)

    def _on_user_distance(self, msg: Float32):
        self.visual_user_distance = float(msg.data)

    def _on_user_emotion(self, msg: String):
        self.visual_user_emotion = str(msg.data)

    def _on_recognized_person(self, msg: String):
        try:
            data = json.loads(msg.data)
            if isinstance(data, dict) and data.get("is_known", False):
                self.visual_recognized_name = f"{data.get('name', 'Bilinmeyen')} ({data.get('confidence', 0.0):.2f})"
        except Exception:
            self.visual_recognized_name = str(msg.data)

    def _on_looking_at_robot(self, msg: Bool):
        self.visual_looking_at_robot = bool(msg.data)

    def _on_person_detected(self, msg: Bool):
        if not msg.data and (time.monotonic() - self.visual_last_time > 0.5):
            self.visual_faces_count = 0
            self.visual_conf = 0.0

    # -------------------------------------------------------------------------
    # Audio & STT Callbacks
    # -------------------------------------------------------------------------
    def _on_stt_text(self, msg: String):
        clean_text = str(msg.data).strip()
        if clean_text:
            self.latest_stt_transcript = clean_text
            self.latest_stt_time = time.monotonic()

    def _on_audio_doa(self, msg: Float32):
        val = float(msg.data)
        now = time.monotonic()
        self.audio_total_events += 1

        # ReSpeaker DOA (0..359° clockwise) -> Relative bearing (positive=left)
        raw = val % 360.0
        rel_bearing = -(raw if raw <= 180.0 else raw - 360.0)
        target_body_yaw = wrap_deg(self.act_head_yaw + rel_bearing)

        # Conversational FOV (±75°), robot speaking gate, and confidence evaluation
        is_in_fov = abs(rel_bearing) <= 75.0
        is_speaking = bool(self.robot_speaking)
        conf = max(0.0, min(1.0, float(self.audio_doa_conf)))

        if is_in_fov and not is_speaking and conf >= 0.35:
            self.audio_accepted_events += 1
            status = "KABUL (Yöneldi)"
        elif is_speaking:
            self.audio_rejected_events += 1
            status = "RED (Eko Bastırıldı)"
        elif not is_in_fov:
            self.audio_rejected_events += 1
            status = "RED (Açı Dışı > 75°)"
        else:
            self.audio_rejected_events += 1
            status = "RED (Düşük Güven)"

        recent_stt = self.latest_stt_transcript if (now - self.latest_stt_time < 3.5) else ""

        if self.audio_doa_deg is None or abs(val - self.audio_doa_deg) > 4.0 or (now - self.audio_last_time > 0.8):
            self.audio_events.append({
                "time": round(now - self.start_time, 2),
                "doa_deg": round(val, 1),
                "rel_bearing_deg": round(rel_bearing, 1),
                "head_yaw_start": round(self.act_head_yaw, 2),
                "target_body_yaw": round(target_body_yaw, 2),
                "confidence": round(conf, 2),
                "status": status,
                "is_speaking": is_speaking,
                "speech_text": recent_stt,
                "final_head_yaw": round(self.act_head_yaw, 2),
                "tracking_error": round(abs(self.act_head_yaw - target_body_yaw), 2),
                "face_seen": False,
                "face_distance_m": 0.0,
            })
        self.audio_doa_deg = val
        self.audio_last_time = now

    def _on_doa_confidence(self, msg: Float32):
        self.audio_doa_conf = max(0.0, min(1.0, float(msg.data)))

    # -------------------------------------------------------------------------
    # Actuator & State Callbacks
    # -------------------------------------------------------------------------
    def _on_active_target(self, msg: String):
        self.active_target_json = msg.data

    def _on_cmd_pos(self, msg: Float32):
        self.cmd_head_yaw = float(msg.data)

    def _on_head_cmd(self, msg):
        self.cmd_head_yaw = float(msg.angle_deg)

    def _on_head_state(self, msg):
        now = time.monotonic()
        self.act_head_yaw = float(msg.position_deg)
        self.act_head_vel = float(msg.velocity_deg_s)
        self.head_moving = bool(msg.moving)
        self.head_stall = bool(getattr(msg, "fault_code", 0) == 4)
        self.max_abs_vel = max(self.max_abs_vel, abs(self.act_head_vel))
        err = self.cmd_head_yaw - self.act_head_yaw
        self.tracking_errors.append(abs(err))
        self.sample_count += 1

        # Update settle telemetry for recent acoustic events
        for ev in reversed(self.audio_events[-3:]):
            if (now - (ev["time"] + self.start_time)) <= 1.5:
                ev["final_head_yaw"] = round(self.act_head_yaw, 2)
                ev["tracking_error"] = round(abs(self.act_head_yaw - ev["target_body_yaw"]), 2)

    def _on_joint_states(self, msg: JointState):
        if "head_yaw_joint" in msg.name:
            idx = msg.name.index("head_yaw_joint")
            if HeadState is None or self.act_head_yaw == 0.0:
                self.act_head_yaw = math.degrees(msg.position[idx])
                self.act_head_vel = math.degrees(msg.velocity[idx])

    def _on_gaze_state(self, msg):
        now = time.monotonic()
        dt_dwell = now - self._last_fsm_dwell_stamp
        if self.gaze_state in self.state_dwell_times:
            self.state_dwell_times[self.gaze_state] += dt_dwell
        self._last_fsm_dwell_stamp = now

        state_val = getattr(msg, "state", 0)
        current_st = STATE_NAMES.get(state_val, f"STATE_{state_val}")
        if current_st != self.prev_gaze_state:
            self.state_transitions.append({
                "time": round(now - self.start_time, 2),
                "from_state": self.prev_gaze_state,
                "to_state": current_st,
                "head_yaw": round(self.act_head_yaw, 2),
                "target_yaw": round(float(getattr(msg, "desired_yaw_deg", 0.0)), 2),
            })
            self.prev_gaze_state = current_st

        self.gaze_state = current_st
        prio_val = getattr(msg, "priority", 0)
        self.gaze_priority = PRIORITY_NAMES.get(prio_val, f"PRIO_{prio_val}")
        self.gaze_desired_yaw = float(getattr(msg, "desired_yaw_deg", 0.0))
        self.gaze_planned_yaw = float(getattr(msg, "planned_yaw_deg", 0.0))
        self.gaze_at_target = bool(getattr(msg, "at_target", False))
        self.gaze_target_valid = bool(getattr(msg, "target_valid", False))
        self.gaze_target_conf = float(getattr(msg, "target_confidence", 0.0))
        self.gaze_target_id = str(getattr(msg, "active_target_id", "None"))

    def _on_speaking(self, msg: Bool):
        self.robot_speaking = bool(msg.data)


def render_dashboard(node: SocialGazeLiveMonitor):
    now = time.monotonic()
    audio_fresh = (now - node.audio_last_time < 1.5) and (node.audio_doa_deg is not None)
    vision_fresh = (now - node.visual_last_time < 1.5) and (node.visual_yaw_deg is not None)

    # Frame delta statistics
    deltas = list(node.camera_frame_deltas)
    avg_delta_ms = (sum(deltas) / len(deltas)) if deltas else 0.0
    min_delta_ms = min(deltas) if deltas else 0.0
    max_delta_ms = max(deltas) if deltas else 0.0
    jitter_ms = (math.sqrt(sum((d - avg_delta_ms)**2 for d in deltas) / len(deltas))) if len(deltas) > 1 else 0.0

    # Color helpers
    cam_color = "\033[1;32m" if node.camera_fps_rolling >= 24.0 else ("\033[1;33m" if node.camera_fps_rolling >= 12.0 else "\033[1;31m")
    vis_color = "\033[1;32m" if node.vision_fps_rolling >= 20.0 else ("\033[1;33m" if node.vision_fps_rolling >= 10.0 else "\033[1;31m")

    lines = []
    lines.append("=" * 80)
    lines.append("       ASTRO SOCIAL ROBOT — REAL-TIME SOCIAL GAZE & VISION FLUIDITY MONITOR")
    lines.append("=" * 80)

    # 1. Camera Stream Fluidity & Hardware Telemetry
    lines.append("\n[1] CAMERA HARDWARE STREAM & FLUIDITY (OAK-D LITE):")
    lines.append(f"  • Stream Resolution / Format : {node.camera_resolution} ({node.camera_encoding})")
    lines.append(f"  • Live Camera Frame Rate     : {cam_color}{node.camera_fps_rolling:.1f} FPS\033[0m (Total: {node.camera_frame_count} frames)")
    lines.append(f"  • Frame Interval (Jitter)    : {avg_delta_ms:.1f} ms (Min: {min_delta_ms:.1f}ms, Max: {max_delta_ms:.1f}ms, Jitter: ±{jitter_ms:.1f}ms)")
    if node.camera_latencies_ms:
        avg_lat = sum(node.camera_latencies_ms) / len(node.camera_latencies_ms)
        lines.append(f"  • Pipeline Transport Latency : {avg_lat:.1f} ms")

    # 2. Vision Perception & Biometrics
    lines.append("\n[2] SPATIAL VISION & BIOMETRIC RECOGNITION:")
    vis_hz_str = f"{vis_color}{node.vision_fps_rolling:.1f} Hz\033[0m" if node.vision_fps_rolling > 0 else "0.0 Hz"
    lines.append(f"  • Face Detector Rate         : {vis_hz_str} (Processed: {node.vision_msg_count} cycles)")
    vis_str = f"{node.visual_yaw_deg:+.1f}° (Conf: {node.visual_conf*100:.0f}%, Faces: {node.visual_faces_count})" if vision_fresh else "NO FACE DETECTED"
    lines.append(f"  • Visual Face Azimuth        : {vis_str}")
    lines.append(f"  • Distance & Emotion         : {node.visual_user_distance:.2f} m | Duygu: \033[1;33m{node.visual_user_emotion.upper()}\033[0m | Göz Teması: {'✅ EVET' if node.visual_looking_at_robot else '❌ YOK'}")
    lines.append(f"  • Recognized Person          : \033[1;36m{node.visual_recognized_name}\033[0m")

    # 3. Acoustic Perception
    lines.append("\n[3] ACOUSTIC DOA PERCEPTION (RESPEAKER):")
    audio_str = f"{node.audio_doa_deg:+.1f}° (Conf: {node.audio_doa_conf*100:.0f}%)" if audio_fresh else "SILENT / NO ACTIVE SPEECH"
    lines.append(f"  • Direction of Arrival (DOA) : {audio_str}")
    lines.append(f"  • Acoustic Statistics        : {node.audio_total_events} events (Kabul: {node.audio_accepted_events}, Red: {node.audio_rejected_events})")
    lines.append(f"  • Robot Self-Speech Gate     : {'🔴 KONUŞUYOR (EKO BASTIRMA AKTİF)' if node.robot_speaking else '🟢 DİNLİYOR (DİKKAT AÇIK)'}")
    if node.latest_stt_transcript and (now - node.latest_stt_time < 5.0):
        lines.append(f"  • Son Algılanan Söz          : \033[1;32m\"{node.latest_stt_transcript}\"\033[0m")

    # 4. Gaze State Machine & Trajectory
    lines.append("\n[4] SOCIAL GAZE POLICY & FSM:")
    lines.append(f"  • Active Gaze State          : \033[1;36m{node.gaze_state}\033[0m (Öncelik: {node.gaze_priority})")
    lines.append(f"  • Desired Target Yaw         : {node.gaze_desired_yaw:+.2f}° (Conf: {node.gaze_target_conf:.2f}, Valid: {node.gaze_target_valid})")
    lines.append(f"  • Motion Planned S-Curve     : {node.gaze_planned_yaw:+.2f}°")
    lines.append(f"  • Foveated / On Target       : {'✅ KİLİTLENDİ' if node.gaze_at_target else '⏳ HEDEFE YÖNELİYOR'}")

    # 5. Actuator Execution
    err = node.cmd_head_yaw - node.act_head_yaw
    lines.append("\n[5] CLOSED-LOOP HEAD MOTOR (50 Hz PID):")
    lines.append(f"  • Commanded vs Physical Yaw  : Cmd: {node.cmd_head_yaw:+.2f}° | Act: \033[1;32m{node.act_head_yaw:+.2f}°\033[0m")
    lines.append(f"  • Angular Velocity           : {node.act_head_vel:+.1f}°/s (Max: {node.max_abs_vel:.1f}°/s)")
    lines.append(f"  • Steady-State Error         : {err:+.2f}° ({'★ MÜKEMMEL' if abs(err) <= 1.2 else 'TAKİP EDİYOR'})")
    lines.append(f"  • Motor Durumu               : {'🔄 DÖNÜYOR' if node.head_moving else '⏸️ SABİT / DWELLING'}")

    lines.append("\n" + "-" * 80)
    lines.append("  [Canlı Test]: Kameranın karşısında yürüyün ve konuşun. Raporu görmek için Ctrl+C yapın.")
    lines.append("-" * 80)

    sys.stdout.write("\033[H\033[J" + "\n".join(lines) + "\n")
    sys.stdout.flush()


def generate_flight_report(node: SocialGazeLiveMonitor):
    duration = time.monotonic() - node.start_time
    avg_err = (sum(node.tracking_errors) / len(node.tracking_errors)) if node.tracking_errors else 0.0
    rms_err = math.sqrt(sum(e**2 for e in node.tracking_errors) / len(node.tracking_errors)) if node.tracking_errors else 0.0

    # Camera deltas
    deltas = list(node.camera_frame_deltas)
    avg_delta_ms = (sum(deltas) / len(deltas)) if deltas else 0.0
    min_delta_ms = min(deltas) if deltas else 0.0
    max_delta_ms = max(deltas) if deltas else 0.0
    jitter_ms = (math.sqrt(sum((d - avg_delta_ms)**2 for d in deltas) / len(deltas))) if len(deltas) > 1 else 0.0
    avg_cam_fps = (node.camera_frame_count / max(0.1, duration)) if node.camera_frame_count > 0 else 0.0
    avg_vis_fps = (node.vision_msg_count / max(0.1, duration)) if node.vision_msg_count > 0 else 0.0

    print("\n\n" + "=" * 100)
    print("       ASTRO SOCIAL GAZE LIVE TEST — FLIGHT RECORDER & FLUIDITY REPORT")
    print("=" * 100)
    print(f"Test Süresi                  : {duration:.2f} saniye")
    print(f"Toplanan Telemetri Örnekleri : {node.sample_count} örnek ({node.sample_count / max(0.1, duration):.1f} Hz)")
    print(f"Maksimum Açısal Hız          : {node.max_abs_vel:.1f}°/s")
    print(f"Ortalama Takip Hatası        : {avg_err:.2f}° (RMS: {rms_err:.2f}°)")

    # 1. Camera Fluidity & Hardware Stream Report
    print("\n[1] KAMERA VE GÖRÜNTÜ İŞLEME AKICILIĞI (CAMERA FLUIDITY):")
    print(f"  • Kamera Çözünürlüğü / Format: {node.camera_resolution} ({node.camera_encoding})")
    print(f"  • Ortalama Kamera Akış Hızı  : {avg_cam_fps:.1f} FPS (Toplam: {node.camera_frame_count} kare)")
    print(f"  • Yüz Algılama Düğüm Hızı    : {avg_vis_fps:.1f} Hz (Toplam: {node.vision_msg_count} kare)")
    print(f"  • Kareler Arası Gecikme (dt) : {avg_delta_ms:.1f} ms (Min: {min_delta_ms:.1f}ms, Max: {max_delta_ms:.1f}ms, Jitter: ±{jitter_ms:.1f}ms)")
    if node.camera_latencies_ms:
        mean_lat = sum(node.camera_latencies_ms) / len(node.camera_latencies_ms)
        print(f"  • Donanım → Düğüm İletim Gecikmesi: {mean_lat:.1f} ms")

    # 2. State Machine Timeline & Dwell Breakdown
    print("\n[2] DURUM MAKİNESİ GEÇİŞLERİ VE KALMA SÜRELERİ (FSM DWELL BREAKDOWN):")
    total_dwell = sum(node.state_dwell_times.values())
    if total_dwell > 0:
        for st_name, dw_t in sorted(node.state_dwell_times.items(), key=lambda x: x[1], reverse=True):
            pct = (dw_t / total_dwell) * 100.0
            if pct > 0.5:
                print(f"  • {st_name:<20}: {dw_t:6.2f}s (%{pct:5.1f})")

    print("\n[3] DURUM GEÇİŞ ZAMAN ÇİZELGESİ (TRANSITION TIMELINE):")
    if node.state_transitions:
        print(f"{'Zaman (s)':<10} | {'Önceki Durum':<18} -> {'Yeni Durum':<18} | {'Kafa Konumu':<12} | {'Hedef Açı'}")
        print("-" * 80)
        for st in node.state_transitions[-20:]:
            print(f"{st['time']:<10.2f} | {st['from_state']:<18} -> {st['to_state']:<18} | {st['head_yaw']:>+6.2f}°      | {st['target_yaw']:>+6.2f}°")
        if len(node.state_transitions) > 20:
            print(f"  ... ({len(node.state_transitions) - 20} önceki durum geçişi rapordan kısaltıldı)")
    else:
        print("  (Test süresince durum değişikliği olmadı: Sabit " + node.gaze_state + ")")

    # 3. Acoustic Orienting & Saccade Audit Table
    print("\n[4] İŞİTSEL YÖNELME VE SES TAKİP DENETİMİ (ACOUSTIC ORIENTING & SACCADE AUDIT):")
    print(f"  • Toplam Algılanan Ses Olayı : {node.audio_total_events} (Kabul: {node.audio_accepted_events}, Red: {node.audio_rejected_events})")
    if node.audio_events:
        print(f"{'Zaman (s)':<9} | {'Ses Açısı':<10} | {'Kafa Başlangıç':<14} | {'Hedef Açı':<10} | {'Karar / Eylem':<20} | {'Son Kafa':<10} | {'Hata':<7} | {'Yüz Görüldü?':<12} | {'Söylenen Söz'}")
        print("-" * 120)
        for ev in node.audio_events[-15:]:
            face_str = f"✅ EVET ({ev.get('face_distance_m', 0):.2f}m)" if ev.get("face_seen", False) else "❌ YOK"
            spk_str = f'"{ev["speech_text"]}"' if ev.get("speech_text") else "-"
            print(f"{ev['time']:<9.2f} | {ev['doa_deg']:>+6.1f}°     | {ev['head_yaw_start']:>+6.2f}°        | {ev['target_body_yaw']:>+6.2f}°   | {ev['status']:<20} | {ev['final_head_yaw']:>+6.2f}°   | {ev['tracking_error']:>5.2f}° | {face_str:<12} | {spk_str}")
        if len(node.audio_events) > 15:
            print(f"  ... ({len(node.audio_events) - 15} önceki ses olayı rapordan kısaltıldı)")
    else:
        print("  • Ses olayı algılanmadı (Sessiz ortam).")

    # 4. Visual Face Tracking Summary
    print("\n[5] GÖRSEL YÜZ TAKİBİ (VISUAL TRACKING SUMMARY):")
    if node.visual_events:
        print(f"  • Toplam Takip Edilen Yüz Karesi : {len(node.visual_events)} kare")
        mean_vis_conf = sum(e['confidence'] for e in node.visual_events) / len(node.visual_events)
        print(f"  • Ortalama Tespit Güveni         : %{mean_vis_conf*100:.1f}")
        for i, ev in enumerate(node.visual_events[-5:], 1):
            print(f"    - Kare {i}: {ev['time']}s | Yüz Açısı = {ev['face_yaw_deg']:+.1f}° | Mesafe = {ev.get('distance_m', 0.0):.2f}m | Hata = {ev['tracking_error']:+.2f}°")
    else:
        print("  • Görsel yüz tespiti algılanmadı.")

    # 5. Stability & Pipeline Verdict
    print("\n[6] SİSTEM VE AKICILIK DEĞERLENDİRMESİ (SYSTEM STABILITY VERDICT):")
    fps_healthy = (avg_cam_fps >= 20.0)
    tracking_healthy = (avg_err <= 15.0)
    
    status_flags = []
    if fps_healthy:
        status_flags.append("✅ KAMERA AKICI (30 FPS Hedefinde)")
    else:
        status_flags.append(f"⚠️ KAMERA HIZI DÜŞÜK ({avg_cam_fps:.1f} FPS)")

    if tracking_healthy:
        status_flags.append(f"✅ HASSAS TAKİP (RMS: {rms_err:.1f}°)")
    else:
        status_flags.append(f"⚠️ TAKİP HATASI (RMS: {rms_err:.1f}°)")

    for flag in status_flags:
        print(f"  • {flag}")

    print("\n" + "=" * 100)
    print("Kabul Özeti: Test başarıyla tamamlandı. Detaylı JSON telemetri kaydedildi.")
    print("=" * 100 + "\n")

    # Save JSON Log
    os.makedirs("ros2_ws/data", exist_ok=True)
    report_file = "ros2_ws/data/social_gaze_live_report.json"
    report_data = {
        "duration_s": round(duration, 2),
        "total_samples": node.sample_count,
        "camera_metrics": {
            "resolution": node.camera_resolution,
            "encoding": node.camera_encoding,
            "total_frames": node.camera_frame_count,
            "average_fps": round(avg_cam_fps, 2),
            "frame_delta_avg_ms": round(avg_delta_ms, 2),
            "frame_delta_min_ms": round(min_delta_ms, 2),
            "frame_delta_max_ms": round(max_delta_ms, 2),
            "frame_jitter_ms": round(jitter_ms, 2),
        },
        "vision_metrics": {
            "total_messages": node.vision_msg_count,
            "detection_fps": round(avg_vis_fps, 2),
            "visual_events_count": len(node.visual_events),
        },
        "max_angular_velocity_deg_s": round(node.max_abs_vel, 2),
        "mean_tracking_error_deg": round(avg_err, 2),
        "rms_tracking_error_deg": round(rms_err, 2),
        "fsm_dwell_times_s": {k: round(v, 2) for k, v in node.state_dwell_times.items()},
        "state_transitions": node.state_transitions,
        "audio_events": node.audio_events,
    }
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)


def main():
    rclpy.init()
    node = SocialGazeLiveMonitor()
    
    from rclpy.executors import SingleThreadedExecutor
    import threading

    executor = SingleThreadedExecutor()
    executor.add_node(node)

    def _safe_spin():
        try:
            executor.spin()
        except Exception:
            pass

    spin_thread = threading.Thread(target=_safe_spin, daemon=True)
    spin_thread.start()

    try:
        while rclpy.ok():
            time.sleep(0.1)
            render_dashboard(node)
    except KeyboardInterrupt:
        pass
    finally:
        generate_flight_report(node)
        try:
            executor.shutdown()
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
