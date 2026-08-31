#!/usr/bin/env python3
"""ASTRO Robot - Isolated Head Actuator Calibration & Step Verification Tool.

Directly tests the serial bridge, Arduino Mega 2560 firmware PID, and optical encoder
without running audio, vision, or gaze FSM nodes.
"""

import math
import struct
import sys
import time
import serial
import glob
import os

SOF1 = 0xAA
SOF2 = 0x55
MSG_HEAD_CMD = 0x03
MSG_ENCODER_TICKS = 0x11
MSG_HEARTBEAT = 0x01
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


def find_serial_port():
    patterns = ["/dev/ttyCH341USB*", "/dev/ttyUSB*", "/dev/ttyACM*"]
    for pat in patterns:
        matches = glob.glob(pat)
        for m in matches:
            if "lidar" not in m:
                return m
    return "/dev/ttyCH341USB0"


class HeadCalibrator:
    def __init__(self, port: str = None, baud: int = 115200):
        self.port_name = port or find_serial_port()
        self.baud = baud
        self.ser = None
        self.raw_head_ticks = 0
        self.running = True

    def connect(self):
        print(f"\n[1/3] Connecting to Arduino on {self.port_name} at {self.baud} baud...")
        try:
            self.ser = serial.Serial(self.port_name, self.baud, timeout=0.1)
            time.sleep(1.5)  # Allow Arduino reset
            print("  -> Connected successfully!")
        except Exception as e:
            print(f"  -> ERROR: Failed to open serial port {self.port_name}: {e}")
            sys.exit(1)

    def send_heartbeat(self):
        pkt = build_packet(MSG_HEARTBEAT, struct.pack("<I", 1))
        self.ser.write(pkt)

    def read_telemetry(self, timeout_s: float = 1.0) -> bool:
        """Reads latest encoder ticks from Arduino stream."""
        start = time.time()
        buf = bytearray()
        state = 0
        expected_len = 0

        while time.time() - start < timeout_s:
            if self.ser.in_waiting > 0:
                chunk = self.ser.read(self.ser.in_waiting)
                for b in chunk:
                    if state == 0:
                        if b == SOF1: state = 1
                    elif state == 1:
                        if b == SOF2: state = 2
                        elif b != SOF1: state = 0
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
                        if c == b and len(buf) > 0:
                            msg_id = buf[0]
                            payload = bytes(buf[1:])
                            if msg_id == MSG_ENCODER_TICKS and len(payload) >= 12:
                                if len(payload) == 16:
                                    dl, dr, head_ticks, dt_us = struct.unpack("<iiiI", payload)
                                    self.raw_head_ticks = head_ticks
                                    return True
                        state = 1 if b == SOF1 else 0
            time.sleep(0.01)
        return False

    def command_angle(self, angle_deg: float):
        """Sends binary head angle command."""
        self.send_heartbeat()
        payload = struct.pack("<f", float(angle_deg))
        pkt = build_packet(MSG_HEAD_CMD, payload)
        self.ser.write(pkt)
        self.ser.flush()

    def run_manual_encoder_calibration(self):
        """Measures raw encoder resolution by manual physical rotation."""
        print("\n========================================================")
        print("   MANUAL ENCODER RESOLUTION CALIBRATION")
        print("========================================================")
        print("Instructions:")
        print("1. Turn the head manually to 0.0° (Center position).")
        input("Press [ENTER] when head is at 0.0° Center...")
        self.send_heartbeat()
        time.sleep(0.2)
        self.read_telemetry()
        start_ticks = self.raw_head_ticks
        print(f"  -> Baseline 0.0° Encoder Ticks = {start_ticks}")

        print("\n2. Now manually rotate the physical head by a KNOWN angle.")
        print("   (e.g., exactly +45° Left or +90° Left, or -45° Right)")
        measured_angle_str = input("Enter the physical angle you turned (in degrees, e.g. 45 or 90): ")
        try:
            measured_angle = float(measured_angle_str)
        except ValueError:
            print("Invalid number!")
            return

        self.send_heartbeat()
        time.sleep(0.2)
        self.read_telemetry()
        end_ticks = self.raw_head_ticks
        delta_ticks = end_ticks - start_ticks

        print("\n---------------- RESULTS ----------------")
        print(f"Physical Head Angle     : {measured_angle:+.2f}°")
        print(f"Start Encoder Ticks     : {start_ticks}")
        print(f"End Encoder Ticks       : {end_ticks}")
        print(f"Delta Encoder Ticks     : {delta_ticks}")

        if abs(measured_angle) > 0.1:
            ticks_per_deg = float(delta_ticks) / float(measured_angle)
            deg_per_tick = 1.0 / ticks_per_deg if ticks_per_deg != 0 else 0.0
            ticks_per_rev = ticks_per_deg * 360.0
            print(f"\n>>> CALCULATED RESOLUTION: {ticks_per_deg:.4f} ticks / degree <<<")
            print(f"    (1 tick = {deg_per_tick:.4f} degrees, {ticks_per_rev:.1f} ticks / 360° turn)")
            print("\nRecommended actions:")
            print(f"1. In calibration_params.yaml : ticks_per_deg: {abs(ticks_per_deg):.4f}")
            print(f"2. In AstroFirmware.ino       : static constexpr float HEAD_TICKS_PER_DEG = {abs(ticks_per_deg):.4f}f;")

    def run_step_table_verification(self):
        """Runs micro-step commands (±2°, ±5°, ±10°) and builds verification table."""
        print("\n========================================================")
        print("   ISOLATED STEP COMMAND VERIFICATION TABLE")
        print("========================================================")
        test_angles = [0.0, 2.0, -2.0, 5.0, -5.0, 10.0, -10.0, 0.0]

        print("\n| ROS cmd | Packet Bytes (Hex) | Target Ticks (Calc) | Encoder Ticks (Read) | Reported Angle | Physical Obs (Notes) |")
        print("|--------:|:------------------:|--------------------:|---------------------:|---------------:|:---------------------|")

        for angle in test_angles:
            # Send command
            payload = struct.pack("<f", float(angle))
            pkt = build_packet(MSG_HEAD_CMD, payload)
            self.command_angle(angle)

            # Wait 1.0s for motor to settle
            time.sleep(1.0)
            self.read_telemetry(timeout_s=0.5)

            # Read back encoder
            ticks = self.raw_head_ticks
            reported_angle = ticks / 2.5882  # Current configured scale

            pkt_hex = " ".join(f"{b:02X}" for b in pkt)
            calc_ticks = round(angle * 2.5882)

            print(f"| {angle:+6.1f}° | `{pkt_hex}` | {calc_ticks:19d} | {ticks:20d} | {reported_angle:+13.2f}° |                      |")

        print("\nTable completed. Verify physical head angles match the commanded angles.")


def main():
    print("========================================================")
    print("   ASTRO ROBOT - HEAD ACTUATOR CALIBRATOR")
    print("========================================================")
    calib = HeadCalibrator()
    calib.connect()

    print("\nSelect Mode:")
    print("  [1] Manual Encoder Calibration (Rotate head by hand & measure exact ticks/deg)")
    print("  [2] Step Response Verification Table (±2°, ±5°, ±10° command test)")
    print("  [3] Send Single Test Angle (Safety limited to ±10°)")
    choice = input("\nEnter choice [1, 2, or 3]: ").strip()

    if choice == "1":
        calib.run_manual_encoder_calibration()
    elif choice == "2":
        calib.run_step_table_verification()
    elif choice == "3":
        ang_str = input("Enter test angle [-10.0 to +10.0 deg]: ").strip()
        try:
            ang = max(-10.0, min(10.0, float(ang_str)))
            print(f"Sending safe command: {ang:+.2f}°...")
            calib.command_angle(ang)
            time.sleep(1.0)
            calib.read_telemetry()
            print(f"Final Encoder Ticks: {calib.raw_head_ticks}")
        except ValueError:
            print("Invalid input.")


if __name__ == "__main__":
    main()
