#!/usr/bin/env python3
import json
import threading

import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Int16MultiArray, String

try:
    from vosk import KaldiRecognizer, Model, SetLogLevel
except ImportError:
    KaldiRecognizer = None
    Model = None
    SetLogLevel = None


class SpeechRecognitionNode(Node):
    def __init__(self):
        super().__init__("speech_recognition_node")
        self.declare_parameter("model_path", "/opt/vosk/vosk-model-small-tr-0.3")
        self.declare_parameter("language", "tr")
        self.declare_parameter("partial_results", True)
        self.declare_parameter("silence_timeout_s", 0.5)

        model_path = self.get_parameter("model_path").value
        self.partial_results = self.get_parameter("partial_results").value
        self.silence_timeout_s = float(self.get_parameter("silence_timeout_s").value)

        self.pub_text = self.create_publisher(String, "/speech/text", 10)
        self.sub = self.create_subscription(
            Int16MultiArray, "/audio/speech_audio", self.audio_callback, 10
        )

        self.buffer = []
        self.last_audio_time = None
        self.lock = threading.Lock()

        if Model is None:
            self.get_logger().error("vosk not installed — speech recognition disabled")
            self.recognizer = None
            return

        if SetLogLevel is not None:
            SetLogLevel(-1)

        try:
            self.model = Model(model_path)
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self.recognizer.SetWords(True)
            self.get_logger().info(f"Vosk model loaded: {model_path}")
        except Exception as e:
            self.get_logger().error(f"Failed to load Vosk model: {e}")
            self.recognizer = None

        self.create_timer(0.1, self._silence_tick)

    def audio_callback(self, msg: Int16MultiArray):
        if self.recognizer is None:
            return

        with self.lock:
            self.buffer.extend(msg.data)
            self.last_audio_time = self.get_clock().now()

    def _process_buffer(self):
        with self.lock:
            if not self.buffer:
                return
            audio_bytes = np.array(self.buffer, dtype=np.int16).tobytes()
            self.buffer.clear()
            self.last_audio_time = None

        if self.recognizer.AcceptWaveform(audio_bytes):
            result = json.loads(self.recognizer.Result())
            text = result.get("text", "").strip()
            if text:
                self._publish_text(text)
        elif self.partial_results:
            partial = json.loads(self.recognizer.PartialResult())
            text = partial.get("partial", "").strip()
            if text:
                self._publish_text(text, partial=True)

    def _publish_text(self, text: str, partial: bool = False):
        msg = String()
        msg.data = text
        self.pub_text.publish(msg)
        if partial:
            self.get_logger().debug(f"Partial: {text}")
        else:
            self.get_logger().info(f"Recognized: {text}")

    def _silence_tick(self):
        # 1. Tamponda veri varsa isleyelim
        with self.lock:
            has_data = len(self.buffer) > 0
        if has_data:
            self._process_buffer()
            
        # 2. Eger VAD'den uzun suredir (0.5s) veri gelmediyse, konusma bitmistir
        now = self.get_clock().now()
        with self.lock:
            if self.last_audio_time is not None:
                elapsed = (now - self.last_audio_time).nanoseconds / 1e9
                if elapsed > self.silence_timeout_s:
                    # Konusma bitti, zorla sonucu alalim
                    result = json.loads(self.recognizer.FinalResult())
                    text = result.get("text", "").strip()
                    if text:
                        self._publish_text(text)
                    self.last_audio_time = None
                    # Modeli sifirlamak icin (yeni cumleye hazirlik)
                    self.recognizer.Reset()


def main():
    rclpy.init()
    node = SpeechRecognitionNode()
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
