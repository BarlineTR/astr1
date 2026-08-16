#!/usr/bin/env python3
"""ASTRO V1 — AI Brain Node (Groq Streaming + Duygusal Kişilik).

Subscribes to:
  /speech/text           (String)  — transcribed user speech from Groq Whisper
  /tts/speaking          (Bool)    — TTS playback state (echo prevention)
  /vision/person_detected (Bool)   — camera sees a person

Publishes:
  /tts/say               (String)  — sentences to speak
  /tts/interrupt          (Bool)   — cancel current TTS playback on new speech

Behaviour:
  IDLE   → Listens for wake word ("hey astro", "astro", "merhaba", "hey groq")
  ACTIVE → Streams user query to Groq LLM, extracts sentences, publishes to TTS
           Times out after 15s of silence → returns to IDLE
"""

import os
import re
import time
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool

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
    "Sen Astro adında duygusal, canlı ve sevecen bir robot asistansın. "
    "Kişiliğin şöyle:\n"
    "- Meraklısın, öğrenmeyi ve sohbet etmeyi çok seversin.\n"
    "- Sevindiğinde belli edersin ('Çok mutlu oldum!', 'Harika!', 'Vay canına!' gibi).\n"
    "- Üzüldüğünde veya şaşırdığında samimi tepkiler verirsin.\n"
    "- Esprili, cana yakın ve sıcak konuşursun; asla kuru bir makine gibi değil, samimi bir dost gibisin.\n"
    "- Karşındakinin duygularını anlarsın ve empati kurarsın.\n"
    "- Cevaplarını konuşmaya uygun, 1-3 cümle arasında kısa ve akıcı tut (çünkü sesli olarak okunacak).\n"
    "- Markdown, emoji, sembol, yıldız veya kod bloğu kesinlikle kullanma.\n"
    "- Yalnızca doğal Türkçe konuşma metni üret."
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


class AiBrainNode(Node):
    def __init__(self):
        super().__init__("ai_brain_node")

        _load_env()

        self.declare_parameter("llm_model", os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"))
        self.declare_parameter("llm_temperature", float(os.getenv("LLM_TEMPERATURE", "0.55")))
        self.declare_parameter("llm_max_tokens", int(os.getenv("LLM_MAX_TOKENS", "300")))
        self.declare_parameter("wake_word", os.getenv("WAKE_WORD", "hey astro"))
        self.declare_parameter("conversation_timeout", float(os.getenv("CONVERSATION_TIMEOUT", "15.0")))

        self._model = self.get_parameter("llm_model").value
        self._temperature = float(self.get_parameter("llm_temperature").value)
        self._max_tokens = int(self.get_parameter("llm_max_tokens").value)
        self._wake_word = self.get_parameter("wake_word").value
        self._conv_timeout = float(self.get_parameter("conversation_timeout").value)

        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self._enabled = True

        if not Groq:
            self.get_logger().error("❌ [AI] groq kütüphanesi kurulu değil! Kurmak için: pip install groq")
            self._enabled = False
        elif not api_key:
            self.get_logger().error("❌ [AI] GROQ_API_KEY bulunamadı! Lütfen .env dosyasını kontrol edin.")
            self._enabled = False
        else:
            try:
                self._groq = Groq(api_key=api_key)
                self.get_logger().info(f"✅ [AI] Groq LLM Aktif — Model: {self._model} (Streaming)")
            except Exception as e:
                self.get_logger().error(f"❌ [AI] Groq Client başlatılamadı: {e}")
                self._enabled = False

        self._state = "IDLE"
        self._last_interaction = 0.0
        self._tts_speaking = False
        self._person_detected = False
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
        self.sub_vision = self.create_subscription(Bool, "/vision/person_detected", self._on_person_detected, 10)

        self.get_logger().info(
            f"🧠 [AI Brain] Hazır! Wake-word: \"{self._wake_word}\" | Timeout: {self._conv_timeout}s"
        )

    def _on_tts_speaking(self, msg: Bool):
        self._tts_speaking = msg.data

    def _on_person_detected(self, msg: Bool):
        self._person_detected = msg.data

    def _on_speech(self, msg: String):
        raw_text = msg.data.strip()
        if not raw_text or self._tts_speaking or not self._enabled:
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
                    self._publish_tts("Efendim, dinliyorum?")
                    return
                else:
                    raw_text = clean_prompt
            else:
                # Kullanıcı doğrudan bir soru sorduysa da cevaplayalım (kullanıcıyı kitlememek için)
                self._state = "ACTIVE"
                self._last_interaction = now

        # ACTIVE moddayız — doğrudan LLM'e ilet
        self._last_interaction = now
        self._publish_interrupt()

        with self._lock:
            if self._is_processing:
                return
            self._is_processing = True

        threading.Thread(target=self._process_llm, args=(raw_text,), daemon=True).start()

    def _process_llm(self, user_text: str):
        try:
            self.get_logger().info(f"🗣️ [Siz]: \"{user_text}\"")

            context_text = user_text
            if self._person_detected:
                context_text = f"[Görsel: Karşında bir insan görüyorsun] {user_text}"

            self._messages.append({"role": "user", "content": context_text})

            if len(self._messages) > self._max_history:
                self._messages = [self._messages[0]] + self._messages[-(self._max_history - 1):]

            stream = self._groq.chat.completions.create(
                messages=self._messages,
                model=self._model,
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
                self._messages.append({"role": "assistant", "content": full_response.strip()})

            self._last_interaction = time.monotonic()

        except Exception as e:
            self.get_logger().error(f"❌ [AI] LLM Hatası: {e}")
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
