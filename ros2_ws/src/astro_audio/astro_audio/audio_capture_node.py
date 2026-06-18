#!/usr/bin/env python3
import struct
import threading
import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, Float32, Int16MultiArray, MultiArrayDimension

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
    TIMEOUT_MS = 100000
    def __init__(self):
        self.dev = None
        if not HAS_USB: return
        self.dev = usb.core.find(idVendor=RESPEAKER_VID, idProduct=RESPEAKER_PID)
        if self.dev is None: return
        try:
            if self.dev.is_kernel_driver_active(0): self.dev.detach_kernel_driver(0)
        except (usb.core.USBError, NotImplementedError): pass
        try: self.dev.set_configuration()
        except usb.core.USBError: pass

    def _read_param(self, param_id: int) -> int:
        if self.dev is None: return 0
        try:
            data = self.dev.ctrl_transfer(
                usb.util.CTRL_IN | usb.util.CTRL_TYPE_VENDOR | usb.util.CTRL_RECIPIENT_DEVICE,
                0, param_id, 0, 8, self.TIMEOUT_MS
            )
            return struct.unpack_from("i", data, 0)[0]
        except usb.core.USBError: return 0

    def speech_detected(self) -> bool: return self._read_param(PARAM_SPEECH_DETECTED) == 1
    def doa_angle(self) -> float: return float(self._read_param(PARAM_DOA_ANGLE))

class AudioCaptureNode(Node):
    def __init__(self):
        super().__init__("audio_capture_node")
        
        self.declare_parameter("sample_rate", 16000)
        self.declare_parameter("channels", 1)
        self.declare_parameter("chunk_size", 1024)
        self.declare_parameter("vad_threshold", 0.6)

        self.sample_rate = int(self.get_parameter("sample_rate").value)
        self.channels = int(self.get_parameter("channels").value)
        self.chunk_size = int(self.get_parameter("chunk_size").value)
        self.vad_threshold = float(self.get_parameter("vad_threshold").value)
        self.device_index_param = 25 

        # Publisher'lar
        self.pub_raw = self.create_publisher(Int16MultiArray, "audio_raw", 10)
        self.pub_vad = self.create_publisher(Bool, "audio/vad", 10)
        self.pub_doa = self.create_publisher(Float32, "audio/doa", 10)
        
        # Topic'leri ROS 2 tablosuna kaydetmek için ilk boş mesajı gönder
        empty_msg = Int16MultiArray()
        empty_msg.layout.dim.append(MultiArrayDimension(label="audio", size=0, stride=0))
        self.pub_raw.publish(empty_msg)

        self.respeaker = ReSpeakerHID()
        self._audio_lock = threading.Lock()
        self._pending = None
        self.stream = None

        if sd is not None:
            try:
                self.stream = sd.InputStream(
                    device=self.device_index_param,
                    channels=self.channels,
                    samplerate=self.sample_rate,
                    blocksize=self.chunk_size,
                    dtype="int16",
                    callback=self._audio_callback,
                )
                self.stream.start()
                self.get_logger().info(f"Audio capture started (device={self.device_index_param})")
            except Exception as exc:
                self.get_logger().error(f"Stream hatası: {exc}")

        self.create_timer(0.02, self._publish_pending)
        self.create_timer(0.05, self._publish_hid)

    def _audio_callback(self, indata, frames, time_info, status):
        mono = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()
        vad_active = bool(self.respeaker.speech_detected()) if self.respeaker.dev else self._energy_vad(mono)
        with self._audio_lock:
            self._pending = (mono.tolist(), vad_active)

    def _publish_pending(self):
        with self._audio_lock:
            pending = self._pending
        if pending is not None:
            mono, vad_active = pending
            raw_msg = Int16MultiArray()
            raw_msg.data = mono
            self.pub_raw.publish(raw_msg)
            
            vad_msg = Bool()
            vad_msg.data = vad_active
            self.pub_vad.publish(vad_msg)

    def _energy_vad(self, mono: np.ndarray) -> bool:
        return (float(np.sqrt(np.mean(mono.astype(np.float32) ** 2))) / 32768.0) > self.vad_threshold

    def _publish_hid(self):
        if self.respeaker.dev:
            msg = Float32()
            msg.data = self.respeaker.doa_angle()
            self.pub_doa.publish(msg)

    def destroy_node(self):
        if self.stream: self.stream.stop()
        super().destroy_node()

def main():
    rclpy.init()
    node = AudioCaptureNode()
    try: rclpy.spin(node)
    except KeyboardInterrupt: pass
    finally: rclpy.shutdown()

if __name__ == "__main__":
    main()