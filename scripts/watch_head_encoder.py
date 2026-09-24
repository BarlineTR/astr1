#!/usr/bin/env python3
"""ASTRO — Süresiz Kafa Enkoderi Canlı İzleme Aracı (Watch Head Encoder).

Terminalde sürekli çalışır, Arduino watchdog'unu besler ve kafa enkoder
değerindeki her değişimi anlık olarak sesli/renkli terminal çıktısıyla gösterir.
Kablo oynatma veya elle döndürme testleri için idealdir.

Kullanım:
    python scripts/watch_head_encoder.py
    python scripts/watch_head_encoder.py --port /dev/ttyCH341USB0
"""

import argparse
import glob
import os
import struct
import sys
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
MSG_ENCODER_TICKS = 0x11  # Arduino Proto::ENCODER_TICKS

# Canonical Head Encoder Resolution: 440 ticks / 170.0 deg = 2.5882 ticks/deg
TICKS_PER_DEG = 2.5882


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


def auto_detect_port() -> str:
    candidates = [
        "/dev/ttyCH341USB0",
        "/dev/astro_arduino",
        "/dev/ttyUSB0",
        "/dev/ttyUSB1",
        "/dev/ttyACM0",
        "/dev/ttyACM1",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # Glob ara
    matches = glob.glob("/dev/ttyCH341*") + glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    if matches:
        return matches[0]
    return "/dev/ttyCH341USB0"


def main():
    parser = argparse.ArgumentParser(description="ASTRO Süresiz Kafa Enkoder İzleyici")
    parser.add_argument("--port", default=None, help="Seri port (varsayılan: otomatik tespit)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud hızı (varsayılan: 115200)")
    args = parser.parse_args()

    port = args.port or auto_detect_port()

    print("\033[1;36m" + "=" * 70)
    print("  ASTRO KAFA ENKODERİ CANLI İZLEME ARACI (SÜRESİZ)")
    print(f"  Port: {port} | Baud: {args.baud}")
    print("=" * 70 + "\033[0m")
    print("📌 Kabloları oynatırken veya kafayı çevirirken ekrandaki değişimi izleyin.")
    print("📌 Ticks değiştiğinde terminal bip sesi verir ve ekrana yeni satır basar.")
    print("Çıkmak için: \033[1;33mCtrl + C\033[0m\n")

    try:
        ser = serial.Serial(port, args.baud, timeout=0.05)
    except Exception as e:
        print(f"\033[1;31m❌ Port açılamadı ({port}): {e}\033[0m")
        sys.exit(1)

    # Arduino DTR reset bekleme süresi
    time.sleep(1.8)
    ser.reset_input_buffer()

    last_hb_time = time.monotonic()
    hb_seq = 0
    start_ticks = None
    last_ticks = None
    change_count = 0
    last_packet_time = time.monotonic()

    # ANSI Renkleri
    GREEN = "\033[1;32m"
    RED = "\033[1;31m"
    YELLOW = "\033[1;33m"
    CYAN = "\033[1;36m"
    RESET = "\033[0m"

    rx_buf = bytearray()

    try:
        while True:
            now = time.monotonic()

            # 1. Watchdog Heartbeat gönder (200ms)
            if now - last_hb_time >= 0.20:
                hb_seq = (hb_seq + 1) & 0xFFFFFFFF
                try:
                    ser.write(build_packet(MSG_HEARTBEAT, struct.pack("<I", hb_seq)))
                except Exception as ex:
                    print(f"\n{RED}❌ TX Hatası: {ex}{RESET}")
                    break
                last_hb_time = now

            # 2. Seri porttan gelen paketleri oku
            waiting = getattr(ser, "in_waiting", 0)
            if waiting:
                rx_buf.extend(ser.read(waiting))

            # Paket çözümleme
            while len(rx_buf) >= 4:
                # SOF ara
                if rx_buf[0] != SOF1:
                    del rx_buf[0]
                    continue
                if rx_buf[1] != SOF2:
                    del rx_buf[0]
                    continue

                length = rx_buf[2]
                pkt_end = 3 + length
                if len(rx_buf) <= pkt_end:
                    break  # Henüz tüm paket gelmedi

                body = rx_buf[2:pkt_end]
                expected_crc = rx_buf[pkt_end]
                if crc8(body) != expected_crc:
                    # CRC hatası
                    del rx_buf[0]
                    continue

                msg_id = rx_buf[3]
                payload = bytes(rx_buf[4:pkt_end])
                del rx_buf[: pkt_end + 1]

                if msg_id == MSG_ENCODER_TICKS and len(payload) >= 12:
                    last_packet_time = now
                    _dl, _dr, head_ticks = struct.unpack("<iii", payload[:12])

                    if start_ticks is None:
                        start_ticks = head_ticks
                        last_ticks = head_ticks
                        print(f"{CYAN}📡 İlk bağlantı kuruldu. Başlangıç Ticks: {start_ticks}{RESET}\n")

                    delta = head_ticks - start_ticks
                    step_delta = head_ticks - last_ticks
                    deg = delta / TICKS_PER_DEG

                    # Değişim var mı kontrol et
                    if step_delta != 0:
                        change_count += 1
                        # Terminal zil sesi (bip) ve yeni satır bas
                        sys.stdout.write("\a")
                        print(
                            f"\n{GREEN}⚡ [DEĞİŞİM #{change_count:03d}] "
                            f"Ham Ticks: {head_ticks:6d} | "
                            f"Fark: {step_delta:+3d} | "
                            f"Toplam Delta: {delta:+6d} ({deg:+6.1f}°) | "
                            f"Zaman: {time.strftime('%H:%M:%S')}{RESET}"
                        )
                        last_ticks = head_ticks

                    # Sürekli durum satırı (aynı satırda yenilenir)
                    status_text = (
                        f"{GREEN}DÖNÜYOR{RESET}"
                        if change_count > 0
                        else f"{YELLOW}BEKLİYOR (Sabit 1){RESET}"
                    )
                    sys.stdout.write(
                        f"\r[CANLI] Ham Ticks: \033[1m{head_ticks:6d}\033[0m | "
                        f"Delta: {delta:+5d} ({deg:+5.1f}°) | "
                        f"Değişim Sayısı: {change_count:3d} | "
                        f"Durum: {status_text}    "
                    )
                    sys.stdout.flush()

            # Bağlantı koptu mu kontrolü (1 saniye paket gelmezse)
            if now - last_packet_time > 1.5 and start_ticks is not None:
                sys.stdout.write(f"\r{RED}⚠️  Arduino'dan paket akışı kesildi!{RESET}          \n")
                last_packet_time = now

            time.sleep(0.01)

    except KeyboardInterrupt:
        print(f"\n\n{CYAN}🛑 İzleme durduruldu. Toplam tespit edilen değişim: {change_count}{RESET}")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
