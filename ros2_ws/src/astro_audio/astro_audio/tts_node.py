#!/usr/bin/env python3
"""ASTRO V1 — Production Hybrid TTS Node with Circuit Breaker & Local XTTS GPU Fallback.

Features:
  - Primary: OpenAI Realtime Engine
  - Fallback: Local Coqui XTTS v2 on CUDA GPU (cuda:0, FP16, cached latents)
  - Single-owner AudioOutputManager for clean ReSpeaker ALSA playback
  - Low-latency streaming SentenceChunker (< 1.0s TTFA)
  - Hardware barge-in interrupt with generation tracking
"""

import json
import os
import queue
import threading
import time
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

from astro_audio.audio_output_manager import AudioOutputManager
from astro_audio.local_xtts_engine import LocalXttsEngine
from astro_audio.realtime_engine import RealtimeEngine
from astro_audio.sentence_chunker import clean_text_for_tts
from astro_audio.tts_orchestrator import OrchestratorState, TTSOrchestrator

try:
    from dotenv import find_dotenv, load_dotenv
except ImportError:
    def find_dotenv(*args, **kwargs): return ""
    def load_dotenv(*args, **kwargs): pass


def _load_env():
    candidates = [
        os.path.abspath(".env"),
        os.path.abspath(".env.production"),
        os.path.abspath(os.path.join(os.getcwd(), ".env")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env")),
        os.path.expanduser("~/Desktop/astr1/.env"),
        os.path.expanduser("~/.env"),
    ]
    for c in candidates:
        if os.path.exists(c):
            load_dotenv(dotenv_path=c, override=True)
            return c
    try:
        env_path = find_dotenv(usecwd=True)
        if env_path:
            load_dotenv(dotenv_path=env_path, override=True)
            return env_path
    except Exception:
        pass
    return None


class TtsNode(Node):
    """ROS 2 Node orchestrating speech synthesis across Realtime API and Local GPU XTTS."""

    def __init__(self):
        super().__init__("tts_node")
        _load_env()

        self.tts_engine_pref = os.getenv("TTS_ENGINE", "openai").lower()
        self.openai_voice = os.getenv("OPENAI_TTS_VOICE", "echo")
        self.tts_language = os.getenv("TTS_LANGUAGE", "tr")

        # 1. Initialize Audio Output Manager
        self.output_manager = AudioOutputManager(
            preferred_device=os.getenv("AUDIO_OUTPUT_DEVICE", ""),
            on_playback_state_change=self._on_playback_state_changed,
            logger=lambda lvl, msg: getattr(self.get_logger(), lvl, self.get_logger().info)(msg),
        )

        # 2. Initialize Realtime Engine (Primary)
        self.realtime_engine = RealtimeEngine(
            model=os.getenv("REALTIME_MODEL", "gpt-realtime"),
            voice=self.openai_voice,
            logger=lambda lvl, msg: getattr(self.get_logger(), lvl, self.get_logger().info)(msg),
        )

        # 3. Initialize Local XTTS GPU Engine (Warm Fallback)
        xtts_home = os.getenv("TTS_XTTS_HOME", "") or os.path.expanduser("~/.astro/tts")
        speaker_wav = self._resolve_speaker_wav(xtts_home)
        self.local_xtts = None

        try:
            self.local_xtts = LocalXttsEngine(
                speaker_wav=speaker_wav,
                language=self.tts_language,
                device=os.getenv("TTS_XTTS_DEVICE", "cuda"),
                half=os.getenv("TTS_XTTS_HALF", "1") not in ("0", "false", "False"),
                home=xtts_home,
                model_dir=os.getenv("TTS_XTTS_MODEL_DIR", "") or None,
                logger=lambda lvl, msg: getattr(self.get_logger(), lvl, self.get_logger().info)(msg),
            )
            # Start worker in background thread to avoid blocking ROS node initialization
            threading.Thread(target=self._start_xtts_background, daemon=True).start()
        except Exception as e:
            self.get_logger().warn(f"⚠️ [TTS Node] Yerel XTTS hazırlığı uyarısı: {e}")

        # 4. Initialize TTS Orchestrator
        self.orchestrator = TTSOrchestrator(
            output_manager=self.output_manager,
            realtime_engine=self.realtime_engine,
            local_xtts_engine=self.local_xtts,
            logger=lambda lvl, msg: getattr(self.get_logger(), lvl, self.get_logger().info)(msg),
            on_state_change=self._on_orchestrator_state_change,
        )

        # Publishers
        self.pub_speaking = self.create_publisher(Bool, "/tts/speaking", 10)
        self.pub_status = self.create_publisher(String, "/tts/status", 10)

        # Subscribers
        self.sub_say = self.create_subscription(String, "/tts/say", self._on_say, 20)
        self.sub_interrupt = self.create_subscription(Bool, "/tts/interrupt", self._on_interrupt, 10)
        self.sub_emotion = self.create_subscription(String, "/robot/emotion", self._on_emotion, 10)

        # Internal Queue for /tts/say requests
        self._say_queue: queue.Queue[dict] = queue.Queue(maxsize=100)
        self._worker_thread = threading.Thread(target=self._process_say_queue, daemon=True)
        self._worker_thread.start()

        # Status timer (1Hz)
        self.create_timer(1.0, self._publish_status_heartbeat)

        self.get_logger().info("🚀 [TTS Node] Hybrid Realtime & XTTS GPU Orchestrator Hazır!")

    def _resolve_speaker_wav(self, xtts_home: str) -> str:
        configured = os.getenv("TTS_XTTS_SPEAKER_WAV", "")
        if configured and os.path.exists(configured):
            return configured
        try:
            from ament_index_python.packages import get_package_share_directory
            packaged = os.path.join(get_package_share_directory("astro_audio"), "voices", "astro.wav")
            if os.path.exists(packaged):
                return packaged
        except Exception:
            pass
        return os.path.join(xtts_home, "Recording.wav") if xtts_home else ""

    def _start_xtts_background(self):
        if self.local_xtts:
            try:
                self.local_xtts.start()
            except Exception as e:
                self.get_logger().error(f"❌ [TTS Node] Local XTTS GPU başlatılamadı: {e}")

    def _on_playback_state_changed(self, is_playing: bool):
        msg = Bool()
        msg.data = is_playing
        self.pub_speaking.publish(msg)

    def _on_orchestrator_state_change(self, state: OrchestratorState):
        status_payload = {
            "state": state.value,
            "engine": "openai_realtime" if state == OrchestratorState.REALTIME_ACTIVE else "xtts_gpu",
            "timestamp": time.time(),
        }
        msg = String()
        msg.data = json.dumps(status_payload)
        self.pub_status.publish(msg)

    def _on_emotion(self, msg: String):
        # Clean decoupled emotion logging
        emotion = msg.data.lower().strip()
        self.get_logger().debug(f"🎭 [TTS Node] Duygu güncellemesi: {emotion}")

    def _on_say(self, msg: String):
        if not msg.data:
            return
        text_data = msg.data
        try:
            parsed = json.loads(text_data)
            if isinstance(parsed, dict) and "text" in parsed:
                text_data = parsed.get("text", "")
        except Exception:
            pass

        clean_text = clean_text_for_tts(text_data)
        if clean_text:
            try:
                self._say_queue.put_nowait({"text": clean_text, "timestamp": time.monotonic()})
            except queue.Full:
                self.get_logger().warn("⚠️ [TTS Node] Say kuyruğu dolu!")

    def _on_interrupt(self, msg: Bool):
        if msg.data:
            # Drain queue
            while not self._say_queue.empty():
                try:
                    self._say_queue.get_nowait()
                except queue.Empty:
                    break
            self.orchestrator.interrupt()

    def _process_say_queue(self):
        while rclpy.ok():
            try:
                item = self._say_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            text = item.get("text", "")
            t_req = item.get("timestamp", time.monotonic())
            if not text:
                continue

            gen_id = self.output_manager.new_generation()
            self.orchestrator.start_turn(turn_id=f"say_{gen_id}", generation_id=gen_id, user_turn_end_t=t_req)

            # Synthesize sentence/clauses
            self.get_logger().info(f'🔊 [TTS Okuyor]: "{text}"')
            self.orchestrator.synthesize_clause(text, generation_id=gen_id, auto_play=True)

    def _publish_status_heartbeat(self):
        status_payload = {
            "orchestrator_state": self.orchestrator.state.value,
            "xtts_ready": self.local_xtts.is_ready() if self.local_xtts else False,
            "realtime_ready": self.realtime_engine.is_ready(),
            "is_playing": self.output_manager.is_playing,
            "current_generation": self.output_manager.current_generation,
        }
        if self.local_xtts:
            status_payload.update(self.local_xtts.get_telemetry())

        msg = String()
        msg.data = json.dumps(status_payload)
        self.pub_status.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = TtsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.local_xtts:
            node.local_xtts.stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
