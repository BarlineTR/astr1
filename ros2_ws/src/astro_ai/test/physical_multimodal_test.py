"""
Jetson fiziksel multi-person test script.

Gerçek OAK-D Lite + ReSpeaker + voice/face modelleri üzerinde
Senaryo A-H'yi çalıştırır ve tüm fusion metriklerini loglar.

Kullanım (Jetson üzerinde):
  cd /home/okistech/Desktop/astr1/ros2_ws
  source /opt/ros/humble/setup.bash && source install/setup.bash
  python3 src/astro_ai/test/physical_multimodal_test.py
"""

import os
import sys
import json
import time
import signal
import threading
from typing import Dict, Any, Optional

# Ensure ROS2 environment is sourced before running
try:
    import rclpy
    from rclpy.node import Node
    from std_msgs.msg import String, Float32, Bool
except ImportError:
    print("ERROR: rclpy not available. Run with sourced ROS2 environment.")
    sys.exit(1)


BANNER = """
╔═══════════════════════════════════════════════════════════════════╗
║         ASTRO PHYSICAL MULTI-PERSON FUSION TEST                   ║
║         Scenarios A through H                                     ║
╚═══════════════════════════════════════════════════════════════════╝
"""

SCENARIOS = [
    ("A", "Sadece Baran konuşuyor. active_speaker=Baran bekleniyor."),
    ("B", "Sadece Oktay konuşuyor. active_speaker=Oktay bekleniyor."),
    ("C", "Baran kamerada, Oktay konuşuyor. active_speaker!=Baran bekleniyor."),
    ("D", "Oktay kamerada, Baran konuşuyor. active_speaker!=Oktay bekleniyor."),
    ("E", "Baran + Oktay aynı kadraja, sırayla konuşuyor. İki ayrı speaker geçişi bekleniyor."),
    ("F", "Baran + Unknown kişi. Unknown konuşuyor. active_speaker=Misafir bekleniyor."),
    ("G", "İki kişi benzer açı, farklı depth. DOA identity prior seçim yapmalı."),
    ("H", "Face identity = Baran, Voice identity = Oktay → AMBIGUOUS/CONFLICT bekleniyor."),
]


class PhysicalTestNode(Node):
    def __init__(self):
        super().__init__("physical_test_listener")
        self.fusion_results = []
        self._current_scenario = "?"
        self._lock = threading.Lock()

        # Subscribe to vision/faces topic
        self.sub_faces = self.create_subscription(
            String, "/vision/faces", self._on_faces, 10
        )
        # Subscribe to /audio/doa topic
        self.sub_doa = self.create_subscription(
            Float32, "/audio/doa", self._on_doa, 10
        )
        # Subscribe to /audio/speaker_id topic
        self.sub_speaker = self.create_subscription(
            String, "/audio/speaker_id", self._on_speaker_id, 10
        )

        self._last_doa = None
        self._last_faces = []
        self._last_speaker = None

        self.get_logger().info("PhysicalTestNode started. Listening to /vision/faces, /audio/doa, /audio/speaker_id")

    def _on_faces(self, msg: String):
        try:
            data = json.loads(msg.data or "[]")
            with self._lock:
                self._last_faces = data if isinstance(data, list) else []
        except Exception:
            pass

    def _on_doa(self, msg: Float32):
        with self._lock:
            self._last_doa = float(msg.data)

    def _on_speaker_id(self, msg: String):
        try:
            raw = (msg.data or "").strip()
            if raw.startswith("{"):
                data = json.loads(raw)
            else:
                is_k = raw.lower() not in ("misafir", "unknown", "none", "")
                data = {"name": raw if is_k else "Misafir", "confidence": 0.9 if is_k else 0.0, "is_known": is_k}
            with self._lock:
                self._last_speaker = data
        except Exception:
            pass

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "scenario": self._current_scenario,
                "timestamp": time.strftime("%H:%M:%S"),
                "DOA": self._last_doa,
                "faces": list(self._last_faces),
                "speaker_id": dict(self._last_speaker) if self._last_speaker else None,
            }

    def set_scenario(self, label: str):
        with self._lock:
            self._current_scenario = label

    def log_snapshot(self):
        snap = self.get_snapshot()
        print(f"\n─── SCENARIO {snap['scenario']} — {snap['timestamp']} ─────────────────────────────────────────")
        print(f"  DOA                : {snap['DOA']}")
        faces = snap["faces"]
        if faces:
            for i, f in enumerate(faces):
                print(f"  [Face {i+1}]")
                print(f"    track_id         : {f.get('track_id')}")
                print(f"    depth_m          : {f.get('distance_m')}")
                print(f"    bearing_deg      : {f.get('camera_azimuth_deg') or f.get('head_yaw_deg')}")
                print(f"    face_identity    : {f.get('recognized_name') or f.get('name')}")
                print(f"    face_confidence  : {f.get('confidence')}")
                print(f"    looking_at_robot : {f.get('looking_at_robot')}")
        else:
            print("  [Faces] None detected")

        spk = snap["speaker_id"]
        if spk:
            print(f"  voice_identity     : {spk.get('name')}")
            print(f"  voice_confidence   : {spk.get('confidence')}")
        else:
            print("  voice_identity     : (not received yet)")

        # Attempt to read [ACTIVE SPEAKER FUSION] from astro_realtime_node topic (if published)
        print("  → (See /astro/realtime_node logs for ACTIVE SPEAKER FUSION / identity_certainty / spatial_score / depth_score)")

        self.fusion_results.append(snap)


def run_physical_test():
    rclpy.init()
    node = PhysicalTestNode()
    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    print(BANNER)
    print("ROS2 topics being monitored:")
    print("  /vision/faces    — OAK-D Lite + YuNet face detections with depth and bearing")
    print("  /audio/doa       — ReSpeaker HID DOA (signed head-relative body yaw)")
    print("  /audio/speaker_id — Voice identity from WeSpeaker ResNet-34 ONNX\n")
    print("NOTE: Ensure astro_realtime_node is running to see [ACTIVE SPEAKER FUSION] logs.\n")

    input("Press ENTER to start...\n")

    for label, description in SCENARIOS:
        print(f"\n{'='*72}")
        print(f"SENARYO {label}: {description}")
        print(f"{'='*72}")
        node.set_scenario(label)

        if label == "G":
            print("\n[G] İki kişi benzer açıda konuşmacı olarak yaklaşsın.")
            print("    DOA'nın voice identity prior sayesinde doğru kişiyi seçtiğini kanıtla.")
            print("    (yakın kişi değil, sesi tanınan kişi seçilmeli)")

        if label == "H":
            print("\n[H] CONFLICT testi: Bir kişinin yüzü Baran, sesi Oktay ile karışırsa.")
            print("    Beklenen: identity_certainty=AMBIGUOUS/CONFLICT, active_speaker=Misafir")

        if label == "E":
            print("\n[E] Baran ve Oktay sırayla konuşsun. İlk geçişi ve ikinci geçişi ayrı göster.")
            print("    STEP 1: Baran konuşuyor...")
            input("  → Baran konuşmaya başladığında ENTER'a bas: ")
            time.sleep(2.0)
            node.log_snapshot()

            print("\n  STEP 2: Oktay konuşuyor...")
            input("  → Oktay konuşmaya başladığında ENTER'a bas: ")
            time.sleep(2.0)
            node.log_snapshot()
            continue

        wait_s = 4.0
        print(f"\n[Senaryo {label}] {wait_s}s bekleniyor...")
        input(f"  → Senaryo hazır olduğunda ENTER'a bas: ")
        time.sleep(wait_s)
        node.log_snapshot()

    print(f"\n{'='*72}")
    print("Tüm senaryolar tamamlandı.")
    print(f"Toplam {len(node.fusion_results)} snapshot kaydedildi.")
    print("\nSonuçlar JSON'a kaydediliyor...")

    output_path = "/tmp/astro_physical_test_results.json"
    with open(output_path, "w") as f:
        json.dump(node.fusion_results, f, indent=2, ensure_ascii=False)
    print(f"  Sonuçlar: {output_path}")

    print("\n[KOORDİNAT KALİBRASYON NOTU]")
    print("  ReSpeaker DOA kalibrasyon verisi (respeaker_doa_calibration.json):")
    print("    physical_deg=0°   → mean_signed_deg=0.45°  (offset: +0.45°)")
    print("    physical_deg=+30° → mean_signed_deg=30.31° (offset: +0.31°)")
    print("    physical_deg=-30° → mean_signed_deg=-29.69° (offset: +0.31°)")
    print("  OAK-D kamera optik açısı: azimuth = -norm_u * (HFOV/2) = -norm_u * 36°")
    print("    İki frame de REP-103 uyumlu; merkez 0°, sol +, sağ -")
    print("  Ölçülen sabit DOA offset: ~+0.3° ile +0.5° arasında (kalibrasyonda mevcut)")
    print("  Bu offset angular_gate=28° içinde kalıyor, düzeltme GEREKMEZ.")

    rclpy.shutdown()


if __name__ == "__main__":
    run_physical_test()
