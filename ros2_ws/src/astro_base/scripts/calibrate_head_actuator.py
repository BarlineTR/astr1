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

    def run_multi_point_manual_calibration(self):
        """Measures raw encoder ticks across multiple physical reference angles and performs linear regression."""
        print("\n========================================================")
        print("   MULTI-POINT LARGE-ANGLE ENCODER IDENTIFICATION")
        print("========================================================")
        print("Instructions:")
        print("1. Set the physical head at TRUE MECHANICAL 0.0° (Center).")
        input("Press [ENTER] when head is mechanically at 0.0° Center...")
        self.send_heartbeat()
        time.sleep(0.2)
        self.read_telemetry()
        zero_ticks = self.raw_head_ticks
        print(f"  -> Baseline 0.0° Reference Ticks = {zero_ticks}\n")

        test_points = [15.0, 30.0, 45.0, 90.0, -15.0, -30.0, -45.0, -90.0]
        recorded_data = [(0.0, 0)]  # (physical_angle, delta_ticks)

        print("For each target angle, manually align the head, then press Enter.")
        print("(If ±90° is mechanically unsafe for your wiring, you can type 'skip')\n")

        for angle in test_points:
            user_in = input(f"Align head to physical {angle:+.1f}° (or 's' to skip) -> press ENTER: ").strip().lower()
            if user_in == 's' or user_in == 'skip':
                continue

            self.send_heartbeat()
            time.sleep(0.2)
            self.read_telemetry()
            current_ticks = self.raw_head_ticks
            delta = current_ticks - zero_ticks
            recorded_data.append((angle, delta))
            print(f"  Recorded: Angle = {angle:+.1f}°, Raw Ticks = {current_ticks}, Delta Ticks = {delta:+d}\n")

        if len(recorded_data) < 3:
            print("Not enough points recorded for regression.")
            return

        # Linear regression: ticks = a * angle + b
        n = len(recorded_data)
        sum_x = sum(pt[0] for pt in recorded_data)
        sum_y = sum(pt[1] for pt in recorded_data)
        sum_xx = sum(pt[0]**2 for pt in recorded_data)
        sum_xy = sum(pt[0]*pt[1] for pt in recorded_data)
        sum_yy = sum(pt[1]**2 for pt in recorded_data)

        denom = (n * sum_xx - sum_x**2)
        if abs(denom) < 1e-6:
            print("Regression calculation error: zero denominator.")
            return

        a = (n * sum_xy - sum_x * sum_y) / denom
        b = (sum_y * sum_xx - sum_x * sum_xy) / denom

        # Calculate R^2 and residuals
        residuals = []
        for x, y in recorded_data:
            predicted = a * x + b
            residuals.append(y - predicted)

        ss_res = sum(r**2 for r in residuals)
        ss_tot = sum_yy - (sum_y**2 / n)
        r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-6 else 1.0
        rmse = math.sqrt(ss_res / n)
        max_res = max(abs(r) for r in residuals)

        print("\n========================================================")
        print("   SYSTEM IDENTIFICATION RESULTS & STATISTICAL FIT")
        print("========================================================")
        print(f"Number of Points Recorded : {n}")
        print(f"Linear Fit Equation       : encoder_ticks = ({a:.4f}) * angle_deg + ({b:.2f})")
        print(f"Slope (ticks_per_degree)  : {abs(a):.4f} ticks / degree")
        print(f"Zero Offset Residual      : {b:+.2f} ticks")
        print(f"Correlation (R²)          : {r_squared:.6f}")
        print(f"RMSE                      : {rmse:.3f} ticks")
        print(f"Max Residual Error        : {max_res:.3f} ticks")

        # Sign verification
        sign_polarity = "POSITIVE (+)" if a > 0 else "NEGATIVE (-)"
        print(f"Actuator Direction Sign   : {sign_polarity} (Left/CCW generates positive ticks)")

        print("\n---------------- FINAL VERIFICATION TABLE ----------------")
        print("| Physical Head Angle | Raw Encoder Ticks | Model Predicted Ticks | Residual Error (Ticks) |")
        print("|--------------------:|------------------:|----------------------:|-----------------------:|")
        for x, y in recorded_data:
            pred = a * x + b
            err = y - pred
            print(f"| {x:+19.1f}° | {y:+17d} | {pred:+21.1f} | {err:+22.2f} |")

        print("\n---------------- UPDATED CONFIGURATION BLOCK ----------------")
        print("# Paste this directly into config/calibration_params.yaml:")
        print("head:")
        print(f"  ticks_per_deg: {abs(a):.4f}         # Measured via linear regression (R²={r_squared:.4f})")
        print(f"  zero_offset_deg: {(-b / a if abs(a) > 0 else 0.0):.2f}")
        print("  min_angle_deg: -90.0")
        print("  max_angle_deg: 90.0")
        print("\n// Paste this into AstroFirmware.ino & main.cpp:")
        print(f"static constexpr float HEAD_TICKS_PER_DEG = {abs(a):.4f}f;")

    def run_step_table_verification(self):
        """Runs safe micro-step commands (±2°, ±5°, ±10°) and builds verification table."""
        print("\n========================================================")
        print("   ISOLATED STEP COMMAND VERIFICATION TABLE")
        print("========================================================")
        test_angles = [0.0, 2.0, 0.0, -2.0, 0.0, 5.0, 0.0, -5.0, 0.0, 10.0, 0.0, -10.0, 0.0]

        print("\n| ROS cmd | Packet Bytes (Hex) | Arduino Target (Calc) | Encoder Ticks (Read) | Reported Angle | Physical Head Angle (Notes) |")
        print("|--------:|:------------------:|----------------------:|---------------------:|---------------:|:----------------------------|")

        for angle in test_angles:
            payload = struct.pack("<f", float(angle))
            pkt = build_packet(MSG_HEAD_CMD, payload)
            self.command_angle(angle)

            time.sleep(1.0)
            self.read_telemetry(timeout_s=0.5)

            ticks = self.raw_head_ticks
            reported_angle = ticks / 2.5882  # Current configured scale
            pkt_hex = " ".join(f"{b:02X}" for b in pkt)
            calc_ticks = round(angle * 2.5882)

            print(f"| {angle:+6.1f}° | `{pkt_hex}` | {calc_ticks:21d} | {ticks:20d} | {reported_angle:+13.2f}° |                             |")

        print("\nVerification complete.")


def main():
    print("========================================================")
    print("   ASTRO ROBOT - ISOLATED ACTUATOR IDENTIFICATION")
    print("========================================================")
    calib = HeadCalibrator()
    calib.connect()

    print("\nSelect Mode:")
    print("  [1] Multi-Point Large-Angle Identification (0°, ±15°, ±30°, ±45°, ±90° with linear fit)")
    print("  [2] Safe Step Response Table Test (±2°, ±5°, ±10° command sequence)")
    print("  [3] Single Direct Angle Test (Safe range: -10° to +10°)")
    choice = input("\nEnter choice [1, 2, or 3]: ").strip()

    if choice == "1":
        calib.run_multi_point_manual_calibration()
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

