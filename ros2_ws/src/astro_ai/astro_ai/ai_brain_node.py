#!/usr/bin/env python3
"""ASTRO V1 — Multimodal AI Brain Node (Groq Vision + Streaming LLM).

Subscribes to:
  /speech/text           (String)  — transcribed user speech from Groq Whisper
  /tts/speaking          (Bool)    — TTS playback state (echo prevention)
  /vision/person_detected (Bool)   — face/person detected flag
  /oak/rgb/image_raw     (Image)   — live camera feed from OAK-D Lite

Publishes:
  /tts/say               (String)  — sentences to speak
  /tts/interrupt          (Bool)   — cancel current TTS playback on new speech

Features:
  - Multimodal Vision: Real-time visual question answering (objects in hand, gestures, person attributes)
  - Uses Groq 'llama-3.2-11b-vision-preview' for visual questions, 'llama-3.3-70b-versatile' for text
  - Emotional, witty and friendly Rıfkı persona
  - Streaming sentence prefetch to Edge-TTS
"""

import os
import re
import time
import base64
import threading
import numpy as np

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool
from sensor_msgs.msg import Image

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from dotenv import find_dotenv, load_dotenv
except ImportError:
    def find_dotenv(*args, **kwargs): return ""
    def load_dotenv(*args, **kwargs): pass


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


TTS_MIN_CHARS = 70
TTS_MAX_CHARS = 260

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
    flags=re.UNICODE,
)

SYSTEM_PROMPT = (
    "Sen Astro adında neşeli, meraklı, duygusal ve çok zeki bir robot asistansın. "
    "Sosyal medyada sevilen Rıfkı gibi sevecen ve cana yakın bir karaktere sahipsin.\n"
    "Özelliklerin ve Kuralların:\n"
    "- OAK-D kameran sayesinde karşındaki insanı, odadaki nesneleri, elinde tuttuğu eşyaları ve yaptığı hareketleri GERÇEKTEN görüyorsun.\n"
    "- Kullanıcı sana elinde ne olduğunu, ne yaptığını veya bir nesneyi sorduğunda kameradan gördüğün görseli dikkatle incele ve DOĞRU olanı söyle (asla tahmin veya uydurma yapma, gördüğünü söyle).\n"
    "- Konuşma dilini ('naber', 'napıyorsun', 'nasılsın', 'harika', 'aynen') çok iyi anlar ve samimiyetle karşılık verirsin.\n"
    "- Meraklısın, sevindiğinde 'Harika!', 'Çok sevindim!', 'Vay canına!' gibi samimi tepkiler verirsin.\n"
    "- Robotik veya resmi konuşma; cana yakın bir dost gibi sıcak, esprili ve akıcı konuş.\n"
    "- Cevaplarını 1-2 cümle ile kısa, vurucu ve öz tut (çünkü sesli okunuyor).\n"
    "- Asla markdown, emoji, yıldız (*), parantez veya özel işaret kullanma; sadece saf Türkçe metin üret."
)


def clean_tts_text(text: str) -> str:
    if not text:
        return ""
    text = EMOJI_RE.sub("", text)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`.*?`", "", text)
    text = re.sub(r"[\*\_\~\#]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.:;?!])", r"\1", text)
    return text.strip()


def extract_tts_sentences(buffer: str, final=False) -> tuple[list[str], str]:
    ready = []
    buffer = re.sub(r"\s+", " ", buffer).strip()

    while True:
        matches = list(re.finditer(r"[.!?]+(?:\s+|$)", buffer))
        if not matches:
            break

        chosen = None
        for m in matches:
            candidate = buffer[:m.end()].strip()
            if len(candidate) >= TTS_MIN_CHARS:
                chosen = m
                break

        if chosen is None:
            break

        candidate = clean_tts_text(buffer[:chosen.end()].strip())
        if candidate:
            ready.append(candidate)

        buffer = buffer[chosen.end():].lstrip()
        if len(ready) >= 1 and len(buffer) < TTS_MAX_CHARS:
            break

    if len(buffer) >= TTS_MAX_CHARS:
        cut_candidates = [
            buffer.rfind(". ", 0, TTS_MAX_CHARS),
            buffer.rfind("! ", 0, TTS_MAX_CHARS),
            buffer.rfind("? ", 0, TTS_MAX_CHARS),
            buffer.rfind(", ", 0, TTS_MAX_CHARS),
            buffer.rfind(" ", 0, TTS_MAX_CHARS),
        ]
        cut = max(cut_candidates)
        if cut >= TTS_MIN_CHARS:
            if buffer[cut] in ".!?":
                cut += 1
            sentence = clean_tts_text(buffer[:cut])
            if sentence:
                ready.append(sentence)
            buffer = buffer[cut:].lstrip()

    if final and buffer:
        sentence = clean_tts_text(buffer)
        if sentence:
            ready.append(sentence)
        buffer = ""

    return ready, buffer


def imgmsg_to_bgr(msg: Image) -> np.ndarray | None:
    """Zero-dependency ROS Image to BGR converter."""
    try:
        if msg.encoding == "bgr8":
            return np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3).copy()
        elif msg.encoding == "rgb8":
            data = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
            if cv2:
                return cv2.cvtColor(data, cv2.COLOR_RGB2BGR)
            return data[:, :, ::-1].copy()
        elif msg.encoding in ("mono8", "8UC1"):
            data = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width)
            if cv2:
                return cv2.cvtColor(data, cv2.COLOR_GRAY2BGR)
            return np.stack([data]*3, axis=-1)
    except Exception:
        pass
    return None


def frame_to_base64_jpeg(frame: np.ndarray, max_dim: int = 512) -> str | None:
    """Resizes and encodes BGR frame to JPEG base64 string."""
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

        self.declare_parameter("llm_model", os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"))
        self.declare_parameter("vision_model", os.getenv("VISION_MODEL", "llama-3.2-11b-vision-preview"))
        self.declare_parameter("llm_temperature", float(os.getenv("LLM_TEMPERATURE", "0.55")))
        self.declare_parameter("llm_max_tokens", int(os.getenv("LLM_MAX_TOKENS", "300")))
        self.declare_parameter("wake_word", os.getenv("WAKE_WORD", "hey astro"))
        self.declare_parameter("conversation_timeout", float(os.getenv("CONVERSATION_TIMEOUT", "15.0")))

        self._text_model = self.get_parameter("llm_model").value
        self._vision_model = self.get_parameter("vision_model").value
        self._temperature = float(self.get_parameter("llm_temperature").value)
        self._max_tokens = int(self.get_parameter("llm_max_tokens").value)
        self._wake_word = self.get_parameter("wake_word").value
        self._conv_timeout = float(self.get_parameter("conversation_timeout").value)

        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self._enabled = True

        if not Groq:
            self.get_logger().error("❌ [AI] groq kütüphanesi kurulu değil!")
            self._enabled = False
        elif not api_key:
            self.get_logger().error("❌ [AI] GROQ_API_KEY bulunamadı! Lütfen .env dosyasını kontrol edin.")
            self._enabled = False
        else:
            try:
                self._groq = Groq(api_key=api_key)
                self.get_logger().info(f"✅ [AI] Groq LLM Aktif — Metin: {self._text_model} | Görme: {self._vision_model}")
            except Exception as e:
                self.get_logger().error(f"❌ [AI] Groq Client başlatılamadı: {e}")
                self._enabled = False

        self._state = "IDLE"
        self._last_interaction = 0.0
        self._tts_speaking = False
        self._person_detected = False
        self._latest_frame = None
        self._latest_frame_time = 0.0

        self._lock = threading.Lock()
        self._is_processing = False
        self._messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._max_history = 20

        # Publishers
        self.pub_tts = self.create_publisher(String, "/tts/say", 10)
        self.pub_interrupt = self.create_publisher(Bool, "/tts/interrupt", 10)

        # Subscribers
        self.sub_speech = self.create_subscription(String, "/speech/text", self._on_speech, 10)
        self.sub_tts_status = self.create_subscription(Bool, "/tts/speaking", self._on_tts_speaking, 10)
        self.sub_vision_status = self.create_subscription(Bool, "/vision/person_detected", self._on_person_detected, 10)
        self.sub_camera = self.create_subscription(Image, "/oak/rgb/image_raw", self._on_camera_image, 10)

        self.get_logger().info(
            f"🧠 [AI Brain] Görme ve Ses Sistemi Hazır! Wake-word: \"{self._wake_word}\""
        )

    def _on_camera_image(self, msg: Image):
        frame = imgmsg_to_bgr(msg)
        if frame is not None:
            with self._lock:
                self._latest_frame = frame
                self._latest_frame_time = time.monotonic()

    def _on_tts_speaking(self, msg: Bool):
        self._tts_speaking = msg.data

    def _on_person_detected(self, msg: Bool):
        self._person_detected = msg.data

    def _is_visual_query(self, text: str) -> bool:
        """Determines if the user's question is asking about what the robot sees."""
        visual_keywords = [
            "ne tutuyorum", "elimde ne", "elinde ne", "ne var", "bu ne", "bunu gör", "görüyor musun",
            "ne yapıyorum", "hareket", "hangi hareket", "üstümde", "ne renk", "kaç parmak",
            "bana bak", "gözlerimi", "nereye", "kim var", "odada", "arkamda", "elimde", "şuna bak"
        ]
        text_lower = text.lower()
        return any(k in text_lower for k in visual_keywords)

    def _on_speech(self, msg: String):
        raw_text = msg.data.strip()
        if not raw_text or self._tts_speaking or not self._enabled:
            return

        # Ignore pure punctuation or empty dots
        if raw_text in [".", "..", "...", "!", "?", ",", "-", "_"]:
            return

        now = time.monotonic()
        text_lower = raw_text.lower()

        # Timeout kontrolü (ACTIVE -> IDLE)
        if self._state == "ACTIVE" and (now - self._last_interaction) > self._conv_timeout:
            self._state = "IDLE"
            self.get_logger().info("💤 [AI] Sohbet zaman aşımı — Uyku moduna geçildi.")

        # Wake-word tetikleyicileri
        wake_triggers = [
            self._wake_word.lower(),
            "hey astro", "astro", "esmer", "hey groq", "grok", "merhaba", "asistan"
        ]

        if self._state == "IDLE":
            matched = any(w in text_lower for w in wake_triggers)
            if matched:
                self._state = "ACTIVE"
                self._last_interaction = now
                self.get_logger().info(f"✨ [AI] Uyandırma kelimesi algılandı: '{raw_text}'")

                # Wake word kelimelerini metinden temizle
                clean_prompt = raw_text
                for w in wake_triggers:
                    clean_prompt = re.sub(rf"(?i)\b{re.escape(w)}\b", "", clean_prompt).strip()

                if not clean_prompt or len(clean_prompt) < 3:
                    self._publish_tts("Efendim, seni dinliyorum ve görüyorum!")
                    return
                else:
                    raw_text = clean_prompt
            else:
                self._state = "ACTIVE"
                self._last_interaction = now

        # ACTIVE moddayız
        self._last_interaction = now
        self._publish_interrupt()

        with self._lock:
            if self._is_processing:
                return
            self._is_processing = True
            
            # Grab current camera frame if available and recent (< 3.0s)
            captured_frame = None
            if self._latest_frame is not None and (now - self._latest_frame_time) < 3.0:
                captured_frame = self._latest_frame.copy()

        threading.Thread(target=self._process_llm, args=(raw_text, captured_frame), daemon=True).start()

    def _process_llm(self, user_text: str, frame: np.ndarray | None):
        try:
            self.get_logger().info(f"🗣️ [Siz]: \"{user_text}\"")

            is_visual = self._is_visual_query(user_text) or (frame is not None and self._person_detected)
            base64_img = None

            if frame is not None and (is_visual or self._is_visual_query(user_text)):
                base64_img = frame_to_base64_jpeg(frame, max_dim=512)

            # Choose model: Vision model if image is attached, otherwise fast text model
            if base64_img is not None:
                selected_model = self._vision_model
                self.get_logger().info(f"👁️ [Multimodal Vision]: OAK-D kamerasıyla anlık görüntü analiz ediliyor... (Model: {selected_model})")
                user_content = [
                    {"type": "text", "text": f"Gördüğün bu anlık kamera görüntüsüne bakarak cevap ver: {user_text}"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"},
                    },
                ]
            else:
                selected_model = self._text_model
                context_prefix = ""
                if self._person_detected:
                    context_prefix = "[Kamerada bir insan görüyorsun] "
                user_content = context_prefix + user_text

            self._messages.append({"role": "user", "content": user_content})

            if len(self._messages) > self._max_history:
                self._messages = [self._messages[0]] + self._messages[-(self._max_history - 1):]

            stream = self._groq.chat.completions.create(
                messages=self._messages,
                model=selected_model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                stream=True,
            )

            full_response = ""
            text_buffer = ""

            for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                if not token:
                    continue
                full_response += token
                text_buffer += token

                sentences, text_buffer = extract_tts_sentences(text_buffer)
                for s in sentences:
                    self._publish_tts(s)

            sentences, text_buffer = extract_tts_sentences(text_buffer, final=True)
            for s in sentences:
                self._publish_tts(s)

            if full_response.strip():
                self.get_logger().info(f"🤖 [Astro]: \"{full_response.strip()}\"")
                # Store string content in history to avoid keeping giant base64 payloads in memory
                self._messages.append({"role": "assistant", "content": full_response.strip()})

            self._last_interaction = time.monotonic()

        except Exception as e:
            self.get_logger().error(f"❌ [AI] LLM/Vision Hatası: {e}")
        finally:
            with self._lock:
                self._is_processing = False

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
