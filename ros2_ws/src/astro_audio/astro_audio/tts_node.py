#!/usr/bin/env python3
"""ASTRO V1 — Real-Time Live Streaming Text-to-Speech Node.

Features:
  - Zero-Wait Chunk Streaming: Audio starts playing the millisecond first chunk arrives from Edge-TTS
  - No disk I/O, no blocking for full sentence generation
  - Dynamic Emotion-based speech rate (+5% to +35%)
  - Immediate interruption handling via generation counter
"""

import os
import re
import asyncio
import subprocess
import threading
import queue

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


class TtsNode(Node):
    def __init__(self):
        super().__init__('tts_node')
        _load_env()

        self.tts_voice = os.getenv("TTS_VOICE", "tr-TR-AhmetNeural")
        self.tts_rate = os.getenv("TTS_RATE", "+25%")
        self.sample_rate = int(os.getenv("SAMPLE_RATE", "16000"))

        if edge_tts is None:
            self.get_logger().error("❌ [TTS] edge_tts modülü kurulu değil!")

        # Publishers
        self.pub_speaking = self.create_publisher(Bool, '/tts/speaking', 10)

        # Subscribers
        self.sub_say = self.create_subscription(String, '/tts/say', self._on_say, 10)
        self.sub_interrupt = self.create_subscription(Bool, '/tts/interrupt', self._on_interrupt, 10)
        self.sub_emotion = self.create_subscription(String, '/robot/emotion', self._on_emotion, 10)

        # Internal state
        self._current_rate = self.tts_rate
        self._speak_queue = queue.Queue()
        self._generation = 0
        self._generation_lock = threading.Lock()
        self._active_proc = None

        # Playback Thread
        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._playback_thread.start()

        self.get_logger().info(f"🔊 [TTS Node] Canlı Sıfır Gecikmeli Streaming Hazır! Ses: {self.tts_voice}")

    def _on_emotion(self, msg: String):
        emotion = msg.data.lower().strip()
        rate_map = {
            "angry": "+35%",
            "rude": "+30%",
            "sarcastic": "+25%",
            "playful": "+25%",
            "formal": "+15%",
            "emotional": "+5%",
        }
        if emotion in rate_map:
            self._current_rate = rate_map[emotion]

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
            if self._active_proc:
                try:
                    self._active_proc.terminate()
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
                self._stream_and_play(text)
            except queue.Empty:
                continue
            except Exception as e:
                self.get_logger().error(f"Playback loop hatası: {e}")

    def _stream_and_play(self, text: str):
        with self._generation_lock:
            current_gen = self._generation

        if edge_tts is None or not text:
            return

        self.get_logger().info(f'🔊 [TTS Canlı Okuyor]: "{text}"')
        self._set_speaking(True)

        # Launch ffplay in streaming pipe mode (starts playing immediately on first byte)
        try:
            player_cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-i", "pipe:0"]
            proc = subprocess.Popen(player_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self._active_proc = proc

            async def _pipe_stream():
                communicate = edge_tts.Communicate(text, self.tts_voice, rate=self._current_rate)
                async for chunk in communicate.stream():
                    with self._generation_lock:
                        if current_gen != self._generation:
                            break
                    if chunk["type"] == "audio" and proc.stdin:
                        try:
                            proc.stdin.write(chunk["data"])
                            proc.stdin.flush()
                        except (BrokenPipeError, IOError):
                            break

            asyncio.run(_pipe_stream())

            if proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

            proc.wait(timeout=10.0)

        except Exception as e:
            self.get_logger().warn(f"Streaming TTS Hatası: {e}")
        finally:
            self._active_proc = None
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
