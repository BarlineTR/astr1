#!/usr/bin/env python3
import struct
import threading

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
        self.declare_parameter("device_index", -1)
        self.declare_parameter("sample_rate", 16000)
        self.declare_parameter("channels", 6)
        self.declare_parameter("chunk_size", 1024)
        self.declare_parameter("vad_threshold", 0.6)

        self.device_name = self.get_parameter("device_name").value
        self.device_index_param = int(self.get_parameter("device_index").value)
        self.sample_rate = int(self.get_parameter("sample_rate").value)
        self.requested_channels = int(self.get_parameter("channels").value)
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

        self._audio_lock = threading.Lock()
        self._pending = None
        self.stream = None

        if sd is None:
            self.get_logger().error("sounddevice not installed — audio disabled")
            return

        device_index, self.channels = self._resolve_device()
        try:
            self.stream = sd.InputStream(
                device=device_index,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.chunk_size,
                dtype="int16",
                callback=self._audio_callback,
            )
            self.stream.start()
            self.get_logger().info(
                f"Audio capture started (device={device_index}, "
                f"{self.sample_rate} Hz, {self.channels} ch)"
            )
        except Exception as exc:
            self.get_logger().error(f"Failed to start audio stream: {exc}")

        self.create_timer(0.02, self._publish_pending)
        self.create_timer(0.05, self._publish_hid)

    def _resolve_device(self):
        if sd is None:
            return None, 1

        if self.device_index_param >= 0:
            dev = sd.query_devices(self.device_index_param)
            channels = min(self.requested_channels, dev["max_input_channels"])
            return self.device_index_param, max(1, channels)

        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] < 1:
                continue
            if self.device_name.lower() in dev["name"].lower():
                channels = min(self.requested_channels, dev["max_input_channels"])
                return i, max(1, channels)

        default_in = sd.default.device[0]
        dev = sd.query_devices(default_in)
        channels = min(self.requested_channels, dev["max_input_channels"])
        self.get_logger().warn(
            f"Device '{self.device_name}' not found, using default input "
            f"({dev['name']}, {channels} ch)"
        )
        return default_in, max(1, channels)

    def _energy_vad(self, mono: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2)))
        return (rms / 32768.0) > self.vad_threshold

    def _audio_callback(self, indata, frames, time_info, status):
        del frames, time_info
        if status:
            self.get_logger().debug(f"Audio status: {status}")

        if indata.ndim == 1:
            mono = indata.copy()
        else:
            mono = indata[:, 0].copy()

        if self.respeaker.dev is not None:
            vad_active = bool(self.respeaker.speech_detected())
        else:
            vad_active = bool(self._energy_vad(mono))

        with self._audio_lock:
            self._pending = (mono.tolist(), vad_active)

    def _publish_pending(self):
        with self._audio_lock:
            pending = self._pending
            self._pending = None

        if pending is None:
            return

        mono, vad_active = pending

        raw_msg = Int16MultiArray()
        raw_msg.data = mono
        self.pub_raw.publish(raw_msg)

        vad_msg = Bool()
        vad_msg.data = vad_active
        self.pub_vad.publish(vad_msg)

        if vad_active:
            speech_msg = Int16MultiArray()
            speech_msg.data = mono
            self.pub_speech.publish(speech_msg)

    def _publish_hid(self):
        if self.respeaker.dev is None:
            return
        doa_msg = Float32()
        doa_msg.data = self.respeaker.doa_angle()
        self.pub_doa.publish(doa_msg)

    def destroy_node(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        super().destroy_node()


def main():
    rclpy.init()
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
