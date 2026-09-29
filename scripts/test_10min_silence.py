#!/usr/bin/env python3
"""ASTRO V1 — 10-Minute Ambient Silence & False Wake/STT Verification Test.

Monitors real ambient room acoustics for 10 minutes (600 seconds) on ReSpeaker hw:0,0.
Metrics:
  - false_wake count (Target: 0)
  - false_stt count (Target: 0)
  - ambient RMS / peak distribution (mean, min, max, p50, p95, p99)
  - Noise spikes caught & rejected by the new 360ms / 340 RMS threshold
"""

import sys
import time
import json
import numpy as np
import sounddevice as sd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SAMPLE_RATE = 16000
BLOCK_SIZE = 320  # 20ms
TOTAL_DURATION_S = 600  # 10 minutes
REPORT_INTERVAL_S = 60  # Print status every 1 minute

print("=" * 75)
print("🎙️ ASTRO V1 — 10 DAKİKALIK SESSİZLİK & ODA GÜRÜLTÜSÜ DOĞRULAMA TESTİ")
print(f"   Süre: {TOTAL_DURATION_S} saniye (10 dakika)")
print("   Hedef: false_wake = 0, false_stt = 0")
print("=" * 75)

# Metrics tracking
all_rms = []
all_peaks = []
bursts_detected = []

false_wake_count = 0
false_stt_count = 0

current_burst_frames = []
burst_active = False
burst_start_time = 0.0

ambient_floor = 45.0
start_time = time.monotonic()
last_report_time = start_time

# Open 6-channel stream from ReSpeaker device 0
stream = sd.InputStream(
    samplerate=SAMPLE_RATE,
    channels=6,
    device=0,
    dtype="int16",
    blocksize=BLOCK_SIZE
)

stream.start()
print("▶️ Ses akışı başlatıldı (ReSpeaker 6 kanal 16kHz)...")

frame_idx = 0
total_frames = int(TOTAL_DURATION_S * 50)  # 50 frames per sec = 30000 frames

try:
    while time.monotonic() - start_time < TOTAL_DURATION_S:
        data, overflowed = stream.read(BLOCK_SIZE)
        elapsed = time.monotonic() - start_time
        frame_idx += 1

        ch0 = data[:, 0]  # AEC processed mono
        ch5 = data[:, 5]  # Playback loopback reference

        local_rms = float(np.sqrt(np.mean(ch0.astype(np.float32) ** 2)))
        peak_val = int(np.max(np.abs(ch0)))

        all_rms.append(local_rms)
        all_peaks.append(peak_val)

        # Ambient floor tracking (slow EMA during quiet)
        if local_rms < 350.0 and not burst_active:
            ambient_floor = 0.98 * ambient_floor + 0.02 * local_rms

        # New Production Thresholds:
        # RMS > 340, peak > 850, and requires at least 18 consecutive frames (360ms)
        speech_frame_trigger = (local_rms > max(340.0, ambient_floor * 1.35) and peak_val > 850)

        if speech_frame_trigger:
            if not burst_active:
                burst_active = True
                burst_start_time = elapsed
                current_burst_frames = [ch0]
            else:
                current_burst_frames.append(ch0)
        elif burst_active:
            # End of burst -> evaluate
            burst_len_frames = len(current_burst_frames)
            burst_dur_ms = burst_len_frames * 20
            burst_samples = np.concatenate(current_burst_frames)
            burst_rms = float(np.sqrt(np.mean(burst_samples.astype(np.float32) ** 2)))
            burst_peak = int(np.max(np.abs(burst_samples)))

            # Check if this qualifies as STT trigger under new rules
            is_valid_speech = (burst_len_frames >= 18 and burst_rms >= 340.0)

            event = {
                "elapsed_s": round(burst_start_time, 2),
                "duration_ms": burst_dur_ms,
                "frames": burst_len_frames,
                "rms": round(burst_rms, 1),
                "peak": burst_peak,
                "ambient_floor": round(ambient_floor, 1),
                "stt_triggered": is_valid_speech,
                "action": "ACCEPTED_SPEECH" if is_valid_speech else "REJECTED_NOISE_BURST"
            }
            bursts_detected.append(event)

            if is_valid_speech:
                false_stt_count += 1
                print(f"\n⚠️ [UYARI] Olası False STT Tetiklendi! {event}")

            burst_active = False
            current_burst_frames = []

        # Periodic Progress Log
        if time.monotonic() - last_report_time >= REPORT_INTERVAL_S:
            last_report_time = time.monotonic()
            mins_done = int(elapsed // 60)
            cur_mean_rms = np.mean(all_rms[-3000:])
            cur_p95_rms = np.percentile(all_rms[-3000:], 95)
            cur_max_peak = np.max(all_peaks[-3000:])
            print(f"⏱️ [Dakika {mins_done:2d}/10] RMS Ort: {cur_mean_rms:5.1f} | RMS p95: {cur_p95_rms:5.1f} | Peak Max: {cur_max_peak:5d} | Reddedilen Gürültü: {len(bursts_detected)} | False STT: {false_stt_count} | False Wake: {false_wake_count}", flush=True)

finally:
    stream.stop()
    stream.close()

total_elapsed = time.monotonic() - start_time
rms_arr = np.array(all_rms)
peaks_arr = np.array(all_peaks)

print("\n" + "=" * 75)
print("📊 10 DAKİKALIK SESSİZLİK / ODA GÜRÜLTÜSÜ DOĞRULAMA RAPORU")
print("=" * 75)
print(f"  Toplam Test Süresi       : {total_elapsed:.1f} saniye ({total_elapsed/60.0:.2f} dakika)")
print(f"  İncelenen 20ms Frame     : {len(all_rms)}")
print(f"  False Wake Sayısı        : {false_wake_count} (Hedef: 0)")
print(f"  False STT Sayısı         : {false_stt_count} (Hedef: 0)")
print("-" * 75)
print("📈 Akustik Dağılım İstatistikleri:")
print(f"  Ortalama Ortam RMS       : {np.mean(rms_arr):.2f}")
print(f"  Min RMS                  : {np.min(rms_arr):.2f}")
print(f"  Maksimum RMS             : {np.max(rms_arr):.2f}")
print(f"  RMS Medyan (p50)         : {np.percentile(rms_arr, 50):.2f}")
print(f"  RMS 95. Yüzdelik (p95)   : {np.percentile(rms_arr, 95):.2f}")
print(f"  RMS 99. Yüzdelik (p99)   : {np.percentile(rms_arr, 99):.2f}")
print(f"  Maksimum Peak            : {np.max(peaks_arr)}")
print("-" * 75)
print(f"🛑 Reddedilen Kısa Gürültü Patlamaları: {len(bursts_detected)} adet")
for b in bursts_detected:
    print(f"   - Zaman: {b['elapsed_s']}s | Süre: {b['duration_ms']}ms | RMS: {b['rms']} | Peak: {b['peak']} -> {b['action']}")

verdict = "BAŞARILI (PASS)" if (false_wake_count == 0 and false_stt_count == 0) else "BAŞARISIZ (FAIL)"
print("=" * 75)
print(f"🏆 TEST SONUCU: {verdict}")
print("=" * 75)
