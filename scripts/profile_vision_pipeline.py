#!/usr/bin/env python3
"""ASTRO V1 — Vision Pipeline Forensic Profiler & Threading Benchmark.

Executes Phase A forensic measurements requested for ASTRO Social Gaze:
  1. Component latency breakdown:
     - imgmsg_to_bgr conversion
     - cv2.resize (720P -> 640x360)
     - cv2.cvtColor (BGR -> Gray)
     - primary face_cascade (detectMultiScale3)
     - fallback face_alt_cascade (detectMultiScale3)
  2. OpenCV threading test:
     - cv2.setNumThreads(1) vs default (multi-threaded)
     - Measures latency p50, p95, min, max, and effective throughput
  3. Live camera topic timing (/oak/rgb/image_raw):
     - Source timestamp interval (hardware clock delta)
     - Arrival interval (transport delta)
     - Timestamp age upon arrival (true transit latency)

Usage:
  # Run offline synthetic benchmark (no ROS needed):
  python3 scripts/profile_vision_pipeline.py --mode=benchmark

  # Run live camera measurement on Jetson (60s):
  python3 scripts/profile_vision_pipeline.py --mode=camera --duration=60
"""

import argparse
import math
import os
import sys
import time
from typing import List, Tuple

import numpy as np

try:
    import cv2
except ImportError:
    print("❌ OpenCV bulunamadı. Lütfen 'python3 -m pip install opencv-python' kurun.")
    sys.exit(1)


def run_synthetic_benchmark(num_iterations: int = 50):
    """Measures exact per-component latencies and thread scaling."""
    print("=" * 80)
    print("       ASTRO VISION FORENSIC BENCHMARK — COMPONENT & THREAD PROFILING")
    print("=" * 80)

    # Initialize Haar cascades
    haar_dir = cv2.data.haarcascades
    face_cascade_path = os.path.join(haar_dir, "haarcascade_frontalface_default.xml")
    face_alt_path = os.path.join(haar_dir, "haarcascade_frontalface_alt2.xml")

    face_cascade = cv2.CascadeClassifier(face_cascade_path)
    face_alt_cascade = cv2.CascadeClassifier(face_alt_path)

    # Create synthetic 720P test frame (1280x720) with a realistic face-like gradient patch
    test_frame_720p = np.zeros((720, 1280, 3), dtype=np.uint8)
    cv2.circle(test_frame_720p, (640, 360), 80, (200, 200, 200), -1)
    cv2.circle(test_frame_720p, (610, 330), 12, (20, 20, 20), -1)
    cv2.circle(test_frame_720p, (670, 330), 12, (20, 20, 20), -1)
    cv2.ellipse(test_frame_720p, (640, 390), (30, 15), 0, 0, 180, (50, 50, 50), 3)

    # Test blank frame (triggers second fallback cascade)
    blank_frame_720p = np.zeros((720, 1280, 3), dtype=np.uint8)

    max_system_threads = cv2.getNumberOfCPUs()
    thread_configs = [1, 2, max_system_threads]

    for threads in thread_configs:
        cv2.setNumThreads(threads)
        actual_threads = cv2.getNumThreads()
        print(f"\n--- [TEST] cv2.setNumThreads({threads}) (Aktif İş Parçacığı: {actual_threads}) ---")

        # 1. Resize & Grayscale Conversion Latency
        resize_times: List[float] = []
        for _ in range(num_iterations):
            t0 = time.perf_counter()
            small = cv2.resize(test_frame_720p, (640, 360), interpolation=cv2.INTER_LINEAR)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            t1 = time.perf_counter()
            resize_times.append((t1 - t0) * 1000.0)

        # 2. Primary Face Cascade Latency (With face present)
        small_gray = cv2.cvtColor(cv2.resize(test_frame_720p, (640, 360)), cv2.COLOR_BGR2GRAY)
        primary_face_times: List[float] = []
        for _ in range(num_iterations):
            t0 = time.perf_counter()
            _ = face_cascade.detectMultiScale3(
                small_gray,
                scaleFactor=1.10,
                minNeighbors=3,
                minSize=(24, 24),
                outputRejectLevels=True,
            )
            t1 = time.perf_counter()
            primary_face_times.append((t1 - t0) * 1000.0)

        # 3. Fallback Alt Cascade Latency (Blank frame -> searches both primary AND alt)
        blank_small_gray = cv2.cvtColor(cv2.resize(blank_frame_720p, (640, 360)), cv2.COLOR_BGR2GRAY)
        fallback_cascade_times: List[float] = []
        dual_cascade_times: List[float] = []
        for _ in range(num_iterations):
            t0 = time.perf_counter()
            rects1, _, _ = face_cascade.detectMultiScale3(
                blank_small_gray,
                scaleFactor=1.10,
                minNeighbors=3,
                minSize=(24, 24),
                outputRejectLevels=True,
            )
            t1 = time.perf_counter()
            rects2, _, _ = face_alt_cascade.detectMultiScale3(
                blank_small_gray,
                scaleFactor=1.10,
                minNeighbors=3,
                minSize=(24, 24),
                outputRejectLevels=True,
            )
            t2 = time.perf_counter()
            fallback_cascade_times.append((t2 - t1) * 1000.0)
            dual_cascade_times.append((t2 - t0) * 1000.0)

        # Calculate statistics
        def _stats(arr):
            return {
                "p50": np.percentile(arr, 50),
                "p95": np.percentile(arr, 95),
                "mean": np.mean(arr),
                "min": np.min(arr),
                "max": np.max(arr),
            }

        s_resize = _stats(resize_times)
        s_pri = _stats(primary_face_times)
        s_alt = _stats(fallback_cascade_times)
        s_dual = _stats(dual_cascade_times)

        print(f"  • Resize + BGR2GRAY (720P -> 640x360) : p50={s_resize['p50']:5.2f}ms | p95={s_resize['p95']:5.2f}ms")
        print(f"  • Primary Haar Cascade (Yüz Varken)    : p50={s_pri['p50']:5.2f}ms | p95={s_pri['p95']:5.2f}ms | Ort={s_pri['mean']:5.2f}ms")
        print(f"  • Fallback face_alt2 (Yüz Yokken)      : p50={s_alt['p50']:5.2f}ms | p95={s_alt['p95']:5.2f}ms | Ort={s_alt['mean']:5.2f}ms")
        print(f"  • Çift Kaskad Toplamı (Yüz Yokken)     : p50={s_dual['p50']:5.2f}ms | p95={s_dual['p95']:5.2f}ms | Max={s_dual['max']:5.2f}ms")
        theoretical_fps = 1000.0 / s_dual["mean"] if s_dual["mean"] > 0 else 0
        print(f"  • Teorik Tek Çekirdek FPS Tavanı       : {theoretical_fps:5.1f} FPS (Boş kare çift tarama)")


def run_live_camera_analysis(duration_sec: float = 60.0):
    """Subscribes directly to /oak/rgb/image_raw and analyzes timestamp intervals."""
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
        from sensor_msgs.msg import Image
    except ImportError:
        print("❌ ROS 2 ortamı (rclpy) bulunamadı. Lütfen 'source /opt/ros/humble/setup.bash' yapın.")
        return

    rclpy.init()
    node = Node("astro_camera_timing_profiler")

    source_stamps: List[float] = []
    arrival_stamps: List[float] = []
    latencies_ms: List[float] = []

    def _cb(msg: Image):
        now_ros_s = node.get_clock().now().nanoseconds * 1e-9
        source_s = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        arrival_stamps.append(now_ros_s)
        source_stamps.append(source_s)
        if source_s > 0:
            latencies_ms.append((now_ros_s - source_s) * 1000.0)

    qos = QoSProfile(
        reliability=QoSReliabilityPolicy.BEST_EFFORT,
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=1,
    )
    sub = node.create_subscription(Image, "/oak/rgb/image_raw", _cb, qos)

    print("=" * 80)
    print(f"   ASTRO CANLI KAMERA ZAMANLAMA TESTİ — /oak/rgb/image_raw ({duration_sec} saniye)")
    print("=" * 80)
    print("Veri toplanıyor... Lütfen bekleyin...")

    start_t = time.time()
    try:
        while (time.time() - start_t) < duration_sec and rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass

    total_frames = len(arrival_stamps)
    actual_duration = time.time() - start_t
    observed_fps = total_frames / max(0.1, actual_duration)

    print("\n" + "=" * 80)
    print("                   CANLI KAMERA ZAMANLAMA RAPORU")
    print("=" * 80)
    print(f"Test Süresi                  : {actual_duration:.2f} saniye")
    print(f"Alınan Toplam Kare Sayısı    : {total_frames} kare")
    print(f"Gözlemlenen Ortalama FPS     : {observed_fps:.2f} FPS")

    if total_frames > 2:
        source_deltas = [
            (source_stamps[i] - source_stamps[i - 1]) * 1000.0
            for i in range(1, len(source_stamps))
        ]
        arrival_deltas = [
            (arrival_stamps[i] - arrival_stamps[i - 1]) * 1000.0
            for i in range(1, len(arrival_stamps))
        ]

        print("\n[1] KAYNAK ZAMAN DAMGASI ARALIĞI (SOURCE TIMESTAMP INTERVAL - OAK-D):")
        print(f"  • Ortalama Donanım Aralığı   : {np.mean(source_deltas):.2f} ms")
        print(f"  • Medyan (p50) Donanım Aralığı: {np.percentile(source_deltas, 50):.2f} ms")
        print(f"  • p95 Donanım Aralığı        : {np.percentile(source_deltas, 95):.2f} ms")
        print(f"  • Min / Max Donanım Aralığı  : {np.min(source_deltas):.2f} ms / {np.max(source_deltas):.2f} ms")

        print("\n[2] VARIŞ ARALIĞI (ARRIVAL INTERVAL - DDS / HOST):")
        print(f"  • Ortalama Varış Aralığı     : {np.mean(arrival_deltas):.2f} ms")
        print(f"  • Medyan (p50) Varış Aralığı : {np.percentile(arrival_deltas, 50):.2f} ms")
        print(f"  • p95 Varış Aralığı          : {np.percentile(arrival_deltas, 95):.2f} ms")
        print(f"  • Min / Max Varış Aralığı    : {np.min(arrival_deltas):.2f} ms / {np.max(arrival_deltas):.2f} ms")

        if latencies_ms:
            valid_lat = [l for l in latencies_ms if abs(l) < 30000.0]
            if valid_lat:
                print("\n[3] DONANIM -> DÜĞÜM GERÇEK İLETİM FARKI (NOW - STAMP):")
                print(f"  • Ortalama İletim Farkı      : {np.mean(valid_lat):.2f} ms")
                print(f"  • Medyan (p50) İletim Farkı  : {np.percentile(valid_lat, 50):.2f} ms")
                print(f"  • p95 İletim Farkı           : {np.percentile(valid_lat, 95):.2f} ms")
                print(f"  • Min / Max İletim Farkı     : {np.min(valid_lat):.2f} ms / {np.max(valid_lat):.2f} ms")

    node.destroy_node()
    rclpy.shutdown()


def main():
    parser = argparse.ArgumentParser(description="ASTRO Vision Profiler")
    parser.add_argument("--mode", choices=["benchmark", "camera"], default="benchmark")
    parser.add_argument("--duration", type=float, default=60.0)
    args = parser.parse_args()

    if args.mode == "benchmark":
        run_synthetic_benchmark()
    elif args.mode == "camera":
        run_live_camera_analysis(args.duration)


if __name__ == "__main__":
    main()
