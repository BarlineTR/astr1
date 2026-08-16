#!/usr/bin/env python3
"""ASTRO V1 — Text-to-Speech Node (Edge-TTS + sounddevice).

Subscribes to:
  /tts/say       (String) — text to speak
  /tts/interrupt  (Bool)  — cancel current playback

Publishes:
  /tts/speaking  (Bool)   — True while audio is playing (echo prevention)

Pipeline:
  1. Receives text on /tts/say
  2. Cleans text (emoji, markdown removal)
  3. Synthesizes via Edge-TTS (tr-TR-AhmetNeural, +20% rate)
  4. Converts MP3→WAV via ffmpeg
  5. Plays via sounddevice on ReSpeaker output
  6. Manages a queue for sequential playback with prefetch
"""

import os
import re
import asyncio
import tempfile
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
    """Emoji ve markdown temizler."""
    if not text:
        return ""
    # Emojileri temizle
    text = EMOJI_RE.sub("", text)
    # Markdown kod bloklarını temizle
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'`.*?`', '', text)
    # Kalın, italik vs
    text = re.sub(r'[\*\_\~\#]', '', text)
    # Fazla boşlukları temizle
    text = " ".join(text.split())
    # Noktalama hatalarını düzelt
    text = re.sub(r'\s+([,.:;?!])', r'\1', text)
    return text.strip()

def find_output_device() -> int | None:
    """ReSpeaker çıkış cihazını bulur, bulamazsa varsayılanı kullanır."""
    if not sd:
        return None
    try:
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            name = dev.get("name", "").lower()
            if dev.get("max_output_channels", 0) > 0:
                if "respeaker" in name or "uac1" in name or "seeed" in name:
                    return i
        return None  # Fallback to default
    except Exception:
        return None


class TtsNode(Node):
    def __init__(self):
        super().__init__('tts_node')
        _load_env()
        
        # Load params from env
        self.tts_voice = os.getenv("TTS_VOICE", "tr-TR-AhmetNeural")
        self.tts_rate = os.getenv("TTS_RATE", "+20%")
        self.sample_rate = int(os.getenv("SAMPLE_RATE", "16000"))
        
        self.out_device_id = find_output_device()
        
        if edge_tts is None:
            self.get_logger().error("edge_tts modülü bulunamadı, sentezleme yapılamayacak.")
            
        if sd is None:
            self.get_logger().error("sounddevice modülü bulunamadı, oynatma yapılamayacak.")
        
        # Publishers & Subscribers
        self.pub_speaking = self.create_publisher(Bool, '/tts/speaking', 10)
        self.sub_say = self.create_subscription(String, '/tts/say', self._on_say, 10)
        self.sub_interrupt = self.create_subscription(Bool, '/tts/interrupt', self._on_interrupt, 10)
        
        # Internal state
        self._speak_queue = queue.Queue()
        self._generation = 0
        self._generation_lock = threading.Lock()
        
        # Thread
        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._playback_thread.start()
        
        self.get_logger().info(f"TTS Node başlatıldı. Ses: {self.tts_voice}, Hız: {self.tts_rate}")

    def _on_say(self, msg: String):
        text = clean_tts_text(msg.data)
        if text:
            self._speak_queue.put(text)

    def _on_interrupt(self, msg: Bool):
        if msg.data:
            with self._generation_lock:
                self._generation += 1
            # Drain queue
            while not self._speak_queue.empty():
                try:
                    self._speak_queue.get_nowait()
                except queue.Empty:
                    break
            if sd is not None:
                try:
                    sd.stop()
                except Exception as e:
                    self.get_logger().error(f"sd.stop() hatası: {e}")

    def _set_speaking(self, state: bool):
        msg = Bool()
        msg.data = state
        self.pub_speaking.publish(msg)

    def _playback_loop(self):
        while rclpy.ok():
            try:
                text = self._speak_queue.get(timeout=0.5)
                self._synthesize_and_play(text)
            except queue.Empty:
                continue
            except Exception as e:
                self.get_logger().error(f"Playback loop hatası: {e}")

    def _synthesize_and_play(self, text: str):
        with self._generation_lock:
            current_gen = self._generation
            
        if edge_tts is None:
            return

        fd_mp3, mp3_path = tempfile.mkstemp(suffix=".mp3")
        fd_wav, wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd_mp3)
        os.close(fd_wav)

        try:
            # 1. Synthesize via edge_tts (async to sync wrapper)
            communicate = edge_tts.Communicate(text, self.tts_voice, rate=self.tts_rate)
            asyncio.run(communicate.save(mp3_path))
            
            with self._generation_lock:
                if current_gen != self._generation:
                    return

            # 2. Convert to WAV via ffmpeg
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_path, "-ar", str(self.sample_rate), "-ac", "1", "-f", "wav", wav_path],
                    check=True
                )
            except subprocess.CalledProcessError as e:
                self.get_logger().error(f"FFmpeg çevirme hatası: {e}")
                return

            with self._generation_lock:
                if current_gen != self._generation:
                    return

            # 3. Read and Play
            if wav is None or sd is None:
                # Fallback to shell command if sounddevice missing
                self._set_speaking(True)
                try:
                    subprocess.run(["ffplay", "-nodisp", "-autoexit", wav_path], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                except Exception as e:
                    self.get_logger().error(f"ffplay fallback hatası: {e}")
                finally:
                    self._set_speaking(False)
                return

            try:
                rate, data = wav.read(wav_path)
            except Exception as e:
                self.get_logger().error(f"WAV okuma hatası: {e}")
                return

            with self._generation_lock:
                if current_gen != self._generation:
                    return

            try:
                self._set_speaking(True)
                sd.play(data, samplerate=rate, device=self.out_device_id, blocking=True)
            except Exception as e:
                self.get_logger().error(f"sounddevice oynatma hatası: {e}")
            finally:
                self._set_speaking(False)

        except Exception as e:
            self.get_logger().error(f"Synthesize error: {e}")
            self._set_speaking(False)
        finally:
            # Cleanup temp files
            try:
                if os.path.exists(mp3_path):
                    os.remove(mp3_path)
                if os.path.exists(wav_path):
                    os.remove(wav_path)
            except Exception as e:
                self.get_logger().error(f"Temp dosya silme hatası: {e}")

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
        rclpy.shutdown()

if __name__ == '__main__':
    main()
