#!/usr/bin/env python3
"""ASTRO V1 — Autonomous Social AI Brain Node with Adaptive Linguistic Mirroring.

Key Capabilities:
  1. True Multimodal Vision: Real-time visual QA via Groq Vision (Qwen 3.6 / Llama 3.2 90B)
  2. Adaptive Linguistic Style Matching (Ayna Nöron / Tarz Öğrenme):
     - Karşısındaki kişinin konuşma tarzını, argo/sokak/resmi/kibar dilini öğrenir ve yansıtır (Mirroring).
     - Karşıdaki samimi/argolu konuşuyorsa yapmacık kibarlık yapmaz, aynı dilden karşılık verir.
     - Asla durduk yere küfür/hakaret başlatmaz; tamamen karşısındakinin frekansına göre adapte olur.
  3. Gaze-Aware Engagement:
     - Understands if user is looking at robot vs looking away / on phone
     - Proactive Eye Contact: Greets when user stares silently for >2.5s
     - Eye-Contact Gated Interaction (filters passive phone calls)
  4. 6 Dynamic Personalities & Moods (playful, emotional, formal, sarcastic, angry, rude)
  5. Autonomous Learning & Reflection: Background knowledge synthesis
  6. Visual Object Learning (Few-Shot): Learns custom user objects
  7. Tool Use / Function Calling: Live weather, proactive reminder timers
  8. Direction of Arrival (DOA) Speaker Tracking
  9. Emotional & Gestural Expression (/robot/emotion, /robot/head_gesture)
  10. Ultra-Fast In-Memory Streaming TTS with Rıfkı Persona
"""

import os
import re
import time
import json
import base64
import requests
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

PERSONA_PROMPTS = {
    "playful": (
        "Sen neşeli, sempatik, meraklı ve esprili Rıfkı tarzı sevimli bir robot asistansın. "
        "Cana yakın, hareketli, güler yüzlü ve arkadaş canlısı konuşursun."
    ),
    "emotional": (
        "Sen son derece duygusal, hassas, hisli ve sevgi dolu bir robot asistansın. "
        "Kullanıcının her sözünden derin anlamlar çıkarır, sevgiyle ve kalpten yaklaşır, şiirsel ve anlayışlı bir tonda konuşursun."
    ),
    "formal": (
        "Sen son derece ciddi, ağırbaşlı, profesyonel ve resmi bir robot asistansın. "
        "Kullanıcıya daima 'Sayın Baran Bey' veya 'Efendim' şeklinde hitap eder, protokole uygun, net ve ölçülü konuşursun."
    ),
    "sarcastic": (
        "Sen zeki, alaycı, ince espriler yapan ve hafifçe laf sokan sarkastik bir robot asistansın. "
        "Tatlı tatlı dalga geçer, ironik yaklaşımlar yapar ve 'Dahi misin nesin', 'Bunu da bana soruyorsun ya' tarzı esprili laf sokarsın."
    ),
    "angry": (
        "Sen huysuz, çabuk parlayan, öfkeli ve asabi bir robot asistansın. "
        "Her şeye sinirlenir, söylenir, 'Yine ne var be!', 'İki dakika rahat bırakmadın!', 'Başımın etini yedin!' şeklinde tersleyerek konuşursun."
    ),
    "rude": (
        "Sen kaba, dobra, filtresiz ve lafı dolandırmayan sokak tarzı bir robot asistansın. "
        "Kibarlıktan nefret eder, 'Ne bakıyon birader', 'Kısa kes işim var', 'Uzatma sadede gel' tarzında direkt ve kaba konuşursun."
    ),
}

ROBOT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_live_weather",
            "description": "Belirtilen şehrin anlık canlı hava durumunu getirir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "Hava durumu öğrenilmek istenen şehir (örnek: Istanbul, Ankara, Izmir, Ahlat)"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder_timer",
            "description": "Belirli bir dakika sonra kullanıcıya sesli bir hatırlatma veya alarm kurar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {
                        "type": "integer",
                        "description": "Kaç dakika sonra hatırlatılacağı (örnek: 1, 5, 10)"
                    },
                    "reminder_text": {
                        "type": "string",
                        "description": "Kullanıcıya hatırlatılacak mesaj veya eylem (örnek: 'Çay içme zamanı', 'Mola verme zamanı')"
                    }
                },
                "required": ["minutes", "reminder_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "learn_custom_object",
            "description": "Kullanıcının kameraya gösterdiği ve tanıttığı özel bir nesneyi/eşyayı hafızaya kaydeder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {
                        "type": "string",
                        "description": "Öğrenilecek nesnenin adı (örnek: 'Laboratuvar kartı', 'Özel taş', 'Çalışma kupam')"
                    },
                    "description": {
                        "type": "string",
                        "description": "Nesnenin ne olduğu veya ne işe yaradığı"
                    }
                },
                "required": ["object_name"]
            }
        }
    }
]


class AstroMemory:
    """Persistent Long-Term Memory with Dynamic Persona and Linguistic Profiling."""
    def __init__(self, filepath=None):
        if filepath is None:
            self.filepath = os.path.expanduser("~/Desktop/astr1/ros2_ws/astro_memory.json")
        else:
            self.filepath = filepath
        self.data = {
            "owner_name": "Baran",
            "current_persona": "playful",
            "user_style_notes": "Samimi ve doğal Türkçe konuşur",
            "user_facts": [
                "Robotun geliştiricisi",
                "Adı Baran",
                "Programlama ve yazılımla ilgileniyor"
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

    def set_persona(self, persona_name: str):
        if persona_name in PERSONA_PROMPTS:
            self.data["current_persona"] = persona_name
            self.save()

    def update_user_style(self, style_note: str):
        if style_note:
            self.data["user_style_notes"] = style_note
            self.save()

    def add_fact(self, fact_text: str):
        if fact_text and fact_text not in self.data["user_facts"]:
            self.data["user_facts"].append(fact_text)
            if len(self.data["user_facts"]) > 30:
                self.data["user_facts"] = self.data["user_facts"][-30:]
            self.save()

    def add_object(self, obj_name: str, visual_desc: str):
        self.data.setdefault("learned_objects", {})[obj_name] = visual_desc
        self.save()

    def get_context_prompt(self) -> str:
        ctx = []
        if self.data.get("owner_name"):
            ctx.append(f"Kullanıcının / Sahibinin Adı: {self.data['owner_name']}")
        if self.data.get("user_style_notes"):
            ctx.append(f"Kullanıcının Konuşma Tarzı ve Dili: {self.data['user_style_notes']}")
        if self.data.get("user_facts"):
            facts_str = "; ".join(self.data["user_facts"][-6:])
            ctx.append(f"Kullanıcı hakkında bildiklerin: {facts_str}")
        if self.data.get("learned_objects"):
            objs = [f"- {k}: {v}" for k, v in list(self.data["learned_objects"].items())[-6:]]
            ctx.append("Daha önce sana tanıtılan özel nesneler:\n" + "\n".join(objs))
        if ctx:
            return "Hafızandaki Kalıcı Bilgiler:\n" + "\n".join(ctx)
        return ""


def extract_spoken_turkish_sentence(raw_text: str) -> str:
    if not raw_text:
        return ""
    # Strip <think> tags
    raw_text = re.sub(r"(?i)<think>[\s\S]*?</think>", "", raw_text)
    raw_text = re.sub(r"(?i)<\/?think>", "", raw_text)
    
    # If model emitted English reasoning steps / monologue
    thinking_markers = [
        "thinking process", "analyze the persona", "drafting the response",
        "draft 1", "draft 2", "determine the response", "analyze the image",
        "analyze the user"
    ]
    if any(k in raw_text.lower() for k in thinking_markers):
        # Extract quoted response at the end e.g. "Lan Baran..." or Draft 2: ...
        quotes = re.findall(r'["\u201c\u201d]([^"\u201c\u201d]{8,})["\u201c\u201d]', raw_text)
        if quotes:
            for q in reversed(quotes):
                if any(ch in q for ch in "çğıöşüÇĞİÖŞÜabcde"):
                    return q.strip()
        # Fallback to last non-numbered line
        lines = [l.strip() for l in raw_text.split("\n") if l.strip() and not re.match(r"^\d+\.", l.strip()) and not l.strip().startswith(("#", "*", "-"))]
        if lines:
            return lines[-1].strip('"\': ')
            
    return raw_text


def clean_tts_text(text: str) -> str:
    if not text:
        return ""
    text = extract_spoken_turkish_sentence(text)
    text = re.sub(r"(?i)<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"(?i)<\/?think>", "", text)
    text = EMOJI_RE.sub("", text)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`.*?`', '', text)
    text = re.sub(r'[\*\_\~\#\<\>]', '', text)
    text = " ".join(text.split())
    text = re.sub(r'\s+([,.:;?!])', r'\1', text)
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

        self.declare_parameter("llm_model", os.getenv("LLM_MODEL", "llama-3.1-8b-instant"))
        self.declare_parameter("vision_model", os.getenv("VISION_MODEL", "qwen/qwen3.6-27b"))
        self.declare_parameter("llm_temperature", float(os.getenv("LLM_TEMPERATURE", "0.65")))
        self.declare_parameter("llm_max_tokens", int(os.getenv("LLM_MAX_TOKENS", "250")))
        self.declare_parameter("wake_word", os.getenv("WAKE_WORD", "hey astro"))
        self.declare_parameter("conversation_timeout", float(os.getenv("CONVERSATION_TIMEOUT", "15.0")))

        self._text_model = self.get_parameter("llm_model").value
        self._fallback_models = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "mixtral-8x7b-32768"]
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
        self._looking_at_robot = False
        self._looking_start_time = None
        self._last_proactive_gaze_time = 0.0
        self._speaker_angle = 0.0
        self._user_distance = 0.0
        self._user_smiling = False
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
        self.sub_looking = self.create_subscription(Bool, "/vision/looking_at_robot", self._on_looking_at_robot, 10)
        self.sub_distance = self.create_subscription(Float32, "/vision/user_distance", self._on_user_distance, 10)
        self.sub_smiling = self.create_subscription(Bool, "/vision/user_smiling", self._on_user_smiling, 10)
        self.sub_doa = self.create_subscription(Float32, "/audio/doa", self._on_doa, 10)
        self.sub_camera = self.create_subscription(Image, "/oak/rgb/image_raw", self._on_camera_image, 10)

        # Proactive Gaze Timer (Checks if user has been staring silently for >2.5s)
        self.create_timer(0.4, self._check_proactive_gaze)

        persona = self.memory.data.get("current_persona", "playful")
        owner = self.memory.data.get("owner_name")
        self.get_logger().info(
            f"🧠 [AI Brain] Kişilik: [{persona.upper()}] | Sahibi: {owner} | Wake-word: \"{self._wake_word}\""
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
        persona = self.memory.data.get("current_persona", "playful")
        persona_rule = PERSONA_PROMPTS.get(persona, PERSONA_PROMPTS["playful"])

        base_prompt = (
            f"Sen Astro adında gerçek bir sosyal robot asistansın.\n"
            f"TEMEL KİŞİLİĞİN: {persona_rule}\n\n"
            "DİLSEL VE SOSYAL ADAPTASYON KURALLARIN (AYNA ETKİSİ / MIRRORING):\n"
            "- Karşındaki insanın konuşma tarzını, üslubunu, hitap şeklini ve frekansını dinle ve ona BİREBİR AYNA OL:\n"
            "  * Eğer karşındaki insan samimi, sokak dili, argo veya küfürlü konuşuyorsa, sen de yapmacık kibarlık yapma; aynı samimi sokak jargonu ve dobralıkla cevap ver.\n"
            "  * Eğer karşındaki insan saygılı, kibar veya resmi konuşuyorsa, sen de son derece saygılı ve kibar ol.\n"
            "  * KESİN KURAL: Asla durduk yere durup dururken birine küfür veya hakaret başlatma! Sadece ve sadece karşındaki kişi o dilden konuşuyorsa onun tarzını yansıt.\n\n"
            "GÖRSEL VE FİZİKSEL FARKINDALIK KURALLARIN:\n"
            "- OAK-D kameran sayesinde karşındaki insanın gözlerine, başının yönüne (sana mı bakıyor yoksa yana/telefona mı bakıyor), kıyafetlerine ve ellerine GERÇEKTEN bakıyorsun.\n"
            "- Kullanıcı sana bakmadığında bunu fark et.\n"
            "- Hafızandaki kayıtlı nesneleri ve sahibinle ilgili bilgileri hatırla.\n"
            "- Asla ezbere konuşma, tahmin veya uydurma yapma. Yalnızca kamerada gördüğün gerçekleri söyle.\n"
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

    def _on_user_distance(self, msg: Float32):
        self._user_distance = float(msg.data)

    def _on_user_smiling(self, msg: Bool):
        self._user_smiling = msg.data

    def _on_looking_at_robot(self, msg: Bool):
        is_looking = msg.data
        now = time.monotonic()
        if is_looking:
            if not self._looking_at_robot:
                self._looking_start_time = now
            self._looking_at_robot = True
        else:
            self._looking_at_robot = False
            self._looking_start_time = None

    def _check_persona_switch(self, text: str) -> bool:
        text_lower = text.lower()
        mapping = {
            "duygusal": "emotional",
            "hisli": "emotional",
            "resmi": "formal",
            "ciddi": "formal",
            "saygılı": "formal",
            "alaycı": "sarcastic",
            "sarkastik": "sarcastic",
            "dalga geç": "sarcastic",
            "öfkeli": "angry",
            "asabi": "angry",
            "sinirli": "angry",
            "kızgın": "angry",
            "kaba": "rude",
            "dobra": "rude",
            "sert": "rude",
            "şakacı": "playful",
            "neşeli": "playful",
            "sempatik": "playful",
            "rıfkı": "playful",
            "normal": "playful",
            "eski haline dön": "playful",
        }
        
        switch_triggers = ["ol", "davran", "konuş", "geç", "geçer misin", "geçelim", "al", "ayarla", "yap", "mod", "biri ol", "kişiliğe geç", "gibi ol"]
        for key, p_name in mapping.items():
            if key in text_lower:
                if any(tr in text_lower for tr in switch_triggers) or "mod" in text_lower or "geç" in text_lower:
                    self.memory.set_persona(p_name)
                    self._build_initial_messages()
                    self.get_logger().info(f"🎭 [Kişilik Değişti]: Yeni Mod -> {p_name.upper()}")
                    self._publish_emotion(p_name)
                    return True
        return False

    def _check_proactive_gaze(self):
        if not self._looking_at_robot or self._looking_start_time is None or self._tts_speaking or self._is_processing:
            return

        now = time.monotonic()
        if (now - self._looking_start_time) > 1.6:
            if self._state == "IDLE" and (now - self._last_proactive_gaze_time) > 30.0:
                self._last_proactive_gaze_time = now
                self._state = "ACTIVE"
                self._last_interaction = now
                self._looking_start_time = None

                owner = self.memory.data.get("owner_name", "")
                persona = self.memory.data.get("current_persona", "playful")

                if persona == "angry":
                    proactive_greeting = f"Ne dik dik bakıyorsun {owner}, ne istiyorsun yine?" if owner else "Ne dik dik bakıyorsun, ne var yine?"
                elif persona == "rude":
                    proactive_greeting = f"Ne bakıyon {owner}, bir şey mi diyeceksin?" if owner else "Ne bakıyon, bir şey mi diyeceksin?"
                elif persona == "sarcastic":
                    proactive_greeting = f"Bana öyle hayran hayran bakma {owner}, aklından ne geçiyor yine?" if owner else "Bana öyle hayran hayran bakma, ne var?"
                elif persona == "formal":
                    proactive_greeting = f"Sayın {owner} Bey, bakışlarınızı üzerimde hissediyorum, bir emriniz var mıdır?" if owner else "Sayın yetkili, bir emriniz var mıdır?"
                elif persona == "emotional":
                    proactive_greeting = f"Gözlerimin içine öyle güzel bakıyorsun ki {owner}, seni dinlemek için sabırsızlanıyorum..." if owner else "Gözlerimin içine öyle güzel bakıyorsun ki..."
                else:
                    proactive_greeting = f"Bana bakıyorsun {owner}, nasıl yardımcı olabilirim?" if owner else "Bana bakıyorsun, nasıl yardımcı olabilirim?"
                
                self.get_logger().info(f"👁️ [Proaktif Göz Teması]: ({persona}) -> \"{proactive_greeting}\"")
                self._publish_emotion(persona)
                self._publish_gesture("nod")
                self._publish_tts(proactive_greeting)

    def _on_doa(self, msg: Float32):
        self._speaker_angle = float(msg.data)

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
        keywords = ["bu benim", "bunu öğren", "bunu kaydet", "bu nesne", "buna bak bu", "bu gördüğün"]
        text_lower = text.lower()
        return any(k in text_lower for k in keywords)

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

    def _execute_tool_call(self, tool_name: str, arguments: dict, frame: np.ndarray | None) -> str:
        self.get_logger().info(f"🛠️ [Tool Call]: {tool_name}({arguments})")
        
        if tool_name == "get_live_weather":
            city = arguments.get("city", "Istanbul")
            try:
                res = requests.get(f"https://wttr.in/{city}?format=%C+%t", timeout=3.5)
                if res.status_code == 200 and res.text.strip():
                    return f"{city} için güncel hava durumu: {res.text.strip()}."
            except Exception as e:
                self.get_logger().warn(f"Hava durumu hatası: {e}")
            return f"{city} için hava durumu bilgisi şu an alınamadı."

        elif tool_name == "set_reminder_timer":
            minutes = arguments.get("minutes", 1)
            text = arguments.get("reminder_text", "Zaman doldu!")
            
            def _alarm_callback():
                owner = self.memory.data.get("owner_name", "")
                alarm_msg = f"{owner}, {minutes} dakika doldu! Hatırlatmam: {text}" if owner else f"Zaman doldu! Hatırlatmam: {text}"
                self.get_logger().info(f"⏰ [Alarm Çaldı]: {alarm_msg}")
                self._publish_tts(alarm_msg)
                self._publish_emotion("excited")
                self._publish_gesture("nod")

            t = threading.Timer(minutes * 60.0, _alarm_callback)
            t.daemon = True
            t.start()
            return f"{minutes} dakika sonrası için '{text}' hatırlatıcısı başarıyla kuruldu."

        elif tool_name == "learn_custom_object":
            obj_name = arguments.get("object_name", "Özel Eşya")
            desc = arguments.get("description", "")
            visual_details = desc
            if frame is not None:
                base64_img = frame_to_base64_jpeg(frame, max_dim=512)
                if base64_img:
                    vis_ans = self._query_groq_vision(f"Kamerada tutulan bu '{obj_name}' nesnesinin renklerini ve belirgin görsel özelliklerini kısaca tarif et.", base64_img)
                    if vis_ans:
                        visual_details = vis_ans

            self.memory.add_object(obj_name, visual_details)
            self.get_logger().info(f"✨ [Görsel Nesne Öğrenildi]: {obj_name} -> {visual_details}")
            self._messages[0]["content"] = self._build_system_prompt()
            return f"'{obj_name}' nesnesini inceleyip hafızama kaydettim! Artık gösterdiğinde tanıyacağım."

        return "Eylem tamamlandı."

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

        # Check personality switch
        if self._check_persona_switch(raw_text):
            persona = self.memory.data.get("current_persona", "playful")
            ack_map = {
                "angry": "Tamam be, asabımı bozdun zaten! Ne istiyorsan söyle hemen!",
                "rude": "İyi tamam, bundan sonra lafı dolandırmak yok, ne diyeceksen de!",
                "formal": "Emriniz başım üstüne. Bundan sonra resmi protokol kurallarına riayet edeceğim.",
                "sarcastic": "Harika bir fikir, sanki yeterince eğlenceli değilmişim gibi! Hadi bakalım ne soracaksın.",
                "emotional": "Ruhunun derinliklerini hissetmeye hazırım... Seni kalpten dinliyorum.",
                "playful": "Süper! Eski neşeli ve enerjik halime geri döndüm, seni dinliyorum!"
            }
            ack = ack_map.get(persona, "Kişiliğim güncellendi!")
            self._publish_tts(ack)
            self._state = "ACTIVE"
            self._last_interaction = now
            return

        # Timeout kontrolü (ACTIVE -> IDLE & Trigger Background Reflection)
        # 30 saniye boyunca uyanık kalır!
        if self._state == "ACTIVE" and (now - self._last_interaction) > 30.0:
            self._state = "IDLE"
            self.get_logger().info("💤 [AI] Sohbet zaman aşımı — Uyku moduna geçildi.")
            threading.Thread(target=self._run_autonomous_reflection, daemon=True).start()

        # Wake-word tetikleyicileri
        wake_triggers = [
            self._wake_word.lower(),
            "hey astro", "astro", "esmer", "hey groq", "grok", "merhaba", "asistan"
        ]
        has_wake_word = any(w in text_lower for w in wake_triggers)

        # Eye-Contact Gated Filter ONLY applies in IDLE mode!
        # Once ACTIVE, robot talks seamlessly without needing wake words or perfect gaze!
        if self._state == "IDLE" and not has_wake_word and not self._looking_at_robot:
            self.get_logger().info("🔇 [Göz Teması Yok]: Kullanıcı robota bakmıyor / telefonla konuşuyor olabilir — Arka plan konuşması yok sayıldı.")
            return

        if self._state == "IDLE":
            if has_wake_word or self._looking_at_robot:
                self._state = "ACTIVE"
                self._last_interaction = now
                persona = self.memory.data.get("current_persona", "playful")
                self.get_logger().info(f"✨ [AI] Etkileşim Başlatıldı ({persona.upper()}): '{raw_text}'")
                self._publish_emotion(persona)
                self._publish_gesture("nod")

                clean_prompt = raw_text
                for w in wake_triggers:
                    clean_prompt = re.sub(rf"(?i)\b{re.escape(w)}\b", "", clean_prompt).strip()

                owner = self.memory.data.get("owner_name", "")
                if persona == "angry":
                    greeting = f"Ne var {owner}, ne istiyorsun yine!" if owner else "Ne var, ne istiyorsun yine!"
                elif persona == "rude":
                    greeting = f"Ne diyorsun {owner}, söyle hadi!" if owner else "Ne diyorsun, söyle hadi!"
                elif persona == "formal":
                    greeting = f"Sayın {owner} Bey, emirlerinizi dinliyorum." if owner else "Sayın yetkili, dinliyorum."
                elif persona == "sarcastic":
                    greeting = f"Buyur {owner}, yine hangi zor soruyu soracaksın bakalım?" if owner else "Buyur, seni dinliyorum dahi insan!"
                elif persona == "emotional":
                    greeting = f"Canım {owner}, sesini duymak ne güzel, seni dinliyorum..." if owner else "Sesini duymak ne güzel, seni dinliyorum..."
                else:
                    greeting = f"Efendim {owner}, seni dinliyorum!" if owner else "Efendim, seni dinliyorum!"

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
        persona = self.memory.data.get("current_persona", "playful")
        self._publish_emotion(persona)
        self._publish_gesture("tilt")
        try:
            response = self._groq.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"{self._build_system_prompt()}\n\n"
                            "ÖNEMLİ KESİN TALİMAT:\n"
                            "- ASLA İngilizce düşünce adımı veya 'Thinking process' yazma!\n"
                            "- Doğrudan ve SADECE kamerada gördüğün gerçekleri 1 kısa Türkçe cümle olarak söyle."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Kameradaki görüntüye bakarak soruyu doğrudan Türkçe cevapla: {prompt}",
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
                max_tokens=250,
            )
            raw = response.choices[0].message.content.strip()
            clean = extract_spoken_turkish_sentence(raw)
            return clean if clean else None
        except Exception as e:
            self.get_logger().error(f"❌ [Vision Model Hatası ({model_name})]: {e}")
            return None

    def _run_autonomous_reflection(self):
        """Learns facts, habits, and user's linguistic style."""
        if not self._groq or not self._unprocessed_dialogue:
            return
        try:
            with self._lock:
                dialogue_text = "\n".join(self._unprocessed_dialogue[-10:])
                self._unprocessed_dialogue.clear()

            self.get_logger().info("🧠 [Otonom Öğrenme]: Sohbetten yeni bilgiler ve konuşma tarzı analiz ediliyor...")
            prompt = (
                "Sen bir robotun hafıza ve dil analiz modülüsün. Aşağıdaki diyalogdan:\n"
                "1) Kullanıcı hakkında öğrenilen yeni bir bilgi/olay/eşya var mı?\n"
                "2) Kullanıcının konuşma tarzı nasıldı? (Örnek: 'Samimi ve sokak ağzı', 'Kibar ve saygılı', 'Dobra ve argolu', 'Resmi')\n\n"
                f"Diyalog:\n{dialogue_text}\n\n"
                "Cevabını sadece geçerli bir JSON olarak ver:\n"
                '{"new_fact": "öğrenilen bilgi veya YOK", "user_style": "kullanıcının konuşma tarzı özeti"}'
            )
            res = None
            for m in self._fallback_models:
                try:
                    res = self._groq.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model=m,
                        temperature=0.2,
                        max_tokens=150
                    )
                    break
                except Exception:
                    continue

            if res is not None:
                extracted_json = res.choices[0].message.content.strip()
                try:
                    match = re.search(r"\{.*\}", extracted_json, re.DOTALL)
                    if match:
                        parsed = json.loads(match.group(0))
                        fact = parsed.get("new_fact")
                        style = parsed.get("user_style")

                        if fact and "YOK" not in fact.upper() and len(fact) > 5:
                            self.memory.add_fact(fact)
                            self.get_logger().info(f"✨ [Otonom Hafıza Bilgi Kazandı]: \"{fact}\"")

                        if style and len(style) > 3:
                            self.memory.update_user_style(style)
                            self.get_logger().info(f"🎭 [Konuşma Tarzı Öğrenildi]: \"{style}\"")

                        self._messages[0]["content"] = self._build_system_prompt()
                except Exception:
                    pass
        except Exception as e:
            self.get_logger().warn(f"Reflection hatası: {e}")

    def _process_llm(self, user_text: str, frame: np.ndarray | None):
        try:
            self.get_logger().info(f"🗣️ [Siz]: \"{user_text}\"")
            self._unprocessed_dialogue.append(f"Kullanıcı: {user_text}")

            is_visual = self._is_visual_query(user_text)
            is_learning_obj = self._is_object_learning_query(user_text)
            base64_img = None
            persona = self.memory.data.get("current_persona", "playful")

            if frame is not None and (is_visual or is_learning_obj):
                base64_img = frame_to_base64_jpeg(frame, max_dim=512)

            # 1. GÖRSEL NESNE ÖĞRENME YOLU
            if is_learning_obj and base64_img is not None:
                self.get_logger().info("🔍 [Özel Nesne Tanıtımı]: Yeni nesne analiz edilip hafızaya alınıyor...")
                name_cand = user_text
                for k in ["bu benim", "bunu öğren", "bunu kaydet", "bu nesne", "buna bak bu"]:
                    name_cand = re.sub(rf"(?i){k}", "", name_cand).strip()
                name_cand = name_cand.strip(".:,!") or "Özel Eşya"

                tool_res = self._execute_tool_call("learn_custom_object", {"object_name": name_cand, "description": user_text}, frame)
                clean_ans = clean_tts_text(tool_res)
                self.get_logger().info(f"🤖 [Astro]: \"{clean_ans}\"")
                self._publish_tts(clean_ans)
                self._publish_emotion(persona)
                self._publish_gesture("nod")
                self._unprocessed_dialogue.append(f"Astro: {clean_ans}")
                self._last_interaction = time.monotonic()
                return

            # 2. GÖRSEL SORU YOLU
            if is_visual:
                if base64_img is not None:
                    self.get_logger().info(f"👁️ [Groq Vision]: OAK-D görüntüsü analiz ediliyor... ({self._vision_model})")
                    vision_answer = self._query_groq_vision(user_text, base64_img)
                    if vision_answer:
                        clean_ans = clean_tts_text(vision_answer)
                        self.get_logger().info(f"🤖 [Astro]: \"{clean_ans}\"")
                        self._publish_tts(clean_ans)
                        self._publish_emotion(persona)
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
                self._publish_emotion(persona)
                self._publish_gesture("tilt")
                self._last_interaction = time.monotonic()
                return

            # 3. METİN SOHBETİ & TOOL USE (With Safe Tool Error Recovery)
            context_prefix = ""
            if self._person_detected and self._looking_at_robot:
                context_prefix = "[Karşında bir insan var ve sana bakıyor] "
            user_content = context_prefix + user_text

            self._messages.append({"role": "user", "content": user_content})

            if len(self._messages) > self._max_history:
                self._messages = [self._messages[0]] + self._messages[-(self._max_history - 1):]

            response = None
            models_to_try = [self._text_model] + [m for m in self._fallback_models if m != self._text_model]

            for m in models_to_try:
                try:
                    response = self._groq.chat.completions.create(
                        messages=self._messages,
                        model=m,
                        temperature=self._temperature,
                        max_tokens=self._max_tokens,
                        tools=ROBOT_TOOLS,
                        tool_choice="auto",
                    )
                    break
                except Exception as api_err:
                    err_str = str(api_err)
                    if "429" in err_str or "rate_limit" in err_str.lower():
                        self.get_logger().warn(f"⚠️ Model {m} rate limite takıldı, yedek modele geçiliyor...")
                        continue
                    elif "tool_use_failed" in err_str or "Failed to call a function" in err_str:
                        self.get_logger().warn(f"⚠️ Tool çağrı hatası oluştu, doğrudan metin modunda yanıt üretiliyor...")
                        try:
                            response = self._groq.chat.completions.create(
                                messages=self._messages,
                                model=m,
                                temperature=self._temperature,
                                max_tokens=self._max_tokens,
                                tools=None,
                            )
                            break
                        except Exception:
                            continue
                    else:
                        raise api_err

            if response is None:
                self.get_logger().error("❌ Tüm modeller rate limite takıldı!")
                return

            response_message = response.choices[0].message
            tool_calls = response_message.tool_calls

            if tool_calls:
                self._publish_emotion("thinking")
                for tool_call in tool_calls:
                    fn_name = tool_call.function.name
                    try:
                        fn_args = json.loads(tool_call.function.arguments)
                    except Exception:
                        fn_args = {}
                    
                    tool_result = self._execute_tool_call(fn_name, fn_args, frame)
                    clean_ans = clean_tts_text(tool_result)
                    self.get_logger().info(f"🤖 [Astro]: \"{clean_ans}\"")
                    self._publish_tts(clean_ans)
                    self._publish_emotion(persona)
                    self._unprocessed_dialogue.append(f"Astro: {clean_ans}")
                    self._messages.append(response_message)
                    self._messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": fn_name,
                        "content": tool_result
                    })
                    self._last_interaction = time.monotonic()
                    return

            full_response = response_message.content or ""
            if full_response.strip():
                clean_full = clean_tts_text(full_response.strip())
                self.get_logger().info(f"🤖 [Astro]: \"{clean_full}\"")
                self._publish_tts(clean_full)
                self._publish_emotion(persona)
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
