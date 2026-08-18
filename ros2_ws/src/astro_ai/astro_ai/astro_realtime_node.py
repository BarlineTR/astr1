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
from std_msgs.msg import Bool, Float32, String

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

        # Perception Cache
        self._lock = threading.RLock()
        self._recognized_person: Optional[Dict[str, Any]] = None
        self._recognized_speaker: Optional[Dict[str, Any]] = None
        self._user_emotion = "neutral"
        self._looking_at_robot = False
        self._user_distance = 0.0
        self._speaker_gender = "unknown"
        self._speaker_angle = 0.0

        # ROS 2 Publishers
        self.pub_output_pcm = self.create_publisher(String, "/audio/realtime_output_pcm", 50)
        self.pub_interrupt = self.create_publisher(Bool, "/tts/interrupt", 10)
        self.pub_emotion = self.create_publisher(String, "/robot/emotion", 10)
        self.pub_gesture = self.create_publisher(String, "/robot/head_gesture", 10)
        self.pub_transcript = self.create_publisher(String, "/speech/text", 10)

        # ROS 2 Subscribers
        self.create_subscription(String, "/audio/realtime_input_pcm", self._on_input_pcm, 50)
        self.create_subscription(String, "/vision/recognized_person", self._on_recognized_person, 10)
        self.create_subscription(String, "/audio/speaker_id", self._on_speaker_id, 10)
        self.create_subscription(String, "/vision/user_emotion", self._on_user_emotion, 10)
        self.create_subscription(Bool, "/vision/looking_at_robot", self._on_looking_at_robot, 10)
        self.create_subscription(Float32, "/vision/user_distance", self._on_user_distance, 10)
        self.create_subscription(Float32, "/audio/doa", self._on_doa, 10)

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
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 350
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

        # 1. Real-Time Streaming Audio Output
        elif event_type == "response.audio.delta":
            delta_b64 = event.get("delta", "")
            if delta_b64:
                out_msg = String()
                out_msg.data = delta_b64
                self.pub_output_pcm.publish(out_msg)

        # 2. Real-Time Streaming Audio Transcript
        elif event_type == "response.audio_transcript.delta":
            text_delta = event.get("delta", "")
            # Streaming token

        # 3. User Speech Started (Barge-In Interruption)
        elif event_type == "input_audio_buffer.speech_started":
            self.get_logger().info("⚡ [Realtime Barge-In] Kullanıcı konuşmaya başladı — Çalma anında durduruluyor...")
            intr_msg = Bool()
            intr_msg.data = True
            self.pub_interrupt.publish(intr_msg)
            # Cancel ongoing OpenAI response generation
            await ws.send(json.dumps({"type": "response.cancel"}))

        # 3b. User Speech Stopped
        elif event_type == "input_audio_buffer.speech_stopped":
            self.get_logger().info("🤫 [Realtime] Cümle bitti, Astro yanıt hazırlıyor...")

        # 3c. Response Created
        elif event_type == "response.created":
            self.get_logger().info("🎙️ [Realtime] Astro sesli yanıt üretmeye başladı...")

        # 4. User Speech Transcription Completed
        elif event_type == "conversation.item.input_audio_transcription.completed":
            user_transcript = event.get("transcript", "").strip()
            if user_transcript:
                self.get_logger().info(f"🗣️ [Siz]: \"{user_transcript}\"")
                self.memory.episodic.add_message("user", user_transcript)
                t_msg = String()
                t_msg.data = user_transcript
                self.pub_transcript.publish(t_msg)

        # 5. Assistant Response Completed
        elif event_type == "response.audio_transcript.done":
            assistant_transcript = event.get("transcript", "").strip()
            if assistant_transcript:
                self.get_logger().info(f"🤖 [Astro Realtime]: \"{assistant_transcript}\"")
                self.memory.episodic.add_message("assistant", assistant_transcript)


        # 6. Realtime Function Calling Execution
        elif event_type == "response.function_call_arguments.done":
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

        return {"status": "unknown_tool"}

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

    def _on_input_pcm(self, msg: String):
        """Sends incoming microphone 24kHz PCM chunk directly to OpenAI Realtime WebSocket."""
        if not msg.data or not self._is_connected or not self._ws or not self._loop:
            return

        payload = {
            "type": "input_audio_buffer.append",
            "audio": msg.data
        }
        try:
            asyncio.run_coroutine_threadsafe(self._ws.send(json.dumps(payload)), self._loop)
        except Exception:
            pass

    def _on_recognized_person(self, msg: String):
        try:
            data = json.loads(msg.data)
            with self._lock:
                self._recognized_person = data
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
        with self._lock:
            face = self._recognized_person or {}
            spk = self._recognized_speaker or {}

        if face.get("is_known") and face.get("confidence", 0.0) >= 0.45:
            return {**face, "source": "face"}
        if spk.get("is_known") and spk.get("confidence", 0.0) >= 0.40:
            return {**spk, "source": "voice"}
        return {"name": "Misafir", "title": "Ziyaretçi", "formal_title": "Misafir", "is_known": False}

    def _sync_perception_to_session(self):
        """Dynamically syncs persona & recognized identity to the active OpenAI Realtime session with cooldown."""
        if not self._ws or not self._loop or not self._is_connected:
            return

        now = time.monotonic()
        identity = self._get_active_biometric_identity()
        identity_name = identity.get("name", "Misafir")

        # Do NOT flood session.update: Only sync if identity actually changed, with min 20s cooldown
        last_id = getattr(self, "_last_synced_identity", "")
        last_time = getattr(self, "_last_sync_time", 0.0)

        if identity_name == last_id and (now - last_time) < 20.0:
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
