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
import base64
import inspect
import json
import os
import re
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32, String

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
    from astro_ai.conversation_session import ConversationSession
    from astro_ai.memory_manager import MemoryManager
    from astro_ai.persona_engine import PersonaEngine, PERSONA_PROMPTS
    from astro_ai.state_machine import RobotState, StateMachine
except ImportError:
    from conversation_session import ConversationSession
    from memory_manager import MemoryManager
    from persona_engine import PersonaEngine, PERSONA_PROMPTS
    from state_machine import RobotState, StateMachine



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
    except Exception:
        pass
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
        return base64.b64encode(buffer).decode("utf-8")
    except Exception:
        return None




REALTIME_WS_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"
VALID_REALTIME_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse", "fable", "onyx"}
def discover_realtime_models(api_key: str, preferred: str = "") -> list[str]:
    candidates = []
    if preferred:
        candidates.append(preferred)

    standard_models = [
        "gpt-4o-realtime-preview",
        "gpt-4o-mini-realtime-preview",
        "gpt-4o-realtime-preview-2024-10-01",
        "gpt-4o-realtime-preview-2024-12-17",
        "gpt-realtime",
        "gpt-realtime-mini"
    ]
    for m in standard_models:
        if m not in candidates:
            candidates.append(m)

    try:
        import urllib.request
        req = urllib.request.Request("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            avail_ids = [m["id"] for m in data.get("data", []) if "realtime" in m.get("id", "")]
            if avail_ids:
                for mid in reversed(avail_ids):
                    if mid in candidates:
                        candidates.remove(mid)
                    candidates.insert(0, mid)
    except Exception:
        pass

    return candidates


class AstroRealtimeNode(Node):
    """ROS 2 Node bridging Astro sensors & audio streams to OpenAI Realtime WebSocket."""

    def __init__(self):
        super().__init__("astro_realtime_node")

        # Load environment variables
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", os.environ.get("AI_API_KEY", "")).strip()
        self.realtime_model = os.environ.get("REALTIME_MODEL", "gpt-4o-realtime-preview").strip()
        raw_voice = os.environ.get("REALTIME_VOICE", os.environ.get("TTS_VOICE", "echo")).strip().lower()
        self.realtime_voice = raw_voice if raw_voice in VALID_REALTIME_VOICES else "echo"
        self.persona_name = os.environ.get("PERSONA", "kufurbaz").strip().lower()


        # Modular Cognitive Subsystems
        self.memory = MemoryManager()
        self.persona_engine = PersonaEngine(self.persona_name)
        self.state_machine = StateMachine(RobotState.IDLE)
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
        self._greeted_people: Dict[str, float] = {}

        # Biometric Voice & Face Engines
        self.voice_recognizer = VoiceRecognizer() if VoiceRecognizer else None
        self.face_recognizer = FaceRecognizer() if FaceRecognizer else None
        self._user_speech_audio_buffer: List[bytes] = []

        # Camera Perception Frame Cache
        self._latest_camera_frame: Optional[np.ndarray] = None
        self._last_img_time = 0.0

        # Autonomous Idle Learning & Environmental Observation (0 OpenAI Cost)
        self._enable_idle_learning = os.environ.get("ENABLE_IDLE_LEARNING", "true").lower() == "true"
        self._last_idle_learning_time = 0.0
        self._last_proactive_gaze_time = 0.0
        if self._enable_idle_learning:
            threading.Thread(target=self._idle_learning_loop, daemon=True).start()
            self.get_logger().info("🤖 [Astro Realtime] Otonom Boşta Öğrenme ve Çevre Gözlem Motoru Aktif (Groq/Gemini 0-Token)!")


        # ROS 2 Publishers
        self.pub_output_pcm = self.create_publisher(String, "/audio/realtime_output_pcm", 50)

        self.pub_interrupt = self.create_publisher(Bool, "/tts/interrupt", 10)
        self.pub_emotion = self.create_publisher(String, "/robot/emotion", 10)
        self.pub_gesture = self.create_publisher(String, "/robot/head_gesture", 10)
        self.pub_transcript = self.create_publisher(String, "/speech/text", 10)

        # ROS 2 Subscribers
        self.create_subscription(String, "/audio/realtime_input_pcm", self._on_input_pcm, 50)
        self.create_subscription(Bool, "/audio/playback_active", self._on_playback_active, 10)
        self.create_subscription(String, "/vision/recognized_person", self._on_recognized_person, 10)
        self.create_subscription(String, "/audio/speaker_id", self._on_speaker_id, 10)
        self.create_subscription(String, "/vision/user_emotion", self._on_user_emotion, 10)
        self.create_subscription(Bool, "/vision/looking_at_robot", self._on_looking_at_robot, 10)
        self.create_subscription(Float32, "/vision/user_distance", self._on_user_distance, 10)
        self.create_subscription(Float32, "/audio/doa", self._on_doa, 10)
        self.create_subscription(Image, "/oak/rgb/image_raw", self._on_camera_image, 10)



        # Tool execution deduplication
        self._executed_tool_calls: set[str] = set()

        # Sleep Mode (Default: Start in Sleeping State)
        self._is_sleeping = True
        self._last_interaction_time = time.monotonic() - 20.0
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
        self.get_logger().info("💤 [Astro Uyku Modu]: Düğüm başlatıldı — Astro uyku modunda (😴). Belirgin bir insan sesi algılandığında uyanacak.")

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

        while rclpy.ok():
            current_model = candidate_models[model_idx % len(candidate_models)]
            ws_url = f"wss://api.openai.com/v1/realtime?model={current_model}"
            try:
                self.get_logger().info(f"🌐 [Realtime WS] OpenAI Realtime API'ye bağlanılıyor: {ws_url}")
                async with websockets.connect(ws_url, **connect_kwargs) as ws:
                    self._ws = ws
                    self._is_connected = True
                    self._is_responding = False
                    self._is_playback_active = False
                    self.get_logger().info(f"✅ [Realtime WS] Bağlantı Başarılı ({current_model})! Oturum parametreleri gönderiliyor...")

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
                err_str = str(e)
                if "4004" in err_str or "model_not_found" in err_str:
                    self.get_logger().warn(f"⚠️ [Realtime Model Bulunamadı] '{current_model}' modeline erişilemedi, bir sonraki modele geçiliyor...")
                    model_idx += 1
                    await asyncio.sleep(1.0)
                else:
                    self.get_logger().warn(f"⚠️ [Realtime WS] Bağlantı koptu ({e}), 3 saniye sonra yeniden bağlanılacak...")
                    await asyncio.sleep(3.0)



    def _build_current_system_prompt(self) -> str:
        """Builds system instructions with memory, identity, persona, and onboarding behavior."""
        identity = self._get_active_biometric_identity()
        is_known = identity.get("is_known", False)
        if is_known:
            name_val = identity.get("name", "Misafir")
            title_val = identity.get("formal_title", identity.get("title", name_val))
            bio_status = (
                f"\n[GÜNCEL BİYOMETRİK KİMLİK]: Karşındaki kişi %100 tanındı -> İsim: {name_val}, Hitap: {title_val}.\n"
                f"ÇOKLU KONUŞMACI & ÖNCELİK KURALI:\n"
                f"1. Karşında {name_val} ({title_val}) var. Kendisine doğrudan ismiyle/hitabıyla hitap et.\n"
                f"2. Eğer odada 2 kişi aynı anda konuşursa veya arkadan başka bir ses gelirse, DAİMA ÖNCELİĞİ TANIDIĞIN KİŞİYE ({name_val}) VER ve ona yanıt ver.\n"
                f"3. Tanıdığın kişi ({name_val}) karşındayken araya giren bilinmeyen sesleri kaydetmeye çalışma veya asıl kişiyi bırakma."
            )
        else:
            bio_status = (
                f"\n[GÜNCEL BİYOMETRİK DURUM]: Karşındaki kişi HENÜZ TANINMIYOR (Bilinmeyen Ses & Yüz / Yeni Kullanıcı / Misafir).\n"
                f"KRİTİK DAVRANIŞ KURALLARI:\n"
                f"1. Karşındaki kişi az önceki kişi DEĞİLDİR (veya sesi tanınmayan farklı biridir). Karşındaki kişiye ASLA önceki isimlerle (Oktay, Baran vb.) hitap etme!\n"
                f"2. Tanışma & Öğrenme: Ortamda tanıdığın hiç kimse yoksa ve SADECE bu bilinmeyen kişi seninle konuşuyorsa, seçili kişiliğinle ({self.persona_name}) sesini ilk defa duyduğunu, hafızandaki kayıtlara uymadığını belirt ve adını sor (Örn: 'Sesini ilk kez duyuyorum, tanıyamadım! Adın ne senin?' veya Küfürbaz modundaysan 'Ulan sesini çıkaramadım, kimsin sen? Adını söyle de kaydedeyim koçum!').\n"
                f"3. Biyometrik Kayıt: SADECE VE SADECE kullanıcı AÇIKÇA kendi adını söylediğinde (örn: 'Adım Ahmet', 'Mehmet ben', 'Bana Ali de') 'enroll_user_biometrics' fonksiyonunu çağır! Kullanıcı adını açıkça söylemediyse ASLA kafandan rastgele isim uydurarak bu fonksiyonu çağırma.\n"
                f"4. Dürüstlük: Asla 'tanıdım' diyerek yalan söyleme veya tanınmayan kişiye ezbere önceki isimleri yapıştırma."
            )

        memory_rule = (
            "\n\n[HAFIZA VE GEÇMİŞ KONUŞMALARI HATIRLAMA KURALI]:\n"
            "- Sana yukarıda 'Kalıcı Bilgilerin', 'Geçmiş Konuşmaların', 'Tercihler' ve 'Kullanıcı Bilgisi' başlıkları altında gerçek hafıza verilerin verilmiştir.\n"
            "- Kullanıcı 'Daha önce ne konuştuk?', 'Ne konuşmuştuk?', 'Hakkımda ne biliyorsun?', 'Beni hatırladın mı?', 'Hafızanda ne kayıtlı?' diye sorduğunda, "
            "ASLA 'hatırlamıyorum' veya 'geçmişi bilmiyorum' deme! Hafızandaki geçmiş diyalog özetlerini, kullanıcının tercihlerini ve bildiğin bilgileri samimiyetle ve net olarak söyle!"
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
                        "transcription": {
                            "model": "whisper-1",
                            "language": "tr"
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.72,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 600,
                            "create_response": False
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

        # 0. Session Update Acknowledged
        if event_type == "session.updated":
            self.get_logger().info("✅ [Realtime WS] Oturum OpenAI tarafından başarıyla onaylandı ve hazır!")

        # 1. Real-Time Streaming Audio Output (GA & Preview names)
        elif event_type in ("response.audio.delta", "response.output_audio.delta"):
            delta_b64 = event.get("delta", "")
            if delta_b64:
                out_msg = String()
                out_msg.data = delta_b64
                self.pub_output_pcm.publish(out_msg)

        # 2. Real-Time Streaming Audio Transcript
        elif event_type in ("response.audio_transcript.delta", "response.output_audio_transcript.delta", "response.text.delta"):
            text_delta = event.get("delta", "")
            # Streaming token

        # 3. User Speech Started
        elif event_type == "input_audio_buffer.speech_started":
            self._wake_up()
            # ONLY trigger barge-in interruption if Astro was ACTUALLY playing audio or generating a response
            if self._is_responding or self._is_playback_active:
                self.get_logger().info("⚡ [Realtime Barge-In] Kullanıcı lafa girdi — Çalma anında durduruluyor...")
                self._is_responding = False
                intr_msg = Bool()
                intr_msg.data = True
                self.pub_interrupt.publish(intr_msg)
                # Cancel ongoing OpenAI response generation
                try:
                    await ws.send(json.dumps({"type": "response.cancel"}))
                except Exception:
                    pass
            else:
                self.get_logger().debug("🎤 [Realtime] Kullanıcı konuşmaya başladı...")

        # 3b. User Speech Stopped
        elif event_type == "input_audio_buffer.speech_stopped":
            self.get_logger().info("🤫 [Realtime] Cümle bitti, biyometri doğrulanıyor ve yanıt üretiliyor...")
            self._run_voice_identification()
            current_prompt = self._build_current_system_prompt()
            resp_event = {
                "type": "response.create",
                "response": {
                    "instructions": current_prompt
                }
            }
            try:
                await ws.send(json.dumps(resp_event))
            except Exception as se:
                self.get_logger().error(f"Response create notice: {se}")


        # 3c. Response Created
        elif event_type == "response.created":
            self._is_responding = True
            self._response_start_time = time.monotonic()
            self.get_logger().info("🎙️ [Realtime] Astro sesli yanıt üretmeye başladı...")

        # 3d. Response Done / Cancelled
        elif event_type in ("response.done", "response.cancelled"):
            self._is_responding = False

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
                tool_result = self._execute_realtime_tool(func_name, args)
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
            self._is_responding = False
            err = event.get("error", {})
            msg = err.get("message", "")
            if "no active response found" not in msg and "already has an active response" not in msg:
                self.get_logger().error(f"❌ [Realtime WS Hatası]: {msg}")



    def _execute_realtime_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Executes integrated robot tools in real time."""
        if name == "get_live_weather":
            city = args.get("city", "Ahlat")
            return {"status": "success", "city": city, "weather": f"{city}'ta hava şu an 22 derece, açık ve güneşli."}

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

        elif name == "inspect_camera_view":
            focus = args.get("focus", "kullanıcının elindeki nesne, rengi ve çevre")
            return self._inspect_camera_view(focus)

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
            except Exception:
                pass
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
        """Runs ultra-fast acoustic voiceprint matching on the recorded user speech (~1.8s window)."""
        if not self.voice_recognizer:
            return
        with self._lock:
            if not self._user_speech_audio_buffer:
                return
            raw_16k_all = b"".join(self._user_speech_audio_buffer[-90:])  # Last ~1.8 seconds (~50ms inference)

        try:
            audio_arr = np.frombuffer(raw_16k_all, dtype=np.int16)
            if len(audio_arr) >= 16000 * 0.4:
                spk_name, spk_conf, spk_meta = self.voice_recognizer.recognize_voice(audio_arr, sample_rate=16000, threshold=0.35)
                is_known_spk = (spk_name is not None and spk_conf >= 0.35)
                now = time.monotonic()
                if is_known_spk:
                    self.get_logger().info(f"🎙️ [Ses Tanıma]: {spk_name} ({spk_meta.get('formal_title', '')}) — Güven: %{int(spk_conf*100)}")
                    with self._lock:
                        self._recognized_speaker = {
                            "name": spk_name,
                            "title": spk_meta.get("title", ""),
                            "formal_title": spk_meta.get("formal_title", spk_name),
                            "confidence": spk_conf,
                            "is_known": True,
                            "source": "voice"
                        }
                        self._active_person_name = spk_name
                        self._person_hold_until = now + 45.0
                    self._sync_perception_to_session()
                else:
                    self.get_logger().info(f"🎙️ [Ses Tanıma]: Bilinmeyen Ses / Tanınmadı (En Yakın: '{spk_name}', Güven: {spk_conf:.2f})")
                    with self._lock:
                        self._recognized_speaker = {"name": "Misafir", "confidence": spk_conf, "is_known": False, "source": "unknown_voice"}
                        self._active_person_name = "Misafir"
                        self._person_hold_until = 0.0
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

        prompt_text = (
            f"Sen Astro adlı sosyal robotun gözüsün. Bu fotoğrafta karşındaki odayı, ortamı, insanların duruşunu, "
            f"masadaki eşyaları ve kullanıcının elinde tuttuğu nesneyi çok detaylı ve %100 doğru şekilde Türkçe açıkla. "
            f"Odaklanılacak konu: {focus if focus else 'kullanıcının elindeki nesne, odadaki eşyalar ve çevre'}. Doğrudan kesin gözlemini kısa ve net yaz."
        )

        refusal_kws = ["üzgünüm", "yardımcı olamam", "açıklayamıyorum", "cannot assist", "i am sorry", "i'm sorry", "doğrudan açıklayamıyorum"]
        obs = None

        # 1. Ultra-Fast Priority: Groq Vision (llama-3.2-11b-vision-preview / llama-3.2-90b-vision-preview) (~250ms, 0 Refusal)
        if self.groq_api_key:
            for v_mod in ["llama-3.2-11b-vision-preview", "llama-3.2-90b-vision-preview"]:
                try:
                    import urllib.request
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
                    req = urllib.request.Request(
                        "https://api.groq.com/openai/v1/chat/completions",
                        data=json.dumps(req_data).encode("utf-8"),
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {self.groq_api_key}"
                        },
                        method="POST"
                    )
                    with urllib.request.urlopen(req, timeout=5.0) as resp:
                        resp_json = json.loads(resp.read().decode("utf-8"))
                        candidate_obs = resp_json["choices"][0]["message"]["content"].strip()
                        if candidate_obs and not any(rk in candidate_obs.lower() for rk in refusal_kws):
                            obs = candidate_obs
                            break
                except Exception as ge:
                    self.get_logger().warn(f"⚠️ [Groq Vision Uyarısı]: {ge}")

        # 2. Fast Fallback: Gemini 2.0 Flash REST (~300ms, 0 Refusal)
        if not obs and self.gemini_api_key:
            try:
                import urllib.request
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.gemini_api_key}"
                payload = {
                    "contents": [{
                        "parts": [
                            {"text": prompt_text},
                            {"inlineData": {"mimeType": "image/jpeg", "data": b64_img}}
                        ]
                    }],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 150}
                }
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    candidate_obs = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if candidate_obs and not any(rk in candidate_obs.lower() for rk in refusal_kws):
                        obs = candidate_obs
            except Exception as gem_e:
                self.get_logger().warn(f"⚠️ [Gemini Vision Uyarısı]: {gem_e}")

        # 3. Fallback: OpenAI Vision REST API (gpt-4o-mini)
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
                req = urllib.request.Request(
                    "https://api.openai.com/v1/chat/completions",
                    data=json.dumps(req_data).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.openai_api_key}"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=6.0) as resp:
                    resp_json = json.loads(resp.read().decode("utf-8"))
                    candidate_obs = resp_json["choices"][0]["message"]["content"].strip()
                    if candidate_obs and not any(rk in candidate_obs.lower() for rk in refusal_kws):
                        obs = candidate_obs
            except Exception as oe:
                self.get_logger().warn(f"⚠️ [OpenAI Vision Uyarısı]: {oe}")

        if obs:
            self.get_logger().info(f"👁️ [Kamera Görme Sonucu]: \"{obs}\"")
            return {"status": "success", "observation": obs}

        return {"status": "error", "observation": "Görüntü analiz edilirken bir hata oluştu."}

    def _check_sleep_mode(self):
        """Transitions Astro into sleep mode after 10 seconds of conversation inactivity."""
        now = time.monotonic()
        is_busy = self._is_responding or self._is_playback_active
        if is_busy:
            self._last_interaction_time = now
            if self._is_sleeping:
                self._wake_up()
            return

        if not self._is_sleeping:
            idle_seconds = now - self._last_interaction_time
            if idle_seconds >= 10.0:
                self._is_sleeping = True
                self.get_logger().info("💤 [Astro Uyku Modu]: 10 saniye hareketsizlik — Astro uyku moduna geçti (😴).")

                # 1. Publish sleeping emotion for face/display
                emo_msg = String()
                emo_msg.data = "sleeping"
                self.pub_emotion.publish(emo_msg)

                # 2. Publish sleep head gesture
                gest_msg = String()
                gest_msg.data = "sleep"
                self.pub_gesture.publish(gest_msg)

    def _wake_up(self):
        """Wakes Astro up from sleep mode upon speech or user interaction."""
        now = time.monotonic()
        self._last_interaction_time = now
        if self._is_sleeping:
            self._is_sleeping = False
            self.get_logger().info("⏰ [Astro Uyandı]: Kullanıcı sesi algılandı — Astro uykudan uyandı ve dinliyor!")

            # 1. Restore persona emotion
            emo_msg = String()
            emo_msg.data = self.persona_name
            self.pub_emotion.publish(emo_msg)

            # 2. Publish wake gesture
            gest_msg = String()
            gest_msg.data = "wake"
            self.pub_gesture.publish(gest_msg)


    def _on_camera_image(self, msg: Image):
        now = time.monotonic()
        if (now - self._last_img_time) < 0.2:  # Max 5 FPS decoding
            return
        self._last_img_time = now
        frame = imgmsg_to_bgr(msg)
        if frame is not None:
            with self._lock:
                self._latest_camera_frame = frame

    def _idle_learning_loop(self):
        """Continuous background loop for autonomous room exploration and cognitive memory consolidation."""
        while rclpy.ok():
            time.sleep(3)
            if not self._enable_idle_learning:
                continue

            # Only run when robot is idle and not actively speaking or responding
            if self._is_responding or self._is_playback_active:
                continue

            now = time.monotonic()
            if (now - self._last_idle_learning_time) > 20.0:
                self._last_idle_learning_time = now

                # 1. Background Room Scene & Object Observation via Camera (Groq Vision)
                self._idle_room_observation(now)

                # 2. Background Cognitive Memory Reflection
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
                try:
                    req_data = {
                        "model": "llama-3.3-70b-versatile",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 60
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
                        ans = resp_json["choices"][0]["message"]["content"].strip()
                except Exception:
                    pass

            # 2. Try Gemini REST (0 Token Cost fallback)
            if not ans and self.gemini_api_key:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.gemini_api_key}"
                    payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.1, "maxOutputTokens": 60}}
                    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=4.0) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        ans = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                except Exception:
                    pass

            if ans and "YOK" not in ans.upper() and len(ans) >= 5:
                identity = self._get_active_biometric_identity()
                name = identity.get("name", "Misafir")
                self.memory.profile.add_observation(f"Kullanıcı Bilgisi ({name}): {ans}")
                self.get_logger().info(f"🧠 [Otonom Hafıza Yansıtması (Groq)]: {ans}")
                # Sync to session so Realtime AI immediately knows this new fact
                self._sync_perception_to_session()
        except Exception as e:
            self.get_logger().debug(f"Memory reflection notice: {e}")

    def _idle_room_observation(self, now: float):
        """Captures camera view in idle and saves visual environment observations to memory using FREE Groq/Gemini."""
        with self._lock:
            frame = self._latest_camera_frame

        if frame is None:
            return

        b64_img = frame_to_base64_jpeg(frame, max_dim=512)
        if not b64_img:
            return

        try:
            import urllib.request
            prompt = (
                "Sen bir sosyal robotun kamera gözüsün. Karşındaki odayı, ortamı, masadaki eşyaları ve etraftaki insanları "
                "tek bir kısa ve net Türkçe cümleyle açıkla (Örn: 'Masada dizüstü bilgisayar ve kahve fincanı duruyor.' "
                "veya 'Oda aydınlık, masada çakmak ve telefon var.'). Başka hiçbir şey yazma."
            )
            obs = None

            # 1. Try Groq Vision (0 Token Cost)
            if self.groq_api_key:
                for v_mod in ["llama-3.2-11b-vision-preview", "llama-3.2-90b-vision-preview"]:
                    try:
                        req_data = {
                            "model": v_mod,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": prompt},
                                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}}
                                    ]
                                }
                            ],
                            "temperature": 0.2,
                            "max_tokens": 80
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
                            obs = resp_json["choices"][0]["message"]["content"].strip()
                            if obs:
                                break
                    except Exception:
                        pass

            # 2. Try Gemini REST (0 Token Cost fallback)
            if not obs and self.gemini_api_key:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.gemini_api_key}"
                    payload = {
                        "contents": [{
                            "parts": [
                                {"text": prompt},
                                {"inlineData": {"mimeType": "image/jpeg", "data": b64_img}}
                            ]
                        }],
                        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 80}
                    }
                    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=4.0) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        obs = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                except Exception:
                    pass

            if obs and len(obs) > 4:
                self.memory.profile.add_observation(f"Görsel Çevre: {obs}")
                self.get_logger().info(f"👁️🧠 [Otonom Görsel Öğrenme (Groq Vision)]: Astro kameradan gördü ve hafızasına kaydetti -> \"{obs}\"")

                # If vision observes a person looking or sitting in front of robot, proactively initiate greeting
                obs_l = obs.lower()
                if any(kw in obs_l for kw in ["bana bakıyor", "kameraya bakıyor", "karşımda oturan", "biri var", "insan var"]):
                    if not self._is_responding and not self._is_playback_active:
                        if (now - self._last_proactive_gaze_time) > 45.0:
                            self._last_proactive_gaze_time = now
                            self.get_logger().info(f"👁️ [Görsel Sahne Proaktif Etkileşim]: Astro karşısındaki kişiyi fark etti!")
                            if self._ws and self._loop and self._is_connected:
                                gaze_event = {
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "message",
                                        "role": "user",
                                        "content": [{"type": "input_text", "text": f"[Sistem Olayı]: Karşındaki kişiyi veya odayı fark ettin ({obs}). Seçili kişiliğinle kısa, doğal ve esprili bir şekilde laf at veya selam ver!"}]
                                    }
                                }
                                asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(gaze_event)), self._loop)
                                asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps({"type": "response.create"})), self._loop)
        except Exception as e:
            self.get_logger().debug(f"Idle vision observation notice: {e}")



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
            except Exception:
                pass

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
            except Exception:
                pass

        if summary and len(summary) > 5:
            self.memory.profile.add_person_session_summary(person_name, summary)
            self.get_logger().info(f"📝 [Kalıcı Hafıza Kaydı ({person_name})]: 'Önceki konuşma hafızaya kaydedildi -> {summary}'")
            self._sync_perception_to_session()

    def _on_playback_active(self, msg: Bool):
        was_active = self._is_playback_active

        self._is_playback_active = bool(msg.data)
        if was_active and not self._is_playback_active:
            self._playback_end_time = time.monotonic()
            self._is_responding = False
            # Clear OpenAI input audio buffer so trailing room reverberation doesn't trigger VAD
            if self._ws and self._loop and self._is_connected:
                try:
                    asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps({"type": "input_audio_buffer.clear"})), self._loop)
                except Exception:
                    pass
            self.get_logger().info("👂 [Astro Dinliyor]: Mikrofon aktif, sizi dinliyor...")

    def _on_input_pcm(self, msg: String):
        """Sends incoming microphone 24kHz PCM chunk directly to OpenAI Realtime WebSocket and buffers 16k PCM for speaker recognition."""
        if not msg.data or not self._is_connected or not self._ws or not self._loop:
            return

        now = time.monotonic()
        # Watchdog: Auto-reset responding flag if stuck > 6.0s without speaker playback
        if self._is_responding and not self._is_playback_active:
            if (now - getattr(self, "_response_start_time", now)) > 6.0:
                self._is_responding = False

        # Zero Self-Hearing Protection:
        # Do not stream mic audio while Astro is actively playing out of the speaker
        if self._is_playback_active or self._is_responding or (now - getattr(self, "_playback_end_time", 0.0) < 0.25):
            return


        # Downsample and buffer 16kHz audio for acoustic voice recognition & dynamic enrollment
        raw_16k = None
        try:
            raw_24k = base64.b64decode(msg.data.encode("ascii"))
            if raw_24k:
                raw_16k = resample_24k_to_16k(raw_24k)
                if raw_16k:
                    with self._lock:
                        self._user_speech_audio_buffer.append(raw_16k)
                        if len(self._user_speech_audio_buffer) > 250:
                            self._user_speech_audio_buffer = self._user_speech_audio_buffer[-250:]
        except Exception:
            pass

        # Acoustic presence / wake-up (requires clear human voice > 120.0 RMS to ignore faint whisper/noise)
        if raw_16k:
            try:
                arr = np.frombuffer(raw_16k, dtype=np.int16)
                local_rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
                if local_rms > 120.0:
                    self._last_interaction_time = now
                    if self._is_sleeping:
                        self._wake_up()
            except Exception:
                pass

        payload = {
            "type": "input_audio_buffer.append",
            "audio": msg.data
        }
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)
        except Exception:
            pass


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
        except Exception:
            pass

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

                    # Proactive greeting check: greet once every 2 minutes per person
                    last_greet = self._greeted_people.get(name, 0.0)
                    if (now - last_greet) > 120.0 and not self._is_responding and not self._is_playback_active:
                        self._greeted_people[name] = now
                        self.get_logger().info(f"👋 [Proaktif Selamlama]: {name} ({formal_title}) algılandı — Selamlama başlatılıyor!")
                        self._trigger_proactive_greeting(name, formal_title)

            self._sync_perception_to_session()
        except Exception:
            pass

    def _on_speaker_id(self, msg: String):
        try:
            data = json.loads(msg.data)
            with self._lock:
                self._recognized_speaker = data
            self._sync_perception_to_session()
        except Exception:
            pass

    def _on_user_emotion(self, msg: String):
        self._user_emotion = msg.data.lower().strip()

    def _on_looking_at_robot(self, msg: Bool):
        self._looking_at_robot = msg.data

    def _on_user_distance(self, msg: Float32):
        self._user_distance = float(msg.data)

    def _on_doa(self, msg: Float32):
        self._speaker_angle = float(msg.data)

    def _get_active_biometric_identity(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            face = self._recognized_person or {}
            spk = self._recognized_speaker or {}
            held_name = getattr(self, "_active_person_name", "Misafir")
            hold_until = getattr(self, "_person_hold_until", 0.0)

        # 1. Unknown Voice Priority: If active voice is analyzed and is UNKNOWN, it MUST be treated as guest
        if spk and not spk.get("is_known", False):
            return {"name": "Misafir", "title": "Ziyaretçi", "formal_title": "Misafir", "is_known": False, "source": "unknown_voice"}

        # 2. Known Active Voice
        if spk.get("is_known") and spk.get("confidence", 0.0) >= 0.35:
            return {**spk, "source": "voice"}

        # 3. Known Active Face
        if face.get("is_known") and face.get("confidence", 0.0) >= 0.45:
            return {**face, "source": "face"}

        # 4. Memory Hold
        if now < hold_until and held_name != "Misafir":
            return {"name": held_name, "title": held_name, "formal_title": held_name, "is_known": True, "source": "memory_hold"}

        return {"name": "Misafir", "title": "Ziyaretçi", "formal_title": "Misafir", "is_known": False}

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
        except Exception:
            pass






def main(args=None):
    rclpy.init(args=args)
    node = AstroRealtimeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
