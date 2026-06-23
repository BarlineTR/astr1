#!/usr/bin/env python3
"""ASTRO V1 — Text-to-Speech Node.

Supports three engines selectable via TTS_ENGINE env var:
  * edge-tts  — High-quality Microsoft Neural voices (requires internet)
  * pyttsx3   — Offline robotic fallback
  * gtts      — Google TTS (requires internet)
"""
import os
import subprocess
import tempfile
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    import edge_tts
    import asyncio
except ImportError:
    edge_tts = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


class TtsNode(Node):
    def __init__(self):
        super().__init__("tts_node")

        # Load .env (guard against missing dotenv)
        if load_dotenv is not None:
            load_dotenv(os.path.join(os.getcwd(), ".env"))

        # ROS parameters — defaults pulled from environment
        self.declare_parameter("engine", os.getenv("TTS_ENGINE", "edge-tts"))
        self.declare_parameter("voice", os.getenv("TTS_VOICE", "tr-TR-AhmetNeural"))
        self.declare_parameter("language", "tr")
        self.declare_parameter("rate", 150)
        self.declare_parameter("volume", 0.8)

        self.engine_name = self.get_parameter("engine").value
        self.voice_name = self.get_parameter("voice").value
        self.language = self.get_parameter("language").value
        self.rate = int(self.get_parameter("rate").value)
        self.volume = float(self.get_parameter("volume").value)

        # Publishers / subscribers
        self.pub_speaking = self.create_publisher(Bool, "/tts/speaking", 10)
        self.sub = self.create_subscription(String, "/tts/say", self._say_callback, 10)

        self.speaking = False
        self._speak_lock = threading.Lock()
        self.tts_engine = None

        # Engine init
        if self.engine_name == "edge-tts":
            if edge_tts is None:
                self.get_logger().warn(
                    "edge-tts paketi kurulu değil, pyttsx3'e düşürülüyor. "
                    "Kurmak için: pip3 install edge-tts"
                )
                self.engine_name = "pyttsx3"
                self._init_pyttsx3()
            else:
                self.get_logger().info(
                    f"✅ [TTS] edge-tts hazır (Ses: {self.voice_name})"
                )
        elif self.engine_name == "pyttsx3":
            self._init_pyttsx3()
        elif self.engine_name == "gtts":
            self.get_logger().info("✅ [TTS] gTTS motoru seçildi (internet gerekli)")
        else:
            self.get_logger().error(f"Bilinmeyen TTS motoru: {self.engine_name}")

    # ------------------------------------------------------------------
    # pyttsx3 setup
    # ------------------------------------------------------------------
    def _init_pyttsx3(self):
        if pyttsx3 is None:
            self.get_logger().error("pyttsx3 kurulu değil — TTS devre dışı")
            return
        self.tts_engine = pyttsx3.init()
        self.tts_engine.setProperty("rate", self.rate)
        self.tts_engine.setProperty("volume", self.volume)
        for voice in self.tts_engine.getProperty("voices"):
            if self.language in voice.id.lower() or self.language in voice.name.lower():
                self.tts_engine.setProperty("voice", voice.id)
                break
        self.get_logger().info("✅ [TTS] pyttsx3 hazır")

    # ------------------------------------------------------------------
    # Speaking state management
    # ------------------------------------------------------------------
    def _set_speaking(self, state: bool):
        self.speaking = state
        msg = Bool()
        msg.data = state
        self.pub_speaking.publish(msg)

    # ------------------------------------------------------------------
    # Callback — spawn a thread so ROS spin is not blocked
    # ------------------------------------------------------------------
    def _say_callback(self, msg: String):
        text = msg.data.strip()
        if not text:
            return
        thread = threading.Thread(target=self._speak, args=(text,), daemon=True)
        thread.start()

    def _speak(self, text: str):
        with self._speak_lock:
            self._set_speaking(True)
            self.get_logger().info(f"🔊 [TTS] Söyleniyor: {text}")
            try:
                if self.engine_name == "edge-tts":
                    self._speak_edge_tts(text)
                elif self.engine_name == "pyttsx3" and self.tts_engine is not None:
                    self.tts_engine.say(text)
                    self.tts_engine.runAndWait()
                elif self.engine_name == "gtts":
                    self._speak_gtts(text)
                else:
                    self.get_logger().warn("Aktif TTS motoru yok")
            except Exception as e:
                self.get_logger().error(f"TTS hatası: {e}")
            finally:
                self._set_speaking(False)

    # ------------------------------------------------------------------
    # edge-tts — uses the Python API directly (no CLI dependency)
    # ------------------------------------------------------------------
    def _speak_edge_tts(self, text: str):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = f.name

            # edge_tts is async; run in a temporary event loop
            async def _generate():
                communicate = edge_tts.Communicate(text, self.voice_name)
                await communicate.save(tmp_path)

            asyncio.run(_generate())

            # Play the generated audio
            subprocess.run(
                ["mpg123", "-q", tmp_path],
                check=True,
                capture_output=True,
            )
        except FileNotFoundError:
            self.get_logger().error(
                "mpg123 bulunamadı. Kurmak için: sudo apt install mpg123"
            )
        except Exception as e:
            self.get_logger().error(f"edge-tts hatası: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    # ------------------------------------------------------------------
    # gTTS fallback
    # ------------------------------------------------------------------
    def _speak_gtts(self, text: str):
        from gtts import gTTS

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                tmp_path = f.name
            tts = gTTS(text=text, lang=self.language)
            tts.save(tmp_path)
            subprocess.run(
                ["mpg123", "-q", tmp_path],
                check=True,
                capture_output=True,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)


def main():
    rclpy.init()
    node = TtsNode()
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
