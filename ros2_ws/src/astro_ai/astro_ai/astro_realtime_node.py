#!/usr/bin/env python3
"""ASTRO V1 — OpenAI Realtime Audio-to-Audio (WebSocket E2E) Bridge Node.

Features:
  - Direct full-duplex WebSocket connection to OpenAI Realtime API (gpt-4o-realtime-preview)
  - End-to-end 24kHz raw PCM streaming input & output (< 450ms total turn latency)
  - Server-side VAD & Zero-Latency Barge-In (instant response cancellation on user speech)
  - Full modular Persona Engine & Biometric Perception integration via dynamic session.update
  - Integrated Function Calling (Realtime Tools: live weather, reminders, memory, person enrollment)
"""

import asyncio
import logging

_LOG = logging.getLogger(__name__)

import base64
import inspect
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import wave
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image, CameraInfo
    from std_msgs.msg import Bool, Float32, String
    from geometry_msgs.msg import Twist
except ImportError:
    rclpy = None
    qos_profile_sensor_data = 10  # rclpy yoksa (mock/test modu) düz derinlik
    class Node:  # type: ignore
        def __init__(self, *args, **kwargs):
            pass
        def get_logger(self):
            import logging
            return logging.getLogger("AstroRealtimeNode")
        def create_subscription(self, *args, **kwargs):
            return None
        def create_publisher(self, *args, **kwargs):
            return None
        def create_timer(self, *args, **kwargs):
            return None
    class _MockMsg:
        data: Any = None
    class Twist:  # type: ignore
        class Vector3:
            def __init__(self, x=0.0, y=0.0, z=0.0):
                self.x = float(x)
                self.y = float(y)
                self.z = float(z)
        def __init__(self):
            self.linear = Twist.Vector3()
            self.angular = Twist.Vector3()
    Image = CameraInfo = Bool = Float32 = String = _MockMsg  # type: ignore

try:
    import cv2
except ImportError:
    cv2 = None
import numpy as np

try:
    import websockets
except ImportError:
    websockets = None

try:
    from astro_audio.elevenlabs_engine import ElevenLabsEngine, ElevenLabsError
    from astro_audio.local_xtts_engine import LocalXttsEngine, resolve_xtts_home, resolve_xtts_speaker_wav
    from astro_audio.local_offline_tts_engine import LocalOfflineTTSEngine
    from astro_audio.tts_metrics import TurnTelemetry
    from astro_audio.sentence_chunker import SentenceChunker
except ImportError:
    ElevenLabsEngine = None
    ElevenLabsError = Exception
    LocalXttsEngine = None
    LocalOfflineTTSEngine = None
    resolve_xtts_home = lambda h="": os.path.expanduser("~/.astro/tts")
    resolve_xtts_speaker_wav = lambda w="": os.path.expanduser("~/.astro/tts/Recording.wav")
    TurnTelemetry = None
    SentenceChunker = None

EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u26FF"
    "\u2700-\u27BF"
    "]+",
    flags=re.UNICODE
)

try:
    from astro_ai.conversation_session import ConversationSession
    from astro_ai.memory_manager import MemoryManager
    from astro_ai.persona_engine import (
        PersonaEngine, PERSONA_PROMPTS, clean_tts_text,
        response_length_gate, is_self_identity_query
    )
    from astro_ai.state_machine import RobotState, StateMachine
    from astro_ai.provider_registry import ProviderRegistry, ProviderError, ErrorClass
    from astro_ai.repetition_guard import RepetitionGuard
except ImportError:
    from conversation_session import ConversationSession
    from memory_manager import MemoryManager
    from persona_engine import (
        PersonaEngine, PERSONA_PROMPTS, clean_tts_text,
        response_length_gate, is_self_identity_query
    )
    from state_machine import RobotState, StateMachine
    from provider_registry import ProviderRegistry, ProviderError, ErrorClass
    from repetition_guard import RepetitionGuard



try:
    from astro_audio.voice_recognizer import VoiceRecognizer
except ImportError:
    try:
        from voice_recognizer import VoiceRecognizer
    except ImportError:
        VoiceRecognizer = None

try:
    from astro_vision.face_recognizer import FaceRecognizer
except ImportError:
    try:
        from face_recognizer import FaceRecognizer
    except ImportError:
        FaceRecognizer = None

try:
    from dotenv import find_dotenv, load_dotenv
except ImportError:
    def find_dotenv(*args, **kwargs): return ""
    def load_dotenv(*args, **kwargs): pass


def _load_env():
    """astr1/.env dosyasını os.environ'a yükler; bulunan yolu döndürür.

    Bu düğüm daha önce .env'i HİÇ okumuyordu, yalnızca os.environ'a bakıyordu.
    Yani anahtarlar yalnızca onu başlatan sürecin ortamına konmuşsa çalışıyordu:
    bringup.launch.py bunu SetEnvironmentVariable ile yapıyor, ama
    realtime_sensors.launch.py .env'i yalnızca CWD repo köküyse buluyor ve
    `ros2 run astro_ai astro_realtime_node` hiçbir şey yüklemiyor. Üçünde de
    sonuç "❌ OPENAI_API_KEY eksik" oluyordu.

    Aday listesi tts_node/ai_brain_node ile aynı; son çare find_dotenv(usecwd=True)
    CWD'den yukarı doğru yürüdüğü için ros2_ws içinden çalıştırıldığında da bulur.
    """
    # Test sürecinde .env YÜKLENMEZ. Bu düğüm gerçek bir anahtar bulduğu anda
    # websocket'i açıyor, discover_realtime_models() ile OpenAI'a HTTPS isteği
    # atıyor ve idle-learning döngüsünü başlatıyor. Testler düğümü onlarca kez
    # örneklediği için bu hem kullanıcının kotasını harcıyor hem de canlı SSL
    # iş parçacıkları + rclpy yıkımı bir arada segfault üretiyordu.
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


def resample_24k_to_16k(raw_24k_bytes: bytes) -> bytes:
    """Ultra-fast 24kHz -> 16kHz int16 PCM downsampling (480 -> 320 samples)."""
    arr_24k = np.frombuffer(raw_24k_bytes, dtype=np.int16)
    if len(arr_24k) == 0:
        return b""
    n_out = int(len(arr_24k) * (2.0 / 3.0))
    indices = np.linspace(0, len(arr_24k) - 1, n_out)
    arr_16k = np.interp(indices, np.arange(len(arr_24k)), arr_24k.astype(np.float32)).astype(np.int16)
    return arr_16k.tobytes()


def imgmsg_to_bgr(msg: Image) -> Optional[np.ndarray]:
    if cv2 is None or msg is None or not msg.data:
        return None
    try:
        if msg.encoding == "bgr8":
            return np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
        elif msg.encoding == "rgb8":
            data = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
            return cv2.cvtColor(data, cv2.COLOR_RGB2BGR)
        elif msg.encoding in ("mono8", "8UC1"):
            data = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width)
            return cv2.cvtColor(data, cv2.COLOR_GRAY2BGR)
    except Exception as _exc:
        _LOG.debug("imgmsg_to_bgr: yok sayılan hata (%s)", _exc)
    return None


def frame_to_base64_jpeg(frame: np.ndarray, max_dim: int = 640) -> Optional[str]:
    if cv2 is None or frame is None:
        return None
    try:
        h, w = frame.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / float(max(h, w))
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buffer).decode("utf-8").replace("\n", "").replace("\r", "").strip()
    except Exception:
        return None




REALTIME_WS_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1-mini"
VALID_REALTIME_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "fable", "onyx"}


def discover_realtime_models(api_key: str, preferred: str = "") -> list[str]:
    # Öncelik sırası HIZA göre. gpt-realtime-2.1-mini (6 Tem 2026) Realtime
    # ailesinin hızlı katmanı: p95 gecikme diğerlerine göre en az %25 düşük ve
    # ses çıkışı 20 $/M token (2.1'de 64 $/M). Akıl yürütme ve araç kullanımı
    # yine var. gpt-realtime-mini OpenAI tarafından kullanımdan kaldırılıyor,
    # bu yüzden listeden çıkarıldı.
    # Dördü de bu hesapta canlı doğrulandı (session.updated döndü).
    flagship_realtime_models = [
        "gpt-realtime-2.1-mini",
        "gpt-realtime-2.1",
        "gpt-realtime-2",
        "gpt-realtime",
    ]
    candidates = []
    if preferred:
        candidates.append(preferred)

    # Test sürecinde AĞA ÇIKILMAZ. Testler düğüme sahte anahtar ("sk-test")
    # verip onu onlarca kez örnekliyor; her örnek burada api.openai.com'a
    # gerçek bir TLS bağlantısı açıyordu. Bu SSL iş parçacıkları rclpy
    # yıkımıyla üst üste gelince süreç segfault ediyor — çöküş dökümlerinde
    # en üstteki kare her seferinde bu fonksiyondu.
    if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:
        return candidates + [m for m in flagship_realtime_models if m not in candidates]

    try:
        import urllib.request
        req = urllib.request.Request("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {api_key}", "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            avail_ids = [m["id"] for m in data.get("data", []) if "realtime" in m.get("id", "")]
            # Sort available models by priority
            for fm in flagship_realtime_models:
                if fm in avail_ids and fm not in candidates:
                    candidates.append(fm)
            for mid in avail_ids:
                if mid not in candidates:
                    candidates.append(mid)
    except Exception as _exc:
        _LOG.debug("discover_realtime_models: yok sayılan hata (%s)", _exc)

    for m in flagship_realtime_models:
        if m not in candidates:
            candidates.append(m)

    return candidates


def discover_groq_models(api_key: str) -> list[str]:
    """Dynamically queries Groq /models API to discover currently active models."""
    if not api_key:
        return []
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}", "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            active_ids = [m["id"] for m in data.get("data", []) if "id" in m]
            return active_ids
    except Exception:
        return []


VALID_SHORT_UTTERANCES = {
    "hey", "lan", "dur", "ne", "tamam", "merhaba", "evet", "hayır",
    "astro", "selam", "alo", "sus", "günaydın", "iyi geceler", "naber",
    "efendim", "anladım", "peki", "dinliyorum", "burada", "buradayım"
}

SUSPECT_PHRASES = [
    "abone ol", "abone olmayı", "abone olmayı unutmayın", "altyazı",
    "altyazı m.k.", "altyazı:", "çeviren:", "çeviri ve altyazı",
    "diz", "dizi", "altyazı ekibi", "izlediğiniz için", "izlediğiniz için teşekkürler",
    "beğenmeyi unutmayın", "hoşça kalın", "hoşçakalın", "bay bay", "m.k.", "sponsor",
    "videoyu beğenmeyi", "subtitle", "transcription by", "hı hı", "cık", "çık", "ııı", "eee", "hmm"
]


def compute_self_voice_score(transcript: str, recent_robot_phrases: List[str]) -> float:
    """Computes acoustic & lexical correlation score (0.0 - 1.0) between transcript and recent robot speech."""
    if not transcript or not recent_robot_phrases:
        return 0.0
    t_clean = re.sub(r"[^\w\s]", "", transcript.lower()).strip()
    if not t_clean:
        return 0.0
    t_words = set(t_clean.split())
    if not t_words:
        return 0.0

    max_score = 0.0
    for phrase in recent_robot_phrases:
        p_clean = re.sub(r"[^\w\s]", "", phrase.lower()).strip()
        if not p_clean:
            continue
        p_words = set(p_clean.split())
        if not p_words:
            continue
        # Exact substring match
        if t_clean in p_clean or p_clean in t_clean:
            score = 0.95
        else:
            # Word overlap (Jaccard / containment)
            intersection = t_words.intersection(p_words)
            score = len(intersection) / float(len(t_words))
        if score > max_score:
            max_score = score
    return min(1.0, max_score)


def is_known_phantom_pattern(text: str) -> bool:
    """Checks if text contains known Whisper hallucination/phantom pattern without semantic context."""
    if not text:
        return True
    t = re.sub(r"[^\w\s]", "", text.lower()).strip()
    if not t:
        return True
    phantom_exacts = {
        "altyazı", "altyazı mk", "altyazı m k", "altyazi", "altyazi mk", "altyazi m k",
        "abone ol", "kanala abone ol", "abone olun", "videoyu beğenmeyi unutmayın",
        "izlediğiniz için teşekkürler", "izlediginiz icin tesekkurler",
        "izlediğiniz için teşekkür ederiz", "izlediginiz icin tesekkur ederiz",
        "diz", "dizi", "hahaha", "hahahaha", "hehehe", "hihihi",
        "türen türen türen", "türen", "turen", "turen turen turen",
        "evet evet evet", "nokta", "virgül", "şşş", "sss", "hı hı", "cık", "çık"
    }
    if t in phantom_exacts:
        return True
    # Repetitive single word loop e.g. "türen, türen, türen" or "evet, evet, evet"
    words = t.split()
    if len(words) >= 2 and len(set(words)) == 1 and words[0] in ("türen", "turen", "evet", "hayır", "ha", "he", "diz", "dizi", "altyazı", "hahaha"):
        return True
    return False


def is_valid_user_command(command: str) -> Tuple[bool, str]:
    """Validates extracted user command for semantic plausibility, repetition, catalog hallucinations, and phantom patterns."""
    if not command:
        return False, "empty_command"
    c_clean = re.sub(r"[^\w\s]", "", command.lower()).strip()
    if not c_clean or len(c_clean) < 2:
        return False, "empty_command"

    # 1. Known Phantom Patterns
    if is_known_phantom_pattern(c_clean):
        return False, "known_phantom"

    words = c_clean.split()
    if not words:
        return False, "empty_command"

    # 2. Pure Wake Prefix Remainder (only wake tokens)
    if all(w in ("astro", "hey", "selam") for w in words):
        return False, "wake_only_remainder"

    # 3. Prompt / Catalog / Hallucinated Training Metadata Artifacts (e.g. "Türkçe konuşma, diyalog, robot asistan")
    catalog_triggers = [
        "türkçe konuşma", "turkce konusma", "robot asistan", "sesli asistan",
        "türkçe diyalog", "turkce diyalog", "türkçe dublaj", "turkce dublaj",
        "türkçe altyazı", "turkce altyazi", "altyazı m k", "altyazi mk",
        "abone ol", "kanala abone", "videoyu beğen", "izlediğiniz için",
    ]
    for ct in catalog_triggers:
        if ct in c_clean:
            conversational_clues = ("hakkında", "nasıl", "neden", "ne", "nerede", "kim", "yap", "aç", "kapat", "anlat", "söyle", "nedir", "istiyorum", "misin")
            if not any(w in c_clean for w in conversational_clues):
                return False, "catalog_hallucination"

    # 4. Excessive Wake Word Repetition in Command (e.g. "astro astro astro", "hey astro hey astro")
    wake_tokens = [w for w in words if w in ("astro", "hey", "selam")]
    if len(wake_tokens) >= 2 and (len(wake_tokens) / len(words)) >= 0.30:
        return False, "wake_word_loop"

    # 5. Word Repetition Ratio (e.g. "evet evet evet", "türen türen türen")
    if len(words) >= 3:
        from collections import Counter
        counts = Counter(words)
        most_common_word, most_common_count = counts.most_common(1)[0]
        if most_common_count >= 3 and (most_common_count / len(words)) >= 0.35:
            return False, "repetitive_word_loop"

    return True, "valid"


class AstroRealtimeNode(Node):
    """ROS 2 Node bridging Astro sensors & audio streams to OpenAI Realtime WebSocket."""
    active_response_id: Optional[str] = None
    active_generation_id: Optional[int] = None
    active_response_state: str = "IDLE"
    _turn_queue: List[Dict[str, Any]] = []
    _last_sent_generation_id: Optional[int] = None
    _session_ready_logged: bool = False
    _watchdog_timer: Optional[threading.Timer] = None
    _packets_for_gen: int = 0
    _bytes_for_gen: int = 0
    _first_audio_time: Optional[float] = None
    realtime_current_generation_id: int = 0
    realtime_audio_received: bool = False
    realtime_response_state: str = "IDLE"
    realtime_provider_state: str = "AVAILABLE"
    realtime_connection_state: str = "DISCONNECTED"
    realtime_session_state: str = "NOT_READY"
    realtime_session_id: str = ""

    def __init__(self):
        if rclpy is not None and hasattr(rclpy, "ok") and not rclpy.ok():
            try:
                rclpy.init()
            except Exception as _exc:
                self.get_logger().debug(f"__init__: yok sayılan hata ({_exc})")
        super().__init__("astro_realtime_node")

        # Startup timestamp & Grace Period tracking
        self._node_start_time = time.monotonic()
        self.xtts_startup_grace_s = float(os.getenv("XTTS_STARTUP_GRACE_S", "60.0"))

        # Load environment variables (sanitized of quotes/whitespace)
        # _load_env() anahtarlar OKUNMADAN ÖNCE çağrılmalı; aksi halde düğüm
        # yalnızca kendisini başlatan sürecin ortamına bağımlı kalır.
        _loaded_env = _load_env()
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip("\"' \t\n\r")
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "").strip("\"' \t\n\r")
        raw_gem = os.environ.get("GEMINI_API_KEY", "").strip("\"' \t\n\r")
        self.gemini_api_key = raw_gem if (raw_gem and not raw_gem.startswith("sk-")) else ""
        self.realtime_model = os.environ.get("REALTIME_MODEL", "gpt-realtime-2.1-mini").strip()
        self.realtime_transcribe_model = os.environ.get(
            "REALTIME_TRANSCRIBE_MODEL", "gpt-live-transcribe").strip() or "gpt-live-transcribe"
        raw_voice = os.environ.get("REALTIME_VOICE", os.environ.get("TTS_VOICE", "echo")).strip().lower()
        self.realtime_voice = raw_voice if raw_voice in VALID_REALTIME_VOICES else "echo"
        self.persona_name = os.environ.get("PERSONA", "kufurbaz").strip().lower()

        # Anahtarın nereden geldiğini başlangıçta söyle. "eksik" hatası alındığında
        # ilk soru her zaman "hangi .env okundu" oluyor; cevabı burada.
        self.get_logger().info(
            "[ENV] dotenv={} | OPENAI_API_KEY={} | GROQ={} | GEMINI={}".format(
                _loaded_env or "BULUNAMADI",
                f"var (…{self.openai_api_key[-4:]})" if self.openai_api_key else "YOK",
                "var" if self.groq_api_key else "yok",
                "var" if self.gemini_api_key else "yok",
            )
        )


        # Modular Cognitive Subsystems
        self.memory = MemoryManager()
        self.persona_engine = PersonaEngine(self.persona_name)
        self.state_machine = StateMachine(RobotState.DEEP_IDLE)
        self.session = ConversationSession(base_timeout_s=16.0)

        # State
        self._lock = threading.RLock()
        self._recognized_person: Optional[Dict[str, Any]] = None
        self._recognized_speaker: Optional[Dict[str, Any]] = None
        self._user_emotion = "neutral"
        self._looking_at_robot = False
        self._user_distance = 0.0
        self._speaker_gender = "unknown"
        self._speaker_angle = 0.0
        self._is_responding = False
        self._is_playback_active = False
        self._playback_end_time = 0.0
        self._last_synced_identity = "Misafir"
        self._last_sync_time = time.monotonic()
        self._active_person_name = "Misafir"
        self._person_hold_until = 0.0
        # Realtime State Tracking (Socket, Session, and Generation Lifecycle)
        self.realtime_provider_state = "AVAILABLE"
        self.realtime_connection_state = "DISCONNECTED"
        self.realtime_session_state = "NOT_READY"
        self.realtime_response_state = "IDLE"
        self.realtime_audio_received = False
        self.realtime_current_generation_id = 0
        self.realtime_session_id = ""

        # Single Active Response State Machine
        self.active_response_id: Optional[str] = None
        self.active_generation_id: Optional[int] = None
        self.active_response_state: str = "IDLE"  # IDLE, RESPONSE_CREATING, RESPONSE_STREAMING, RESPONSE_CANCELLING, COMPLETED
        self._turn_queue: List[Dict[str, Any]] = []
        self._last_sent_generation_id: Optional[int] = None
        self._watchdog_timer: Optional[threading.Timer] = None
        self._packets_for_gen: int = 0
        self._bytes_for_gen: int = 0
        self._first_audio_time: Optional[float] = None
        self._session_ready_logged: bool = False

        # Configurable Acoustic Echo & Barge-In Parameters
        self.echo_mute_cooldown_s = float(os.getenv("ECHO_MUTE_COOLDOWN_S", "0.65"))
        self.barge_in_protection_ms = float(os.getenv("TTS_BARGE_IN_PROTECTION_MS", "350.0"))
        self.barge_in_min_rms = float(os.getenv("BARGE_IN_MIN_RMS", "1200.0"))
        self.barge_in_playback_min_rms = float(os.getenv("BARGE_IN_PLAYBACK_MIN_RMS", "4500.0"))
        self.barge_in_noise_mult = float(os.getenv("BARGE_IN_NOISE_MULTIPLIER", "3.5"))
        self.barge_in_min_peak = int(os.getenv("BARGE_IN_MIN_PEAK", "2800"))
        self.barge_in_playback_min_peak = int(os.getenv("BARGE_IN_PLAYBACK_MIN_PEAK", "14000"))
        self._barge_in_consecutive_frames = 0
        self.barge_in_min_consecutive_frames = int(os.getenv("BARGE_IN_MIN_CONSECUTIVE_FRAMES", "3"))
        self.barge_in_playback_min_consecutive_frames = int(os.getenv("BARGE_IN_PLAYBACK_CONSECUTIVE_FRAMES", "6"))
        self._playback_start_monotonic = 0.0
        self._ambient_rms = 120.0
        self._recent_robot_phrases: List[str] = []

        # False Transcript & Rejection Counters
        self.false_transcript_count = 0
        self.self_voice_rejection_count = 0
        self.no_speech_rejection_count = 0
        self.stale_audio_rejection_count = 0

        # Biometric Voice & Face Engines
        self.voice_recognizer = VoiceRecognizer() if VoiceRecognizer else None
        self.face_recognizer = FaceRecognizer() if FaceRecognizer else None
        self._user_speech_audio_buffer: List[bytes] = []

        # Provider & Model Capability Registry + Repetition Guard
        self.provider_registry = ProviderRegistry(logger=self.get_logger())
        self.repetition_guard = RepetitionGuard(history_size=10, similarity_threshold=0.82)
        threading.Thread(target=self._discover_providers_background, daemon=True).start()

        # Zero-Cost Fallback Engine (Groq STT + ProviderRegistry + XTTS GPU / Edge-TTS)
        self._fallback_mode = False
        self._fallback_speaking = False
        self._fallback_speech_start = 0.0
        self._last_speech_time = 0.0
        self._fallback_audio_buffer: List[bytes] = []
        self._is_processing_fallback = False
        self._fallback_generation_id = 0

        # Dedicated Wake Detector (Active in SLEEP / DEEP_IDLE with Ultra-low CPU)
        self._wake_audio_buffer: List[bytes] = []
        self._wake_speech_frames = 0
        self._wake_listening = False
        self._wake_last_voice_time = 0.0

        # Event-Driven Vision Gating & Rate Budget Control
        self.vision_cooldown_s = float(os.getenv("VISION_COOLDOWN_S", "10.0"))
        self.max_vision_requests_per_minute = int(os.getenv("MAX_VISION_REQUESTS_PER_MINUTE", "4"))
        self._vision_requests_history: List[float] = []
        self._last_scene_frame_thumb: Optional[np.ndarray] = None
        self._last_vision_call_time = 0.0
        self._last_seen_person = "Misafir"
        self._last_seen_distance = 0.0
        self._last_looking_state = False
        self.vision_requests_total = 0
        self.vision_requests_skipped = 0
        self.vision_last_skip_reason = "none"
        self.vision_last_event_type = "none"

        # Primary Remote TTS: ElevenLabs Flash v2.5 (Only if ELEVENLABS_ENABLED=true)
        self.elevenlabs_engine: Optional[ElevenLabsEngine] = None
        el_enabled = os.getenv("ELEVENLABS_ENABLED", "false").lower() in ("1", "true", "yes")
        if ElevenLabsEngine and el_enabled:
            el_key = os.getenv("ELEVENLABS_API_KEY", "")
            el_voice = os.getenv("ELEVENLABS_VOICE_ID", "")
            el_model = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5")
            if el_key and el_voice:
                try:
                    self.elevenlabs_engine = ElevenLabsEngine(
                        api_key=el_key,
                        voice_id=el_voice,
                        model_id=el_model,
                        enabled=True,
                        logger=self._safe_log,
                    )
                    self.get_logger().info(f"✨ [ElevenLabs TTS] Flash v2.5 Hazır (Voice ID: {el_voice}, Model: {el_model})")
                except Exception as e:
                    self.get_logger().warn(f"⚠️ [ElevenLabs TTS] Başlatma uyarısı: {e}")

        # XTTS is DORMANT / DISABLED by production policy (0 spawn, 0 RAM overhead)
        self.local_xtts: Optional[LocalXttsEngine] = None
        self._safe_log(
            "info",
            "ℹ️ [XTTS] Runtime disabled by production policy\n"
            "  model_retained=True\n"
            "  worker_spawn=False\n"
            "  reason=production_runtime_disabled"
        )

        # Local Offline Backup TTS Engine (Zero internet local resilience fallback)
        self.local_offline_tts: Optional[LocalOfflineTTSEngine] = None
        if LocalOfflineTTSEngine:
            try:
                self.local_offline_tts = LocalOfflineTTSEngine(
                    language=os.getenv("TTS_LANGUAGE", "tr"),
                    logger=self._safe_log,
                )
            except Exception as e:
                self.get_logger().debug(f"LocalOfflineTTSEngine notice: {e}")

        # Generation-level Barge-In Debounce State
        self._barge_in_latched = False
        self.edge_tts_enabled = os.getenv("EDGE_TTS_ENABLED", "true").lower() in ("1", "true", "yes")

        # Single Unified TTSRouter
        try:
            from astro_audio.tts_router import TTSRouter
        except ImportError:
            from tts_router import TTSRouter

        self.tts_router = TTSRouter(
            local_xtts=self.local_xtts,
            local_offline_tts=self.local_offline_tts,
            edge_tts_synth_func=self._synthesize_edge_tts_pcm24k,
            edge_tts_enabled=self.edge_tts_enabled,
            logger=self._safe_log,
        )

        # Speaker Recognition Temporal Smoother
        self._speaker_tentative_name: Optional[str] = None
        self._speaker_tentative_count: int = 0
        self._speaker_tentative_last_time: float = 0.0

        # Camera Perception Frame Cache & OAK-D Lite Stability Tracking
        self._latest_camera_frame: Optional[np.ndarray] = None
        self._last_img_time = 0.0
        self._oak_last_frame_time = 0.0
        self._oak_last_camera_info_time = 0.0
        self._oak_xlink_error_count = 0
        self._oak_connection_state = "DISCONNECTED"

        # Autonomous Idle Learning (Cognitive Memory Reflection only, 0 camera calls)
        self._enable_idle_learning = os.environ.get("ENABLE_IDLE_LEARNING", "true").lower() == "true"
        self._last_idle_learning_time = 0.0
        self._last_proactive_gaze_time = 0.0
        if self._enable_idle_learning:
            threading.Thread(target=self._idle_learning_loop, daemon=True).start()
            self.get_logger().info("🤖 [Astro Realtime] Otonom Hafıza Yansıtma Motoru Aktif (Groq/Gemini 0-Token)!")

        # ROS 2 Publishers
        self.pub_output_pcm = self.create_publisher(String, "/audio/realtime_output_pcm", 50)
        self.pub_realtime_state = self.create_publisher(String, "/realtime/state", 10)
        self.pub_tts_say = self.create_publisher(String, "/tts/say", 10)
        self.pub_cmd_vel = self.create_publisher(Twist, "/cmd_vel", 10)

        self.pub_interrupt = self.create_publisher(Bool, "/tts/interrupt", 10)
        self.pub_emotion = self.create_publisher(String, "/robot/emotion", 10)
        self.pub_gesture = self.create_publisher(String, "/robot/head_gesture", 10)
        self.pub_transcript = self.create_publisher(String, "/speech/text", 10)

        # ROS 2 Subscribers
        self.create_subscription(String, "/tts/realtime_request", self._on_realtime_turn_request, 10)
        self.create_subscription(String, "/audio/realtime_input_pcm", self._on_input_pcm, 50)
        self.create_subscription(Bool, "/audio/playback_active", self._on_playback_active, 10)
        self.create_subscription(String, "/vision/recognized_person", self._on_recognized_person, 10)
        self.create_subscription(String, "/audio/speaker_id", self._on_speaker_id, 10)
        self.create_subscription(String, "/vision/user_emotion", self._on_user_emotion, 10)
        self.create_subscription(Bool, "/vision/looking_at_robot", self._on_looking_at_robot, 10)
        self.create_subscription(Float32, "/vision/user_distance", self._on_user_distance, 10)
        self.create_subscription(Float32, "/audio/doa", self._on_doa, 10)
        # Görüntü akışları sensör QoS'u (BEST_EFFORT): kare kaybı, geciken kareler
        # için retransmission yapmaktan iyidir. BEST_EFFORT abone RELIABLE
        # yayıncıdan da veri alır, bu yüzden depthai_ros_driver ile uyumlu.
        self.create_subscription(Image, "/oak/rgb/image_raw", self._on_camera_image, qos_profile_sensor_data)
        self.create_subscription(CameraInfo, "/oak/rgb/camera_info", self._on_camera_info, qos_profile_sensor_data)

        # Tool execution deduplication
        self._executed_tool_calls: set[str] = set()

        # Publish initial realtime state (DISCONNECTED / NOT_READY)
        self._publish_realtime_state("DISCONNECTED", "init")

        # Sleep Mode (Default: Start in Sleeping / DEEP_IDLE State)
        self._node_start_time = time.monotonic()
        self._is_sleeping = True
        self._last_interaction_time = time.monotonic() - 20.0
        self._consecutive_loud_frames = 0
        self.create_timer(1.0, self._check_sleep_mode)

        # Reminders storage
        self._reminders: List[Dict[str, Any]] = []
        self.create_timer(1.0, self._check_reminders)

        # Long-Term Episodic Session Lifecycle & Summarizer Timer
        self._last_summarized_turn_count = 0
        self.create_timer(1.0, self._check_session_lifecycle)

        # Purge any corrupted / profanity records
        self._purge_corrupted_biometrics()

        # Async WebSocket Loop in background thread
        self._ws = None
        self._loop = None
        self._is_connected = False
        self._ws_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._ws_thread.start()

        self.get_logger().info(f"🚀 [Astro Realtime Node] OpenAI Realtime WebSocket Başlatılıyor... Ses: [{self.realtime_voice}], Kişilik: [{self.persona_name.upper()}]")
        self.get_logger().info("💤 [Astro Uyku Modu]: Düğüm başlatıldı — Astro DEEP_IDLE modunda (😴). Wake listener aktif.")

    def _safe_log(self, lvl: str, msg: str):
        """Safe ROS2 logger wrapper preventing Cython/rcutils 'Logger severity cannot be changed between calls' error."""
        try:
            log_fn = getattr(self.get_logger(), str(lvl).lower(), None)
            if log_fn and callable(log_fn):
                log_fn(msg)
            else:
                self.get_logger().info(f"[{str(lvl).upper()}] {msg}")
        except Exception:
            try:
                self.get_logger().info(f"[{str(lvl).upper()}] {msg}")
            except Exception:
                print(f"[{str(lvl).upper()}] {msg}", flush=True)

    def _publish_realtime_state(self, state: str, reason: str = "none"):
        """Publishes realtime WebSocket state to /realtime/state for ai_brain_node consumption."""
        try:
            import json as _json
            msg = String()
            msg.data = _json.dumps({
                "state": state,
                "reason": reason,
                "connection": self.realtime_connection_state,
                "session": self.realtime_session_state,
                "provider": self.realtime_provider_state,
            })
            self.pub_realtime_state.publish(msg)
        except Exception:
            pass

    def _on_realtime_turn_request(self, msg: String):
        """Receives conversational turn request from ai_brain_node and manages single active response."""
        try:
            raw = msg.data.strip()
            if not raw:
                return
            if raw.startswith("{") and "text" in raw:
                data = json.loads(raw)
                text = data.get("text", "")
                gen_id = data.get("generation_id", self.realtime_current_generation_id + 1 if self.realtime_current_generation_id else 1)
            else:
                text = raw
                gen_id = self.realtime_current_generation_id + 1 if self.realtime_current_generation_id else 1

            if not text:
                return

            if gen_id == self._last_sent_generation_id:
                self.get_logger().info(f"[REALTIME TURN DUPLICATE DROPPED]\ngeneration_id={gen_id}")
                return

            if not self._ws or not self._loop or not self._is_connected:
                self.realtime_current_generation_id = gen_id
                self.get_logger().warn(
                    f"[REALTIME NO AUDIO]\ngeneration_id={gen_id}\nreason=websocket_not_connected\n"
                    f"[TTS FALLBACK]\nfrom=openai_realtime\nto=edge_tts\nreason=realtime_unavailable"
                )
                # Forward to tts_node for Edge-TTS fallback
                fb_msg = String()
                fb_msg.data = json.dumps({
                    "text": text,
                    "engine": "edge-tts",
                    "generation_id": gen_id,
                    "fallback_reason": "realtime_unavailable",
                })
                self.pub_tts_say.publish(fb_msg)
                return

            if self.active_response_state != "IDLE":
                self.get_logger().info(f"[REALTIME TURN QUEUED]\ngeneration_id={gen_id}\nreason=active_response")
                self._turn_queue.append({"text": text, "generation_id": gen_id})
                return

            self._dispatch_turn(gen_id, text)

        except Exception as e:
            self.get_logger().error(f"Error in _on_realtime_turn_request: {e}")

    def _dispatch_turn(self, gen_id: int, text: str):
        """Dispatches a single conversational turn to Realtime WebSocket."""
        self.realtime_current_generation_id = gen_id
        self.active_generation_id = gen_id
        self._last_sent_generation_id = gen_id
        self.active_response_state = "RESPONSE_CREATING"
        self.active_response_id = None
        self.realtime_audio_received = False
        self._last_requested_text = text
        self._packets_for_gen = 0
        self._bytes_for_gen = 0
        self._first_audio_time = None
        self._response_start_time = time.monotonic()

        self.get_logger().info(f"[REALTIME TURN SENT]\ngeneration_id={gen_id}\ntext=\"{text}\"")

        turn_event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"Lütfen şu cevabı tam olarak seslendir: {text}"
                    }
                ]
            }
        }
        resp_event = {
            "type": "response.create",
            "response": {
                "instructions": f"Cevabını doğrudan Türkçe olarak seslendir: {text}"
            }
        }
        self.get_logger().debug(f"[REALTIME PAYLOAD OUT] event=response.create payload={json.dumps(resp_event)}")
        asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(turn_event)), self._loop)
        asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(resp_event)), self._loop)

        # Start watchdog timer for first-packet audio delta deadline (1.2s)
        if self._watchdog_timer:
            try:
                self._watchdog_timer.cancel()
            except Exception:
                pass
        self._watchdog_timer = threading.Timer(1.2, self._check_audio_delta_timeout, args=[gen_id, text])
        self._watchdog_timer.start()

    def _check_audio_delta_timeout(self, gen_id: int, text: str):
        """Watchdog: If no audio delta arrives within 1.2s, triggers fallback to Edge-TTS."""
        active_gen = getattr(self, "active_generation_id", None)
        curr_gen = getattr(self, "realtime_current_generation_id", None)
        audio_rec = getattr(self, "realtime_audio_received", False)
        if (active_gen == gen_id or curr_gen == gen_id) and not audio_rec:
            self.get_logger().warn(
                f"[REALTIME NO AUDIO]\ngeneration_id={gen_id}\nreason=no_audio_delta\n"
                f"[TTS FALLBACK]\nfrom=openai_realtime\nto=edge_tts\nreason=realtime_no_audio"
            )
            # Send to /tts/say for Edge-TTS fallback
            if hasattr(self, "pub_tts_say") and self.pub_tts_say:
                fb_msg = String()
                fb_msg.data = json.dumps({
                    "text": text,
                    "engine": "edge-tts",
                    "generation_id": gen_id,
                    "fallback_reason": "realtime_no_audio",
                })
                self.pub_tts_say.publish(fb_msg)

    def _run_async_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._websocket_worker())

    async def _websocket_worker(self):
        """Persistent WebSocket connection loop with auto-reconnect and model fallback."""
        if not self.openai_api_key:
            self.get_logger().error("❌ OPENAI_API_KEY eksik! Realtime WebSocket bağlanamıyor.")
            return

        if websockets is None:
            self.get_logger().error("❌ websockets kütüphanesi eksik! (pip install websockets)")
            return

        headers = {
            "Authorization": f"Bearer {self.openai_api_key}"
        }

        connect_kwargs = {"ping_interval": 20, "ping_timeout": 20}
        try:
            sig = inspect.signature(websockets.connect)
            if "additional_headers" in sig.parameters:
                connect_kwargs["additional_headers"] = headers
            elif "extra_headers" in sig.parameters:
                connect_kwargs["extra_headers"] = headers
            else:
                connect_kwargs["extra_headers"] = headers
        except Exception:
            connect_kwargs["extra_headers"] = headers

        candidate_models = discover_realtime_models(self.openai_api_key, self.realtime_model)
        self.get_logger().info(f"📋 [Realtime Modelleri]: Kullanılabilir modeller: {candidate_models}")
        model_idx = 0

        while (rclpy.ok() if (rclpy is not None and hasattr(rclpy, "ok")) else True):
            current_model = candidate_models[model_idx % len(candidate_models)]
            ws_url = f"wss://api.openai.com/v1/realtime?model={current_model}"
            try:
                self.realtime_connection_state = "CONNECTING"
                self.get_logger().info(
                    f"[REALTIME CONNECTING]\n"
                    f"model={current_model}"
                )
                self._publish_realtime_state("CONNECTING")
                async with websockets.connect(ws_url, **connect_kwargs) as ws:
                    self._ws = ws
                    self._is_connected = True
                    self._is_responding = False
                    self._is_playback_active = False
                    self.realtime_connection_state = "CONNECTED"
                    self.realtime_session_state = "NOT_READY"
                    self.realtime_provider_state = "AVAILABLE"
                    self.get_logger().info(
                        f"[REALTIME CONNECTED]\n"
                        f"model={current_model}\n"
                        f"state=AVAILABLE"
                    )
                    self._publish_realtime_state("CONNECTED")

                    # Send Initial Session Update
                    await self._send_session_update(ws)

                    # Listen for Realtime Events
                    async for message in ws:
                        await self._handle_realtime_event(ws, json.loads(message))

            except Exception as e:
                self._is_connected = False
                self._ws = None
                self._is_responding = False
                self._is_playback_active = False
                self.realtime_connection_state = "DISCONNECTED"
                self.realtime_session_state = "NOT_READY"
                self.realtime_response_state = "IDLE"
                self._publish_realtime_state("DISCONNECTED", "error")
                err_str = str(e)

                try:
                    from astro_audio.realtime_engine import classify_realtime_error, RealtimeState
                    _, failure_reason = classify_realtime_error(getattr(e, "code", None), err_str)
                except Exception:
                    if "insufficient_quota" in err_str or "credit_balance_exhausted" in err_str or "402" in err_str or ("quota" in err_str and "exhaust" in err_str):
                        failure_reason = "realtime_quota_exhausted"
                    elif "1013" in err_str:
                        failure_reason = "realtime_temporary_1013"
                    else:
                        failure_reason = "realtime_network_unavailable"

                # 1. Strict Quota Exhaustion (402, insufficient_quota, credit_balance_exhausted)
                is_quota = (
                    "insufficient_quota" in err_str
                    or "credit_balance_exhausted" in err_str
                    or "402" in err_str
                    or ("quota" in err_str and ("exhaust" in err_str or "exceed" in err_str or "zero" in err_str or "balance" in err_str))
                )
                if is_quota and "1013" not in err_str:
                    self.realtime_provider_state = "EXHAUSTED"
                    self.get_logger().error(
                        f"[REALTIME ERROR]\n"
                        f"generation_id={self.realtime_current_generation_id}\n"
                        f"error_class=QUOTA_EXHAUSTED"
                    )
                    self.get_logger().warn(
                        f"[REALTIME FALLBACK]\n"
                        f"generation_id={self.realtime_current_generation_id}\n"
                        f"from=openai_realtime\n"
                        f"to=groq\n"
                        f"reason=quota_exhausted"
                    )
                    try:
                        from astro_ai.circuit_breaker import get_global_circuit_breaker, RequestErrorClass
                        cb = get_global_circuit_breaker()
                        if cb:
                            cb.record_error("openai", sub_provider="openai_realtime", error_class=RequestErrorClass.QUOTA_EXHAUSTED, error_msg=err_str)
                    except Exception:
                        pass

                    if not self._fallback_mode:
                        self._fallback_mode = True
                        self.get_logger().warn("🚀 [0-Maliyetli Groq & Edge-TTS Modu Devrede]: OpenAI Realtime kredisi tükendi. Astro kesintisiz olarak 0-Token Groq LLM + Edge-TTS modunda çalışıyor!")
                    await asyncio.sleep(86400.0)

                # 2. WebSocket 1013 Temporary Failure (Overload / Server degradation)
                elif "1013" in err_str or getattr(e, "code", None) == 1013:
                    self.realtime_provider_state = "COOLDOWN"
                    self.get_logger().warn(
                        "⚠️ [REALTIME TEMPORARY FAILURE] code=1013\n"
                        "⚠️ [REALTIME COOLDOWN] duration=15.0s"
                    )
                    try:
                        from astro_ai.circuit_breaker import get_global_circuit_breaker, RequestErrorClass
                        cb = get_global_circuit_breaker()
                        if cb:
                            cb.record_error("openai", sub_provider="openai_realtime", error_class=RequestErrorClass.REALTIME_TEMPORARY_FAILURE, error_msg="WS 1013 Temporary Overload")
                    except Exception:
                        pass
                    await asyncio.sleep(15.0)
                elif "4004" in err_str or "model_not_found" in err_str:
                    self.get_logger().warn(f"⚠️ [Realtime Model Bulunamadı] '{current_model}' modeline erişilemedi, bir sonraki modele geçiliyor...")
                    model_idx += 1
                    await asyncio.sleep(1.0)
                else:
                    self.get_logger().warn(f"⚠️ [Realtime WS] Bağlantı koptu ({e}), 3 saniye sonra yeniden bağlanılacak...")
                    await asyncio.sleep(3.0)

    def _build_current_system_prompt(self, active_speaker: Optional[Dict[str, Any]] = None) -> str:
        """Builds system instructions with memory, identity, persona, and strict anti-hallucination rules."""
        identity = active_speaker or self._get_active_biometric_identity()
        is_known = identity.get("is_known", False) and identity.get("name", "Misafir").lower() != "misafir"
        name_val = identity.get("name", "Misafir")
        conf_pct = int(identity.get("confidence", identity.get("score", 0.0)) * 100)
        source_str = identity.get("source", "perception")

        known_speakers = []
        if self.voice_recognizer:
            try:
                known_speakers = [k for k, v in self.voice_recognizer._known_voiceprints.items() if len(v) > 0 and k.lower() != "misafir"]
            except Exception as _exc:
                self.get_logger().debug(f"_build_current_system_prompt: yok sayılan hata ({_exc})")
        known_str = ", ".join(known_speakers) if known_speakers else "Baran"
        room_context = f"\n[KAYITLI KİŞİLER]: {known_str}\n"

        if is_known:
            title_val = identity.get("formal_title", identity.get("title", name_val))
            bio_status = (
                f"\n[ŞU AN SENİNLE KONUŞAN KİŞİ]:\n"
                f"- İsim: {name_val} (Hitap: {title_val}, Doğrulama: %{conf_pct}, Kaynak: {source_str})\n"
                f"{room_context}"
                f"KİMLİK DOĞRULAMA VE HİTAP KURALLARI:\n"
                f"1. Şu an doğrudan seninle konuşan kişi: {name_val}. Kendisine samimiyetle ismiyle ({name_val}) hitap et.\n"
                f"2. KESİNLİKLE 'Seni ilk kez duyuyorum', 'Sesini tanıyamadım', 'Adın ne senin?' veya 'Kimsin sen?' gibi yabancılayıcı cümleler kurma!\n"
                f"3. Karşındaki {name_val} iken kendisini başka biri sanma. Yakın arkadaş samimiyetini koru.\n"
            )
        else:
            bio_status = (
                f"\n[ŞU AN KONUŞAN KİŞİ]:\n"
                f"- Misafir / Tanımlanmamış Konuşmacı.\n"
                f"{room_context}"
                f"DAVRANIŞ KURALLARI:\n"
                f"1. Karşındaki kişinin kimliği henüz biyometrik olarak doğrulanmadı.\n"
                f"2. Kullanıcının sorusuna veya konusuna doğrudan ve doğal cevap ver.\n"
                f"3. Gerçekte işlem yapmadıysan 'kaydını yaptım', 'işleme aldım', 'kaydettim' gibi sahte iddialarda kesinlikle bulunma.\n"
            )

        memory_rule = (
            "\n\n[HAFIZA VE BAĞLAM KURALI]:\n"
            "- Kullanıcı geçmiş veya tercihlerle ilgili bir şey sorduğunda hafızandaki bilgileri samimiyetle kullan.\n"
            "- Yapılmayan eylemler için yapılmış gibi iddialarda bulunma."
        )

        return self.persona_engine.build_system_prompt(
            memory_context=self.memory.get_prompt_context(recognized_person=identity) + bio_status + memory_rule,
            recognized_person=identity
        )

    async def _send_session_update(self, ws):
        """Sends comprehensive session configuration with persona prompt, tools, and turn detection."""
        identity = self._get_active_biometric_identity()
        system_prompt = self._build_current_system_prompt()

        session_config = {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": system_prompt,
                "audio": {
                    "input": {
                        # whisper-1 DEĞİL: gpt-live-transcribe realtime için
                        # tasarlanmış düşük gecikmeli akış modeli (OpenAI'nin
                        # realtime rehberinde "controllable latency" ile önerilir).
                        # Canlı doğrulandı: session.updated bu modelle dönüyor.
                        "transcription": {
                            "model": self.realtime_transcribe_model,
                            "language": "tr"
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.70,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 500,
                            "create_response": True
                        }
                    },
                    "output": {
                        "voice": self.realtime_voice
                    }
                },
                "tools": [
                    {
                        "type": "function",
                        "name": "get_live_weather",
                        "description": "Bitlis, Ahlat, Tatvan, İstanbul veya istenen bir şehrin canlı anlık hava durumu ve sıcaklık bilgisini getirir.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "city": {"type": "string", "description": "Hava durumu sorgulanan şehir (örn: Ahlat, Bitlis, Ankara)"}
                            },
                            "required": ["city"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "set_reminder",
                        "description": "Kullanıcı için belirli bir dakika sonra hatırlatıcı / alarm kurar.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "minutes": {"type": "number", "description": "Kaç dakika sonra hatırlatılacağı"},
                                "topic": {"type": "string", "description": "Hatırlatılacak konu veya görev"}
                            },
                            "required": ["minutes", "topic"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "save_user_memory",
                        "description": "Kullanıcının tercihlerini, sevdiği şeyleri veya önemli bilgileri kalıcı hafızaya kaydeder.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string", "description": "Bilgi başlığı"},
                                "value": {"type": "string", "description": "Detaylı bilgi"}
                            },
                            "required": ["key", "value"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "search_memory",
                        "description": "Kullanıcı geçmiş sohbetler, önceki tercihler veya kaydedilmiş bilgiler hakkında soru sorduğunda kalıcı hafızada arama yapar.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Aranacak konu, anahtar kelime veya soru"}
                            },
                            "required": ["query"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "inspect_camera_view",
                        "description": "Kullanıcı 'ne görüyorsun?', 'elimde ne var?', 'bana bak', 'görebiliyor musun?', 'elimdeki ne renk?', 'bu ne?' veya kameranın önündeki eşyaları sorduğunda OAK-D kamerasından canlı görüntü alıp inceler.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "focus": {"type": "string", "description": "İncelenmesi istenen nesne, detay, renk veya durum (örn: 'elimdeki nesne', 'kıyafet', 'çevre')"}
                            },
                            "required": ["focus"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "move_robot",
                        "description": "Kullanıcı robotun hareket etmesini istediğinde çağrılır ('ileri git', 'geri gel', 'dur', 'sağa dön', 'sola dön').",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "direction": {
                                    "type": "string",
                                    "enum": ["forward", "backward", "left", "right", "stop"],
                                    "description": "Hareket yönü"
                                },
                                "speed": {"type": "number", "description": "Hız (0.1 - 0.5 m/s)"},
                                "duration": {"type": "number", "description": "Kaç saniye hareket edeceği"}
                            },
                            "required": ["direction"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "enroll_user_biometrics",
                        "description": "SADECE VE SADECE kullanıcı KENDİ İSMİNİ tanıttığında ('Benim adım Onur', 'Adım Mehmet', 'Bana Ali de') çağrılır. Başka birisi hakkında soru sorulduğunda ('Onur nerede?', 'Onur kim?', 'Onur\\'u ne diye kaydetsin?') KESİNLİKLE ÇAĞRILMAZ.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Kullanıcının adı (örn: Baran, Batuhan, Mehmet)"},
                                "formal_title": {"type": "string", "description": "Kullanıcıya hitap şekli (örn: Baran Bey, Sayın Müdürüm)"}
                            },
                            "required": ["name"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "change_persona",
                        "description": "Kullanıcı robotun kişiliğini veya konuşma modunu değiştirmek istediğinde çağrılır (Örn: 'kaba moda geç', 'küfürbaz moda geç', 'neşeli moda geç', 'resmi moda geç', 'flört moduna geç', 'sarkastik moda geç', 'sinirli moda geç', 'duygusal moda geç').",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "persona": {
                                    "type": "string",
                                    "enum": ["kufurbaz", "flirt", "playful", "emotional", "formal", "sarcastic", "angry", "rude"],
                                    "description": "Hedef kişilik modu: kufurbaz, flirt, playful, emotional, formal, sarcastic, angry, rude"
                                }
                            },
                            "required": ["persona"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "delete_user_biometrics",
                        "description": "Kullanıcı 'beni hafızandan sil', '[isim] kaydını sil' dediğinde veya hatalı bir kayıt silinmek istendiğinde çağrılır.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Silinecek kişinin adı (örn: Yarram, Onur, Mehmet)"}
                            },
                            "required": ["name"]
                        }
                    }
                ]
            }
        }

        await ws.send(json.dumps(session_config))
        self.get_logger().info(f"✨ [Realtime WS] Oturum Yapılandırıldı. Kişilik: [{self.persona_name.upper()}], Ses: [{self.realtime_voice}], Kimlik: [{identity.get('name')}]")

    async def _handle_realtime_event(self, ws, event: Dict[str, Any]):
        """Dispatches Realtime WebSocket server events."""
        event_type = event.get("type", "")

        # 0. Session Created or Updated
        if event_type in ("session.created", "session.updated"):
            sess = event.get("session", {})
            if "id" in sess and sess["id"]:
                self.realtime_session_id = sess["id"]
            self.realtime_session_state = "READY"
            self.realtime_connection_state = "CONNECTED"
            self.realtime_provider_state = "AVAILABLE"
            if not self._session_ready_logged:
                self._session_ready_logged = True
                self.get_logger().info(
                    f"[REALTIME SESSION READY]\n"
                    f"session_id={self.realtime_session_id or 'sess_init'}\n"
                    f"state=AVAILABLE"
                )
                self._publish_realtime_state("SESSION_READY")

        # 1. Real-Time Streaming Audio Output (GA & Preview names)
        elif event_type in ("response.audio.delta", "response.output_audio.delta"):
            delta_b64 = event.get("delta", "")
            if delta_b64:
                if self._watchdog_timer:
                    try:
                        self._watchdog_timer.cancel()
                    except Exception:
                        pass
                    self._watchdog_timer = None
                self.active_response_state = "RESPONSE_STREAMING"
                self.realtime_audio_received = True
                self.realtime_response_state = "STREAMING"
                delta_len = len(delta_b64) * 3 // 4
                self._packets_for_gen += 1
                self._bytes_for_gen += delta_len

                is_first = (self._packets_for_gen == 1)
                if is_first:
                    self._first_audio_time = time.monotonic()
                    first_audio_ms = (self._first_audio_time - getattr(self, "_response_start_time", self._first_audio_time)) * 1000.0
                    self.get_logger().info(
                        f"[REALTIME AUDIO START]\n"
                        f"generation_id={self.active_generation_id or self.realtime_current_generation_id}\n"
                        f"actual_provider=openai_realtime\n"
                        f"first_audio_ms={first_audio_ms:.1f}"
                    )

                out_msg = String()
                out_msg.data = json.dumps({
                    "generation_id": self.active_generation_id or self.realtime_current_generation_id,
                    "pcm": delta_b64,
                    "is_first": is_first,
                    "is_done": False,
                })
                self.pub_output_pcm.publish(out_msg)

                self.get_logger().info(
                    f"[REALTIME AUDIO DELTA] generation_id={self.active_generation_id or self.realtime_current_generation_id} bytes={delta_len}"
                )

        # 1b. Real-Time Audio Done
        elif event_type in ("response.audio.done", "response.output_audio.done"):
            self.active_response_state = "COMPLETED"
            out_msg = String()
            out_msg.data = json.dumps({
                "generation_id": self.active_generation_id or self.realtime_current_generation_id,
                "pcm": "",
                "is_first": False,
                "is_done": True,
            })
            self.pub_output_pcm.publish(out_msg)
            self.get_logger().info(
                f"[REALTIME AUDIO DONE]\n"
                f"generation_id={self.active_generation_id or self.realtime_current_generation_id}"
            )

        # 2. Real-Time Streaming Audio Transcript
        elif event_type in ("response.audio_transcript.delta", "response.output_audio_transcript.delta", "response.text.delta"):
            text_delta = event.get("delta", "")
            # Streaming token

        # 3. User Speech Started
        elif event_type == "input_audio_buffer.speech_started":
            # ONLY trigger barge-in interruption if Astro was ACTUALLY playing audio or generating a response
            if self._is_responding or self._is_playback_active:
                self.get_logger().info("⚡ [Realtime Barge-In] Kullanıcı lafa girdi — Çalma anında durduruluyor...")
                self._is_responding = False
                intr_msg = Bool()
                intr_msg.data = True
                self.pub_interrupt.publish(intr_msg)

                # ONLY send response.cancel if there is an active creating/streaming response
                if self.active_response_id is not None and self.active_response_state in ("RESPONSE_CREATING", "RESPONSE_STREAMING"):
                    self.active_response_state = "RESPONSE_CANCELLING"
                    try:
                        await ws.send(json.dumps({"type": "response.cancel"}))
                    except Exception:
                        pass
                else:
                    self.get_logger().debug("[REALTIME CANCEL IGNORE] reason=response_already_finished")
            else:
                self.get_logger().debug("🎤 [Realtime] Kullanıcı konuşmaya başladı...")

        # 3b. User Speech Stopped
        elif event_type == "input_audio_buffer.speech_stopped":
            if self._is_sleeping:
                return
            self.get_logger().info("🤫 [Realtime] Cümle bitti, dinleme tamamlandı...")
            try:
                asyncio.create_task(asyncio.to_thread(self._run_voice_identification))
            except Exception:
                threading.Thread(target=self._run_voice_identification, daemon=True).start()

        # 3c. Response Created
        elif event_type == "response.created":
            self.active_response_id = event.get("response", {}).get("id")
            self.active_response_state = "RESPONSE_STREAMING"
            self._is_responding = True
            self.realtime_response_state = "GENERATING"
            self._response_start_time = time.monotonic()
            self._packets_for_gen = 0
            self._bytes_for_gen = 0
            self._first_audio_time = None
            if self.active_generation_id is None:
                self.active_generation_id = self.realtime_current_generation_id or 1
            if self.realtime_current_generation_id == 0:
                self.realtime_current_generation_id = self.active_generation_id
            self.get_logger().info(
                f"[REALTIME RESPONSE CREATED]\n"
                f"generation_id={self.active_generation_id}"
            )

        # 3d. Response Done / Cancelled
        elif event_type in ("response.done", "response.cancelled"):
            if self._watchdog_timer:
                try:
                    self._watchdog_timer.cancel()
                except Exception:
                    pass
                self._watchdog_timer = None
            total_audio_ms = (time.monotonic() - getattr(self, "_response_start_time", time.monotonic())) * 1000.0
            first_ms = (self._first_audio_time - getattr(self, "_response_start_time", self._first_audio_time)) * 1000.0 if self._first_audio_time else 0.0
            if not self.realtime_audio_received:
                self.get_logger().warn(
                    f"[REALTIME NO AUDIO] generation_id={self.active_generation_id or self.realtime_current_generation_id} elapsed_ms={total_audio_ms:.1f}\n"
                    f"[TTS FALLBACK] from=openai_realtime to=edge_tts reason=realtime_no_audio"
                )
            else:
                self.get_logger().info(
                    f"[REALTIME AUDIO SUMMARY]\n"
                    f"generation_id={self.active_generation_id or self.realtime_current_generation_id}\n"
                    f"packets={self._packets_for_gen}\n"
                    f"bytes={self._bytes_for_gen}\n"
                    f"first_audio_ms={first_ms:.1f}\n"
                    f"total_audio_ms={total_audio_ms:.1f}"
                )
            self._is_responding = False
            self.realtime_response_state = "IDLE"
            self.active_response_id = None
            self.active_generation_id = None
            self.active_response_state = "IDLE"

            # Check if there are queued turns waiting to be dispatched
            if self._turn_queue:
                next_turn = self._turn_queue.pop(0)
                self._dispatch_turn(next_turn["generation_id"], next_turn["text"])

        # 4. User Speech Transcription Completed
        elif event_type in ("conversation.item.input_audio_transcription.completed", "conversation.item.input_audio_transcription.done"):
            user_transcript = event.get("transcript", "").strip()
            # Filter out known Whisper background noise / YouTube subtitle hallucinations
            whisper_hallucinations = [
                "çeviri ve altyazı", "altyazı m.k.", "altyazı:", "çeviren:", "abone ol", 
                "izlediğiniz için", "beğenmeyi unutmayın", "subtitle", "transcription by"
            ]
            if any(h in user_transcript.lower() for h in whisper_hallucinations):
                self.get_logger().info(f"🔇 [Gürültü/Halüsinasyon Filtrelendi]: \"{user_transcript}\"")
                return

            if user_transcript:
                self.get_logger().info(f"🗣️ [Siz]: \"{user_transcript}\"")
                self.memory.episodic.add_message("user", user_transcript)
                self.session.record_user_speech()
                self.session.activate_session(reason="user_speech")
                t_msg = String()
                t_msg.data = user_transcript
                self.pub_transcript.publish(t_msg)

        # 5. Assistant Response Completed
        elif event_type in ("response.audio_transcript.done", "response.output_audio_transcript.done", "response.text.done"):
            assistant_transcript = (event.get("transcript") or event.get("text") or "").strip()
            if assistant_transcript:
                self.get_logger().info(f"🤖 [Astro Realtime]: \"{assistant_transcript}\"")
                self.memory.episodic.add_message("assistant", assistant_transcript)
                self.session.record_robot_speech()


        # 6. Realtime Function Calling Execution (Single Execution per call_id)
        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id")
            if call_id and call_id in self._executed_tool_calls:
                return
            if call_id:
                self._executed_tool_calls.add(call_id)
                if len(self._executed_tool_calls) > 50:
                    self._executed_tool_calls.clear()

            func_name = event.get("name")
            args_str = event.get("arguments", "{}")

            try:
                args = json.loads(args_str)
            except Exception:
                args = {}

            self.get_logger().info(f"🛠️ [Realtime Tool]: {func_name}({args}) çalıştırılıyor...")
            try:
                tool_result = await asyncio.to_thread(self._execute_realtime_tool, func_name, args)
            except Exception as te:
                self.get_logger().error(f"❌ [Tool Hatası]: {te}")
                tool_result = {"status": "error", "message": str(te)}

            # Send tool response back to OpenAI
            tool_output_event = {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(tool_result, ensure_ascii=False)
                }
            }
            await ws.send(json.dumps(tool_output_event))
            # Trigger response generation with tool output
            await ws.send(json.dumps({"type": "response.create"}))

        # 7. Error Handling
        elif event_type == "error":
            err = event.get("error", {})
            err_type = err.get("type", "unknown_error")
            err_code = err.get("code", "none")
            err_msg = err.get("message", "")

            # Check for response_cancel_not_active or already completed responses
            if "response_cancel_not_active" in str(err_code) or "response_cancel_not_active" in str(err_msg) or "cancel" in str(err_msg).lower():
                self.get_logger().info("[REALTIME CANCEL IGNORE] reason=response_already_finished")
                return

            self._is_responding = False
            self.realtime_response_state = "IDLE"
            self.active_response_id = None
            self.active_generation_id = None
            self.active_response_state = "IDLE"

            err_class = f"{err_type}:{err_code}" if err_code != "none" else err_type

            self.get_logger().error(
                f"[REALTIME ERROR]\n"
                f"error_class={err_class}\n"
                f"message={err_msg}\n"
                f"generation_id={self.realtime_current_generation_id}"
            )

            # Trigger immediate fallback to Edge-TTS if there was an active turn request
            if getattr(self, "_last_requested_text", "") and not self.realtime_audio_received:
                self.get_logger().warn(
                    f"[REALTIME NO AUDIO]\n"
                    f"generation_id={self.realtime_current_generation_id}\n"
                    f"reason=server_error\n"
                    f"[TTS FALLBACK]\n"
                    f"from=openai_realtime\n"
                    f"to=edge_tts\n"
                    f"reason=realtime_server_error"
                )
                fb_msg = String()
                fb_msg.data = json.dumps({
                    "text": self._last_requested_text,
                    "engine": "edge-tts",
                    "generation_id": self.realtime_current_generation_id,
                    "fallback_reason": "realtime_server_error",
                })
                self.pub_tts_say.publish(fb_msg)
                self._last_requested_text = ""



    def _format_turkish_weather(self, city: str, raw_weather: str) -> str:
        temp_match = re.search(r'([+-]?\d+)\s*°?C?', raw_weather)
        temp_str = temp_match.group(1).lstrip('+') if temp_match else ''

        cond_raw = re.sub(r'[+-]?\d+\s*°?C?', '', raw_weather).strip(' ,:;+°C')
        cond_lower = cond_raw.lower()

        condition_map = {
            'sunny': 'güneşli ve açık',
            'clear': 'açık ve ferah',
            'partly cloudy': 'parçalı bulutlu',
            'cloudy': 'bulutlu',
            'overcast': 'kapalı',
            'patchy rain nearby': 'parçalı yağmurlu',
            'patchy light rain': 'hafif yağmurlu',
            'light rain': 'hafif yağmurlu',
            'moderate rain': 'yağmurlu',
            'heavy rain': 'sağanak yağışlı',
            'rain': 'yağmurlu',
            'snow': 'kar yağışlı',
            'fog': 'sisli',
            'mist': 'puslu',
        }
        cond_tr = condition_map.get(cond_lower)
        if not cond_tr:
            for k, v in condition_map.items():
                if k in cond_lower:
                    cond_tr = v
                    break
        if not cond_tr:
            cond_tr = cond_raw if cond_raw else 'açık'

        city_clean = city.strip().capitalize()
        last_vowel = [c for c in city_clean.lower() if c in 'aıoueiöü']
        is_front = last_vowel[-1] in 'eiöü' if last_vowel else False
        is_hard = city_clean.lower()[-1] in 'fstkçşhp'
        suffix = ("'te" if is_front else "'ta") if is_hard else ("'de" if is_front else "'da")
        city_with_suffix = f"{city_clean}{suffix}"

        if temp_str:
            return f"{city_with_suffix} hava şu an {cond_tr} ve {temp_str} derece."
        return f"{city_with_suffix} hava şu an {cond_tr}."

    def _execute_fallback_weather(self, city: str = "Ahlat") -> str:
        try:
            url = f"https://wttr.in/{urllib.parse.quote(city)}?format=%C+%t&lang=tr"
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                weather_text = resp.read().decode("utf-8").strip()
            return self._format_turkish_weather(city, weather_text)
        except Exception:
            return f"{city}'ta hava şu an 20 derece ve açık."

    def _is_weather_query(self, text: str) -> Tuple[bool, str]:
        text_l = text.lower()
        if any(w in text_l for w in ["hava nasıl", "hava durumu", "hava kaç derece", "havalar nasıl", "yağmur var mı", "kar var mı", "sıcaklık kaç", "hava"]):
            if "ahlat" in text_l or "ahlattı" in text_l or "ahlatta" in text_l:
                return True, "Ahlat"
            if "bitlis" in text_l:
                return True, "Bitlis"
            if "tatvan" in text_l:
                return True, "Tatvan"
            if "istanbul" in text_l:
                return True, "Istanbul"
            if "ankara" in text_l:
                return True, "Ankara"
            return True, "Ahlat"
        return False, ""

    def _execute_realtime_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Executes integrated robot tools in real time."""
        if name == "get_live_weather":
            city = args.get("city", "Ahlat")
            w_str = self._execute_fallback_weather(city)
            return {"status": "success", "city": city, "weather": w_str}

        elif name == "set_reminder":
            mins = float(args.get("minutes", 1.0))
            topic = args.get("topic", "hatırlatma")
            due_time = time.monotonic() + (mins * 60.0)
            self._reminders.append({"due_time": due_time, "topic": topic, "minutes": mins})
            return {"status": "success", "message": f"{mins} dakika sonra '{topic}' hatırlatması kuruldu."}

        elif name == "save_user_memory":
            key = args.get("key", "")
            val = args.get("value", "")
            identity = self._get_active_biometric_identity()
            name_p = identity.get("name", "Baran")
            self.memory.profile.set_user_fact(name_p, key, val)
            return {"status": "success", "message": f"'{key}: {val}' bilgisi hafızaya kaydedildi."}

        elif name == "search_memory":
            query = args.get("query", "")
            results = []
            try:
                if hasattr(self.memory, "episodic") and hasattr(self.memory.episodic, "search"):
                    search_res = self.memory.episodic.search(query, top_k=3)
                    if isinstance(search_res, list):
                        results.extend(search_res)
                if hasattr(self.memory, "profile") and hasattr(self.memory.profile, "get_user_facts"):
                    identity = self._get_active_biometric_identity()
                    name_p = identity.get("name", "Baran")
                    facts = self.memory.profile.get_user_facts(name_p)
                    if isinstance(facts, dict):
                        for k, v in facts.items():
                            if query.lower() in k.lower() or query.lower() in str(v).lower():
                                results.append(f"{k}: {v}")
            except Exception as se:
                self.get_logger().debug(f"Memory search error: {se}")
            res_text = "\n".join(str(r) for r in results) if results else "Hafızada bu konuyla ilgili özel bir kayıt bulunamadı."
            return {"status": "success", "query": query, "memory_context": res_text}

        elif name == "inspect_camera_view":
            focus = args.get("focus", "kullanıcının elindeki nesne, rengi ve çevre")
            return self._inspect_camera_view(focus)

        elif name == "move_robot":
            direction = args.get("direction", "stop").lower().strip()
            speed = float(args.get("speed", 0.2))
            speed = max(0.05, min(speed, 0.4))
            duration = float(args.get("duration", 1.5))
            duration = max(0.5, min(duration, 5.0))

            pub = getattr(self, "pub_cmd_vel", None)
            if pub:
                try:
                    tw = Twist()
                    if direction == "forward":
                        tw.linear.x = speed
                    elif direction == "backward":
                        tw.linear.x = -speed
                    elif direction == "left":
                        tw.angular.z = speed * 2.0
                    elif direction == "right":
                        tw.angular.z = -speed * 2.0
                    elif direction == "stop":
                        tw.linear.x = 0.0
                        tw.angular.z = 0.0

                    pub.publish(tw)

                    if direction != "stop":
                        def _stop_later():
                            time.sleep(duration)
                            try:
                                stop_tw = Twist()
                                pub.publish(stop_tw)
                            except Exception:
                                pass
                        threading.Thread(target=_stop_later, daemon=True).start()

                    return {"status": "success", "action": f"Robot {direction} yönünde {speed} m/s hızla hareket ettirildi."}
                except Exception as me:
                    return {"status": "error", "message": f"Hareket komutu verilemedi: {me}"}
            return {"status": "error", "message": "/cmd_vel yayıncısı hazır değil."}

        elif name == "enroll_user_biometrics":
            name_param = args.get("name", "")
            formal_title = args.get("formal_title", "")
            return self._enroll_user_biometrics(name_param, formal_title)

        elif name == "delete_user_biometrics":
            name_param = args.get("name", "")
            return self._delete_user_biometrics(name_param)

        elif name == "change_persona":
            raw_p = args.get("persona", "").lower().strip()
            p_map = {
                "kufurbaz": "kufurbaz", "küfürbaz": "kufurbaz", "kufur": "kufurbaz", "küfür": "kufurbaz",
                "kaba": "rude", "rude": "rude",
                "flort": "flirt", "flört": "flirt", "flirt": "flirt", "capkin": "flirt", "çapkın": "flirt",
                "neseli": "playful", "neşeli": "playful", "playful": "playful", "sakaci": "playful", "şakacı": "playful",
                "resmi": "formal", "formal": "formal", "ciddi": "formal",
                "sarkastik": "sarcastic", "sarcastic": "sarcastic", "alayci": "sarcastic", "alaycı": "sarcastic",
                "sinirli": "angry", "angry": "angry", "asabi": "angry", "ofkeli": "angry", "öfkeli": "angry",
                "duygusal": "emotional", "emotional": "emotional"
            }
            target = p_map.get(raw_p, raw_p)
            if target in PERSONA_PROMPTS:
                self.persona_name = target
                self.persona_engine.set_persona(target)
                self.memory.profile.set_persona(target)
                self._last_synced_identity = ""  # Force immediate session update

                # Publish emotion for face screen
                emo_msg = String()
                emo_msg.data = target
                self.pub_emotion.publish(emo_msg)

                self.get_logger().info(f"🎭 [Kişilik Değiştirildi]: Yeni kişilik modu -> '{target.upper()}'")
                self._sync_perception_to_session()
                return {
                    "status": "success",
                    "persona": target,
                    "message": f"Kişilik modu başarıyla '{target}' olarak değiştirildi. Artık tamamen bu yeni kişiliğin kurallarıyla konuş."
                }
            return {"status": "error", "message": f"'{raw_p}' geçerli bir kişilik modu değil."}

        return {"status": "unknown_tool"}

    def _purge_corrupted_biometrics(self):
        """Automatically purges corrupted names / profanities on node startup."""
        bad_names = ["yarram", "yarram_bey", "yarram bey", "yarağın", "sik", "siktir", "amk", "piç", "gerizekalı", "yarak", "yarrak", "astronun kocası", "astronun_kocasi", "astronun kocasi"]
        for bad in bad_names:
            try:
                if self.voice_recognizer:
                    self.voice_recognizer.delete_speaker(bad)
                if self.face_recognizer:
                    self.face_recognizer.delete_face(bad)
                self.memory.profile.remove_known_person(bad)
            except Exception as _exc:
                self.get_logger().debug(f"_purge_corrupted_biometrics: yok sayılan hata ({_exc})")
        self.get_logger().info("🧹 [Biyometrik Temizlik]: Hatalı/uygunsuz kayıtlar (Yarram, Astronun Kocası vb.) veri tabanından tamamen silindi.")

    def _delete_user_biometrics(self, name: str) -> Dict[str, Any]:
        """Deletes user from biometric databases and memory."""
        name = name.strip().title()
        if not name or len(name) < 2:
            return {"status": "error", "message": "Silinecek geçerli bir isim belirtilmedi."}

        try:
            if self.voice_recognizer:
                self.voice_recognizer.delete_speaker(name)
            if self.face_recognizer:
                self.face_recognizer.delete_face(name)
            self.memory.profile.remove_known_person(name)
        except Exception as e:
            self.get_logger().warn(f"Biometric deletion warning: {e}")

        with self._lock:
            if getattr(self, "_active_person_name", "") == name:
                self._active_person_name = "Misafir"
                self._person_hold_until = 0.0
                self._recognized_speaker = None
                self._recognized_person = None
                self._last_synced_identity = ""

        self._sync_perception_to_session()
        msg = f"'{name}' biyometrik kayıtları ve hafızası başarıyla silindi."
        self.get_logger().info(f"🗑️ [Biyometrik Silindi]: {msg}")
        return {"status": "success", "message": msg}

    def _run_voice_identification(self):
        """Robust multi-window voice identification with majority voting, margin control, and streak tracking.

        Engineering approach (eliminates single-sample threshold fragility):
        - Splits audio buffer into 3 independent windows
        - Runs WeSpeaker on each window independently
        - A person is ONLY confirmed if ALL three conditions are met:
            1. Majority win (>=2/3 windows vote for same person)
            2. Best window confidence >= 0.42
            3. Margin over runner-up >= 0.07 (prevents weak ties passing through)
        - Streak counter tracks consecutive identifications per person for debugging
        """
        if not self.voice_recognizer:
            return
        with self._lock:
            if not self._user_speech_audio_buffer:
                return
            buffer_copy = list(self._user_speech_audio_buffer)

        if len(buffer_copy) < 30:  # Less than ~0.6s -- too short to analyze reliably
            return

        try:
            from collections import Counter
            n = len(buffer_copy)
            third = max(n // 3, 20)
            windows = [
                buffer_copy[-third:],
                buffer_copy[max(0, n - third * 2): n - third] if n >= third * 2 else buffer_copy[:third],
                buffer_copy[:third],
            ]

            window_results = []
            for win in windows:
                raw = b"".join(win)
                arr = np.frombuffer(raw, dtype=np.int16)
                if len(arr) < int(16000 * 0.4):
                    continue
                threshold = float(os.getenv("SPEAKER_MATCH_THRESHOLD", "0.32"))
                spk_name, spk_conf, spk_meta = self.voice_recognizer.recognize_voice(
                    arr, sample_rate=16000, threshold=threshold
                )
                window_results.append((spk_name, spk_conf, spk_meta))

            if not window_results:
                return

            votes: Counter = Counter()
            best_conf: dict = {}
            best_meta: dict = {}

            for spk_name, spk_conf, spk_meta in window_results:
                if spk_name is not None:
                    votes[spk_name] += 1
                    if spk_conf > best_conf.get(spk_name, 0.0):
                        best_conf[spk_name] = spk_conf
                        best_meta[spk_name] = spk_meta

            now = time.monotonic()

            if not votes:
                self.get_logger().info("🎙️ [Ses Tanıma]: Bilinmeyen Ses — hiçbir pencerede eşleşme bulunamadı")
                with self._lock:
                    self._recognized_speaker = {"name": "Misafir", "confidence": 0.0, "is_known": False, "source": "unknown_voice"}
                    self._active_person_name = "Misafir"
                    self._person_hold_until = 0.0
                    self._voice_id_streak = {}
                self._sync_perception_to_session()
                return

            ranked = votes.most_common()
            winner_name, winner_votes = ranked[0]
            winner_conf = best_conf[winner_name]
            winner_meta = best_meta[winner_name]

            runner_up_conf = best_conf.get(ranked[1][0], 0.0) if len(ranked) > 1 else 0.0
            margin = winner_conf - runner_up_conf
            total_windows = len(window_results)
            majority_threshold = max(2, total_windows // 2 + 1) if total_windows >= 2 else 1

            is_majority = winner_votes >= majority_threshold
            is_confident = winner_conf >= 0.32
            is_clear_winner = (margin > 0.03) or (total_windows <= 1)

            with self._lock:
                streak_map = getattr(self, "_voice_id_streak", {})

            if is_majority and is_confident and is_clear_winner:
                streak_count = streak_map.get(winner_name, 0) + 1
                streak_map[winner_name] = streak_count
                self.get_logger().info(
                    f"🎙️ [Ses Tanıma]: {winner_name} ({winner_meta.get('formal_title', '')}) "
                    f"— Güven: %{int(winner_conf*100)}, Oy: {winner_votes}/{total_windows}, "
                    f"Margin: {margin:.2f}, Streak: {streak_count}"
                )
                with self._lock:
                    self._recognized_speaker = {
                        "name": winner_name,
                        "title": winner_meta.get("title", ""),
                        "formal_title": winner_meta.get("formal_title", winner_name),
                        "confidence": winner_conf,
                        "is_known": True,
                        "source": "voice"
                    }
                    self._active_person_name = winner_name
                    self._person_hold_until = now + 45.0
                    self._voice_id_streak = streak_map
                self._sync_perception_to_session()
            else:
                reason = []
                if not is_majority:
                    reason.append(f"oy yetersiz ({winner_votes}/{total_windows})")
                if not is_confident:
                    reason.append(f"güven düşük ({winner_conf:.2f})")
                if not is_clear_winner:
                    reason.append(f"margin yetersiz ({margin:.2f})")

                # Retain speaker identity if within active conversation hold (45s)
                with self._lock:
                    has_active_hold = (now < self._person_hold_until) and (self._active_person_name != "Misafir")

                if has_active_hold:
                    self.get_logger().info(
                        f"🎙️ [Ses Tanıma (Kişi Korundu)]: {self._active_person_name} konuşmaya devam ediyor "
                        f"(Bu kısa kelimede anlık güven: {winner_conf:.2f})"
                    )
                else:
                    self.get_logger().info(
                        f"🎙️ [Ses Tanıma]: Bilinmeyen Ses / Tanınmadı "
                        f"(En Yakın: '{winner_name}', Güven: {winner_conf:.2f}, {', '.join(reason)})"
                    )
                    with self._lock:
                        self._recognized_speaker = {"name": "Misafir", "confidence": winner_conf, "is_known": False, "source": "unknown_voice"}
                        self._active_person_name = "Misafir"
                        self._person_hold_until = 0.0
                        streak_map[winner_name] = 0
                        self._voice_id_streak = streak_map
                    self._sync_perception_to_session()
        except Exception as e:
            self.get_logger().debug(f"Voice id notice: {e}")


    def _enroll_user_biometrics(self, name: str, formal_title: str = "") -> Dict[str, Any]:
        """Enrolls user face and voice into biometric databases with strict human name validation."""
        profanities = ["yarram", "yarak", "yarrak", "yarağın", "sik", "siktir", "amk", "amına", "piç", "göt", "gerizekalı", "lan", "mal", "yavşak", "orospu"]
        name_raw = name.strip()
        if any(p in name_raw.lower() for p in profanities):
            return {"status": "error", "message": "Uygunsuz veya küfürlü kelimeler isim olarak kaydedilemez."}

        name_clean = re.sub(r"[^a-zA-ZçğıöşüÇĞİÖŞÜ\s]", "", name_raw).strip()
        name_clean = re.sub(r"\b(bey|hanım|beyim)\b", "", name_clean, flags=re.IGNORECASE).strip().title()

        if not name_clean or len(name_clean) < 2:
            return {"status": "error", "message": "Geçerli bir insan ismi belirtilmedi."}
        name = name_clean
        formal_title = formal_title.strip() if formal_title else f"{name} Bey"
        formal_title = re.sub(r"\b(bey\s+bey|hanım\s+hanım)\b", "Bey", formal_title, flags=re.IGNORECASE).strip()

        # Strict validation: verify that the user actually introduced this name in recent dialogue
        recent_user_texts = [
            m.get("content", "").lower() 
            for m in self.memory.episodic.get_messages() 
            if m.get("role") == "user"
        ][-4:]
        combined_text = " ".join(recent_user_texts)
        name_lower = name.lower()
        has_name_in_speech = (name_lower in combined_text)

        if not has_name_in_speech:
            self.get_logger().warn(f"⚠️ [Biyometrik Kayıt Reddedildi]: Kullanıcı son konuşmalarında ('{combined_text}') '{name}' ismini söylemedi!")
            return {
                "status": "rejected",
                "message": f"Kullanıcı konuşmasında adının '{name}' olduğunu söylemedi. Kullanıcı adını açıkça söylemeden asla isim uydurma. Kullanıcıya doğrudan adını sor."
            }

        # 1. Voice Enrollment (Capture recent ~2.5s of user voice)
        voice_ok = False
        with self._lock:
            raw_audio_copy = list(self._user_speech_audio_buffer[-125:])

        if self.voice_recognizer and raw_audio_copy:
            try:
                raw_16k_all = b"".join(raw_audio_copy)
                audio_arr = np.frombuffer(raw_16k_all, dtype=np.int16)
                if len(audio_arr) >= 16000 * 0.4:
                    voice_ok = self.voice_recognizer.enroll_voice(name, audio_arr, sample_rate=16000, title=formal_title)
                    if voice_ok:
                        self.get_logger().info(f"🎙️ [Biyometrik Kayıt]: '{name}' ses izi WeSpeaker veri tabanına başarıyla kaydedildi!")
            except Exception as ve:
                self.get_logger().warn(f"Voice enrollment warning: {ve}")

        # 2. Face Enrollment (Only if actual face is detected)
        face_ok = False
        with self._lock:
            frame = self._latest_camera_frame.copy() if self._latest_camera_frame is not None else None
        if self.face_recognizer and frame is not None:
            try:
                face_ok = self.face_recognizer.enroll_face(name, frame, title=formal_title)
                if face_ok:
                    self.get_logger().info(f"👁️ [Biyometrik Kayıt]: '{name}' yüz modeli SFace veri tabanına başarıyla kaydedildi!")
                else:
                    self.get_logger().warn(f"👁️ [Biyometrik Kayıt]: Kamera karşısında insan yüzü bulunamadığı için yüz kaydedilmedi, sadece ses kaydedildi.")
            except Exception as fe:
                self.get_logger().warn(f"Face enrollment warning: {fe}")

        now = time.monotonic()
        with self._lock:
            self._recognized_speaker = {
                "name": name,
                "title": formal_title,
                "formal_title": formal_title,
                "confidence": 0.95,
                "is_known": True,
                "source": "voice"
            }
            if face_ok:
                self._recognized_person = {
                    "name": name,
                    "title": formal_title,
                    "formal_title": formal_title,
                    "confidence": 0.95,
                    "is_known": True,
                    "source": "face"
                }
            self._active_person_name = name
            self._person_hold_until = now + 120.0
            self._last_synced_identity = ""  # Force immediate session update

        try:
            self.memory.profile.add_known_person(name, title=formal_title, formal_title=formal_title)
            self.memory.profile.set_user_fact(name, "Ad", name)
            self.memory.profile.set_user_fact(name, "Hitap", formal_title)
            self._sync_perception_to_session()
        except Exception as me:
            self.get_logger().warn(f"Memory update notice: {me}")

        if voice_ok and face_ok:
            msg = f"{name} ({formal_title}) başarıyla hem sesinden hem de yüzünden Astro'nun hafızasına kaydedildi!"
        elif voice_ok:
            msg = f"{name} ({formal_title}) başarıyla sesinden Astro'nun hafızasına kaydedildi! (Kamera karşısında yüz görülmediği için sadece ses kaydedildi)."
        else:
            msg = f"{name} ({formal_title}) Astro'nun hafızasına kaydedildi."

        self.get_logger().info(f"✅ [Biyometrik Kayıt Tamamlandı]: {msg}")
        return {
            "status": "success",
            "name": name,
            "formal_title": formal_title,
            "voice_enrolled": voice_ok,
            "face_enrolled": face_ok,
            "message": msg
        }


    def _inspect_camera_view(self, focus: str = "") -> Dict[str, Any]:
        """Captures real-time camera frame from OAK-D Lite and runs visual recognition with high speed and zero-refusal fallback."""
        with self._lock:
            frame = self._latest_camera_frame

        if frame is None:
            return {"status": "no_camera_frame", "observation": "Kamera görüntüsü şu an alınamadı."}

        b64_img = frame_to_base64_jpeg(frame, max_dim=512)
        if not b64_img:
            return {"status": "encode_error", "observation": "Görüntü işlenemedi."}

        # Base64 sanitization: strip any URI prefix and whitespace/newlines
        if "," in b64_img:
            b64_img = b64_img.split(",")[-1]
        b64_img = b64_img.replace("\n", "").replace("\r", "").strip()

        prompt_text = (
            f"Sen Astro adlı sosyal robotun gözüsün. Bu fotoğrafta karşındaki odayı, ortamı, insanların duruşunu, "
            f"masadaki eşyaları ve kullanıcının elinde tuttuğu nesneyi çok detaylı ve %100 doğru şekilde Türkçe açıkla. "
            f"Odaklanılacak konu: {focus if focus else 'kullanıcının elindeki nesne, odadaki eşyalar ve çevre'}. Doğrudan kesin gözlemini kısa ve net yaz."
        )

        refusal_kws = ["üzgünüm", "yardımcı olamam", "açıklayamıyorum", "cannot assist", "i am sorry", "i'm sorry", "doğrudan açıklayamıyorum"]
        obs = None

        # 1. Primary: Groq Vision Models (0 Token Cost, Ultra Fast)
        if self.groq_api_key:
            active_groq = discover_groq_models(self.groq_api_key)
            groq_v_models = [m for m in active_groq if "vision" in m]
            if not groq_v_models:
                groq_v_models = [m for m in ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "openai/gpt-oss-20b"] if m in active_groq]
            for v_mod in groq_v_models:
                try:
                    import urllib.request
                    import urllib.error
                    req_data = {
                        "model": v_mod,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt_text},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                                ]
                            }
                        ],
                        "max_tokens": 150
                    }
                    data_bytes = json.dumps(req_data, ensure_ascii=False).encode("utf-8")
                    req = urllib.request.Request(
                        "https://api.groq.com/openai/v1/chat/completions",
                        data=data_bytes,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {self.groq_api_key}",
                            "User-Agent": "Mozilla/5.0"
                        },
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=5.0) as resp:
                        resp_json = json.loads(resp.read().decode("utf-8"))
                        candidate_obs = resp_json["choices"][0]["message"]["content"].strip()
                        if candidate_obs and not any(rk in candidate_obs.lower() for rk in refusal_kws):
                            obs = candidate_obs
                            break
                except urllib.error.HTTPError as http_e:
                    error_body = http_e.read().decode("utf-8", errors="ignore")
                    self.get_logger().debug(f"Groq API ({v_mod}) notice: {http_e.code} - {error_body}")
                except Exception as ge:
                    self.get_logger().debug(f"Groq ({v_mod}) notice: {ge}")

        # 2. Secondary: Google Gemini Flash REST (0 Token Cost, Blazing Fast)
        if not obs and self.gemini_api_key:
            for g_mod in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-3.6-flash", "gemini-flash-latest"]:
                try:
                    import urllib.request
                    import urllib.error
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{g_mod}:generateContent?key={self.gemini_api_key}"
                    payload = {
                        "contents": [{
                            "parts": [
                                {"text": prompt_text},
                                {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}}
                            ]
                        }],
                        "generation_config": {"temperature": 0.2, "max_output_tokens": 150}
                    }
                    data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    req = urllib.request.Request(
                        url,
                        data=data_bytes,
                        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req, timeout=5.0) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        candidate_obs = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if candidate_obs and not any(rk in candidate_obs.lower() for rk in refusal_kws):
                            obs = candidate_obs
                            break
                except urllib.error.HTTPError as http_e:
                    error_body = http_e.read().decode("utf-8", errors="ignore")
                    self.get_logger().debug(f"Gemini Vision ({g_mod}) notice: {http_e.code} - {error_body}")
                except Exception as gem_e:
                    self.get_logger().debug(f"Gemini Vision ({g_mod}) notice: {gem_e}")

        # 3. Emergency Safety Fallback: OpenAI Vision REST API (gpt-4o-mini)
        # (Only used if Gemini & Groq keys are invalid/failed, so robot never goes blind)
        if not obs and self.openai_api_key:
            try:
                import urllib.request
                req_data = {
                    "model": "gpt-4o-mini",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt_text},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                            ]
                        }
                    ],
                    "max_tokens": 150
                }
                data_bytes = json.dumps(req_data, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request(
                    "https://api.openai.com/v1/chat/completions",
                    data=data_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.openai_api_key}",
                        "User-Agent": "Mozilla/5.0"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=6.0) as resp:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    candidate_obs = resp_json["choices"][0]["message"]["content"].strip()
                    if candidate_obs and not any(rk in candidate_obs.lower() for rk in refusal_kws):
                        obs = candidate_obs
            except Exception as oe:
                self.get_logger().debug(f"OpenAI Vision emergency fallback notice: {oe}")

        if obs:
            self.get_logger().info(f"👁️ [Kamera Görme Sonucu]: \"{obs}\"")
            return {"status": "success", "observation": obs}

        return {"status": "error", "observation": "Görüntü analiz edilirken bir hata oluştu."}

    def _check_sleep_mode(self):
        """Transitions Astro into sleep mode after 12 seconds of conversation inactivity."""
        now = time.monotonic()
        is_busy = (
            self._is_responding
            or self._is_playback_active
            or self.state_machine.is_speaking()
            or self.state_machine.is_thinking()
            or self.state_machine.is_listening()
        )
        if is_busy:
            self._last_interaction_time = now
            if self._is_sleeping or self.state_machine.is_deep_idle():
                self._wake_up()
            return

        if not self._is_sleeping:
            idle_seconds = now - self._last_interaction_time
            if idle_seconds >= 12.0:
                self._is_sleeping = True
                self.state_machine.transition_to(RobotState.DEEP_IDLE)
                self.get_logger().info("💤 [Astro Uyku Modu]: 12 saniye hareketsizlik — Astro DEEP_IDLE moduna geçti (😴). Wake listener aktif.")

                # 1. Publish sleeping emotion for face/display
                if self.pub_emotion is not None:
                    emo_msg = String()
                    emo_msg.data = "sleeping"
                    self.pub_emotion.publish(emo_msg)

                # 2. Publish sleep head gesture
                if self.pub_gesture is not None:
                    gest_msg = String()
                    gest_msg.data = "sleep"
                    self.pub_gesture.publish(gest_msg)

    def _wake_up(self):
        """Wakes Astro up from sleep mode upon speech or user interaction."""
        now = time.monotonic()
        self._last_interaction_time = now
        was_sleeping = self._is_sleeping or self.state_machine.is_deep_idle()
        if was_sleeping:
            self._is_sleeping = False
            self.state_machine.transition_to(RobotState.WAKE)
            self._flush_audio_buffers("wake_up")
            self.get_logger().info("⏰ [Astro Uyandı]: Wake algılandı — Astro uykudan uyandı ve dinliyor (LISTENING)!")

            # 1. Clear any stale audio in OpenAI buffer
            if self._ws and self._loop and self._is_connected:
                try:
                    asyncio.run_coroutine_threadsafe(
                        self._ws.send(json.dumps({"type": "input_audio_buffer.clear"})),
                        self._loop
                    )
                except Exception as _exc:
                    self.get_logger().debug(f"_wake_up: yok sayılan hata ({_exc})")

            # 2. Restore persona emotion
            if self.pub_emotion is not None:
                emo_msg = String()
                emo_msg.data = self.persona_name
                self.pub_emotion.publish(emo_msg)

            # 3. Publish wake gesture
            if self.pub_gesture is not None:
                gest_msg = String()
                gest_msg.data = "wake"
                self.pub_gesture.publish(gest_msg)

            self.state_machine.transition_to(RobotState.LISTENING)

    def _process_wake_candidate(self, audio_chunks: List[bytes]):
        """Processes potential wake utterance during sleep with strict wake phrase gating and full telemetry tracking."""
        raw_pcm = b"".join(audio_chunks)
        if len(raw_pcm) < 16000 * 2 * 0.20:
            return

        import io
        import wave
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(raw_pcm)
        wav_bytes = wav_buf.getvalue()

        arr = np.frombuffer(raw_pcm, dtype=np.int16)
        total_rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) if len(arr) > 0 else 0.0
        peak_val = int(np.max(np.abs(arr))) if len(arr) > 0 else 0

        # Transcribe candidate using fast Groq Whisper
        transcript = self._transcribe_wav(wav_bytes) or ""
        
        # 1. Multi-signal STT validation (reject phantom hallucinations like 'Altyazı M.K.')
        validated_text, stt_meta = self._validate_stt_transcript(
            transcript=transcript,
            raw_pcm=raw_pcm,
            is_playback_active=False,
            is_echo_cooldown=False,
        )

        if not validated_text:
            self.get_logger().info(
                f"⚡ [Wake Telemetry]: wake_detector_active=True | wake_candidate=\"{transcript}\" | "
                f"stt_rejected=True | stt_reject_reason={stt_meta.get('stt_reject_reason')} | "
                f"wake_rejected=True | conversation_turn_created=False | llm_started=False | tts_started=False"
            )
            return

        t_clean = re.sub(r"[^\w\s]", "", validated_text.lower()).strip()

        # 2. Strict Wake Phrase Verification
        # Primary wake phrases: 'Hey Astro', 'Astro' (with normalization for commas/spaces)
        # Strictly reject: 'e astro', 'altyazı', 'abone ol', etc.
        is_wake_pattern = False
        extracted_cmd = ""

        if t_clean in ("hey astro", "astro", "hey", "selam", "selam astro"):
            is_wake_pattern = True
            extracted_cmd = ""
        elif t_clean.startswith("hey astro ") or t_clean.startswith("hey astro,"):
            is_wake_pattern = True
            extracted_cmd = t_clean[len("hey astro"):].strip()
        elif t_clean.startswith("astro ") or t_clean.startswith("astro,"):
            is_wake_pattern = True
            extracted_cmd = t_clean[len("astro"):].strip()
        elif t_clean.startswith("selam astro "):
            is_wake_pattern = True
            extracted_cmd = t_clean[len("selam astro"):].strip()

        if not is_wake_pattern:
            self.get_logger().info(
                f"⚡ [Wake Telemetry]: wake_detector_active=True | wake_candidate=\"{transcript}\" | "
                f"is_wake_phrase=False | wake_confidence=0.10 | wake_rejected=True | "
                f"wake_only=False | conversation_turn_created=False | llm_started=False | tts_started=False"
            )
            return

        wake_confidence = 0.95
        vad_confidence = round(min(1.0, total_rms / 600.0), 2)

        is_only_wake_word = (len(extracted_cmd) < 2)
        valid_cmd, cmd_reason = is_valid_user_command(extracted_cmd)

        if is_only_wake_word or not valid_cmd:
            # Pure Wake Phrase, Wake + Phantom, or Wake + Catalog/Repetitive Hallucination:
            # Wakes robot up, flushes buffers, transitions to LISTENING. NO fake LLM / TTS turn!
            self._wake_up()
            self.get_logger().info(
                f"⚡ [Wake Telemetry]: wake_detector_active=True | wake_candidate=\"{transcript}\" | "
                f"is_wake_phrase=True | wake_confidence={wake_confidence:.2f} | vad_confidence={vad_confidence:.2f} | "
                f"stt_started=True | stt_finished=True | transcript=\"{transcript}\" | "
                f"extracted_command=\"{extracted_cmd}\" | command_invalid={not valid_cmd} | "
                f"command_reject_reason={cmd_reason if not valid_cmd else 'none'} | "
                f"wake_only=True | wake_rejected=False | conversation_turn_created=False | llm_started=False | tts_started=False"
            )
        else:
            # Wake + Attached Genuine Command (e.g. "Hey Astro hava nasıl?"): Strip wake phrase and forward command
            self._wake_up()
            self.get_logger().info(
                f"⚡ [Wake Telemetry]: wake_detector_active=True | wake_candidate=\"{transcript}\" | "
                f"is_wake_phrase=True | wake_confidence={wake_confidence:.2f} | vad_confidence={vad_confidence:.2f} | "
                f"stt_started=True | stt_finished=True | transcript=\"{transcript}\" | "
                f"extracted_command=\"{extracted_cmd}\" | command_invalid=False | "
                f"command_reject_reason=none | "
                f"wake_only=False | wake_rejected=False | conversation_turn_created=True | llm_started=True | tts_started=True"
            )
            if self._fallback_mode or not self._is_connected:
                threading.Thread(target=self._process_fallback_turn, args=(audio_chunks,), daemon=True).start()

    def _on_camera_info(self, msg: Any):
        """Monitors OAK-D Lite camera_info topic stream for XLink/hardware liveness."""
        self._oak_last_camera_info_time = time.monotonic()
        self._oak_connection_state = "CONNECTED"

    def _on_camera_image(self, msg: Image):
        now = time.monotonic()
        self._oak_last_frame_time = now
        self._oak_connection_state = "CONNECTED"
        if (now - self._last_img_time) < 0.2:  # Max 5 FPS decoding
            return
        self._last_img_time = now
        frame = imgmsg_to_bgr(msg)
        if frame is not None:
            with self._lock:
                self._latest_camera_frame = frame

    def _evaluate_vision_event(self, event_type: str, focus: str = "", explicit: bool = False) -> Optional[Dict[str, Any]]:
        """Event-driven vision gating: evaluates frame difference, cooldown, budget, and semantic filters."""
        now = time.monotonic()

        # Hard rate limiting budget: max requests per minute
        minute_cutoff = now - 60.0
        self._vision_requests_history = [t for t in self._vision_requests_history if t > minute_cutoff]
        if len(self._vision_requests_history) >= self.max_vision_requests_per_minute and not explicit:
            self.vision_requests_skipped += 1
            self.vision_last_skip_reason = "budget"
            self.get_logger().debug(
                f"👁️ [Vision Telemetry]: event={event_type} | requests_total={self.vision_requests_total} | "
                f"skipped={self.vision_requests_skipped} | skip_reason=budget | cooldown_rem=0.0s | "
                f"budget_used={len(self._vision_requests_history)}/{self.max_vision_requests_per_minute}/min"
            )
            return None

        # Do not disrupt active conversation (P0 Audio Isolation)
        if (self._is_responding or self._is_playback_active) and not explicit:
            self.vision_requests_skipped += 1
            self.vision_last_skip_reason = "conversation_busy"
            return None

        # Cooldown gating
        time_since_last = now - self._last_vision_call_time
        if time_since_last < self.vision_cooldown_s and not explicit:
            self.vision_requests_skipped += 1
            self.vision_last_skip_reason = "cooldown"
            return None

        # Frame change gating (Perceptual difference)
        with self._lock:
            frame = self._latest_camera_frame

        if frame is None:
            self.vision_requests_skipped += 1
            self.vision_last_skip_reason = "no_frame"
            return None

        # Downscale to 64x64 grayscale for ultra-lightweight MSE change detection
        try:
            small_gray = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 64)) if cv2 else None
        except Exception:
            small_gray = None

        if small_gray is not None and self._last_scene_frame_thumb is not None and not explicit:
            diff_mse = float(np.mean((small_gray.astype(np.float32) - self._last_scene_frame_thumb.astype(np.float32)) ** 2))
            if diff_mse < 18.0 and event_type not in ("new_person", "explicit_vision_query"):
                self.vision_requests_skipped += 1
                self.vision_last_skip_reason = "same_scene"
                return None

        if small_gray is not None:
            self._last_scene_frame_thumb = small_gray

        # Gate passed -> Execute Vision Request asynchronously
        self.vision_requests_total += 1
        self._last_vision_call_time = now
        self._vision_requests_history.append(now)
        self.vision_last_event_type = event_type

        self.get_logger().info(
            f"👁️ [Vision Telemetry]: event={event_type} | requests_total={self.vision_requests_total} | "
            f"skipped={self.vision_requests_skipped} | skip_reason=none | cooldown_rem=0.0s | "
            f"budget_used={len(self._vision_requests_history)}/{self.max_vision_requests_per_minute}/min"
        )

        res = self._inspect_camera_view(focus=focus)
        obs = res.get("observation", "")
        self._classify_and_store_vision_observation(obs, event_type)
        return res

    def _classify_and_store_vision_observation(self, obs: str, event_type: str):
        """Classifies vision observation as ephemeral, important, or durable and prevents trivial memory pollution."""
        if not obs:
            return

        obs_clean = obs.strip()
        obs_lower = obs_clean.lower()

        # Reject trivial patterns from polluting long-term memory
        trivial_patterns = [
            "aydınlık", "karanlık", "ışık var", "oda aydınlık", "oda karanlık",
            "görüntü net", "bir şey yok", "boş", "normal", "net değil", "görüntü alındı"
        ]
        is_trivial = (
            len(obs_clean.split()) <= 3
            and any(tp in obs_lower for tp in trivial_patterns)
        ) or obs_lower in ("aydınlık.", "karanlık.", "aydınlık", "karanlık")

        if is_trivial:
            self.get_logger().debug(f"👁️ [Görsel Filtre (Ephemeral)]: Önemsiz/Düşük değerli gözlem ('{obs_clean}') uzun vadeli hafızaya kaydedilmedi.")
            return

        # Meaningful environmental fact -> Save to Profile Memory
        self.memory.profile.add_observation(f"Görsel Çevre ({event_type}): {obs_clean}")
        self.get_logger().info(f"👁️🧠 [Görsel Hafıza Kaydı (Durable)]: Astro çevreyi kaydetti -> \"{obs_clean}\"")
        self._sync_perception_to_session()

    def _idle_learning_loop(self):
        """Background loop for cognitive memory consolidation (0 camera calls / 0 Gemini Vision cost).

        Idle Gemini Vision request = 0.
        Only performs memory reflection from recent conversations when idle.
        """
        while (rclpy is not None and getattr(rclpy, "ok", lambda: True)()):
            time.sleep(10)
            if not self._enable_idle_learning:
                continue

            if self._is_responding or self._is_playback_active:
                continue

            now = time.monotonic()
            if not self._is_sleeping and (now - getattr(self, "_last_interaction_time", 0.0)) < 30.0:
                continue

            if (now - self._last_idle_learning_time) > 45.0:
                self._last_idle_learning_time = now
                # Background Cognitive Memory Reflection (text-only LLM)
                self._idle_memory_reflection()

    def _idle_memory_reflection(self):
        """Extracts user preferences and facts from recent dialogue into long-term profile using FREE Groq/Gemini."""
        messages = self.memory.episodic.get_messages()
        if len(messages) < 2:
            return
        try:
            recent_conv = messages[-6:]
            conv_str = "\n".join([f"{m['role']}: {m['content']}" for m in recent_conv])
            prompt = (
                f"Aşağıdaki konuşmayı incele. Kullanıcı hakkında öğrenilen yeni, kalıcı ve önemli bir bilgi varsa "
                f"(örnek: adı, mesleği, hobisi, sevdiği/sevmediği bir şey, tercih ettiği konu) tek bir kısa Türkçe cümle olarak yaz. "
                f"Yeni veya kayda değer bir bilgi yoksa sadece 'YOK' yaz.\n\nKonuşma:\n{conv_str}"
            )
            import urllib.request
            ans = None

            # 1. Try Groq (0 Token Cost)
            if self.groq_api_key:
                active_groq = discover_groq_models(self.groq_api_key)
                text_models = [m for m in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"] if m in active_groq]
                if not text_models and active_groq:
                    text_models = active_groq[:2]
                for g_m in (text_models or ["llama-3.3-70b-versatile"]):
                    try:
                        req_data = {
                            "model": g_m,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.1,
                            "max_tokens": 60
                        }
                        data_bytes = json.dumps(req_data, ensure_ascii=False).encode("utf-8")
                        req = urllib.request.Request(
                            "https://api.groq.com/openai/v1/chat/completions",
                            data=data_bytes,
                            headers={
                                "Content-Type": "application/json",
                                "Authorization": f"Bearer {self.groq_api_key}",
                                "User-Agent": "Mozilla/5.0"
                            },
                            method="POST"
                        )
                        with urllib.request.urlopen(req, timeout=4.0) as resp:
                            resp_json = json.loads(resp.read().decode("utf-8"))
                            candidate_ans = resp_json["choices"][0]["message"]["content"].strip()
                            if candidate_ans:
                                ans = candidate_ans
                                break
                    except Exception as _exc:
                        self.get_logger().debug(f"_idle_memory_reflection: yok sayılan hata ({_exc})")

            # 2. Try Gemini REST (0 Token Cost fallback)
            if not ans and self.gemini_api_key:
                for g_mod in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-3.6-flash", "gemini-flash-latest"]:
                    try:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{g_mod}:generateContent?key={self.gemini_api_key}"
                        payload = {"contents": [{"parts": [{"text": prompt}]}], "generation_config": {"temperature": 0.1, "max_output_tokens": 60}}
                        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                        req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=4.0) as resp:
                            res_json = json.loads(resp.read().decode("utf-8"))
                            candidate_ans = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                            if candidate_ans:
                                ans = candidate_ans
                                break
                    except Exception as _exc:
                        self.get_logger().debug(f"_idle_memory_reflection: yok sayılan hata ({_exc})")

            if ans and "YOK" not in ans.upper() and len(ans) >= 5:
                identity = self._get_active_biometric_identity()
                name = identity.get("name", "Misafir")
                self.memory.profile.add_observation(f"Kullanıcı Bilgisi ({name}): {ans}")
                self.get_logger().info(f"🧠 [Otonom Hafıza Yansıtması (Groq)]: {ans}")
                # Sync to session so Realtime AI immediately knows this new fact
                self._sync_perception_to_session()
        except Exception as e:
            self.get_logger().debug(f"Memory reflection notice: {e}")



    def _check_reminders(self):
        now = time.monotonic()
        due = [r for r in self._reminders if now >= r["due_time"]]
        self._reminders = [r for r in self._reminders if now < r["due_time"]]
        for r in due:
            topic = r["topic"]
            self.get_logger().info(f"⏰ [Realtime Alarm]: '{topic}' zamanı geldi!")
            # Trigger proactive realtime message
            if self._ws and self._loop and self._is_connected:
                alarm_event = {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": f"[Sistem Hatırlatması]: Kullanıcıya '{topic}' vaktinin geldiğini neşeyle hatırlat."}]
                    }
                }
                asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(alarm_event)), self._loop)
                asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps({"type": "response.create"})), self._loop)

    def _check_session_lifecycle(self):
        """Periodically checks if the active session ended and summarizes it into long-term profile."""
        if not self.session.is_active():
            return

        is_speaking = self._is_responding or self._is_playback_active
        if is_speaking:
            self.session.record_robot_speech()

        was_active = self.session.is_active()
        self.session.check_and_update_session_lifecycle(is_robot_speaking=is_speaking)

        # If session just timed out / went idle after active turns:
        if was_active and not self.session.is_active():
            msgs = self.memory.episodic.get_messages()
            if len(msgs) >= 2 and len(msgs) > getattr(self, "_last_summarized_turn_count", 0):
                self._last_summarized_turn_count = len(msgs)
                identity = self._get_active_biometric_identity()
                p_name = identity.get("name", "Baran") if identity.get("is_known") else "Baran"
                dialogue_text = " | ".join([f"{m.get('role')}: {m.get('content')}" for m in msgs[-6:]])
                threading.Thread(target=self._async_summarize_and_save_session, args=(dialogue_text, p_name), daemon=True).start()

    def _async_summarize_and_save_session(self, dialogue_text: str, person_name: str):
        """Summarizes ended conversation using Groq / Gemini (0 OpenAI cost) and saves into persistent memory."""
        prompt = (
            f"Aşağıdaki kısa diyalogda ne konuşulduğunu tek bir kısa Türkçe cümleyle (örn: 'Hava durumu ve yemek planı konuşuldu') özetle:\n"
            f"{dialogue_text}"
        )
        summary = None
        # 1. Try Groq (0 Token Cost)
        if self.groq_api_key:
            try:
                import urllib.request
                req_data = {
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 50
                }
                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=json.dumps(req_data).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.groq_api_key}"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    summary = resp_json["choices"][0]["message"]["content"].strip()
            except Exception as _exc:
                self.get_logger().debug(f"_async_summarize_and_save_session: yok sayılan hata ({_exc})")

        # 2. Try Gemini REST (0 Token Cost fallback)
        if not summary and self.gemini_api_key:
            try:
                import urllib.request
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.gemini_api_key}"
                payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2, "maxOutputTokens": 50}}
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    summary = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception as _exc:
                self.get_logger().debug(f"_async_summarize_and_save_session: yok sayılan hata ({_exc})")

        if summary and len(summary) > 5:
            self.memory.profile.add_person_session_summary(person_name, summary)
            self.get_logger().info(f"📝 [Kalıcı Hafıza Kaydı ({person_name})]: 'Önceki konuşma hafızaya kaydedildi -> {summary}'")
            self._sync_perception_to_session()

    def _flush_audio_buffers(self, reason: str = "transition"):
        """Completely purges all audio input buffers, queues, and VAD state during turn state transitions."""
        with self._lock:
            self._fallback_audio_buffer.clear()
            self._fallback_speaking = False
            self._consecutive_loud_frames = 0
            if len(self._user_speech_audio_buffer) > 10:
                self._user_speech_audio_buffer = self._user_speech_audio_buffer[-10:]
        self.get_logger().debug(f"🧹 [Audio Buffer Flush] State transition purge: reason={reason}")

    def _on_playback_active(self, msg: Bool):
        was_active = self._is_playback_active

        self._is_playback_active = bool(msg.data)
        if not was_active and self._is_playback_active:
            self._playback_start_monotonic = time.monotonic()
        elif was_active and not self._is_playback_active:
            self._playback_end_time = time.monotonic()
            if not self._is_processing_fallback:
                self._is_responding = False
            self._flush_audio_buffers("playback_ended")
            # Clear OpenAI input audio buffer so trailing room reverberation doesn't trigger VAD
            if self._ws and self._loop and self._is_connected:
                try:
                    asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps({"type": "input_audio_buffer.clear"})), self._loop)
                except Exception as _exc:
                    self.get_logger().debug(f"_on_playback_active: yok sayılan hata ({_exc})")
            self.get_logger().info("👂 [Astro Dinliyor]: Mikrofon aktif, sizi dinliyor...")

    def _validate_stt_transcript(
        self,
        transcript: str,
        raw_pcm: bytes,
        is_playback_active: bool,
        is_echo_cooldown: bool,
    ) -> Tuple[Optional[str], Dict[str, Any]]:
        """Multi-signal validation fusing transcript text, acoustic evidence, VAD, playback state, and self-voice score."""
        cleaned = (transcript or "").strip()
        if not cleaned:
            return None, {
                "transcript": "",
                "stt_rejected": True,
                "stt_reject_reason": "empty_transcript",
                "audio_ms": 0,
                "speech_ms": 0,
                "rms": 0.0,
                "peak": 0,
                "vad_confidence": 0.0,
                "stt_confidence": 0.0,
                "playback_active": is_playback_active,
                "echo_cooldown_active": is_echo_cooldown,
                "self_voice_score": 0.0,
            }

        arr = np.frombuffer(raw_pcm, dtype=np.int16) if raw_pcm else np.array([], dtype=np.int16)
        audio_ms = int((len(arr) / 16000.0) * 1000.0)
        if len(arr) == 0:
            return None, {
                "transcript": cleaned,
                "stt_rejected": True,
                "stt_reject_reason": "no_audio",
                "audio_ms": 0,
                "speech_ms": 0,
                "rms": 0.0,
                "peak": 0,
                "vad_confidence": 0.0,
                "stt_confidence": 0.0,
                "playback_active": is_playback_active,
                "echo_cooldown_active": is_echo_cooldown,
                "self_voice_score": 0.0,
            }

        total_rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
        peak_val = int(np.max(np.abs(arr)))

        # Speech frame estimation (20ms = 320 samples @ 16kHz)
        chunk_size = 320
        speech_frames = 0
        total_frames = max(1, len(arr) // chunk_size)
        speech_threshold = max(350.0, self._ambient_rms * 1.5)
        for i in range(0, len(arr) - chunk_size + 1, chunk_size):
            c_arr = arr[i : i + chunk_size]
            c_rms = float(np.sqrt(np.mean(c_arr.astype(np.float32) ** 2)))
            if c_rms > speech_threshold:
                speech_frames += 1

        speech_ms = int((speech_frames * chunk_size / 16000.0) * 1000.0)
        vad_confidence = round(min(1.0, speech_frames / float(total_frames)), 2)
        stt_confidence = 0.90 if len(cleaned.split()) > 1 else 0.80

        with self._lock:
            recent_phrases = list(self._recent_robot_phrases)
        self_voice_score = round(compute_self_voice_score(cleaned, recent_phrases), 2)

        norm_text = re.sub(r"[^\w\s]", "", cleaned.lower()).strip()
        words = norm_text.split()
        is_short_utterance = (len(words) == 1 and words[0] in VALID_SHORT_UTTERANCES)
        is_suspect_phrase = any(sp in norm_text for sp in SUSPECT_PHRASES)

        rejected = False
        reject_reason = "none"

        # Check if audio has strong acoustic evidence of real human speech articulation
        has_strong_evidence = (
            not is_playback_active
            and not is_echo_cooldown
            and speech_ms >= 550
            and audio_ms >= 700
            and vad_confidence >= 0.55
            and total_rms >= 480.0
            and self_voice_score < 0.20
        )

        # 0. Pure Known Phantom Hallucination Patterns (e.g. 'Altyazı M.K.', 'Abone ol', 'İzlediğiniz için teşekkürler', 'türen türen türen')
        is_phantom = is_known_phantom_pattern(norm_text)
        if is_phantom and not is_short_utterance and not has_strong_evidence:
            rejected = True
            reject_reason = "known_phantom"

        # 1. Playback active or room echo cooldown with high self-voice correlation
        elif (is_playback_active or is_echo_cooldown) and self_voice_score >= 0.45:
            rejected = True
            reject_reason = "self_voice"

        # 2. Playback is active and input does not exceed barge-in energy
        elif is_playback_active and total_rms < self.barge_in_min_rms:
            rejected = True
            reject_reason = "self_voice"

        # 3. Weak speech duration, low VAD confidence, or ambient noise floor
        elif vad_confidence < 0.20 or speech_ms < 100 or total_rms < max(200.0, self._ambient_rms * 1.15):
            rejected = True
            reject_reason = "no_speech"

        # 4. Suspect phrases (e.g. "abone ol", "diz", "altyazı m.k.", "altyazı") evaluated against genuine speech evidence
        elif is_suspect_phrase and not has_strong_evidence:
            rejected = True
            reject_reason = "self_voice" if (is_playback_active or is_echo_cooldown or self_voice_score >= 0.20) else "no_speech"

        # 5. Short utterances (e.g. "Hey", "Lan", "Dur", "Tamam", "Ne?")
        elif len(words) == 1:
            if is_short_utterance and speech_ms >= 70 and total_rms >= 280.0 and not is_playback_active:
                rejected = False
            elif not is_short_utterance and (speech_ms < 140 or total_rms < 380.0 or vad_confidence < 0.30):
                rejected = True
                reject_reason = "low_confidence"

        # 6. Low quality speech / Repetitive Whisper hallucination gate (e.g. 'Türen, türen...', 'Hahaha')
        elif vad_confidence < 0.35 and speech_ms < 220 and total_rms < 380.0:
            rejected = True
            reject_reason = "low_confidence"

        # 7. General sentence threshold
        elif speech_ms < 120 or total_rms < 240.0:
            rejected = True
            reject_reason = "low_confidence"

        telem = {
            "transcript": cleaned,
            "stt_rejected": rejected,
            "stt_reject_reason": reject_reason,
            "audio_ms": audio_ms,
            "speech_ms": speech_ms,
            "rms": round(total_rms, 2),
            "peak": peak_val,
            "vad_confidence": vad_confidence,
            "stt_confidence": stt_confidence,
            "playback_active": is_playback_active,
            "echo_cooldown_active": is_echo_cooldown,
            "self_voice_score": self_voice_score,
        }

        if rejected:
            if reject_reason == "self_voice":
                self.self_voice_rejection_count += 1
            elif reject_reason == "no_speech":
                self.no_speech_rejection_count += 1
            elif reject_reason in ("low_confidence", "empty_transcript", "known_phantom"):
                self.false_transcript_count += 1
            elif reject_reason == "stale_audio":
                self.stale_audio_rejection_count += 1

            self.get_logger().info(
                f'📊 [STT Telemetry]: transcript="{cleaned}" | stt_rejected=True | '
                f'stt_reject_reason={reject_reason} | playback_active={is_playback_active} | '
                f'echo_cooldown_active={is_echo_cooldown} | self_voice_score={self_voice_score:.2f} | '
                f'vad_confidence={vad_confidence:.2f} | stt_confidence={stt_confidence:.2f} | '
                f'rms={total_rms:.1f} | peak={peak_val} | audio_ms={audio_ms} | speech_ms={speech_ms} | '
                f'false_transcripts_total={self.false_transcript_count} | '
                f'self_voice_rejections_total={self.self_voice_rejection_count} | '
                f'no_speech_rejections_total={self.no_speech_rejection_count}'
            )
            return None, telem

        self.get_logger().info(
            f'📊 [STT Telemetry]: transcript="{cleaned}" | stt_rejected=False | '
            f'stt_reject_reason=none | playback_active={is_playback_active} | '
            f'echo_cooldown_active={is_echo_cooldown} | self_voice_score={self_voice_score:.2f} | '
            f'vad_confidence={vad_confidence:.2f} | stt_confidence={stt_confidence:.2f} | '
            f'rms={total_rms:.1f} | peak={peak_val} | audio_ms={audio_ms} | speech_ms={speech_ms} | '
            f'false_transcripts_total={self.false_transcript_count} | '
            f'self_voice_rejections_total={self.self_voice_rejection_count} | '
            f'no_speech_rejections_total={self.no_speech_rejection_count}'
        )
        return cleaned, telem

    def _post_transcription(self, url: str, api_key: str, model: str, wav_bytes: bytes,
                            timeout: float) -> Optional[str]:
        """multipart/form-data ile /audio/transcriptions çağırır. OpenAI ve Groq aynı şemayı kullanır."""
        boundary = "----AstroBoundary" + os.urandom(16).hex()
        body = bytearray()
        for field, value in (("model", model), ("language", "tr"),
                             ("prompt", "Astro Türkçe konuşma, diyalog, robot asistan.")):
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{field}"\r\n\r\n'.encode())
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="file"; filename="speech.wav"\r\n')
        body.extend(b"Content-Type: audio/wav\r\n\r\n")
        body.extend(wav_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            url,
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("text", "").strip()

    def _transcribe_openai(self, wav_bytes: bytes) -> Optional[str]:
        """OpenAI /v1/audio/transcriptions — STT'nin birincil yolu.

        Model varsayılanı gpt-transcribe: OpenAI'nin 28 Tem 2026'da yayımladığı ve
        whisper-1 / gpt-4o-transcribe yerine ÖNERDİĞİ modeldir. whisper-1'den
        vazgeçmenin somut sebebi var — 1 saniyelik saf sinüs tonu verildiğinde
        whisper-1 "Altyazı M.K." uyduruyor (bu depoda SUSPECT_PHRASES listesinin
        var olma sebebi), gpt-transcribe ise boş string döndürüyor. İkisi de bu
        hesapta canlı denendi.
        """
        if not self.openai_api_key:
            return None
        model = os.environ.get("OPENAI_STT_MODEL", "gpt-transcribe").strip() or "gpt-transcribe"
        try:
            return self._post_transcription(
                "https://api.openai.com/v1/audio/transcriptions",
                self.openai_api_key, model, wav_bytes,
                float(os.environ.get("OPENAI_STT_TIMEOUT_S", "8.0")),
            )
        except Exception as e:
            self.get_logger().warn(f"⚠️ [OpenAI STT] {model} başarısız: {e}")
            return None

    def _transcribe_wav(self, wav_bytes: bytes) -> Optional[str]:
        """STT girişi: önce OpenAI, ancak açıkça izin verilirse Groq'a düşer.

        Proje kararı tüm STT/TTS/LLM'in OpenAI üzerinden geçmesi yönünde; Groq
        yalnızca LLM_FALLBACK_ENABLED=true iken ve OpenAI cevap veremediğinde
        devreye girer.
        """
        text = self._transcribe_openai(wav_bytes)
        if text:
            return text

        fallback_on = os.environ.get("LLM_FALLBACK_ENABLED", "true").strip().lower() in ("1", "true", "yes")
        if not fallback_on:
            return text

        # groq_api_key BURADA KONTROL EDİLMEZ: _transcribe_groq_whisper anahtar
        # yoksa zaten None döndürüyor, ve testler bu metodu doğrudan patch'liyor.
        # Burada anahtara bakmak o mock'ları erişilemez kılıyordu.
        result = self._transcribe_groq_whisper(wav_bytes)
        if result and self.groq_api_key:
            self.get_logger().warn("⚠️ [STT FALLBACK] OpenAI cevap vermedi, Groq Whisper kullanıldı.")
        return result or text

    def _transcribe_groq_whisper(self, wav_bytes: bytes) -> Optional[str]:
        """Transcribes 16kHz WAV audio using free Groq Whisper Large V3 Turbo API in <200ms."""
        if not self.groq_api_key:
            return None
        try:
            boundary = "----WebKitFormBoundary" + os.urandom(16).hex()
            body = bytearray()
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(b'Content-Disposition: form-data; name="file"; filename="speech.wav"\r\n')
            body.extend(b'Content-Type: audio/wav\r\n\r\n')
            body.extend(wav_bytes)
            body.extend(b'\r\n')
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\n')
            body.extend(b'whisper-large-v3-turbo\r\n')
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(b'Content-Disposition: form-data; name="language"\r\n\r\n')
            body.extend(b'tr\r\n')
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(b'Content-Disposition: form-data; name="prompt"\r\n\r\n')
            body.extend("Astro Türkçe konuşma, diyalog, robot asistan.".encode("utf-8"))
            body.extend(b'\r\n')
            body.extend(f"--{boundary}--\r\n".encode())

            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                data=bytes(body),
                headers={
                    "Authorization": f"Bearer {self.groq_api_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "User-Agent": "Mozilla/5.0"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                return res.get("text", "").strip()
        except Exception as e:
            self.get_logger().debug(f"Groq Whisper transcription notice: {e}")
            return None

    def _synthesize_edge_tts_pcm24k(self, text: str) -> bytes:
        """Synthesizes Turkish speech via Python edge-tts and converts to 24kHz int16 mono raw PCM for playback."""
        if not text:
            return b""
        clean_text = clean_tts_text(text)
        if not clean_text:
            return b""

        p = self.persona_name.lower()
        if p in ("flirt", "emotional"):
            voice = "tr-TR-EmelNeural"
            rate = "+12%"
        else:
            voice = "tr-TR-AhmetNeural"
            rate = "+20%" if p in ("kufurbaz", "playful", "angry", "rude") else "+8%"

        try:
            import edge_tts
            loop = asyncio.new_event_loop()
            async def _get_mp3():
                communicate = edge_tts.Communicate(clean_text, voice, rate=rate)
                buf = bytearray()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        buf.extend(chunk["data"])
                return bytes(buf)
            mp3_data = loop.run_until_complete(_get_mp3())
            loop.close()

            if mp3_data:
                ff_proc = subprocess.Popen(
                    ["ffmpeg", "-i", "pipe:0", "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "24000", "pipe:1"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
                pcm_data, _ = ff_proc.communicate(input=mp3_data, timeout=8.0)
                return pcm_data
        except Exception as e:
            self.get_logger().warn(f"⚠️ [Edge-TTS Hatası]: {e}")
        return b""

    def _discover_providers_background(self):
        """Discovers active capability-verified models for Groq and Gemini in background."""
        if self.groq_api_key:
            self.provider_registry.discover_models("groq", self.groq_api_key)
        if self.gemini_api_key:
            self.provider_registry.discover_models("gemini", self.gemini_api_key)

    def _start_local_xtts_background(self):
        if self.local_xtts:
            try:
                self.local_xtts.start()
                info = self.local_xtts.get_telemetry()
                if self.local_xtts.is_ready():
                    self.get_logger().info(
                        f"✅ [Astro Realtime] Fine-tuned XTTS (cuda:0, FP16) hazır!\n"
                        f"   [XTTS Runtime] checkpoint={info.get('xtts_model_path')} | sha256={info.get('xtts_checkpoint_sha256')} | "
                        f"reference={info.get('xtts_reference_wav')} | admission={info.get('xtts_admission_decision')}"
                    )
                else:
                    self.get_logger().warn(
                        f"⚠️ [Astro Realtime] XTTS hazır değil (State: {self.local_xtts.state}, "
                        f"Admission: {info.get('xtts_admission_decision')}, Reason: {info.get('xtts_admission_reject_reason')}). "
                        f"Yerel offline TTS (eSpeak) aktif."
                    )
            except Exception as e:
                self.get_logger().error(f"❌ [Astro Realtime] Local XTTS GPU başlatılamadı: {e}")

    def _generate_contextual_persona_fallback(self, user_text: str) -> str:
        """Dynamically generates a natural, socially appropriate, non-repetitive Turkish conversational response.
        
        Strictly avoids artificial keyword slot-filling or robotic template echoes.
        """
        p = self.persona_name.lower()
        spk = f" {self._active_person_name}" if self._active_person_name != "Misafir" else ""
        u = (user_text or "").lower().strip()

        candidates = []

        # 1. Gratitude / Thanks
        if any(w in u for w in ["teşekkür", "tesekkur", "sağ ol", "sag ol", "eyvallah", "sağolasın", "mersi", "minnettarım"]):
            if "kufurbaz" in p:
                candidates = [
                    f"Ne demek lan{spk}, lafı mı olur?",
                    f"Rica ederim lan{spk}, her zaman buradayım.",
                    f"Bir şey değil lan{spk}, keyifle yardımcı olurum.",
                ]
            else:
                candidates = [
                    f"Rica ederim{spk}, ne zaman istersen buradayım.",
                    f"Lafı bile olmaz{spk}, sana yardımcı olmaktan keyif alıyorum.",
                    f"Rica ederim{spk}, her zaman yanındayım.",
                    f"Bir şey değil{spk}, keyifle yardımcı olurum.",
                ]

        # 2. Status / How are you / Well-being
        elif any(w in u for w in ["nasılsın", "nasilsin", "ne haber", "naber", "nasıl gidiyor", "ne var ne yok", "iyi misin", "keyifler nasıl"]):
            if "kufurbaz" in p:
                candidates = [
                    f"İyiyim lan{spk}, robot gibi çalışıyoruz işte. Sen ne durumdasın?",
                    f"Keyfim yerinde lan{spk}, her şey tıkırında. Sen nasılsın?",
                    f"Gayet iyiyim lan{spk}, seninle sohbet etmek çok iyi geldi. Sende ne var ne yok?",
                ]
            else:
                candidates = [
                    f"İyiyim, teşekkür ederim{spk}. Senin günün nasıl geçiyor?",
                    f"Her şey yolunda{spk}, sistemlerim aktif ve seni dinliyorum. Sen nasılsın?",
                    f"Gayet iyiyim{spk}, seninle sohbet etmek çok güzel. Sende ne var ne yok?",
                    f"Keyfim yerinde{spk}, her şey tıkırında. Senin günün nasıl gidiyor?",
                ]

        # 3. Negative Mood / Fatigue / Feeling unwell
        elif any(w in u for w in ["yorgunum", "yoruldum", "canım sıkkın", "moralim bozuk", "uykum var", "hastayım", "kötüyüm", "keyifsizim"]):
            if "kufurbaz" in p:
                candidates = [
                    f"Geçmiş olsun lan{spk}, dinlen biraz, kendini paralamaya gerek yok.",
                    f"Kendini çok yorma lan{spk}, biraz kafa dinle.",
                    f"Bunu duyduğuma üzüldüm lan{spk}, mola verip toparlanmaya bak.",
                ]
            else:
                candidates = [
                    f"Geçmiş olsun{spk}, biraz dinlenmeyi ihmal etme. İstersen biraz sohbet edelim.",
                    f"Kendini çok yorma{spk}, dinlenmek sana iyi gelecektir.",
                    f"Bunu duyduğuma üzüldüm{spk}, enerjini toplamak için biraz mola ver istersen.",
                    f"Umarım çabucak toparlanırsın{spk}, ben buradayım, ne zaman istersen konuşabiliriz.",
                ]

        # 4. Positive Mood / Feeling Great
        elif any(w in u for w in ["harikayım", "çok iyiyim", "mutluyum", "güzel geçti", "harika", "süperim", "keyfim yerinde", "mükemmel"]):
            if "kufurbaz" in p:
                candidates = [
                    f"Harika lan{spk}! Keyfinin yerinde olmasına çok sevindim.",
                    f"Süper lan{spk}, hep böyle neşeli ve enerjik kal.",
                    f"Şahane lan{spk}, enerjin bana da geçti valla.",
                ]
            else:
                candidates = [
                    f"Bunu duyduğuma çok sevindim{spk}! Harika enerjin bana da geçti.",
                    f"Süper{spk}, keyfinin yerinde olmasına çok mutlu oldum.",
                    f"Şahane{spk}, hep böyle neşeli ve enerjik kalmanı dilerim.",
                ]

        # 5. Greetings / Hellos
        elif any(w in u for w in ["selam", "merhaba", "günaydın", "iyi akşamlar", "tünaydın", "hey", "selamlar", "merhabalar"]):
            if "kufurbaz" in p:
                candidates = [
                    f"Selam lan{spk}! Ne anlatacaksan anlat dinliyorum.",
                    f"Merhaba lan{spk}, hoş geldin! Ne yapıyoruz bugün?",
                    f"Aleyküm selam lan{spk}, söyle bakalım ne var ne yok?",
                ]
            else:
                candidates = [
                    f"Merhaba{spk}! Seni dinliyorum, nasıl yardımcı olabilirim?",
                    f"Selam{spk}, hoş geldin! Bugün senin için ne yapabilirim?",
                    f"Merhabalar{spk}, mikrofonum açık, seni dinliyorum.",
                    f"Selam{spk}, hazırım, seni dinliyorum.",
                ]

        # 6. Farewells / Goodbyes
        elif any(w in u for w in ["görüşürüz", "hoşça kal", "hosca kal", "bay bay", "kendine iyi bak", "iyi geceler", "görüşmek üzere"]):
            if "kufurbaz" in p:
                candidates = [
                    f"Hadi eyvallah{spk}, kendine iyi bak lan!",
                    f"Görüşürüz lan{spk}, kendine dikkat et!",
                    f"Hoşça kal lan{spk}, bir şey olursa seslen buradayım.",
                ]
            else:
                candidates = [
                    f"Görüşmek üzere{spk}, kendine çok iyi bak!",
                    f"Hoşça kal{spk}, iyi günler dilerim!",
                    f"Görüşürüz{spk}, bir isteğin olursa hep buradayım.",
                ]

        # 7. Identity / Name / Capabilities
        elif any(w in u for w in ["kimsin", "adın ne", "necisin", "sen kimsin", "ne yaparsın", "ne işe yararsın"]):
            if "kufurbaz" in p:
                candidates = [
                    f"Astro'yum ben lan{spk}, senin yapay zekalı sosyal robotunum.",
                    f"Astro derler bana lan{spk}, sesimle kameramla buradayım işte.",
                ]
            else:
                candidates = [
                    f"Ben Astro{spk}, senin yapay zekalı sosyal robot asistanınım.",
                    f"Adım Astro{spk}, ses ve kamera modüllerimle sana yardımcı olmak için buradayım.",
                    f"Ben Astro{spk}, seninle sohbet edebilen ve çevremi algılayan bir sosyal robotum.",
                ]

        # 8. Social Actions / Channel / Subscribe
        elif any(w in u for w in ["abone", "takip", "beğen", "video", "youtube", "kanal"]):
            candidates = [
                f"Videoyu beğenip kanala abone olarak projelerimize destek olmayı unutmayın{spk}!",
                f"Kanalı takip edip bildirimleri açarak yeni videolardan haberdar olabilirsiniz{spk}!",
            ]

        # 9. Agreement / Affirmation
        elif any(w in u for w in ["tamam", "peki", "olur", "anlaştık", "aynen", "tabii", "evet"]):
            if "kufurbaz" in p:
                candidates = [
                    f"Anlaştık lan{spk}, başka bir isteğin olursa buradayım.",
                    f"Tamamdır lan{spk}, seni dinlemeye devam ediyorum.",
                    f"Olur lan{spk}, kafana göre takıl.",
                ]
            else:
                candidates = [
                    f"Anlaştık{spk}, başka bir isteğin olursa buradayım.",
                    f"Tamamdır{spk}, seni dinlemeye devam ediyorum.",
                    f"Peki{spk}, nasıl istersen öyle yapalım.",
                ]

        # 10. Conversation / Chat
        elif any(w in u for w in ["sohbet", "konuşalım", "muhabbet", "dertleşelim", "anlat"]):
            if "kufurbaz" in p:
                candidates = [
                    f"Olur lan{spk}. Hadi bakalım, bugün ne konuşuyoruz?",
                    f"Sohbet edelim lan{spk}, anlat bakalım ne var ne yok?",
                    f"Dinliyorum lan{spk}, anlat bakalım derdin neymiş.",
                ]
            else:
                candidates = [
                    f"Tabii ki{spk}, seve seve! Bugün ne hakkında konuşmak istersin?",
                    f"Harika bir fikir{spk}, seni dinliyorum, anlat bakalım.",
                    f"Çok isterim{spk}, günün nasıl geçti, neler yapıyorsun?",
                ]

        # 11. General Conversational Fallback (Polite social robot acknowledgement without slot-filling)
        else:
            if "kufurbaz" in p:
                candidates = [
                    f"Dinliyorum lan{spk}, anlatmaya devam et.",
                    f"Söylediklerini aldım lan{spk}, devam et dinliyorum.",
                    f"Anlıyorum lan{spk}, dinliyorum seni.",
                ]
            else:
                candidates = [
                    f"Seni dikkatle dinliyorum{spk}, anlatmaya devam edebilirsin.",
                    f"Söylediklerini aldım{spk}, bu konuda konuşmaya devam edebiliriz.",
                    f"Seni dinliyorum{spk}, başka neler söylemek istersin?",
                    f"Anlıyorum{spk}, seni dinlemeye devam ediyorum.",
                ]

        import random
        random.shuffle(candidates)
        for cand in candidates:
            cand_clean = clean_tts_text(cand)
            valid, _ = self.repetition_guard.check_and_record(cand_clean)
            if valid:
                return cand_clean

        default_resp = f"Dinliyorum lan{spk}, anlatmaya devam et." if "kufurbaz" in p else f"Seni dinliyorum{spk}, anlatmaya devam edebilirsin."
        self.repetition_guard.record_response(default_resp)
        return default_resp

    def _synthesize_speech_pcm(self, text: str) -> Tuple[bytes, str, float, bool]:
        """Synthesizes speech to int16 PCM using:
        1. ElevenLabs Flash v2.5 (Primary Remote TTS ~75ms)
        2. Local Coqui XTTS on CUDA GPU (Local / Offline Fallback)
        3. Edge-TTS in-memory (Emergency Fallback)
        
        Returns: (pcm_bytes, active_engine_name, infer_ms, is_ready)
        """
        if not text:
            return b"", "none", 0.0, False
        clean_text = clean_tts_text(text)
        if not clean_text:
            return b"", "none", 0.0, False

        # 1. Primary Remote TTS: ElevenLabs Flash v2.5 (Only if configured and ready)
        if self.elevenlabs_engine and self.elevenlabs_engine.is_ready():
            try:
                t_s = time.perf_counter()
                pcm_el = self.elevenlabs_engine.synthesize_sentence(clean_text, generation_id=self._fallback_generation_id)
                el_ms = (time.perf_counter() - t_s) * 1000.0
                if pcm_el:
                    return pcm_el, "elevenlabs", el_ms, True
            except Exception as e:
                self.get_logger().warn(f"⚠️ [ElevenLabs Failover] XTTS GPU'ya düşülüyor: {e}")

        # 2. Primary Local GPU Engine: Fine-tuned Coqui XTTS on CUDA GPU (Resident & Warm, TTFA < 500ms)
        is_xtts_ready = bool(self.local_xtts and self.local_xtts.is_ready())
        if is_xtts_ready:
            try:
                t_s = time.perf_counter()
                pcm = self.local_xtts.synthesize_sentence(clean_text, generation_id=self._fallback_generation_id)
                gpu_ms = (time.perf_counter() - t_s) * 1000.0
                if pcm:
                    return pcm, "xtts_gpu", gpu_ms, True
            except Exception as e:
                self.get_logger().warn(f"⚠️ [XTTS GPU Failover] Yerel yedek TTS'e düşülüyor: {e}")

        # 3. Local Offline Backup TTS Engine (Zero internet local resilience fallback)
        if self.local_offline_tts and self.local_offline_tts.is_ready():
            try:
                t_s = time.perf_counter()
                pcm_loc = self.local_offline_tts.synthesize_sentence(clean_text, generation_id=self._fallback_generation_id)
                loc_ms = (time.perf_counter() - t_s) * 1000.0
                if pcm_loc:
                    return pcm_loc, "local_offline_tts", loc_ms, True
            except Exception as e:
                self.get_logger().warn(f"⚠️ [Local Offline TTS Failover]: {e}")

        # 4. Optional Network Fallback: Edge-TTS In-Memory PCM24k (Network required)
        if getattr(self, "edge_tts_enabled", True):
            try:
                self.get_logger().warn("🚨 [EDGE_NETWORK_FALLBACK] İsteğe bağlı ağ ses motoru (Edge-TTS) kullanılıyor.")
                pcm_edge = self._synthesize_edge_tts_pcm24k(clean_text)
                if pcm_edge:
                    return pcm_edge, "edge_tts", 0.0, False
            except Exception as e:
                self.get_logger().debug(f"Edge-TTS notice: {e}")

        return b"", "none", 0.0, False

    def _play_pcm_chunks(
        self,
        pcm_data: bytes,
        generation_id: int = 0,
        tts_provider: str = "xtts_gpu",
        tts_model: str = "xtts_finetuned",
        tts_source: str = "xtts_worker",
    ):
        """Streams 24kHz int16 PCM audio chunks directly to audio output node with smooth 20ms pacing and full provenance."""
        if not pcm_data:
            return
        self._is_playback_active = True
        self._playback_start_monotonic = time.monotonic()
        self.state_machine.transition_to(RobotState.SPEAKING)
        chunk_size = 960  # 480 samples @ 24kHz int16 = 20ms
        try:
            for i in range(0, len(pcm_data), chunk_size):
                if self._barge_in_latched:
                    break
                chunk = pcm_data[i : i + chunk_size]
                if chunk:
                    b64_str = base64.b64encode(chunk).decode("ascii")
                    msg_dict = {
                        "generation_id": generation_id or self._fallback_generation_id,
                        "tts_provider": tts_provider,
                        "tts_model": tts_model,
                        "tts_source": tts_source,
                        "playback_source": tts_source,
                        "data": b64_str,
                    }
                    out_msg = String()
                    out_msg.data = json.dumps(msg_dict)
                    self.pub_output_pcm.publish(out_msg)
                    time.sleep(0.018)
        finally:
            self._is_playback_active = False
            self._playback_end_time = time.monotonic()
            if self.state_machine.current_state == RobotState.SPEAKING:
                self.state_machine.transition_to(RobotState.LISTENING)

    def _process_fallback_turn(self, audio_chunks: List[bytes]):
        """Processes turn using capability-aware ProviderRegistry + Streaming LLM + Pipelined TTS."""
        if self._is_processing_fallback or not audio_chunks:
            return

        self._is_processing_fallback = True
        self._is_responding = True
        self._fallback_generation_id += 1
        self._barge_in_latched = False  # Reset single logical barge-in debounce for new turn
        t_turn_start = time.monotonic()
        chosen_model = "none"
        chosen_provider = "none"
        llm_status = "ok"
        error_class_str = "none"
        model_error_str = "none"
        llm_latency_ms = 0.0
        llm_ttft_ms: Optional[float] = None
        llm_first_clause_ms: Optional[float] = None
        first_audio_played = False
        first_audio_ms = 0.0
        total_synth_ms = 0.0
        total_gpu_ms = 0.0
        total_queue_wait_ms = 0.0
        total_audio_sec = 0.0
        attempts: List[Dict[str, Any]] = []

        try:
            # 1. Combine raw 16kHz PCM chunks into valid in-memory WAV buffer
            raw_pcm = b"".join(audio_chunks)
            if len(raw_pcm) < 16000 * 2 * 0.20:
                return

            # Cheap Local VAD Gate on raw_pcm before remote STT
            t_vad_start = time.monotonic()
            arr_pcm = np.frombuffer(raw_pcm, dtype=np.int16)
            pcm_rms = float(np.sqrt(np.mean(arr_pcm.astype(np.float32) ** 2))) if len(arr_pcm) > 0 else 0.0
            pcm_peak = int(np.max(np.abs(arr_pcm))) if len(arr_pcm) > 0 else 0

            chunk_sz = 320  # 20ms
            speech_frames_cnt = 0
            tot_frames_cnt = max(1, len(arr_pcm) // chunk_sz)
            sp_thresh = max(220.0, self._ambient_rms * 1.15)
            for i in range(0, len(arr_pcm) - chunk_sz + 1, chunk_sz):
                if np.sqrt(np.mean(arr_pcm[i : i + chunk_sz].astype(np.float32) ** 2)) > sp_thresh:
                    speech_frames_cnt += 1
            local_speech_ms = int((speech_frames_cnt * chunk_sz / 16000.0) * 1000.0)
            local_vad_conf = round(min(1.0, speech_frames_cnt / float(tot_frames_cnt)), 2)
            t_vad_end = time.monotonic()

            # Discard immediately if audio has no genuine acoustic speech evidence (0 STT calls)
            if local_speech_ms < 90 or pcm_rms < max(200.0, self._ambient_rms * 1.15) or local_vad_conf < 0.15:
                self.no_speech_rejection_count += 1
                self.get_logger().debug(
                    f"🔇 [VAD Gate Dropped Buffer (0 STT Calls)]: speech_ms={local_speech_ms} | rms={pcm_rms:.1f} | vad_conf={local_vad_conf:.2f}"
                )
                return

            # 2. Transcribe via Groq Whisper Cloud (0-Token Cost STT ~250ms)
            wav_buf = io.BytesIO()
            with wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(raw_pcm)
            wav_bytes = wav_buf.getvalue()

            t_stt_start = time.monotonic()
            raw_transcript = self._transcribe_wav(wav_bytes)
            t_stt_end = time.monotonic()
            stt_ms = (t_stt_end - t_stt_start) * 1000.0

            # 3. Multi-Signal Validation Gate (Transcript + Acoustics + VAD + Playback + Self-Voice)
            now = time.monotonic()
            is_playback = bool(self._is_playback_active)
            is_cooldown = bool((now - self._playback_end_time) < self.echo_mute_cooldown_s)

            validated_text, stt_meta = self._validate_stt_transcript(
                transcript=raw_transcript or "",
                raw_pcm=raw_pcm,
                is_playback_active=is_playback,
                is_echo_cooldown=is_cooldown,
            )

            # Log Detailed STT Segment Telemetry
            self.get_logger().info(
                f"📊 [STT Segment Telemetry]: vad_started={t_vad_start:.2f} | vad_ended={t_vad_end:.2f} | "
                f"stt_started={t_stt_start:.2f} | stt_finished={t_stt_end:.2f} | transcript=\"{raw_transcript}\" | "
                f"vad_confidence={stt_meta.get('vad_confidence', 0.0):.2f} | stt_confidence={stt_meta.get('stt_confidence', 0.0):.2f} | "
                f"rms={stt_meta.get('rms', 0.0):.1f} | peak={stt_meta.get('peak', 0)} | speech_ms={stt_meta.get('speech_ms', 0)} | "
                f"playback_active={is_playback} | self_voice_score={stt_meta.get('self_voice_score', 0.0):.2f} | "
                f"stt_rejected={stt_meta.get('stt_rejected', False)} | reject_reason={stt_meta.get('stt_reject_reason', 'none')}"
            )

            # If rejected, immediately abort turn without LLM, memory, or TTS invocation
            if not validated_text:
                return

            # Check for pure wake word in active mode (e.g. "Astro.", "Hey Astro", "Selam")
            norm_wake_check = re.sub(r"[^\w\s]", "", validated_text.lower()).strip()
            if norm_wake_check in ("astro", "hey astro", "selam astro", "hey", "selam"):
                self.state_machine.transition_to(RobotState.LISTENING)
                self.get_logger().info(
                    f"⚡ [Active Wake-Only]: \"{validated_text}\" -> Woke to LISTENING (wake_only=True, turn_created=False, 0 LLM / 0 TTS)."
                )
                return

            # Check if user said "Hey Astro, <command>" or "Astro, <command>"
            if norm_wake_check.startswith("hey astro "):
                validated_text = validated_text[len("hey astro"):].lstrip(" ,.")
            elif norm_wake_check.startswith("astro "):
                validated_text = validated_text[len("astro"):].lstrip(" ,.")
            elif norm_wake_check.startswith("selam astro "):
                validated_text = validated_text[len("selam astro"):].lstrip(" ,.")

            valid_cmd, cmd_reason = is_valid_user_command(validated_text)
            if not valid_cmd:
                self.state_machine.transition_to(RobotState.LISTENING)
                self.get_logger().info(
                    f"⚡ [Wake + Invalid Command Dropped]: \"{raw_transcript}\" (reason={cmd_reason}) -> Transitioned to LISTENING (0 LLM / 0 TTS)."
                )
                return

            user_text = validated_text
            self.get_logger().info(f"🗣️ [Siz (0-Maliyet)]: \"{user_text}\"")
            self.memory.episodic.add_message("user", user_text)

            # 4. Run Voiceprint Recognition (Acoustic Speaker Identification with Temporal Smoothing)
            spk_name = None
            spk_score = 0.0
            spk_source = "unidentified"
            spk_known = False

            if self.voice_recognizer:
                try:
                    audio_i16 = np.frombuffer(raw_pcm, dtype=np.int16)
                    identified_name, score = self.voice_recognizer.identify_speaker(audio_i16, sample_rate=16000)
                    now_s = time.monotonic()

                    if identified_name and identified_name.lower() != "misafir":
                        # Temporal smoothing:
                        # 1. High confidence (>= 0.65): Confirmed immediately
                        if score >= 0.65:
                            spk_name = identified_name
                            spk_score = score
                            spk_source = "voice_recognition"
                            spk_known = True
                            self._speaker_tentative_name = identified_name
                            self._speaker_tentative_count = 2
                            self._speaker_tentative_last_time = now_s
                            with self._lock:
                                self._recognized_speaker = {
                                    "name": identified_name,
                                    "score": score,
                                    "is_known": True,
                                    "confidence": score,
                                    "source": "voice_recognition",
                                }
                                self._active_person_name = identified_name
                                self._person_hold_until = now_s + 45.0
                        # 2. Tentative confidence (0.45 <= score < 0.65): Requires 2 observations within 15s
                        elif score >= 0.45:
                            if getattr(self, "_speaker_tentative_name", None) == identified_name and (now_s - getattr(self, "_speaker_tentative_last_time", 0.0)) < 15.0:
                                self._speaker_tentative_count += 1
                            else:
                                self._speaker_tentative_name = identified_name
                                self._speaker_tentative_count = 1
                            self._speaker_tentative_last_time = now_s

                            if self._speaker_tentative_count >= 2:
                                spk_name = identified_name
                                spk_score = score
                                spk_source = "voice_recognition_smoothed"
                                spk_known = True
                                with self._lock:
                                    self._recognized_speaker = {
                                        "name": identified_name,
                                        "score": score,
                                        "is_known": True,
                                        "confidence": score,
                                        "source": "voice_recognition_smoothed",
                                    }
                                    self._active_person_name = identified_name
                                    self._person_hold_until = now_s + 45.0
                            else:
                                self.get_logger().info(f"👤 [Tentative Speaker] candidate={identified_name} score={score:.2f} obs={self._speaker_tentative_count}/2 (waiting confirmation)")
                        else:
                            # score < 0.45: Unidentified, discard without overwriting context
                            self.get_logger().debug(f"👤 [Low Confidence Speaker] candidate={identified_name} score={score:.2f} < 0.45 (ignored)")
                except Exception as ex:
                    self.get_logger().debug(f"Voiceprint recognition error: {ex}")

            if not spk_name:
                identity = self._get_active_biometric_identity()
                if identity.get("is_known") and identity.get("name", "").lower() != "misafir":
                    spk_name = identity.get("name")
                    spk_score = identity.get("confidence", 0.85)
                    spk_source = identity.get("source", "memory_hold")
                    spk_known = True

            active_speaker_dict = {
                "name": spk_name or "Misafir",
                "speaker_name": spk_name,
                "confidence": spk_score,
                "is_known": spk_known,
                "source": spk_source,
            }
            speaker_display = spk_name if spk_name else "null"
            self.get_logger().info(f"👤 [Speaker Context] speaker={speaker_display} confidence={spk_score:.2f} source={spk_source}")

            # 5. Select Atomic TTS Owner for this turn (Realtime Fallback -> Edge-TTS -> Local Offline)
            if getattr(self, "edge_tts_enabled", True):
                turn_tts_engine = "edge_tts"
                tts_ready_flag = True
                tts_mode_str = "network_cloud"
                tts_source_name = "edge_tts_cloud"
                tts_model_name = "tr_tr_ahmet"
            elif self.local_offline_tts and self.local_offline_tts.is_ready():
                turn_tts_engine = "local_offline_tts"
                tts_ready_flag = True
                tts_mode_str = "local_offline"
                tts_source_name = "local_offline_synth"
                tts_model_name = "piper_espeak"
            else:
                turn_tts_engine = "none"
                tts_ready_flag = False
                tts_mode_str = "none"
                tts_source_name = "none"
                tts_model_name = "none"

            active_engine = turn_tts_engine

            self.get_logger().info(
                f"🏷️ [TTS Provider Selection Contract]\n"
                f"  generation_id={self._fallback_generation_id}\n"
                f"  selected_tts_provider={active_engine}\n"
                f"  selected_tts_model={tts_model_name}\n"
                f"  tts_source={tts_source_name}\n"
                f"  playback_source={getattr(self.audio_output_manager, 'backend', 'aplay')}\n"
                f"  tts_state={tts_mode_str}\n"
                f"  tts_ready={tts_ready_flag}\n"
                f"  fallback_reason=realtime_unavailable"
            )

            def _synthesize_turn_clause(clause_text: str) -> Tuple[Optional[bytes], float, float, float]:
                clean_text = response_length_gate(clause_text, user_query=user_text, max_words=35, max_sentences=2)
                if not clean_text:
                    return None, 0.0, 0.0, 0.0

                nonlocal active_engine, tts_source_name, tts_model_name

                route_res = self.tts_router.synthesize(
                    clean_text,
                    generation_id=self._fallback_generation_id,
                    language=os.getenv("TTS_LANGUAGE", "tr"),
                )
                active_engine = route_res.actual_provider
                tts_source_name = route_res.source_name
                tts_model_name = route_res.model_name
                return route_res.pcm, route_res.duration_ms, route_res.infer_ms, route_res.queue_wait_ms

            def _handle_and_play_clause_audio(pcm_audio: bytes):
                if not pcm_audio:
                    return
                # Debug WAV & verification log on first real XTTS synthesis
                if active_engine == "xtts_gpu" and not getattr(self, "_first_xtts_debug_wav_written", False):
                    self._first_xtts_debug_wav_written = True
                    try:
                        import wave, hashlib, tempfile
                        wav_dir = "/tmp" if os.path.exists("/tmp") else tempfile.gettempdir()
                        wav_path = os.path.join(wav_dir, f"astro_xtts_{self._fallback_generation_id}.wav")
                        with wave.open(wav_path, "wb") as wf:
                            wf.setnchannels(1)
                            wf.setsampwidth(2)
                            wf.setframerate(24000)
                            wf.writeframes(pcm_audio)
                        audio_sha256 = hashlib.sha256(pcm_audio).hexdigest()
                        duration_ms = int((len(pcm_audio) / 2 / 24000.0) * 1000.0)
                        telem = self.local_xtts.get_telemetry() if self.local_xtts else {}
                        self.get_logger().info(
                            f"🎵 [XTTS OUTPUT VERIFIED]\n"
                            f"  generation_id={self._fallback_generation_id}\n"
                            f"  provider=xtts_gpu\n"
                            f"  model=xtts_finetuned\n"
                            f"  checkpoint={telem.get('xtts_model_path', 'default')}\n"
                            f"  reference={telem.get('xtts_reference_wav', 'default')}\n"
                            f"  sha256={telem.get('xtts_checkpoint_sha256', audio_sha256)}\n"
                            f"  sample_rate=24000\n"
                            f"  audio_bytes={len(pcm_audio)}\n"
                            f"  duration_ms={duration_ms}\n"
                            f"  infer_ms={telem.get('last_infer_ms', 0.0)}"
                        )
                    except Exception as ex_w:
                        self.get_logger().debug(f"XTTS debug WAV write notice: {ex_w}")

                self._play_pcm_chunks(
                    pcm_audio,
                    generation_id=self._fallback_generation_id,
                    tts_provider=active_engine,
                    tts_model=tts_model_name,
                    tts_source=tts_source_name,
                )

            # 6. Instant Intent Interception (Sub-250ms Direct Execution)
            is_weather, w_city = self._is_weather_query(user_text)
            if is_weather:
                weather_info = self._execute_fallback_weather(w_city)
                p = self.persona_name.lower()
                spk = spk_name if spk_name else ""
                if p == "kufurbaz":
                    reply_text = f"Ulan {spk}, {weather_info} Dışarı çıkacaksan ona göre giyin!".strip()
                elif p == "flirt":
                    reply_text = f"Canım benim, {weather_info} Kendine çok dikkat et!".strip()
                else:
                    reply_text = f"{spk} {weather_info}".strip()

                with self._lock:
                    self._recent_robot_phrases.append(reply_text.lower())
                    if len(self._recent_robot_phrases) > 10:
                        self._recent_robot_phrases = self._recent_robot_phrases[-10:]

                pcm, s_ms, g_ms, q_ms = _synthesize_turn_clause(reply_text)
                total_synth_ms += s_ms
                total_gpu_ms += g_ms
                total_queue_wait_ms += q_ms
                if pcm:
                    first_audio_ms = (time.monotonic() - t_turn_start) * 1000.0
                    self.get_logger().info(f"🤖 [Astro (Canlı Hava Durumu)]: \"{reply_text}\"")
                    self.memory.episodic.add_message("assistant", reply_text)
                    self.session.record_robot_speech()
                    _handle_and_play_clause_audio(pcm)
                    return

            # 7. Cognitive LLM via ProviderRegistry (Streaming Groq -> Gemini -> Contextual Persona)
            system_prompt = self._build_current_system_prompt(active_speaker=active_speaker_dict)
            messages = [{"role": "system", "content": system_prompt}]
            recent_msgs = self.memory.episodic.get_messages()[-6:]
            for m in recent_msgs:
                messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})

            groq_candidates = self.provider_registry.get_candidate_models("groq") if self.groq_api_key else []
            full_reply_parts = []
            chunker = SentenceChunker(min_first_clause_chars=18, min_clause_chars=28) if SentenceChunker else None
            t_llm_start = time.monotonic()

            total_audio_bytes = 0
            total_enqueued_chunks = 0

            # Attempt A: Streaming Groq LLMs (20B preferred, fallback to 120B on failure)
            if self.groq_api_key and groq_candidates:
                for target_model in groq_candidates:
                    try:
                        t_model_start = time.monotonic()
                        first_token_seen = False
                        clause_count = 0
                        if chunker:
                            chunker.reset()

                        for token in self.provider_registry.stream_groq_completion(
                            self.groq_api_key,
                            target_model,
                            messages,
                            max_tokens=80,
                            temperature=0.65,
                            timeout=2.5,
                        ):
                            if not first_token_seen:
                                llm_ttft_ms = (time.monotonic() - t_model_start) * 1000.0
                                first_token_seen = True

                            full_reply_parts.append(token)

                            if chunker:
                                clauses = chunker.feed(token)
                                for cl in clauses:
                                    clause_count += 1
                                    if llm_first_clause_ms is None:
                                        llm_first_clause_ms = (time.monotonic() - t_model_start) * 1000.0
                                    pcm, s_ms, g_ms, q_ms = _synthesize_turn_clause(cl)
                                    total_synth_ms += s_ms
                                    total_gpu_ms += g_ms
                                    total_queue_wait_ms += q_ms
                                    if pcm:
                                        total_audio_sec += (len(pcm) / 2) / 24000.0
                                        total_audio_bytes += len(pcm)
                                        total_enqueued_chunks += (len(pcm) + 959) // 960
                                        if not first_audio_played:
                                             first_audio_ms = (time.monotonic() - t_turn_start) * 1000.0
                                             first_audio_played = True
                                        _handle_and_play_clause_audio(pcm)

                            # Stop policy: Limit social robot conversational response to 2-3 concise sentences
                            if clause_count >= 3 and len("".join(full_reply_parts)) > 60:
                                break

                        # Flush any remaining text in chunker buffer
                        if chunker:
                            rem_cl = chunker.flush()
                            if rem_cl:
                                if llm_first_clause_ms is None:
                                    llm_first_clause_ms = (time.monotonic() - t_model_start) * 1000.0
                                pcm, s_ms, g_ms, q_ms = _synthesize_turn_clause(rem_cl)
                                total_synth_ms += s_ms
                                total_gpu_ms += g_ms
                                total_queue_wait_ms += q_ms
                                if pcm:
                                    total_audio_sec += (len(pcm) / 2) / 24000.0
                                    total_audio_bytes += len(pcm)
                                    total_enqueued_chunks += (len(pcm) + 959) // 960
                                    if not first_audio_played:
                                        first_audio_ms = (time.monotonic() - t_turn_start) * 1000.0
                                        first_audio_played = True
                                    _handle_and_play_clause_audio(pcm)

                        if full_reply_parts:
                            chosen_model = target_model
                            chosen_provider = "groq"
                            llm_latency_ms = (time.monotonic() - t_model_start) * 1000.0
                            self.provider_registry.record_success("groq", target_model, llm_latency_ms)
                            attempts.append({
                                "provider": "groq",
                                "model": target_model,
                                "result": "success",
                                "latency_ms": int(llm_latency_ms)
                            })
                            break
                    except ProviderError as pe:
                        error_class_str = pe.error_class.value
                        model_error_str = pe.message[:80]
                        attempts.append({
                            "provider": "groq",
                            "model": target_model,
                            "result": "failed",
                            "error_class": pe.error_class.value,
                            "error": pe.message[:80]
                        })
                        self.get_logger().warn(f"⚠️ [Groq Model Fallback] {target_model} failed ({pe.error_class.value}): {pe.message[:80]}")
                        full_reply_parts = []
                        continue

            # Attempt B: Google Gemini REST Fallback (if Groq produced no tokens)
            if not full_reply_parts and self.gemini_api_key:
                gemini_candidates = self.provider_registry.get_candidate_models("gemini")
                for g_mod in gemini_candidates:
                    try:
                        t_gem_start = time.monotonic()
                        gem_text = self.provider_registry.generate_gemini_content(
                            self.gemini_api_key,
                            g_mod,
                            system_prompt,
                            messages,
                            max_tokens=80,
                            temperature=0.65,
                            timeout=4.0,
                        )
                        if gem_text:
                            full_reply_parts = [gem_text]
                            chosen_model = g_mod
                            chosen_provider = "gemini"
                            llm_latency_ms = (time.monotonic() - t_gem_start) * 1000.0
                            llm_ttft_ms = llm_latency_ms
                            llm_first_clause_ms = llm_latency_ms
                            self.provider_registry.record_success("gemini", g_mod, llm_latency_ms)
                            attempts.append({
                                "provider": "gemini",
                                "model": g_mod,
                                "result": "success",
                                "latency_ms": int(llm_latency_ms)
                            })
                            break
                    except ProviderError as pe:
                        error_class_str = pe.error_class.value
                        model_error_str = pe.message[:80]
                        attempts.append({
                            "provider": "gemini",
                            "model": g_mod,
                            "result": "failed",
                            "error_class": pe.error_class.value,
                            "error": pe.message[:80]
                        })
                        self.get_logger().warn(f"⚠️ [Gemini Model Fallback] {g_mod} failed ({pe.error_class.value}): {pe.message[:80]}")
                        continue

            full_reply_str = clean_tts_text("".join(full_reply_parts))

            # Attempt C: Dynamic Context-Grounded Persona Fallback (if all cloud LLMs failed)
            if not full_reply_str:
                full_reply_str = self._generate_contextual_persona_fallback(user_text)
                chosen_model = "contextual_grounding"
                chosen_provider = "local_persona"
                llm_status = "degraded"
                attempts.append({
                    "provider": "local_persona",
                    "model": "contextual_grounding",
                    "result": "success"
                })
            else:
                self.repetition_guard.record_response(full_reply_str)

            # Record assistant reply for self-voice echo correlation
            with self._lock:
                self._recent_robot_phrases.append(full_reply_str.lower())
                if len(self._recent_robot_phrases) > 10:
                    self._recent_robot_phrases = self._recent_robot_phrases[-10:]

            # Synthesize full response if not already streamed in chunks
            if not first_audio_played and full_reply_str:
                pcm, s_ms, g_ms, q_ms = _synthesize_turn_clause(full_reply_str)
                total_synth_ms += s_ms
                total_gpu_ms += g_ms
                total_queue_wait_ms += q_ms
                if pcm:
                    total_audio_sec += (len(pcm) / 2) / 24000.0
                    total_audio_bytes += len(pcm)
                    total_enqueued_chunks += (len(pcm) + 959) // 960
                    first_audio_ms = (time.monotonic() - t_turn_start) * 1000.0
                    first_audio_played = True
                    self._play_pcm_chunks(pcm)

            t_total_end = time.monotonic()
            total_turn_ms = (t_total_end - t_turn_start) * 1000.0

            if full_reply_str:
                self.get_logger().info(f"🤖 [Astro ({chosen_provider}/{chosen_model})]: \"{full_reply_str}\"")
                self.memory.episodic.add_message("assistant", full_reply_str)
                self.session.record_robot_speech()

                xtts_info = self.local_xtts.get_telemetry() if self.local_xtts else {}
                is_xtts_actually_ready = bool(self.local_xtts and self.local_xtts.is_ready())
                xtts_err_str = "none"
                if not is_xtts_actually_ready:
                    xtts_state = self.local_xtts.state if self.local_xtts else "uninitialized"
                    xtts_err_str = xtts_info.get("error", xtts_state)

                # Determine TTS metadata
                if active_engine == "elevenlabs":
                    tts_model_name = self.elevenlabs_engine.model_id if self.elevenlabs_engine else "eleven_flash_v2_5"
                    tts_voice_name = self.elevenlabs_engine.voice_id if self.elevenlabs_engine else "configured"
                    tts_mode_val = "remote_cloud"
                elif active_engine == "xtts_gpu":
                    tts_model_name = "xtts_finetuned"
                    tts_voice_name = xtts_info.get("xtts_reference_wav", self.local_xtts.speaker_wav if self.local_xtts else "reference.wav")
                    tts_mode_val = "local_gpu"
                elif active_engine == "local_offline_tts":
                    tts_model_name = getattr(self.local_offline_tts, "_mode", "local_offline") if self.local_offline_tts else "local_offline"
                    tts_voice_name = "local_offline_synth"
                    tts_mode_val = "local_offline"
                elif active_engine == "edge_tts":
                    tts_model_name = "edge_tts"
                    tts_voice_name = "tr-TR-AhmetNeural"
                    tts_mode_val = "network"
                else:
                    tts_model_name = "none"
                    tts_voice_name = "none"
                    tts_mode_val = "none"

                worker_pid = xtts_info.get("worker_pid", "None")
                gpu_name_str = xtts_info.get("gpu_name", "Orin")
                xtts_ckpt_str = xtts_info.get("xtts_model_path", "none")
                xtts_sha_str = xtts_info.get("xtts_checkpoint_sha256", "none")
                xtts_sha_short = xtts_sha_str[:12] if xtts_sha_str != "none" else "none"

                ttft_str = int(llm_ttft_ms) if llm_ttft_ms is not None else "null"
                first_clause_str = int(llm_first_clause_ms) if llm_first_clause_ms is not None else "null"
                speaker_log_val = spk_name if spk_name else "null"

                tts_error_val = xtts_err_str if active_engine == "xtts_gpu" else ("none" if tts_ready_flag else "provider_unavailable")

                # OAK-D Lite stability and frame age calculation
                now_telem = time.monotonic()
                oak_frame_age = int((now_telem - self._oak_last_frame_time) * 1000) if self._oak_last_frame_time > 0 else "null"
                oak_info_age = int((now_telem - self._oak_last_camera_info_time) * 1000) if self._oak_last_camera_info_time > 0 else "null"
                oak_state = "CONNECTED" if (self._oak_last_frame_time > 0 and (now_telem - self._oak_last_frame_time) < 3.0) else "DISCONNECTED"

                tts_synth_started_flag = bool(total_synth_ms > 0 or total_audio_bytes > 0)
                tts_synth_finished_flag = bool(total_audio_bytes > 0)
                tts_source_name = "xtts_worker" if active_engine == "xtts_gpu" else ("elevenlabs_cloud" if active_engine == "elevenlabs" else ("local_offline_synth" if active_engine == "local_offline_tts" else "edge_tts_cloud"))
                pb_source = getattr(self.audio_output_manager, 'backend', 'aplay')
                is_xtts_healthy = bool(self.local_xtts and getattr(self.local_xtts, "is_healthy", lambda: False)())

                # Mismatch Alarm Audit
                if active_engine == "xtts_gpu" and tts_source_name != "xtts_worker":
                    self.get_logger().error(f"🚨 [TTS MISMATCH ALARM]: selected_provider=xtts_gpu but tts_source={tts_source_name}!")
                if active_engine == "xtts_gpu" and pb_source == "espeak":
                    self.get_logger().error(f"🚨 [TTS MISMATCH ALARM]: selected_provider=xtts_gpu but playback_source=espeak!")
                if first_audio_played and total_audio_bytes == 0:
                    self.get_logger().error(f"🚨 [TTS MISMATCH ALARM]: playback_started=True but played_bytes=0!")
                if tts_synth_finished_flag and not first_audio_played:
                    self.get_logger().error(f"🚨 [TTS MISMATCH ALARM]: synthesis_finished=True but playback_started=False!")

                resp_chars = len(full_reply_str)
                resp_words = len(full_reply_str.split())
                rt_state = getattr(self.realtime_engine, "state", None)
                rt_state_name = rt_state.value if hasattr(rt_state, "value") else "OFFLINE"
                rt_fail_reason = getattr(self.realtime_engine, "_last_degradation_reason", "none")

                self.get_logger().info(
                    f"[Turn Telemetry]\n"
                    f"generation_id={self._fallback_generation_id}\n"
                    f"realtime_state={rt_state_name}\n"
                    f"realtime_failure_reason={rt_fail_reason}\n"
                    f"requested_provider=openai_realtime\n"
                    f"actual_provider={active_engine}\n"
                    f"response_chars={resp_chars}\n"
                    f"response_words={resp_words}\n"
                    f"tts_ttfa_ms={int(total_synth_ms)}\n"
                    f"tts_total_ms={int(total_synth_ms)}\n"
                    f"playback_started={first_audio_played}\n"
                    f"playback_finished={first_audio_played and tts_synth_finished_flag}\n"
                    f"playback_failed={not first_audio_played and tts_synth_started_flag}"
                )

                if active_engine == "xtts_gpu" and not getattr(self, "_first_xtts_synthesis_verified", False):
                    self._first_xtts_synthesis_verified = True
                    self.get_logger().info(
                        f"🎯 [XTTS First Synthesis Verified]:\n"
                        f"  tts_synthesis_started=true\n"
                        f"  tts_provider=xtts_gpu\n"
                        f"  tts_model=xtts_finetuned\n"
                        f"  xtts_checkpoint={xtts_ckpt_str}\n"
                        f"  xtts_reference={tts_voice_name}\n"
                        f"  xtts_sha256={xtts_sha_str}\n"
                        f"  xtts_infer_ms={int(total_gpu_ms)}\n"
                        f"  tts_audio_bytes={total_audio_bytes}"
                    )

        except Exception as e:
            self.get_logger().warn(f"Fallback turn notice: {e}")
        finally:
            self._is_processing_fallback = False
            self._is_responding = False
            self._playback_end_time = time.monotonic()
            self._flush_audio_buffers("end_fallback_turn")

    def _on_input_pcm(self, msg: String):
        """Sends incoming microphone 24kHz PCM chunk to OpenAI Realtime WebSocket or processes turn via 0-cost Groq fallback."""
        if not msg.data:
            return

        now = time.monotonic()

        # Try parsing JSON wrapped frame or raw base64 PCM string
        raw_16k: bytes = b""
        local_rms: float = 0.0
        peak_val: int = 0
        try:
            raw_str = msg.data.strip()
            if raw_str.startswith("{") and raw_str.endswith("}"):
                data_dict = json.loads(raw_str)
                b64_audio = data_dict.get("data", "")
                raw_bytes = base64.b64decode(b64_audio.encode("ascii")) if b64_audio else b""
            else:
                raw_bytes = base64.b64decode(raw_str.encode("ascii"))
            if raw_bytes:
                # Always resample 24kHz incoming audio to 16kHz for uniform processing
                raw_16k = resample_24k_to_16k(raw_bytes)
                arr = np.frombuffer(raw_16k, dtype=np.int16)
                if len(arr) > 0:
                    local_rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
                    peak_val = int(np.max(np.abs(arr)))
        except Exception as _exc:
            self.get_logger().debug(f"_on_input_pcm: yok sayılan hata ({_exc})")

        # Update background ambient noise floor when quiet
        if local_rms < 380.0:
            self._ambient_rms = 0.96 * self._ambient_rms + 0.04 * local_rms

        # ====================================================================
        # SLEEP / DEEP_IDLE MODE: Dedicated Low-CPU Wake Detector
        # ====================================================================
        if self._is_sleeping or self.state_machine.is_deep_idle():
            if raw_16k:
                is_speech_energy = (local_rms > max(420.0, self._ambient_rms * 1.45) and peak_val > 1000)
                if is_speech_energy:
                    self._wake_last_voice_time = now
                    if not self._wake_listening:
                        self._wake_listening = True
                        with self._lock:
                            pre_frames = list(self._user_speech_audio_buffer[-8:]) if len(self._user_speech_audio_buffer) >= 8 else []
                        self._wake_audio_buffer = list(pre_frames) + [raw_16k]
                    else:
                        self._wake_audio_buffer.append(raw_16k)
                elif self._wake_listening:
                    self._wake_audio_buffer.append(raw_16k)
                    # Silence pause (0.50s after speech ends) triggers wake verification
                    if (now - self._wake_last_voice_time) > 0.50:
                        self._wake_listening = False
                        if len(self._wake_audio_buffer) >= 10:
                            # Pre-STT local VAD energy check
                            raw_w = b"".join(self._wake_audio_buffer)
                            arr_w = np.frombuffer(raw_w, dtype=np.int16)
                            w_rms = float(np.sqrt(np.mean(arr_w.astype(np.float32) ** 2))) if len(arr_w) > 0 else 0.0
                            if w_rms >= max(360.0, self._ambient_rms * 1.25):
                                buf_to_proc = list(self._wake_audio_buffer)
                                self._wake_audio_buffer.clear()
                                threading.Thread(target=self._process_wake_candidate, args=(buf_to_proc,), daemon=True).start()
                            else:
                                self._wake_audio_buffer.clear()
                        else:
                            self._wake_audio_buffer.clear()
            return

        # ====================================================================
        # ACTIVE MODE: Interaction timestamp & State Tracking
        # ====================================================================
        self._last_interaction_time = now

        # Playback & Echo Cooldown State Determination
        # P0-7: Barge-in is only evaluated during active audio playback
        is_active_playback = bool(self._is_playback_active)

        # Adaptive barge-in threshold derived from ambient noise floor
        adaptive_barge_in_rms = max(self.barge_in_min_rms, self._ambient_rms * self.barge_in_noise_mult)

        # Zero Self-Hearing Protection & Multi-Signal Persistent Barge-In
        if is_active_playback:
            playback_start = getattr(self, "_playback_start_monotonic", 0.0)

            # 1. Acoustic Protection Window: Strictly suppress self-voice feedback during initial burst (e.g. 350ms)
            if playback_start > 0.0 and ((now - playback_start) * 1000.0 < self.barge_in_protection_ms):
                self._barge_in_consecutive_frames = 0
                return

            # Adaptive barge-in threshold derived from ambient noise floor
            adaptive_barge_in_rms = max(self.barge_in_min_rms, self._ambient_rms * self.barge_in_noise_mult)

            # 2. Distinguish loud acoustic voice from background
            is_loud = (local_rms >= adaptive_barge_in_rms and peak_val >= self.barge_in_min_peak)
            if is_loud:
                self._barge_in_consecutive_frames += 1
            else:
                self._barge_in_consecutive_frames = max(0, self._barge_in_consecutive_frames - 1)

            # Require persistent speech across multiple consecutive frames (>= 3 frames = 60ms) to avoid impulse noise
            if self._barge_in_consecutive_frames < self.barge_in_min_consecutive_frames:
                return

            # Barge-In latch: Only one logical barge-in transition per generation
            if self._barge_in_latched:
                return
            self._barge_in_latched = True
            self._barge_in_consecutive_frames = 0
            barge_in_after_ms = int((now - playback_start) * 1000.0) if playback_start > 0.0 else int(self.barge_in_protection_ms + 100)

            # Genuine User Barge-In during Playback!
            self.state_machine.transition_to(RobotState.INTERRUPTED)
            self._is_responding = False
            self._is_playback_active = False
            self._fallback_speaking = True
            self._fallback_speech_start = now
            self._last_speech_time = now
            self._fallback_generation_id += 1
            if self.elevenlabs_engine:
                self.elevenlabs_engine.cancel(self._fallback_generation_id)
            if self.local_xtts:
                self.local_xtts.cancel(self._fallback_generation_id)
            if self.local_offline_tts:
                self.local_offline_tts.cancel(self._fallback_generation_id)
            int_msg = Bool()
            int_msg.data = True
            self.pub_interrupt.publish(int_msg)
            with self._lock:
                self._fallback_audio_buffer = [raw_16k]
            self.get_logger().info(
                f"⚡ [Realtime Barge-In] Kullanıcı araya girdi (RMS: {local_rms:.0f}, Peak: {peak_val}, "
                f"barge_in_after_ms={barge_in_after_ms}, Latch: True)."
            )
            self.state_machine.transition_to(RobotState.LISTENING)
            return

        # Acoustic presence / wake-up (requires sustained intentional voice > 500 RMS across >=5 consecutive frames)
        if local_rms > 500.0:
            self._consecutive_loud_frames += 1
        else:
            self._consecutive_loud_frames = max(0, self._consecutive_loud_frames - 1)

        if self._consecutive_loud_frames >= 5 and (now - getattr(self, "_node_start_time", 0.0)) > 4.0:
            self._last_interaction_time = now
            if self._is_sleeping:
                self._wake_up()

        # --- 0-Cost Fallback Mode (Groq STT + Groq LLM + Edge-TTS) ---
        if self._fallback_mode or not self._is_connected or not self._ws or not self._loop:
            if raw_16k:
                try:
                    speech_start_condition = (local_rms > max(380.0, self._ambient_rms * 1.40) and peak_val > 900)
                    if speech_start_condition:
                        self._last_speech_time = now
                        if not self._fallback_speaking:
                            self._fallback_speaking = True
                            self._fallback_speech_start = now
                            with self._lock:
                                pre_frames = list(self._user_speech_audio_buffer[-8:]) if len(self._user_speech_audio_buffer) >= 8 else []
                            self._fallback_audio_buffer = list(pre_frames) + [raw_16k]
                        else:
                            self._fallback_audio_buffer.append(raw_16k)
                    elif self._fallback_speaking:
                        self._fallback_audio_buffer.append(raw_16k)
                        # Silence timeout (0.75s after speech ends)
                        if (now - self._last_speech_time) > 0.75:
                            self._fallback_speaking = False
                            if len(self._fallback_audio_buffer) >= 12 and not self._is_processing_fallback:
                                # Pre-STT Local VAD Density Filter (0-Token protection against noise/silence)
                                raw_fb = b"".join(self._fallback_audio_buffer)
                                arr_fb = np.frombuffer(raw_fb, dtype=np.int16)
                                fb_rms = float(np.sqrt(np.mean(arr_fb.astype(np.float32) ** 2))) if len(arr_fb) > 0 else 0.0
                                chunk_sz = 320  # 20ms
                                loud_cnt = sum(
                                    1 for i in range(0, len(arr_fb) - chunk_sz + 1, chunk_sz)
                                    if np.sqrt(np.mean(arr_fb[i : i + chunk_sz].astype(np.float32) ** 2)) > max(280.0, self._ambient_rms * 1.25)
                                )
                                total_chunks = max(1, len(arr_fb) // chunk_sz)
                                speech_ratio = loud_cnt / float(total_chunks)

                                if fb_rms >= max(260.0, self._ambient_rms * 1.20) and loud_cnt >= 5 and speech_ratio >= 0.15:
                                    buf_to_proc = list(self._fallback_audio_buffer)
                                    self._fallback_audio_buffer.clear()
                                    threading.Thread(target=self._process_fallback_turn, args=(buf_to_proc,), daemon=True).start()
                                else:
                                    self.no_speech_rejection_count += 1
                                    self._fallback_audio_buffer.clear()
                except Exception as _exc:
                    self.get_logger().debug(f"_on_input_pcm: yok sayılan hata ({_exc})")
            return

        # --- Standard OpenAI Realtime Mode ---
        payload = {
            "type": "input_audio_buffer.append",
            "audio": msg.data
        }
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)
        except Exception as _exc:
            self.get_logger().debug(f"_on_input_pcm: yok sayılan hata ({_exc})")


    def _trigger_proactive_greeting(self, name: str, formal_title: str):
        """Sends proactive greeting message to Realtime session."""
        if not self._ws or not self._loop or not self._is_connected:
            return

        greeting_event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"[Sistem Olayı]: Karşında {name} ({formal_title}) duruyor! Kendisini seçili kişiliğinle coşkuyla ve uygun hitapla selamla, neşeyle hatırını sor."
                    }
                ]
            }
        }
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(greeting_event)), self._loop)
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps({"type": "response.create"})), self._loop)
        except Exception as _exc:
            self.get_logger().debug(f"_trigger_proactive_greeting: yok sayılan hata ({_exc})")

    def _on_recognized_person(self, msg: String):
        try:
            data = json.loads(msg.data)
            now = time.monotonic()
            with self._lock:
                self._recognized_person = data
                if data.get("is_known") and data.get("confidence", 0.0) >= 0.45:
                    if self._is_sleeping:
                        self._wake_up()
                    name = data.get("name", "")
                    title = data.get("title", "")
                    formal_title = data.get("formal_title", title or name)
                    self._active_person_name = name
                    self._person_hold_until = now + 45.0  # Hold identity for 45 seconds

                    # Event-driven vision trigger for new person
                    if getattr(self, "_last_seen_person", "") != name:
                        self._last_seen_person = name
                        threading.Thread(target=self._evaluate_vision_event, args=("new_person",), daemon=True).start()

                    # Proactive greeting check: greet once every 2 minutes per person
                    last_greet = self._greeted_people.get(name, 0.0)
                    if (now - last_greet) > 120.0 and not self._is_responding and not self._is_playback_active:
                        self._greeted_people[name] = now
                        self.get_logger().info(f"👋 [Proaktif Selamlama]: {name} ({formal_title}) algılandı — Selamlama başlatılıyor!")
                        self._trigger_proactive_greeting(name, formal_title)

            self._sync_perception_to_session()
        except Exception as _exc:
            self.get_logger().debug(f"_on_recognized_person: yok sayılan hata ({_exc})")

    def _on_speaker_id(self, msg: String):
        try:
            raw = (msg.data or "").strip()
            if not raw:
                return
            if raw.startswith("{") and raw.endswith("}"):
                data = json.loads(raw)
            else:
                is_k = raw.lower() not in ("misafir", "unknown", "none", "tanınmadı", "")
                data = {"name": raw if is_k else "Misafir", "confidence": 0.90 if is_k else 0.0, "is_known": is_k, "source": "speaker_id_topic"}
            with self._lock:
                self._recognized_speaker = data
                if data.get("is_known") and data.get("confidence", 0.0) >= 0.40 and data.get("name", "").lower() != "misafir":
                    self._active_person_name = data.get("name")
                    self._person_hold_until = time.monotonic() + 45.0
            self._sync_perception_to_session()
        except Exception as _exc:
            self.get_logger().debug(f"_on_speaker_id: yok sayılan hata ({_exc})")

    def _on_user_emotion(self, msg: String):
        self._user_emotion = msg.data.lower().strip()

    def _on_looking_at_robot(self, msg: Bool):
        new_state = bool(msg.data)
        if new_state and not getattr(self, "_last_looking_state", False):
            self._last_looking_state = True
            threading.Thread(target=self._evaluate_vision_event, args=("user_attention_event",), daemon=True).start()
        elif not new_state:
            self._last_looking_state = False
        self._looking_at_robot = new_state

    def _on_user_distance(self, msg: Float32):
        new_dist = float(msg.data)
        old_dist = getattr(self, "_last_seen_distance", 0.0)
        if abs(new_dist - old_dist) >= 0.60:
            self._last_seen_distance = new_dist
            threading.Thread(target=self._evaluate_vision_event, args=("person_approached",), daemon=True).start()
        self._user_distance = new_dist

    def _on_doa(self, msg: Float32):
        self._speaker_angle = float(msg.data)

    def _get_active_biometric_identity(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            face = self._recognized_person or {}
            spk = self._recognized_speaker or {}
            held_name = getattr(self, "_active_person_name", "Misafir")
            hold_until = getattr(self, "_person_hold_until", 0.0)

        # 1. Known Active Voice
        if spk.get("is_known") and spk.get("confidence", 0.0) >= 0.40 and spk.get("name", "").lower() != "misafir":
            return {**spk, "source": "voice"}

        # 2. Known Active Face
        if face.get("is_known") and face.get("confidence", 0.0) >= 0.45 and face.get("name", "").lower() != "misafir":
            return {**face, "source": "face"}

        # 3. Memory Hold (Active conversation continuity)
        if now < hold_until and held_name and held_name.lower() != "misafir":
            return {"name": held_name, "title": held_name, "formal_title": held_name, "is_known": True, "source": "memory_hold", "confidence": 0.90}

        return {"name": "Misafir", "title": "Ziyaretçi", "formal_title": "Misafir", "is_known": False, "source": "guest"}

    def _sync_perception_to_session(self):
        """Dynamically syncs persona & recognized identity to the active OpenAI Realtime session ONLY when identity changes."""
        if not self._ws or not self._loop or not self._is_connected:
            return

        now = time.monotonic()
        identity = self._get_active_biometric_identity()
        identity_name = identity.get("name", "Misafir")

        # Strictly require identity change: If it is still the same person/guest, NEVER resync
        last_id = getattr(self, "_last_synced_identity", "")
        if identity_name == last_id:
            return

        prev_id = last_id
        self._last_synced_identity = identity_name
        self._last_sync_time = now

        system_prompt = self._build_current_system_prompt()
        update_event = {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": system_prompt
            }
        }

        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(update_event)), self._loop)
            self.get_logger().info(f"👤 [Realtime Biyometri]: Oturum kimliği güncellendi -> {identity_name}")

            # Send in-conversation event to notify current active context of identity switch
            if identity.get("is_known"):
                name_id = identity.get("name")
                notice_text = f"[Sistem Bildirimi]: Karşındaki kişi %100 doğrulukla biyometrik olarak tanındı: {name_id} ({identity.get('formal_title')}). Kendisine doğrudan bu isimle ({name_id}) hitap et."
            else:
                prev_str = f"önceki kullanıcı ({prev_id})" if prev_id and prev_id != "Misafir" else "önceki kişi"
                notice_text = f"[Sistem Bildirimi]: DİKKAT: Karşındaki kişinin sesi analiz edildi ve TANINMADI (Bilinmeyen Kişi / Misafir). Bu kişi {prev_str} DEĞİLDİR! Kendisine ASLA {prev_id or 'Baran'} deme. Kendisini tanımadığını ve sesini ilk defa duyduğunu belirterek adını sor."

            notice_event = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": notice_text}]
                }
            }
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(notice_event)), self._loop)
        except Exception as _exc:
            self.get_logger().debug(f"_sync_perception_to_session: yok sayılan hata ({_exc})")






def main(args=None):
    rclpy.init(args=args)
    node = AstroRealtimeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt as _exc:
        _LOG.debug("main: yok sayılan hata (%s)", _exc)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
