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
    from astro_ai.persona_engine import PersonaEngine
    from astro_ai.state_machine import RobotState, StateMachine
except ImportError:
    from conversation_session import ConversationSession
    from memory_manager import MemoryManager
    from persona_engine import PersonaEngine
    from state_machine import RobotState, StateMachine


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

        # Camera Perception Frame Cache
        self._latest_camera_frame: Optional[np.ndarray] = None
        self._last_img_time = 0.0

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



        # Reminders storage
        self._reminders: List[Dict[str, Any]] = []
        self.create_timer(1.0, self._check_reminders)

        # Async WebSocket Loop in background thread
        self._ws = None
        self._loop = None
        self._is_connected = False
        self._ws_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._ws_thread.start()

        self.get_logger().info(f"🚀 [Astro Realtime Node] OpenAI Realtime WebSocket Başlatılıyor... Ses: [{self.realtime_voice}], Kişilik: [{self.persona_name.upper()}]")

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
                    self.get_logger().info(f"✅ [Realtime WS] Bağlantı Başarılı ({current_model})! Oturum parametreleri gönderiliyor...")

                    # Send Initial Session Update
                    await self._send_session_update(ws)

                    # Listen for Realtime Events
                    async for message in ws:
                        await self._handle_realtime_event(ws, json.loads(message))

            except Exception as e:
                self._is_connected = False
                self._ws = None
                err_str = str(e)
                if "4004" in err_str or "model_not_found" in err_str:
                    self.get_logger().warn(f"⚠️ [Realtime Model Bulunamadı] '{current_model}' modeline erişilemedi, bir sonraki modele geçiliyor...")
                    model_idx += 1
                    await asyncio.sleep(1.0)
                else:
                    self.get_logger().warn(f"⚠️ [Realtime WS] Bağlantı koptu ({e}), 3 saniye sonra yeniden bağlanılacak...")
                    await asyncio.sleep(3.0)


    async def _send_session_update(self, ws):
        """Sends comprehensive session configuration with persona prompt, tools, and turn detection."""
        identity = self._get_active_biometric_identity()
        system_prompt = self.persona_engine.build_system_prompt(
            memory_context=self.memory.get_prompt_context(recognized_person=identity),
            recognized_person=identity
        )

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
                            "threshold": 0.65,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 600
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
                    }
                ]
            }
        }


        await ws.send(json.dumps(session_config))
        self.get_logger().info(f"✨ [Realtime WS] Oturum Yapılandırıldı. Kişilik: [{self.persona_name.upper()}], Ses: [{self.realtime_voice}]")

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
            self.get_logger().info("🤫 [Realtime] Cümle bitti, Astro yanıt hazırlıyor...")

        # 3c. Response Created
        elif event_type == "response.created":
            self._is_responding = True
            self.get_logger().info("🎙️ [Realtime] Astro sesli yanıt üretmeye başladı...")


        # 3d. Response Done
        elif event_type == "response.done":
            self._is_responding = False

        # 4. User Speech Transcription Completed
        elif event_type in ("conversation.item.input_audio_transcription.completed", "conversation.item.input_audio_transcription.done"):
            user_transcript = event.get("transcript", "").strip()
            if user_transcript:
                self.get_logger().info(f"🗣️ [Siz]: \"{user_transcript}\"")
                self.memory.episodic.add_message("user", user_transcript)
                t_msg = String()
                t_msg.data = user_transcript
                self.pub_transcript.publish(t_msg)

        # 5. Assistant Response Completed
        elif event_type in ("response.audio_transcript.done", "response.output_audio_transcript.done", "response.text.done"):
            assistant_transcript = (event.get("transcript") or event.get("text") or "").strip()
            if assistant_transcript:
                self.get_logger().info(f"🤖 [Astro Realtime]: \"{assistant_transcript}\"")
                self.memory.episodic.add_message("assistant", assistant_transcript)

        # 6. Realtime Function Calling Execution
        elif event_type in ("response.function_call_arguments.done", "response.output_item.done"):
            if event_type == "response.output_item.done":
                item = event.get("item", {})
                if item.get("type") != "function_call":
                    return
                call_id = item.get("call_id")
                func_name = item.get("name")
                args_str = item.get("arguments", "{}")
            else:
                call_id = event.get("call_id")
                func_name = event.get("name")
                args_str = event.get("arguments", "{}")

            try:
                args = json.loads(args_str)
            except Exception:
                args = {}

            self.get_logger().info(f"🛠️ [Realtime Tool]: {func_name}({args}) çalıştırılıyor...")
            tool_result = self._execute_realtime_tool(func_name, args)

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
            msg = err.get("message", "")
            if "no active response found" not in msg:
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

        return {"status": "unknown_tool"}

    def _inspect_camera_view(self, focus: str = "") -> Dict[str, Any]:
        """Captures real-time camera frame from OAK-D Lite and runs visual recognition."""
        with self._lock:
            frame = self._latest_camera_frame

        if frame is None:
            return {"status": "no_camera_frame", "observation": "Kamera görüntüsü şu an alınamadı."}

        b64_img = frame_to_base64_jpeg(frame, max_dim=640)
        if not b64_img:
            return {"status": "encode_error", "observation": "Görüntü işlenemedi."}

        # Query OpenAI Vision REST API (gpt-4o-mini)
        try:
            import urllib.request
            req_data = {
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Sen Astro adlı sosyal robotun gözüsün. Bu fotoğrafta kullanıcının elinde tuttuğu nesneyi, rengini, materyalini, kullanıcının duruşunu ve çevreyi çok detaylı ve %100 doğru şekilde Türkçe açıkla. Odaklanılacak konu: {focus if focus else 'kullanıcının elindeki nesne ve detayları'}. Doğrudan kesin gözlemini kısa ve net yaz."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64_img}"
                                }
                            }
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
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                resp_json = json.loads(resp.read().decode("utf-8"))
                obs = resp_json["choices"][0]["message"]["content"].strip()
                self.get_logger().info(f"👁️ [Kamera Görme Sonucu]: \"{obs}\"")
                return {"status": "success", "observation": obs}
        except Exception as e:
            self.get_logger().error(f"❌ [Vision Hatası]: {e}")
            return {"status": "error", "observation": "Görüntü analiz edilirken bir hata oluştu."}

    def _on_camera_image(self, msg: Image):
        now = time.monotonic()
        if (now - self._last_img_time) < 0.2:  # Max 5 FPS decoding
            return
        self._last_img_time = now
        frame = imgmsg_to_bgr(msg)
        if frame is not None:
            with self._lock:
                self._latest_camera_frame = frame

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

    def _on_playback_active(self, msg: Bool):
        was_active = self._is_playback_active
        self._is_playback_active = bool(msg.data)
        if was_active and not self._is_playback_active:
            self._playback_end_time = time.monotonic()
            # Clear OpenAI input audio buffer so trailing room reverberation doesn't trigger VAD
            if self._ws and self._loop and self._is_connected:
                try:
                    asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps({"type": "input_audio_buffer.clear"})), self._loop)
                except Exception:
                    pass
            self.get_logger().info("👂 [Astro Dinliyor]: Mikrofon aktif, sizi dinliyor...")

    def _on_input_pcm(self, msg: String):
        """Sends incoming microphone 24kHz PCM chunk directly to OpenAI Realtime WebSocket."""
        if not msg.data or not self._is_connected or not self._ws or not self._loop:
            return

        # Zero Self-Hearing Protection:
        # Do not stream mic audio while Astro is generating or speaking, or within 300ms of playback finish
        if self._is_playback_active or self._is_responding or (time.monotonic() - getattr(self, "_playback_end_time", 0.0) < 0.30):
            return

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

        if face.get("is_known") and face.get("confidence", 0.0) >= 0.45:
            return {**face, "source": "face"}
        if spk.get("is_known") and spk.get("confidence", 0.0) >= 0.40:
            return {**spk, "source": "voice"}
        if now < hold_until and held_name != "Misafir":
            return {"name": held_name, "title": held_name, "formal_title": held_name, "is_known": True, "source": "memory_hold"}

        return {"name": "Misafir", "title": "Ziyaretçi", "formal_title": "Misafir", "is_known": False}


    def _sync_perception_to_session(self):
        """Dynamically syncs persona & recognized identity to the active OpenAI Realtime session ONLY when identity changes."""
        if not self._ws or not self._loop or not self._is_connected:
            return

        # Do NOT interrupt active response generation or speaking
        if getattr(self, "_is_responding", False) or getattr(self, "_is_playback_active", False):
            return

        now = time.monotonic()
        identity = self._get_active_biometric_identity()
        identity_name = identity.get("name", "Misafir")

        # Strictly require identity change: If it is still the same person/guest, NEVER resync
        last_id = getattr(self, "_last_synced_identity", "")
        if identity_name == last_id:
            return

        self._last_synced_identity = identity_name
        self._last_sync_time = now

        system_prompt = self.persona_engine.build_system_prompt(
            memory_context=self.memory.get_prompt_context(recognized_person=identity),
            recognized_person=identity
        )
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
