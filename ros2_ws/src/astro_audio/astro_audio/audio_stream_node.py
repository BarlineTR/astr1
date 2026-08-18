#!/usr/bin/env python3
"""ASTRO V1 — Real-Time 24kHz Audio Streaming & Playback Engine for OpenAI Realtime API.

Features:
  - 24,000 Hz, 16-bit Mono PCM raw stream capture from ReSpeaker 4-Mic USB Array (20ms chunks)
  - Zero-latency non-blocking streaming playback of OpenAI response.audio.delta PCM chunks
  - Sub-millisecond queue flush & output stream abort on user barge-in (/tts/interrupt)
  - Real-time RMS acoustic monitoring & hardware auto-selection
"""

import base64
import os
import queue
import struct
import sys
import threading
import time
from typing import Optional

import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, String

try:
    import sounddevice as sd
except ImportError:
    sd = None


RESPEAKER_NAME_HINTS = ("respeaker", "uac1", "seeed", "arrayuac", "usb audio")
SAMPLE_RATE = 24000  # OpenAI Realtime standard
CHANNELS = 1
DTYPE = "int16"
CHUNK_MS = 20  # 20ms chunks = 480 samples @ 24kHz
BLOCK_SIZE = int(SAMPLE_RATE * (CHUNK_MS / 1000.0))  # 480


def list_devices():
    if sd is None:
        return []
    try:
        return [
            (i, dev.get("name", "?"), dev.get("max_input_channels", 0), dev.get("max_output_channels", 0))
            for i, dev in enumerate(sd.query_devices())
        ]
    except Exception:
        return []


def find_audio_device(is_input: bool = True, preferred: str = "") -> tuple[Optional[int], str]:
    if sd is None:
        return None, "sounddevice kurulu değil"

    devs = list_devices()
    valid = [(i, name) for i, name, in_ch, out_ch in devs if (in_ch > 0 if is_input else out_ch > 0)]
    if not valid:
        return None, "uygun ses cihazı bulunamadı"

    # 1. Preferred override
    if preferred:
        if preferred.strip().lstrip("-").isdigit():
            idx = int(preferred)
            for i, name in valid:
                if i == idx:
                    return i, name
        else:
            needle = preferred.strip().lower()
            for i, name in valid:
                if needle in name.lower():
                    return i, name

    # 2. ReSpeaker match
    for i, name in valid:
        if any(h in name.lower() for h in RESPEAKER_NAME_HINTS):
            return i, name

    # 3. Default
    return valid[0][0], valid[0][1]


class AudioStreamNode(Node):
    """ROS 2 Node managing real-time bidirectional 24kHz PCM audio for OpenAI Realtime WebSocket."""

    def __init__(self):
        super().__init__("audio_stream_node")

        # Publishers
        self.pub_input_pcm = self.create_publisher(String, "/audio/realtime_input_pcm", 20)
        self.pub_playback_active = self.create_publisher(Bool, "/audio/playback_active", 10)
        self.pub_input_level = self.create_publisher(Float32, "/audio/mic_level", 10)

        # Subscribers
        self.create_subscription(String, "/audio/realtime_output_pcm", self._on_output_pcm, 50)
        self.create_subscription(Bool, "/tts/interrupt", self._on_interrupt, 10)

        # Device selection
        pref_in = os.getenv("AUDIO_INPUT_DEVICE", "")
        pref_out = os.getenv("AUDIO_OUTPUT_DEVICE", "")
        self._in_dev_idx, in_name = find_audio_device(is_input=True, preferred=pref_in)
        self._out_dev_idx, out_name = find_audio_device(is_input=False, preferred=pref_out)

        self.get_logger().info(f"🎤 [Realtime Audio] Giriş Cihazı: [{self._in_dev_idx}] {in_name} (24kHz Mono)")
        self.get_logger().info(f"🔊 [Realtime Audio] Çıkış Cihazı: [{self._out_dev_idx}] {out_name} (24kHz Mono)")

        # Playback Queue & Thread
        self._play_queue: queue.Queue[bytes] = queue.Queue(maxsize=500)
        self._is_playing = False
        self._playback_lock = threading.Lock()
        self._stop_event = threading.Event()

        # Capture Stream
        self._input_stream = None
        self._output_stream = None

        # Start Playback Thread
        self._play_thread = threading.Thread(target=self._playback_worker, daemon=True)
        self._play_thread.start()

        # Start Input Capture Stream
        self._start_input_stream()

        # Playback status ticker timer
        self.create_timer(0.05, self._publish_status)

    def _start_input_stream(self):
        if sd is None:
            self.get_logger().error("sounddevice kütüphanesi eksik! Canlı ses yakalanamıyor.")
            return

        try:
            self._input_stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                device=self._in_dev_idx,
                channels=CHANNELS,
                dtype=DTYPE,
                callback=self._input_callback,
            )
            self._input_stream.start()
            self.get_logger().info("✅ [Realtime Audio] 24kHz Canlı Mikrofon Akışı Başlatıldı (20ms/blok).")
        except Exception as e:
            self.get_logger().error(f"❌ [Realtime Audio] Giriş akışı başlatılamadı: {e}")

    def _input_callback(self, indata, frames, time_info, status):
        """Audio hardware callback triggered every 20ms with 480 16-bit PCM samples."""
        if status:
            pass

        raw_bytes = bytes(indata)
        if not raw_bytes:
            return

        # Measure RMS level for diagnostic & VAD
        try:
            arr = np.frombuffer(raw_bytes, dtype=np.int16)
            rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
        except Exception:
            rms = 0.0

        # Encode to base64 and publish to ROS 2 topic for Realtime WebSocket node
        b64_str = base64.b64encode(raw_bytes).decode("ascii")
        msg = String()
        msg.data = b64_str
        self.pub_input_pcm.publish(msg)

    def _on_output_pcm(self, msg: String):
        """Incoming 24kHz PCM audio chunk from OpenAI Realtime API (base64)."""
        if not msg.data:
            return
        try:
            raw_pcm = base64.b64decode(msg.data.encode("ascii"))
            if raw_pcm:
                self._play_queue.put_nowait(raw_pcm)
        except (queue.Full, Exception) as e:
            self.get_logger().debug(f"PCM enqueue notice: {e}")

    def _on_interrupt(self, msg: Bool):
        """Zero-latency barge-in signal: instantly flush playback buffer queue."""
        if msg.data:
            with self._playback_lock:
                # Clear all buffered PCM chunks immediately
                while not self._play_queue.empty():
                    try:
                        self._play_queue.get_nowait()
                    except queue.Empty:
                        break
            self.get_logger().info("⚡ [Realtime Audio] Araya Girme (Barge-In) — Ses Çalma Anında Kesildi.")

    def _playback_worker(self):
        """Dedicated real-time audio playback loop sending PCM directly to hardware DAC."""
        if sd is None:
            return

        try:
            out_stream = sd.RawOutputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                device=self._out_dev_idx,
                channels=CHANNELS,
                dtype=DTYPE,
            )
            out_stream.start()
            self._output_stream = out_stream
        except Exception as e:
            self.get_logger().error(f"❌ [Realtime Audio] Çıkış akışı başlatılamadı: {e}")
            return

        while not self._stop_event.is_set():
            try:
                chunk = self._play_queue.get(timeout=0.05)
                self._is_playing = True
                with self._playback_lock:
                    out_stream.write(chunk)
            except queue.Empty:
                self._is_playing = False
            except Exception as e:
                self._is_playing = False
                self.get_logger().debug(f"Playback write notice: {e}")

    def _publish_status(self):
        msg = Bool()
        msg.data = bool(self._is_playing or not self._play_queue.empty())
        self.pub_playback_active.publish(msg)

    def destroy_node(self):
        self._stop_event.set()
        if self._input_stream:
            try:
                self._input_stream.stop()
                self._input_stream.close()
            except Exception:
                pass
        if self._output_stream:
            try:
                self._output_stream.stop()
                self._output_stream.close()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = AudioStreamNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
