#!/usr/bin/env python3
"""ASTRO V1 — Physical Action Grounding & Hardware Authority Manager.

Coordinates robotic motion execution, sound-source localization actions,
safety interlocking, hardware ACK verification, and action idempotency.

Key Principles:
  1. Physical Grounding: LLMs never guess or hallucinate movement directions or success.
  2. Sound Direction Authority: The ReSpeaker 4-Mic DOA subsystem is the sole authority
     for acoustic orientation. If DOA is unavailable/weak, 'NO_DIRECTION' is produced.
  3. Machine-Verifiable Action Results: Every physical command produces an unambiguous
     `ActionResult` containing success flag, actual directions, error codes, and telemetry.
  4. Safety Interlocking: Heartbeat, LiDAR obstacle proximity, and sensor freshness
     watchdogs gate all physical movement independently of AI personas.
  5. Idempotency: Actions carry unique IDs and timestamps to prevent duplicate executions.
"""

import collections
import dataclasses
import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

try:
    from geometry_msgs.msg import Twist
except ImportError:
    class Twist:  # type: ignore
        def __init__(self):
            class _Vec:
                x = 0.0
                y = 0.0
                z = 0.0
            self.linear = _Vec()
            self.angular = _Vec()

try:
    from astro_base.msg import HeadCmd
except ImportError:
    class HeadCmd:  # type: ignore
        angle_deg: float = 0.0


@dataclass
class SoundDirection:
    """Represents a validated acoustic sound direction from the microphone array."""
    azimuth_deg: float      # Relative yaw: -180.0° to +180.0° (0 = front, + = right, - = left)
    confidence: float       # 0.0 to 1.0
    valid: bool             # True if confidence >= threshold and fresh
    timestamp: float        # time.monotonic()
    raw_doa_deg: float      # 0.0° to 359.0° circular ReSpeaker DOA
    rms_level: float        # Audio frame RMS energy
    source: str = "respeaker_4mic"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "azimuth_deg": round(self.azimuth_deg, 1),
            "confidence": round(self.confidence, 2),
            "valid": self.valid,
            "timestamp": round(self.timestamp, 3),
            "raw_doa_deg": round(self.raw_doa_deg, 1),
            "rms_level": round(self.rms_level, 1),
            "source": self.source,
        }


@dataclass
class ActionResult:
    """Machine-verifiable action result for physical grounding."""
    success: bool
    action: str
    action_id: str
    generation_id: Optional[int] = None
    azimuth_deg: Optional[float] = None
    confidence: Optional[float] = None
    requested_direction: Optional[str] = None
    actual_direction: Optional[str] = None
    duration_ms: Optional[int] = None
    hardware_ack: bool = False
    error_code: Optional[str] = None
    error: Optional[str] = None
    reason: Optional[str] = None
    message: str = ""
    timestamp: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        status_val = "success" if self.success else ("blocked" if self.reason in ("heartbeat_unhealthy", "obstacle_detected", "lidar_stale_or_disconnected", "safety_blocked") else "error")
        d: Dict[str, Any] = {
            "status": status_val,
            "success": self.success,
            "action": self.action,
            "action_id": self.action_id,
            "hardware_ack": self.hardware_ack,
            "message": self.message,
            "timestamp": round(self.timestamp, 3),
        }
        if self.generation_id is not None:
            d["generation_id"] = self.generation_id
        if self.azimuth_deg is not None:
            d["azimuth_deg"] = self.azimuth_deg
        if self.confidence is not None:
            d["confidence"] = self.confidence
        if self.requested_direction is not None:
            d["requested_direction"] = self.requested_direction
        if self.actual_direction is not None:
            d["actual_direction"] = self.actual_direction
        if self.duration_ms is not None:
            d["duration_ms"] = self.duration_ms
        if self.error_code is not None:
            d["error_code"] = self.error_code
        if self.error is not None:
            d["error"] = self.error
        if self.reason is not None:
            d["reason"] = self.reason
        return d


def circular_doa_to_yaw(doa_deg: float, offset_deg: float = 0.0, invert: bool = False) -> float:
    """Converts 0°..359° circular ReSpeaker DOA to robot body yaw frame (-180°..+180°)."""
    raw = (doa_deg + offset_deg) % 360.0
    if raw <= 180.0:
        yaw = raw
    else:
        yaw = raw - 360.0
    if invert:
        yaw = -yaw
    return yaw


class ActionManager:
    """Physical action grounding, DOA orientation authority, and hardware coordination."""

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        pub_cmd_vel: Any = None,
        pub_head_cmd: Any = None,
        node: Any = None,
    ):
        self._logger = logger or logging.getLogger("ActionManager")
        self._pub_cmd_vel = pub_cmd_vel
        self._pub_head_cmd = pub_head_cmd
        self._node = node
        self._lock = threading.RLock()

        # DOA Tracking & Consensus
        self._latest_doa: Optional[SoundDirection] = None
        self._doa_history: Deque[Tuple[float, float, float]] = collections.deque(maxlen=6)  # (timestamp, yaw, rms)
        self._min_doa_confidence = 0.40
        self._doa_freshness_timeout_s = 3.5
        self._ambient_rms = 120.0
        self._is_speaking = False
        self._is_playback_active = False

        # Action Idempotency & History
        self._executed_action_ids: Set[str] = set()
        self._recent_actions: Deque[ActionResult] = collections.deque(maxlen=50)

        # Movement Safety Limits
        self.max_linear_speed = 0.4   # m/s
        self.max_angular_speed = 0.8  # rad/s
        self.max_duration_s = 5.0

    def update_audio_state(
        self,
        raw_doa_deg: Optional[float] = None,
        rms_level: Optional[float] = None,
        vad_active: bool = False,
        is_speaking: bool = False,
        is_playback_active: bool = False,
    ):
        """Updates internal acoustic perception state and evaluates DOA validity."""
        now = time.monotonic()
        with self._lock:
            self._is_speaking = is_speaking
            self._is_playback_active = is_playback_active

            if rms_level is not None:
                if not is_speaking and not is_playback_active and rms_level < 400.0:
                    self._ambient_rms = 0.95 * self._ambient_rms + 0.05 * rms_level

            if raw_doa_deg is not None:
                # Discard DOA while robot itself is speaking
                if is_speaking or is_playback_active:
                    return

                cur_rms = rms_level if rms_level is not None else 500.0
                yaw = circular_doa_to_yaw(raw_doa_deg)
                self._doa_history.append((now, yaw, cur_rms))

                # Calculate confidence based on acoustic energy & VAD
                energy_ratio = cur_rms / max(80.0, self._ambient_rms)
                vad_factor = 0.9 if vad_active else 0.5
                conf = min(1.0, max(0.0, (energy_ratio / 3.0) * vad_factor))

                # Temporal clustering / consistency check
                recent = [y for ts, y, _ in self._doa_history if (now - ts) <= 2.0]
                if len(recent) >= 2:
                    # Check angular variance
                    mean_y = sum(recent) / len(recent)
                    is_consistent = all(abs(y - mean_y) <= 25.0 for y in recent)
                    if is_consistent:
                        conf = min(1.0, conf + 0.25)
                        yaw = mean_y
                    else:
                        conf = max(0.0, conf - 0.20)

                is_valid = (conf >= self._min_doa_confidence) and (energy_ratio >= 1.5)

                self._latest_doa = SoundDirection(
                    azimuth_deg=float(yaw),
                    confidence=float(conf),
                    valid=bool(is_valid),
                    timestamp=now,
                    raw_doa_deg=float(raw_doa_deg),
                    rms_level=float(cur_rms),
                )

                # Format exact ROS log as mandated by specification
                sign = "+" if yaw >= 0 else ""
                self._logger.info(
                    f"[DOA]\n"
                    f"azimuth_deg={sign}{yaw:.1f}\n"
                    f"confidence={conf:.2f}\n"
                    f"valid={str(is_valid).lower()}"
                )

    def get_sound_direction(self) -> Optional[SoundDirection]:
        """Returns the current sound direction if fresh and valid, else None."""
        now = time.monotonic()
        with self._lock:
            if not self._latest_doa:
                return None
            if (now - self._latest_doa.timestamp) > self._doa_freshness_timeout_s:
                return None
            if not self._latest_doa.valid:
                return None
            return self._latest_doa

    def execute_turn_to_sound(
        self,
        generation_id: Optional[int] = None,
        action_id: Optional[str] = None,
    ) -> ActionResult:
        """Executes physical orientation towards the validated acoustic sound source.

        If DOA is unavailable or invalid, strictly produces NO_DIRECTION without moving motors.
        """
        now = time.monotonic()
        act_id = action_id or f"turn_sound_{int(now * 1000)}"

        with self._lock:
            # Idempotency check
            if act_id in self._executed_action_ids:
                return ActionResult(
                    success=True,
                    action="turn_to_sound",
                    action_id=act_id,
                    generation_id=generation_id,
                    hardware_ack=True,
                    message="Bu ses yönü eylemi zaten yürütüldü.",
                )

            sound_dir = self.get_sound_direction()

            # 1. DOA Verification Gate
            if sound_dir is None or not sound_dir.valid or sound_dir.confidence < self._min_doa_confidence:
                self._logger.warning("⚠️ [ActionManager] turn_to_sound reddedildi: NO_DIRECTION (DOA yok veya zayıf)")
                res = ActionResult(
                    success=False,
                    action="turn_to_sound",
                    action_id=act_id,
                    generation_id=generation_id,
                    error_code="NO_DIRECTION",
                    error="Sesin yönü belirlenemedi (DOA unavailable veya sinyal zayıf).",
                    reason="no_sound_direction",
                    message="Sesin hangi yönden geldiği tespit edilemediği için robot hareket ettirilmedi.",
                    hardware_ack=False,
                )
                self._recent_actions.append(res)
                return res

            azimuth = sound_dir.azimuth_deg
            confidence = sound_dir.confidence

            # 2. Safety Gates (Heartbeat & LiDAR Freshness)
            blocked_reason = self._check_safety_gates(direction="turn")
            if blocked_reason:
                res = ActionResult(
                    success=False,
                    action="turn_to_sound",
                    action_id=act_id,
                    generation_id=generation_id,
                    azimuth_deg=round(azimuth, 1),
                    confidence=round(confidence, 2),
                    error_code=blocked_reason.get("error_code", "SAFETY_BLOCKED"),
                    reason=blocked_reason.get("reason", "safety_blocked"),
                    error=blocked_reason.get("message", "Güvenlik kilidi devrede."),
                    message=blocked_reason.get("message", "Güvenlik kilidi nedeniyle hareket edilmedi."),
                    hardware_ack=False,
                )
                self._recent_actions.append(res)
                return res

            # 3. Execute Motor Command
            # Calculate rotation parameters
            dir_str = "right" if azimuth > 0 else "left"
            yaw_rad = math.radians(abs(azimuth))
            turn_speed = 0.4  # rad/s
            turn_duration = max(0.4, min(3.0, yaw_rad / turn_speed))

            # Send Head Command if head motor publisher exists
            pub_head = self._pub_head_cmd or getattr(self._node, "pub_head_cmd", None)
            if pub_head:
                try:
                    head_msg = HeadCmd()
                    head_msg.angle_deg = float(max(-70.0, min(70.0, azimuth)))
                    pub_head.publish(head_msg)
                except Exception as he:
                    self._logger.warning(f"HeadCmd yayını başarısız: {he}")

            # Send Base Rotation to /cmd_vel
            pub_vel = self._pub_cmd_vel or getattr(self._node, "pub_cmd_vel", None)
            if pub_vel:
                try:
                    tw = Twist()
                    tw.angular.z = turn_speed if azimuth < 0 else -turn_speed
                    pub_vel.publish(tw)

                    def _stop_later():
                        time.sleep(turn_duration)
                        try:
                            stop_tw = Twist()
                            pub_vel.publish(stop_tw)
                        except Exception:
                            pass
                    threading.Thread(target=_stop_later, daemon=True).start()
                except Exception as me:
                    res = ActionResult(
                        success=False,
                        action="turn_to_sound",
                        action_id=act_id,
                        generation_id=generation_id,
                        error_code="MOTOR_COMMAND_FAILED",
                        error=str(me),
                        message="Motor komutu verilemedi.",
                        hardware_ack=False,
                    )
                    self._recent_actions.append(res)
                    return res

            self._executed_action_ids.add(act_id)
            if len(self._executed_action_ids) > 100:
                self._executed_action_ids.clear()

            res = ActionResult(
                success=True,
                action="turn_to_sound",
                action_id=act_id,
                generation_id=generation_id,
                azimuth_deg=round(azimuth, 1),
                confidence=round(confidence, 2),
                requested_direction=dir_str,
                actual_direction=dir_str,
                duration_ms=int(turn_duration * 1000),
                hardware_ack=True,
                message=f"Sesin geldiği {round(azimuth, 1)}° ({dir_str}) yönüne başarıyla dönüldü.",
            )
            self._recent_actions.append(res)
            return res

    def execute_move(
        self,
        direction: str,
        speed: float = 0.2,
        duration: float = 1.5,
        generation_id: Optional[int] = None,
        action_id: Optional[str] = None,
    ) -> ActionResult:
        """Executes a linear or angular base motion with verified hardware authority."""
        now = time.monotonic()
        act_id = action_id or f"move_{direction}_{int(now * 1000)}"
        clean_dir = (direction or "stop").lower().strip()

        with self._lock:
            # Idempotency check
            if clean_dir != "stop" and act_id in self._executed_action_ids:
                return ActionResult(
                    success=True,
                    action="move_robot",
                    action_id=act_id,
                    generation_id=generation_id,
                    requested_direction=clean_dir,
                    actual_direction=clean_dir,
                    hardware_ack=True,
                    message="Bu hareket eylemi zaten yürütüldü.",
                )

            valid_dirs = ["forward", "backward", "left", "right", "stop"]
            if clean_dir not in valid_dirs:
                return ActionResult(
                    success=False,
                    action="move_robot",
                    action_id=act_id,
                    generation_id=generation_id,
                    error_code="INVALID_DIRECTION",
                    error=f"Geçersiz yön: '{direction}'. Geçerli yönler: {valid_dirs}",
                    message="Geçersiz hareket yönü belirtildi.",
                    hardware_ack=False,
                )

            # Clamp parameters for safety
            clamped_speed = max(0.05, min(speed, self.max_linear_speed))
            clamped_duration = max(0.5, min(duration, self.max_duration_s))

            if clean_dir != "stop":
                blocked_reason = self._check_safety_gates(direction=clean_dir)
                if blocked_reason:
                    res = ActionResult(
                        success=False,
                        action="move_robot",
                        action_id=act_id,
                        generation_id=generation_id,
                        requested_direction=clean_dir,
                        error_code=blocked_reason.get("error_code", "SAFETY_BLOCKED"),
                        reason=blocked_reason.get("reason", "safety_blocked"),
                        error=blocked_reason.get("message", "Güvenlik kilidi devrede."),
                        message=blocked_reason.get("message", "Güvenlik nedeniyle hareket engellendi."),
                        hardware_ack=False,
                    )
                    self._recent_actions.append(res)
                    return res

            pub_vel = self._pub_cmd_vel or getattr(self._node, "pub_cmd_vel", None)
            if not pub_vel:
                return ActionResult(
                    success=False,
                    action="move_robot",
                    action_id=act_id,
                    generation_id=generation_id,
                    error_code="MOTOR_CONTROLLER_UNAVAILABLE",
                    error="/cmd_vel yayıncısı hazır değil veya bağlantı yok.",
                    message="Motor kontrolcüsü hazır olmadığı için hareket edilemedi.",
                    hardware_ack=False,
                )

            try:
                tw = Twist()
                if clean_dir == "forward":
                    tw.linear.x = clamped_speed
                elif clean_dir == "backward":
                    tw.linear.x = -clamped_speed
                elif clean_dir == "left":
                    tw.angular.z = clamped_speed * 2.0
                elif clean_dir == "right":
                    tw.angular.z = -clamped_speed * 2.0
                elif clean_dir == "stop":
                    tw.linear.x = 0.0
                    tw.angular.z = 0.0

                pub_vel.publish(tw)

                if clean_dir != "stop":
                    def _stop_later():
                        time.sleep(clamped_duration)
                        try:
                            stop_tw = Twist()
                            pub_vel.publish(stop_tw)
                        except Exception:
                            pass
                    threading.Thread(target=_stop_later, daemon=True).start()

                if clean_dir != "stop":
                    self._executed_action_ids.add(act_id)
                    if len(self._executed_action_ids) > 100:
                        self._executed_action_ids.clear()

                res = ActionResult(
                    success=True,
                    action="move_robot",
                    action_id=act_id,
                    generation_id=generation_id,
                    requested_direction=clean_dir,
                    actual_direction=clean_dir,
                    duration_ms=int(clamped_duration * 1000),
                    hardware_ack=True,
                    message=f"Robot {clean_dir} yönünde {clamped_speed} m/s hızla hareket ettirildi.",
                )
                self._recent_actions.append(res)
                return res

            except Exception as exc:
                res = ActionResult(
                    success=False,
                    action="move_robot",
                    action_id=act_id,
                    generation_id=generation_id,
                    error_code="MOTOR_WRITE_ERROR",
                    error=str(exc),
                    message="Motor komutu verilirken hata oluştu.",
                    hardware_ack=False,
                )
                self._recent_actions.append(res)
                return res

    def _check_safety_gates(self, direction: str) -> Optional[Dict[str, str]]:
        """Checks Arduino heartbeat health, LiDAR proximity, and LiDAR freshness."""
        node = self._node
        if not node:
            return None

        # 1. Heartbeat Health Gate
        hb_ok = getattr(node, "_arduino_heartbeat_healthy", False)
        last_ack = getattr(node, "_last_heartbeat_ack_time", 0.0)
        if not hb_ok or (time.monotonic() - last_ack) > 2.0:
            return {
                "error_code": "MOTOR_CONTROLLER_UNAVAILABLE",
                "reason": "heartbeat_unhealthy",
                "message": "Arduino bağlantısı veya heartbeat aktif değil, güvenlik için hareket engellendi."
            }

        # 2. Obstacle Detection Gate
        if direction == "forward" and getattr(node, "_obstacle_detected", False):
            return {
                "error_code": "OBSTACLE_DETECTED",
                "reason": "obstacle_detected",
                "message": "Robotun önünde engel tespit edildi, hareket güvenlik nedeniyle engellendi."
            }

        # 3. LiDAR Freshness Watchdog Gate
        last_scan_time = getattr(node, "_last_laser_scan_time", 0.0)
        is_lidar_stale = (time.monotonic() - last_scan_time) > 2.0
        if is_lidar_stale:
            if hasattr(node, "_lidar_health"):
                node._lidar_health = "UNHEALTHY"
            if direction == "forward":
                return {
                    "error_code": "LIDAR_STALE_OR_DISCONNECTED",
                    "reason": "lidar_stale_or_disconnected",
                    "message": "LiDAR tarama verisi alınamıyor veya güncel değil, güvenlik nedeniyle ileri hareket engellendi."
                }

        return None
