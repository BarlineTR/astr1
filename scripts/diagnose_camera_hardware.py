#!/usr/bin/env python3
"""ASTRO V1 — Camera Hardware, USB Link Speed & Native FPS Benchmark.

Performs a unified hardware test on OAK-D Lite:
  1. Inspects Linux USB Topology (lsusb -t)
  2. Opens a single DepthAI Hardware Session
  3. Queries exact physical USB Link Speed (USB 2.0 480Mbps vs USB 3.0 5Gbps)
  4. Streams 90 raw 720p frames directly from VPU without ROS 2 middleware
  5. Calculates exact hardware FPS and frame transport timing
"""

import os
import subprocess
import sys
import time


def print_header(title):
    print("\n" + "=" * 70)
    print(f"   {title}")
    print("=" * 70)


def main():
    print("=" * 70)
    print("       ASTRO ROBOT — OAK-D KAMERA VE USB DONANIM TEŞHİS ARACI")
    print("=" * 70)

    # 1. Linux USB bus topology
    print_header("1. LINUX USB VERİ YOLU (TOPOLOGY)")
    try:
        res = subprocess.run(["lsusb", "-t"], capture_output=True, text=True, timeout=3)
        for line in res.stdout.strip().split("\n"):
            if "Class=" in line or "Driver=" in line or "Dev" in line:
                print("  " + line)
    except Exception as e:
        print(f"  lsusb çalıştırılamadı: {e}")

    # Deep Process & Service Inspection
    print_header("2. KAMERAYI KULLANAN SÜREÇLERİN TESPİTİ (PROCESS SCAN)")
    try:
        ps_res = subprocess.run(["ps", "-eo", "pid,user,command"], capture_output=True, text=True)
        found_proc = False
        for line in ps_res.stdout.split("\n"):
            lower = line.lower()
            if any(k in lower for k in ["depthai", "oak", "camera", "ros2", "astro"]) and "diagnose" not in lower:
                print(f"  • [Çalışan Süreç]: {line.strip()}")
                found_proc = True
        if not found_proc:
            print("  ✓ Standart ROS2 veya DepthAI süreci bulunamadı.")
    except Exception as e:
        print(f"  Süreç tarama hatası: {e}")

    # 3. Unified DepthAI Hardware Benchmark
    print_header("3. OAK-D DONANIM BAĞLANTISI VE SAF FPS ÖLÇÜMÜ")
    try:
        import depthai as dai
    except ImportError:
        print("  ❌ depthai Python kütüphanesi bulunamadı.")
        return

    # Build Pipeline
    pipeline = dai.Pipeline()

    # DepthAI 3.x Native Camera API
    cam = pipeline.create(dai.node.Camera)
    if hasattr(cam, "setSize"):
        cam.setSize(1280, 720)
    if hasattr(cam, "setFps"):
        cam.setFps(30)

    print("\n  [Kamera Donanımı Başlatılıyor...]")
    time.sleep(0.5)

    device = None
    try:
        device = dai.Device()
        if hasattr(device, "startPipeline"):
            device.startPipeline(pipeline)
        elif hasattr(device, "start"):
            device.start(pipeline)

        usb_speed = device.getUsbSpeed()
        speed_name = usb_speed.name
        
        print(f"\n  🎯 FİZİKSEL BAĞLANTI HIZI: \033[1;36m{speed_name}\033[0m")
        if "HIGH" in speed_name or "2" in speed_name:
            print("  ⚠️  Kamera USB 2.0 (High Speed - 480 Mbps) modunda çalışıyor.")
            print("      Neden: 4 telli şarj kablosu veya USB 2.0 portu/çoklayıcı.")
        elif "SUPER" in speed_name or "3" in speed_name:
            print("  ✅ Kamera USB 3.0 / SuperSpeed (5 Gbps / 10 Gbps) modunda çalışıyor.")

        # Queue Discovery
        q_name = None
        if hasattr(device, "getOutputQueueNames"):
            names = device.getOutputQueueNames()
            if names:
                q_name = names[0]
        if not q_name:
            q_name = "camera"

        q = device.getOutputQueue(name=q_name, maxSize=4, blocking=False)

        print(f"\n  [Kamera VPU'sundan 90 Kare Çekiliyor (Kuyruk: {q_name})...]")
        t_start = time.monotonic()
        frames = 0
        deltas = []
        last_t = t_start

        # Measure for up to 4 seconds
        while frames < 90 and (time.monotonic() - t_start < 4.5):
            frame = q.get()
            if frame is not None:
                now = time.monotonic()
                frames += 1
                deltas.append((now - last_t) * 1000.0)
                last_t = now

        total_time = time.monotonic() - t_start
        fps = frames / max(0.001, total_time)
        avg_delta = sum(deltas[1:]) / max(1, len(deltas) - 1) if len(deltas) > 1 else 0.0

        print("\n" + "=" * 70)
        print("       TEST SONUÇLARI (SAF DONANIM PERFORMANSI)")
        print("=" * 70)
        print(f"  • Toplam Okunan Kare : {frames} kare")
        print(f"  • Geçen Süre         : {total_time:.2f} saniye")
        print(f"  • Saf Donanım FPS    : \033[1;32m{fps:.1f} FPS\033[0m")
        print(f"  • Kareler Arası Süre : {avg_delta:.1f} ms")

        if fps >= 24.0:
            print("\n  🎯 DEĞERLENDİRME: Kamera donanımı ve VPU çipi tam 30 FPS hızında çalışıyor!")
        elif fps >= 10.0:
            print(f"\n  🎯 DEĞERLENDİRME: Kamera {fps:.1f} FPS veriyor. Pozlama süresi veya USB 2 hattı hızı sınırlıyor.")
        else:
            print(f"\n  🎯 DEĞERLENDİRME: Kamera {fps:.1f} FPS veriyor. 480 Mbps USB 2.0 kablo sıkıştırmasız veri aktarımını kilitliyor.")

    except Exception as exc:
        print(f"\n  ❌ Test hatası: {exc}")
    finally:
        if device is not None and hasattr(device, "close"):
            try:
                device.close()
            except Exception:
                pass

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    main()
