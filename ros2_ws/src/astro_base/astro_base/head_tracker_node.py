#!/usr/bin/env python3
"""ASTRO V1 — Social Sound-Localization & Head Tracking Node.

Controls robot head yaw orientation using ReSpeaker 4-Mic DOA (Direction of Arrival)
and multimodal perception with human-like social gaze behavior:
  - Acoustic energy & VAD gating (resists ambient background noise)
  - Self-voice suppression (zero tracking while robot is speaking)
  - Temporal consensus filtering (rejects momentary noise spikes & reverberation)
  - Deadband hysteresis (prevents micro-jitter and neck twitching)
  - Gaze dwell time (holds attention for >= 2.5s before switching target)
  - Smooth S-curve / slew-rate velocity limiting (max 45°/s, organic motion)
  - Idle return-to-center after sustained silence
"""

import collections
import json
import math
import os
import threading
import time
from typing import Deque, Optional, Tuple, Any

try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import Bool, Float32, String
except ImportError:
    rclpy = None
    class Node:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass
        def declare_parameter(self, name, default):
            pass
        def get_parameter(self, name):
            class _Param:
                def __init__(self, val): self.value = val
            # Map standard defaults
            defaults = {
                "enabled": True, "doa_offset_deg": 0.0, "doa_invert": False,
                "max_yaw_deg": 70.0, "min_yaw_deg": -70.0, "deadband_deg": 12.0,
                "min_dwell_time_s": 2.5, "idle_return_timeout_s": 8.0,
                "max_speed_deg_s": 45.0, "update_rate_hz": 20.0,
                "min_rms_threshold": 800.0, "noise_multiplier": 2.2,
                "consensus_window_size": 5, "consensus_threshold": 3,
                "consensus_tolerance_deg": 18.0
            }
            return _Param(defaults.get(name, 0.0))
        def get_logger(self):
            import logging
            return logging.getLogger("HeadTrackerNode")
        def create_subscription(self, *args, **kwargs):
            return None
        def create_publisher(self, *args, **kwargs):
            class _Pub:
                def publish(self, msg): pass
            return _Pub()
        def create_timer(self, *args, **kwargs):
            return None
        def destroy_node(self):
            pass
    class _MockMsg:
        data: Any = None
    Bool = Float32 = String = _MockMsg  # type: ignore

try:
    from astro_base.msg import HeadCmd
except ImportError:
    class HeadCmd:  # type: ignore
        angle_deg: float = 0.0


def doa_to_robot_yaw(doa_deg: float, offset_deg: float = 0.0, invert: bool = False) -> float:
    """Converts ReSpeaker circular DOA (0°..359° clockwise) to robot body yaw frame (-180°..+180°).

    Standard ReSpeaker 4-Mic mounting:
      - 0° = straight ahead (0° yaw)
      - 90° = right (+90° yaw)
      - 270° = left (-90° yaw)
      - 180° = directly behind (±180° yaw)
    """
    raw = (doa_deg + offset_deg) % 360.0
    if raw <= 180.0:
        yaw = raw
    else:
        yaw = raw - 360.0

    if invert:
        yaw = -yaw
    return yaw


class SocialGazeStateMachine:
    """Manages social gaze states: IDLE, ATTENDING, ENGAGED, RETURNING."""
    IDLE = "IDLE"
    ATTENDING = "ATTENDING"
    ENGAGED = "ENGAGED"
    RETURNING = "RETURNING"


class HeadTrackerNode(Node):
    """ROS 2 Node for intelligent sound-driven head orientation."""

    def __init__(self):
        super().__init__("head_tracker_node")

        # Declare parameters with configurable defaults
        self.declare_parameter("enabled", True)
        self.declare_parameter("doa_offset_deg", 0.0)
        self.declare_parameter("doa_invert", False)
        self.declare_parameter("max_yaw_deg", 70.0)
        self.declare_parameter("min_yaw_deg", -70.0)
        self.declare_parameter("deadband_deg", 12.0)
        self.declare_parameter("min_dwell_time_s", 2.5)
        self.declare_parameter("idle_return_timeout_s", 8.0)
        self.declare_parameter("max_speed_deg_s", 45.0)
        self.declare_parameter("update_rate_hz", 20.0)
        self.declare_parameter("min_rms_threshold", 800.0)
        self.declare_parameter("noise_multiplier", 2.2)
        self.declare_parameter("consensus_window_size", 5)
        self.declare_parameter("consensus_threshold", 3)
        self.declare_parameter("consensus_tolerance_deg", 18.0)

        # Load parameters
        self.enabled = bool(self.get_parameter("enabled").value)
        self.doa_offset_deg = float(self.get_parameter("doa_offset_deg").value)
        self.doa_invert = bool(self.get_parameter("doa_invert").value)
        self.max_yaw_deg = float(self.get_parameter("max_yaw_deg").value)
        self.min_yaw_deg = float(self.get_parameter("min_yaw_deg").value)
        self.deadband_deg = float(self.get_parameter("deadband_deg").value)
        self.min_dwell_time_s = float(self.get_parameter("min_dwell_time_s").value)
        self.idle_return_timeout_s = float(self.get_parameter("idle_return_timeout_s").value)
        self.max_speed_deg_s = float(self.get_parameter("max_speed_deg_s").value)
        self.update_rate_hz = float(self.get_parameter("update_rate_hz").value)
        self.min_rms_threshold = float(self.get_parameter("min_rms_threshold").value)
        self.noise_multiplier = float(self.get_parameter("noise_multiplier").value)
        self.consensus_window_size = int(self.get_parameter("consensus_window_size").value)
        self.consensus_threshold = int(self.get_parameter("consensus_threshold").value)
        self.consensus_tolerance_deg = float(self.get_parameter("consensus_tolerance_deg").value)

        # Publishers
        self.pub_head_cmd = self.create_publisher(HeadCmd, "/head_cmd", 10)
        self.pub_head_status = self.create_publisher(String, "/head/status", 10)

        # Subscribers
        self.create_subscription(Float32, "/audio/doa", self._on_doa, 10)
        self.create_subscription(Float32, "/audio/mic_level", self._on_mic_level, 10)
        self.create_subscription(Bool, "/audio/vad", self._on_vad, 10)
        self.create_subscription(Bool, "/tts/speaking", self._on_tts_speaking, 10)
        self.create_subscription(Bool, "/audio/playback_active", self._on_playback_active, 10)
        self.create_subscription(String, "/robot/emotion", self._on_emotion, 10)

        # State & Thread Safety
        self._lock = threading.Lock()
        self._current_yaw = 0.0
        self._target_yaw = 0.0
        self._filtered_target_yaw = 0.0
        self._state = SocialGazeStateMachine.IDLE

        # Acoustic & Noise Tracking
        self._ambient_rms = 120.0
        self._latest_rms = 0.0
        self._vad_active = False
        self._is_speaking = False
        self._is_playback_active = False
        self._last_speech_time = 0.0
        self._last_gaze_switch_time = time.monotonic()
        self._last_update_time = time.monotonic()

        # Circular buffer for DOA temporal consensus
        self._doa_history: Deque[Tuple[float, float]] = collections.deque(maxlen=self.consensus_window_size)

        # Periodic control loop timer (20 Hz)
        timer_period = 1.0 / max(1.0, self.update_rate_hz)
        self._control_timer = self.create_timer(timer_period, self._control_loop)

        self.get_logger().info(
            f"🤖 [Head Tracker] Başlatıldı | Limitler: [{self.min_yaw_deg}°, {self.max_yaw_deg}°] | "
            f"Maks Hız: {self.max_speed_deg_s}°/s | Deadband: {self.deadband_deg}° | Dwell: {self.min_dwell_time_s}s"
        )

    def _on_doa(self, msg: Float32):
        """Processes raw acoustic Direction of Arrival from ReSpeaker."""
        if not self.enabled:
            return

        now = time.monotonic()
        raw_doa = float(msg.data)

        with self._lock:
            # 1. Self-Voice Gate: Ignore DOA if robot itself is playing audio/speaking
            if self._is_speaking or self._is_playback_active:
                return

            # 2. Acoustic Energy Gate: Verify sound is significantly louder than ambient noise
            adaptive_threshold = max(self.min_rms_threshold, self._ambient_rms * self.noise_multiplier)
            if self._latest_rms < adaptive_threshold and not self._vad_active:
                return

            # Convert to robot body frame yaw angle
            robot_yaw = doa_to_robot_yaw(raw_doa, offset_deg=self.doa_offset_deg, invert=self.doa_invert)

            # Record in consensus history (timestamp, yaw)
            self._doa_history.append((now, robot_yaw))
            self._last_speech_time = now

            # 3. Temporal Consensus Clustering: Check if at least N samples in recent window agree
            candidate_yaw = self._evaluate_consensus()
            if candidate_yaw is None:
                return

            # 4. Mechanical & Safety Clamping
            clamped_target = max(self.min_yaw_deg, min(self.max_yaw_deg, candidate_yaw))

            # 5. Gaze Dwell Time & Deadband Hysteresis
            dwell_elapsed = now - self._last_gaze_switch_time
            angle_diff = abs(clamped_target - self._current_yaw)

            # Must exceed deadband AND satisfy dwell time to initiate a new head gaze
            if angle_diff >= self.deadband_deg and dwell_elapsed >= self.min_dwell_time_s:
                self._target_yaw = clamped_target
                self._last_gaze_switch_time = now
                self._state = SocialGazeStateMachine.ATTENDING
                self.get_logger().info(
                    f"🎯 [Head Tracker Gaze]: DOA={raw_doa:.1f}° -> Hedef Yaw={clamped_target:.1f}° "
                    f"(Fark={angle_diff:.1f}°, RMS={self._latest_rms:.0f})"
                )

    def _evaluate_consensus(self) -> Optional[float]:
        """Finds cluster consensus in recent DOA history to filter reverberation & outlier spikes."""
        if len(self._doa_history) < self.consensus_threshold:
            return None

        recent_samples = [yaw for ts, yaw in self._doa_history]
        best_cluster = []

        for candidate in recent_samples:
            cluster = [y for y in recent_samples if abs(y - candidate) <= self.consensus_tolerance_deg]
            if len(cluster) > len(best_cluster):
                best_cluster = cluster

        if len(best_cluster) >= self.consensus_threshold:
            # Return cluster average
            return float(sum(best_cluster) / len(best_cluster))
        return None

    def _on_mic_level(self, msg: Float32):
        """Tracks RMS audio input energy and background ambient noise floor."""
        rms = float(msg.data)
        with self._lock:
            self._latest_rms = rms
            if not self._is_speaking and not self._is_playback_active and rms < 400.0:
                # Slowly track ambient background level
                self._ambient_rms = 0.95 * self._ambient_rms + 0.05 * rms

    def _on_vad(self, msg: Bool):
        with self._lock:
            self._vad_active = bool(msg.data)
            if self._vad_active:
                self._last_speech_time = time.monotonic()

    def _on_tts_speaking(self, msg: Bool):
        with self._lock:
            self._is_speaking = bool(msg.data)

    def _on_playback_active(self, msg: Bool):
        with self._lock:
            self._is_playback_active = bool(msg.data)

    def _on_emotion(self, msg: String):
        # Placeholder for future emotional head gestures (e.g. nodding, tilt)
        pass

    def _control_loop(self):
        """Periodic 20 Hz trajectory generator with slew-rate velocity limiting."""
        if not self.enabled:
            return

        now = time.monotonic()
        with self._lock:
            dt = max(0.001, now - self._last_update_time)
            self._last_update_time = now

            # Idle timeout: return head to 0° (neutral forward position) after prolonged silence
            if (now - self._last_speech_time) > self.idle_return_timeout_s:
                if abs(self._current_yaw) > 2.0:
                    self._target_yaw = 0.0
                    self._state = SocialGazeStateMachine.RETURNING
                else:
                    self._state = SocialGazeStateMachine.IDLE

            # Smooth Trajectory Generation: Slew-rate velocity limiting
            max_step = self.max_speed_deg_s * dt
            err = self._target_yaw - self._current_yaw

            if abs(err) <= max_step:
                self._current_yaw = self._target_yaw
            else:
                self._current_yaw += math.copysign(max_step, err)

            current_yaw_to_send = self._current_yaw
            target_yaw_snapshot = self._target_yaw
            state_snapshot = self._state

        # Publish smooth head command to /head_cmd
        cmd = HeadCmd()
        cmd.angle_deg = float(current_yaw_to_send)
        self.pub_head_cmd.publish(cmd)

        # Periodic status telemetry
        status = {
            "current_yaw_deg": round(current_yaw_to_send, 1),
            "target_yaw_deg": round(target_yaw_snapshot, 1),
            "state": state_snapshot,
            "ambient_rms": round(self._ambient_rms, 1),
            "is_speaking": self._is_speaking,
        }
        status_msg = String()
        status_msg.data = json.dumps(status)
        self.pub_head_status.publish(status_msg)


def main(args=None):
    rclpy.init(args=args)
    node = HeadTrackerNode()
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
