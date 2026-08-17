#!/usr/bin/env python3
"""ASTRO V1 — In-Memory Text-to-Speech Node.

Features:
  - In-Memory RAM Synthesis: Edge-TTS converted via FFmpeg pipe
  - Robust ALSA/ReSpeaker Playback via aplay / sounddevice fallback
  - Dynamic Emotion-based speech rate (+5% to +35%)
  - Hardware barge-in interrupt with immediate process termination
"""

import os
import re
import asyncio
import subprocess
import threading
import queue
import shutil

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool

try:
    import edge_tts
except ImportError:
    edge_tts = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

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


def find_respeaker_alsa_device():
    """Finds exact ALSA card name or index for ReSpeaker."""
    try:
        res = subprocess.run(["aplay", "-l"], capture_output=True, text=True)
        for line in res.stdout.splitlines():
            if any(k in line.lower() for k in ["respeaker", "arrayuac", "uac1.0", "seeed"]):
                # Extract card number e.g. card 0:
                m = re.search(r"card\s+(\d+):", line)
                if m:
                    return f"plughw:{m.group(1)},0"
    except Exception:
        pass
    return "default"


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

        self.tts_engine = os.getenv("TTS_ENGINE", "openai").lower()
        self.openai_voice = os.getenv("OPENAI_TTS_VOICE", "onyx")
        self.tts_voice = os.getenv("TTS_VOICE", "tr-TR-AhmetNeural")
        self.tts_rate = os.getenv("TTS_RATE", "+25%")
        self.sample_rate = int(os.getenv("SAMPLE_RATE", "16000"))

        self.alsa_device = find_respeaker_alsa_device()
        self.has_aplay = shutil.which("aplay") is not None

        # OpenAI TTS Client
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip() or os.environ.get("AI_API_KEY", "").strip()
        self._openai_client = None
        if OpenAI and self.openai_api_key and self.openai_api_key.startswith("sk-"):
            try:
                self._openai_client = OpenAI(api_key=self.openai_api_key)
                if self.tts_engine == "openai":
                    self.get_logger().info(f"🚀 [TTS Node] OpenAI TTS-1 Motoru Aktif! Ses: [{self.openai_voice}] (HD İnsansı Vurgu)")
            except Exception as e:
                self.get_logger().error(f"❌ [TTS Node] OpenAI client başlatılamadı: {e}")

        if edge_tts is None and self._openai_client is None:
            self.get_logger().error("❌ [TTS] Ne OpenAI ne de edge_tts modülü kullanılamıyor!")

        # Publishers
        self.pub_speaking = self.create_publisher(Bool, '/tts/speaking', 10)

        # Subscribers
        self.sub_say = self.create_subscription(String, '/tts/say', self._on_say, 10)
        self.sub_interrupt = self.create_subscription(Bool, '/tts/interrupt', self._on_interrupt, 10)
        self.sub_emotion = self.create_subscription(String, '/robot/emotion', self._on_emotion, 10)

        # Internal state
        self._current_rate = self.tts_rate
        self._current_speed = 1.05
        self._speak_queue = queue.Queue()
        self._generation = 0
        self._generation_lock = threading.Lock()
        self._current_process = None   # aplay process
        self._current_ffmpeg = None    # ffmpeg decode process

        # Playback Thread
        self._playback_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._playback_thread.start()

        engine_name = f"OpenAI TTS-1 ({self.openai_voice})" if self.tts_engine == "openai" and self._openai_client else f"Edge-TTS ({self.tts_voice})"
        self.get_logger().info(f"🔊 [TTS Node] ALSA ReSpeaker Hazır! Motor: {engine_name} | Çıkış: [{self.alsa_device}]")

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
        speed_map = {
            "angry": 1.20,
            "rude": 1.15,
            "sarcastic": 1.10,
            "playful": 1.08,
            "formal": 1.00,
            "emotional": 0.95,
        }
        if emotion in rate_map:
            self._current_rate = rate_map[emotion]
            self._current_speed = speed_map.get(emotion, 1.05)

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
            # Kill both FFmpeg decode and aplay playback to prevent zombie processes
            for proc in (self._current_ffmpeg, self._current_process):
                if proc is not None:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
            self._current_ffmpeg = None
            self._current_process = None
            self._set_speaking(False)

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

        if not text:
            return

        try:
            self.get_logger().info(f'🔊 [TTS Okuyor]: "{text}"')
            wav_data = None

            # 1. Try Primary OpenAI TTS-1 (Natural Human Inflection & Direct WAV)
            if self.tts_engine == "openai" and self._openai_client:
                try:
                    resp = self._openai_client.audio.speech.create(
                        model="tts-1",
                        voice=self.openai_voice,
                        input=text,
                        response_format="wav",
                        speed=self._current_speed
                    )
                    wav_data = resp.content
                except Exception as oai_err:
                    self.get_logger().warn(f"⚠️ [OpenAI TTS Hatası] ({oai_err}), Edge-TTS yedeğe geçiliyor...")

            with self._generation_lock:
                if current_gen != self._generation:
                    return

            # 2. Fallback to Edge-TTS In-Memory Synthesis via FFmpeg
            if not wav_data and edge_tts is not None:
                try:
                    mp3_bytes = asyncio.run(_async_synthesize_bytes(text, self.tts_voice, self._current_rate))
                    with self._generation_lock:
                        if current_gen != self._generation:
                            return

                    if mp3_bytes:
                        ffmpeg_proc = subprocess.Popen(
                            ["ffmpeg", "-loglevel", "quiet", "-i", "pipe:0", "-f", "wav",
                             "-ar", str(self.sample_rate), "-ac", "1", "pipe:1"],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL
                        )
                        self._current_ffmpeg = ffmpeg_proc
                        wav_data, _ = ffmpeg_proc.communicate(input=mp3_bytes)
                        self._current_ffmpeg = None
                except Exception as edge_err:
                    self.get_logger().warn(f"⚠️ [Edge-TTS Hatası]: {edge_err}")

            with self._generation_lock:
                if current_gen != self._generation:
                    return

            if not wav_data:
                return

            # 3. Direct Hardware Output with Cascading Fallbacks
            self._set_speaking(True)
            try:
                played = False
                if self.has_aplay:
                    devices_to_try = [self.alsa_device]
                    for d in ["default", "pulse", "sysdefault"]:
                        if d not in devices_to_try:
                            devices_to_try.append(d)

                    for dev in devices_to_try:
                        try:
                            aplay_proc = subprocess.Popen(
                                ["aplay", "-q", "-D", dev, "-"],
                                stdin=subprocess.PIPE,
                                stderr=subprocess.PIPE
                            )
                            self._current_process = aplay_proc
                            _, stderr_data = aplay_proc.communicate(input=wav_data)
                            if aplay_proc.returncode == 0:
                                played = True
                                break
                            else:
                                err_txt = stderr_data.decode('utf-8', errors='ignore') if stderr_data else ""
                                self.get_logger().debug(f"aplay -D {dev} çıkış hatası ({aplay_proc.returncode}): {err_txt}")
                        except Exception as pe:
                            self.get_logger().debug(f"aplay {dev} istisnası: {pe}")

                if not played and sd is not None:
                    try:
                        import io
                        import wave
                        import numpy as np
                        wav_io = io.BytesIO(wav_data)
                        with wave.open(wav_io, 'rb') as wf:
                            raw_pcm = wf.readframes(wf.getnframes())
                            actual_sr = wf.getframerate()
                        arr = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
                        sd.play(arr, samplerate=actual_sr)
                        sd.wait()
                        played = True
                    except Exception as sde:
                        self.get_logger().warn(f"SoundDevice çalma hatası: {sde}")

                if not played:
                    self.get_logger().warn("⚠️ [TTS] Hiçbir ses çıkış aygıtına ulaşılamadı (aplay/sounddevice başarısız)!")

            finally:
                self._current_process = None
                self._current_ffmpeg = None
                self._set_speaking(False)

        except Exception as e:
            self.get_logger().warn(f"TTS Playback Hatası: {e}")
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
