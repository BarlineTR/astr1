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

        # Parameters (Fast Turn-Taking: 0.40s silence timeout)
        self.declare_parameter('silence_timeout_s', 0.40)
        self.declare_parameter('sample_rate', 16000)
        self._silence_timeout_s = float(self.get_parameter('silence_timeout_s').value)
        self._sample_rate = int(self.get_parameter('sample_rate').value)

        # Publishers
        self._text_pub = self.create_publisher(String, '/speech/text', 10)

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

        self.get_logger().info("✅ [STT] Groq Whisper-large-v3 Hazır ve Dinliyor.")

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
        try:
            arr = np.array(audio_data, dtype=np.int16)

            wav_io = io.BytesIO()
            with wave.open(wav_io, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self._sample_rate)
                wf.writeframes(arr.tobytes())

            wav_bytes = wav_io.getvalue()

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

            # Filter hallucination / empty / junk / phantom noise
            junk_filters = [
                "altyazı", "abone ol", "izlediğiniz için", "www.", ".com",
                "you", "thank you", "bye", "subtitles", "watching", "amara.org",
                "hı hı", "hı", "cık", "çık", "eee", "ııı", "hmm"
            ]
            if any(junk == text_lower or junk in text_lower for junk in junk_filters):
                return

            if len(text_lower) < 3 and text_lower not in ["ne", "su", "al", "ev", "on"]:
                return

            if text and text not in [".", "...", ",", "!", "?"]:
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
