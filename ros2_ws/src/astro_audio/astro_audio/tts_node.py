#!/usr/bin/env python3
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


class TtsNode(Node):
    def __init__(self):
        super().__init__("tts_node")
        self.declare_parameter("engine", "pyttsx3")
        self.declare_parameter("language", "tr")
        self.declare_parameter("rate", 150)
        self.declare_parameter("volume", 0.8)

        self.engine_name = self.get_parameter("engine").value
        self.language = self.get_parameter("language").value
        self.rate = int(self.get_parameter("rate").value)
        self.volume = float(self.get_parameter("volume").value)

        self.pub_speaking = self.create_publisher(Bool, "/tts/speaking", 10)
        self.sub = self.create_subscription(String, "/tts/say", self.say_callback, 10)

        self.speaking = False
        self.mute_lock = threading.Lock()
        self.tts_engine = None

        if self.engine_name == "pyttsx3":
            self._init_pyttsx3()
        elif self.engine_name == "gtts":
            self.get_logger().info("Using gTTS engine (requires internet)")
        else:
            self.get_logger().error(f"Unknown TTS engine: {self.engine_name}")

    def _init_pyttsx3(self):
        if pyttsx3 is None:
            self.get_logger().error("pyttsx3 not installed")
            return
        self.tts_engine = pyttsx3.init()
        self.tts_engine.setProperty("rate", self.rate)
        self.tts_engine.setProperty("volume", self.volume)
        for voice in self.tts_engine.getProperty("voices"):
            if self.language in voice.id.lower() or self.language in voice.name.lower():
                self.tts_engine.setProperty("voice", voice.id)
                break
        self.get_logger().info("pyttsx3 TTS engine ready")

    def _set_speaking(self, state: bool):
        self.speaking = state
        msg = Bool()
        msg.data = state
        self.pub_speaking.publish(msg)

    def say_callback(self, msg: String):
        text = msg.data.strip()
        if not text:
            return
        thread = threading.Thread(target=self._speak, args=(text,), daemon=True)
        thread.start()

    def _speak(self, text: str):
        with self.mute_lock:
            self._set_speaking(True)
            try:
                if self.engine_name == "pyttsx3" and self.tts_engine is not None:
                    self.tts_engine.say(text)
                    self.tts_engine.runAndWait()
                elif self.engine_name == "gtts":
                    self._speak_gtts(text)
                else:
                    self.get_logger().warn("TTS engine not available")
            except Exception as e:
                self.get_logger().error(f"TTS failed: {e}")
            finally:
                self._set_speaking(False)

    def _speak_gtts(self, text: str):
        from gtts import gTTS

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            tmp_path = f.name
        try:
            tts = gTTS(text=text, lang=self.language)
            tts.save(tmp_path)
            subprocess.run(
                ["mpg123", "-q", tmp_path],
                check=True,
                capture_output=True,
            )
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


def main():
    rclpy.init()
    node = TtsNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
