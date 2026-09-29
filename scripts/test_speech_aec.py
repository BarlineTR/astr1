import sounddevice as sd
import numpy as np
import math

print("=" * 65)
print("  ASTRO V1 — REAL SPEECH PLAYBACK AEC ATTENUATION TEST")
print("=" * 65)

sample_rate = 16000
device_idx = 0  # ReSpeaker (hw:0,0)

# Generate synthetic speech-like multi-frequency audio (formants: 300Hz, 1200Hz, 2500Hz) with syllables
duration_s = 3.0
n_samples = int(duration_s * sample_rate)
t = np.linspace(0, duration_s, n_samples, endpoint=False)

# 4 syllables
envelope = np.zeros(n_samples, dtype=np.float32)
for i in range(4):
    start = int((0.5 + i * 0.5) * sample_rate)
    dur = int(0.35 * sample_rate)
    envelope[start:start+dur] = np.hanning(dur)

speech_sim = (
    0.5 * np.sin(2 * np.pi * 320 * t) +
    0.3 * np.sin(2 * np.pi * 1250 * t) +
    0.2 * np.sin(2 * np.pi * 2400 * t)
) * envelope * 22000.0
speech_sim = speech_sim.astype(np.int16)

# 2-channel playback buffer
playback_buf = np.stack([speech_sim, speech_sim], axis=1)

print(f"Playing 3.0s simulated speech and recording 6 channels on Device [{device_idx}]...")
rec_data = sd.playrec(playback_buf, samplerate=sample_rate, channels=6, device=device_idx, dtype="int16")
sd.wait()

# Analysis:
# 1. Pre-speech baseline (0.05s to 0.45s)
base_samples = rec_data[int(0.05 * sample_rate):int(0.45 * sample_rate), :]
ambient_rms = [float(np.sqrt(np.mean(base_samples[:, ch].astype(np.float32) ** 2))) for ch in range(6)]

# 2. Syllable 3 active period (1.55s to 1.80s)
active_samples = rec_data[int(1.55 * sample_rate):int(1.80 * sample_rate), :]
during_rms = [float(np.sqrt(np.mean(active_samples[:, ch].astype(np.float32) ** 2))) for ch in range(6)]
during_peaks = [int(np.max(np.abs(active_samples[:, ch]))) for ch in range(6)]

# 3. Post-speech decay period (after 2.5s)
post_start = int(2.55 * sample_rate)
post_samples = rec_data[post_start:, :]

# Measure decay on Ch0 and Ch1
window_size = int(0.02 * sample_rate)
ch0_tail_ms = 0
thresh = max(ambient_rms[0] * 1.25, ambient_rms[0] + 50.0)

for s in range(0, len(post_samples) - window_size, window_size):
    w_rms = float(np.sqrt(np.mean(post_samples[s:s + window_size, 0].astype(np.float32) ** 2)))
    if w_rms <= thresh:
        ch0_tail_ms = (s / float(sample_rate)) * 1000.0
        break
else:
    ch0_tail_ms = (len(post_samples) / float(sample_rate)) * 1000.0

ch0_tone = during_rms[0]
ch1_tone = during_rms[1]
ch5_loop = during_rms[5]
att_db = 20.0 * math.log10(max(1.0, ch1_tone) / max(1.0, ch0_tone)) if ch0_tone > 0 else 0.0

print("\n" + "=" * 65)
print("  📊 GERÇEK SPEECH AEC ÖLÇÜM SONUÇLARI")
print("=" * 65)
for ch in range(6):
    ch_name = "Ch 0 (AEC)" if ch == 0 else f"Ch {ch} (Mic)" if ch < 5 else "Ch 5 (Loopback)"
    print(f"  {ch_name:18}: Ambient={ambient_rms[ch]:6.1f} | Active={during_rms[ch]:7.1f} | Peak={during_peaks[ch]:5d}")
print("-" * 65)
print(f"  🎯 AEC Attenuation (Ch1 vs Ch0)      : {att_db:+.2f} dB")
print(f"  ⏱️ Post-Speech Echo Tail (Ch0 Sönüm) : {ch0_tail_ms:.1f} ms")
print(f"  Loopback Sinyal Varlığı              : {'✅ AKTİF' if ch5_loop > 100 else '❌ PASİF'}")
print("=" * 65)
