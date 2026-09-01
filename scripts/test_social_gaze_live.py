#!/usr/bin/env python3
"""ASTRO Robot — Real-Time Audiovisual Social Gaze Live Monitor & Test Tool.

Subscribes to all perception, fusion, state machine, and actuator topics to provide
a live terminal dashboard for verifying:
  1. Acoustic DOA (ReSpeaker Sound Localization)
  2. Visual Face Tracking (OAK-D Lite Foveation & Gaze Direction)
  3. Multimodal Audio-Visual Association & Target State
  4. 9-State Social Gaze State Machine Transitions
  5. S-Curve Motion Execution & Head Closed-Loop Tracking

Usage:
  python3 scripts/test_social_gaze_live.py
"""

import json
import math
import os
import sys
import time
from typing import Optional

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from std_msgs.msg import Bool, Float32, Int32, String
    from sensor_msgs.msg import JointState
    try:
        from astro_base.msg import GazeStatus, HeadCmd, HeadState
    except ImportError:
        GazeStatus = HeadCmd = HeadState = None
except ImportError as exc:
    print(f"Error importing ROS 2 packages: {exc}")
    sys.exit(1)


STATE_NAMES = {
    0: "IDLE (0)",
    1: "SEARCHING (1)",
    2: "AUDIO_ACQUIRE (2)",
    3: "ORIENTING (3)",
    4: "VISUAL_ACQUIRE (4)",
    5: "TRACKING (5)",
    6: "HOLD (6)",
    7: "TARGET_LOST (7)",
    8: "RETURNING (8)",
}

PRIORITY_NAMES = {
    0: "IDLE (0)",
    1: "VISUAL_PERSON (1)",
    2: "ACTIVE_SPEAKER (2)",
    3: "DIALOGUE (3)",
    4: "GESTURE (4)",
    5: "SAFETY (5)",
}


class SocialGazeLiveMonitor(Node):
    def __init__(self):
        super().__init__("social_gaze_live_monitor")

        # Telemetry State
        self.audio_doa_deg: Optional[float] = None
        self.audio_last_time: float = 0.0
        self.visual_yaw_deg: Optional[float] = None
        self.visual_conf: float = 0.0
        self.visual_faces_count: int = 0
        self.visual_last_time: float = 0.0

        self.gaze_state: str = "IDLE (0)"
        self.gaze_priority: str = "IDLE (0)"
        self.gaze_desired_yaw: float = 0.0
        self.gaze_planned_yaw: float = 0.0
        self.gaze_at_target: bool = True
        self.gaze_target_valid: bool = False
        self.gaze_target_conf: float = 0.0
        self.gaze_target_id: str = "None"
        self.active_target_json: str = "{}"

        self.cmd_head_yaw: float = 0.0
        self.act_head_yaw: float = 0.0
        self.act_head_vel: float = 0.0
        self.head_moving: bool = False
        self.head_stall: bool = False
        self.robot_speaking: bool = False

        qos_be = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)

        # Subscriptions
        self.create_subscription(Float32, "/audio/doa", self._on_audio_doa, 10)
        self.create_subscription(Float32, "/audio/doa_deg", self._on_audio_doa, 10)
        self.create_subscription(String, "/vision/detections_json", self._on_vision_json, 10)
        self.create_subscription(String, "/vision/faces", self._on_vision_json, 10)
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

    def _on_audio_doa(self, msg: Float32):
        self.audio_doa_deg = float(msg.data)
        self.audio_last_time = time.monotonic()

    def _on_vision_json(self, msg: String):
        try:
            data = json.loads(msg.data)
            faces = data.get("faces", [])
            self.visual_faces_count = len(faces)
            if faces:
                primary = faces[0]
                self.visual_yaw_deg = float(primary.get("azimuth_deg", primary.get("yaw_deg", 0.0)))
                self.visual_conf = float(primary.get("confidence", 0.85))
                self.visual_last_time = time.monotonic()
            else:
                self.visual_conf = 0.0
        except Exception:
            pass

    def _on_active_target(self, msg: String):
        self.active_target_json = msg.data

    def _on_cmd_pos(self, msg: Float32):
        self.cmd_head_yaw = float(msg.data)

    def _on_head_cmd(self, msg):
        self.cmd_head_yaw = float(msg.angle_deg)

    def _on_head_state(self, msg):
        self.act_head_yaw = float(msg.position_deg)
        self.act_head_vel = float(msg.velocity_deg_s)
        self.head_moving = bool(msg.moving)
        self.head_stall = bool(getattr(msg, "fault_code", 0) == 4)

    def _on_joint_states(self, msg: JointState):
        if "head_yaw_joint" in msg.name:
            idx = msg.name.index("head_yaw_joint")
            if HeadState is None or self.act_head_yaw == 0.0:
                self.act_head_yaw = math.degrees(msg.position[idx])
                self.act_head_vel = math.degrees(msg.velocity[idx])

    def _on_gaze_state(self, msg):
        state_val = getattr(msg, "state", 0)
        self.gaze_state = STATE_NAMES.get(state_val, f"STATE_{state_val}")
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

    # ANSI Clear Screen and Home (Single Buffer)
    lines = []
    lines.append("=" * 80)
    lines.append("       ASTRO SOCIAL ROBOT — REAL-TIME MULTIMODAL SOCIAL GAZE DASHBOARD")
    lines.append("=" * 80)

    # 1. Perception Layer
    lines.append("\n[1] PERCEPTION INPUTS:")
    audio_str = f"{node.audio_doa_deg:+.1f}° (ACTIVE)" if audio_fresh else "SILENT / NO SIGNAL"
    lines.append(f"  • Acoustic DOA (ReSpeaker) : {audio_str}")
    
    vis_str = f"{node.visual_yaw_deg:+.1f}° (Conf: {node.visual_conf:.2f}, Faces: {node.visual_faces_count})" if vision_fresh else "NO FACE DETECTED"
    lines.append(f"  • Visual Face (OAK-D Lite) : {vis_str}")
    lines.append(f"  • Robot Self-Speech Gate   : {'🔴 SPEAKING (ECHO SUPPRESSION ACTIVE)' if node.robot_speaking else '🟢 LISTENING / ATTENTIVE'}")

    # 2. Gaze Policy & State Machine Layer
    lines.append("\n[2] SOCIAL GAZE POLICY & FSM:")
    lines.append(f"  • Active Gaze State        : \033[1;36m{node.gaze_state}\033[0m")
    lines.append(f"  • Priority Source          : {node.gaze_priority}")
    lines.append(f"  • Desired Gaze Target      : {node.gaze_desired_yaw:+.2f}° (Conf: {node.gaze_target_conf:.2f}, Valid: {node.gaze_target_valid})")
    lines.append(f"  • Motion Planned Trajectory: {node.gaze_planned_yaw:+.2f}°")
    lines.append(f"  • Target Acquired / Fixed  : {'✅ YES (FOVEATED)' if node.gaze_at_target else '⏳ SLEWING / CONVERGING'}")

    # 3. Motion Planning & Actuator Loop
    err = node.cmd_head_yaw - node.act_head_yaw
    lines.append("\n[3] ACTUATOR CLOSED-LOOP EXECUTION:")
    lines.append(f"  • Commanded Trajectory     : {node.cmd_head_yaw:+.2f}°")
    lines.append(f"  • Physical Head Position   : \033[1;32m{node.act_head_yaw:+.2f}°\033[0m")
    lines.append(f"  • Joint Angular Velocity   : {node.act_head_vel:+.1f}°/s")
    lines.append(f"  • Steady-State Error       : {err:+.2f}° ({'★ ON TARGET' if abs(err) <= 1.2 else 'TRACKING'})")
    lines.append(f"  • Actuator Moving Status   : {'🔄 SLEWING' if node.head_moving else '⏸️ SETTLED / DWELLING'}")

    lines.append("\n" + "-" * 80)
    lines.append("  [Canlı Test]: Robotun karşısında konuşun veya hareket edin. (Çıkış: Ctrl+C)")
    lines.append("-" * 80)

    # Print buffer cleanly at home position
    sys.stdout.write("\033[H\033[J" + "\n".join(lines) + "\n")
    sys.stdout.flush()


def main():
    rclpy.init()
    node = SocialGazeLiveMonitor()

    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)
            render_dashboard(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
