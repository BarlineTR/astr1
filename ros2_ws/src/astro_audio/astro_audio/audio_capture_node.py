#!/usr/bin/env python3
"""ASTRO V1 — Audio Capture Node (ReSpeaker 16kHz Mono + Hardware VAD).

Matches TTS/hey_groq_assistant.py hardware capture pipeline:
  - Finds hardware ReSpeaker USB input device directly via sounddevice
  - Records 1-channel (mono) at 16000Hz (ReSpeaker on-board AEC + Beamformed audio)
  - VAD with 500 int16 RMS threshold
  - Publishes to /audio/speech_audio and /audio/vad
"""

import os
import re
import struct
import subprocess
import threading
import time
import numpy as np

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, Int16MultiArray

try:
    import sounddevice as sd
except ImportError:
    sd = None

try:
    import usb.core
    import usb.util
    HAS_USB = True
except ImportError:
    HAS_USB = False

RESPEAKER_VID = 0x2886
RESPEAKER_PID = 0x0018
PARAM_SPEECH_DETECTED = 19
PARAM_DOA_ANGLE = 21


class ReSpeakerHID:
    TIMEOUT_MS = 1000

    def __init__(self):
        self.dev = None
        if not HAS_USB:
            return
        try:
            self.dev = usb.core.find(idVendor=RESPEAKER_VID, idProduct=RESPEAKER_PID)
        except Exception:
            self.dev = None

    def _read_param(self, param_id: int) -> int:
        if self.dev is None:
            return 0
        try:
            data = self.dev.ctrl_transfer(
                usb.util.CTRL_IN | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE,
                0,
                param_id,
                0,
                8,
                self.TIMEOUT_MS,
            )
            return struct.unpack_from("i", data, 0)[0]
        except Exception:
            return 0

    def speech_detected(self) -> bool:
        return self._read_param(PARAM_SPEECH_DETECTED) == 1

    def doa_angle(self) -> float:
        return float(self._read_param(PARAM_DOA_ANGLE))


def find_respeaker_device() -> tuple[int | None, str]:
    """Finds the hardware ReSpeaker device index directly from sounddevice."""
    if sd is None:
        return None, "sounddevice_not_found"

    devices = sd.query_devices()
    respeaker_in = None
    respeaker_name = "default"

    # 1. Look for hardware ReSpeaker / Seeed / UAC directly
    for i, dev in enumerate(devices):
        name = dev.get("name", "").lower()
        if any(k in name for k in ["respeaker", "uac1", "seeed", "arrayuac"]):
            if dev.get("max_input_channels", 0) > 0:
                respeaker_in = i
                respeaker_name = dev.get("name", "")
                break

    # 2. Fallback to default system input if not found
    if respeaker_in is None:
        try:
            default_in = sd.default.device[0]
            if default_in >= 0:
                respeaker_in = default_in
                respeaker_name = devices[default_in].get("name", "default")
        except Exception:
            pass

    return respeaker_in, respeaker_name


class AudioCaptureNode(Node):
    def __init__(self):
        super().__init__("audio_capture_node")

        self.declare_parameter("sample_rate", 16000)
        self.declare_parameter("chunk_size", 960)  # 60ms chunk (0.06s * 16000 = 960)
        self.declare_parameter("vad_threshold", 550.0)

        self.sample_rate = int(self.get_parameter("sample_rate").value)
        self.chunk_size = int(self.get_parameter("chunk_size").value)
        self.vad_threshold = float(self.get_parameter("vad_threshold").value)

        # Publishers
        self.pub_raw = self.create_publisher(Int16MultiArray, "audio_raw", 10)
        self.pub_speech = self.create_publisher(Int16MultiArray, "/audio/speech_audio", 10)
        self.pub_vad = self.create_publisher(Bool, "/audio/vad", 10)
        self.pub_doa = self.create_publisher(Float32, "audio/doa", 10)

        self.respeaker = ReSpeakerHID()
        self._audio_lock = threading.Lock()
        self._pending = None
        self._noise_floor = 150.0

        # Find Hardware Device
        dev_id, dev_name = find_respeaker_device()
        self.get_logger().info(f"🎤 [Audio Capture] Cihaz: [{dev_id}] - {dev_name} (Mono 16kHz)")

        self.stream = None
        if sd is not None and dev_id is not None:
            try:
                self.stream = sd.InputStream(
                    device=dev_id,
                    channels=1,  # 1-channel mono directly gives clean AEC beamformed audio
                    samplerate=self.sample_rate,
                    blocksize=self.chunk_size,
                    dtype="int16",
                    callback=self._audio_callback,
                )
                self.stream.start()
                self.get_logger().info(f"✅ [ReSpeaker] Ses akışı başlatıldı! (Cihaz ID: {dev_id})")
            except Exception as e:
                self.get_logger().warn(f"sounddevice mono açamadı ({e}). 2-kanal deneniyor...")
                try:
                    self.stream = sd.InputStream(
                        device=dev_id,
                        channels=2,
                        samplerate=self.sample_rate,
                        blocksize=self.chunk_size,
                        dtype="int16",
                        callback=self._audio_callback,
                    )
                    self.stream.start()
                    self.get_logger().info(f"✅ [ReSpeaker] 2-kanal ses akışı başlatıldı!")
                except Exception as e2:
                    self.get_logger().error(f"❌ [ReSpeaker] Ses girişi açılamadı: {e2}")

        self.create_timer(0.02, self._publish_pending)
        self.create_timer(0.1, self._publish_hid)

    def _audio_callback(self, indata, frames, time_info, status):
        if indata.ndim > 1 and indata.shape[1] > 1:
            mono = indata[:, 0].copy()
        else:
            mono = indata.flatten().copy()

        # Calculate exact int16 RMS (same as hey_groq_assistant.py)
        rms = int(np.sqrt(np.mean(mono.astype(np.float32) ** 2)))

        # Adaptive noise floor tracking
        if rms < self._noise_floor * 2.0:
            self._noise_floor = 0.95 * self._noise_floor + 0.05 * float(rms)

        # Dynamic VAD threshold
        dynamic_thresh = max(self.vad_threshold, self._noise_floor + 200.0)
        is_speech = rms > dynamic_thresh

        with self._audio_lock:
            self._pending = (mono.tolist(), is_speech)

    def _publish_pending(self):
        with self._audio_lock:
            pending = self._pending
            self._pending = None

        if pending is not None:
            mono, vad_active = pending

            vad_msg = Bool()
            vad_msg.data = vad_active
            self.pub_vad.publish(vad_msg)

            speech_msg = Int16MultiArray()
            speech_msg.data = mono
            self.pub_speech.publish(speech_msg)

    def _publish_hid(self):
        if self.respeaker.dev:
            try:
                angle = self.respeaker.doa_angle()
                msg = Float32()
                msg.data = angle
                self.pub_doa.publish(msg)
            except Exception:
                pass

    def destroy_node(self):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = AudioCaptureNode()
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