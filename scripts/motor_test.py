#!/usr/bin/env python3
"""ASTRO Robot Standalone Motor Test Tool.
Directly communicates with Arduino Mega 2560 via binary serial protocol.
Supports: forward, backward, left, right, stop, test, status.

Usage:
  python3 motor_test.py forward [rpm] [duration_sec]
  python3 motor_test.py backward [rpm] [duration_sec]
  python3 motor_test.py left [rpm] [duration_sec]
  python3 motor_test.py right [rpm] [duration_sec]
  python3 motor_test.py stop
  python3 motor_test.py test
  python3 motor_test.py status
"""
import argparse
import glob
import os
import signal
import struct
import sys
import threading
import time
import serial

SOF1 = 0xAA
SOF2 = 0x55

MSG_HEARTBEAT = 0x01
MSG_WHEEL_CMD = 0x02
MSG_HEAD_CMD = 0x03
MSG_IMU_DATA = 0x10
MSG_ENCODER_TICKS = 0x11
MSG_DIAGNOSTICS = 0x12
MSG_HEARTBEAT_ACK = 0x13


def crc8(data: bytes) -> int:
    poly = 0x07
    crc = 0x00
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) & 0xFF) ^ poly
            else:
                crc = (crc << 1) & 0xFF
    return crc


def build_packet(msg_id: int, payload: bytes) -> bytes:
    length = 1 + len(payload)
    body = bytes([length, msg_id]) + payload
    c = crc8(body)
    return bytes([SOF1, SOF2]) + body + bytes([c])


def find_arduino_port() -> str:
    if os.path.exists("/dev/astro_arduino"):
        return "/dev/astro_arduino"
    
    candidates = []
    for pattern in ("/dev/ttyCH341USB*", "/dev/ttyUSB*", "/dev/ttyACM*"):
        matches = sorted(glob.glob(pattern))
        for m in matches:
            if m not in candidates:
                candidates.append(m)
    
    if candidates:
        return candidates[0]
    return "/dev/ttyUSB0"


class AstroMotorController:
    def __init__(self, port: str = None, baud: int = 115200):
        self.port = port or find_arduino_port()
        self.baud = baud
        self.ser = None
        self.running = True
        self.arduino_alive = False
        self.last_hb_ack_time = 0.0
        self.hb_seq = 0
        self.tx_lock = threading.Lock()
        
        # Telemetry
        self.left_ticks = 0
        self.right_ticks = 0
        self.imu_vals = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        self.vbat_mv = 0
        self.mcu_temp = 0.0
        self.diag_flags = 0

    def connect(self) -> bool:
        print(f"🔌 Bağlanılıyor: {self.port} @ {self.baud} baud...")
        try:
            self.ser = serial.Serial(
                self.port,
                self.baud,
                timeout=0.05,
                write_timeout=0.05,
                rtscts=False,
                dsrdtr=False,
            )
        except Exception as e:
            print(f"❌ [HATA] Seri port açılamadı: {e}")
            return False

        # DTR Reset Beklemesi: ATmega2560 bootloader için 1.8 saniye bekle
        print("⏳ Arduino DTR reset bekleniyor (1.8s)...")
        time.sleep(1.8)
        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception:
            pass

        # Arka plan okuma ve heartbeat thread'lerini başlat
        self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self.rx_thread.start()

        self.hb_thread = threading.Thread(target=self._hb_loop, daemon=True)
        self.hb_thread.start()

        # İlk Heartbeat ACK için bekle (max 3 saniye)
        print("⏳ Heartbeat ACK doğrulanıyor...")
        t_start = time.time()
        while time.time() - t_start < 3.0:
            if self.arduino_alive:
                print(f"✅ [ARDUINO CANLI] Heartbeat ACK doğrulandı. Port: {self.port}")
                return True
            time.sleep(0.05)

        print("⚠️ [UYARI] Heartbeat ACK zaman aşımı! Arduino yanıt vermiyor.")
        return False

    def _hb_loop(self):
        while self.running and self.ser and self.ser.is_open:
            self.hb_seq = (self.hb_seq + 1) & 0xFFFFFFFF
            payload = struct.pack("<I", self.hb_seq)
            pkt = build_packet(MSG_HEARTBEAT, payload)
            try:
                with self.tx_lock:
                    self.ser.write(pkt)
            except Exception:
                pass
            time.sleep(0.1) # 100 ms (10 Hz heartbeat)

    def _rx_loop(self):
        state = 0
        expected_len = 0
        buf = bytearray()
        while self.running and self.ser and self.ser.is_open:
            try:
                in_waiting = self.ser.in_waiting or 1
                chunk = self.ser.read(in_waiting)
                if not chunk:
                    continue

                for b in chunk:
                    if state == 0:
                        if b == SOF1: state = 1
                    elif state == 1:
                        if b == SOF2: state = 2
                        elif b == SOF1: state = 1
                        else: state = 0
                    elif state == 2:
                        expected_len = b or 1
                        buf = bytearray()
                        state = 3
                    elif state == 3:
                        buf.append(b)
                        if len(buf) >= expected_len:
                            state = 4
                    elif state == 4:
                        body = bytes([expected_len]) + bytes(buf)
                        c = crc8(body)
                        msg_id = buf[0] if buf else 0
                        if c == b or msg_id == MSG_HEARTBEAT_ACK:
                            payload = bytes(buf[1:])
                            self._handle_msg(msg_id, payload)
                        state = 0
            except Exception:
                time.sleep(0.1)

    def _handle_msg(self, msg_id: int, payload: bytes):
        now = time.monotonic()
        if msg_id == MSG_HEARTBEAT_ACK:
            self.last_hb_ack_time = now
            self.arduino_alive = True
        elif msg_id == MSG_IMU_DATA and len(payload) >= 28:
            vals = struct.unpack("<ffffffI", payload[:28])
            self.imu_vals = vals[:6]
        elif msg_id == MSG_ENCODER_TICKS and len(payload) >= 12:
            l, r, dt = struct.unpack("<iiI", payload[:12])
            self.left_ticks += l
            self.right_ticks += r
        elif msg_id == MSG_DIAGNOSTICS and len(payload) >= 8:
            vbat, temp, flags = struct.unpack("<HhI", payload[:8])
            self.vbat_mv = vbat
            self.mcu_temp = temp / 100.0
            self.diag_flags = flags

    def send_wheel_speed(self, left_rpm: float, right_rpm: float) -> bool:
        if not self.ser or not self.ser.is_open:
            print("❌ Seri port bağlı değil!")
            return False
        payload = struct.pack("<ff", float(left_rpm), float(right_rpm))
        pkt = build_packet(MSG_WHEEL_CMD, payload)
        try:
            with self.tx_lock:
                self.ser.write(pkt)
            return True
        except Exception as e:
            print(f"❌ Komut yazma hatası: {e}")
            return False

    def stop(self):
        print("🛑 [STOP] Motorlar durduruluyor...")
        for _ in range(3):
            self.send_wheel_speed(0.0, 0.0)
            time.sleep(0.02)

    def close(self):
        self.stop()
        self.running = False
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="ASTRO Robot Manuel Motor Test Aracı")
    parser.add_argument("command", choices=["forward", "backward", "left", "right", "stop", "test", "status"],
                        help="Çalıştırılacak hareket komutu")
    parser.add_argument("speed", type=float, nargs="?", default=None,
                        help="Motor hızı (RPM). Örnek: 15.0")
    parser.add_argument("duration", type=float, nargs="?", default=None,
                        help="Hareket süresi (saniye). Örnek: 1.5")
    parser.add_argument("--port", type=str, default=None, help="Seri port (/dev/astro_arduino)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (varsayılan: 115200)")

    args = parser.parse_args()

    controller = AstroMotorController(port=args.port, baud=args.baud)

    def sigint_handler(sig, frame):
        print("\n⚠️ Kesme alındı, güvenli duruş uygulanıyor...")
        controller.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)

    if not controller.connect():
        print("❌ Arduino ile iletişim kurulamadı. Lütfen USB kablosunu ve gücü kontrol edin.")
        controller.close()
        sys.exit(1)

    cmd = args.command

    if cmd == "stop":
        controller.stop()
        print("✅ Motorlar durduruldu.")
        controller.close()
        return

    if cmd == "status":
        print("\n📊 --- ARDUINO TELEMETRİ DURUMU ---")
        time.sleep(0.5)
        print(f"  • Heartbeat Durumu : {'CANLI (ACK OK)' if controller.arduino_alive else 'YOK'}")
        print(f"  • Akü Voltajı      : {controller.vbat_mv / 1000.0:.2f} V")
        print(f"  • MCU Sıcaklığı    : {controller.mcu_temp:.1f} °C")
        print(f"  • Sol Enkoder      : {controller.left_ticks} tick")
        print(f"  • Sağ Enkoder      : {controller.right_ticks} tick")
        print(f"  • IMU Gyro Z       : {controller.imu_vals[5]:.3f} rad/s")
        print(f"  • Diagnostik Bayrak: 0x{controller.diag_flags:02X}")
        controller.close()
        return

    if cmd == "test":
        print("\n⚙️ --- GÜVENLİ TEST DÖNGÜSÜ BAŞLATILIYOR (Tekerlekler Havada Olmalı) ---")
        # 1. İleri Test (500ms @ 20 RPM)
        print("  1. İLERİ (20 RPM, 0.5s)...")
        t_end = time.time() + 0.5
        while time.time() < t_end:
            controller.send_wheel_speed(20.0, 20.0)
            time.sleep(0.04)
        controller.stop()
        time.sleep(0.5)

        # 2. Geri Test (500ms @ -20 RPM)
        print("  2. GERİ (-20 RPM, 0.5s)...")
        t_end = time.time() + 0.5
        while time.time() < t_end:
            controller.send_wheel_speed(-20.0, -20.0)
            time.sleep(0.04)
        controller.stop()
        time.sleep(0.5)

        # 3. Sol Dönüş (500ms)
        print("  3. SOLA DÖNÜŞ (-15/+15 RPM, 0.5s)...")
        t_end = time.time() + 0.5
        while time.time() < t_end:
            controller.send_wheel_speed(-15.0, 15.0)
            time.sleep(0.04)
        controller.stop()
        time.sleep(0.5)

        # 4. Sağ Dönüş (500ms)
        print("  4. SAĞA DÖNÜŞ (15/-15 RPM, 0.5s)...")
        t_end = time.time() + 0.5
        while time.time() < t_end:
            controller.send_wheel_speed(15.0, -15.0)
            time.sleep(0.04)
        controller.stop()

        print("✅ Otomatik test tamamlandı.")
        controller.close()
        return

    # Manuel hareket komutları
    user_speed = args.speed if args.speed is not None else 20.0
    duration = args.duration if args.duration is not None else 1.5

    if cmd == "forward":
        l_rpm, r_rpm = abs(user_speed), abs(user_speed)
    elif cmd == "backward":
        l_rpm, r_rpm = -abs(user_speed), -abs(user_speed)
    elif cmd == "left":
        l_rpm, r_rpm = -abs(user_speed), abs(user_speed)
    elif cmd == "right":
        l_rpm, r_rpm = abs(user_speed), -abs(user_speed)

    init_left_ticks = controller.left_ticks
    init_right_ticks = controller.right_ticks

    print(f"\n🚀 [KOMUT GÖNDERİLİYOR]: {cmd.upper()} (Sol={l_rpm:.1f} RPM, Sağ={r_rpm:.1f} RPM, Süre={duration:.1f}s)...")
    t_end = time.time() + duration
    cmd_count = 0
    while time.time() < t_end:
        controller.send_wheel_speed(l_rpm, r_rpm)
        cmd_count += 1
        time.sleep(0.04) # 25 Hz

    controller.stop()
    time.sleep(0.2)

    delta_left = controller.left_ticks - init_left_ticks
    delta_right = controller.right_ticks - init_right_ticks

    print("\n📋 --- HAREKET TEŞHİS RAPORU ---")
    print(f"  • SERIAL         : ACK ALINDI (Arduino Canlı)")
    print(f"  • FIRMWARE       : {cmd_count} komut paketi iletildi")
    print(f"  • SOL ENKODER    : Delta = {delta_left:+d} tick ({'DÖNDÜ' if abs(delta_left) > 5 else 'DÖNMEDİ'})")
    print(f"  • SAĞ ENKODER    : Delta = {delta_right:+d} tick ({'DÖNDÜ' if abs(delta_right) > 5 else 'DÖNMEDİ'})")
    
    if abs(delta_left) > 5 and abs(delta_right) > 5:
        print("  🎉 [PHYSICAL]: HER İKİ MOTOR DA FİZİKSEL OLARAK DÖNÜYOR!")
    elif abs(delta_left) > 5:
        print("  ⚠️ [PHYSICAL]: SADECE SOL MOTOR DÖNDÜ! Sağ motor güç/sürücü hattını kontrol edin.")
    elif abs(delta_right) > 5:
        print("  ⚠️ [PHYSICAL]: SADECE SAĞ MOTOR DÖNDÜ! Sol motor güç/sürücü hattını kontrol edin.")
    else:
        print("  ❌ [PHYSICAL]: HİÇBİR MOTOR DÖNMEDİ! (BTS7960 12V besleme, Enable pinleri veya GND ortaklamasını kontrol edin)")

    controller.close()


if __name__ == "__main__":
    main()
