#!/usr/bin/env python3
"""ASTRO V1 — Speech Recognition Node (Groq Whisper).

Subscribes to:
  /audio/speech_audio  (Int16MultiArray) — raw 16kHz mono PCM from audio_capture_node
  /audio/vad           (Bool)            — voice activity detection flag
  /tts/speaking        (Bool)            — TTS playback state (echo prevention)

Publishes:
  /speech/text         (String)          — final transcribed text

Pipeline:
  1. Continuously buffers audio from /audio/speech_audio when VAD is active
  2. On silence timeout (1.2s), sends buffer to Groq Whisper-large-v3 API
  3. Publishes transcribed text to /speech/text
  4. Ignores audio while TTS is speaking (echo cancellation)
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
            self.get_logger().error("groq package not installed. STT disabled.")
            self.enabled = False
            return
            
        _load_env()
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            self.get_logger().error("GROQ_API_KEY not found in environment. STT disabled.")
            self.enabled = False
            return
            
        try:
            self.groq_client = Groq(api_key=api_key)
        except Exception as e:
            self.get_logger().error(f"Failed to init Groq client: {e}")
            self.enabled = False
            return
            
        # Parameters
        self.declare_parameter('silence_timeout_s', 0.75)
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
        self._ring_buffer: list[int] = []  # max 6400 samples
        self._is_speaking: bool = False
        self._last_speech_time: float | None = None
        self._tts_speaking: bool = False
        self._last_tts_end_time: float | None = None
        
        # Timer
        self.create_timer(0.1, self._silence_tick)
        
        self.get_logger().info("[STT] Groq Whisper aktif.")
        
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
            if self._last_tts_end_time is not None and (time.monotonic() - self._last_tts_end_time) < 0.8:
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
            
        if not msg.data:
            return
            
        with self._lock:
            if self._tts_speaking:
                return
            if self._last_tts_end_time is not None and (time.monotonic() - self._last_tts_end_time) < 0.8:
                return
                
            if not self._is_speaking:
                self._buffer.extend(self._ring_buffer)
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
                    
        if audio_data is not None and len(audio_data) >= 4800:
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
            
            result = self.groq_client.audio.transcriptions.create(
                file=("speech.wav", wav_bytes),
                model="whisper-large-v3",
                language="tr",
                response_format="text"
            )
            
            text = str(result).strip()
            text_lower = text.lower()
            
            # Filter junk hallucinations
            if any(junk in text_lower for junk in ["altyazı", "abone ol", "izlediğiniz için"]):
                return
                
            if text:
                self.get_logger().info(f'[STT] "{text}"')
                msg = String()
                msg.data = text
                self._text_pub.publish(msg)
                
        except Exception as e:
            self.get_logger().error(f"[STT] Transcribe error: {e}")

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
