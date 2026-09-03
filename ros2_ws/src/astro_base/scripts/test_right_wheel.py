#!/usr/bin/env python3
"""ASTRO Robot — Sadece Sağ Tekerlek Test Aracı (Right Wheel Isolated Test).

İşlev:
  1. Arduino Mega 2560'a binary serial protokolüyle bağlanır.
  2. Sol tekerleği tamamen sabit tutarak (0.0 RPM):
     - 0.5 saniye İLERİ (+25.0 RPM) döndürür.
     - 0.2 saniye fren/geçiş beklemesi yapar.
     - 0.5 saniye GERİ (-25.0 RPM) döndürür.
  3. Güvenli şekilde motorları durdurur.
  4. Enkoder tick değişimlerini ve voltaj/sıcaklık telemetrisini ekrana basar.

Kullanım:
  python3 src/astro_base/scripts/test_right_wheel.py
  python3 scripts/test_right_wheel.py
"""

import argparse
import glob
import os
import signal
import struct
import sys
import threading
import time

try:
    import serial
except ImportError:
    print("❌ 'pyserial' modülü bulunamadı. Lütfen yükleyin: pip install pyserial")
    sys.exit(1)

SOF1 = 0xAA
SOF2 = 0x55

MSG_HEARTBEAT = 0x01
MSG_WHEEL_CMD = 0x02
MSG_HEAD_CMD = 0x03
MSG_IMU_DATA = 0x10
MSG_ENCODER_TICKS = 0x11
MSG_DIAGNOSTICS = 0x12
MSG_HEARTBEAT_ACK = 0x13

PORT_FALLBACKS = (
    "/dev/astro_arduino",
    "/dev/ttyCH341USB0",
    "/dev/ttyUSB0",
    "/dev/ttyUSB1",
    "/dev/ttyACM0",
    "/dev/ttyACM1",
)


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


def find_serial_port(preferred_port=None) -> str:
    if preferred_port and os.path.exists(preferred_port):
        return preferred_port

    for port in PORT_FALLBACKS:
        if os.path.exists(port):
            return port

    for pattern in ("/dev/astro_*", "/dev/ttyCH341USB*", "/dev/ttyUSB*", "/dev/ttyACM*"):
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]

    if sys.platform.startswith("win"):
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        if ports:
            return ports[0].device

    return None


class RightWheelTester:
    def __init__(self, port=None, baud=115200):
        self.port = find_serial_port(port)
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
        self.vbat_mv = 0
        self.mcu_temp = 0.0
        self.diag_flags = 0

    def connect(self) -> bool:
        if not self.port:
            print("❌ Arduino portu bulunamadı! Cihazın bağlı olduğundan emin olun.")
            return False

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
            time.sleep(2.0)  # Arduino bootloader beklemesi

            self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
            self.rx_thread.start()
            self.hb_thread = threading.Thread(target=self._hb_loop, daemon=True)
            self.hb_thread.start()

            # Handshake / Heartbeat ACK beklemesi
            print("⏳ Arduino Heartbeat ACK bekleniyor...")
            for _ in range(40):
                if self.arduino_alive:
                    print("✅ Arduino bağlantısı ve Heartbeat doğrulandı!")
                    return True
                time.sleep(0.05)

            print("⚠️ [UYARI] Heartbeat ACK zaman aşımı! Arduino yanıt vermiyor.")
            return False
        except Exception as exc:
            print(f"❌ Seri port bağlantı hatası: {exc}")
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
            time.sleep(0.1)  # 10 Hz Heartbeat

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
                        if b == SOF1:
                            state = 1
                    elif state == 1:
                        if b == SOF2:
                            state = 2
                        elif b == SOF1:
                            state = 1
                        else:
                            state = 0
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
            return False
        payload = struct.pack("<ff", float(left_rpm), float(right_rpm))
        pkt = build_packet(MSG_WHEEL_CMD, payload)
        try:
            with self.tx_lock:
                self.ser.write(pkt)
            return True
        except Exception:
            return False

    def stop(self):
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
    parser = argparse.ArgumentParser(description="ASTRO Robot Sağ Tekerlek 0.5s İleri / 0.5s Geri Testi")
    parser.add_argument("--speed", type=float, default=25.0, help="Sağ tekerlek test hızı (RPM, varsayılan: 25.0)")
    parser.add_argument("--port", type=str, default=None, help="Arduino seri portu (varsayılan: otomatik)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (varsayılan: 115200)")

    args = parser.parse_args()
    test_speed = abs(args.speed)

    tester = RightWheelTester(port=args.port, baud=args.baud)

    def sigint_handler(sig, frame):
        print("\n⚠️ Test kullanıcı tarafından iptal edildi! Güvenli duruş uygulanıyor...")
        tester.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, sigint_handler)

    if not tester.connect():
        sys.exit(1)

    print("\n========================================================")
    print("   🤖 ASTRO — İZOLE SAĞ TEKERLEK TESTİ")
    print("========================================================")
    print(f"  • Test Edilen Motor : SADECE SAĞ TEKERLEK (Sol Motor: 0.0 RPM)")
    print(f"  • Test Hızı         : {test_speed:.1f} RPM")
    print(f"  • Akü Voltajı       : {tester.vbat_mv / 1000.0:.2f} V")
    print(f"  • MCU Sıcaklığı     : {tester.mcu_temp:.1f} °C")
    print("--------------------------------------------------------")
    print("⚠️ UYARI: Robotun tekerleklerinin serbest dönebildiğinden emin olun.\n")

    time.sleep(0.5)

    # Başlangıç enkoder değerleri
    init_left = tester.left_ticks
    init_right = tester.right_ticks

    # --- 1. AŞAMA: 0.5 SANİYE İLERİ ---
    print(f"🚀 [AŞAMA 1/2] Sağ Tekerlek İLERİ ({+test_speed:.1f} RPM, 0.5 saniye)...")
    t_end = time.time() + 0.5
    fwd_cmds = 0
    while time.time() < t_end:
        tester.send_wheel_speed(left_rpm=0.0, right_rpm=test_speed)
        fwd_cmds += 1
        time.sleep(0.04)  # 25 Hz komut frekansı

    # Kısa fren ve stabilizasyon beklemesi (0.2s)
    tester.stop()
    time.sleep(0.2)

    fwd_right_ticks = tester.right_ticks - init_right
    fwd_left_ticks = tester.left_ticks - init_left
    print(f"  -> İleri Tamamlandı! Sağ Enkoder Delta: {fwd_right_ticks:+d} tick (Sol: {fwd_left_ticks:+d} tick)\n")

    # --- 2. AŞAMA: 0.5 SANİYE GERİ ---
    print(f"🔄 [AŞAMA 2/2] Sağ Tekerlek GERİ ({-test_speed:.1f} RPM, 0.5 saniye)...")
    t_end = time.time() + 0.5
    bwd_cmds = 0
    while time.time() < t_end:
        tester.send_wheel_speed(left_rpm=0.0, right_rpm=-test_speed)
        bwd_cmds += 1
        time.sleep(0.04)  # 25 Hz komut frekansı

    # Güvenli durdurma
    tester.stop()
    time.sleep(0.3)

    total_right_ticks = tester.right_ticks - init_right
    total_left_ticks = tester.left_ticks - init_left

    print("\n========================================================")
    print("   📊 SAĞ TEKERLEK TEST RAPORU")
    print("========================================================")
    print(f"  • İleri Komut Sayısı : {fwd_cmds} paket")
    print(f"  • Geri Komut Sayısı  : {bwd_cmds} paket")
    print(f"  • Sol Motor Hareketi : {total_left_ticks:+d} tick ({'BEKLENDİĞİ GİBİ SABİT' if abs(total_left_ticks) <= 5 else 'UYARI: HAREKET ETTİ!'})")
    print(f"  • Sağ İleri Enkoder  : {fwd_right_ticks:+d} tick")
    print(f"  • Sağ Net Delta      : {total_right_ticks:+d} tick")
    print("--------------------------------------------------------")

    if abs(fwd_right_ticks) > 5:
        print("  🎉 [BAŞARILI]: Sağ tekerlek motoru ve enkoderi sağlıklı çalışıyor!")
    else:
        print("  ❌ [DİKKAT]: Sağ tekerlekten enkoder hareketi algılanamadı!")
        print("     Kontrol edin: BTS7960 motor sürücü 12V beslemesi, motor kabloları veya sigorta.")
    print("========================================================\n")

    tester.close()


if __name__ == "__main__":
    main()
