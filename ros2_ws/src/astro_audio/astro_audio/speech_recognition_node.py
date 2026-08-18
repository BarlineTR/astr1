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

import json
import rclpy
from rclpy.node import Node
from std_msgs.msg import Int16MultiArray, String, Bool

try:
    from astro_audio.voice_recognizer import VoiceRecognizer
except ImportError:
    from voice_recognizer import VoiceRecognizer

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from dotenv import find_dotenv, load_dotenv
except ImportError:
    def find_dotenv(*args, **kwargs): return ""
    def load_dotenv(*args, **kwargs): pass


def _load_env():
    candidates = [
        os.path.abspath(".env"),
        os.path.abspath(".env.production"),
        os.path.abspath(os.path.join(os.getcwd(), ".env")),
        os.path.abspath(os.path.join(os.getcwd(), ".env.production")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env.production")),
        os.path.expanduser("~/Desktop/astr1/.env"),
        os.path.expanduser("~/Desktop/astr1/.env.production"),
        os.path.expanduser("~/.env")
    ]
    for c in candidates:
        if os.path.exists(c):
            load_dotenv(dotenv_path=c, override=True)
            return c
    try:
        env_path = find_dotenv(usecwd=True)
        if env_path:
            load_dotenv(dotenv_path=env_path, override=True)
            return env_path
    except Exception:
        pass
    return None


def estimate_pitch_and_gender(audio_arr: np.ndarray, sample_rate: int = 16000) -> tuple[float, str]:
    """Estimates fundamental frequency (F0) using autocorrelation on a small window (fast & lightweight)."""
    if len(audio_arr) < 1024:
        return 0.0, "unknown"
    try:
        # Take a centered 1024-sample slice to avoid O(N^2) CPU spike
        mid = len(audio_arr) // 2
        data = audio_arr[max(0, mid - 512): min(len(audio_arr), mid + 512)].astype(np.float32)
        data = data - np.mean(data)
        if np.max(np.abs(data)) < 200:
            return 0.0, "unknown"

        corr = np.correlate(data, data, mode='full')
        corr = corr[len(corr)//2:]

        min_lag = int(sample_rate / 350)
        max_lag = int(sample_rate / 75)

        if len(corr) > max_lag:
            peak_lag = min_lag + np.argmax(corr[min_lag:max_lag])
            if peak_lag > 0:
                pitch_hz = sample_rate / peak_lag
                if pitch_hz >= 165.0:
                    return float(pitch_hz), "female"
                elif pitch_hz >= 75.0:
                    return float(pitch_hz), "male"
    except Exception:
        pass
    return 0.0, "unknown"


class SpeechRecognitionNode(Node):
    def __init__(self):
        super().__init__('speech_recognition_node')

        self.enabled = True
        _load_env()
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip() or os.environ.get("AI_API_KEY", "").strip()
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
        
        self.openai_client = None
        self.groq_client = None

        if OpenAI and self.openai_api_key and self.openai_api_key.startswith("sk-"):
            try:
                self.openai_client = OpenAI(api_key=self.openai_api_key)
                self.get_logger().info("🚀 [STT] OpenAI Whisper-1 Birincil STT Motoru Aktif!")
            except Exception as e:
                self.get_logger().error(f"❌ [STT] OpenAI client başlatılamadı: {e}")

        if Groq and self.groq_api_key:
            try:
                self.groq_client = Groq(api_key=self.groq_api_key)
                self.get_logger().info("✅ [STT] Groq Whisper-large-v3 Yedek Motoru Hazır.")
            except Exception as e:
                self.get_logger().debug(f"Groq client notice: {e}")

        # Yerel motor (varsayılan): internet ve API anahtarı gerektirmez.
        # .env -> STT_ENGINE="faster-whisper" | "groq" | "openai"
        self.stt_engine = os.getenv("STT_ENGINE", "faster-whisper").strip().lower()
        self.fw_model = None
        if self.stt_engine in ("faster-whisper", "faster_whisper"):
            self._init_faster_whisper()

        if not self.fw_model and not self.openai_client and not self.groq_client:
            self.get_logger().error("❌ [STT] Ne OPENAI_API_KEY ne de GROQ_API_KEY bulunamadı! STT devre dışı.")
            self.enabled = False
            return

        # Parameters (Ultra-fast responsive conversational turn-taking: 0.38s silence pause tolerance)
        self.declare_parameter('silence_timeout_s', 0.38)
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('stt_min_peak', 1200.0)
        self.declare_parameter('stt_min_rms', 300.0)
        self.declare_parameter('stt_chunk_rms', 420.0)
        self.declare_parameter('stt_chunk_peak', 1050.0)
        self.declare_parameter('stt_voice_ratio_min', 0.18)
        self._silence_timeout_s = float(self.get_parameter('silence_timeout_s').value)
        self._sample_rate = int(self.get_parameter('sample_rate').value)
        self._min_peak = float(self.get_parameter('stt_min_peak').value)
        self._min_rms = float(self.get_parameter('stt_min_rms').value)
        self._chunk_rms = float(self.get_parameter('stt_chunk_rms').value)
        self._chunk_peak = float(self.get_parameter('stt_chunk_peak').value)
        self._voice_ratio_min = float(self.get_parameter('stt_voice_ratio_min').value)

        # Voice Recognition Engine
        self.voice_recognizer = VoiceRecognizer()

        # Publishers
        self._text_pub = self.create_publisher(String, '/speech/text', 10)
        self._gender_pub = self.create_publisher(String, '/audio/speaker_gender', 10)
        self._speaker_pub = self.create_publisher(String, '/audio/speaker_id', 10)
        self._interrupt_pub = self.create_publisher(Bool, '/tts/interrupt', 10)

        # Subscribers
        self.create_subscription(Int16MultiArray, '/audio/speech_audio', self._audio_cb, 10)
        self.create_subscription(Bool, '/audio/vad', self._vad_cb, 10)
        self.create_subscription(Bool, '/tts/speaking', self._tts_speaking_cb, 10)
        self.create_subscription(String, '/tts/say', self._tts_say_cb, 10)
        self.create_subscription(Bool, '/ai/session_active', self._session_active_cb, 10)

        # Internal state
        self._lock = threading.Lock()
        self._buffer: list[int] = []
        self._ring_buffer: list[int] = []  # 6400 samples (0.4s pre-roll)
        self._is_speaking: bool = False
        self._last_speech_time: float | None = None
        self._tts_speaking: bool = False
        self._tts_speaking_start_time: float | None = None
        self._last_tts_end_time: float | None = None
        self._session_active: bool = False
        self._ambient_rms: float = 100.0
        self._recent_tts_phrases: list[tuple[str, float]] = []  # (phrase_lower, timestamp)

        # Guards against concurrent / out-of-order transcription results
        self._transcribe_lock = threading.Lock()
        self._stt_sequence: int = 0

        # Timer (0.05s resolution)
        self.create_timer(0.05, self._silence_tick)

        self.get_logger().info("✅ [STT] Groq Whisper-large-v3 + Self-Echo Immunity + Bağlam Duyarlı Filtre Hazır.")

    def _session_active_cb(self, msg: Bool):
        self._session_active = msg.data

    def _tts_say_cb(self, msg: String):
        phrase = msg.data.lower().strip(" .,!?:;")
        if phrase:
            with self._lock:
                now = time.monotonic()
                self._recent_tts_phrases.append((phrase, now))
                # Keep only last 10 phrases
                if len(self._recent_tts_phrases) > 10:
                    self._recent_tts_phrases = self._recent_tts_phrases[-10:]

    def _tts_speaking_cb(self, msg: Bool):
        with self._lock:
            was_speaking = self._tts_speaking
            self._tts_speaking = msg.data

            if not was_speaking and self._tts_speaking:
                # TTS just started speaking — purge any buffered audio so robot does NOT record itself!
                self._tts_speaking_start_time = time.monotonic()
                self._is_speaking = False
                self._buffer.clear()
                self._ring_buffer.clear()
                self._last_speech_time = None
            elif was_speaking and not self._tts_speaking:
                # TTS just ended
                self._last_tts_end_time = time.monotonic()
                self._tts_speaking_start_time = None
                self._is_speaking = False
                self._buffer.clear()
                self._ring_buffer.clear()
                self._last_speech_time = None

    def _audio_cb(self, msg: Int16MultiArray):
        if not self.enabled:
            return

        with self._lock:
            # While robot is speaking, do NOT record speaker audio into buffer!
            if self._tts_speaking:
                return

            data = list(msg.data)
            self._ring_buffer.extend(data)
            if len(self._ring_buffer) > 6400:
                self._ring_buffer = self._ring_buffer[-6400:]

            # If speaking, record to speech buffer
            if self._is_speaking:
                self._buffer.extend(data)
            elif len(data) >= 320:
                # Track ambient noise floor during non-speech frames
                chunk_arr = np.array(data, dtype=np.int16)
                c_rms = float(np.sqrt(np.mean(chunk_arr.astype(np.float32)**2)))
                if c_rms < 1500.0:
                    self._ambient_rms = 0.95 * self._ambient_rms + 0.05 * c_rms

    def _vad_cb(self, msg: Bool):
        if not self.enabled:
            return

        with self._lock:
            # Ignore VAD while robot is actively speaking to prevent echolalia
            if self._tts_speaking:
                return

            if msg.data:
                now = time.monotonic()

                # Post-TTS echo suppression (0.60s room reverberation cooldown)
                if self._last_tts_end_time is not None and (now - self._last_tts_end_time) < 0.60:
                    return

                if not self._is_speaking:
                    self._buffer = list(self._ring_buffer)
                    self._is_speaking = True
                self._last_speech_time = now

    def _silence_tick(self):
        if not self.enabled:
            return

        audio_data = None
        with self._lock:
            if self._tts_speaking:
                return

            if self._is_speaking and self._last_speech_time is not None:
                elapsed = time.monotonic() - self._last_speech_time
                if elapsed > self._silence_timeout_s:
                    audio_data = list(self._buffer)
                    self._buffer.clear()
                    self._is_speaking = False
                    self._last_speech_time = None

        if audio_data is not None and len(audio_data) >= 5600:  # at least 0.35s of sound
            now = time.monotonic()
            if (now - getattr(self, '_last_transcribe_dispatch_time', 0.0)) < 0.45:
                return  # Protect against rapid duplicate triggers
            self._last_transcribe_dispatch_time = now

            with self._transcribe_lock:
                self._stt_sequence += 1
                my_seq = self._stt_sequence
            threading.Thread(target=self._transcribe, args=(audio_data, my_seq), daemon=True).start()

    def _init_faster_whisper(self) -> bool:
        """Yerel faster-whisper modelini yükler; CUDA yoksa CPU'ya düşer."""
        if WhisperModel is None:
            self.get_logger().warn("faster-whisper kurulu değil — bulut motorlar denenecek")
            return False

        name = os.getenv("STT_FW_MODEL", "large-v2")
        device = os.getenv("STT_FW_DEVICE", "cuda")
        compute = os.getenv("STT_FW_COMPUTE_TYPE", "float16")
        try:
            self.get_logger().info(f"Yerele yükleniyor: Faster-Whisper ({name}, {device}, {compute})...")
            try:
                self.fw_model = WhisperModel(name, device=device, compute_type=compute)
            except Exception as exc:
                if device != "cuda":
                    raise
                compute = os.getenv("STT_FW_CPU_COMPUTE_TYPE", "int8")
                cpu_model = os.getenv("STT_FW_CPU_MODEL", "base")
                self.get_logger().warn(f"CUDA ile yüklenemedi ({exc}) — CPU moduna ve hafif modele ({cpu_model}) geçiliyor")
                device = "cpu"
                name = cpu_model
                self.fw_model = WhisperModel(name, device="cpu", compute_type=compute)

        except Exception as e:
            self.get_logger().error(f"❌ [STT] Faster-Whisper yüklenemedi: {e}")
            self.fw_model = None
            return False

        self.get_logger().info(f"✅ [STT] Faster-Whisper hazır (model: {name}, cihaz: {device})")
        return True

    def _transcribe(self, audio_data: list[int], seq: int):
        try:
            arr = np.array(audio_data, dtype=np.int16)
            if len(arr) == 0:
                return

            # 1. Compute audio Peak Amplitude & RMS energy
            max_amp = float(np.max(np.abs(arr)))
            total_rms = float(np.sqrt(np.mean(arr.astype(np.float32)**2)))
            
            # Dynamic thresholding based on ambient noise floor
            dynamic_min_rms = max(self._min_rms, self._ambient_rms * 1.4)
            dynamic_chunk_rms = max(self._chunk_rms, self._ambient_rms * 1.6)

            # Reject ambient floor noise and breathing
            if max_amp < self._min_peak or total_rms < dynamic_min_rms:
                return

            # 2. Acoustic Speech Density Verification (20ms frames)
            chunk_size = int(self._sample_rate * 0.02)
            num_chunks = len(arr) // chunk_size
            if num_chunks < 15:  # Less than 0.30s
                return

            voice_chunks = 0
            for i in range(num_chunks):
                c = arr[i * chunk_size : (i + 1) * chunk_size]
                c_rms = np.sqrt(np.mean(c.astype(np.float32)**2))
                c_peak = np.max(np.abs(c))
                if c_rms > dynamic_chunk_rms and c_peak > self._chunk_peak:
                    voice_chunks += 1

            voice_ratio = voice_chunks / num_chunks
            total_voice_duration = voice_chunks * 0.02

            # Real human speech must occupy >= 18% of buffer and have at least 0.20s continuous voice energy
            if total_voice_duration < 0.20 or voice_ratio < self._voice_ratio_min:
                return

            wav_io = io.BytesIO()
            with wave.open(wav_io, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self._sample_rate)
                wf.writeframes(arr.tobytes())

            wav_bytes = wav_io.getvalue()

            # Estimate voice pitch and gender
            _, gender = estimate_pitch_and_gender(arr, self._sample_rate)
            gender_msg = String()
            gender_msg.data = gender
            self._gender_pub.publish(gender_msg)

            # Acoustic Speaker Identification (Voiceprint Matching)
            spk_name, spk_conf, spk_meta = self.voice_recognizer.recognize_voice(arr, self._sample_rate)
            is_known_spk = (spk_name is not None and spk_conf >= 0.40)
            spk_info = {

                "name": spk_name if is_known_spk else "Misafir",
                "title": spk_meta.get("title", "Konuşmacı"),
                "formal_title": spk_meta.get("formal_title", "Misafir"),
                "confidence": spk_conf,
                "is_known": is_known_spk,
                "gender": gender
            }
            spk_msg = String()
            spk_msg.data = json.dumps(spk_info)
            self._speaker_pub.publish(spk_msg)

            if is_known_spk:
                self.get_logger().info(f"🎙️ [Ses Tanıma]: {spk_name} ({spk_meta.get('formal_title', '')}) (Güven: {spk_conf:.2f})")

            text = None

            # 1. Ultra-Fast Groq Whisper Large V3 (80ms Latency - Primary Free STT)
            if self.groq_client:
                try:
                    result = self.groq_client.audio.transcriptions.create(
                        file=("speech.wav", wav_bytes),
                        model="whisper-large-v3",
                        language="tr",
                        temperature=0.0,
                        response_format="text"
                    )
                    text = str(result).strip()
                except Exception as ge:
                    self.get_logger().warn(f"⚠️ [Groq Whisper] Hatası ({ge}), yedek motorlara geçiliyor...")

            # 2. OpenAI Whisper-1 Fallback
            if not text and self.openai_client:
                try:
                    res = self.openai_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=("speech.wav", wav_bytes),
                        language="tr",
                        temperature=0.0,
                        response_format="text"
                    )
                    text = str(res).strip()
                except Exception as oe:
                    self.get_logger().warn(f"⚠️ [OpenAI Whisper] Hatası: {oe}")

            # 3. Yerel Faster-Whisper (Yalnızca bulut motorlar başarısız olursa)
            if not text and self.fw_model is not None:
                try:
                    audio_f32 = arr.astype(np.float32) / 32768.0
                    segments, _info = self.fw_model.transcribe(
                        audio_f32, beam_size=1, language="tr"
                    )
                    text = "".join(seg.text for seg in segments).strip()
                except Exception as fe:
                    self.get_logger().warn(f"⚠️ [Faster-Whisper] Hatası ({fe})")


            if not text:
                return
            text_lower = text.lower().strip(" .,!?:;")

            # Hallucination Filter: Ignore known Whisper silence phantom phrases
            silence_hallucinations = [
                "iyi misin", "teşekkür ederim", "teşekkürler", "altyazı", "abone ol",
                "görüşmek üzere", "hoşça kalın", "hoşçakalın", "sağ olun", "kalbimde sizle geldim",
                "merhaba, kalbimde sizle geldim", "sizle geldim", "ben ali", "merhaba, ben ali",
                "sıfır tutu", "gizletme üzerime", "yanıldım gözlerimde"
            ]
            if any(sh in text_lower for sh in silence_hallucinations) and (total_rms < 500.0 or voice_ratio < 0.35):
                return

            # Reject isolated 'merhaba' if voice energy is low or voice duration under 0.5s
            if text_lower in ["merhaba", "merhabalar"] and (total_rms < 480.0 or total_voice_duration < 0.45):
                return

            # Context-aware single-word filter: Only reject when NO active conversation session
            # During active session, "evet"/"hayır"/"tamam" are legitimate user responses
            always_hallucinations = ["hı hı", "hı", "cık", "çık", "eee", "ııı", "hmm"]
            session_dependent = ["evet", "hayır", "tamam"]
            if text_lower in always_hallucinations:
                return
            if text_lower in session_dependent and not self._session_active:
                return

            # Filter empty / junk / phantom noise
            junk_filters = [
                "altyazı", "abone ol", "izlediğiniz için", "www.", ".com",
                "you", "thank you", "bye", "subtitles", "watching", "amara.org",
                "kalbimde", "sizle geldim", "sıfır tutu", "gizletme üzerime"
            ]
            if any(junk in text_lower for junk in junk_filters):
                return

            if len(text_lower) < 3 and text_lower not in ["ne", "su", "al", "ev", "on"]:
                return

            # ── Self-Echo Immunity Check ──────────────────────────────────────────
            # If the transcribed text matches something Astro itself said in the last 8s, DISCARD IT!
            now = time.monotonic()
            with self._lock:
                for past_phrase, past_time in self._recent_tts_phrases:
                    if (now - past_time) < 8.0:
                        if text_lower in past_phrase or past_phrase in text_lower:
                            self.get_logger().info(f'🔇 [Yankı / Robot Kendi Sesini Duydu — Filtrelendi]: "{text}"')
                            return
                        # Check word overlap
                        words_heard = set(text_lower.split())
                        words_spoken = set(past_phrase.split())
                        if len(words_heard) >= 2 and len(words_heard.intersection(words_spoken)) >= len(words_heard) * 0.75:
                            self.get_logger().info(f'🔇 [Yankı / Robot Kendi Sesini Duydu — Filtrelendi]: "{text}"')
                            return

            if text and text not in [".", "...", ",", "!", "?"]:
                # Discard stale results
                with self._transcribe_lock:
                    if seq != self._stt_sequence:
                        return

                self.get_logger().info(f'🎤 [Duyulan]: "{text}"')
                msg = String()
                msg.data = text
                self._text_pub.publish(msg)

        except Exception as e:
            self.get_logger().error(f"❌ [STT] Transcribe hatası: {e}")


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
