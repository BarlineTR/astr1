#!/usr/bin/env python3
"""Standalone Head Encoder Verification Tool.

Directly connects to Arduino Mega via serial (/dev/ttyCH341USB0) without ROS 2,
sends heartbeats, and streams raw ENCODER_TICKS payloads in real time.
"""

import argparse
import struct
import sys
import time

try:
    import serial
except ImportError:
    print("ERROR: pyserial is required. Run 'pip install pyserial'.")
    sys.exit(1)

# Protocol Constants
SOF1 = 0xAA
SOF2 = 0x55
MSG_HEARTBEAT = 0x01
MSG_WHEEL_CMD = 0x02
MSG_HEAD_CMD = 0x03
MSG_HEAD_SET_ZERO = 0x04
MSG_IMU_DATA = 0x10
MSG_ENCODER_TICKS = 0x11
MSG_DIAGNOSTICS = 0x12
MSG_HEARTBEAT_ACK = 0x13

TICKS_PER_DEG = 0.288


def crc8(data: bytes) -> int:
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def build_packet(msg_id: int, payload: bytes = b"") -> bytes:
    length = 1 + len(payload)
    header = bytes([SOF1, SOF2, length, msg_id])
    chk = crc8(bytes([length, msg_id]) + payload)
    return header + payload + bytes([chk])


def parse_packets(stream: bytearray):
    packets = []
    i = 0
    n = len(stream)
    while i < n:
        if stream[i] != SOF1:
            i += 1
            continue
        if i + 1 >= n:
            break
        if stream[i + 1] != SOF2:
            i += 1
            continue
        if i + 2 >= n:
            break
        length = stream[i + 2]
        end = i + 3 + length
        if end >= n:
            break
        body = stream[i + 2 : end]
        if crc8(body) != stream[end]:
            i += 1
            continue
        msg_id = stream[i + 3]
        payload = bytes(stream[i + 4 : end])
        packets.append((msg_id, payload))
        i = end + 1
    del stream[:i]
    return packets


def main():
    parser = argparse.ArgumentParser(description="Test raw head encoder ticks from Arduino.")
    parser.add_argument("--port", default="/dev/ttyCH341USB0", help="Serial port (default: /dev/ttyCH341USB0)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--duration", type=float, default=15.0, help="Test duration in seconds (default: 15.0)")
    parser.add_argument("--move", action="store_true", help="Send slight head motor commands (+10° / -10°) to test dynamic movement")
    args = parser.parse_args()

    print(f"Opening serial port {args.port} at {args.baud} baud...")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.05)
    except Exception as e:
        print(f"Failed to open port {args.port}: {e}")
        sys.exit(1)

    # Allow Arduino reset after serial connect
    time.sleep(1.8)
    ser.reset_input_buffer()

    rx_buf = bytearray()
    start_time = time.monotonic()
    last_beat = 0.0
    seq = 0

    packet_count = 0
    non_zero_ticks_seen = 0
    initial_ticks = None
    last_reported_ticks = None

    print("\n" + "=" * 65)
    print(">>> LISTENING FOR ENCODER TICKS FROM ARDUINO...")
    print("   Please move the robot head gently by hand or observe motor.")
    print("=" * 65 + "\n")

    try:
        while time.monotonic() - start_time < args.duration:
            now = time.monotonic()

            # Heartbeat or motion command
            if now - last_beat > 0.1:
                last_beat = now
                seq += 1
                if args.move:
                    # Move +10° for 2s, then -10° for 2s, then 0°
                    elapsed = now - start_time
                    target = 10.0 if (int(elapsed) % 4 < 2) else -10.0
                    cmd_pkt = build_packet(MSG_HEAD_CMD, struct.pack("<f", target))
                    ser.write(cmd_pkt)
                else:
                    hb_pkt = build_packet(MSG_HEARTBEAT, struct.pack("<I", seq & 0xFFFFFFFF))
                    ser.write(hb_pkt)

            # Read serial data
            chunk = ser.read(ser.in_waiting or 1)
            if chunk:
                rx_buf.extend(chunk)
                packets = parse_packets(rx_buf)
                for msg_id, payload in packets:
                    if msg_id == MSG_ENCODER_TICKS and len(payload) >= 16:
                        wheel_l, wheel_r, head_ticks, dt_us = struct.unpack("<iiiI", payload[:16])
                        packet_count += 1

                        if initial_ticks is None:
                            initial_ticks = head_ticks

                        delta = head_ticks - initial_ticks
                        angle_deg = head_ticks / TICKS_PER_DEG

                        if head_ticks != 0:
                            non_zero_ticks_seen += 1

                        # Print on change or periodically
                        if last_reported_ticks is None or head_ticks != last_reported_ticks or packet_count % 20 == 0:
                            last_reported_ticks = head_ticks
                            status = "[ACTIVE]" if head_ticks != 0 else "[ZERO  ]"
                            print(
                                f"{status} Pkt #{packet_count:04d} | "
                                f"Head Ticks: {head_ticks:+6d} (delta: {delta:+5d}, ~{angle_deg:+.1f} deg) | "
                                f"Wheels: [L:{wheel_l:+5d}, R:{wheel_r:+5d}]"
                            )

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        # Send 0.0 cmd and close
        ser.write(build_packet(MSG_HEAD_CMD, struct.pack("<f", 0.0)))
        ser.close()

    print("\n" + "=" * 65)
    print("--- TEST SUMMARY ---")
    print(f"   Total ENCODER_TICKS packets received: {packet_count}")
    print(f"   Non-zero head ticks count: {non_zero_ticks_seen}")
    if non_zero_ticks_seen > 0:
        print(f"   >>> SUCCESS: Encoder pulses detected! Last ticks = {last_reported_ticks}")
    else:
        print("   >>> NOTICE: All received packets reported 0 head ticks.")
    print("=" * 65)


if __name__ == "__main__":
    main()
