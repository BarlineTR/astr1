#!/usr/bin/env python3
"""ASTRO V1 — Camera Hardware, USB Link Speed & Pipeline Diagnostic Tool.

Checks:
  1. Physical USB Port & Cable Link Speed (USB 2.0 480Mbps vs USB 3.0 5Gbps)
  2. DepthAI Direct Hardware Pipeline FPS (without ROS 2 queue overhead)
"""

import os
import subprocess
import sys
import time

def print_header(title):
    print("\n" + "=" * 70)
    print(f"   {title}")
    print("=" * 70)

def check_usb_link():
    print_header("1. FİZİKSEL USB PORT VE KABLO HIZI KONTROLÜ")
    
    # 1. Check via lsusb -t
    try:
        res = subprocess.run(["lsusb", "-t"], capture_output=True, text=True, timeout=3)
        print("[lsusb -t çıktısı]:")
        for line in res.stdout.strip().split("\n"):
            if "Class=" in line or "Driver=" in line or "Dev" in line:
                print("  " + line)
    except Exception as e:
        print(f"  lsusb çalıştırılamadı: {e}")

    # 2. Check DepthAI USB speed enumeration
    print("\n[DepthAI Donanım Tanımlama]:")
    try:
        import depthai as dai
        devices = dai.Device.getAllAvailableDevices()
        if not devices:
            print("  ❌ OAK-D kamerası USB'de bulunamadı (Sensors launch açık olabilir, durdurun)!")
            return None
        for dev in devices:
            print(f"  • Cihaz Adı  : {getattr(dev, 'name', str(dev))}")
            dev_id = getattr(dev, 'deviceId', getattr(dev, 'mxid', getattr(dev, 'name', 'N/A')))
            print(f"  • Device ID  : {dev_id}")
            print(f"  • Protokol   : {getattr(dev, 'protocol', 'USB')}")
        
        # Test connection speed
        with dai.Device() as device:
            usb_speed = device.getUsbSpeed()
            print(f"\n  🎯 BAĞLANTI HIZI: \033[1;36m{usb_speed.name}\033[0m")
            if "HIGH" in usb_speed.name or "2" in usb_speed.name:
                print("  ⚠️  DİKKAT: Kamera USB 2.0 (High Speed - 480 Mbps) modunda çalışıyor!")
                print("      Neden: Kullanılan Type-C kablosu 4-telli telefon şarj kablosudur.")
                print("      Çözüm: camera_params.yaml içindeki i_low_bandwidth: true donanımsal sıkıştırma modu bu kabloda 30 FPS sağlayacaktır.")
            elif "SUPER" in usb_speed.name or "3" in usb_speed.name:
                print("  ✅ MÜKEMMEL: Kamera USB 3.0 / SuperSpeed (5 Gbps) modunda tam bant genişliğinde bağlı.")
            return usb_speed.name
    except ImportError:
        print("  depthai python kütüphanesi bulunamadı.")
    except Exception as e:
        print(f"  DepthAI bağlantı testi notu: {e}")
    return None

def test_native_hardware_fps():
    print_header("2. SAF DONANIM AKIŞ HIZI TESTİ (ROS 2 HARİÇ)")
    try:
        import depthai as dai
        print("Kamera donanımında doğrudan test akışı başlatılıyor...")
        
        pipeline = dai.Pipeline()
        
        # DepthAI 3.x Native Camera API
        pipeline = dai.Pipeline()
        cam = pipeline.create(dai.node.Camera)
        if hasattr(cam, "setSize"):
            cam.setSize(1280, 720)
        if hasattr(cam, "setFps"):
            cam.setFps(30)

        with dai.Device(pipeline) as device:
            usb_speed = device.getUsbSpeed()
            print(f"  • Cihaz USB Hızı: \033[1;36m{usb_speed.name}\033[0m")
            
            # DepthAI 3 queue discovery
            queue_name = None
            if hasattr(device, "getOutputQueueNames"):
                q_names = device.getOutputQueueNames()
                queue_name = q_names[0] if q_names else None
            if not queue_name:
                queue_name = "camera"

            try:
                q = device.getOutputQueue(name=queue_name, maxSize=4, blocking=False)
            except Exception:
                q = device.getOutputQueue(name=device.getOutputQueueNames()[0], maxSize=4, blocking=False)

            t_start = time.monotonic()
            frames = 0
            while frames < 90 and (time.monotonic() - t_start < 4.0):
                frame = q.get()
                if frame is not None:
                    frames += 1
            dt = time.monotonic() - t_start
            fps = frames / max(0.01, dt)
            
            print(f"\n  📊 Donanım Saf FPS : \033[1;32m{fps:.1f} FPS\033[0m ({frames} kare / {dt:.2f}s)")
            if fps >= 24.0:
                print("  ✅ Kamera donanımı ve VPU çipi 30 FPS üretme yeteneğine tam sahip!")
            else:
                print(f"  ⚠️ Kamera donanım seviyesinde {fps:.1f} FPS veriyor (USB 2.0 480 Mbps kablo limiti).")
    except Exception as e:
        print(f"  Doğrudan test hatası: {e}")

if __name__ == "__main__":
    print("=" * 70)
    print("       ASTRO ROBOT — OAK-D KAMERA VE USB DONANIM TEŞHİS ARACI")
    print("=" * 70)
    check_usb_link()
    test_native_hardware_fps()
    print("\n" + "=" * 70 + "\n")
