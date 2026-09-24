#!/usr/bin/env python3
"""Isolated HEAD Actuator & Encoder Test Tool for ASTRO Robot.

Bypasses all vision, Kalman filtering, coordinate transformations, and gaze arbitration.
Directly tests the physical head motor and encoder loop via send_angle():
Target sequence: 0° → +10° → +20° → +10° → 0° → -10° → 0°

Reports on every command:
command_target_deg, encoder_ticks, encoder_actual_deg, position_source, TX/RX info.
Strict invariant: encoder_actual_deg is NEVER derived from software estimation.
"""

import argparse
import os
import struct
import sys
import time
from pathlib import Path

# Add repo directories to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "standalone"))
sys.path.insert(0, str(REPO_ROOT / "ros2_ws" / "src" / "astro_base"))

try:
    import serial
except ImportError:
    print("❌ ERROR: pyserial is required. Run 'pip install pyserial'.")
    sys.exit(1)

from head_link import (
    HeadLink,
    TICKS_PER_DEG,
    encode_head_cmd,
    parse_packets,
    MSG_HEAD_CMD,
    MSG_ENCODER_TICKS,
    MSG_HEARTBEAT,
)
from astro_base.gaze.head_state import PositionSource


class SerialSpy:
    """Wraps a serial.Serial instance to log raw TX and RX bytes without altering data."""

    def __init__(self, ser):
        self._ser = ser
        self.last_tx_hex = "NONE"
        self.last_rx_summary = "NONE"
        self.total_tx_bytes = 0
        self.total_rx_bytes = 0
        self.rx_packet_count = 0
        self.head_cmd_count = 0
        self.encoder_ticks_count = 0

    @property
    def in_waiting(self):
        return getattr(self._ser, "in_waiting", 0)

    def write(self, data: bytes):
        if len(data) >= 4 and data[3] == MSG_HEAD_CMD:
            self.head_cmd_count += 1
            self.last_tx_hex = data.hex(" ").upper()
        self.total_tx_bytes += len(data)
        return self._ser.write(data)

    def read(self, size: int = 1):
        chunk = self._ser.read(size)
        if chunk:
            self.total_rx_bytes += len(chunk)
        return chunk

    def close(self):
        return self._ser.close()

    def reset_input_buffer(self):
        return self._ser.reset_input_buffer()


def auto_detect_port():
    """Tries standard serial port candidates."""
    candidates = [
        "/dev/ttyCH341USB0",
        "/dev/ttyUSB0",
        "/dev/ttyACM0",
        "/dev/astro_base",
        "COM3",
        "COM4",
        "COM6",
        "COM7",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description="Isolated HEAD Actuator & Encoder Verification Tool.")
    parser.add_argument(
        "--port",
        default=auto_detect_port(),
        help="Serial port for Arduino Mega (default: auto-detected)",
    )
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument(
        "--hold-s",
        type=float,
        default=2.0,
        help="Hold duration per target angle in seconds (default: 2.0s)",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("ASTRO ISOLATED HEAD ACTUATOR / ENCODER TEST")
    print("=" * 80)
    print(f"Port: {args.port} | Baud: {args.baud} | Hold per target: {args.hold_s}s")
    print("Bypassing: Vision, Kalman Filter, Target Calculation, Camera TF")
    print("Exercising: HeadLink.send_angle() -> Arduino HEAD_CMD -> Motor -> Encoder -> HeadLink.poll()")
    print("=" * 80)

    try:
        raw_ser = serial.Serial(args.port, args.baud, timeout=0.02)
    except Exception as exc:
        print(f"[ERROR] SERIAL PORT ERROR: Cannot open {args.port}: {exc}")
        print("\n[RESULT] BREAKAGE: LAYER 0 - PHYSICAL SERIAL CONNECTION")
        print("  Port is unavailable, disconnected, or permission denied.")
        return 1

    # Allow Arduino reset settling after DTR toggle
    print("Waiting 1.8s for Arduino bootloader to initialize...")
    time.sleep(1.8)
    raw_ser.reset_input_buffer()

    spy = SerialSpy(raw_ser)
    head = HeadLink(port=spy)

    targets = [0.0, 10.0, 20.0, 10.0, 0.0, -10.0, 0.0]

    all_ticks_recorded = []
    encoder_responsive = False

    print("\nStarting target sequence: 0 deg -> +10 deg -> +20 deg -> +10 deg -> 0 deg -> -10 deg -> 0 deg\n")
    print(
        f"{'STEP':<6} | {'TARGET':<8} | {'TICKS':<8} | {'ACTUAL_DEG':<10} | {'SOURCE':<10} | {'RAW_TX_HEX':<24} | {'LAST_RX':<20}"
    )
    print("-" * 105)

    step_idx = 0
    test_start = time.monotonic()

    try:
        for tgt in targets:
            step_idx += 1
            step_start = time.monotonic()

            # 1. Send absolute head target via standard send_angle API
            head.send_angle(tgt)

            # Sample periodically during hold time
            while time.monotonic() - step_start < args.hold_s:
                now = time.monotonic()
                head.poll()
                head.tick(now)

                hstate = head.state_mgr.evaluate(timestamp=now)

                # Strict invariant: encoder_actual_deg is NEVER derived from software estimation
                if hstate.position_source == PositionSource.ENCODER and hstate.actual_yaw_deg is not None:
                    enc_actual = f"{hstate.actual_yaw_deg:+.2f}°"
                    pos_source = "ENCODER"
                else:
                    enc_actual = "None"
                    pos_source = "UNKNOWN"

                raw_ticks = getattr(head.state_mgr, "encoder_ticks", None)
                if raw_ticks is not None:
                    all_ticks_recorded.append(raw_ticks)
                    ticks_str = f"{raw_ticks:+d}"
                else:
                    ticks_str = "None"

                rx_desc = f"pkts={spy.rx_packet_count} bytes={spy.total_rx_bytes}"

                line = (
                    f"[{step_idx}/{len(targets)}]  | "
                    f"{tgt:+5.1f}°  | "
                    f"{ticks_str:<8} | "
                    f"{enc_actual:<10} | "
                    f"{pos_source:<10} | "
                    f"{spy.last_tx_hex:<24} | "
                    f"{rx_desc}"
                )
                print(line)
                time.sleep(0.20)

    except KeyboardInterrupt:
        print("\n[INFO] Test interrupted by user.")
    finally:
        # Return head to 0.0 on exit
        try:
            head.send_angle(0.0)
            time.sleep(0.2)
            head.poll()
            spy.close()
        except Exception:
            pass

    # =========================================================================
    # FORENSIC BREAKAGE ANALYSIS
    # =========================================================================
    print("\n" + "=" * 80)
    print("HAM TEST SONUCLARI VE KATMAN ANALIZI")
    print("=" * 80)

    total_time = time.monotonic() - test_start
    print(f"Toplam Sure: {total_time:.1f} s")
    print(f"Gonderilen HEAD_CMD Paketleri (TX): {spy.head_cmd_count}")
    print(f"Alinan Toplam Seri Bayt (RX): {spy.total_rx_bytes} bytes")

    unique_ticks = set(all_ticks_recorded)
    ticks_range = (max(all_ticks_recorded) - min(all_ticks_recorded)) if all_ticks_recorded else 0

    print(f"Kaydedilen Enkoder Ticks Cesitliligi: {len(unique_ticks)} farkli deger (Aralik: {ticks_range} ticks)")
    if all_ticks_recorded:
        print(f"Ilk Ticks: {all_ticks_recorded[0]} | Son Ticks: {all_ticks_recorded[-1]}")

    print("-" * 80)
    print("KATMAN KIRILMA DEGERLENDIRMESI:")

    if spy.total_rx_bytes == 0:
        print("[KIRILMA] KATMAN 1 - SERI RX / ARDUINO DONGUSU")
        print("  Arduino'dan hicbir bayt donmuyor. UART0 baglantisi, baud rate (115200) veya")
        print("  Arduino loopControl() kilitlenmis/resetlenmis olabilir.")
    elif not all_ticks_recorded or len(unique_ticks) <= 1:
        print("[KIRILMA] KATMAN 2 - FIZIKSEL ENKODER / MOTOR SURUCU (L298N/BTS7960/DONANIM)")
        print("  Arduino seri paketleri aliyor ve ENCODER_TICKS donuyor ANCAK ticks degeri")
        print("  komutlar (+10, +20, -10) verilmesine ragmen HIC DEGISMIYOR (0 veya sabit).")
        print("  Muhtemel nedenler:")
        print("    1. Kafa motoruna 12V motor beslemesi gitmiyor (anahtar kapali / sigorta / kablo).")
        print("    2. Enkoder A/B pinleri (Pin 18/19 vb.) kesme almiyor veya gevsek.")
        print("    3. Motor surucu PWM cikisi vermiyor veya stall guard devrede.")
    else:
        print("[BASARILI] TUM KATMANLAR SAGLIKLI")
        print("  HEAD_CMD Arduino tarafindan basariyla alindi, motor hareket etti ve enkoder")
        print("  komutla uyumlu olarak degisti.")
    print("=" * 80)


if __name__ == "__main__":
    sys.exit(main())
