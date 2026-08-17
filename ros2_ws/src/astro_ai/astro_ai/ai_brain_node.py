#!/usr/bin/env python3
"""ASTRO V1 — Multimodal AI Brain Node with Dynamic Vision Discovery & Long-Term Memory.

Features:
  - Dynamic Vision Model Discovery: Automatically selects the active vision model from Groq API (e.g. qwen/qwen3.6-27b, etc.)
  - True Multimodal Vision: Real-time OAK-D camera image analysis
  - Zero Hallucination: Strict visual grounding (speaks only what it truly sees)
  - Long-Term Memory (astro_memory.json): Remembers user names and facts
  - Ultra-Fast Streaming TTS: First sentence spoken in <150ms
  - Rıfkı Persona: Emotional, witty, friendly Turkish conversational agent
"""

import os
import re
import time
import json
import codecs
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
    import requests
except ImportError:
    requests = None

# Google Gemini — REST üzerinden konuşulur (SDK bağımlılığı yok, requests yeter).
GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
# "gemini-3.7-flash" gibi sürümlü, genel kullanıma açık flash modelleri yakalar.
# preview/lite/image/tts türevleri bilinçli olarak dışarıda: robot sohbeti için
# düşük gecikmeli ama tam yetenekli, kararlı bir model isteniyor.
GEMINI_FLASH_RE = re.compile(r"^gemini-(\d+)(?:\.(\d+))?-flash$")
# ListModels çağrısı başarısız olursa bu sırayla denenir. "-latest" takma adı
# Google tarafından güncel flash modele yönlendirilir; sürüm sabitlemekten daha
# dayanıklıdır (örn. gemini-2.5-flash artık yeni anahtarlara 404 dönüyor).
GEMINI_MODEL_FALLBACKS = ("gemini-flash-latest",)

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
    """Persistent Long-Term Memory for ASTRO V1."""
    def __init__(self, filepath=None):
        if filepath is None:
            self.filepath = os.path.expanduser("~/Desktop/astr1/ros2_ws/astro_memory.json")
        else:
            self.filepath = filepath
        self.data = {
            "owner_name": None,
            "user_facts": [],
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

    def get_context_prompt(self) -> str:
        ctx = []
        if self.data.get("owner_name"):
            ctx.append(f"Kullanıcının / Sahibinin Adı: {self.data['owner_name']}")
        if self.data.get("user_facts"):
            facts_str = "; ".join(self.data["user_facts"][-5:])
            ctx.append(f"Kullanıcı hakkında bildiklerin: {facts_str}")
        if ctx:
            return "Hafızandaki Bilgiler:\n" + "\n".join(ctx)
        return ""


def clean_tts_text(text: str) -> str:
    if not text:
        return ""
    # Strip <think>...</think> blocks if present
    text = re.sub(r"(?i)<think>[\s\S]*?</think>", "", text)
    # Strip standalone think tags
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

        # Sağlayıcı seçimi: sohbet ve görme ayrı ayrı yönlendirilebilir.
        # VISION_PROVIDER verilmezse LLM_PROVIDER neyse görme de oraya gider.
        self.provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
        self.vision_provider = (os.getenv("VISION_PROVIDER", "").strip() or self.provider).lower()

        self.declare_parameter("llm_model", os.getenv("LLM_MODEL", ""))
        self.declare_parameter("llm_temperature", float(os.getenv("LLM_TEMPERATURE", "0.55")))
        # Gemini 3.x'te düşünme tokenları da bu bütçeden düşülür: 300 token, cevabın
        # kendisine sıra gelmeden tükenip cümleyi ortasından kesiyordu.
        self.declare_parameter("llm_max_tokens", int(os.getenv("LLM_MAX_TOKENS", "1000")))
        self.declare_parameter("wake_word", os.getenv("WAKE_WORD", "hey astro"))
        self.declare_parameter("conversation_timeout", float(os.getenv("CONVERSATION_TIMEOUT", "15.0")))

        self._text_model = self.get_parameter("llm_model").value
        self._temperature = float(self.get_parameter("llm_temperature").value)
        self._max_tokens = int(self.get_parameter("llm_max_tokens").value)
        self._wake_word = self.get_parameter("wake_word").value
        self._conv_timeout = float(self.get_parameter("conversation_timeout").value)
        # "low" (varsayılan, hızlı) | "high" (daha iyi akıl yürütme, yavaş) | "off"
        self._thinking = os.getenv("LLM_THINKING", "low").strip().lower()

        self.groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self.gemini_api_key = (
            os.environ.get("GEMINI_API_KEY", "")
            or os.environ.get("GOOGLE_API_KEY", "")
        ).strip()
        self._groq = None
        self._vision_model = None
        self._enabled = False
        self._last_finish_reason = None

        if self.provider == "gemini":
            self._init_gemini()
        elif self.provider == "groq":
            self._init_groq()
        else:
            self.get_logger().error(
                f"❌ [AI] Bilinmeyen LLM_PROVIDER: \"{self.provider}\" — \"gemini\" veya \"groq\" olmalı"
            )

        # Görme farklı bir sağlayıcıdan isteniyorsa onun istemcisi de hazırlanmalı.
        if self._enabled and self.vision_provider == "groq" and self._groq is None:
            self._init_groq(as_vision_only=True)

        self._state = "IDLE"
        self._last_interaction = 0.0
        self._tts_speaking = False
        self._person_detected = False
        self._latest_frame = None
        self._latest_frame_time = 0.0

        self._lock = threading.Lock()
        self._is_processing = False
        self._messages = []
        self._max_history = 20
        self._build_initial_messages()

        # Publishers
        self.pub_tts = self.create_publisher(String, "/tts/say", 10)
        self.pub_interrupt = self.create_publisher(Bool, "/tts/interrupt", 10)

        # Subscribers
        self.sub_speech = self.create_subscription(String, "/speech/text", self._on_speech, 10)
        self.sub_tts_status = self.create_subscription(Bool, "/tts/speaking", self._on_tts_speaking, 10)
        self.sub_vision_status = self.create_subscription(Bool, "/vision/person_detected", self._on_person_detected, 10)
        self.sub_camera = self.create_subscription(Image, "/oak/rgb/image_raw", self._on_camera_image, 10)

        owner = self.memory.data.get("owner_name")
        owner_info = f" (Tanınan Kişi: {owner})" if owner else ""
        if self._enabled:
            self.get_logger().info(
                f"🧠 [AI Brain] Görme, Hafıza ve Ses Sistemi Hazır! Wake-word: \"{self._wake_word}\"{owner_info}"
            )
        else:
            self.get_logger().error(
                "🧠 [AI Brain] LLM devre dışı — düğüm ayakta ama konuşulanlara cevap veremez. "
                "Yukarıdaki hatayı giderip yeniden başlatın."
            )

    # ------------------------------------------------------------------
    # Sağlayıcı kurulumu
    # ------------------------------------------------------------------
    def _init_gemini(self):
        """Google Gemini (REST) — sohbet için varsayılan sağlayıcı."""
        if requests is None:
            self.get_logger().error("❌ [AI] requests paketi yok — Gemini kullanılamaz")
            return
        if not self.gemini_api_key:
            self.get_logger().error(
                "❌ [AI] GEMINI_API_KEY bulunamadı! .env dosyanıza ekleyin "
                "(anahtar: https://aistudio.google.com/apikey)"
            )
            return

        self._text_model = self._text_model or self._discover_gemini_model()
        if self.vision_provider == "gemini":
            self._vision_model = self._text_model
        self._enabled = True
        self.get_logger().info(
            f"✅ [AI] Google Gemini aktif — Metin: {self._text_model} | Görme: "
            f"{self._vision_model if self.vision_provider == 'gemini' else self.vision_provider}"
        )

    def _init_groq(self, as_vision_only: bool = False):
        """Groq — LLM_PROVIDER=\"groq\" ile seçilir, ayrıca görme için kullanılabilir."""
        if Groq is None or not self.groq_api_key:
            msg = "❌ [AI] GROQ_API_KEY bulunamadı veya groq paketi kurulu değil"
            if as_vision_only:
                self.get_logger().warn(f"{msg} — görsel sorular yanıtlanamayacak")
            else:
                self.get_logger().error(f"{msg}! LLM devre dışı.")
            return
        try:
            self._groq = Groq(api_key=self.groq_api_key)
            self._vision_model = self._discover_vision_model()
            if as_vision_only:
                self.get_logger().info(f"✅ [AI] Groq görme için hazır: {self._vision_model}")
                return
            self._text_model = self._text_model or "llama-3.3-70b-versatile"
            self._enabled = True
            self.get_logger().info(
                f"✅ [AI] Groq aktif — Metin: {self._text_model} | Görme: {self._vision_model}"
            )
        except Exception as e:
            self.get_logger().error(f"❌ [AI] Groq Client başlatılamadı: {e}")

    def _discover_gemini_model(self) -> str:
        """Anahtarın erişebildiği en güncel kararlı flash modelini seçer.

        Model adları hızla değişiyor (gemini-2.5 → 3.x → …); sabit bir ada bağlanmak
        yerine API'ye sormak, kod eskidiğinde bile güncel modeli bulmayı sağlar.
        Sürümler metin olarak değil sayı olarak karşılaştırılır: 3.10 > 3.7.
        """
        try:
            res = requests.get(
                f"{GEMINI_API_ROOT}/models",
                headers={"x-goog-api-key": self.gemini_api_key},
                timeout=10.0,
            )
            res.raise_for_status()
            available = [
                m["name"].split("/", 1)[-1]
                for m in res.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]

            versioned = []
            for name in available:
                match = GEMINI_FLASH_RE.match(name)
                if match:
                    major, minor = match.groups()
                    versioned.append(((int(major), int(minor or 0)), name))
            if versioned:
                return max(versioned)[1]

            for fallback in GEMINI_MODEL_FALLBACKS:
                if fallback in available:
                    return fallback
            if available:
                return available[0]
        except Exception as e:
            self.get_logger().warn(f"Gemini model listesi alınamadı ({e}) — varsayılana düşülüyor")
        return GEMINI_MODEL_FALLBACKS[0]

    def _discover_vision_model(self) -> str:
        """Queries Groq API to discover active multimodal vision model."""
        try:
            models = self._groq.models.list()
            available = [m.id for m in models.data]
            
            # Look for vision-capable models in priority order
            for cand in ["qwen/qwen3.6-27b", "meta-llama/llama-4-scout-preview", "llama-3.2-90b-vision-preview"]:
                if cand in available:
                    return cand
            
            # Find any active model with vision/multimodal/qwen keyword
            for m_id in available:
                if any(k in m_id.lower() for k in ["vision", "vl", "multimodal", "qwen3"]):
                    return m_id
        except Exception as e:
            self.get_logger().warn(f"Vision model discovery failed ({e}), using default qwen/qwen3.6-27b")
        
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
        
        # Strict explicit name introduction patterns
        patterns = [
            r"\b(?:benim\s+adım|adım|ismim)\s+([a-zA-ZçğıöşüÇĞİÖŞÜ]{3,15})\b",
            r"\bbana\s+([a-zA-ZçğıöşüÇĞİÖŞÜ]{3,15})\s+(?:de|diyebilirsin|dersin)\b",
            r"\bbeni\s+([a-zA-ZçğıöşüÇĞİÖŞÜ]{3,15})\s+olarak\s+(?:kaydet|hatırla|bil)\b",
        ]
        
        # Blacklist of common non-name words
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

                clean_prompt = raw_text
                for w in wake_triggers:
                    clean_prompt = re.sub(rf"(?i)\b{re.escape(w)}\b", "", clean_prompt).strip()

                owner = self.memory.data.get("owner_name")
                greeting = f"Efendim {owner}, seni dinliyorum ve görüyorum!" if owner else "Efendim, seni dinliyorum ve görüyorum!"

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

        # Learn names or facts if present
        self._check_and_learn_memory(raw_text)

        with self._lock:
            if self._is_processing:
                return
            self._is_processing = True

            captured_frame = None
            if self._latest_frame is not None and (now - self._latest_frame_time) < 4.0:
                captured_frame = self._latest_frame.copy()

        threading.Thread(target=self._process_llm, args=(raw_text, captured_frame), daemon=True).start()

    # ------------------------------------------------------------------
    # Google Gemini — REST çağrıları
    # ------------------------------------------------------------------
    def _gemini_url(self, method: str) -> str:
        return f"{GEMINI_API_ROOT}/models/{self._text_model}:{method}"

    @staticmethod
    def _to_gemini_contents(messages):
        """OpenAI biçimli geçmişi Gemini'nin contents + systemInstruction yapısına çevirir.

        Gemini'de sistem istemi ayrı bir alandır ve asistan rolünün adı "model"dir.
        """
        system_parts = []
        contents = []
        for m in messages:
            role, content = m.get("role"), m.get("content", "")
            if not content:
                continue
            if role == "system":
                system_parts.append(content)
            else:
                contents.append({
                    "role": "model" if role == "assistant" else "user",
                    "parts": [{"text": content}],
                })
        system_instruction = {"parts": [{"text": "\n\n".join(system_parts)}]} if system_parts else None
        return contents, system_instruction

    def _gemini_generation_config(self, temperature=None, max_tokens=None) -> dict:
        config = {
            "temperature": self._temperature if temperature is None else temperature,
            "maxOutputTokens": self._max_tokens if max_tokens is None else max_tokens,
        }
        # Gemini 3.x'te "düşünme" tokenları maxOutputTokens bütçesinden harcanır:
        # varsayılan ayarla 300 tokenin 287'si düşünmeye gidip cevap yarıda kesiliyordu.
        # Robot sohbetinde düşük gecikme istediğimiz için düşünme kısılır.
        if self._thinking != "off":
            config["thinkingConfig"] = {"thinkingLevel": self._thinking}
        return config

    def _gemini_post(self, url: str, payload: dict, timeout: float, stream: bool = False):
        """Gemini'ye POST atar; geçici hatalarda tekrar dener.

        - 503/429: sunucu yoğun ya da kota — kısa beklemeyle yeniden denenir.
        - 400 + thinkingConfig: model bu parametreyi tanımıyor (eski nesil) — parametre
          çıkarılıp bir kez daha denenir.
        """
        headers = {"x-goog-api-key": self.gemini_api_key, "Content-Type": "application/json"}
        for attempt in range(3):
            res = requests.post(url, headers=headers, json=payload, timeout=timeout, stream=stream)
            if res.status_code in (429, 503) and attempt < 2:
                if stream:
                    res.close()
                reason = "kota doldu (429)" if res.status_code == 429 else "sunucu meşgul (503)"
                self.get_logger().warn(f"Gemini {reason} — yeniden deneniyor")
                time.sleep(1.5 * (attempt + 1))
                continue
            if res.status_code == 429:
                self.get_logger().error(
                    "❌ [AI] Gemini kotası doldu (429). Ücretsiz katmanda dakika/gün başına "
                    "istek sınırı vardır — biraz bekleyin veya faturalandırmayı açın."
                )
            if res.status_code == 400 and "thinkingConfig" in payload.get("generationConfig", {}):
                if "thinking" in res.text.lower():
                    if stream:
                        res.close()
                    self.get_logger().warn("Model thinkingConfig desteklemiyor — parametresiz denenecek")
                    payload["generationConfig"].pop("thinkingConfig", None)
                    continue
            return res
        return res

    def _stream_gemini(self, messages):
        """Yanıtı parça parça üretir — ilk cümle tamamlanır tamamlanmaz TTS'e gider."""
        contents, system_instruction = self._to_gemini_contents(messages)
        payload = {"contents": contents, "generationConfig": self._gemini_generation_config()}
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        # alt=sse olmadan API tek parça JSON dizisi döndürür ve akış avantajı kaybolur.
        with self._gemini_post(
            self._gemini_url("streamGenerateContent") + "?alt=sse",
            payload,
            timeout=60.0,
            stream=True,
        ) as res:
            if res.status_code != 200:
                raise RuntimeError(f"Gemini HTTP {res.status_code}: {res.text[:300]}")
            yield from self._parse_sse(res)

    def _parse_sse(self, res):
        """SSE akışını satır satır çözer ve metin parçalarını üretir.

        `requests.iter_lines()` kullanılmıyor: charset başlıkta gelmediğinde ISO-8859-1
        varsayıp Türkçe karakterleri bozuyor ("gören" -> "gÃ¶ren") ve çok baytlı bir
        karakter iki TCP parçasına bölündüğünde satırı sakatlayabiliyor. Artımlı UTF-8
        çözücü + elle satır tamponu ikisini de kökten çözer.
        """
        decoder = codecs.getincrementaldecoder("utf-8")()
        buffer = ""

        def handle(line: str):
            line = line.strip()
            if not line.startswith("data:"):
                return None
            chunk = line[len("data:"):].strip()
            if not chunk or chunk == "[DONE]":
                return None
            try:
                return json.loads(chunk)
            except json.JSONDecodeError:
                self.get_logger().warn(f"Gemini akışında çözülemeyen olay: {chunk[:120]}")
                return None

        def emit(data):
            for candidate in data.get("candidates", []):
                if candidate.get("finishReason"):
                    self._last_finish_reason = candidate["finishReason"]
                for part in candidate.get("content", {}).get("parts", []):
                    text = part.get("text")
                    if text:
                        yield text

        for chunk in res.iter_content(chunk_size=None):
            buffer += decoder.decode(chunk)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                data = handle(line)
                if data:
                    yield from emit(data)

        buffer += decoder.decode(b"", True)   # yarım kalan çok baytlı karakteri bitir
        if buffer.strip():
            data = handle(buffer)
            if data:
                yield from emit(data)

    def _query_gemini_vision(self, prompt: str, base64_image: str) -> str | None:
        """Anlık kamera karesini Gemini'ye sorar (tek parça yanıt)."""
        try:
            payload = {
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"text": f"Kameradaki bu anlık görüntüye bakarak cevap ver: {prompt}"},
                        {"inline_data": {"mime_type": "image/jpeg", "data": base64_image}},
                    ],
                }],
                "systemInstruction": {"parts": [{
                    "text": (
                        f"{self._build_system_prompt()}\n\n"
                        "ÖNEMLİ: Sadece görüntüde gerçekten gördüğünü söyle, uydurma. "
                        "Kısa ve net 1-2 Türkçe cümle kur."
                    )
                }]},
                # Görmede düşük sıcaklık: uydurmayı azaltır.
                "generationConfig": self._gemini_generation_config(temperature=0.1, max_tokens=600),
            }
            res = self._gemini_post(self._gemini_url("generateContent"), payload, timeout=30.0)
            if res.status_code != 200:
                self.get_logger().error(f"❌ [Gemini Vision] HTTP {res.status_code}: {res.text[:300]}")
                return None
            parts = res.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
            return text or None
        except Exception as e:
            self.get_logger().error(f"❌ [Gemini Vision Hatası]: {e}")
            return None

    def _query_vision(self, prompt: str, base64_image: str) -> str | None:
        """Görsel soruyu seçili görme sağlayıcısına yönlendirir."""
        if self.vision_provider == "gemini":
            return self._query_gemini_vision(prompt, base64_image)
        if self._groq is not None:
            return self._query_groq_vision(prompt, base64_image)
        self.get_logger().warn(
            f"Görme sağlayıcısı \"{self.vision_provider}\" hazır değil — görsel soru yanıtlanamıyor"
        )
        return None

    def _query_groq_vision(self, prompt: str, base64_image: str) -> str | None:
        """Queries active multimodal vision model with robust extraction."""
        model_name = self._vision_model or "qwen/qwen3.6-27b"
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
            
            # Extract final answer
            if "</think>" in raw:
                actual = raw.split("</think>")[-1].strip()
                if actual:
                    return actual
            
            # If answer was purely inside think or not closed, clean think markers
            clean = re.sub(r"(?i)<\/?think>", "", raw).strip()
            return clean if clean else None
            
        except Exception as e:
            self.get_logger().error(f"❌ [Vision Model Hatası ({model_name})]: {e}")
            return None

    def _stream_llm(self, messages):
        """Seçili sağlayıcıdan yanıtı parça parça üretir."""
        if self.provider == "gemini":
            yield from self._stream_gemini(messages)
            return

        stream = self._groq.chat.completions.create(
            messages=messages,
            model=self._text_model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            stream=True,
        )
        for chunk in stream:
            if getattr(chunk, "choices", None):
                yield getattr(chunk.choices[0].delta, "content", "") or ""

    def _process_llm(self, user_text: str, frame: np.ndarray | None):
        try:
            self.get_logger().info(f"🗣️ [Siz]: \"{user_text}\"")

            is_visual = self._is_visual_query(user_text)
            base64_img = None

            if frame is not None and is_visual:
                base64_img = frame_to_base64_jpeg(frame, max_dim=512)

            # 1. GÖRSEL SORU YOLU (Multimodal Vision)
            if is_visual:
                if base64_img is not None:
                    self.get_logger().info(
                        f"👁️ [{self.vision_provider} Vision]: OAK-D kamerasıyla anlık görüntü "
                        f"analiz ediliyor... ({self._vision_model})"
                    )
                    vision_answer = self._query_vision(user_text, base64_img)
                    if vision_answer:
                        clean_ans = clean_tts_text(vision_answer)
                        self.get_logger().info(f"🤖 [Astro]: \"{clean_ans}\"")
                        self._publish_tts(clean_ans)
                        # Save string to history
                        self._messages.append({"role": "user", "content": user_text})
                        self._messages.append({"role": "assistant", "content": clean_ans})
                        self._last_interaction = time.monotonic()
                        return

                # Kamera görüntüsü yoksa veya Vision hata verdiyse ASLA ezbere uydurma!
                owner = self.memory.data.get("owner_name", "")
                name_tag = f" {owner}" if owner else ""
                fallback_msg = f"Şu an kameramdan elini veya görüntüyü net göremiyorum{name_tag}, lütfen kameraya biraz daha yaklaştırır mısın?"
                self.get_logger().info(f"🤖 [Astro]: \"{fallback_msg}\"")
                self._publish_tts(fallback_msg)
                self._last_interaction = time.monotonic()
                return

            # 2. HIZLI METİN SOHBETİ YOLU (akışlı LLM — Gemini veya Groq)
            context_prefix = ""
            if self._person_detected:
                context_prefix = "[Kamerada karşında bir insan görüyorsun] "
            user_content = context_prefix + user_text

            self._messages.append({"role": "user", "content": user_content})

            if len(self._messages) > self._max_history:
                self._messages = [self._messages[0]] + self._messages[-(self._max_history - 1):]

            full_response = ""
            text_buffer = ""
            self._last_finish_reason = None

            for token in self._stream_llm(self._messages):
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

            if self._last_finish_reason == "MAX_TOKENS":
                # Sessizce yarım cümle söylemek yerine sebebini bildir.
                self.get_logger().warn(
                    f"Cevap token sınırında kesildi (LLM_MAX_TOKENS={self._max_tokens}). "
                    "Değeri artırın ya da LLM_THINKING=\"off\" deneyin."
                )

            if full_response.strip():
                clean_full = clean_tts_text(full_response.strip())
                self.get_logger().info(f"🤖 [Astro]: \"{clean_full}\"")
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
