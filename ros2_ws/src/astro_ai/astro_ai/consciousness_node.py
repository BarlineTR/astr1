#!/usr/bin/env python3
"""ASTRO V1 — Consciousness Architecture Node (ROS2 Adapter).

Serves as the ROS2 adapter layer bridging:
  - Perception topic subscriptions -> In-memory Sensor Snapshots & Event Generation
  - Pure Python CognitiveEventBus -> /consciousness/event publication
  - Cognitive State & Introspection -> /consciousness/state & /consciousness/workspace
  - Consciousness Action Intents -> /consciousness/action_intent

Zero-blocking architecture: All topic callbacks perform O(1) thread-safe cache updates.
The 10 Hz cognitive cycle runs deterministically without blocking on disk or network.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional

_LOG = logging.getLogger(__name__)

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import (
        QoSProfile,
        ReliabilityPolicy,
        DurabilityPolicy,
        HistoryPolicy,
        qos_profile_sensor_data,
    )
    from sensor_msgs.msg import LaserScan
    from std_msgs.msg import Bool, Float32, String
    try:
        from astro_base.msg import HeadState
    except ImportError:
        try:
            from astro_interfaces.msg import HeadState
        except ImportError:
            HeadState = None
except ImportError:
    rclpy = None
    qos_profile_sensor_data = 10
    HeadState = None

    class _MockPublisher:
        def __init__(self, topic=""):
            self.topic = topic
            self.last_msg = None
            self.count = 0

        def publish(self, msg):
            self.last_msg = msg
            self.count += 1

    class Node:  # type: ignore
        def __init__(self, name="mock_node", *args, **kwargs):
            self._name = name

        def get_name(self):
            return self._name

        def get_logger(self):
            return logging.getLogger(self._name)

        def declare_parameter(self, name, value):
            return value

        def get_parameter(self, name):
            class _Param:
                def __init__(self, v):
                    self.value = v
            return _Param(None)

        def create_subscription(self, *args, **kwargs):
            return None

        def create_publisher(self, msg_type, topic, *args, **kwargs):
            return _MockPublisher(topic)

        def create_timer(self, period_sec, callback):
            return None

    class _MockMsg:
        def __init__(self, data=None, **kwargs):
            self.data = data
            self.ranges = []
            for k, v in kwargs.items():
                setattr(self, k, v)

    Bool = Float32 = String = LaserScan = _MockMsg  # type: ignore

from astro_ai.brain.affective_state import AffectiveStateManager
from astro_ai.brain.cognitive_event_bus import CognitiveEventBus
from astro_ai.brain.cognitive_loop import CognitiveLoop
from astro_ai.contracts.consciousness_types import (
    ActionIntent,
    CognitiveEvent,
    CognitiveEventType,
    CognitiveWorkspace,
    RobotAffectiveState,
    SelfState,
)
from astro_ai.spatial.spatial_fusion import SpatialFusionEngine
from astro_ai.state_machine import RobotState


class ConsciousnessNode(Node):
    """ROS2 node wrapping the ASTRO Consciousness Architecture."""

    def __init__(self, node_name: str = "consciousness_node"):
        super().__init__(node_name)
        self._lock = threading.RLock()

        # Parameters
        self.declare_parameter("cognitive_loop_hz", 10.0)
        self.declare_parameter("enable_telemetry", True)
        self.declare_parameter("temporal_history_size", 50)

        param_hz = self.get_parameter("cognitive_loop_hz").value
        self.loop_hz = float(param_hz) if param_hz is not None else 10.0
        self.timer_period = 1.0 / max(1.0, min(50.0, self.loop_hz))

        param_hist = self.get_parameter("temporal_history_size").value
        self.temporal_history_size = int(param_hist) if param_hist is not None else 50

        # Core Substrates (Phase 0A, 0B, Phase 1 & Phase 2)
        self.event_bus = CognitiveEventBus(max_capacity=250)
        self.self_state = SelfState()
        self.affective_manager = AffectiveStateManager()
        self.affective_state = self.affective_manager.state
        self.spatial_fusion = SpatialFusionEngine()
        self.loop = CognitiveLoop(
            world_model=None,
            event_bus=self.event_bus,
            self_state=self.self_state,
            affective_manager=self.affective_manager,
            target_hz=self.loop_hz,
            temporal_history_size=self.temporal_history_size,
            on_telemetry=self.get_logger().info,
        )
        self.self_model = self.loop.self_model

        # Ephemeral Sensor Caches (Thread-safe)
        self._sensor_cache: Dict[str, Any] = {
            "faces_json": "[]",
            "person_detected": False,
            "looking_at_robot": False,
            "vad": False,
            "doa_deg": 0.0,
            "tts_speaking": False,
            "last_speech_text": "",
            "head_yaw_deg": 0.0,
            "min_front_distance_m": 12.0,
            "last_sensor_update_ts": time.time(),
        }

        # Telemetry & Timing
        self._last_telemetry_ts = 0.0
        self._telemetry_interval_s = 0.5  # 2 Hz telemetry
        self._cycle_count = 0
        self._last_cycle_time_ms = 0.0

        # ROS2 Interfaces Setup
        self._setup_publishers()
        self._setup_subscribers()

        # Periodic Timer (Nominal 10 Hz)
        self._timer = self.create_timer(self.timer_period, self._on_cycle)
        self.get_logger().info(
            f"🧠 [Bilinç Düğümü] ASTRO Bilinç Mimarisi {self.loop_hz} Hz frekansında başarıyla başlatıldı."
        )

    # -------------------------------------------------------------------------
    # Publishers & Subscribers Setup
    # -------------------------------------------------------------------------

    def _setup_publishers(self) -> None:
        # Standard QoS profiles
        state_qos = 10
        if rclpy:
            state_qos = QoSProfile(
                depth=1,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
                history=HistoryPolicy.KEEP_LAST,
            )

        self._pub_state = self.create_publisher(String, "/consciousness/state", state_qos)
        self._pub_event = self.create_publisher(String, "/consciousness/event", 20)
        self._pub_workspace = self.create_publisher(String, "/consciousness/workspace", 1)
        self._pub_action_intent = self.create_publisher(String, "/consciousness/action_intent", 10)

    def _setup_subscribers(self) -> None:
        self.create_subscription(String, "/vision/faces", self._on_faces_msg, qos_profile_sensor_data)
        self.create_subscription(Bool, "/vision/person_detected", self._on_person_detected_msg, qos_profile_sensor_data)
        self.create_subscription(Bool, "/vision/looking_at_robot", self._on_looking_msg, qos_profile_sensor_data)
        self.create_subscription(String, "/vision/recognized_person", self._on_recognized_person_msg, 10)
        self.create_subscription(Bool, "/audio/vad", self._on_audio_vad_msg, qos_profile_sensor_data)
        self.create_subscription(Float32, "/audio/doa", self._on_audio_doa_msg, qos_profile_sensor_data)
        self.create_subscription(Bool, "/tts/speaking", self._on_tts_speaking_msg, 10)
        self.create_subscription(Bool, "/robot/is_speaking", self._on_tts_speaking_msg, 10)
        self.create_subscription(Bool, "/audio/playback_active", self._on_tts_speaking_msg, 10)
        self.create_subscription(String, "/speech/text", self._on_speech_text_msg, 10)
        self.create_subscription(LaserScan, "/scan", self._on_scan_msg, qos_profile_sensor_data)
        if HeadState is not None:
            self.create_subscription(HeadState, "/head/state", self._on_head_state_msg, qos_profile_sensor_data)
        else:
            self.create_subscription(Float32, "/head/state", self._on_head_state_msg, qos_profile_sensor_data)
        self.create_subscription(String, "/gaze/active_target", self._on_active_target_msg, 10)

    # -------------------------------------------------------------------------
    # Perception Callbacks (O(1) Non-Blocking Caches)
    # -------------------------------------------------------------------------

    def _on_faces_msg(self, msg: Any) -> None:
        raw_txt = getattr(msg, "data", "[]")
        now = time.time()
        face_data: List[Dict[str, Any]] = []
        try:
            parsed = json.loads(raw_txt)
            if isinstance(parsed, list):
                face_data = parsed
        except Exception:
            pass

        has_faces = len(face_data) > 0
        with self._lock:
            prev = self._sensor_cache["person_detected"]
            self._sensor_cache["faces_json"] = raw_txt
            self._sensor_cache["person_detected"] = has_faces
            self._sensor_cache["last_sensor_update_ts"] = now
            self.spatial_fusion.update_vision_perception(
                faces=face_data,
                looking_at_robot=self._sensor_cache.get("looking_at_robot", False),
            )

        self.loop.event_detector.notify_sensor_active("camera", now)

        # Emit perception events on state transitions if not already triggered by /vision/person_detected
        if has_faces and not prev:
            self.get_logger().info("👁️ [Bilinç: Görme Algısı] Kamera görüş alanında kişi algılandı")
            self.event_bus.create_and_publish(
                event_type=CognitiveEventType.PERSON_APPEARED,
                source="vision",
                data={"timestamp": now},
            )
        elif not has_faces and prev:
            self.get_logger().info("👁️ [Bilinç: Görme Algısı] Kişi kamera görüş alanından ayrıldı")
            self.event_bus.create_and_publish(
                event_type=CognitiveEventType.PERSON_DISAPPEARED,
                source="vision",
                data={"timestamp": now},
            )

    def _on_recognized_person_msg(self, msg: Any) -> None:
        val = str(getattr(msg, "data", "")).strip()
        with self._lock:
            self._sensor_cache["recognized_person"] = val if val else None

    def _on_active_target_msg(self, msg: Any) -> None:
        val = str(getattr(msg, "data", "")).strip()
        now = time.time()
        with self._lock:
            self._sensor_cache["active_target_id"] = val if val else None
        self.loop.event_detector.notify_sensor_active("gaze", now)

    def _on_person_detected_msg(self, msg: Any) -> None:
        val = bool(getattr(msg, "data", False))
        prev = self._sensor_cache["person_detected"]
        now = time.time()
        with self._lock:
            self._sensor_cache["person_detected"] = val
            self._sensor_cache["last_sensor_update_ts"] = now

        self.loop.event_detector.notify_sensor_active("camera", now)

        # Emit perception events on state transitions
        if val and not prev:
            self.get_logger().info("👁️ [Bilinç: Görme Algısı] Kamera görüş alanında kişi algılandı")
            self.event_bus.create_and_publish(
                event_type=CognitiveEventType.PERSON_APPEARED,
                source="vision",
                data={"timestamp": now},
            )
        elif not val and prev:
            self.get_logger().info("👁️ [Bilinç: Görme Algısı] Kişi kamera görüş alanından ayrıldı")
            self.event_bus.create_and_publish(
                event_type=CognitiveEventType.PERSON_DISAPPEARED,
                source="vision",
                data={"timestamp": now},
            )

    def _on_looking_msg(self, msg: Any) -> None:
        val = bool(getattr(msg, "data", False))
        with self._lock:
            self._sensor_cache["looking_at_robot"] = val
            try:
                face_data = json.loads(self._sensor_cache.get("faces_json", "[]"))
                if not isinstance(face_data, list):
                    face_data = []
            except Exception:
                face_data = []
            self.spatial_fusion.update_vision_perception(
                faces=face_data,
                looking_at_robot=val,
            )

    def _on_audio_vad_msg(self, msg: Any) -> None:
        val = bool(getattr(msg, "data", False))
        prev = self._sensor_cache["vad"]
        now = time.time()
        with self._lock:
            self._sensor_cache["vad"] = val
            self.self_state.is_listening = val
            self.spatial_fusion.update_audio_perception(
                doa_deg=self._sensor_cache.get("doa_deg", 0.0),
                is_speaking=val,
                vad_active=val,
            )

        self.loop.event_detector.notify_sensor_active("audio", now)

        if val and not prev:
            self.get_logger().info(f"🎙️ [Bilinç: İşitsel Algı] Kullanıcı konuşma başlangıcı algılandı (Ses Açısı: {self._sensor_cache['doa_deg']:.1f}°)")
            self.event_bus.create_and_publish(
                event_type=CognitiveEventType.PERSON_SPOKE,
                source="audio",
                data={"doa_deg": self._sensor_cache["doa_deg"]},
            )

    def _on_audio_doa_msg(self, msg: Any) -> None:
        now = time.time()
        doa = float(getattr(msg, "data", 0.0))
        with self._lock:
            self._sensor_cache["doa_deg"] = doa
            self.spatial_fusion.update_audio_perception(
                doa_deg=doa,
                is_speaking=self._sensor_cache.get("vad", False),
                vad_active=self._sensor_cache.get("vad", False),
            )
        self.loop.event_detector.notify_sensor_active("audio", now)

    def _on_tts_speaking_msg(self, msg: Any) -> None:
        val = bool(getattr(msg, "data", False))
        prev = self._sensor_cache["tts_speaking"]
        with self._lock:
            self._sensor_cache["tts_speaking"] = val
            self.self_state.is_speaking = val
        if val and not prev:
            self.event_bus.create_and_publish(
                event_type=CognitiveEventType.ROBOT_STARTED_SPEAKING,
                source="tts",
            )
        elif not val and prev:
            self.event_bus.create_and_publish(
                event_type=CognitiveEventType.ROBOT_FINISHED_SPEAKING,
                source="tts",
            )

    def _on_speech_text_msg(self, msg: Any) -> None:
        text = str(getattr(msg, "data", "")).strip()
        now = time.time()
        if text:
            with self._lock:
                self._sensor_cache["last_speech_text"] = text
            self.loop.event_detector.notify_sensor_active("audio", now)
            self.get_logger().info(f"🗣️ [Bilinç: Konuşma Tanıma] Kullanıcı metni: \"{text}\"")
            self.event_bus.create_and_publish(
                event_type=CognitiveEventType.PERSON_SPOKE,
                source="speech_recognition",
                data={"text": text},
            )

    def _on_scan_msg(self, msg: Any) -> None:
        ranges = getattr(msg, "ranges", [])
        now = time.time()
        if ranges:
            valid_ranges = [r for r in ranges if 0.15 < r < 12.0]
            if valid_ranges:
                with self._lock:
                    self._sensor_cache["min_front_distance_m"] = min(valid_ranges)
            angle_min = getattr(msg, "angle_min", -math.pi)
            angle_increment = getattr(msg, "angle_increment", math.radians(1.0))
            range_min = getattr(msg, "range_min", 0.15)
            range_max = getattr(msg, "range_max", 12.0)
            self.spatial_fusion.update_lidar_scan(
                ranges=list(ranges),
                angle_min=angle_min,
                angle_increment=angle_increment,
                range_min=range_min,
                range_max=range_max,
            )
        self.loop.event_detector.notify_sensor_active("lidar", now)

    def _on_head_state_msg(self, msg: Any) -> None:
        if hasattr(msg, "canonical_yaw_deg") and not math.isnan(msg.canonical_yaw_deg):
            yaw = float(msg.canonical_yaw_deg)
        elif hasattr(msg, "actual_yaw_deg") and not math.isnan(msg.actual_yaw_deg):
            yaw = float(msg.actual_yaw_deg)
        elif hasattr(msg, "estimated_yaw_deg") and not math.isnan(msg.estimated_yaw_deg):
            yaw = float(msg.estimated_yaw_deg)
        else:
            yaw = float(getattr(msg, "data", 0.0))
        now = time.time()
        with self._lock:
            self._sensor_cache["head_yaw_deg"] = yaw
            self.self_state.current_head_yaw_deg = yaw
        self.loop.event_detector.notify_sensor_active("head", now)

    # -------------------------------------------------------------------------
    # Cognitive Cycle (Timer Callback - Nominal 10 Hz)
    # -------------------------------------------------------------------------

    def _on_cycle(self) -> None:
        """Executes one non-blocking cognitive step."""
        t_start = time.perf_counter()
        now = time.time()

        with self._lock:
            self._cycle_count += 1

            # 1. Update SelfState dynamic timing
            self.self_state.timestamp = now
            self.self_state.is_speaking = self._sensor_cache["tts_speaking"]
            self.self_state.is_listening = self._sensor_cache["vad"]
            self.self_state.current_head_yaw_deg = self._sensor_cache["head_yaw_deg"]

            # Authoritative single spatial fusion pathway
            fused_people = self.spatial_fusion.compute_fusion(now=now)

            # 2. Publish any unprocessed events to ROS2 telemetric stream
            unprocessed = self.event_bus.get_unprocessed_events()
            if unprocessed:
                for evt in unprocessed:
                    msg = String()
                    msg.data = json.dumps(evt.to_dict(), ensure_ascii=False)
                    self._pub_event.publish(msg)

            # 3. Step CognitiveLoop (Perceive -> Event -> World Temporal Update)
            cycle_result = self.loop.step({
                "people": fused_people,
                "person_detected": bool(fused_people) or self._sensor_cache["person_detected"],
                "vad": self._sensor_cache["vad"],
                "doa_deg": self._sensor_cache["doa_deg"],
                "tts_speaking": self._sensor_cache["tts_speaking"],
                "active_target_id": self._sensor_cache.get("active_target_id", None),
                "robot_state": {
                    "head_yaw_deg": self._sensor_cache["head_yaw_deg"],
                    "is_speaking": self._sensor_cache["tts_speaking"],
                },
                "environment": {
                    "front_clearance_m": self._sensor_cache["min_front_distance_m"],
                },
            })
            self.affective_state = cycle_result.affective_state or self.affective_manager.state

            # Emit ActionIntent to /consciousness/action_intent stream
            if cycle_result.action_intent is not None:
                self.emit_action_intent(cycle_result.action_intent)

            # 3. Telemetry Publishing (2 Hz)
            if (now - self._last_telemetry_ts) >= self._telemetry_interval_s:
                self._last_telemetry_ts = now
                self._publish_telemetry()

            # Record cycle execution latency
            t_elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            self._last_cycle_time_ms = t_elapsed_ms
            self.self_state.cycle_time_ms = t_elapsed_ms

    def _publish_telemetry(self) -> None:
        """Publishes SelfState telemetry snapshot."""
        try:
            state_dict = self.self_state.to_dict()
            state_dict["affective"] = self.affective_state.to_dict()
            state_dict["introspection"] = self.self_state.get_introspection_summary()
            state_dict["cycle_count"] = self._cycle_count

            msg = String()
            msg.data = json.dumps(state_dict, ensure_ascii=False)
            self._pub_state.publish(msg)
        except Exception as exc:
            self.get_logger().error(f"❌ [Bilinç Telemetrisi] Telemetri yayınlama hatası: {exc}")

    def emit_action_intent(self, intent: ActionIntent) -> None:
        """Emits an ActionIntent to downstream arbiters via /consciousness/action_intent."""
        try:
            msg = String()
            msg.data = json.dumps(intent.to_dict(), ensure_ascii=False)
            self._pub_action_intent.publish(msg)
        except Exception as exc:
            self.get_logger().error(f"❌ [Bilinç Eylem Amacı] Eylem amacı yayınlama hatası: {exc}")


def main(args=None):
    if rclpy is None:
        logging.basicConfig(level=logging.INFO)
        _LOG.info("rclpy yüklü değil; Bilinç Düğümü (ConsciousnessNode) bağımsız test modunda çalıştırılıyor.")
        node = ConsciousnessNode()
        for _ in range(5):
            node._on_cycle()
            time.sleep(0.1)
        return

    rclpy.init(args=args)
    node = ConsciousnessNode()
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
