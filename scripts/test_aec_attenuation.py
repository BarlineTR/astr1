import sounddevice as sd
import numpy as np
import time
import math

print("=" * 65)
print("  ASTRO V1 — RESPEAKER HARDWARE AEC & ATTENUATION TEST")
print("=" * 65)

sample_rate = 16000
duration_s = 2.5
tone_duration_s = 1.0
pre_silence_s = 0.5
device_idx = 0  # ReSpeaker (hw:0,0)

# Generate 1.0s tone at 1000 Hz, with 20ms fade in/out
n_tone_samples = int(tone_duration_s * sample_rate)
t = np.linspace(0, tone_duration_s, n_tone_samples, endpoint=False)
envelope = np.ones(n_tone_samples, dtype=np.float32)
ramp = int(0.02 * sample_rate)
envelope[:ramp] = np.linspace(0, 1, ramp)
envelope[-ramp:] = np.linspace(1, 0, ramp)
tone = (np.sin(2 * np.pi * 1000 * t) * envelope * 20000.0).astype(np.int16)

# Create 2-channel playback audio: pre-silence (0.5s) + tone (1.0s) + post-silence (1.0s)
n_total_samples = int(duration_s * sample_rate)
playback_audio = np.zeros((n_total_samples, 2), dtype=np.int16)
start_sample = int(pre_silence_s * sample_rate)
playback_audio[start_sample:start_sample + n_tone_samples, 0] = tone
playback_audio[start_sample:start_sample + n_tone_samples, 1] = tone

print(f"Starting simultaneous 2-ch playback and 6-ch recording on Device [{device_idx}]...")
rec_data = sd.playrec(playback_audio, samplerate=sample_rate, channels=6, device=device_idx, dtype="int16")
sd.wait()

print("Processing recorded multi-channel PCM...")
# Channels: (n_total_samples, 6)
# 1. Pre-silence ambient baseline (0.1s to 0.4s)
ambient_start = int(0.1 * sample_rate)
ambient_end = int(0.4 * sample_rate)
ambient_rms = [
    float(np.sqrt(np.mean(rec_data[ambient_start:ambient_end, ch].astype(np.float32) ** 2)))
    for ch in range(6)
]

# 2. During tone playback (0.6s to 1.4s)
tone_active_start = int(0.6 * sample_rate)
tone_active_end = int(1.4 * sample_rate)
during_rms = [
    float(np.sqrt(np.mean(rec_data[tone_active_start:tone_active_end, ch].astype(np.float32) ** 2)))
    for ch in range(6)
]
during_peaks = [
    int(np.max(np.abs(rec_data[tone_active_start:tone_active_end, ch])))
    for ch in range(6)
]

print("\n--- KANAL DETAYLARI (Sessizlik vs Çalma) ---")
for ch in range(6):
    print(f"  Channel {ch}: Ambient RMS = {ambient_rms[ch]:.1f}, During RMS = {during_rms[ch]:.1f}, Peak = {during_peaks[ch]}")

# Attenuation
attenuation_db = 20.0 * math.log10(max(1.0, ch1_tone) / max(1.0, ch0_tone)) if ch0_tone > 0 else 0.0

# 3. Residual Echo Decay Duration
# Find when Ch0 drops below (ambient_rms[0] * 1.15 or ambient + 15)
decay_search_start = start_sample + n_tone_samples
window_size = int(0.01 * sample_rate)  # 10ms windows
threshold = max(ambient_rms[0] * 1.20, ambient_rms[0] + 15.0)
tail_samples = 0

for idx in range(decay_search_start, n_total_samples - window_size, window_size):
    win_rms = float(np.sqrt(np.mean(rec_data[idx:idx + window_size, 0].astype(np.float32) ** 2)))
    if win_rms <= threshold:
        tail_samples = idx - decay_search_start
        break
else:
    tail_samples = n_total_samples - decay_search_start

tail_ms = (tail_samples / float(sample_rate)) * 1000.0

print("\n" + "=" * 65)
print("  📊 RESPEAKER AEC & RESIDUAL ECHO GERÇEK ÖLÇÜM SONUÇLARI")
print("=" * 65)
print(f"  Ch 0 (AEC Processed) Taban Gürültüsü : {ambient_rms[0]:.1f} RMS")
print(f"  Ch 1 (Ham Mikrofon)  Taban Gürültüsü : {ambient_rms[1]:.1f} RMS")
print("-" * 65)
print(f"  Ch 5 (Loopback Referansı) Çalma Gücü : {ch5_tone:.1f} RMS (Peak: {during_peaks[5]})")
print(f"  Ch 1 (Ham Mikrofon) Hoparlör Algısı  : {ch1_tone:.1f} RMS (Peak: {during_peaks[1]})")
print(f"  Ch 0 (AEC Süzülmüş) Çıkış Sinyali    : {ch0_tone:.1f} RMS (Peak: {during_peaks[0]})")
print("-" * 65)
print(f"  🎯 Gerçek Donanım AEC Attenuation   : {attenuation_db:+.2f} dB")
print(f"  ⏱️ Gerçek Residual Echo Tail Süresi : {tail_ms:.1f} ms")
print(f"  Loopback Referans Kanalı Durumu      : {'✅ AKTİF (Ch5 PCM mevcut)' if ch5_tone > 100 else '❌ PASİF (Ch5 sessiz)'}")
print("=" * 65)
