#!/usr/bin/env python3
"""ASTRO — Standalone Head Encoder & Port Live Tester.

No ROS, no camera, no GUI required.
Connects directly to Arduino Mega, feeds watchdog heartbeat,
and prints raw encoder ticks and calculated angle in real time at 50 Hz.
"""

import glob
import os
import struct
import sys
import time

try:
    import serial
except ImportError:
    print("❌ 'pyserial' kütüphanesi eksik. Yüklemek için: pip3 install pyserial")
    sys.exit(1)

SOF1 = 0xAA
SOF2 = 0x55
MSG_ENCODER_TICKS = 0x02
MSG_HEARTBEAT = 0x01
MSG_HEAD_CMD = 0x03

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

def build_packet(msg_id: int, payload: bytes) -> bytes:
    length = 1 + len(payload)
    body = bytes([length, msg_id]) + payload
    return bytes([SOF1, SOF2]) + body + bytes([crc8(body)])

def find_arduino_port():
    candidates = [
        "/dev/astro_arduino",
        "/dev/ttyCH341USB0",
        "/dev/ttyUSB0",
        "/dev/ttyUSB1",
        "/dev/ttyACM0",
        "/dev/ttyACM1",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # Glob search
    ch341 = glob.glob("/dev/ttyCH341*")
    if ch341:
        return ch341[0]
    usb = glob.glob("/dev/ttyUSB*")
    if usb:
        return usb[0]
    return None

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_arduino_port()
    if not port:
        print("❌ Arduino portu bulunamadı! Lütfen USB kablosunu kontrol edin.")
        sys.exit(1)

    print("=" * 65)
    print(f"  ASTRO KAFA ENKODER CANLI TEST ARACI")
    print(f"  Port: {port} | Baud: 115200")
    print("=" * 65)
    print("Kafayı elinizle çevirin veya kabloları deneyin.")
    print("Durdurmak için Ctrl+C basın.\n")

    try:
        ser = serial.Serial(port, 115200, timeout=0.1)
    except Exception as e:
        print(f"❌ Port açılamadı ({port}): {e}")
        sys.exit(1)

    last_hb = time.monotonic()
    hb_seq = 0
    start_ticks = None

    try:
        while True:
            now = time.monotonic()
            # Send heartbeat every 200ms
            if now - last_hb >= 0.2:
                hb_seq = (hb_seq + 1) & 0xFFFFFFFF
                ser.write(build_packet(MSG_HEARTBEAT, struct.pack("<I", hb_seq)))
                last_hb = now

            # Read packet header
            b = ser.read(1)
            if b == bytes([SOF1]):
                if ser.read(1) == bytes([SOF2]):
                    length = ord(ser.read(1))
                    msg_id = ord(ser.read(1))
                    payload = ser.read(length - 1)
                    _crc = ser.read(1)

                    if msg_id == MSG_ENCODER_TICKS and len(payload) >= 12:
                        _dl, _dr, head_ticks = struct.unpack("<iii", payload[:12])
                        if start_ticks is None:
                            start_ticks = head_ticks

                        delta = head_ticks - start_ticks
                        deg = delta / TICKS_PER_DEG

                        status = "✅ DÖNÜYOR" if abs(delta) > 0 else "⏳ 0 (Sinyal Bekleniyor)"
                        print(
                            f"\r>>> [HAM TICK]: {head_ticks:7d} | "
                            f"[DEĞİŞİM]: {delta:+6d} | "
                            f"[AÇI]: {deg:+6.1f}° | "
                            f"Durum: {status}   ",
                            end="",
                            flush=True,
                        )
    except KeyboardInterrupt:
        print("\n\nTest sonlandırıldı.")
    finally:
        ser.close()

if __name__ == "__main__":
    main()
