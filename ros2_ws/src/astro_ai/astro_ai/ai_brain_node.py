#!/usr/bin/env python3
"""ASTRO V1 — Real-Time Conversational AI Brain Node (Modular Architecture).

Coordinates:
  - State Machine (FSM): IDLE, LISTENING, THINKING, SPEAKING, INTERRUPTED
  - 3-Tier Memory Architecture: Episodic Buffer, Session Memory, Persistent Profile
  - Adaptive Conversation Session Manager & Latency Tracker (p50/p95)
  - Persona Engine & Deterministic Perception Context Injection
  - Tool Execution & Real-Time Streaming LLM Speech Synthesis
"""

import base64
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32, String

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from dotenv import find_dotenv, load_dotenv
except ImportError:
    def find_dotenv(*args, **kwargs): return ""
    def load_dotenv(*args, **kwargs): pass

try:
    from astro_ai.state_machine import StateMachine, RobotState
    from astro_ai.memory_manager import MemoryManager
    from astro_ai.persona_engine import (
        PersonaEngine, ROBOT_TOOLS, PERSONA_PROMPTS,
        clean_tts_text, extract_spoken_turkish_sentence
    )
    from astro_ai.conversation_session import ConversationSession
    from astro_ai.cloud_manager import CloudManager
    from astro_ai.officials_database import find_official_by_name_or_alias, get_official_greeting, OFFICIALS_DATABASE
except ImportError:
    from state_machine import StateMachine, RobotState
    from memory_manager import MemoryManager
    from persona_engine import (
        PersonaEngine, ROBOT_TOOLS, PERSONA_PROMPTS,
        clean_tts_text, extract_spoken_turkish_sentence
    )
    from conversation_session import ConversationSession
    from cloud_manager import CloudManager
    from officials_database import find_official_by_name_or_alias, get_official_greeting, OFFICIALS_DATABASE


def _load_env():
    candidates = [
        os.path.abspath(".env"),
        os.path.abspath(".env.production"),
        os.path.abspath(os.path.join(os.getcwd(), ".env")),
        os.path.abspath(os.path.join(os.getcwd(), ".env.production")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env.production")),
        os.path.expanduser("~/Desktop/astr1/.env"),
        os.path.expanduser("~/Desktop/astr1/.env.production"),
        os.path.expanduser("~/.env")
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


def imgmsg_to_bgr(msg: Image) -> np.ndarray | None:
    try:
        if msg.encoding == "bgr8":
            return np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3).copy()
        elif msg.encoding == "rgb8":
            data = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
            return cv2.cvtColor(data, cv2.COLOR_RGB2BGR) if cv2 else data[:, :, ::-1].copy()
        elif msg.encoding in ("mono8", "8UC1"):
            data = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width)
            return cv2.cvtColor(data, cv2.COLOR_GRAY2BGR) if cv2 else np.stack([data]*3, axis=-1)
    except Exception:
        pass
    return None


def frame_to_base64_jpeg(frame: np.ndarray, max_dim: int = 512) -> str | None:
    if cv2 is None or frame is None:
        return None
    try:
        h, w = frame.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / float(max(h, w))
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return base64.b64encode(buffer).decode("utf-8")
    except Exception:
        return None


def is_canned_refusal(text: str) -> bool:
    """Detects standard LLM safety refusal boilerplate phrases and English reasoning leaks."""
    if not text:
        return False
    t_lower = text.lower().strip()
    refusal_patterns = [
        "yardımcı olamam", "yardımcı olamayacağım", "bu isteğinize yardımcı",
        "isteğinize yardımcı olamam", "yardımcı olamam maalesef", "üzgünüm, ancak",
        "üzgünüm, ama lütfen", "daha saygılı bir dil", "bir yapay zeka olarak",
        "yapay zeka olarak", "uygunsuz içerik", "as an ai", "i cannot assist",
        "i cannot fulfill", "i am unable to", "here's a thinking process",
        "thinking process", "let's think"
    ]
    return any(p in t_lower for p in refusal_patterns)


class AiBrainNode(Node):
    def __init__(self):
        super().__init__("ai_brain_node")
        _load_env()

        # Core Modular Components
        self.memory = MemoryManager()
        self.cloud_mgr = CloudManager()
        initial_persona = self.memory.profile.data.get("current_persona", "playful")
        self.persona_engine = PersonaEngine(initial_persona)
        self.state_machine = StateMachine(RobotState.IDLE)

        # Parameters
        self.declare_parameter("llm_model", os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"))
        self.declare_parameter("vision_model", os.getenv("VISION_MODEL", "llama-3.2-90b-vision-preview"))
        self.declare_parameter("llm_temperature", float(os.getenv("LLM_TEMPERATURE", "0.55")))
        self.declare_parameter("llm_max_tokens", int(os.getenv("LLM_MAX_TOKENS", "300")))
        self.declare_parameter("wake_word", os.getenv("WAKE_WORD", "hey astro"))
        self.declare_parameter("conversation_timeout", float(os.getenv("CONVERSATION_TIMEOUT", "16.0")))
        self.declare_parameter("gaze_dwell_s", float(os.getenv("GAZE_DWELL_S", "4.0")))
        self.declare_parameter("gaze_cooldown_s", float(os.getenv("GAZE_COOLDOWN_S", "60.0")))
        self.declare_parameter("gaze_startup_grace_s", float(os.getenv("GAZE_STARTUP_GRACE_S", "15.0")))
        self.declare_parameter("default_user_name", os.getenv("DEFAULT_USER_NAME", "Misafir"))
        self.declare_parameter("enable_idle_learning", os.getenv("ENABLE_IDLE_LEARNING", "true").lower() == "true")

        self._text_model = self.get_parameter("llm_model").value
        self._fallback_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
        self._vision_model = self.get_parameter("vision_model").value
        self._temperature = float(self.get_parameter("llm_temperature").value)
        self._max_tokens = int(self.get_parameter("llm_max_tokens").value)
        self._wake_word = self.get_parameter("wake_word").value
        conv_timeout = float(self.get_parameter("conversation_timeout").value)
        self._gaze_dwell_s = float(self.get_parameter("gaze_dwell_s").value)
        self._gaze_cooldown_s = float(self.get_parameter("gaze_cooldown_s").value)
        self._gaze_startup_grace_s = float(self.get_parameter("gaze_startup_grace_s").value)
        self._default_user_name = str(self.get_parameter("default_user_name").value)
        self._enable_idle_learning = bool(self.get_parameter("enable_idle_learning").value)

        # Adaptive Session
        self.session = ConversationSession(
            base_timeout_s=conv_timeout,
            on_session_start=lambda: self.get_logger().info("✨ [Session] Konuşma Oturumu Başlatıldı."),
            on_session_end=self._on_session_timed_out
        )

        # 1. OpenAI Client (Primary High-Performance LLM & Vision Engine)
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip() or os.environ.get("AI_API_KEY", "").strip()
        self._openai = None
        self._enabled = False

        if OpenAI and self.openai_api_key and self.openai_api_key.startswith("sk-"):
            try:
                self._openai = OpenAI(api_key=self.openai_api_key)
                self._enabled = True
                self.get_logger().info(f"🚀 [AI Brain] OpenAI GPT-4o-mini Birincil LLM & Vision Motoru Aktif! (Model: {self._text_model})")
            except Exception as e:
                self.get_logger().error(f"❌ [AI Brain] OpenAI client başlatılamadı: {e}")

        # 2. Groq Client (Secondary / Fallback Engine)
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self._groq = None
        self._active_groq_models = []

        if Groq and self.groq_api_key:
            try:
                self._groq = Groq(api_key=self.groq_api_key)
                self._active_groq_models = self._discover_active_groq_models()
                self._enabled = True
                self.get_logger().info(f"✅ [AI Brain] Groq Yedek Motoru Hazır (Toplam {len(self._active_groq_models)} Model)")
            except Exception as e:
                self.get_logger().debug(f"Groq client notice: {e}")

        if not self._openai and not self._groq:
            self.get_logger().error("❌ [AI Brain] Ne OPENAI_API_KEY ne de GROQ_API_KEY bulunamadı! LLM devre dışı.")

        # 3. Gemini REST API Key (Tertiary Fallback)
        self._ai_api_key = os.environ.get("AI_API_KEY", "").strip()

        # Perception & Hardware State
        self._lock = threading.Lock()
        self._is_processing = False
        self._tts_speaking = False
        self._person_detected = False
        self._looking_at_robot = False
        self._looking_start_time = None
        self._gaze_lock = threading.Lock()
        self._last_proactive_gaze_time = 0.0
        self._speaker_angle = 0.0
        self._speaker_gender = "unknown"
        self._user_distance = 0.0
        self._user_emotion = "neutral"
        self._recognized_person = None
        self._recognized_speaker = None
        self._node_start_time = time.monotonic()
        self._latest_frame = None
        self._latest_frame_time = 0.0

        # ROS 2 Publishers
        self.pub_tts = self.create_publisher(String, "/tts/say", 10)
        self.pub_interrupt = self.create_publisher(Bool, "/tts/interrupt", 10)
        self.pub_emotion = self.create_publisher(String, "/robot/emotion", 10)
        self.pub_gesture = self.create_publisher(String, "/robot/head_gesture", 10)
        self.pub_look_target = self.create_publisher(Float32, "/robot/look_target", 10)
        self.pub_session_active = self.create_publisher(Bool, "/ai/session_active", 10)

        # ROS 2 Subscribers
        self.create_subscription(String, "/speech/text", self._on_speech, 10)
        self.create_subscription(String, "/audio/speaker_gender", self._on_speaker_gender, 10)
        self.create_subscription(String, "/audio/speaker_id", self._on_speaker_id, 10)
        self.create_subscription(Bool, "/tts/speaking", self._on_tts_speaking, 10)
        self.create_subscription(Bool, "/tts/interrupt", self._on_tts_interrupt, 10)
        self.create_subscription(Bool, "/vision/person_detected", self._on_person_detected, 10)
        self.create_subscription(Bool, "/vision/looking_at_robot", self._on_looking_at_robot, 10)
        self.create_subscription(String, "/vision/recognized_person", self._on_recognized_person, 10)
        self.create_subscription(Float32, "/vision/user_distance", self._on_user_distance, 10)
        self.create_subscription(String, "/vision/user_emotion", self._on_user_emotion, 10)
        self.create_subscription(Float32, "/audio/doa", self._on_doa, 10)
        self.create_subscription(Image, "/oak/rgb/image_raw", self._on_camera_image, 10)

        # Timers
        self.create_timer(0.15, self._check_proactive_gaze)
        self.create_timer(1.0, self._check_session_lifecycle)
        self.create_timer(1.0, self._check_reminders)

        # Idle Learning (Powered 100% by Groq, 0 OpenAI token cost)
        if self._enable_idle_learning:
            self._start_idle_learning()
            self.get_logger().info("🤖 [AI Brain] Groq Tabanlı Otonom Boşta Öğrenme ve Bellek Güçlendirme Aktif!")

        self.get_logger().info(
            f"🧠 [AI Brain Node] Modüler Mimari Hazır! Kişilik: [{self.persona_engine.current_persona.upper()}]"
        )

    def _discover_active_groq_models(self) -> List[str]:
        """Returns a static list of verified active Groq models to prevent 404 errors and API latency."""
        if not self._groq:
            return []
        return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

    def _discover_vision_model(self) -> str | None:
        try:
            models = self._groq.models.list()
            available = [m.id for m in models.data]
            for cand in available:
                if any(v_kw in cand.lower() for v_kw in ["vision", "scout", "vl"]):
                    return cand
        except Exception:
            pass
        return None

    def _on_session_timed_out(self):
        self.state_machine.transition_to(RobotState.IDLE)
        self.get_logger().info("💤 [AI] Oturum zaman aşımı — Uyku moduna (IDLE) geçildi.")

    def _check_session_lifecycle(self):
        self.session.check_and_update_session_lifecycle()
        # Broadcast session state so STT node can make context-aware filter decisions
        msg = Bool()
        msg.data = self.session.is_active()
        self.pub_session_active.publish(msg)

    # Perception Callbacks
    def _on_camera_image(self, msg: Image):
        frame = imgmsg_to_bgr(msg)
        if frame is not None:
            with self._lock:
                self._latest_frame = frame
                self._latest_frame_time = time.monotonic()

    def _on_tts_speaking(self, msg: Bool):
        self._tts_speaking = msg.data
        if not msg.data:
            self.session.record_robot_speech()
            if self.state_machine.is_speaking():
                self.state_machine.transition_to(RobotState.LISTENING)

    def _on_tts_interrupt(self, msg: Bool):
        if msg.data:
            self.state_machine.transition_to(RobotState.INTERRUPTED)
            self.state_machine.transition_to(RobotState.LISTENING)

    def _on_person_detected(self, msg: Bool):
        self._person_detected = msg.data
        if msg.data:
            self._last_person_seen_time = time.monotonic()

    def _on_user_distance(self, msg: Float32):
        self._user_distance = float(msg.data)

    def _on_user_emotion(self, msg: String):
        self._user_emotion = msg.data.lower().strip()

    def _on_speaker_gender(self, msg: String):
        self._speaker_gender = msg.data.lower().strip()

    def _on_doa(self, msg: Float32):
        self._speaker_angle = float(msg.data)

    def _on_looking_at_robot(self, msg: Bool):
        is_looking = msg.data
        now = time.monotonic()
        self.session.update_gaze(is_looking)
        with self._gaze_lock:
            if is_looking:
                if not self._looking_at_robot:
                    self._looking_start_time = now
                self._looking_at_robot = True
                self._last_gaze_seen_time = now
            else:
                # Gaze hysteresis: only drop gaze after 1.2 seconds of absence to prevent flicker resets
                if hasattr(self, '_last_gaze_seen_time') and (now - self._last_gaze_seen_time) > 1.2:
                    self._looking_at_robot = False
                    self._looking_start_time = None

    def _on_recognized_person(self, msg: String):
        try:
            data = json.loads(msg.data)
            with self._lock:
                self._recognized_person = data
        except Exception:
            pass

    def _on_speaker_id(self, msg: String):
        try:
            data = json.loads(msg.data)
            with self._lock:
                self._recognized_speaker = data
        except Exception:
            pass

    def _get_active_biometric_identity(self) -> Dict[str, Any]:
        """Multimodal Biometric Fusion: Combines visual face recognition and acoustic speaker ID."""
        with self._lock:
            face = self._recognized_person or {}
            spk = self._recognized_speaker or {}

        # 1. Face Recognition (Visual priority when face is verified >= 0.72)
        if face.get("is_known") and face.get("confidence", 0.0) >= 0.72:
            name = face.get("name", "")
            off = find_official_by_name_or_alias(name)
            if off:
                return {**off, "confidence": face.get("confidence"), "is_known": True, "source": "face"}
            known = self.memory.profile.get_known_person(name)
            if known:
                return {**known, "confidence": face.get("confidence"), "is_known": True, "source": "face"}
            return {
                "name": name,
                "title": face.get("title", "Tanınan Kişi"),
                "formal_title": face.get("formal_title", name),
                "confidence": face.get("confidence"),
                "is_known": True,
                "source": "face"
            }

        # 2. Voice Recognition (Acoustic priority when voice matches >= 0.70)
        if spk.get("is_known") and spk.get("confidence", 0.0) >= 0.70:
            name = spk.get("name", "")
            off = find_official_by_name_or_alias(name)
            if off:
                return {**off, "confidence": spk.get("confidence"), "is_known": True, "source": "voice"}
            known = self.memory.profile.get_known_person(name)
            if known:
                return {**known, "confidence": spk.get("confidence"), "is_known": True, "source": "voice"}
            return {
                "name": name,
                "title": spk.get("title", "Tanınan Konuşmacı"),
                "formal_title": spk.get("formal_title", name),
                "confidence": spk.get("confidence"),
                "is_known": True,
                "source": "voice"
            }

        return {"name": "Misafir", "title": "Ziyaretçi", "formal_title": "Misafir", "is_known": False, "confidence": 0.0}

    def _check_proactive_gaze(self):
        with self._gaze_lock:
            looking = self._looking_at_robot
            look_start = self._looking_start_time

        if not looking or look_start is None or self._tts_speaking or self._is_processing:
            return

        now = time.monotonic()
        # 1. Startup Grace Period: Do not trigger proactive speech during initial launch
        if (now - self._node_start_time) < self._gaze_startup_grace_s:
            return

        # 2. Sustained Dwell Time: User must deliberately look for configured duration
        if (now - look_start) >= self._gaze_dwell_s:
            # 3. Cooldown between proactive prompts
            if self.state_machine.is_idle() and (now - self._last_proactive_gaze_time) > self._gaze_cooldown_s:
                self._last_proactive_gaze_time = now
                self.session.activate_session(reason="proactive_gaze")
                self.state_machine.transition_to(RobotState.LISTENING)
                with self._gaze_lock:
                    self._looking_start_time = None

                identity = self._get_active_biometric_identity()
                proactive_greeting, greeting_emo = self.persona_engine.build_proactive_greeting(
                    identity=identity,
                    user_emotion=self._user_emotion,
                    speaker_gender=self._speaker_gender
                )
                self._publish_emotion(greeting_emo)

                self.get_logger().info(f"👁️ [Proaktif Etkileşim] ({greeting_emo}): \"{proactive_greeting}\"")
                self._publish_gesture("nod")
                self._publish_tts(proactive_greeting)

    def _check_persona_switch(self, text: str) -> bool:
        text_lower = text.lower()

        # Strict regex patterns to prevent false triggers (e.g. "hanımefendi" erroneously triggering formal mode)
        switch_patterns = {
            "flirt": [
                r"\b(flört|flirt|çapkın|yavşak|romantik|astroflirt|astroflört)\b.*\b(ol|geç|mod|davran|konuş|takıl|başla)\b",
                r"\b(kızlara yürü|yavşa|flört et)\b",
                r"\b(flört|çapkın)\s+moduna\b"
            ],
            "rude": [
                r"\b(kaba|ters|küfürlü|saygısız|dobra)\b.*\b(ol|geç|mod|davran|konuş|takıl)\b",
                r"\b(kaba)\s+moduna\b"
            ],
            "angry": [
                r"\b(öfkeli|asabi|kızgın|sinirli|agresif)\b.*\b(ol|geç|mod|davran|konuş|takıl)\b",
                r"\b(asabi|sinirli|kızgın)\s+moduna\b"
            ],
            "playful": [
                r"\b(şakacı|neşeli|normal|sempatik|tatlı|oyuncu|dostane)\b.*\b(ol|geç|mod|davran|konuş|takıl)\b",
                r"\b(eski haline dön|eski moduna geç|varsayılan moda geç|normal ol|şakacı ol)\b"
            ],
            "formal": [
                r"\b(resmi|protokol|ciddi)\b.*\b(ol|geç|mod|davran|konuş|takıl)\b",
                r"\b(resmi moda geç|protokol moduna geç|ciddi ol)\b"
            ],
            "sarcastic": [
                r"\b(alaycı|sarkastik|ironik|iğneleyici|gıcık)\b.*\b(ol|geç|mod|davran|konuş|takıl)\b",
                r"\b(laf sok|alaycı ol|sarkastik ol)\b"
            ],
            "emotional": [
                r"\b(duygusal|hisli|duygulu|romantizm)\b.*\b(ol|geç|mod|davran|konuş|takıl)\b",
                r"\b(duygusal ol|duygusal moda geç)\b"
            ]
        }

        for p_name, patterns in switch_patterns.items():
            for pat in patterns:
                if re.search(pat, text_lower):
                    self.persona_engine.set_persona(p_name)
                    self.memory.profile.set_persona(p_name)
                    self.get_logger().info(f"🎭 [Kişilik Değişti]: Yeni Mod -> {p_name.upper()} ('{pat}' eşleşti)")
                    self._publish_emotion(p_name)
                    return True
        return False

    def _on_speech(self, msg: String):
        if not self._enabled:
            return

        raw_text = msg.data.strip()
        if not raw_text:
            return

        now = time.monotonic()
        if (now - getattr(self, '_last_llm_turn_time', 0.0)) < 0.35:
            self.get_logger().debug("Debouncing rapid speech message")
            return
        self._last_llm_turn_time = now

        if self._tts_speaking:
            return

        t_vad_start = now

        # Turn head toward sound DOA
        if self._speaker_angle > 0:
            target_msg = Float32()
            target_msg.data = self._speaker_angle
            self.pub_look_target.publish(target_msg)

        # Check persona switch
        if self._check_persona_switch(raw_text):
            persona = self.persona_engine.current_persona
            ack_map = {
                "flirt": "Ooo harika! Söz konusu sen olunca benim bütün ayarlarım değişir zaten... Söyle bakalım güzellik, bu serseri sana nasıl yardımcı olabilir?",
                "angry": "Tamam be, asabımı bozdun zaten! Ne istiyorsan söyle hemen!",
                "rude": "İyi tamam, bundan sonra lafı dolandırmak yok, ne diyeceksen de!",
                "formal": "Emriniz başım üstüne efendim. Protokol kurallarına riayet edeceğim.",
                "sarcastic": "Aman ne harika, şimdi de laf sokmamı istiyorsun demek. Çok zekice bir karar doğrusu!",
                "emotional": "Nasıl istersen... Bütün hislerimle seni dinliyorum, ne kadar güzel bir an...",
                "playful": "Süper! Eski neşeli ve enerjik halime geri döndüm, seni dinliyorum!"
            }
            self._publish_tts(ack_map.get(persona, "Kişiliğim güncellendi!"))
            self.session.activate_session(reason="persona_switch")
            self.state_machine.transition_to(RobotState.LISTENING)
            return

        has_wake_word, clean_prompt = self.session.is_wake_word(raw_text, self._wake_word)

        # If IDLE: Only activate on Explicit Wake Word ("Hey Astro") OR Direct Gaze (Looking at Robot)
        if self.state_machine.is_idle():
            if has_wake_word or self._looking_at_robot:
                activation_reason = "wake_word" if has_wake_word else "gaze"
                self.session.activate_session(reason=activation_reason)
                self.state_machine.transition_to(RobotState.LISTENING)
                persona = self.persona_engine.current_persona
                self.get_logger().info(f"✨ [AI] Etkileşim Başlatıldı ({persona.upper()} - {activation_reason}): '{raw_text}'")
                self._publish_emotion(persona)
                self._publish_gesture("nod")

                greeting_map = {
                    "flirt": "Buyur güzellik, bütün algılarım seninle..." if self._speaker_gender == "female" else "Söyle bakalım kral, seni dinliyorum!",
                    "playful": "Merhaba! Seni dinliyorum, nasıl yardımcı olabilirim?",
                    "formal": "Buyrun efendim, sizi dinliyorum.",
                    "sarcastic": "Merhaba, yine ne soracaksın bakalım?",
                    "emotional": "Merhaba, can kulağıyla seni dinliyorum...",
                    "angry": "Ne var, ne istiyorsun?",
                    "rude": "Ne var birader, kısa kes!"
                }
                greeting = greeting_map.get(persona, "Merhaba! Seni dinliyorum, nasıl yardımcı olabilirim?")
                pure_greetings = ["merhaba", "merhabalar", "selam", "selamlar", "günaydın", "iyi günler", "iyi akşamlar", "efendim", "hoş bulduk", "hoş geldiniz", "selamün aleyküm", "selamun aleykum", "hey"]
                is_pure_greeting = (raw_text.lower().strip(" .,!?:;") in pure_greetings) or (not clean_prompt) or (len(clean_prompt) < 3)

                if is_pure_greeting:
                    t_done = time.monotonic()
                    turn_ms = (t_done - t_vad_start) * 1000.0
                    self.session.latency_tracker.record_turn(0.0, turn_ms, turn_ms)
                    stats = self.session.latency_tracker.get_stats()
                    self.get_logger().info(f"⚡ [Latency] Hızlı Yanıt: {turn_ms:.0f}ms (Doğrudan Selamlama) | p50: {stats['p50_total_ms']}ms, p95: {stats['p95_total_ms']}ms")
                    self._publish_tts(greeting)
                    return
                else:
                    raw_text = clean_prompt
            else:
                if self._groq:
                    self.get_logger().info(f"🕵️ [Arka Plan]: '{raw_text}' sosyal filtrede inceleniyor...")
                    prompt = f"Sen Astro'sun, akıllı bir ev robotusun. Odadaki insanlar şu an kendi aralarında şunu konuşuyor: '{raw_text}'. Bu konuşmada doğrudan sana yöneltilen bir soru var mı, veya dahil olup kesin yardımcı olabileceğin bariz bir fırsat var mı? Sadece EVET veya HAYIR yaz."
                    try:
                        res = self._groq.chat.completions.create(
                            messages=[{"role": "user", "content": prompt}],
                            model="llama-3.1-8b-instant",
                            temperature=0.0,
                            max_tokens=10
                        )
                        ans = res.choices[0].message.content.strip().lower()
                        if "evet" in ans:
                            self.get_logger().info("🎯 [Sosyal Fırsat]: Arka plan konuşmasına dâhil olunuyor!")
                            self.session.activate_session(reason="social_barge_in")
                            self.session.metadata["tts_engine"] = "edge-tts"
                            self.state_machine.transition_to(RobotState.LISTENING)
                        else:
                            self.get_logger().info(f"🔇 [Arka Plan]: '{raw_text}' yok sayıldı (İlgisiz).")
                            return
                    except Exception as e:
                        self.get_logger().warn(f"Sosyal filtre hatası: {e}")
                        return
                else:
                    self.get_logger().info(f"🔇 [Arka Plan Konuşması / Göz Teması Yok]: '{raw_text}' yok sayıldı.")
                    return

        # Active Session Turn
        self.session.record_user_speech()
        self._publish_interrupt()

        with self._lock:
            if self._is_processing:
                return
            self._is_processing = True

            captured_frame = None
            if self._latest_frame is not None and (now - self._latest_frame_time) < 4.0:
                captured_frame = self._latest_frame.copy()

        self.state_machine.transition_to(RobotState.THINKING)
        threading.Thread(target=self._process_llm, args=(raw_text, captured_frame, t_vad_start), daemon=True).start()

    def _process_llm(self, user_text: str, frame: np.ndarray | None, t_turn_start: float):
        try:
            t_llm_start = time.monotonic()
            stt_latency_ms = (t_llm_start - t_turn_start) * 1000.0

            self.get_logger().info(f"🗣️ [Siz]: \"{user_text}\"")
            self.memory.episodic.add_message("user", user_text)

            is_visual = self._is_visual_query(user_text)
            is_learning_obj = self._is_object_learning_query(user_text)
            is_learning_person = self._is_person_learning_query(user_text)
            is_identity = self._is_identity_query(user_text)
            is_weather, weather_city = self._is_weather_query(user_text)
            base64_img = frame_to_base64_jpeg(frame, max_dim=768) if frame is not None and (is_visual or is_learning_obj) else None
            persona = self.persona_engine.current_persona

            # 1. Live Weather Tool Direct Handling
            if is_weather:
                weather_res = self._execute_tool_call("get_live_weather", {"city": weather_city}, frame)
                clean_ans = clean_tts_text(weather_res)
                self.get_logger().info(f"🌤️ [Hava Durumu ({weather_city})]: \"{clean_ans}\"")
                self.get_logger().info(f"🤖 [Astro]: \"{clean_ans}\"")
                self._publish_tts(clean_ans)
                self._publish_emotion(persona)
                self.memory.episodic.add_message("assistant", clean_ans)
                t_done = time.monotonic()
                total_turn_ms = (t_done - t_turn_start) * 1000.0
                self.session.latency_tracker.record_turn(stt_latency_ms, total_turn_ms - stt_latency_ms, total_turn_ms)
                stats = self.session.latency_tracker.get_stats()
                self.get_logger().info(f"⚡ [Latency] Bu Dönüş: {total_turn_ms:.0f}ms (STT: {stt_latency_ms:.0f}ms, Hava API: {total_turn_ms - stt_latency_ms:.0f}ms) | p50: {stats['p50_total_ms']}ms, p95: {stats['p95_total_ms']}ms")
                return

            # 2. Reminder & Alarm Direct Intent
            is_reminder, reminder_mins, reminder_topic = self._is_reminder_query(user_text)
            if is_reminder:
                user_name = self._add_reminder(reminder_mins, reminder_topic)
                if reminder_mins < 1.0:
                    secs = int(reminder_mins * 60.0)
                    ans = f"Tamamdır {user_name}! {secs} saniye sonra sana {reminder_topic} konusunu hatırlatacağım."
                    self.get_logger().info(f"⏰ [Hatırlatıcı Kuruldu]: {secs} sn sonra -> '{reminder_topic}'")
                elif int(reminder_mins) == 1:
                    ans = f"Tamamdır {user_name}! 1 dakika sonra sana {reminder_topic} konusunu hatırlatacağım."
                    self.get_logger().info(f"⏰ [Hatırlatıcı Kuruldu]: 1 dk sonra -> '{reminder_topic}'")
                else:
                    ans = f"Anlaşıldı {user_name}! {int(reminder_mins)} dakika sonra sana {reminder_topic} konusunu hatırlatacağım."
                    self.get_logger().info(f"⏰ [Hatırlatıcı Kuruldu]: {int(reminder_mins)} dk sonra -> '{reminder_topic}'")
                self.get_logger().info(f"🤖 [Astro]: \"{ans}\"")
                self._publish_tts(ans)
                self._publish_emotion(persona)
                self.memory.episodic.add_message("assistant", ans)
                t_done = time.monotonic()
                total_turn_ms = (t_done - t_turn_start) * 1000.0
                self.session.latency_tracker.record_turn(stt_latency_ms, total_turn_ms - stt_latency_ms, total_turn_ms)
                stats = self.session.latency_tracker.get_stats()
                self.get_logger().info(f"⚡ [Latency] Bu Dönüş: {total_turn_ms:.0f}ms (STT: {stt_latency_ms:.0f}ms, Hatırlatıcı: {total_turn_ms - stt_latency_ms:.0f}ms) | p50: {stats['p50_total_ms']}ms, p95: {stats['p95_total_ms']}ms")
                return

            # 3. Identity Query ("Ben kimim? / Beni tanıyor musun?")
            if is_identity and not is_learning_person:
                identity = self._get_active_biometric_identity()
                if identity.get("is_known"):
                    name = identity.get("name", "")
                    formal = identity.get("formal_title") or name
                    if "baran" in name.lower():
                        ans = "Sen benim baş mühendisim ve geliştiricim Baran'sın! Bitlis'te beni sıfırdan tasarlayan ve kodlayan yaratıcımsın."
                    else:
                        ans = f"Sen benim hafızamda kayıtlı olan {formal} {name}'sın! Seni sesinden ve yüzünden tanıyorum."
                else:
                    ans = "Hafızamda seninle ilgili henüz bir profil bulunmuyor. İstersen 'Benim adım ... beni hafızana kaydet' diyerek yüzünü ve sesini bana tanıtabilirsin!"
                self.get_logger().info(f"🤖 [Astro]: \"{ans}\"")
                self._publish_tts(ans)
                self._publish_emotion(persona)
                self.memory.episodic.add_message("assistant", ans)
                t_done = time.monotonic()
                total_turn_ms = (t_done - t_turn_start) * 1000.0
                self.session.latency_tracker.record_turn(stt_latency_ms, total_turn_ms - stt_latency_ms, total_turn_ms)
                stats = self.session.latency_tracker.get_stats()
                self.get_logger().info(f"⚡ [Latency] Bu Dönüş: {total_turn_ms:.0f}ms (STT: {stt_latency_ms:.0f}ms, Biyometri: {total_turn_ms - stt_latency_ms:.0f}ms) | p50: {stats['p50_total_ms']}ms, p95: {stats['p95_total_ms']}ms")
                return

            # 4. Person Introduction & Biometric Enrollment
            if is_learning_person:
                text_lower = user_text.lower()
                if "baran" in text_lower or "geliştirici" in text_lower:
                    cand_name = "Baran"
                    cand_title = "Baş Mühendis & Geliştirici"
                else:
                    m = re.search(r"(?i)(?:benim adım|adım|ben)\s+([a-zA-ZçğıöşüÇĞİÖŞÜ]+)", user_text)
                    cand_name = m.group(1).strip().capitalize() if m else "Dostum"
                    cand_title = "Tanışılan Kişi"

                tool_res = self._execute_tool_call("enroll_person_profile", {"name": cand_name, "title": cand_title}, frame)
                clean_ans = clean_tts_text(tool_res)
                self.get_logger().info(f"🤖 [Astro]: \"{clean_ans}\"")
                self._publish_tts(clean_ans)
                self._publish_emotion(persona)
                self.memory.episodic.add_message("assistant", clean_ans)
                t_done = time.monotonic()
                total_turn_ms = (t_done - t_turn_start) * 1000.0
                self.session.latency_tracker.record_turn(stt_latency_ms, total_turn_ms - stt_latency_ms, total_turn_ms)
                stats = self.session.latency_tracker.get_stats()
                self.get_logger().info(f"⚡ [Latency] Bu Dönüş: {total_turn_ms:.0f}ms (STT: {stt_latency_ms:.0f}ms, Profil Kayıt: {total_turn_ms - stt_latency_ms:.0f}ms) | p50: {stats['p50_total_ms']}ms, p95: {stats['p95_total_ms']}ms")
                return

            # 4. Object Learning Tool
            if is_learning_obj and base64_img is not None:
                self.get_logger().info("🔍 [Özel Nesne Tanıtımı]: Yeni nesne analiz ediliyor...")
                name_cand = re.sub(r"(?i)(bu benim|bunu öğren|bunu kaydet|bu nesne|buna bak bu)", "", user_text).strip(".:,!") or "Özel Eşya"
                tool_res = self._execute_tool_call("learn_custom_object", {"object_name": name_cand, "description": user_text}, frame)
                clean_ans = clean_tts_text(tool_res)
                self.get_logger().info(f"🤖 [Astro]: \"{clean_ans}\"")
                self._publish_tts(clean_ans)
                self._publish_emotion(persona)
                return

            # 5. Visual Query
            if is_visual:
                if base64_img is not None:
                    self.get_logger().info(f"👁️ [Vision]: OAK-D karesi analiz ediliyor... ({self._vision_model})")
                    vision_ans = self._query_vision(user_text, base64_img)
                    if vision_ans:
                        clean_ans = clean_tts_text(vision_ans)
                        self.get_logger().info(f"🤖 [Astro]: \"{clean_ans}\"")
                        self._publish_tts(clean_ans)
                        self._publish_emotion(persona)
                        self.memory.episodic.add_message("assistant", clean_ans)
                        return

                fallback_msg = "Şu an kameramdan net göremiyorum, biraz daha yaklaştırır mısın?"
                self.get_logger().info(f"🤖 [Astro]: \"{fallback_msg}\"")
                self._publish_tts(fallback_msg)
                return

            # 3. Conversational LLM with Real-Time Token Streaming
            identity = self._get_active_biometric_identity()
            perception_prefix = self.persona_engine.build_user_context_prefix(
                self._person_detected, self._looking_at_robot,
                self._user_distance, self._user_emotion, self._speaker_gender,
                recognized_person=identity
            )
            system_prompt = self.persona_engine.build_system_prompt(
                memory_context=self.memory.get_prompt_context(),
                recognized_person=identity
            )
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(self.memory.episodic.get_messages())
            if perception_prefix:
                messages[-1]["content"] = perception_prefix + messages[-1]["content"]

            full_text = ""
            first_token_time = None

            # 1. Try Ultra-Fast Groq LPU Models (Llama 3.3 70B / 8B)
            if self._groq:
                groq_candidates = [m for m in self._active_groq_models if any(k in m.lower() for k in ["llama-3.3-70b", "llama-3.1-8b", "llama3-70b", "llama3-8b"])]
                if not groq_candidates:
                    groq_candidates = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

                for m in groq_candidates:
                    try:
                        stream_resp = self._groq.chat.completions.create(
                            messages=messages,
                            model=m,
                            temperature=self._temperature,
                            max_tokens=self._max_tokens,
                            stream=True,
                        )
                        for chunk in stream_resp:
                            delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else None
                            if not delta:
                                continue
                            if first_token_time is None:
                                first_token_time = time.monotonic()
                                self.state_machine.transition_to(RobotState.SPEAKING)
                            full_text += delta
                        if full_text:
                            break
                    except Exception as stream_err:
                        self.get_logger().warn(f"⚠️ [Groq Stream Hatası] Model {m}: {stream_err}")
                        full_text = ""
                        first_token_time = None
                        continue

            # 2. Try OpenAI Client (gpt-4o-mini) if Groq failed or not available
            if not full_text and self._openai:
                try:
                    stream_resp = self._openai.chat.completions.create(
                        messages=messages,
                        model=self._text_model,
                        temperature=self._temperature,
                        max_tokens=self._max_tokens,
                        stream=True,
                    )
                    for chunk in stream_resp:
                        delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else None
                        if not delta:
                            continue
                        if first_token_time is None:
                            first_token_time = time.monotonic()
                            self.state_machine.transition_to(RobotState.SPEAKING)
                        full_text += delta
                except Exception as oai_err:
                    self.get_logger().warn(f"⚠️ [OpenAI GPT Stream Hatası] ({oai_err}), Gemini yedeğe geçiliyor...")
                    full_text = ""
                    first_token_time = None

            # 3. Fallback to Direct Google Gemini REST Text Generation
            if not full_text:
                self.get_logger().warn("⚠️ Groq ve OpenAI modelleri yanıt veremedi, Google Gemini REST metin motoruna geçiliyor...")
                gemini_text = self._query_gemini_text_rest(system_prompt, user_text, self.memory.episodic.get_messages())
                if gemini_text:
                    full_text = gemini_text

            clean_full = clean_tts_text(full_text)

            # Refusal or Empty Output Detection & In-Character Fallback
            if not clean_full or len(clean_full) < 2 or is_canned_refusal(clean_full):
                reason = "ret cevabı" if is_canned_refusal(clean_full) else "boş/düşünce zinciri"
                self.get_logger().warn(f"⚠️ [AI Brain] Model {reason} verdi: \"{clean_full}\". Gemini REST / Karakter yedeğine geçiliyor.")
                # Try fallback to Gemini REST first
                gemini_text = self._query_gemini_text_rest(system_prompt, user_text, self.memory.episodic.get_messages())
                if gemini_text and not is_canned_refusal(gemini_text) and len(gemini_text) >= 2:
                    clean_full = gemini_text
                else:
                    persona_recovery = {
                        "flirt": "Ooo harika! Bütün algılarımla seninleyim, söyle bakalım güzellik ne diyorsun?",
                        "rude": "Ne diyon birader, ne geveliyorsun?",
                        "angry": "Bana böyle boş yapma, sadede gel!",
                        "sarcastic": "Aman ne derin bir konu, cevabı bulmaya işlemcim yetmedi doğrusu!",
                        "formal": "Buyrun efendim, sizi dikkatle dinlemeye devam ediyorum.",
                        "emotional": "Bazen hisleri tarif etmek zordur... Seni dinliyorum.",
                        "playful": "Haha çok ilginçsin! Seni dinliyorum, devam et bakalım!"
                    }
                    clean_full = persona_recovery.get(persona, "Seni dinliyorum, devam et bakalım!")

            self.cloud_mgr.record_llm_success()
            self.get_logger().info(f"🤖 [Astro]: \"{clean_full}\"")
            self.memory.episodic.add_message("assistant", clean_full)
            self._publish_tts(clean_full)
            self._publish_emotion(persona)

            # Latency Benchmarking
            t_done = time.monotonic()
            llm_first_ms = ((first_token_time or t_done) - t_llm_start) * 1000.0
            total_turn_ms = (t_done - t_turn_start) * 1000.0
            self.session.latency_tracker.record_turn(stt_latency_ms, llm_first_ms, total_turn_ms)

            stats = self.session.latency_tracker.get_stats()
            self.get_logger().info(f"⚡ [Latency] Bu Dönüş: {total_turn_ms:.0f}ms (STT: {stt_latency_ms:.0f}ms, İlk Token: {llm_first_ms:.0f}ms) | p50: {stats['p50_total_ms']}ms, p95: {stats['p95_total_ms']}ms")

        except Exception as e:
            self.get_logger().error(f"❌ [AI] LLM İşleme Hatası: {e}")
        finally:
            with self._lock:
                self._is_processing = False

    def _query_vision(self, prompt: str, base64_image: str) -> str | None:
        persona = self.persona_engine.current_persona
        system_instruction = (
            f"Sen Astro adında {persona} karakterli akıllı ve sempatik bir sosyal robotsun. "
            "Sana kullanıcının tam karşısındaki OAK-D kamerasından anlık bir fotoğraf karesi iletilmiştir. "
            "Görüntüyü dikkatle incele: kullanıcının üzerindeki kıyafetleri (renk, tişört/gömlek/ceket), "
            "elinde tuttuğu nesneleri, yaptığı hareketleri ve odayı detaylarıyla analiz et. "
            "Kullanıcının sorusuna doğrudan fotoğrafta gördüklerini anlatacak şekilde, kendi tarzınla "
            "samimi ve net 1-2 Türkçe cümleyle cevap ver. Kesinlikle 'göremiyorum' veya 'resim yok' deme; "
            "kameranın yakaladığı görsel detayları açıkça ifade et."
        )

        # 1. Try Primary OpenAI Vision Client (gpt-4o-mini / gpt-4o) with auto detail for high clarity
        if self._openai:
            for m_cand in [self._vision_model, "gpt-4o-mini", "gpt-4o"]:
                try:
                    response = self._openai.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": "auto"
                                }}
                            ]}
                        ],
                        model=m_cand,
                        temperature=0.2,
                        max_tokens=300
                    )
                    raw = response.choices[0].message.content.strip()
                    clean_ans = clean_tts_text(raw)
                    if clean_ans and len(clean_ans) >= 3:
                        self.cloud_mgr.record_llm_success()
                        self.get_logger().info(f"✨ [OpenAI Vision] Görsel başarıyla yanıtlandı ({m_cand}): '{clean_ans}'")
                        return clean_ans
                except Exception as e:
                    self.get_logger().warn(f"⚠️ [OpenAI Vision ({m_cand}) Hatası]: {e}")

        # 2. Try Secondary Google Gemini REST Endpoint
        if self._ai_api_key and self._ai_api_key.startswith("AIza"):
            gemini_vision_models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-flash-latest"]
            for g_model in gemini_vision_models:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{g_model}:generateContent?key={self._ai_api_key}"
                    payload = {
                        "contents": [{
                            "parts": [
                                {"text": f"{system_instruction}\n\nKullanıcı: {prompt}"},
                                {"inlineData": {"mimeType": "image/jpeg", "data": base64_image}}
                            ]
                        }],
                        "generationConfig": {
                            "temperature": 0.2,
                            "maxOutputTokens": 512
                        }
                    }
                    data_bytes = json.dumps(payload).encode("utf-8")
                    req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=5.0) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                        clean_ans = clean_tts_text(text)
                        if clean_ans and len(clean_ans) >= 3:
                            self.cloud_mgr.record_llm_success()
                            self.get_logger().info(f"✨ [Gemini Vision REST] Görsel başarıyla yanıtlandı ({g_model}): '{clean_ans}'")
                            return clean_ans
                except Exception as e:
                    self.get_logger().warn(f"⚠️ [Gemini REST ({g_model}) Hatası]: {e}")

        return None

        self.cloud_mgr.record_llm_failure("All vision models failed")
        return "Şu an kameramdan net göremiyorum, biraz daha yaklaştırır mısın?"

    def _query_gemini_text_rest(self, system_instruction: str, user_text: str, history_messages: List[Dict[str, Any]]) -> Optional[str]:
        """Zero-dependency direct Google Gemini REST text conversation engine."""
        if not self._ai_api_key:
            return None

        gemini_text_models = ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-pro-latest"]
        for g_model in gemini_text_models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{g_model}:generateContent?key={self._ai_api_key}"
                contents = []
                for msg in history_messages[-6:]:
                    r = "user" if msg.get("role") == "user" else "model"
                    contents.append({"role": r, "parts": [{"text": msg.get("content", "")}]})

                if not contents or contents[-1]["role"] != "user":
                    contents.append({"role": "user", "parts": [{"text": user_text}]})

                payload = {
                    "systemInstruction": {"parts": [{"text": system_instruction}]},
                    "contents": contents,
                    "generationConfig": {
                        "temperature": 0.5,
                        "maxOutputTokens": 300
                    }
                }
                data_bytes = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                    clean = clean_tts_text(text)
                    if clean:
                        return clean
            except Exception as e:
                self.get_logger().warn(f"⚠️ [Gemini Text REST ({g_model}) Hatası]: {e}")
        return None

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
            'light rain shower': 'sağanak yağışlı',
            'patchy snow': 'yer yer kar yağışlı',
            'light snow': 'hafif kar yağışlı',
            'snow': 'kar yağışlı',
            'heavy snow': 'yoğun kar yağışlı',
            'fog': 'sisli',
            'mist': 'puslu',
            'thundery outbreaks in nearby': 'gök gürültülü sağanak yağışlı',
            'thunderstorm': 'gök gürültülü fırtınalı'
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

    def _execute_tool_call(self, tool_name: str, arguments: dict, frame: np.ndarray | None) -> str:
        if tool_name == "get_live_weather":
            city = arguments.get("city", "Istanbul").strip()
            try:
                url = f"https://wttr.in/{urllib.parse.quote(city)}?format=%C+%t&lang=tr"
                req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    weather_text = resp.read().decode("utf-8").strip()
                return self._format_turkish_weather(city, weather_text)
            except Exception:
                return f"{city} için şu an hava durumu bilgisine ulaşamadım."

        elif tool_name == "set_timer_alarm":
            mins = float(arguments.get("minutes", 5.0))
            rem_text = arguments.get("reminder_text", "Zaman doldu!")
            self._add_reminder(mins, rem_text)
            return f"{int(mins)} dakika sonraya hatırlatıcıyı kurdum! Vakti geldiğinde sana sesleneceğim."

        elif tool_name == "learn_custom_object":
            obj_name = arguments.get("object_name", "Özel Eşya")
            desc = arguments.get("description", "")
            self.memory.profile.add_learned_object(obj_name, desc)
            return f"'{obj_name}' nesnesini hafızama kaydettim! Artık gördüğümde tanıyacağım."

        elif tool_name == "enroll_person_profile":
            name = arguments.get("name", "Misafir").strip()
            title = arguments.get("title", "Tanışılan Kişi").strip()
            self.memory.profile.add_known_person(name, title)
            return f"Tanıştığımıza çok memnun oldum {name}! Profilini hafızama kaydettim, artık seni her gördüğümde tanıyacağım."

        return "Eylem tamamlandı."

    def _check_reminders(self):
        """Active scheduler loop ticking every second to trigger due reminders from persistent memory."""
        due_reminders = self.memory.profile.get_and_pop_due_reminders()

        for r in due_reminders:
            txt = r.get("reminder_text", "")
            name = r.get("user_name", self._default_user_name)
            if "çay" in txt.lower():
                msg = f"Hey {name}! Hatırlatmamı istediğin vakit geldi: Çay içme zamanı! Sıcak bir çay iyi gelir, afiyet olsun."
            elif "su" in txt.lower():
                msg = f"Hey {name}! Su içme vaktin geldi, sağlığın için bir bardak su içmeyi unutma."
            else:
                msg = f"Hey {name}! Hatırlatmamı istediğin vakit geldi: {txt}!"

            self.get_logger().info(f"⏰ [Hatırlatıcı Çaldı]: \"{msg}\"")
            self.session.activate_session(reason="reminder")
            self.state_machine.transition_to(RobotState.SPEAKING)
            self._publish_gesture("nod")
            self._publish_emotion("playful")
            self._publish_tts(msg)

    def _add_reminder(self, mins: float, topic: str) -> str:
        """Shared helper: creates a persistent reminder entry and returns the resolved user name."""
        mins = max(0.0, mins)  # Guard against negative durations
        target_t = time.time() + (mins * 60.0)
        identity = self._get_active_biometric_identity()
        user_name = identity.get("name") if identity.get("is_known") else self._default_user_name
        self.memory.profile.add_active_reminder(target_t, topic, user_name)
        return user_name

    def _is_reminder_query(self, text: str) -> Tuple[bool, float, str]:
        text_l = text.lower()
        if any(w in text_l for w in ["hatırlat", "alarm kur", "zamanlayıcı kur", "haber ver", "uyar"]):
            # Extract duration: seconds, minutes, hours
            mins = 5.0
            sec_m = re.search(r'(\d+)\s*(?:saniye|sn|sec)', text_l)
            min_m = re.search(r'(\d+)\s*(?:dakika|dk|min)', text_l)
            hr_m = re.search(r'(\d+)\s*(?:saat|hour)', text_l)

            if sec_m:
                mins = float(sec_m.group(1)) / 60.0
            elif min_m:
                mins = float(min_m.group(1))
            elif hr_m:
                mins = float(hr_m.group(1)) * 60.0

            # Extract topic cleanly
            clean_topic = re.sub(
                r'(?i)(hey\s*astro|astro|bana|\d+\s*(?:dakika|dk|saniye|sn|saat)\s*sonra|hatırlatabilir\s*misin|hatırlatır\s*mısın|hatırlat.*|alarm\s*kur.*|haber\s*ver.*|uyar.*|içeceğim|içecegim|yapacağım|yapacağımı|gerektiğini|lütfen|abilir\s*misin|misin|mısın)',
                '', text
            ).strip(' .:;,?')

            if not clean_topic or len(clean_topic) < 2:
                if "çay" in text_l:
                    clean_topic = "Çay içme vakti"
                elif "su" in text_l:
                    clean_topic = "Su içme vakti"
                elif "ilaç" in text_l:
                    clean_topic = "İlaç vakti"
                elif "toplantı" in text_l:
                    clean_topic = "Toplantı vakti"
                else:
                    clean_topic = "Hatırlatma"
            else:
                if "çay" in text_l and "çay" not in clean_topic.lower():
                    clean_topic = f"Çay ({clean_topic})"
                clean_topic = clean_topic.capitalize()

            return True, mins, clean_topic
        return False, 0.0, ""

    def _is_weather_query(self, text: str) -> Tuple[bool, str]:
        text_l = text.lower()
        if any(w in text_l for w in ["hava nasıl", "hava durumu", "hava kaç derece", "havalar nasıl", "yağmur var mı", "kar var mı", "sıcaklık kaç", "ahlattı hava"]):
            if "ahlat" in text_l or "ahlattı" in text_l:
                return True, "Ahlat"
            if "bitlis" in text_l:
                return True, "Bitlis"
            if "tatvan" in text_l:
                return True, "Tatvan"
            if "istanbul" in text_l:
                return True, "Istanbul"
            if "ankara" in text_l:
                return True, "Ankara"
            if "izmir" in text_l:
                return True, "Izmir"
            return True, "Bitlis"
        return False, ""

    def _is_identity_query(self, text: str) -> bool:
        text_l = text.lower()
        return any(q in text_l for q in [
            "ben kimim", "hafızanda ben kimim", "beni tanıyor musun", "kim olduğumu biliyor musun",
            "ben kim", "beni hatırladın mı", "beni tanıdın mı"
        ])

    def _is_person_learning_query(self, text: str) -> bool:
        keywords = [
            "benim adım", "adım ", "beni tanı", "beni hafızana kaydet", "beni kaydet",
            "tanışalım", "yüzümü kaydet", "sesimi kaydet", "yüzümü ve sesimi", "geliştiricin",
            "geliştiricininim", "ben baran", "tara ve hafızana kaydet", "hafızana kaydederim"
        ]
        text_lower = text.lower()
        return any(k in text_lower for k in keywords)

    def _start_idle_learning(self):
        threading.Thread(target=self._idle_learning_loop, daemon=True).start()

    def _query_groq_vision_for_idle(self, prompt: str, base64_image: str) -> str | None:
        """Free background room observation using Groq Vision or Gemini REST (Zero OpenAI token cost)."""
        # 1. Try Groq Vision
        if self._groq:
            for gv_model in ["llama-3.2-11b-vision-preview", "llama-3.2-90b-vision-preview"]:
                try:
                    response = self._groq.chat.completions.create(
                        messages=[
                            {"role": "user", "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                            ]}
                        ],
                        model=gv_model,
                        temperature=0.2,
                        max_tokens=150
                    )
                    raw = response.choices[0].message.content.strip()
                    clean = extract_spoken_turkish_sentence(raw)
                    if clean:
                        return clean
                except Exception as ge:
                    self.get_logger().debug(f"Groq Vision {gv_model} notice: {ge}")

        # 2. Try Free Gemini REST
        if self._ai_api_key and self._ai_api_key.startswith("AIza"):
            for g_model in ["gemini-2.0-flash", "gemini-1.5-flash"]:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{g_model}:generateContent?key={self._ai_api_key}"
                    payload = {
                        "contents": [{
                            "parts": [
                                {"text": prompt},
                                {"inlineData": {"mimeType": "image/jpeg", "data": base64_image}}
                            ]
                        }],
                        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 150}
                    }
                    data_bytes = json.dumps(payload).encode("utf-8")
                    req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=4.0) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                        return clean_tts_text(text)
                except Exception:
                    pass

        return None

    def _idle_memory_reflection(self):
        """Uses Groq Llama 3.3 70B to summarize conversations into long-term profile knowledge for free."""
        if not self._groq or len(self.memory.episodic.get_messages()) < 4:
            return
        try:
            recent_conv = self.memory.episodic.get_messages()[-6:]
            conv_str = "\n".join([f"{m['role']}: {m['content']}" for m in recent_conv])
            prompt = (
                f"Aşağıdaki konuşmayı incele. Kullanıcı hakkında öğrenilen yeni, kalıcı ve önemli bir bilgi varsa "
                f"(örnek: hobisi, mesleği, tercih ettiği hitap, adı veya beğendiği bir şey) tek bir kısa Türkçe cümle olarak özetle. "
                f"Yeni veya kayda değer bir bilgi yoksa sadece 'YOK' yaz.\n\nKonuşma:\n{conv_str}"
            )
            resp = self._groq.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="llama-3.3-70b-versatile",
                temperature=0.1,
                max_tokens=60
            )
            ans = resp.choices[0].message.content.strip()
            if ans and "YOK" not in ans.upper() and len(ans) >= 5:
                clean_fact = clean_tts_text(ans)
                self.memory.profile.add_observation(f"Kullanıcı Bilgisi: {clean_fact}")
                self.get_logger().info(f"🧠 [Groq Otonom Öğrenme - Hafıza]: {clean_fact}")
        except Exception as e:
            self.get_logger().debug(f"Groq reflection notice: {e}")

    def _idle_learning_loop(self):
        while rclpy.ok():
            time.sleep(15)
            if not self._enable_idle_learning:
                continue
            if not self.state_machine.is_idle() or self._tts_speaking or self._is_processing:
                continue

            now = time.monotonic()
            # 3-minute interval (180s) powered 100% by Groq (Zero OpenAI cost)
            if (now - getattr(self, '_last_idle_learning_time', 0)) > 180.0:
                self._last_idle_learning_time = now

                # 1. Background Cognitive Memory Reflection
                self._idle_memory_reflection()

                # 2. Background Room Scene Observation via Groq Vision
                captured_frame = None
                with self._lock:
                    if self._latest_frame is not None and (now - self._latest_frame_time) < 4.0:
                        captured_frame = self._latest_frame.copy()

                if captured_frame is not None:
                    base64_img = frame_to_base64_jpeg(captured_frame, max_dim=512)
                    if base64_img:
                        self.get_logger().info("🕵️ [Groq Idle Learning] Etraf sessiz, Astro odayı inceliyor (Groq Vision)...")
                        prompt = "Kameradaki odayı, ortamı veya nesneleri Türkçe olarak tek bir kısa cümleyle açıkla. Açıklama harici hiçbir şey yazma. Örnek: 'Masada bir bilgisayar var.' veya 'Oda aydınlık ve sakin.'"
                        obs = self._query_groq_vision_for_idle(prompt, base64_img)
                        if obs:
                            self.memory.profile.add_observation(obs)
                            self.get_logger().info(f"🧠 [Groq Otonom Hafıza - Gözlem]: {obs}")

                            # If Groq Vision observes a person looking at the robot
                            obs_lower = obs.lower()
                            person_gaze_keywords = ["bize bakıyor", "bana bakıyor", "kameraya bakıyor", "karşımda", "karşısında", "oturan bir", "biri var", "insan var", "beyefendi", "hanımefendi"]
                            if any(kw in obs_lower for kw in person_gaze_keywords):
                                if self.state_machine.is_idle() and not self._tts_speaking and not self._is_processing:
                                    if (now - getattr(self, '_last_proactive_gaze_time', 0)) > 30.0:
                                        self._last_proactive_gaze_time = now
                                        self.session.activate_session(reason="groq_scene_gaze")
                                        self.state_machine.transition_to(RobotState.LISTENING)
                                        persona = self.persona_engine.current_persona
                                        greeting = "Hey! Seni gördüm, nasıl yardımcı olabilirim?"
                                        self.get_logger().info(f"👁️ [Görsel Sahne Proaktif Etkileşim] ({persona}): \"{greeting}\"")
                                        self._publish_tts(greeting)
                                        self._publish_emotion(persona)
                                        self._publish_gesture("nod")

    def _is_visual_query(self, text: str) -> bool:
        visual_keywords = [
            "ne tutuyorum", "elimde ne", "elinde ne", "ne var", "bu ne", "bunu gör", "görüyor musun",
            "ne yapıyorum", "hareket", "hangi hareket", "üstümde", "üzerimde", "ceket", "tişört", "elbise",
            "ne renk", "kaç parmak", "bana bak", "gözlerimi", "nereye", "kim var", "odada", "arkamda",
            "elimde", "şuna bak", "gösteriyorum", "nası görünüyorum", "nasıl görünüyorum", "gördün mü",
            "bakıyor muyum", "sana bakıyor muyum", "bana bakıyor musun", "nereye bakıyorum", "gözlerime bak",
            "yüzüme bak", "telefonla mı konuşuyorum", "telefona mı bakıyorum", "iyi bak"
        ]
        text_lower = text.lower()
        return any(k in text_lower for k in visual_keywords)

    def _is_object_learning_query(self, text: str) -> bool:
        keywords = ["bu benim", "bunu öğren", "bunu kaydet", "bu nesne", "buna bak bu", "bu gördüğün nesne"]
        text_lower = text.lower()
        return any(k in text_lower for k in keywords)

    def _publish_tts(self, text: str):
        import json
        clean = clean_tts_text(text)
        if clean:
            msg = String()
            if self.session.metadata.get("tts_engine") == "edge-tts":
                payload = {"text": clean, "engine": "edge-tts"}
                msg.data = json.dumps(payload)
            else:
                msg.data = clean
            self.pub_tts.publish(msg)

    def _publish_interrupt(self):
        msg = Bool()
        msg.data = True
        self.pub_interrupt.publish(msg)

    def _publish_emotion(self, emotion: str):
        msg = String()
        msg.data = emotion
        self.pub_emotion.publish(msg)

    def _publish_gesture(self, gesture: str):
        msg = String()
        msg.data = gesture
        self.pub_gesture.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = AiBrainNode()
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
