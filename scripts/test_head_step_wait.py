#!/usr/bin/env python3
"""ASTRO Robot — Kafa 3x10° Döndürme ve 60s Bekleme Doğrulama Aracı.

İşlem Sırası:
  1. Arduino'ya bağlanır ve başlangıç enkoder değerini (ticks) kaydeder.
  2. 1. Adım: +10.0° komutu gönderir (3.5 saniye).
  3. 2. Adım: +20.0° komutu gönderir (3.5 saniye).
  4. 3. Adım: +30.0° komutu gönderir (3.5 saniye).
  5. 60 Saniye Bekleme: Son konumda bekler, canlı ticks ve delta değişimlerini
     saniye saniye ekrana basar. Herhangi bir enkoder değişimi olduğunda terminal bip verir.
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
    print("❌ 'pyserial' kütüphanesi eksik. Yüklemek için: pip install pyserial")
    sys.exit(1)

# Protocol Sabitleri
SOF1 = 0xAA
SOF2 = 0x55

MSG_HEARTBEAT = 0x01
MSG_HEAD_CMD = 0x03
MSG_ENCODER_TICKS = 0x11
MSG_DIAGNOSTICS = 0x12
MSG_HEARTBEAT_ACK = 0x13

FLAG_WATCHDOG_TIMEOUT = 0x01
FLAG_HEAD_STALL = 0x04
FLAG_HEAD_LIMIT = 0x08

TICKS_PER_DEG = 0.288


def crc8(data: bytes) -> int:
    crc = 0x00
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def build_packet(msg_id: int, payload: bytes = b"") -> bytes:
    length = 1 + len(payload)
    body = bytes([length, msg_id]) + payload
    return bytes([SOF1, SOF2]) + body + bytes([crc8(body)])


def find_serial_port() -> str:
    candidates = [
        "/dev/ttyCH341USB0",
        "/dev/astro_arduino",
        "/dev/ttyUSB0",
        "/dev/ttyUSB1",
        "/dev/ttyACM0",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    matches = glob.glob("/dev/ttyCH341*") + glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    return matches[0] if matches else "/dev/ttyCH341USB0"


class AstroHeadStepTester:
    def __init__(self, port: str = None, baud: int = 115200):
        self.port = port or find_serial_port()
        self.baud = baud
        self.ser = None
        self.running = True
        self.arduino_alive = False
        self.hb_seq = 0
        self.tx_lock = threading.Lock()

        # Telemetri
        self.head_ticks = 0
        self.start_ticks = None
        self.last_ticks = None
        self.change_count = 0
        self.diag_flags = 0
        self.vbat_mv = 0
        self.mcu_temp = 0.0
        self.active_cmd_deg = 0.0

    def connect(self) -> bool:
        print(f"🔌 Arduino'ya bağlanılıyor: {self.port} @ {self.baud} baud...")
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.05)
            time.sleep(2.0)  # Bootloader bekle
            self.ser.reset_input_buffer()

            self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
            self.rx_thread.start()
            self.hb_thread = threading.Thread(target=self._hb_loop, daemon=True)
            self.hb_thread.start()

            for _ in range(30):
                if self.arduino_alive and self.start_ticks is not None:
                    print(f"✅ Arduino Bağlandı! Başlangıç Ticks: {self.start_ticks}")
                    return True
                time.sleep(0.1)
            print("❌ Arduino Heartbeat veya Enkoder yanıtı zaman aşımına uğradı.")
            return False
        except Exception as exc:
            print(f"❌ Seri port bağlantı hatası: {exc}")
            return False

    def _hb_loop(self):
        while self.running and self.ser and self.ser.is_open:
            self.hb_seq = (self.hb_seq + 1) & 0xFFFFFFFF
            pkt = build_packet(MSG_HEARTBEAT, struct.pack("<I", self.hb_seq))
            with self.tx_lock:
                try:
                    self.ser.write(pkt)
                except Exception:
                    pass
            time.sleep(0.05)

    def _rx_loop(self):
        buf = bytearray()
        while self.running and self.ser and self.ser.is_open:
            try:
                waiting = self.ser.in_waiting or 1
                chunk = self.ser.read(waiting)
                if not chunk:
                    continue
                buf.extend(chunk)

                while len(buf) >= 4:
                    if buf[0] != SOF1:
                        del buf[0]
                        continue
                    if buf[1] != SOF2:
                        del buf[0]
                        continue
                    length = buf[2]
                    pkt_end = 3 + length
                    if len(buf) <= pkt_end:
                        break
                    body = buf[2:pkt_end]
                    expected_crc = buf[pkt_end]
                    if crc8(body) != expected_crc:
                        del buf[0]
                        continue
                    msg_id = buf[3]
                    payload = bytes(buf[4:pkt_end])
                    del buf[: pkt_end + 1]

                    if msg_id == MSG_HEARTBEAT_ACK:
                        self.arduino_alive = True
                    elif msg_id == MSG_ENCODER_TICKS and len(payload) >= 12:
                        _, _, ht = struct.unpack("<iii", payload[:12])
                        self.head_ticks = ht
                        if self.start_ticks is None:
                            self.start_ticks = ht
                            self.last_ticks = ht
                        elif ht != self.last_ticks:
                            self.change_count += 1
                            sys.stdout.write("\a")
                            delta_all = ht - self.start_ticks
                            print(
                                f"\n⚡ [DEĞİŞİM #{self.change_count:02d}] "
                                f"Ticks: {ht} | Adım Farkı: {ht - self.last_ticks:+d} | "
                                f"Toplam Delta: {delta_all:+d} ({delta_all / TICKS_PER_DEG:+.1f}°)"
                            )
                            self.last_ticks = ht
                    elif msg_id == MSG_DIAGNOSTICS and len(payload) >= 8:
                        vbat, temp, flags = struct.unpack("<HhI", payload[:8])
                        self.vbat_mv = vbat
                        self.mcu_temp = temp / 100.0
                        self.diag_flags = flags
            except Exception:
                break

    def send_head_cmd(self, angle_deg: float):
        self.active_cmd_deg = angle_deg
        pkt = build_packet(MSG_HEAD_CMD, struct.pack("<f", float(angle_deg)))
        with self.tx_lock:
            try:
                self.ser.write(pkt)
            except Exception:
                pass

    def run_step(self, step_idx: int, target_angle: float, duration_s: float = 3.5):
        print(f"\n" + "=" * 65)
        print(f"▶ ADIM {step_idx}/3: Hedef Kafa Açısı = {target_angle:+.1f}° (Süre: {duration_s}s)")
        print("=" * 65)
        t0 = time.monotonic()
        while time.monotonic() - t0 < duration_s:
            self.send_head_cmd(target_angle)
            cur = self.head_ticks
            delta = cur - (self.start_ticks or 0)
            deg = delta / TICKS_PER_DEG
            stall = bool(self.diag_flags & FLAG_HEAD_STALL)
            status = "STALL (DURDU)" if stall else "DÖNÜŞTE"
            sys.stdout.write(
                f"\r  Komut: {target_angle:+5.1f}° | Ticks: {cur:5d} | "
                f"Delta: {delta:+4d} ({deg:+5.1f}°) | Değişim: {self.change_count:2d} | Durum: {status}    "
            )
            sys.stdout.flush()
            time.sleep(0.08)
        print()

    def run_wait(self, duration_s: float = 60.0):
        print(f"\n" + "=" * 65)
        print(f"⏳ 60 SANİYE BEKLEME BAŞLADI (Son konum korunuyor, telemetri izleniyor)")
        print(f"📌 Bu sırada kabloları kontrol edebilir veya ekrandaki ticks değişimini izleyebilirsiniz.")
        print("=" * 65)
        t0 = time.monotonic()
        while time.monotonic() - t0 < duration_s:
            rem = int(duration_s - (time.monotonic() - t0))
            # Komut tutulur
            self.send_head_cmd(self.active_cmd_deg)
            cur = self.head_ticks
            delta = cur - (self.start_ticks or 0)
            deg = delta / TICKS_PER_DEG
            sys.stdout.write(
                f"\r⏱️ Kalan: {rem:2d}s | Ticks: {cur:5d} | "
                f"Delta: {delta:+4d} ({deg:+5.1f}°) | Toplam Değişim: {self.change_count:2d} | Ticks: {'CANLI' if self.change_count > 0 else 'SABİT 1'}    "
            )
            sys.stdout.flush()
            time.sleep(0.1)
        print("\n\n✅ 60 saniyelik bekleme süresi tamamlandı.")

    def close(self):
        self.running = False
        if self.ser:
            self.send_head_cmd(0.0)
            time.sleep(0.1)
            self.ser.close()


def main():
    parser = argparse.ArgumentParser(description="ASTRO Kafa 3x10° Döndürme ve 60s Bekleme Testi")
    parser.add_argument("--port", default=None, help="Seri port")
    parser.add_argument("--baud", type=int, default=115200, help="Baud hızı")
    args = parser.parse_args()

    tester = AstroHeadStepTester(port=args.port, baud=args.baud)
    if not tester.connect():
        sys.exit(1)

    try:
        # 3 kez 10'ar derece dönme
        tester.run_step(1, 10.0, duration_s=3.5)
        time.sleep(0.5)
        tester.run_step(2, 20.0, duration_s=3.5)
        time.sleep(0.5)
        tester.run_step(3, 30.0, duration_s=3.5)
        time.sleep(0.5)

        # 60 saniye bekleme
        tester.run_wait(60.0)

        # Özet
        final_delta = tester.head_ticks - (tester.start_ticks or 0)
        print("\n" + "=" * 65)
        print("📊 TEST SONUÇ RAPORU:")
        print(f"  • Başlangıç Ticks : {tester.start_ticks}")
        print(f"  • Bitiş Ticks     : {tester.head_ticks}")
        print(f"  • Toplam Değişim  : {tester.change_count} kez pulse yakalandı")
        print(f"  • Net Açısal Fark : {final_delta} ticks ({final_delta / TICKS_PER_DEG:+.1f}°)")
        if tester.change_count > 0:
            print("  🎉 ENKODER ÇALIŞIYOR! Pin 22/23'ten donanımsal darbe başarıyla alındı!")
        else:
            print("  ⚠️ ENKODER DARBESİ GELMEDİ: Ticks değişmedi (Pin 22/23 sinyali 0).")
        print("=" * 65)

    except KeyboardInterrupt:
        print("\n🛑 Kullanıcı tarafından durduruldu.")
    finally:
        tester.close()


if __name__ == "__main__":
    main()
