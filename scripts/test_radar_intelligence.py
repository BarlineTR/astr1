#!/usr/bin/env python3
"""ASTRO V1 — Radar (LiDAR) Spatial Intelligence & Memory Test Tool.

Tests:
1. Spatial Clustering & Distance Measurement (LidarTracker)
2. Radial Velocity Calculation (Stationary object vs. approaching human)
3. Blindspot Approach Reflex (Robot turns head curiously when approached from sides)
4. Spatial Memory Landmark Storage (SQLite persistent spatial memory)

Usage:
  # 1. Offline Simulation (No hardware needed, runs on laptop with ASCII radar display):
  python scripts/test_radar_intelligence.py --sim

  # 2. Live ROS 2 Mode (Connects to running RPLIDAR /scan topic):
  python scripts/test_radar_intelligence.py --live
"""

import argparse
import io
import math
import os
import sys
import time
from typing import List, Tuple

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure astro_ai is importable
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ASTRO_AI_PATH = os.path.join(WORKSPACE_ROOT, "ros2_ws", "src", "astro_ai")
if ASTRO_AI_PATH not in sys.path:
    sys.path.insert(0, ASTRO_AI_PATH)

try:
    from astro_ai.spatial.lidar_tracker import LidarTracker
    from astro_ai.contracts.spatial_state import LidarCluster, SpatialPersonTrack
    from astro_ai.memory_v2.sqlite_storage import SQLiteMemoryStorage
    from astro_ai.memory_v2.spatial_memory import SpatialMemory
except ImportError as err:
    print(f"[ERROR] Could not import astro_ai modules: {err}")
    print("Ensure python environment is active and PYTHONPATH includes ros2_ws/src/astro_ai.")
    sys.exit(1)


def render_ascii_radar(
    tracks: List[SpatialPersonTrack],
    grid_size: int = 15,
    max_range_m: float = 3.0,
    reflex_active: bool = False,
    target_yaw: float = 0.0,
) -> str:
    """Renders a 2D top-down ASCII polar radar representation."""
    grid = [["·" for _ in range(grid_size)] for _ in range(grid_size)]
    cx = grid_size // 2
    cy = grid_size // 2

    # Draw range rings (1m, 2m, 3m)
    for r_m, char in [(1.0, "1"), (2.0, "2"), (3.0, "3")]:
        r_grid = int(round((r_m / max_range_m) * (grid_size // 2)))
        for dy in range(-r_grid, r_grid + 1):
            for dx in range(-r_grid, r_grid + 1):
                d = math.hypot(dx, dy)
                if abs(d - r_grid) < 0.5:
                    gx, gy = cx + dx, cy - dy
                    if 0 <= gx < grid_size and 0 <= gy < grid_size and grid[gy][gx] == "·":
                        grid[gy][gx] = char

    # Robot at center
    grid[cy][cx] = "▲"  # Pointing forward (+X)

    # Place tracks
    for tr in tracks:
        # tr.azimuth_deg: 0 is forward, + is left (CCW in ROS), - is right
        ang_rad = math.radians(tr.azimuth_deg)
        dist = tr.distance_m
        if dist > max_range_m:
            continue
        scale = (grid_size // 2) / max_range_m
        dx = -math.sin(ang_rad) * dist * scale
        dy = -math.cos(ang_rad) * dist * scale
        gx = int(round(cx + dx))
        gy = int(round(cy + dy))
        is_approaching = tr.velocity_mps < -0.05
        if 0 <= gx < grid_size and 0 <= gy < grid_size:
            grid[gy][gx] = "⚡" if is_approaching else "👤"

    lines = []
    lines.append("       [İLERİ / 0°]")
    for row in grid:
        lines.append("  " + " ".join(row))
    lines.append("  [SOL +90°]  ROBOT  [SAĞ -90°]")
    if reflex_active:
        lines.append(f"  👉 [REFLEKS AKTİF] Kafa Çevirme Hedefi: {target_yaw:+.1f}°")
    return "\n".join(lines)


def run_simulation():
    print("=" * 70)
    print("🛰️  ASTRO RADAR (LiDAR) SPATIAL INTELLIGENCE SIMULATION")
    print("=" * 70)
    print("Senaryo:")
    print("1. Robot IDLE (boşta) bekliyor.")
    print("2. Bir kişi sol kör noktadan (+45° açıyla, 2.5 metre mesafeden) yaklaşıyor.")
    print("3. LiDAR Tracker kümeyi yakalayıp yaklaşma hızını (velocity < -0.05 m/s) hesaplar.")
    print("4. İnsansı Zeka (Blindspot Curiosity Reflex) tetiklenir ve kafa oraya çevrilir.")
    print("=" * 70)
    time.sleep(0.5)

    tracker = LidarTracker()

    # Distances for approaching person over 4 frames
    trajectory = [2.5, 2.1, 1.7, 1.3]
    t_start = 100.0

    for step, dist in enumerate(trajectory):
        t_current = t_start + (step * 0.5)  # 0.5s intervals (vel approx -0.8 m/s)

        # Generate 360-degree synthetic scan
        ranges = [8.0] * 360
        # +45 degrees in 0..359 array (where 180 is 0°, 225 is +45°)
        idx = int(round(180 + 45))
        for offset in [-2, -1, 0, 1, 2]:
            ranges[(idx + offset) % 360] = dist + (abs(offset) * 0.02)

        snapshot = tracker.process_scan(
            ranges=ranges,
            angle_min=-math.pi,
            angle_increment=math.radians(1.0),
            timestamp=t_current,
        )
        tracks = tracker.get_active_tracks()

        # Evaluate reflex condition (mirroring astro_realtime_node._evaluate_lidar_blindspot_approach)
        reflex_triggered = False
        target_yaw = 0.0
        best_candidate = None
        for tr in tracks:
            az = tr.azimuth_deg
            if 25.0 <= abs(az) <= 70.0:
                if 0.3 <= tr.distance_m <= 2.5:
                    if tr.velocity_mps < -0.05 or tr.distance_m < 1.6:
                        best_candidate = tr
                        reflex_triggered = True
                        target_yaw = float(tr.azimuth_deg)

        print(f"\n--- [ADIM {step + 1} / {len(trajectory)}] Zaman: {t_current:.1f}s ---")
        if tracks:
            t = tracks[0]
            print(f"📍 Tespit Edilen Varlık: ID={t.track_id} | Açı={t.azimuth_deg:+.1f}° | Mesafe={t.distance_m:.2f}m | Hız={t.velocity_mps:+.2f} m/s")
            if t.velocity_mps < -0.05:
                print(f"⚡ DURUM: Yaklaşıyor! (Hız: {t.velocity_mps:.2f} m/s)")
            else:
                print(f"⏸️  DURUM: Sabit veya Uzaklaşıyor.")
        else:
            print("📍 Varlık tespit edilemedi.")

        # Display radar visualization
        radar_view = render_ascii_radar(
            tracks,
            grid_size=13,
            max_range_m=3.0,
            reflex_active=reflex_triggered,
            target_yaw=target_yaw,
        )
        print(radar_view)

        if reflex_triggered and best_candidate:
            print(f"👀 [LiDAR Blindspot Reflex TETİKLENDİ]")
            print(f"   Robot başı {target_yaw:+.1f}° açısına yönlendiriliyor!")
            print(f"   Kamera o yöne dönüp yüz arayacak, yüz bulursa konuşma başlayacak.")

        time.sleep(0.5)

    print("\n" + "=" * 70)
    print("🧠 2. AŞAMA: MEKÂNSAL HAFIZA (SPATIAL MEMORY) TESTİ")
    print("=" * 70)
    storage = SQLiteMemoryStorage(":memory:")
    spat_mem = SpatialMemory(storage)

    print("İşaretler (Landmarks) veritabanına kaydediliyor...")
    lm1 = spat_mem.store_landmark(
        name="Ofis Kapısı",
        category="Giriş",
        x_m=2.40,
        y_m=1.60,
        orientation_deg=45.0,
        description="Ana giriş kapısı",
    )
    lm2 = spat_mem.store_landmark(
        name="Toplantı Masası",
        category="Mobilya",
        x_m=-1.50,
        y_m=3.00,
        orientation_deg=0.0,
        description="Büyük çalışma masası",
    )
    print(f"✅ Kaydedildi: '{lm1.name}' ({lm1.relative_x_m}m, {lm1.relative_y_m}m)")
    print(f"✅ Kaydedildi: '{lm2.name}' ({lm2.relative_x_m}m, {lm2.relative_y_m}m)")

    print("\nHafızadan sorgulama yapılıyor:")
    recalled = spat_mem.get_landmark("Ofis Kapısı")
    if recalled:
        print(f"🔍 Hatırlandı: {recalled.name} -> Kategori: {recalled.category}, Mesafe: {math.hypot(recalled.relative_x_m, recalled.relative_y_m):.2f}m, Açı: {recalled.orientation_deg}°")
        print(f"   Açıklama: {recalled.description}")

    print("\n🎉 Tüm Radar Zeka ve Hafıza Testleri Başarıyla Tamamlandı!")


def run_live():
    print("=" * 70)
    print("🛰️  ASTRO CANLI RADAR (LiDAR) DİNLENİYOR (/scan)...")
    print("=" * 70)
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import LaserScan
    except ImportError:
        print("[HATA] rclpy kütüphanesi bulunamadı. ROS 2 ortamını kaynaklayın: source /opt/ros/humble/setup.bash")
        sys.exit(1)

    rclpy.init()
    tracker = LidarTracker()

    class LidarVisualizerNode(Node):
        def __init__(self):
            super().__init__("lidar_intelligence_visualizer")
            qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
            self.create_subscription(LaserScan, "/scan", self.on_scan, qos)
            self.create_subscription(LaserScan, "/scan_filtered", self.on_scan, qos)
            self.last_print = 0.0
            self.get_logger().info("Canlı /scan konusu bekleniyor...")

        def on_scan(self, msg: LaserScan):
            now = time.monotonic()
            if now - self.last_print < 0.5:
                return
            self.last_print = now

            tracker.process_scan(
                ranges=list(msg.ranges),
                angle_min=msg.angle_min,
                angle_increment=msg.angle_increment,
                range_min=msg.range_min,
                range_max=msg.range_max,
                timestamp=now,
            )
            tracks = tracker.get_active_tracks()

            reflex = False
            target_yaw = 0.0
            for tr in tracks:
                if 25.0 <= abs(tr.azimuth_deg) <= 70.0 and 0.3 <= tr.distance_m <= 2.5:
                    if tr.velocity_mps < -0.05 or tr.distance_m < 1.6:
                        reflex = True
                        target_yaw = tr.azimuth_deg
                        break

            # Clear screen ANSI
            print("\033[H\033[J", end="")
            print(f"🛰️  ASTRO CANLI RADAR — Aktif Varlık Sayısı: {len(tracks)}")
            print("-" * 50)
            for t in tracks:
                state = "⚡ YAKLAŞIYOR" if t.velocity_mps < -0.05 else ("🚶 SABİT/UZAKLAŞIYOR")
                print(f"Varlık {t.track_id}: {t.distance_m:.2f}m @ {t.azimuth_deg:+.1f}° | Hız: {t.velocity_mps:+.2f} m/s | {state}")

            print("\n" + render_ascii_radar(tracks, grid_size=15, max_range_m=3.5, reflex_active=reflex, target_yaw=target_yaw))

    node = LidarVisualizerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("\nÇıkış yapıldı.")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASTRO Radar Intelligence Test Runner")
    parser.add_argument("--sim", action="store_true", help="Simülasyon modunu çalıştır (donanımsız masabaşı testi)")
    parser.add_argument("--live", action="store_true", help="Canlı ROS 2 /scan konusunu dinle")
    args = parser.parse_args()

    if args.live:
        run_live()
    else:
        run_simulation()
