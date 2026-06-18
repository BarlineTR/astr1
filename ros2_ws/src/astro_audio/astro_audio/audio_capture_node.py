#!/usr/bin/env python3
import struct

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
    """Read VAD and DOA from ReSpeaker Mic Array HID interface."""

    TIMEOUT_MS = 100000

    def __init__(self):
        self.dev = None
        if not HAS_USB:
            return
        self.dev = usb.core.find(idVendor=RESPEAKER_VID, idProduct=RESPEAKER_PID)
        if self.dev is None:
            return
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except (usb.core.USBError, NotImplementedError):
            pass
        try:
            self.dev.set_configuration()
        except usb.core.USBError:
            pass

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
        except usb.core.USBError:
            return 0

    def speech_detected(self) -> bool:
        return self._read_param(PARAM_SPEECH_DETECTED) == 1

    def doa_angle(self) -> float:
        return float(self._read_param(PARAM_DOA_ANGLE))


class AudioCaptureNode(Node):
    def __init__(self):
        super().__init__("audio_capture_node")
        self.declare_parameter("device_name", "ReSpeaker")
        self.declare_parameter("sample_rate", 16000)
        self.declare_parameter("channels", 6)
        self.declare_parameter("chunk_size", 1024)
        self.declare_parameter("vad_threshold", 0.6)

        self.device_name = self.get_parameter("device_name").value
        self.sample_rate = int(self.get_parameter("sample_rate").value)
        self.channels = int(self.get_parameter("channels").value)
        self.chunk_size = int(self.get_parameter("chunk_size").value)
        self.vad_threshold = float(self.get_parameter("vad_threshold").value)

        self.pub_raw = self.create_publisher(Int16MultiArray, "/audio/raw", 10)
        self.pub_vad = self.create_publisher(Bool, "/audio/vad", 10)
        self.pub_doa = self.create_publisher(Float32, "/audio/doa", 10)
        self.pub_speech = self.create_publisher(
            Int16MultiArray, "/audio/speech_audio", 10
        )

        self.respeaker = ReSpeakerHID()
        if self.respeaker.dev is None:
            self.get_logger().warn(
                "ReSpeaker HID not found — using energy-based VAD fallback"
            )

        self.device_index = self._find_device()
        if sd is None:
            self.get_logger().error("sounddevice not installed")
            return

        self.stream = sd.InputStream(
            device=self.device_index,
            channels=self.channels,
            samplerate=self.sample_rate,
            blocksize=self.chunk_size,
            dtype="int16",
            callback=self._audio_callback,
        )
        self.stream.start()
        self.get_logger().info(
            f"Audio capture started (device={self.device_index}, "
            f"{self.sample_rate} Hz, {self.channels} ch)"
        )

        self.hid_timer = self.create_timer(0.05, self._publish_hid)

    def _find_device(self):
        if sd is None:
            return None
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if self.device_name.lower() in dev["name"].lower():
                return i
        self.get_logger().warn(
            f"Device '{self.device_name}' not found, using default input"
        )
        return None

    def _energy_vad(self, mono: np.ndarray) -> bool:
        rms = np.sqrt(np.mean(mono.astype(np.float32) ** 2))
        normalized = rms / 32768.0
        return normalized > self.vad_threshold

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            self.get_logger().debug(f"Audio status: {status}")

        mono = indata[:, 0].copy()

        raw_msg = Int16MultiArray()
        raw_msg.data = mono.tolist()
        self.pub_raw.publish(raw_msg)

        if self.respeaker.dev is not None:
            vad_active = self.respeaker.speech_detected()
        else:
            vad_active = self._energy_vad(mono)

        vad_msg = Bool()
        vad_msg.data = vad_active
        self.pub_vad.publish(vad_msg)

        if vad_active:
            speech_msg = Int16MultiArray()
            speech_msg.data = mono.tolist()
            self.pub_speech.publish(speech_msg)

    def _publish_hid(self):
        if self.respeaker.dev is None:
            return
        doa_msg = Float32()
        doa_msg.data = self.respeaker.doa_angle()
        self.pub_doa.publish(doa_msg)

    def destroy_node(self):
        if hasattr(self, "stream") and self.stream is not None:
            self.stream.stop()
            self.stream.close()
        super().destroy_node()


def main():
    rclpy.init()
    node = AudioCaptureNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
