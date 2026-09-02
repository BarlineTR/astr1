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
            print("  ❌ OAK-D kamerası USB'de bulunamadı (Başka bir süreç kamerayı açık tutuyor olabilir)!")
            return None
        for dev in devices:
            print(f"  • Cihaz Adı  : {dev.name}")
            print(f"  • MxId        : {dev.getMxId()}")
            print(f"  • Durum       : {dev.state}")
            print(f"  • Protokol    : {dev.protocol}")
        
        # Test connection speed
        with dai.Device() as device:
            usb_speed = device.getUsbSpeed()
            print(f"\n  🎯 BAĞLANTI HIZI: \033[1;36m{usb_speed.name}\033[0m")
            if "HIGH" in usb_speed.name or "2" in usb_speed.name:
                print("  ⚠️  DİKKAT: Kamera USB 2.0 (High Speed - 480 Mbps) modunda çalışıyor!")
                print("      Nedenler:")
                print("      1. Kablo: Tip-C şarj kabloları yalnızca 480 Mbps destekler (USB 3.0 SuperSpeed veri kablosu gerekir).")
                print("      2. Port : Jetson üzerindeki mavi renkli USB 3.0 portuna takılı olmayabilir.")
                print("      3. Hub  : Araya takılan çoklayıcı USB 2.0 hızına düşürüyor olabilir.")
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
        print("Kamera donanımında doğrudan 100 karelik test akışı başlatılıyor...")
        
        pipeline = dai.Pipeline()
        
        # Support both DepthAI v2 / v3 method signatures
        if hasattr(pipeline, "createColorCamera"):
            cam_rgb = pipeline.createColorCamera()
        else:
            cam_rgb = pipeline.create(dai.node.ColorCamera)

        cam_rgb.setResolution(dai.ColorCameraProperties.SensorResolution.THE_720_P)
        cam_rgb.setFps(30)
        cam_rgb.setInterleaved(False)
        cam_rgb.setColorOrder(dai.ColorCameraProperties.ColorOrder.BGR)

        if hasattr(pipeline, "createXLinkOut"):
            xout = pipeline.createXLinkOut()
        elif hasattr(dai.node, "XLinkOut"):
            xout = pipeline.create(dai.node.XLinkOut)
        else:
            xout = pipeline.createXLinkOut()

        xout.setStreamName("video")
        cam_rgb.video.link(xout.input)

        with dai.Device(pipeline) as device:
            usb_speed = device.getUsbSpeed()
            print(f"  • Cihaz USB Hızı: {usb_speed.name}")
            q = device.getOutputQueue(name="video", maxSize=4, blocking=False)
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
                print(f"  ⚠️ Kamera donanım seviyesinde {fps:.1f} FPS veriyor (Kablo bant genişliği kısıtlı).")
    except Exception as e:
        print(f"  Doğrudan test notu: {e}")

if __name__ == "__main__":
    print("=" * 70)
    print("       ASTRO ROBOT — OAK-D KAMERA VE USB DONANIM TEŞHİS ARACI")
    print("=" * 70)
    check_usb_link()
    test_native_hardware_fps()
    print("\n" + "=" * 70 + "\n")
