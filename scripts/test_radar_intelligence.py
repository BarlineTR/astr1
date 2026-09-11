#!/usr/bin/env python3
"""ASTRO V1 — Professional LiDAR Radar & Spatial Intelligence Monitor.

Provides a clean, human-readable terminal dashboard displaying:
1. Real-time detected tracks, sectors (Blindspot, Front, Sides, Rear).
2. Distances, azimuth angles, and radial approach velocities.
3. Clean top-down 2D compass radar map with track ID markers.
4. Humanoid intelligence & curiosity reflex verdict explanation.

Usage:
  # 1. Offline Simulation (Interactive test without hardware):
  python scripts/test_radar_intelligence.py --sim

  # 2. Live Mode (Connects to running RPLIDAR /scan topic):
  python scripts/test_radar_intelligence.py --live
"""

import argparse
import io
import math
import os
import sys
import time
from typing import List, Optional, Tuple

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
    print(f"[ERROR] astro_ai kütüphaneleri yüklenemedi: {err}")
    print("Python sanal ortamının aktif olduğunu ve ros2_ws/src/astro_ai dizinini kontrol edin.")
    sys.exit(1)


def get_sector_info(azimuth_deg: float) -> Tuple[str, str, bool]:
    """Classifies an azimuth angle into human-friendly sectors.
    
    Returns: (sector_name, badge, is_blindspot_angle)
    """
    az = azimuth_deg
    if abs(az) <= 20.0:
        return "ÖN MERKEZ", "[ÖN]", False
    elif 20.0 < az <= 70.0:
        return "SOL KÖR NOKTA", "[SOL KÖR]", True
    elif -70.0 <= az < -20.0:
        return "SAĞ KÖR NOKTA", "[SAĞ KÖR]", True
    elif 70.0 < az <= 110.0:
        return "SOL YAN", "[SOL]", False
    elif -110.0 <= az < -70.0:
        return "SAĞ YAN", "[SAĞ]", False
    elif az > 110.0:
        return "SOL ARKA", "[SOL ARKA]", False
    else:
        return "SAĞ ARKA", "[SAĞ ARKA]", False


def render_radar_dashboard(
    tracks: List[SpatialPersonTrack],
    scan_hz: float = 10.0,
    source_name: str = "/scan",
    max_range_m: float = 3.5,
) -> str:
    """Renders a structured, professional terminal dashboard with a clean 2D radar."""
    # 1. Analyze candidates for blindspot curiosity reflex
    approaching_candidate: Optional[SpatialPersonTrack] = None
    for tr in tracks:
        az = tr.azimuth_deg
        # Blindspot sector: 25°..70° and social distance 0.3m..2.5m
        if 25.0 <= abs(az) <= 70.0 and 0.3 <= tr.distance_m <= 2.5:
            approach_streak = getattr(tr, "consecutive_approaching_count", 0)
            if tr.velocity_mps < -0.15 and approach_streak >= 2:
                if approaching_candidate is None or tr.distance_m < approaching_candidate.distance_m:
                    approaching_candidate = tr

    reflex_active = approaching_candidate is not None
    target_yaw = approaching_candidate.azimuth_deg if approaching_candidate else 0.0

    lines = []
    lines.append("=" * 88)
    lines.append(f"🛰️  ASTRO 2D RADAR (LiDAR) VE MEKÂNSAL ZEKA MONİTÖRÜ")
    lines.append(f"Kaynak: {source_name} | Frekans: {scan_hz:.1f} Hz | Tespit Edilen Nesne/Varlık: {len(tracks)}")
    lines.append("=" * 88)
    lines.append("")
    lines.append("📊 TESPİT EDİLEN NESNELER VE KÖR NOKTA DURUM TABLOSU:")
    lines.append("-" * 88)
    lines.append(f"{'ID':<8} {'SEKTÖR':<17} {'MESAFE':<10} {'AÇI (YAW)':<12} {'RADYAL HIZ':<14} {'DURUM':<14} {'EYLEM'}")
    lines.append("-" * 88)

    if not tracks:
        lines.append("  (Çevrede 3.5 metre menzil içinde hiçbir nesne tespit edilmedi - Alan tamamen boş)")
    else:
        for tr in tracks:
            sec_name, badge, is_bs = get_sector_info(tr.azimuth_deg)
            tid_num = tr.track_id.replace("track_", "#")
            approach_streak = getattr(tr, "consecutive_approaching_count", 0)

            # Motion status with 0.15 m/s threshold
            if tr.velocity_mps < -0.15:
                mot_status = "⚡ YAKLAŞIYOR"
            elif tr.velocity_mps > 0.15:
                mot_status = "↗️  UZAKLAŞIYOR"
            else:
                mot_status = "⏸️  SABİT"

            # Action evaluation (requires 2 consecutive approaching frames)
            if is_bs and tr.velocity_mps < -0.15 and approach_streak >= 2:
                action_str = f"👉 [REFLEKS AKTİF] Kafa {tr.azimuth_deg:+.1f}° açısına yöneliyor"
            elif is_bs and tr.velocity_mps < -0.15 and approach_streak == 1:
                action_str = "⏳ Doğrulanıyor (1. kare)"
            elif is_bs and tr.distance_m <= 2.5:
                action_str = "Yoksayılıyor (Durgun nesne/mobilya)"
            elif abs(tr.azimuth_deg) <= 20.0:
                action_str = "Kamera görüş alanında (Ön)"
            else:
                action_str = "İzleme (Görüş dışı/Arka)"

            lines.append(
                f"{tid_num:<8} {sec_name:<17} {tr.distance_m:>4.2f} m    {tr.azimuth_deg:>+6.1f}°     "
                f"{tr.velocity_mps:>+5.2f} m/s     {mot_status:<14} {action_str}"
            )
    lines.append("-" * 88)
    lines.append("")

    # 2. Render 2D Top-Down Circular Radar Map (19x19 Grid)
    grid_size = 19
    grid = [[" " for _ in range(grid_size)] for _ in range(grid_size)]
    cx = grid_size // 2
    cy = grid_size // 2

    # Coordinate crosshairs
    for x in range(grid_size):
        grid[cy][x] = "·"
    for y in range(grid_size):
        grid[y][cx] = "·"

    # Concentric range rings: 1.0m, 2.0m, 3.0m
    scale = (grid_size // 2) / max_range_m
    for r_m, r_lbl in [(1.0, "1"), (2.0, "2"), (3.0, "3")]:
        r_cells = r_m * scale
        for ang in range(0, 360, 15):
            rad = math.radians(ang)
            gx = int(round(cx - math.sin(rad) * r_cells))
            gy = int(round(cy - math.cos(rad) * r_cells))
            if 0 <= gx < grid_size and 0 <= gy < grid_size:
                if grid[gy][gx] == " ":
                    grid[gy][gx] = "°"

    # Robot in center (Facing Forward / Up)
    grid[cy][cx] = "▲"

    # Place tracks onto radar grid
    for tr in tracks:
        if tr.distance_m > max_range_m:
            continue
        rad = math.radians(tr.azimuth_deg)
        # ROS standard: +azimuth is left (-X in display), -azimuth is right (+X in display)
        # Forward is UP (-Y in display), Backward is DOWN (+Y in display)
        gx = int(round(cx - math.sin(rad) * tr.distance_m * scale))
        gy = int(round(cy - math.cos(rad) * tr.distance_m * scale))
        
        # Format track number
        tid_raw = tr.track_id.replace("track_", "")
        tid_char = tid_raw if len(tid_raw) <= 2 else tid_raw[-2:]
        if tr.velocity_mps < -0.08:
            cell_char = "⚡"
        else:
            cell_char = tid_char

        if 0 <= gx < grid_size and 0 <= gy < grid_size:
            grid[gy][gx] = cell_char

    lines.append("🧭 KUŞBAKIŞI 360° RADAR HARİTASI (Her halka 1 metre, Merkez: Robot ▲):")
    lines.append("                         [ 0° ÖN ]")
    lines.append("                            |")
    for row_idx, row in enumerate(grid):
        row_str = " ".join(f"{c:>2}" for c in row)
        if row_idx == cy:
            lines.append(f"  [SOL +90°] --- {row_str} --- [SAĞ -90°]")
        else:
            lines.append(f"                 {row_str}")
    lines.append("                            |")
    lines.append("                       [ ±180° ARKA ]")
    lines.append("")

    # 3. Decision & Intelligence Verdict Summary
    lines.append("-" * 88)
    lines.append("🧠 İNSANSI ZEKA VE REFLEKS KARARI:")
    if reflex_active and approaching_candidate:
        tid_str = approaching_candidate.track_id.replace("track_", "#")
        lines.append(f"• Robot Kafa Durumu:   👉 [KÖR NOKTA REFLEKSİ AKTİF] -> Hedef: {target_yaw:+.1f}°")
        lines.append(f"• Tetikleyen Varlık:   {tid_str} ({approaching_candidate.azimuth_deg:+.1f}°, {approaching_candidate.distance_m:.2f}m, Hız: {approaching_candidate.velocity_mps:+.2f} m/s)")
        lines.append(f"• Gerekçe:             Varlık sol/sağ kör noktadan robota doğru yaklaşıyor!")
        lines.append(f"• Robot Eylemi:        Kafa o yöne merakla çevriliyor; kamera açısına girince yüz aranacak.")
    else:
        lines.append("• Robot Kafa Durumu:   [IDLE / SABİT (0.0°)]")
        if tracks:
            lines.append("• Gerekçe:             Çevredeki tüm nesneler durgun (hız < 0.15 m/s). Duvar veya eşya olarak")
            lines.append("                       değerlendirildi; gereksiz yere kafa çevrilmeyip enerji/motor korunuyor.")
        else:
            lines.append("• Gerekçe:             Kör noktada veya çevrede yaklaşan hiçbir varlık yok.")
        lines.append("• Kör Nokta Alarmı:    PASİF (Biri kör noktadan robota doğru yürümeye başladığında aktif olur).")
    lines.append("-" * 88)
    lines.append("📖 HIZLI LEJANT / SİMGE KILAVUZU:")
    lines.append("• ▲: Robot (Öne bakar: 0°)   | °: Metre halkaları (1m, 2m, 3m)  | ·: Eksen çizgisi")
    lines.append("• Sayılar (1, 2..): Nesnenin haritadaki tam konumu               | ⚡: Robota doğru yürüyen insan")
    lines.append("• Açı: (+) = SOL taraf, (-) = SAĞ taraf                         | Hız: (-) = Yaklaşıyor, (+) = Uzaklaşıyor")
    lines.append("• Refleks: Sadece kör noktadan (25°-70°) robota yaklaşanlar kafa merak refleksini tetikler.")
    lines.append("=" * 88)

    return "\n".join(lines)


def run_simulation():
    print("=" * 88)
    print("🛰️  ASTRO RADAR (LiDAR) SPATIAL INTELLIGENCE SIMULATION")
    print("=" * 88)
    print("Bu simülasyon, donanım olmadan algoritmanın nasıl çalıştığını gösterir:")
    print("1. Çevrede sabit bir duvar (#3) ve sabit bir masa (#59) bulunur.")
    print("2. Sol kör noktadan (+55° açıyla) bir insan (#47) robota doğru yaklaşır (2.5m -> 1.3m).")
    print("3. Algoritma durgun nesneleri eler, yaklaşan kişiyi ve hızını anında yakalar.")
    print("=" * 88)
    time.sleep(1.0)

    tracker = LidarTracker()

    # Approaching person distances over 4 frames
    trajectory = [2.5, 2.1, 1.7, 1.3]
    t_start = 100.0

    for step, person_dist in enumerate(trajectory):
        t_current = t_start + (step * 0.5)

        # Generate 360-degree synthetic scan
        ranges = [8.0] * 360
        # 1. Stationary wall at +126° (0.85m)
        w_idx = int(round(180 + 126.4))
        for o in [-2, -1, 0, 1, 2]:
            ranges[(w_idx + o) % 360] = 0.85 + (abs(o) * 0.01)

        # 2. Approaching human at +55° (person_dist)
        h_idx = int(round(180 + 55.0))
        for o in [-2, -1, 0, 1, 2]:
            ranges[(h_idx + o) % 360] = person_dist + (abs(o) * 0.02)

        tracker.process_scan(
            ranges=ranges,
            angle_min=-math.pi,
            angle_increment=math.radians(1.0),
            timestamp=t_current,
        )
        tracks = tracker.get_active_tracks()

        # Render clean dashboard
        dashboard = render_radar_dashboard(
            tracks=tracks,
            scan_hz=10.0,
            source_name="SİMÜLASYON",
            max_range_m=3.5,
        )
        print("\033[H\033[J", end="")  # Clear screen ANSI
        print(f"[ADIM {step + 1} / {len(trajectory)}]")
        print(dashboard)
        time.sleep(1.5)

    print("\n🎉 Simülasyon başarıyla tamamlandı!")


def run_live(flip: bool = False):
    try:
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import qos_profile_sensor_data
        from sensor_msgs.msg import LaserScan
    except ImportError:
        print("[HATA] rclpy kütüphanesi bulunamadı. ROS 2 ortamını kaynaklayın: source /opt/ros/humble/setup.bash")
        sys.exit(1)

    rclpy.init()
    tracker = LidarTracker()

    class LidarVisualizerNode(Node):
        def __init__(self):
            super().__init__("lidar_intelligence_visualizer")
            self.create_subscription(LaserScan, "/scan", self.on_scan, qos_profile_sensor_data)
            self.last_print = 0.0
            self.msg_count = 0
            self.last_scan_time = time.monotonic()
            self.estimated_hz = 10.0
            self.get_logger().info("Canlı /scan konusu dinleniyor (QoS: sensor_data)...")
            self.diag_timer = self.create_timer(4.0, self._check_first_scan)

        def _check_first_scan(self):
            if self.msg_count == 0:
                self.get_logger().warning(
                    "⚠️  Hala /scan verisi gelmedi. Kontrol adımları:\n"
                    "   1. 'ros2 topic list' çıktısında /scan var mı?\n"
                    "   2. 'ros2 node list' çıktısında rplidar_node çalışıyor mu?\n"
                    "   3. 'ls -l /dev/ttyUSB*' ile lidar port izinlerini kontrol edin (sudo chmod 666 /dev/ttyUSB*)"
                )

        def on_scan(self, msg: LaserScan):
            now = time.monotonic()
            self.msg_count += 1
            dt = now - self.last_scan_time
            self.last_scan_time = now
            if dt > 0:
                self.estimated_hz = 0.9 * self.estimated_hz + 0.1 * (1.0 / dt)

            # Limit console refresh to ~2Hz (every 0.5s) for smooth, non-flickering display
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

            if flip:
                for tr in tracks:
                    tr.azimuth_deg = -tr.azimuth_deg
                    tr.current_y = -tr.current_y

            src_label = "/scan (YÖN AYNALANDI [FLIP])" if flip else "/scan"
            dashboard = render_radar_dashboard(
                tracks=tracks,
                scan_hz=self.estimated_hz,
                source_name=src_label,
                max_range_m=3.5,
            )

            # Clear screen ANSI and print dashboard
            print("\033[H\033[J", end="")
            print(dashboard)

    node = LidarVisualizerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("\nRadar monitöründen çıkış yapıldı.")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASTRO Radar Intelligence Dashboard")
    parser.add_argument("--sim", action="store_true", help="Simülasyon modunu çalıştır (donanımsız masabaşı testi)")
    parser.add_argument("--live", action="store_true", help="Canlı ROS 2 /scan konusunu dinle")
    parser.add_argument("--flip", action="store_true", help="Sağ ve sol yönleri tersine çevir (Ayna tersliği düzeltmesi)")
    args = parser.parse_args()

    if args.live:
        run_live(flip=args.flip)
    else:
        run_simulation()
