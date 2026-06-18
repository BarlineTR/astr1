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
    TIMEOUT_MS = 1000
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
        self.declare_parameter("channels", 6)
        self.declare_parameter("chunk_size", 1024)
        self.declare_parameter("vad_threshold", 0.05)

        self.sample_rate = int(self.get_parameter("sample_rate").value)
        self.channels = int(self.get_parameter("channels").value)
        self.chunk_size = int(self.get_parameter("chunk_size").value)
        self.vad_threshold = float(self.get_parameter("vad_threshold").value)

        # PulseAudio için ReSpeaker kaynak adını çevre değişkeni olarak ayarla
        import os
        self.pulse_source = "alsa_input.usb-SEEED_ReSpeaker_4_Mic_Array__UAC1.0_-00.multichannel-input"
        os.environ["PULSE_SOURCE"] = self.pulse_source

        # Backend seçimleri (1: sounddevice, 2: arecord fallback)
        self.stream_thread = None
        self._stop_event = threading.Event()
        
        # PulseAudio aktif olduğu için sounddevice üzerinde doğrudan 'pulse' veya 'default' arayüzünü seçelim
        self.device_index = None
        if sd is not None:
            devices = sd.query_devices()
            # Önce "pulse" cihazını ara
            for i, dev in enumerate(devices):
                if dev['name'] == 'pulse':
                    self.device_index = i
                    break
            # Bulunamazsa "default" cihazını ara
            if self.device_index is None:
                for i, dev in enumerate(devices):
                    if dev['name'] == 'default':
                        self.device_index = i
                        break
            
            if self.device_index is not None:
                self.get_logger().info(f"sounddevice PulseAudio arayüzü seçildi. İndeks: {self.device_index} - {devices[self.device_index]['name']}")
            else:
                self.get_logger().warn("sounddevice default/pulse cihazını bulamadı. Fallback yöntemine geçilecek.")

        self.pub_raw = self.create_publisher(Int16MultiArray, "audio_raw", 10)
        self.pub_vad = self.create_publisher(Bool, "audio/vad", 10)
        self.pub_doa = self.create_publisher(Float32, "audio/doa", 10)
        
        self.respeaker = ReSpeakerHID()
        self._audio_lock = threading.Lock()
        self._pending = None
        self.stream = None

        sd_success = False
        if sd is not None and self.device_index is not None:
            try:
                # Pulse üzerinden 6 kanal okuma (ReSpeaker 4-Mic Array için)
                self.stream = sd.InputStream(
                    device=self.device_index,
                    channels=self.channels,
                    samplerate=self.sample_rate,
                    blocksize=2048,
                    dtype="int16",
                    callback=self._audio_callback,
                )
                self.stream.start()
                sd_success = True
                self.get_logger().info("Audio capture (sounddevice PulseAudio) başarıyla başlatıldı.")
            except Exception as exc:
                self.get_logger().error(f"sounddevice stream açılamadı: {exc}")

        # Eğer sounddevice başarısız olursa arecord ile Pulse veya ALSA üzerinden bağlanmayı dene
        if not sd_success:
            self.get_logger().warn("sounddevice başlatılamadı. arecord fallback moduna geçiliyor...")
            self.stream_thread = threading.Thread(target=self._arecord_capture_loop, daemon=True)
            self.stream_thread.start()

        self.create_timer(0.02, self._publish_pending)
        self.create_timer(0.05, self._publish_hid)

    def _arecord_capture_loop(self):
        import subprocess
        import os
        
        # Arecord ile denenecek cihaz konfigürasyonları sırasıyla:
        # 1. PulseAudio (PULSE_SOURCE ile yönlendirilmiş)
        # 2. ALSA sysdefault (ArrayUAC10 kartına özel)
        # 3. ALSA plughw (ArrayUAC10 kartına özel)
        # 4. ALSA hw (ArrayUAC10 kartına özel)
        # 5. default
        alsa_devs = [
            "pulse",
            "sysdefault:CARD=ArrayUAC10",
            "plughw:CARD=ArrayUAC10,DEV=0",
            "hw:CARD=ArrayUAC10,DEV=0",
            "default"
        ]
        
        channel_attempts = [6, 4, 2, 1]
        process = None
        
        # Alt süreç için PulseAudio çevre değişkenini içeren ortamı hazırla
        env = os.environ.copy()
        env["PULSE_SOURCE"] = self.pulse_source
        
        for alsa_dev in alsa_devs:
            self.get_logger().info(f"arecord deneniyor. Cihaz: {alsa_dev}")
            for ch in channel_attempts:
                if self._stop_event.is_set():
                    break
                    
                cmd = [
                    'arecord',
                    '-D', alsa_dev,
                    '-f', 'S16_LE',
                    '-r', str(self.sample_rate),
                    '-c', str(ch),
                    '-t', 'raw',
                    '-q'
                ]
                
                try:
                    process = subprocess.Popen(
                        cmd, 
                        stdout=subprocess.PIPE, 
                        stderr=subprocess.PIPE,
                        env=env
                    )
                    self.get_logger().info(f"arecord komutu: {' '.join(cmd)}")
                    
                    chunk_bytes = self.chunk_size * ch * 2 # 16-bit = 2 byte
                    
                    # İlk okuma testi
                    data = process.stdout.read(chunk_bytes)
                    if not data:
                        stdout_val, stderr_val = process.communicate()
                        err_msg = stderr_val.decode('utf-8', errors='ignore').strip()
                        self.get_logger().warn(f"arecord {ch} kanallı okuma yapamadı (Cihaz: {alsa_dev}). Hata: {err_msg}")
                        continue
                    
                    self.get_logger().info(f"arecord başarıyla bağlandı! ({alsa_dev}, {ch} kanal modunda çalışıyor)")
                    
                    # Veri okuma döngüsü
                    while not self._stop_event.is_set():
                        arr = np.frombuffer(data, dtype=np.int16).reshape(-1, ch)
                        mono = arr[:, 0].copy() # 0. kanal her zaman mevcuttur
                        
                        vad_active = bool(self.respeaker.speech_detected()) if self.respeaker.dev else self._energy_vad(mono)
                        with self._audio_lock:
                            self._pending = (mono.tolist(), vad_active)
                            
                        data = process.stdout.read(chunk_bytes)
                        if not data:
                            break
                            
                    break
                    
                except Exception as e:
                    self.get_logger().error(f"arecord başlatma hatası: {e}")
                    if process:
                        process.terminate()
            
            if process and process.poll() is None and not self._stop_event.is_set():
                break
                
        if process:
            try:
                process.terminate()
            except:
                pass

    def _audio_callback(self, indata, frames, time_info, status):
        mono = indata[:, 0].copy()
        vad_active = bool(self.respeaker.speech_detected()) if self.respeaker.dev else self._energy_vad(mono)
        with self._audio_lock:
            self._pending = (mono.tolist(), vad_active)

    def _publish_pending(self):
        with self._audio_lock:
            pending = self._pending
            self._pending = None
        
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
    finally: node.destroy_node(); rclpy.shutdown()

if __name__ == "__main__":
    main()