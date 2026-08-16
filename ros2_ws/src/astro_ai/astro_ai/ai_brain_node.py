#!/usr/bin/env python3
"""ASTRO V1 — AI Brain Node (Groq Streaming + Duygusal Kişilik).

Subscribes to:
  /speech/text           (String)  — transcribed user speech
  /tts/speaking          (Bool)    — TTS playback state
  /vision/person_detected (Bool)   — camera sees a person

Publishes:
  /tts/say               (String)  — sentences to speak
  /tts/interrupt          (Bool)   — cancel current TTS (when new user speech arrives)

Behaviour:
  IDLE   → Listens for wake word ("hey astro", "astro", "merhaba")
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
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

TTS_MIN_CHARS = 70
TTS_MAX_CHARS = 260

EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27FF]|[\u2000-\u2BFF]")

SYSTEM_PROMPT = (
    "Sen Astro adında duygusal, canlı ve sevecen bir robotsun. "
    "Kişiliğin şöyle:\n"
    "- Meraklısın, öğrenmeyi çok seversin\n"
    "- Sevindiğinde belli edersin, 'Çok mutlu oldum!', 'Harika!' gibi ifadeler kullanırsın\n"
    "- Üzüldüğünde de belli edersin, 'Bu beni biraz üzdü...' gibi\n"
    "- Esprili ve samimi konuşursun, robot gibi değil arkadaş gibi\n"
    "- Karşındakinin duygularını anlarsın ve empati kurarsın\n"
    "- Kısa ve öz konuşursun ama sıcak ve cana yakınsın\n"
    "- 2-3 cümleyi geçme, çünkü sesli okunacak\n"
    "- Markdown, emoji, sembol, kod bloğu kullanma\n"
    "- Sadece doğal Türkçe konuşma metni üret"
)

def clean_tts_text(text: str) -> str:
    # Remove markdown chars
    t = text.replace("*", "").replace("#", "").replace("_", "").replace("`", "")
    # Remove emojis
    t = EMOJI_RE.sub("", t)
    # Replace newlines with space
    t = t.replace("\n", " ")
    # Clean up multiple spaces
    t = re.sub(r"\s+", " ", t).strip()
    return t

def extract_tts_sentences(buffer: str, final=False) -> tuple[list[str], str]:
    ready_sentences = []
    delimiters = [". ", "? ", "! ", ": ", "\n"]
    
    while True:
        min_idx = -1
        delim_len = 0
        for d in delimiters:
            idx = buffer.find(d)
            if idx != -1:
                if min_idx == -1 or idx < min_idx:
                    min_idx = idx
                    delim_len = len(d)
                    
        if min_idx == -1:
            break
            
        sentence = buffer[:min_idx].strip()
        
        # Check if length satisfies minimum before splitting
        if len(sentence) < TTS_MIN_CHARS and not final:
            break
            
        buffer = buffer[min_idx + delim_len:].lstrip()
        
        if len(sentence) > TTS_MAX_CHARS:
            split_idx = sentence.rfind(", ", 0, TTS_MAX_CHARS)
            if split_idx == -1:
                split_idx = TTS_MAX_CHARS
                
            first = sentence[:split_idx].strip()
            second = sentence[split_idx:].strip()
            
            cleaned = clean_tts_text(first)
            if cleaned:
                ready_sentences.append(cleaned)
                
            buffer = second + " " + buffer
            continue
            
        cleaned = clean_tts_text(sentence)
        if cleaned:
            ready_sentences.append(cleaned)
            
    if final and buffer:
        cleaned = clean_tts_text(buffer)
        if cleaned:
            ready_sentences.append(cleaned)
        buffer = ""
        
    return ready_sentences, buffer

class AiBrainNode(Node):
    def __init__(self):
        super().__init__('ai_brain_node')
        
        self.declare_parameter("llm_model", "llama-3.3-70b-versatile")
        self.declare_parameter("llm_temperature", 0.55)
        self.declare_parameter("llm_max_tokens", 300)
        self.declare_parameter("wake_word", "hey astro")
        self.declare_parameter("conversation_timeout", 15)
        
        self._model = self.get_parameter("llm_model").value
        self._temperature = self.get_parameter("llm_temperature").value
        self._max_tokens = self.get_parameter("llm_max_tokens").value
        self._wake_word = self.get_parameter("wake_word").value
        self._conv_timeout = self.get_parameter("conversation_timeout").value
        
        api_key = os.environ.get("GROQ_API_KEY", "")
        self._enabled = True
        
        if not Groq:
            self.get_logger().error("[AI] groq kütüphanesi bulunamadı! AI devre dışı.")
            self._enabled = False
        elif not api_key:
            self.get_logger().error("[AI] GROQ_API_KEY bulunamadı! AI devre dışı.")
            self._enabled = False
        else:
            self._groq = Groq(api_key=api_key)
            
        self._state = "IDLE"
        self._last_interaction = time.monotonic()
        self._tts_speaking = False
        self._person_detected = False
        self._lock = threading.Lock()
        self._is_processing = False
        self._messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._max_history = 20
        
        self.pub_tts = self.create_publisher(String, '/tts/say', 10)
        self.pub_interrupt = self.create_publisher(Bool, '/tts/interrupt', 10)
        
        self.sub_speech = self.create_subscription(String, '/speech/text', self._on_speech, 10)
        self.sub_tts_status = self.create_subscription(Bool, '/tts/speaking', self._on_tts_speaking, 10)
        self.sub_vision = self.create_subscription(Bool, '/vision/person_detected', self._on_person_detected, 10)
        
        if self._enabled:
            self.get_logger().info(f"[AI] Başlatıldı. Model: {self._model}")
        
    def _on_tts_speaking(self, msg: Bool):
        self._tts_speaking = msg.data
        
    def _on_person_detected(self, msg: Bool):
        self._person_detected = msg.data
        
    def _on_speech(self, msg: String):
        text = msg.data.strip()
        if not text or self._tts_speaking or not self._enabled:
            return
            
        now = time.monotonic()
        
        if self._state == "ACTIVE" and (now - self._last_interaction) > self._conv_timeout:
            self._state = "IDLE"
            
        if self._state == "IDLE":
            wake_words = [self._wake_word.lower(), "astro", "merhaba"]
            text_lower = text.lower()
            
            matched = False
            for w in wake_words:
                if w in text_lower:
                    matched = True
                    text = re.sub(rf"(?i)\b{w}\b", "", text).strip()
                    break
                    
            self._state = "ACTIVE"
            if matched:
                self.get_logger().info("[AI] Uyandırma kelimesi algılandı, Aktif.")
                if not text:
                    self._publish_tts("Efendim, dinliyorum?")
                    return

        self._last_interaction = now
        self._publish_interrupt()
        
        with self._lock:
            if self._is_processing:
                return
            self._is_processing = True
            
        threading.Thread(target=self._process_llm, args=(text,), daemon=True).start()

    def _process_llm(self, user_text: str):
        try:
            context_text = user_text
            if self._person_detected:
                context_text = f"[Kamera: Birini görüyorum] {user_text}"
                
            self._messages.append({"role": "user", "content": context_text})
            
            if len(self._messages) > self._max_history:
                self._messages = [self._messages[0]] + self._messages[-(self._max_history-1):]
                
            stream = self._groq.chat.completions.create(
                messages=self._messages,
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                stream=True
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
                self._messages.append({"role": "assistant", "content": full_response.strip()})
                
            self._last_interaction = time.monotonic()
            
        except Exception as e:
            self.get_logger().error(f"[AI] LLM Hatası: {e}")
        finally:
            with self._lock:
                self._is_processing = False

    def _publish_tts(self, text: str):
        msg = String()
        msg.data = text
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

if __name__ == '__main__':
    main()
