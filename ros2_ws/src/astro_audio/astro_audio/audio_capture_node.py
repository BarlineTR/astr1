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
        self.declare_parameter("audio_gain", 3.0)

        self.sample_rate = int(self.get_parameter("sample_rate").value)
        self.channels = int(self.get_parameter("channels").value)
        self.chunk_size = int(self.get_parameter("chunk_size").value)
        self.vad_threshold = float(self.get_parameter("vad_threshold").value)
        self.audio_gain = float(self.get_parameter("audio_gain").value)

        # PulseAudio kaynağını ve ALSA kart adını dinamik olarak bul
        import subprocess
        import os
        import re
        import time

        self.pulse_source = None
        self.alsa_card_name = "ArrayUAC10"

        # 1. PulseAudio kaynaklarını tara (Cihazın sisteme tam oturması için 5 kez dene)
        for attempt in range(5):
            try:
                out = subprocess.check_output(["pactl", "list", "sources", "short"], stderr=subprocess.DEVNULL).decode("utf-8")
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 2:
                        name = parts[1]
                        # ReSpeaker, Array veya UAC içeren ses girişini ara
                        if any(x in name.lower() for x in ["respeaker", "array", "uac"]):
                            # Tercihen multichannel girişi seç
                            if "multichannel" in name.lower():
                                self.pulse_source = name
                                break
                            self.pulse_source = name
                if self.pulse_source:
                    break
            except Exception:
                pass
            time.sleep(0.5)

        if self.pulse_source:
            self.get_logger().info(f"Dinamik algılanan PulseAudio kaynağı: {self.pulse_source}")
            try:
                # PulseAudio varsayılan girişini ReSpeaker olarak ayarla
                subprocess.run(["pactl", "set-default-source", self.pulse_source], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                os.environ["PULSE_SOURCE"] = self.pulse_source
                self.get_logger().info(f"PulseAudio varsayılan kaynağı ReSpeaker olarak ayarlandı.")
            except Exception as e:
                self.get_logger().warn(f"PulseAudio varsayılan kaynağı ayarlanamadı: {e}")
        else:
            self.get_logger().warn("PulseAudio üzerinde ReSpeaker kaynağı bulunamadı, varsayılan sistem girişi kullanılacak.")
            if "PULSE_SOURCE" in os.environ:
                del os.environ["PULSE_SOURCE"]

        # 2. ALSA kartlarını tara (5 kez dene)
        for attempt in range(5):
            try:
                out = subprocess.check_output(["arecord", "-l"], stderr=subprocess.DEVNULL).decode("utf-8")
                found = False
                for line in out.splitlines():
                    # 'respeaker', 'array', 'uac', 'seeed', 'usb audio' gibi her turlu olasi ismi kontrol et
                    if any(x in line.lower() for x in ["respeaker", "array", "uac", "seeed", "usb audio"]):
                        match = re.search(r'card (\d+): ([\w\-]+)', line)
                        if match:
                            self.alsa_card_name = match.group(2)
                            self.get_logger().info(f"✅ [ReSpeaker] ALSA Kartı Bulundu: {self.alsa_card_name} (Kart ID: {match.group(1)})")
                            found = True
                            break
                if found:
                    break
            except Exception:
                pass
            time.sleep(0.5)

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
        self.pub_speech = self.create_publisher(Int16MultiArray, "/audio/speech_audio", 10)
        self.pub_vad = self.create_publisher(Bool, "/audio/vad", 10)
        self.pub_doa = self.create_publisher(Float32, "audio/doa", 10)
        
        self.respeaker = ReSpeakerHID()
        self.speech_detected_status = False
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
                self.get_logger().info("✅ [ReSpeaker] Ses yakalama aktif ve dinliyor! (PulseAudio üzerinden)")
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
            f"sysdefault:CARD={self.alsa_card_name}",
            f"plughw:CARD={self.alsa_card_name},DEV=0",
            f"hw:CARD={self.alsa_card_name},DEV=0",
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
                    
                    self.get_logger().info(f"✅ [ReSpeaker] Ses yakalama aktif ve dinliyor! (arecord {alsa_dev}, {ch} kanal)")
                    
                    # Veri okuma döngüsü
                    while not self._stop_event.is_set():
                        arr = np.frombuffer(data, dtype=np.int16).reshape(-1, ch)
                        mono = arr[:, 0].copy() # 0. kanal her zaman mevcuttur
                        
                        # Uygulamaya dijital kazanc ekleyelim (Vosk'un kelimeleri daha iyi secebilmesi icin)
                        if self.audio_gain != 1.0:
                            mono = np.clip(mono.astype(np.float32) * self.audio_gain, -32768, 32767).astype(np.int16)
                        
                        vad_active = self.speech_detected_status if self.respeaker.dev else self._energy_vad(mono)
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
        
        # Uygulamaya dijital kazanc ekleyelim (Vosk'un kelimeleri daha iyi secebilmesi icin)
        if self.audio_gain != 1.0:
            mono = np.clip(mono.astype(np.float32) * self.audio_gain, -32768, 32767).astype(np.int16)
            
        vad_active = self.speech_detected_status if self.respeaker.dev else self._energy_vad(mono)
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
            
            # Her zaman kesintisiz gonder (Vosk ses kaybini engellemek icin)
            speech_msg = Int16MultiArray()
            speech_msg.data = mono
            self.pub_speech.publish(speech_msg)

    def _energy_vad(self, mono: np.ndarray) -> bool:
        return (float(np.sqrt(np.mean(mono.astype(np.float32) ** 2))) / 32768.0) > self.vad_threshold

    def _publish_hid(self):
        if self.respeaker.dev:
            # USB/HID okumalarını ana iş parçacığı zamanlayıcısında (timer) yapalım
            self.speech_detected_status = bool(self.respeaker.speech_detected())
            
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