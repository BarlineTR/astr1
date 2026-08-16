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
        if Groq is None:
            self.get_logger().error("❌ [STT] groq kütüphanesi kurulu değil!")
            self.enabled = False
            return

        _load_env()
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            self.get_logger().error("❌ [STT] GROQ_API_KEY bulunamadı! STT devre dışı.")
            self.enabled = False
            return

        try:
            self.groq_client = Groq(api_key=api_key)
        except Exception as e:
            self.get_logger().error(f"❌ [STT] Groq client başlatılamadı: {e}")
            self.enabled = False
            return

        # Parameters (Natural conversational turn-taking: 0.65s silence pause tolerance)
        self.declare_parameter('silence_timeout_s', 0.65)
        self.declare_parameter('sample_rate', 16000)
        self._silence_timeout_s = float(self.get_parameter('silence_timeout_s').value)
        self._sample_rate = int(self.get_parameter('sample_rate').value)

        # Publishers
        self._text_pub = self.create_publisher(String, '/speech/text', 10)
        self._gender_pub = self.create_publisher(String, '/audio/speaker_gender', 10)
        self._interrupt_pub = self.create_publisher(Bool, '/tts/interrupt', 10)

        # Subscribers
        self.create_subscription(Int16MultiArray, '/audio/speech_audio', self._audio_cb, 10)
        self.create_subscription(Bool, '/audio/vad', self._vad_cb, 10)
        self.create_subscription(Bool, '/tts/speaking', self._tts_speaking_cb, 10)
        self.create_subscription(String, '/tts/say', self._tts_say_cb, 10)

        # Internal state
        self._lock = threading.Lock()
        self._buffer: list[int] = []
        self._ring_buffer: list[int] = []  # 6400 samples (0.4s pre-roll)
        self._is_speaking: bool = False
        self._last_speech_time: float | None = None
        self._tts_speaking: bool = False
        self._tts_speaking_start_time: float | None = None
        self._last_tts_end_time: float | None = None
        self._recent_tts_phrases: list[tuple[str, float]] = []  # (phrase_lower, timestamp)

        # Guards against concurrent / out-of-order transcription results
        self._transcribe_lock = threading.Lock()
        self._stt_sequence: int = 0

        # Timer (0.05s resolution)
        self.create_timer(0.05, self._silence_tick)

        self.get_logger().info("✅ [STT] Groq Whisper-large-v3 + Self-Echo Immunity Hazır.")

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

        if audio_data is not None and len(audio_data) >= 4800:  # at least 0.3s
            with self._transcribe_lock:
                self._stt_sequence += 1
                my_seq = self._stt_sequence
            threading.Thread(target=self._transcribe, args=(audio_data, my_seq), daemon=True).start()

    def _transcribe(self, audio_data: list[int], seq: int):
        try:
            arr = np.array(audio_data, dtype=np.int16)

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

            # Turkish whisper prompt hinting for accurate recognition
            whisper_prompt = "Astro, hey astro, robot, naber, nasılsın, ne haber, elinde ne var, beni görüyor musun, nasılsın iyi misin."

            result = self.groq_client.audio.transcriptions.create(
                file=("speech.wav", wav_bytes),
                model="whisper-large-v3",
                language="tr",
                prompt=whisper_prompt,
                temperature=0.0,
                response_format="text"
            )

            text = str(result).strip()
            text_lower = text.lower().strip(" .,!?:;")

            # Exact match hallucination filter
            exact_hallucinations = ["evet", "hayır", "tamam", "hı hı", "hı", "cık", "çık", "eee", "ııı", "hmm"]
            if text_lower in exact_hallucinations:
                return

            # Filter empty / junk / phantom noise
            junk_filters = [
                "altyazı", "abone ol", "izlediğiniz için", "www.", ".com",
                "you", "thank you", "bye", "subtitles", "watching", "amara.org"
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
