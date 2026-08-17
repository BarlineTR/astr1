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
        os.path.abspath(os.path.join(os.getcwd(), ".env")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env")),
        os.path.expanduser("~/Desktop/astr1/.env"),
        os.path.expanduser("~/.env")
    ]
    for c in candidates:
        if os.path.exists(c):
            load_dotenv(dotenv_path=c, override=False)
            return c
    try:
        env_path = find_dotenv(usecwd=True)
        if env_path:
            load_dotenv(dotenv_path=env_path, override=False)
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
        self.declare_parameter("conversation_timeout", float(os.getenv("CONVERSATION_TIMEOUT", "8.0")))

        self._text_model = self.get_parameter("llm_model").value
        self._fallback_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
        self._vision_model = self.get_parameter("vision_model").value
        self._temperature = float(self.get_parameter("llm_temperature").value)
        self._max_tokens = int(self.get_parameter("llm_max_tokens").value)
        self._wake_word = self.get_parameter("wake_word").value
        conv_timeout = float(self.get_parameter("conversation_timeout").value)

        # Adaptive Session
        self.session = ConversationSession(
            base_timeout_s=conv_timeout,
            on_session_start=lambda: self.get_logger().info("✨ [Session] Konuşma Oturumu Başlatıldı."),
            on_session_end=self._on_session_timed_out
        )

        # Groq Client
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self._groq = None
        self._enabled = True

        if Groq and self.groq_api_key:
            try:
                self._groq = Groq(api_key=self.groq_api_key)
                self._active_groq_models = self._discover_active_groq_models()
                self._vision_model = self._discover_vision_model()
                v_name = self._vision_model if self._vision_model else "Gemini Flash (Direct REST)"
                t_name = self._active_groq_models[0] if self._active_groq_models else self._text_model
                self.get_logger().info(f"✅ [AI Brain] LLM Aktif — Metin: {t_name} (Toplam {len(self._active_groq_models)} Groq Modeli) | Vision: {v_name}")
            except Exception as e:
                self.get_logger().error(f"❌ [AI Brain] Groq client başlatılamadı: {e}")
                self._active_groq_models = []
                self._enabled = False
        else:
            self.get_logger().error("❌ [AI Brain] GROQ_API_KEY bulunamadı! STT/LLM devre dışı.")
            self._active_groq_models = []
            self._enabled = False

        # Secondary / Vision Fallback Client (Gemini / OpenAI API)
        self._ai_api_key = os.environ.get("AI_API_KEY", "").strip()
        self._ai_base_url = os.environ.get("AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/").strip()
        self._ai_model = os.environ.get("AI_MODEL", "gemini-2.5-flash").strip()
        self._fallback_vision_client = None
        if OpenAI and self._ai_api_key:
            try:
                self._fallback_vision_client = OpenAI(api_key=self._ai_api_key, base_url=self._ai_base_url)
                self.get_logger().info(f"✅ [AI Brain] Gemini/OpenAI Vision Yedek İstemcisi Hazır ({self._ai_model})")
            except Exception as e:
                self.get_logger().debug(f"OpenAI fallback client notice: {e}")

        # Perception & Hardware State
        self._lock = threading.Lock()
        self._is_processing = False
        self._tts_speaking = False
        self._person_detected = False
        self._looking_at_robot = False
        self._looking_start_time = None
        self._last_proactive_gaze_time = 0.0
        self._speaker_angle = 0.0
        self._speaker_gender = "unknown"
        self._user_distance = 0.0
        self._user_emotion = "neutral"
        self._recognized_person = None
        self._recognized_speaker = None
        self._latest_frame = None
        self._latest_frame_time = 0.0

        # ROS 2 Publishers
        self.pub_tts = self.create_publisher(String, "/tts/say", 10)
        self.pub_interrupt = self.create_publisher(Bool, "/tts/interrupt", 10)
        self.pub_emotion = self.create_publisher(String, "/robot/emotion", 10)
        self.pub_gesture = self.create_publisher(String, "/robot/head_gesture", 10)
        self.pub_look_target = self.create_publisher(Float32, "/robot/look_target", 10)

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

        # Idle Learning (Opt-in to prevent token burn)
        self._enable_idle_vision = bool(os.getenv("ENABLE_IDLE_VISION", "false").lower() == "true")
        if self._enable_idle_vision:
            self._start_idle_learning()

        self.get_logger().info(
            f"🧠 [AI Brain Node] Modüler Mimari Hazır! Kişilik: [{self.persona_engine.current_persona.upper()}]"
        )

    def _discover_active_groq_models(self) -> List[str]:
        """Dynamically queries Groq API to get real, active, non-deprecated model IDs."""
        if not self._groq:
            return []
        try:
            models = self._groq.models.list()
            active_ids = [m.id for m in models.data]
            chat_models = []
            for mid in active_ids:
                mid_l = mid.lower()
                if any(x in mid_l for x in ["whisper", "embedding", "guard", "moderation", "tts"]):
                    continue
                chat_models.append(mid)

            def score(m):
                ml = m.lower()
                if "120b" in ml or "70b" in ml or "large" in ml: return 3
                if "32b" in ml or "27b" in ml or "20b" in ml or "8x7b" in ml: return 2
                if "8b" in ml or "mini" in ml or "flash" in ml: return 1
                return 0

            chat_models.sort(key=score, reverse=True)
            return chat_models
        except Exception as e:
            self.get_logger().warn(f"⚠️ Groq aktif model keşfi başarısız: {e}")
            return []

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
        if not self._looking_at_robot or self._looking_start_time is None or self._tts_speaking or self._is_processing:
            return

        now = time.monotonic()
        if (now - self._looking_start_time) >= 0.3:
            if self.state_machine.is_idle() and (now - self._last_proactive_gaze_time) > 8.0:
                self._last_proactive_gaze_time = now
                self.session.activate_session(reason="proactive_gaze")
                self.state_machine.transition_to(RobotState.LISTENING)
                self._looking_start_time = None

                identity = self._get_active_biometric_identity()
                persona = self.persona_engine.current_persona

                # Personalized Proactive Greeting
                if identity.get("is_known"):
                    off = find_official_by_name_or_alias(identity.get("name", ""))
                    if off:
                        proactive_greeting = get_official_greeting(off)
                        self._publish_emotion("formal")
                    elif "baran" in identity.get("name", "").lower():
                        proactive_greeting = "Selam Baran! Çalışmalara tam gaz devam mı?"
                        self._publish_emotion("playful")
                    else:
                        formal = identity.get("formal_title") or identity.get("name")
                        proactive_greeting = f"Merhaba {formal}! Seni gördüğüme çok sevindim, nasıl yardımcı olabilirim?"
                        self._publish_emotion(persona)
                else:
                    if persona == "flirt":
                        proactive_greeting = "Bana öyle güzel bakıyorsunuz ki güzellik, gözleriniz işlemcimi yaktı... İsminiz ne sizin, tanışalım mı?"
                        self._publish_emotion("flirt")
                    elif persona == "playful":
                        if self._user_emotion == "happy":
                            proactive_greeting = "Gözlerinin içi gülüyor, süper! Nasıl yardımcı olabilirim?"
                        else:
                            proactive_greeting = "Hey, bana bakıyorsun! Nasıl yardımcı olabilirim?"
                        self._publish_emotion("playful")
                    elif persona == "formal":
                        proactive_greeting = "Bakışlarınızı üzerimde hissediyorum efendim, bir emriniz var mıdır?"
                        self._publish_emotion("formal")
                    else:
                        proactive_greeting = "Merhaba! Sana nasıl yardımcı olabilirim?"
                        self._publish_emotion(persona)

                self.get_logger().info(f"👁️ [Proaktif Etkileşim] ({persona}): \"{proactive_greeting}\"")
                self._publish_gesture("nod")
                self._publish_tts(proactive_greeting)

    def _check_persona_switch(self, text: str) -> bool:
        text_lower = text.lower()
        mapping = {
            "flörtöz": "flirt", "çapkın": "flirt", "piç": "flirt", "romantik": "flirt", "kızlara yürü": "flirt",
            "duygusal": "emotional", "hisli": "emotional", "resmi": "formal", "ciddi": "formal", "saygılı": "formal",
            "alaycı": "sarcastic", "sarkastik": "sarcastic", "öfkeli": "angry", "asabi": "angry",
            "kaba": "rude", "dobra": "rude", "şakacı": "playful", "neşeli": "playful", "normal": "playful"
        }
        for key, p_name in mapping.items():
            if key in text_lower and any(tr in text_lower for tr in ["ol", "geç", "mod", "davran", "konuş"]):
                self.persona_engine.set_persona(p_name)
                self.memory.profile.set_persona(p_name)
                self.get_logger().info(f"🎭 [Kişilik Değişti]: Yeni Mod -> {p_name.upper()}")
                self._publish_emotion(p_name)
                return True
        return False

    def _on_speech(self, msg: String):
        raw_text = msg.data.strip()
        if not raw_text or self._tts_speaking or not self._enabled:
            return

        now = time.monotonic()
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
        recent_person = (self._person_detected or (hasattr(self, '_last_person_seen_time') and (now - self._last_person_seen_time) < 4.0))

        # If IDLE: Activate on Wake Word / Greetings, Direct Gaze, or Person Presence
        if self.state_machine.is_idle():
            if has_wake_word or self._looking_at_robot or recent_person:
                activation_reason = "wake_word" if has_wake_word else ("gaze" if self._looking_at_robot else "person_presence")
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
                    self._publish_tts(greeting)
                    return
                else:
                    raw_text = clean_prompt
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
            base64_img = frame_to_base64_jpeg(frame, max_dim=512) if frame is not None and (is_visual or is_learning_obj) else None
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
                return

            # 2. Identity Query ("Ben kimim? / Beni tanıyor musun?")
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
                return

            # 3. Person Introduction & Biometric Enrollment
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
                    vision_ans = self._query_groq_vision(user_text, base64_img)
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

            stream_resp = None
            models_to_try = list(self._active_groq_models) if self._active_groq_models else [self._text_model]
            if self._text_model in models_to_try:
                models_to_try.remove(self._text_model)
                models_to_try.insert(0, self._text_model)

            for m in models_to_try:
                try:
                    stream_resp = self._groq.chat.completions.create(
                        messages=messages,
                        model=m,
                        temperature=self._temperature,
                        max_tokens=self._max_tokens,
                        stream=True,
                    )
                    break
                except Exception as stream_err:
                    self.get_logger().warn(f"⚠️ Model {m} stream hatası: {stream_err}")
                    continue

            # Fallback to Direct Google Gemini REST Text Generation
            if stream_resp is None:
                self.get_logger().warn("⚠️ Groq modelleri yanıt veremedi, Google Gemini REST metin motoruna geçiliyor...")
                gemini_text = self._query_gemini_text_rest(system_prompt, user_text, self.memory.episodic.get_messages())
                if gemini_text:
                    self.cloud_mgr.record_llm_success()
                    self.get_logger().info(f"🤖 [Astro (Gemini)]: \"{gemini_text}\"")
                    self.memory.episodic.add_message("assistant", gemini_text)
                    self._publish_tts(gemini_text)
                    self._publish_emotion(persona)
                    return

                self.cloud_mgr.record_llm_failure("All cloud models failed")
                self.get_logger().error("❌ Tüm LLM modelleri başarısız oldu! Yerel çevrimdışı moda geçiliyor.")
                offline_msg = "Şu an internet bağlantımda bir sorun var ama seni dinliyorum!"
                self._publish_tts(offline_msg)
                return

            self.cloud_mgr.record_llm_success()

            full_text = ""
            first_token_time = None

            for chunk in stream_resp:
                delta = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else None
                if not delta:
                    continue

                if first_token_time is None:
                    first_token_time = time.monotonic()
                    self.state_machine.transition_to(RobotState.SPEAKING)

                full_text += delta

            clean_full = clean_tts_text(full_text)
            if clean_full and len(clean_full) >= 2:
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

    def _query_groq_vision(self, prompt: str, base64_image: str) -> str | None:
        persona = self.persona_engine.current_persona
        system_instruction = f"Sen Astro adında {persona} karakterli akıllı ve sempatik bir sosyal robotsun. Karşındaki kameradan çekilen görüntüyü görüyorsun. Kullanıcının sorusunu (örneğin elinde ne tuttuğunu veya odada ne olduğunu) dikkatle incele ve kendi kişiliğinle tek bir eksiksiz doğal Türkçe cümleyle yanıtla."

        # 1. Try Primary Groq Vision (if available)
        if self._groq and self._vision_model:
            try:
                response = self._groq.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]}
                    ],
                    model=self._vision_model,
                    temperature=0.2,
                    max_tokens=300
                )
                raw = response.choices[0].message.content.strip()
                clean = extract_spoken_turkish_sentence(raw)
                if clean:
                    self.cloud_mgr.record_llm_success()
                    return clean
            except Exception as e:
                self.get_logger().warn(f"⚠️ [Groq Vision] Başarısız ({e}), Gemini Vision yedeğe geçiliyor...")

        # 2. Try Direct Google Gemini REST Endpoint (Ultra-Fast, Zero-Dependency)
        if self._ai_api_key:
            for g_model in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-2.5-flash"]:
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
                            "maxOutputTokens": 1024,
                            "thinkingConfig": {
                                "thinkingBudget": 0
                            }
                        }
                    }
                    data_bytes = json.dumps(payload).encode("utf-8")
                    req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=4.5) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                        clean_ans = clean_tts_text(text)
                        if clean_ans and len(clean_ans) >= 3:
                            self.cloud_mgr.record_llm_success()
                            self.get_logger().info(f"✨ [Gemini Vision REST] Görsel başarıyla yanıtlandı ({g_model}): '{clean_ans}'")
                            return clean_ans
                except Exception as e:
                    self.get_logger().warn(f"⚠️ [Gemini REST ({g_model}) Hatası]: {e}")

        # 2. Try Fallback OpenAI Client (if OpenAI key)
        if self._fallback_vision_client and self._ai_api_key.startswith("sk-"):
            for m_cand in ["gpt-4o-mini", "gpt-4o"]:
                try:
                    response = self._fallback_vision_client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
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
                except Exception as e2:
                    self.get_logger().warn(f"⚠️ [OpenAI Vision ({m_cand}) Hatası]: {e2}")

        self.cloud_mgr.record_llm_failure("All vision models failed")
        return None

    def _query_gemini_text_rest(self, system_instruction: str, user_text: str, history_messages: List[Dict[str, Any]]) -> Optional[str]:
        """Zero-dependency direct Google Gemini REST text conversation engine."""
        if not self._ai_api_key:
            return None

        for g_model in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash", "gemini-1.5-flash-8b"]:
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
                        "maxOutputTokens": 300,
                        "thinkingConfig": {"thinkingBudget": 0}
                    }
                }
                data_bytes = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=4.5) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                    clean = clean_tts_text(text)
                    if clean:
                        return clean
            except Exception as e:
                self.get_logger().warn(f"⚠️ [Gemini Text REST ({g_model}) Hatası]: {e}")
        return None

    def _execute_tool_call(self, tool_name: str, arguments: dict, frame: np.ndarray | None) -> str:
        if tool_name == "get_live_weather":
            city = arguments.get("city", "Istanbul").strip()
            try:
                url = f"https://wttr.in/{urllib.parse.quote(city)}?format=%C+%t&lang=tr"
                req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    weather_text = resp.read().decode("utf-8").strip()
                return f"{city} için hava durumu şu an {weather_text}."
            except Exception:
                return f"{city} için şu an hava durumu bilgisine ulaşamadım."

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

    def _idle_learning_loop(self):
        while rclpy.ok():
            time.sleep(10)
            if not self._enabled or not self.state_machine.is_idle() or self._tts_speaking or self._is_processing:
                continue

            now = time.monotonic()
            # Relaxed 5-minute interval (300s) to protect token quota and prevent unnecessary API calls
            if (now - getattr(self, '_last_idle_learning_time', 0)) > 300.0:
                self._last_idle_learning_time = now

                captured_frame = None
                with self._lock:
                    if self._latest_frame is not None and (now - self._latest_frame_time) < 4.0:
                        captured_frame = self._latest_frame.copy()

                if captured_frame is not None:
                    base64_img = frame_to_base64_jpeg(captured_frame, max_dim=512)
                    if base64_img:
                        self.get_logger().info("🕵️ [Idle Learning] Etraf sessiz, Astro etrafı inceliyor...")
                        prompt = "Kameradaki görüntüyü Türkçe olarak tek bir kısa cümleyle açıkla. Açıklama harici hiçbir şey yazma. Örnek: 'Masada bir bilgisayar var.' veya 'Oda şu an aydınlık ve boş.'"
                        obs = self._query_groq_vision(prompt, base64_img)
                        if obs:
                            self.memory.profile.add_observation(obs)
                            self.get_logger().info(f"🧠 [Hafıza Güncellendi - Gözlem]: {obs}")

                            # If Gemini Vision observes a person looking at the robot or sitting in front of it
                            obs_lower = obs.lower()
                            person_gaze_keywords = ["bize bakıyor", "bana bakıyor", "kameraya bakıyor", "karşımda", "karşısında", "oturan bir", "biri var", "insan var", "beyefendi", "hanımefendi"]
                            if any(kw in obs_lower for kw in person_gaze_keywords):
                                if self.state_machine.is_idle() and not self._tts_speaking and not self._is_processing:
                                    if (now - getattr(self, '_last_proactive_gaze_time', 0)) > 20.0:
                                        self._last_proactive_gaze_time = now
                                        self.session.activate_session(reason="gemini_scene_gaze")
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
        clean = clean_tts_text(text)
        if clean:
            msg = String()
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
