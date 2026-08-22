#!/usr/bin/env python3
"""ASTRO Robot — Bağımsız & Güvenli Tekerlek Test Aracı (Standalone Wheel Tester).

Bu script ROS 2, AI veya kamera sistemlerini başlatmadan DOĞRUDAN Arduino ile
güvenli bir şekilde haberleşir ve tekerlek motorlarını kontrollü şekilde test etmenizi sağlar.

Kullanım:
  1) İnteraktif Menü:
     python3 scripts/test_wheels.py

  2) Tek Seferlik Komut (Örn: 20 RPM ile 1.0 saniye ileri):
     python3 scripts/test_wheels.py --left 20 --right 20 --duration 1.0

  3) Acil Durdurma:
     python3 scripts/test_wheels.py --stop
"""

import argparse
import glob
import os
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

PORT_FALLBACKS = (
    "/dev/astro_arduino",
    "/dev/ttyACM0",
    "/dev/ttyACM1",
    "/dev/ttyUSB0",
    "/dev/ttyUSB1",
    "/dev/ttyCH341USB0",
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

    # Glob search
    for pattern in ("/dev/astro_*", "/dev/ttyACM*", "/dev/ttyUSB*"):
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]

    # Windows COM ports fallback
    if sys.platform.startswith("win"):
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        if ports:
            return ports[0].device

    return None


class SafeWheelTester:
    def __init__(self, port=None, baud=500000):
        self.port = find_serial_port(port)
        self.baud = baud
        self.ser = None
        self.running = True
        self._lock = threading.Lock()

        if not self.port:
            raise RuntimeError(
                "❌ Arduino seri portu bulunamadı! USB kablosunun takılı olduğundan emin olun."
            )

        print(f"🔌 Bağlanılıyor: {self.port} @ {self.baud} baud...")
        try:
            self.ser = serial.Serial(
                self.port,
                self.baud,
                timeout=0.1,
                write_timeout=0.2,
                rtscts=False,
                dsrdtr=False,
            )
        except Exception as e:
            raise RuntimeError(f"❌ Port açılamadı ({self.port}): {e}")

        # Start background heartbeat thread (Arduino watchdog requires heartbeat every <1s)
        self.hb_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
        self.hb_thread.start()
        time.sleep(0.5)
        print("✅ Arduino bağlantısı kuruldu ve kalp atışı (heartbeat) aktif.")

    def _heartbeat_worker(self):
        hb_pkt = build_packet(MSG_HEARTBEAT, b"")
        while self.running:
            with self._lock:
                if self.ser and self.ser.is_open:
                    try:
                        self.ser.write(hb_pkt)
                    except Exception:
                        pass
            time.sleep(0.08)  # ~12.5 Hz

    def send_wheel_speed(self, left_rpm: float, right_rpm: float):
        payload = struct.pack("<ff", float(left_rpm), float(right_rpm))
        pkt = build_packet(MSG_WHEEL_CMD, payload)
        with self._lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.write(pkt)
                except Exception as e:
                    print(f"⚠️ Paket gönderme hatası: {e}")

    def stop(self):
        """Tekerlekleri anında durdurur (0 RPM)."""
        for _ in range(3):
            self.send_wheel_speed(0.0, 0.0)
            time.sleep(0.02)
        print("🛑 Motorlar durduruldu (0 RPM).")

    def run_timed_test(self, left_rpm: float, right_rpm: float, duration_sec: float):
        """Belirtilen süre boyunca motorları çalıştırır ve süre dolunca OTOMATİK durdurur."""
        print(
            f"🚀 [Hareket Başlıyor] Sol: {left_rpm:.1f} RPM | Sağ: {right_rpm:.1f} RPM | Süre: {duration_sec:.1f} sn"
        )
        start_time = time.time()
        try:
            while time.time() - start_time < duration_sec:
                self.send_wheel_speed(left_rpm, right_rpm)
                time.sleep(0.05)
        except KeyboardInterrupt:
            print("\n⚠️ Kullanıcı tarafından kesildi!")
        finally:
            self.stop()

    def close(self):
        self.stop()
        self.running = False
        time.sleep(0.1)
        if self.ser and self.ser.is_open:
            self.ser.close()
        print("🔌 Bağlantı kapatıldı.")


def print_menu():
    print("\n" + "=" * 50)
    print(" 🤖 ASTRO ROBOT — GÜVENLİ TEKERLEK TEST PANELİ")
    print("=" * 50)
    print(" [1] ⬆️  İLERİ Testi      (20 RPM, 1.0 saniye)")
    print(" [2] ⬇️  GERİ Testi       (-20 RPM, 1.0 saniye)")
    print(" [3] 🔄 Sola Dönme       (Sol: -20, Sağ: +20 RPM, 1.0 sn)")
    print(" [4] 🔄 Sağa Dönme       (Sol: +20, Sağ: -20 RPM, 1.0 sn)")
    print(" [5] 🟡 Yalnız Sol Teker (20 RPM, 1.0 sn)")
    print(" [6] 🟢 Yalnız Sağ Teker (20 RPM, 1.0 sn)")
    print(" [7] ⚙️  Özel Değer Gir   (Sol RPM, Sağ RPM, Süre)")
    print(" [0] 🛑 ACİL DURDUR     (0 RPM)")
    print(" [Q] ❌ Çıkış")
    print("=" * 50)


def interactive_mode(tester: SafeWheelTester):
    while True:
        print_menu()
        try:
            choice = input("Seçiminiz [0-7, Q]: ").strip().upper()
        except (KeyboardInterrupt, EOFError):
            break

        if choice == "1":
            tester.run_timed_test(20.0, 20.0, 1.0)
        elif choice == "2":
            tester.run_timed_test(-20.0, -20.0, 1.0)
        elif choice == "3":
            tester.run_timed_test(-20.0, 20.0, 1.0)
        elif choice == "4":
            tester.run_timed_test(20.0, -20.0, 1.0)
        elif choice == "5":
            tester.run_timed_test(20.0, 0.0, 1.0)
        elif choice == "6":
            tester.run_timed_test(0.0, 20.0, 1.0)
        elif choice == "7":
            try:
                l = float(input("Sol Tekerlek RPM (-100 ile +100 arası): ") or "0")
                r = float(input("Sağ Tekerlek RPM (-100 ile +100 arası): ") or "0")
                d = float(input("Çalışma Süresi (saniye, örn 1.0): ") or "1.0")
                tester.run_timed_test(l, r, d)
            except ValueError:
                print("❌ Geçersiz sayı girdiniz!")
        elif choice == "0":
            tester.stop()
        elif choice in ("Q", "QUIT", "EXIT"):
            break
        else:
            print("❌ Geçersiz seçim!")


def main():
    parser = argparse.ArgumentParser(description="ASTRO Bağımsız Tekerlek Test Aracı")
    parser.add_argument("--port", type=str, default=None, help="Arduino seri portu (örn /dev/ttyACM0)")
    parser.add_argument("--baud", type=int, default=500000, help="Baud rate (varsayılan 500000)")
    parser.add_argument("--left", type=float, default=None, help="Sol tekerlek RPM değeri")
    parser.add_argument("--right", type=float, default=None, help="Sağ tekerlek RPM değeri")
    parser.add_argument("--duration", type=float, default=1.0, help="Çalışma süresi (sn, varsayılan 1.0)")
    parser.add_argument("--stop", action="store_true", help="Motorları anında durdur")

    args = parser.parse_args()

    try:
        tester = SafeWheelTester(port=args.port, baud=args.baud)
    except Exception as e:
        print(f"\n{e}")
        return

    try:
        if args.stop:
            tester.stop()
        elif args.left is not None and args.right is not None:
            tester.run_timed_test(args.left, args.right, args.duration)
        else:
            interactive_mode(tester)
    finally:
        tester.close()


if __name__ == "__main__":
    main()
