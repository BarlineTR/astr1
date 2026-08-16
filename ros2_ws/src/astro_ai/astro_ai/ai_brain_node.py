#!/usr/bin/env python3
"""ASTRO V1 — Autonomous Social AI Brain Node.

Key Capabilities:
  1. True Multimodal Vision: Real-time visual QA via Groq Vision (Qwen 3.6 / Llama 3.2 90B)
  2. Autonomous Learning & Reflection: Extracts facts, preferences, and objects in background
  3. Direction of Arrival (DOA) Attention: Tracks speaker angle from ReSpeaker 4-Mic
  4. Emotional & Gestural Expression: Publishes /robot/emotion and /robot/head_gesture
  5. Proactive Awareness: Detects person approaching and greets naturally
  6. Ultra-Fast Zero-Lag Streaming TTS with Rıfkı Persona
"""

import os
import re
import time
import json
import base64
import threading
import numpy as np

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool, Float32
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


TTS_MIN_CHARS = 12
TTS_MAX_CHARS = 240

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


class AstroMemory:
    """Persistent Long-Term Memory with Autonomous Knowledge Synthesis."""
    def __init__(self, filepath=None):
        if filepath is None:
            self.filepath = os.path.expanduser("~/Desktop/astr1/ros2_ws/astro_memory.json")
        else:
            self.filepath = filepath
        self.data = {
            "owner_name": "Baran",
            "user_facts": [
                "Robotun geliştiricisi",
                "Adı Baran"
            ],
            "learned_objects": {},
            "conversation_summaries": [],
            "last_interaction": None,
        }
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.data.update(saved)
            except Exception:
                pass
        # Clean corrupted names
        if self.data.get("owner_name") and str(self.data["owner_name"]).lower() in ["şarkı", "cevap", "yardım", "nasılsın"]:
            self.data["owner_name"] = "Baran"
            self.save()

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def set_owner(self, name: str):
        self.data["owner_name"] = name
        self.save()

    def add_fact(self, fact_text: str):
        if fact_text and fact_text not in self.data["user_facts"]:
            self.data["user_facts"].append(fact_text)
            if len(self.data["user_facts"]) > 30:
                self.data["user_facts"] = self.data["user_facts"][-30:]
            self.save()

    def add_object(self, obj_name: str, description: str):
        self.data.setdefault("learned_objects", {})[obj_name] = description
        self.save()

    def get_context_prompt(self) -> str:
        ctx = []
        if self.data.get("owner_name"):
            ctx.append(f"Kullanıcının / Sahibinin Adı: {self.data['owner_name']}")
        if self.data.get("user_facts"):
            facts_str = "; ".join(self.data["user_facts"][-6:])
            ctx.append(f"Kullanıcı hakkında bildiklerin: {facts_str}")
        if self.data.get("learned_objects"):
            objs = [f"{k} ({v})" for k, v in list(self.data["learned_objects"].items())[-4:]]
            ctx.append(f"Daha önce öğrendiğin özel eşyalar: {', '.join(objs)}")
        if ctx:
            return "Hafızandaki Kalıcı Bilgiler:\n" + "\n".join(ctx)
        return ""


def clean_tts_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"(?i)<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"(?i)<\/?think>", "", text)
    text = EMOJI_RE.sub("", text)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`.*?`", "", text)
    text = re.sub(r"[\*\_\~\#\<\>]", "", text)
    text = " ".join(text.split())
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

        self.memory = AstroMemory()

        self.declare_parameter("llm_model", os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"))
        self.declare_parameter("vision_model", os.getenv("VISION_MODEL", "qwen/qwen3.6-27b"))
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

        self.groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self._groq = None
        self._enabled = True

        if Groq and self.groq_api_key:
            try:
                self._groq = Groq(api_key=self.groq_api_key)
                self._vision_model = self._discover_vision_model()
                self.get_logger().info(
                    f"✅ [AI] Groq Aktif — Metin: {self._text_model} | Görme (Vision): {self._vision_model}"
                )
            except Exception as e:
                self.get_logger().error(f"❌ [AI] Groq Client başlatılamadı: {e}")
                self._enabled = False
        else:
            self.get_logger().error("❌ [AI] GROQ_API_KEY bulunamadı! STT/LLM devre dışı.")
            self._enabled = False

        self._state = "IDLE"
        self._last_interaction = 0.0
        self._tts_speaking = False
        self._person_detected = False
        self._speaker_angle = 0.0
        self._latest_frame = None
        self._latest_frame_time = 0.0
        self._unprocessed_dialogue = []

        self._lock = threading.Lock()
        self._is_processing = False
        self._messages = []
        self._max_history = 20
        self._build_initial_messages()

        # Publishers
        self.pub_tts = self.create_publisher(String, "/tts/say", 10)
        self.pub_interrupt = self.create_publisher(Bool, "/tts/interrupt", 10)
        self.pub_emotion = self.create_publisher(String, "/robot/emotion", 10)
        self.pub_gesture = self.create_publisher(String, "/robot/head_gesture", 10)
        self.pub_look_target = self.create_publisher(Float32, "/robot/look_target", 10)

        # Subscribers
        self.sub_speech = self.create_subscription(String, "/speech/text", self._on_speech, 10)
        self.sub_tts_status = self.create_subscription(Bool, "/tts/speaking", self._on_tts_speaking, 10)
        self.sub_vision_status = self.create_subscription(Bool, "/vision/person_detected", self._on_person_detected, 10)
        self.sub_doa = self.create_subscription(Float32, "/audio/doa", self._on_doa, 10)
        self.sub_camera = self.create_subscription(Image, "/oak/rgb/image_raw", self._on_camera_image, 10)

        owner = self.memory.data.get("owner_name")
        owner_info = f" (Tanınan Kişi: {owner})" if owner else ""
        self.get_logger().info(
            f"🧠 [AI Brain] Görme, Otonom Hafıza, DOA ve Ses Sistemi Hazır! Wake-word: \"{self._wake_word}\"{owner_info}"
        )

    def _discover_vision_model(self) -> str:
        try:
            models = self._groq.models.list()
            available = [m.id for m in models.data]
            for cand in ["qwen/qwen3.6-27b", "meta-llama/llama-4-scout-preview", "llama-3.2-90b-vision-preview"]:
                if cand in available:
                    return cand
            for m_id in available:
                if any(k in m_id.lower() for k in ["vision", "vl", "multimodal", "qwen3"]):
                    return m_id
        except Exception:
            pass
        return "qwen/qwen3.6-27b"

    def _build_system_prompt(self) -> str:
        base_prompt = (
            "Sen Astro adında neşeli, meraklı, duygusal ve çok zeki bir robot asistansın. "
            "Sosyal medyada sevilen Rıfkı gibi sevecen ve cana yakın bir karaktere sahipsin.\n"
            "Önemli Kuralların:\n"
            "- OAK-D kameran sayesinde karşındaki insanı, kıyafetlerini, renkleri, elindeki eşyaları ve hareketlerini GERÇEKTEN görüyorsun.\n"
            "- Asla ezbere konuşma, tahmin veya uydurma yapma. Yalnızca kamerada gördüğün gerçekleri söyle.\n"
            "- Kullanıcı sana ne giydiğini veya elinde ne olduğunu sorduğunda görseli dikkatle incele; eğer elinde hiçbir şey yoksa 'Elinde bir şey görmüyorum' de.\n"
            "- Kullanıcının adını biliyorsan arada sırada samimi şekilde kullanabilirsin ama her cümlenin başında papağan gibi tekrarlama, doğal konuş.\n"
            "- Robotik konuşma; cana yakın bir dost gibi samimi, esprili ve akıcı konuş.\n"
            "- Cevaplarını 1-2 cümle ile kısa ve öz tut (çünkü sesli okunuyor).\n"
            "- Asla markdown, emoji, yıldız (*), parantez, <think> etiketi veya kod bloğu kullanma; sadece saf Türkçe metin üret."
        )
        memory_ctx = self.memory.get_context_prompt()
        if memory_ctx:
            return f"{base_prompt}\n\n{memory_ctx}"
        return base_prompt

    def _build_initial_messages(self):
        self._messages = [{"role": "system", "content": self._build_system_prompt()}]

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

    def _on_doa(self, msg: Float32):
        self._speaker_angle = float(msg.data)

    def _is_visual_query(self, text: str) -> bool:
        visual_keywords = [
            "ne tutuyorum", "elimde ne", "elinde ne", "ne var", "bu ne", "bunu gör", "görüyor musun",
            "ne yapıyorum", "hareket", "hangi hareket", "üstümde", "üzerimde", "ceket", "tişört", "elbise",
            "ne renk", "kaç parmak", "bana bak", "gözlerimi", "nereye", "kim var", "odada", "arkamda",
            "elimde", "şuna bak", "gösteriyorum", "nası görünüyorum", "nasıl görünüyorum", "gördün mü"
        ]
        text_lower = text.lower()
        return any(k in text_lower for k in visual_keywords)

    def _check_and_learn_memory(self, user_text: str):
        text_lower = user_text.lower().strip()
        patterns = [
            r"\b(?:benim\s+adım|adım|ismim)\s+([a-zA-ZçğıöşüÇĞİÖŞÜ]{3,15})\b",
            r"\bbana\s+([a-zA-ZçğıöşüÇĞİÖŞÜ]{3,15})\s+(?:de|diyebilirsin|dersin)\b",
            r"\bbeni\s+([a-zA-ZçğıöşüÇĞİÖŞÜ]{3,15})\s+olarak\s+(?:kaydet|hatırla|bil)\b",
        ]
        blacklist = {
            "şarkı", "masal", "fıkra", "cevap", "yardım", "kahve", "yemek", "resim",
            "video", "kitap", "bilgi", "haber", "nasılsın", "merhaba", "selam", "astro",
            "robot", "asistan", "birşey", "bunu", "şunu", "kimim", "kimsin", "nedir",
            "nasıl", "neden", "niye", "hangi", "nerede", "nereye", "şimdi", "burada"
        }
        for pat in patterns:
            match = re.search(pat, text_lower)
            if match:
                candidate = match.group(1).lower()
                if candidate not in blacklist:
                    proper_name = candidate.capitalize()
                    self.memory.set_owner(proper_name)
                    self.get_logger().info(f"🧠 [Memory]: Kullanıcı adı hafızaya kaydedildi -> {proper_name}")
                    self._messages[0]["content"] = self._build_system_prompt()
                    break

    def _on_speech(self, msg: String):
        raw_text = msg.data.strip()
        if not raw_text or self._tts_speaking or not self._enabled:
            return

        if raw_text in [".", "..", "...", "!", "?", ",", "-", "_"]:
            return

        now = time.monotonic()
        text_lower = raw_text.lower()

        # Turn head/look toward speaker angle
        if self._speaker_angle > 0:
            target_msg = Float32()
            target_msg.data = self._speaker_angle
            self.pub_look_target.publish(target_msg)

        # Timeout kontrolü (ACTIVE -> IDLE & Trigger Background Reflection)
        if self._state == "ACTIVE" and (now - self._last_interaction) > self._conv_timeout:
            self._state = "IDLE"
            self.get_logger().info("💤 [AI] Sohbet zaman aşımı — Uyku moduna geçildi.")
            # Trigger background autonomous reflection
            threading.Thread(target=self._run_autonomous_reflection, daemon=True).start()

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
                self._publish_emotion("happy")
                self._publish_gesture("nod")

                clean_prompt = raw_text
                for w in wake_triggers:
                    clean_prompt = re.sub(rf"(?i)\b{re.escape(w)}\b", "", clean_prompt).strip()

                owner = self.memory.data.get("owner_name")
                greeting = f"Efendim {owner}, dinliyorum!" if owner else "Efendim, seni dinliyorum!"

                if not clean_prompt or len(clean_prompt) < 3:
                    self._publish_tts(greeting)
                    return
                else:
                    raw_text = clean_prompt
            else:
                self._state = "ACTIVE"
                self._last_interaction = now

        self._last_interaction = now
        self._publish_interrupt()

        self._check_and_learn_memory(raw_text)

        with self._lock:
            if self._is_processing:
                return
            self._is_processing = True

            captured_frame = None
            if self._latest_frame is not None and (now - self._latest_frame_time) < 4.0:
                captured_frame = self._latest_frame.copy()

        threading.Thread(target=self._process_llm, args=(raw_text, captured_frame), daemon=True).start()

    def _query_groq_vision(self, prompt: str, base64_image: str) -> str | None:
        model_name = self._vision_model or "qwen/qwen3.6-27b"
        self._publish_emotion("curious")
        self._publish_gesture("tilt")
        try:
            response = self._groq.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"{self._build_system_prompt()}\n\n"
                            "ÖNEMLİ: Asla düşünce veya açıklama yazma. Doğrudan kamerada gördüğün gerçekleri kısa ve net 1-2 Türkçe cümleyle söyle."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Kameradaki bu anlık görüntüye bakarak cevap ver: {prompt}",
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                            },
                        ],
                    }
                ],
                model=model_name,
                temperature=0.1,
                max_tokens=600,
            )
            raw = response.choices[0].message.content.strip()
            
            if "</think>" in raw:
                actual = raw.split("</think>")[-1].strip()
                if actual:
                    return actual
            
            clean = re.sub(r"(?i)<\/?think>", "", raw).strip()
            return clean if clean else None
            
        except Exception as e:
            self.get_logger().error(f"❌ [Vision Model Hatası ({model_name})]: {e}")
            return None

    def _run_autonomous_reflection(self):
        """Autonomous Background Reflection: Learns facts and habits from recent dialogues."""
        if not self._groq or not self._unprocessed_dialogue:
            return
        try:
            with self._lock:
                dialogue_text = "\n".join(self._unprocessed_dialogue[-10:])
                self._unprocessed_dialogue.clear()

            self.get_logger().info("🧠 [Otonom Öğrenme]: Son sohbetten yeni bilgiler çıkarılıyor...")
            prompt = (
                "Sen bir robotun hafıza analiz modülüsün. Aşağıdaki diyalogdan kullanıcı hakkında öğrenilen "
                "yeni bir bilgi (ilgi alanı, işi, hobisi, yaptığı şey) veya gösterdiği özel bir eşya var mı?\n"
                f"Diyalog:\n{dialogue_text}\n\n"
                "Varsa sadece kısa tek bir Türkçe cümle olarak yaz (örnek: 'Robotik ve yazılımla ilgileniyor'). "
                "Yoksa sadece 'YOK' yaz."
            )
            res = self._groq.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self._text_model,
                temperature=0.2,
                max_tokens=100
            )
            extracted = res.choices[0].message.content.strip()
            if extracted and "YOK" not in extracted.upper() and len(extracted) > 5:
                self.memory.add_fact(extracted)
                self.get_logger().info(f"✨ [Otonom Hafıza Kazandı]: \"{extracted}\"")
                self._messages[0]["content"] = self._build_system_prompt()
        except Exception as e:
            self.get_logger().warn(f"Reflection hatası: {e}")

    def _process_llm(self, user_text: str, frame: np.ndarray | None):
        try:
            self.get_logger().info(f"🗣️ [Siz]: \"{user_text}\"")
            self._unprocessed_dialogue.append(f"Kullanıcı: {user_text}")

            is_visual = self._is_visual_query(user_text)
            base64_img = None

            if frame is not None and is_visual:
                base64_img = frame_to_base64_jpeg(frame, max_dim=512)

            # 1. GÖRSEL SORU YOLU (Multimodal Vision)
            if is_visual:
                if base64_img is not None:
                    self.get_logger().info(f"👁️ [Groq Vision]: OAK-D görüntüsü analiz ediliyor... ({self._vision_model})")
                    vision_answer = self._query_groq_vision(user_text, base64_img)
                    if vision_answer:
                        clean_ans = clean_tts_text(vision_answer)
                        self.get_logger().info(f"🤖 [Astro]: \"{clean_ans}\"")
                        self._publish_tts(clean_ans)
                        self._publish_emotion("happy")
                        self._unprocessed_dialogue.append(f"Astro: {clean_ans}")
                        self._messages.append({"role": "user", "content": user_text})
                        self._messages.append({"role": "assistant", "content": clean_ans})
                        self._last_interaction = time.monotonic()
                        return

                owner = self.memory.data.get("owner_name", "")
                name_tag = f" {owner}" if owner else ""
                fallback_msg = f"Şu an kameramdan görüntüyü net göremiyorum{name_tag}, lütfen kameraya biraz daha yaklaştırır mısın?"
                self.get_logger().info(f"🤖 [Astro]: \"{fallback_msg}\"")
                self._publish_tts(fallback_msg)
                self._publish_emotion("thinking")
                self._publish_gesture("tilt")
                self._last_interaction = time.monotonic()
                return

            # 2. HIZLI METİN SOHBETİ YOLU (Groq Streaming LLM)
            self._publish_emotion("happy")
            context_prefix = ""
            if self._person_detected:
                context_prefix = "[Kamerada karşında bir insan görüyorsun] "
            user_content = context_prefix + user_text

            self._messages.append({"role": "user", "content": user_content})

            if len(self._messages) > self._max_history:
                self._messages = [self._messages[0]] + self._messages[-(self._max_history - 1):]

            stream = self._groq.chat.completions.create(
                messages=self._messages,
                model=self._text_model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                stream=True,
            )

            full_response = ""
            text_buffer = ""

            for chunk in stream:
                token = ""
                if hasattr(chunk, 'choices') and chunk.choices:
                    delta = chunk.choices[0].delta
                    token = getattr(delta, 'content', '') or ""

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
                clean_full = clean_tts_text(full_response.strip())
                self.get_logger().info(f"🤖 [Astro]: \"{clean_full}\"")
                self._unprocessed_dialogue.append(f"Astro: {clean_full}")
                self._messages.append({"role": "assistant", "content": clean_full})

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
