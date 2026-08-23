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
import logging

_LOG = logging.getLogger(__name__)

import os
import sys
import queue
import threading
import time
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

from astro_audio.audio_output_manager import AudioOutputManager
from astro_audio.local_xtts_engine import LocalXttsEngine, resolve_xtts_home, resolve_xtts_speaker_wav
from astro_audio.realtime_engine import RealtimeEngine
from astro_audio.sentence_chunker import clean_text_for_tts
from astro_audio.tts_orchestrator import OrchestratorState, TTSOrchestrator

try:
    from dotenv import find_dotenv, load_dotenv
except ImportError:
    def find_dotenv(*args, **kwargs): return ""
    def load_dotenv(*args, **kwargs): pass


def _load_env():
    # Test sürecinde .env YÜKLENMEZ: aksi hâlde testler kullanıcının gerçek
    # anahtarlarını alıp canlı API çağrıları yapıyor (astro_realtime_node
    # websocket'i gerçekten açıyor, kota harcanıyor) ve testler ".env yok"
    # varsayımıyla yazıldığı için sonuçlar çalıştırma ortamına göre değişiyor.
    if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:
        return None

    candidates = [
        os.path.abspath(".env"),
        os.path.abspath(".env.production"),
        os.path.abspath(os.path.join(os.getcwd(), ".env")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env")),
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
    except Exception as _exc:
        _LOG.debug("_load_env: yok sayılan hata (%s)", _exc)
    return None


class TtsNode(Node):
    """ROS 2 Node orchestrating speech synthesis across Realtime API and Local GPU XTTS."""

    def _log(self, level: str, message: str) -> None:
        """Alt sistemler için seviye yönlendirici.

        rclpy günlükçüsü seviyeyi çağrı yerine (dosya+satır) göre önbelleğe alır; tek bir
        lambda satırından hem info hem warn gönderilirse "Logger severity cannot be changed
        between calls" hatası çağıran iş parçacığını öldürür. Her seviye kendi satırında.
        """
        logger = self.get_logger()
        if level == "error":
            logger.error(message)
        elif level in ("warn", "warning"):
            logger.warn(message)
        elif level == "debug":
            logger.debug(message)
        else:
            logger.info(message)

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
            logger=self._log,
        )

        # 2. Initialize Realtime Engine (Primary)
        self.realtime_engine = RealtimeEngine(
            model=os.getenv("REALTIME_MODEL", "gpt-realtime"),
            voice=self.openai_voice,
            logger=self._log,
        )

        # 3. Yerel XTTS — yalnızca TTS_ENGINE="xtts" (veya TTS_XTTS_ENABLED=true) ile kurulur.
        # Eskiden burada koşulsuz "self.local_xtts = None" vardı: 1.816 satırlık XTTS
        # kodu hiçbir ayarla erişilemiyordu. Varsayılan hâlâ KAPALI (0 süreç, 0 RAM).
        self.local_xtts = None
        xtts_on = (self.tts_engine_pref == "xtts"
                   or os.getenv("TTS_XTTS_ENABLED", "false").strip().strip('"\'').lower() in ("1", "true", "yes"))
        if xtts_on:
            try:
                self.local_xtts = LocalXttsEngine(
                    speaker_wav=resolve_xtts_speaker_wav(os.getenv("TTS_XTTS_SPEAKER_WAV", "")),
                    language=self.tts_language,
                    device=os.getenv("TTS_XTTS_DEVICE", "cuda"),
                    half=os.getenv("TTS_XTTS_HALF", "1").strip() not in ("0", "false", "no"),
                    home=resolve_xtts_home(os.getenv("TTS_XTTS_HOME", "")),
                    logger=self._log,
                )
                self._log("info", "🎙️ [TTS] Yerel XTTS etkin (TTS_ENGINE=xtts)")
            except Exception as exc:
                self.local_xtts = None
                self._log("warn", f"⚠️ [TTS] XTTS başlatılamadı ({exc}) — zincirdeki sonraki motora düşülecek.")

        # 4. Initialize Local Offline TTS & Edge-TTS engines
        from astro_audio.edge_tts_engine import EdgeTTSEngine
        from astro_audio.local_offline_tts_engine import LocalOfflineTTSEngine

        self.local_offline_tts = LocalOfflineTTSEngine(
            language=self.tts_language,
            logger=self._log,
        )
        self.edge_tts = EdgeTTSEngine(
            logger=self._log,
        )

        # 4.5 OpenAI Speech API (REST) motoru.
        # TTS_ENGINE="openai" ARTIK GERÇEKTEN BU ANLAMA GELİYOR. Önceden ayar
        # yalnızca "xtts"/"elevenlabs" ile karşılaştırılıyordu, "openai" yazmak
        # hiçbir şey yapmıyordu; motor da ENABLE_OPENAI_REST_TTS bayrağının
        # arkasındaydı ve o bayrak hiçbir yerde belgelenmemişti. Sonuç: Realtime
        # düştüğü anda zincir yerel espeak'e iniyordu.
        # ENABLE_OPENAI_REST_TTS hâlâ çalışıyor (TTS_ENGINE başka bir değerdeyken
        # motoru yine de açmak için).
        self.openai_tts = None
        openai_rest_on = (
            self.tts_engine_pref == "openai"
            or os.getenv("ENABLE_OPENAI_REST_TTS", "false").strip().strip('"\'').lower() in ("1", "true", "yes")
        )
        if openai_rest_on:
            from astro_audio.openai_tts_engine import OpenAITTSEngine
            engine = OpenAITTSEngine(voice=self.openai_voice, logger=self._log)
            if engine.is_installed:
                self.openai_tts = engine
            else:
                self._log("warn", "⚠️ [OpenAI-TTS] TTS_ENGINE=openai ama motor kurulamadı "
                                  "(openai paketi veya OPENAI_API_KEY eksik).")

        # 4.6 ElevenLabs — TTS_ENGINE="elevenlabs" veya ELEVENLABS_ENABLED=true ile kurulur.
        # Motor 330 satırdı ama hiçbir yerde örneklenmiyordu; artık zincire bağlı.
        self.elevenlabs = None
        el_on = (self.tts_engine_pref == "elevenlabs"
                 or os.getenv("ELEVENLABS_ENABLED", "false").strip().strip('"\'').lower() in ("1", "true", "yes"))
        if el_on:
            from astro_audio.elevenlabs_engine import ElevenLabsEngine

            engine = ElevenLabsEngine(enabled=True, logger=self._log)
            if engine.is_ready():
                self.elevenlabs = engine
                self._log("info", f"🎧 [TTS] ElevenLabs etkin (model: {engine.model_id})")
            else:
                self._log("warn", "⚠️ [TTS] ElevenLabs istendi ama API anahtarı/ses kimliği eksik — atlanıyor.")

        # 5. Initialize TTS Orchestrator with Authoritative Fallback Chain (Realtime -> Edge-TTS -> Local Offline)
        self.orchestrator = TTSOrchestrator(
            output_manager=self.output_manager,
            realtime_engine=self.realtime_engine,
            local_xtts_engine=self.local_xtts,
            local_offline_tts_engine=self.local_offline_tts,
            edge_tts_engine=self.edge_tts,
            openai_tts_engine=self.openai_tts,
            elevenlabs_engine=self.elevenlabs,
            logger=self._log,
            on_state_change=self._on_orchestrator_state_change,
        )

        # Publishers
        self.pub_speaking = self.create_publisher(Bool, "/tts/speaking", 10)
        self.pub_status = self.create_publisher(String, "/tts/status", 10)

        # Subscribers
        self.sub_say = self.create_subscription(String, "/tts/say", self._on_say, 20)
        self.sub_interrupt = self.create_subscription(Bool, "/tts/interrupt", self._on_interrupt, 10)
        self.sub_emotion = self.create_subscription(String, "/robot/emotion", self._on_emotion, 10)
        # /audio/realtime_output_pcm'e BİLEREK abone olunmuyor. Realtime PCM'in
        # tek sahibi audio_stream_node'dur (giriş de çıkış da). Buraya bir
        # abonelik geri eklenirse aynı ALSA cihazına iki süreç yazar ve
        # "Device or resource busy" / "write to closed file" hataları döner.
        # Bkz. docs/superpowers/specs/2026-08-23-realtime-s2s-voice-core-design.md §5.2

        # Internal Queue for /tts/say requests
        self._say_queue: queue.Queue[dict] = queue.Queue(maxsize=100)
        self._worker_thread = threading.Thread(target=self._process_say_queue, daemon=True)
        self._worker_thread.start()

        # Status timer (1Hz)
        self.create_timer(1.0, self._publish_status_heartbeat)

        # Gerçek zinciri yaz; XTTS kapalıyken "XTTS GPU Orchestrator" demek yanıltıcıydı.
        chain = []
        if self.realtime_engine: chain.append("openai_realtime")
        if self.openai_tts: chain.append(f"openai_tts({self.openai_tts.model})")
        if self.local_xtts: chain.append("xtts_gpu")
        if self.edge_tts: chain.append("edge_tts")
        if self.local_offline_tts: chain.append("espeak")
        self.get_logger().info(
            f"🚀 [TTS Node] Hazır | TTS_ENGINE={self.tts_engine_pref} | zincir: {' -> '.join(chain)}"
        )

    def _resolve_speaker_wav(self, xtts_home: str) -> str:
        configured = os.getenv("TTS_XTTS_SPEAKER_WAV", "")
        if configured and os.path.exists(configured):
            return configured
        try:
            from ament_index_python.packages import get_package_share_directory
            packaged = os.path.join(get_package_share_directory("astro_audio"), "voices", "astro.wav")
            if os.path.exists(packaged):
                return packaged
        except Exception as _exc:
            self.get_logger().debug(f"_resolve_speaker_wav: yok sayılan hata ({_exc})")
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
        except Exception as _exc:
            self.get_logger().debug(f"_on_say: yok sayılan hata ({_exc})")

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
            self.output_manager.abort_realtime_stream(self.output_manager.current_generation)
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

            # Synthesize sentence/clauses with deterministic fallback and playback
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
    except KeyboardInterrupt as _exc:
        _LOG.debug("main: yok sayılan hata (%s)", _exc)
    finally:
        if node.local_xtts:
            node.local_xtts.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
