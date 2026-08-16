#!/usr/bin/env python3
"""ASTRO V1 — High-Speed In-Memory Text-to-Speech Node (Edge-TTS + RAM streaming).

Subscribes to:
  /tts/say       (String) — text to speak
  /tts/interrupt  (Bool)  — cancel current playback

Publishes:
  /tts/speaking  (Bool)   — True while audio is playing (echo prevention)

Performance Optimizations:
  - Zero Disk I/O: Audio synthesized in-memory and piped directly
  - Ultra-low latency playback queue
  - Fallback audio players (sounddevice -> paplay -> aplay -> ffplay)
  - Immediate interruption handling
"""

import os
import re
import io
import asyncio
import subprocess
import threading
import queue
import numpy as np

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    import sounddevice as sd
except ImportError:
    sd = None

try:
    import scipy.io.wavfile as wav
except ImportError:
    wav = None

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
    flags=re.UNICODE
)


def clean_tts_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"(?i)<think>[\s\S]*?</think>", "", text)
    text = re.sub(r"(?i)<\/?think>", "", text)
    text = EMOJI_RE.sub("", text)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`.*?`', '', text)
    text = re.sub(r'[\*\_\~\#\<\>]', '', text)
    text = " ".join(text.split())
    text = re.sub(r'\s+([,.:;?!])', r'\1', text)
    return text.strip()


def find_output_device() -> int | None:
    if not sd:
        return None
    try:
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            name = dev.get("name", "").lower()
            if dev.get("max_output_channels", 0) > 0:
                if any(k in name for k in ["respeaker", "uac1", "seeed", "arrayuac"]):
                    return i
        default_out = sd.default.device[1]
        if default_out >= 0:
            return default_out
    except Exception:
        pass
    return None


async def _async_synthesize_bytes(text: str, voice: str, rate: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buffer.extend(chunk["data"])
    return bytes(buffer)


class TtsNode(Node):
    def __init__(self):
        super().__init__('tts_node')
        _load_env()

        self.tts_voice = os.getenv("TTS_VOICE", "tr-TR-AhmetNeural")
        self.tts_rate = os.getenv("TTS_RATE", "+25%")
        self.sample_rate = int(os.getenv("SAMPLE_RATE", "16000"))

        self.out_device_id = find_output_device()

        if edge_tts is None:
            self.get_logger().error("❌ [TTS] edge_tts modülü kurulu değil!")

        # Publishers
        self.pub_speaking = self.create_publisher(Bool, '/tts/speaking', 10)

        # Subscribers
        self.sub_say = self.create_subscription(String, '/tts/say', self._on_say, 10)
        self.sub_interrupt = self.create_subscription(Bool, '/tts/interrupt', self._on_interrupt, 10)

        # Internal state
        self._speak_queue = queue.Queue()
        self._generation = 0
        self._generation_lock = threading.Lock()

        # Playback Thread
        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._playback_thread.start()

        out_name = "default"
        if sd and self.out_device_id is not None:
            try:
                out_name = sd.query_devices(self.out_device_id)['name']
            except Exception:
                pass
        self.get_logger().info(f"🔊 [TTS Node] Ultra Hızlı RAM Streaming Hazır! Ses: {self.tts_voice} | Çıkış: [{self.out_device_id}] {out_name}")

    def _on_say(self, msg: String):
        text = clean_tts_text(msg.data)
        if text:
            self._speak_queue.put(text)

    def _on_interrupt(self, msg: Bool):
        if msg.data:
            with self._generation_lock:
                self._generation += 1
            while not self._speak_queue.empty():
                try:
                    self._speak_queue.get_nowait()
                except queue.Empty:
                    break
            if sd is not None:
                try:
                    sd.stop()
                except Exception:
                    pass

    def _set_speaking(self, state: bool):
        msg = Bool()
        msg.data = state
        self.pub_speaking.publish(msg)

    def _playback_loop(self):
        while rclpy.ok():
            try:
                text = self._speak_queue.get(timeout=0.05)
                self._synthesize_and_play_memory(text)
            except queue.Empty:
                continue
            except Exception as e:
                self.get_logger().error(f"Playback loop hatası: {e}")

    def _synthesize_and_play_memory(self, text: str):
        with self._generation_lock:
            current_gen = self._generation

        if edge_tts is None:
            return

        try:
            self.get_logger().info(f'🔊 [TTS Okuyor]: "{text}"')

            # 1. In-Memory Synthesis (RAM)
            mp3_bytes = asyncio.run(_async_synthesize_bytes(text, self.tts_voice, self.tts_rate))

            with self._generation_lock:
                if current_gen != self._generation:
                    return

            if not mp3_bytes:
                return

            # 2. In-Memory Pipe Decoding via FFmpeg to 16kHz Mono PCM
            proc = subprocess.Popen(
                ["ffmpeg", "-loglevel", "quiet", "-i", "pipe:0", "-f", "s16le", "-ar", str(self.sample_rate), "-ac", "1", "pipe:1"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            pcm_data, _ = proc.communicate(input=mp3_bytes)

            with self._generation_lock:
                if current_gen != self._generation:
                    return

            if not pcm_data:
                return

            # 3. Fast Sounddevice RAM Playback
            audio_array = np.frombuffer(pcm_data, dtype=np.int16)
            played = False

            if sd is not None:
                try:
                    self._set_speaking(True)
                    with self._generation_lock:
                        if current_gen != self._generation:
                            return
                    try:
                        sd.play(audio_array, samplerate=self.sample_rate, device=self.out_device_id, blocking=True)
                        played = True
                    except Exception:
                        sd.play(audio_array, samplerate=self.sample_rate, device=None, blocking=True)
                        played = True
                except Exception as e:
                    self.get_logger().warn(f"sounddevice oynatma hatası: {e}")
                finally:
                    self._set_speaking(False)

            # 4. Fallback if sounddevice failed
            if not played:
                self._set_speaking(True)
                try:
                    p = subprocess.Popen(["aplay", "-D", "default", "-f", "S16_LE", "-r", str(self.sample_rate), "-c", "1"], stdin=subprocess.PIPE)
                    p.communicate(input=pcm_data)
                except Exception:
                    pass
                finally:
                    self._set_speaking(False)

        except Exception as e:
            self.get_logger().error(f"TTS In-Memory Sentez Hatası: {e}")
            self._set_speaking(False)


def main(args=None):
    rclpy.init(args=args)
    node = TtsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        with node._generation_lock:
            node._generation += 1
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
