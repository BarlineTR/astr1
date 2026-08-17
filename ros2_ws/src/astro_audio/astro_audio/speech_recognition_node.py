#!/usr/bin/env python3
"""ASTRO V1 — Speech Recognition Node (Groq Whisper-large-v3).

Subscribes to:
  /audio/speech_audio  (Int16MultiArray) — 16kHz mono PCM from audio_capture_node
  /audio/vad           (Bool)            — voice activity detection flag
  /tts/speaking        (Bool)            — TTS playback state (echo prevention)

Publishes:
  /speech/text         (String)          — final transcribed text

Features:
  - Pre-roll ring buffer (~0.4s) to never miss initial syllables ("Hey...", "Na...")
  - Silence timeout (0.75s) matching hey_groq_assistant.py
  - Whisper prompt hinting for robot context ("Astro, naber, nasılsın...")
"""

import os
import time
import io
import wave
import threading
import numpy as np

import rclpy
from rclpy.node import Node
from std_msgs.msg import Int16MultiArray, String, Bool

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

try:
    from astro_audio.speaker_db import SpeakerEngine, SpeakerEngineUnavailable
except ImportError:  # paket kaynaktan çalıştırılıyorsa
    SpeakerEngine = None

    class SpeakerEngineUnavailable(RuntimeError):
        pass

# Türkçe tanımayı iyileştiren bağlam ipucu (her iki motorda da kullanılır)
WHISPER_PROMPT = (
    "Astro, hey astro, robot, naber, nasılsın, ne haber, elinde ne var, "
    "beni görüyor musun, nasılsın iyi misin."
)
# Whisper'ın sessizlikte uydurduğu tipik ifadeler
JUNK_FILTERS = ("altyazı", "abone ol", "izlediginiz icin", "izlediğiniz için", "www.", ".com", "m.k")


def _fold(text: str) -> str:
    """Karşılaştırma için metni sadeleştirir.

    Türkçe "İ" harfinin küçüğü "i" değil, "i" + birleşik nokta (U+0307) olur;
    düz str.lower() ile "İzlediğiniz" hiçbir zaman "izlediğiniz" ile eşleşmez ve
    Whisper'ın en sık halüsinasyonu filtreden kaçardı. Birleşik işaretleri atarak
    bu tuzağı kapatıyoruz.
    """
    import unicodedata

    lowered = text.replace("İ", "i").replace("I", "ı").lower()
    return "".join(c for c in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(c))

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


class SpeechRecognitionNode(Node):
    def __init__(self):
        super().__init__('speech_recognition_node')

        _load_env()

        self.enabled = False
        self.groq_client = None
        self.fw_model = None
        # .env: "faster-whisper" (yerel, varsayılan) veya "groq" (bulut)
        self.engine = os.getenv("STT_ENGINE", "faster-whisper").strip().lower()

        if self.engine == "groq":
            self._init_groq() or self._init_faster_whisper()
        else:
            if self.engine not in ("faster-whisper", "faster_whisper"):
                self.get_logger().warn(
                    f"Bilinmeyen STT_ENGINE=\"{self.engine}\" — yerel faster-whisper kullanılıyor"
                )
                self.engine = "faster-whisper"
            self._init_faster_whisper() or self._init_groq()

        if not self.enabled:
            self.get_logger().error(
                "❌ [STT] Hiçbir konuşma tanıma motoru başlatılamadı — düğüm dinliyor "
                "ama deşifre edemez."
            )

        # Parameters
        self.declare_parameter('silence_timeout_s', 0.75)
        self.declare_parameter('sample_rate', 16000)
        self._silence_timeout_s = float(self.get_parameter('silence_timeout_s').value)
        self._sample_rate = int(self.get_parameter('sample_rate').value)

        # Konuşmacı tanıma (sesten kişi ayırt etme) — isteğe bağlı, yoksa STT çalışmaya devam eder
        self.speaker = None
        if os.getenv("SPEAKER_ID_ENABLED", "1") not in ("0", "false", "False"):
            if SpeakerEngine is None:
                self.get_logger().warn("speaker_db modülü yüklenemedi — konuşmacı tanıma kapalı")
            else:
                try:
                    self.speaker = SpeakerEngine()
                    self.get_logger().info(
                        f"✅ [Konuşmacı] Tanıma aktif — kayıtlı: {self.speaker.summary()}"
                    )
                    if not self.speaker.people:
                        self.get_logger().warn(
                            "Kayıtlı ses yok — konuşan \"bilinmeyen\" görünecek. "
                            "Kayıt: ./scripts/enroll_speaker.py --name <isim> --record"
                        )
                except SpeakerEngineUnavailable as exc:
                    self.get_logger().warn(f"[Konuşmacı] Tanıma kapalı — {exc}")

        # Publishers
        self._text_pub = self.create_publisher(String, '/speech/text', 10)
        self._speaker_pub = self.create_publisher(String, '/audio/speaker_name', 10)

        # Subscribers
        self.create_subscription(Int16MultiArray, '/audio/speech_audio', self._audio_cb, 10)
        self.create_subscription(Bool, '/audio/vad', self._vad_cb, 10)
        self.create_subscription(Bool, '/tts/speaking', self._tts_speaking_cb, 10)

        # Internal state
        self._lock = threading.Lock()
        self._buffer: list[int] = []
        self._ring_buffer: list[int] = []  # 6400 samples (0.4s pre-roll)
        self._is_speaking: bool = False
        self._last_speech_time: float | None = None
        self._tts_speaking: bool = False
        self._last_tts_end_time: float | None = None

        # Timer (0.05s resolution)
        self.create_timer(0.05, self._silence_tick)

    # ------------------------------------------------------------------
    # Motor kurulumu — biri kurulamazsa diğeri denenir
    # ------------------------------------------------------------------
    def _init_faster_whisper(self) -> bool:
        """Yerel faster-whisper; internet gerektirmez, GPU'da hızlıdır."""
        if WhisperModel is None:
            self.get_logger().error(
                "faster-whisper kurulu değil (pip install faster-whisper)"
            )
            return False

        name = os.getenv("STT_FW_MODEL", "large-v2")
        device = os.getenv("STT_FW_DEVICE", "cuda")
        compute = os.getenv("STT_FW_COMPUTE_TYPE", "float16")
        try:
            self.get_logger().info(
                f"Yerele Yükleniyor: Faster-Whisper ({name}) Cihaz: {device} Hassasiyet: {compute}..."
            )
            try:
                self.fw_model = WhisperModel(name, device=device, compute_type=compute)
            except Exception as exc:
                if device != "cuda":
                    raise
                # CUDA yoksa/cuDNN uyumsuzsa sessizce ölmek yerine CPU'ya düş.
                compute = os.getenv("STT_FW_CPU_COMPUTE_TYPE", "int8")
                self.get_logger().warn(
                    f"CUDA ile yüklenemedi ({exc}) — CPU moduna düşülüyor ({compute})"
                )
                device = "cpu"
                self.fw_model = WhisperModel(name, device="cpu", compute_type=compute)
        except Exception as e:
            self.get_logger().error(f"❌ [STT] Faster-Whisper yükleme hatası: {e}")
            return False

        self.engine = "faster-whisper"
        self.enabled = True
        self.get_logger().info(
            f"✅ [STT] Faster-Whisper hazır ve dinliyor (model: {name}, cihaz: {device})"
        )
        return True

    def _init_groq(self) -> bool:
        """Groq Whisper-large-v3 (bulut) — API anahtarı ve internet gerekir."""
        if Groq is None:
            self.get_logger().error("groq kütüphanesi kurulu değil (pip install groq)")
            return False
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            self.get_logger().error("GROQ_API_KEY bulunamadı")
            return False
        try:
            self.groq_client = Groq(api_key=api_key)
        except Exception as e:
            self.get_logger().error(f"❌ [STT] Groq client başlatılamadı: {e}")
            return False

        self.engine = "groq"
        self.enabled = True
        self.get_logger().info("✅ [STT] Groq Whisper-large-v3 hazır ve dinliyor")
        return True

    def _tts_speaking_cb(self, msg: Bool):
        with self._lock:
            was_speaking = self._tts_speaking
            self._tts_speaking = msg.data

            if was_speaking and not self._tts_speaking:
                self._last_tts_end_time = time.monotonic()
                self._buffer.clear()
                self._is_speaking = False
                self._last_speech_time = None
            elif not was_speaking and self._tts_speaking:
                self._buffer.clear()
                self._is_speaking = False
                self._last_speech_time = None

    def _audio_cb(self, msg: Int16MultiArray):
        if not self.enabled:
            return

        with self._lock:
            if self._tts_speaking:
                return
            if self._last_tts_end_time is not None and (time.monotonic() - self._last_tts_end_time) < 0.6:
                return

            data = list(msg.data)
            self._ring_buffer.extend(data)
            if len(self._ring_buffer) > 6400:
                self._ring_buffer = self._ring_buffer[-6400:]

            if self._is_speaking:
                self._buffer.extend(data)

    def _vad_cb(self, msg: Bool):
        if not self.enabled:
            return

        with self._lock:
            if self._tts_speaking:
                return
            if self._last_tts_end_time is not None and (time.monotonic() - self._last_tts_end_time) < 0.6:
                return

            if msg.data:
                if not self._is_speaking:
                    # Speech started: include pre-roll ring buffer so start of word is intact
                    self._buffer = list(self._ring_buffer)
                    self._is_speaking = True
                self._last_speech_time = time.monotonic()

    def _silence_tick(self):
        if not self.enabled:
            return

        audio_data = None
        with self._lock:
            if self._is_speaking and self._last_speech_time is not None:
                elapsed = time.monotonic() - self._last_speech_time
                if elapsed > self._silence_timeout_s:
                    audio_data = list(self._buffer)
                    self._buffer.clear()
                    self._is_speaking = False
                    self._last_speech_time = None

        if audio_data is not None and len(audio_data) >= 4800:  # at least 0.3s
            threading.Thread(target=self._transcribe, args=(audio_data,), daemon=True).start()

    def _transcribe(self, audio_data: list[int]):
        if not self.enabled:
            return
        try:
            arr = np.array(audio_data, dtype=np.int16)
            if self.engine == "groq":
                text = self._transcribe_groq(arr)
            else:
                text = self._transcribe_faster_whisper(arr)
            # Kim konuştu? Deşifreyle aynı ses parçasından hesaplanır.
            speaker = self._identify_speaker(arr)
            self._publish_text(text, speaker)
        except Exception as e:
            self.get_logger().error(f"❌ [STT] Deşifre hatası: {e}")

    def _transcribe_faster_whisper(self, arr: np.ndarray) -> str:
        """Yerel deşifre — model float32 [-1, 1] bekler, WAV'a yazmaya gerek yok."""
        audio = arr.astype(np.float32) / 32768.0
        segments, _info = self.fw_model.transcribe(
            audio,
            beam_size=5,
            language="tr",
            initial_prompt=WHISPER_PROMPT,
        )
        return "".join(segment.text for segment in segments).strip()

    def _transcribe_groq(self, arr: np.ndarray) -> str:
        """Bulut deşifre — API dosya beklediği için bellek içi WAV üretilir."""
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            wf.writeframes(arr.tobytes())

        result = self.groq_client.audio.transcriptions.create(
            file=("speech.wav", wav_io.getvalue()),
            model="whisper-large-v3",
            language="tr",
            prompt=WHISPER_PROMPT,
            temperature=0.0,
            response_format="text",
        )
        return str(result).strip()

    def _identify_speaker(self, arr: np.ndarray) -> str:
        """Ses parçasından konuşanı tanır; tanınmazsa boş dize döner."""
        if self.speaker is None:
            return ""
        try:
            embedding = self.speaker.embed(arr, self._sample_rate)
            if embedding is None:      # parça çok kısa
                return ""
            name, score = self.speaker.identify(embedding)
            self.get_logger().debug(
                f"[Konuşmacı] {name or 'bilinmeyen'} (benzerlik {score:.3f})"
            )
            return name or ""
        except Exception as e:
            self.get_logger().warn(f"[Konuşmacı] Tanıma hatası: {e}")
            return ""

    def _publish_text(self, text: str, speaker: str = ""):
        if not text or text in (".", "...", ",", "!", "?"):
            return
        # Whisper sessizlikte altyazı/abone ol gibi ifadeler uydurur; bunları yutma.
        if any(junk in _fold(text) for junk in JUNK_FILTERS):
            return

        # Konuşmacı adı ayrı konudan gider; /speech/text saf metin kalır ki
        # ai_brain_node'daki uyandırma kelimesi eşleşmesi bozulmasın.
        self._speaker_pub.publish(String(data=speaker))
        who = f"{speaker}" if speaker else "bilinmeyen"
        self.get_logger().info(f'🎤 [{who}]: "{text}"')
        self._text_pub.publish(String(data=text))


def main(args=None):
    rclpy.init(args=args)
    node = SpeechRecognitionNode()
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
