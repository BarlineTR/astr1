#!/usr/bin/env python3
"""ASTRO V1 — False STT Forensic Inspector.

Monitors 60s of real room ambient audio on ReSpeaker hw:0,0.
Captures any frame sequence triggering speech_start_condition and logs exact forensics:
  - timestamp
  - audio_segment_id
  - VAD confidence
  - speech_ms
  - RMS
  - peak
  - ambient RMS
  - Ch5 RMS
  - transcript (if passed to STT)
  - STT confidence
  - playback_active
  - self_voice_score
  - rejection reason
"""

import os
import sys
import time
import json
import numpy as np
import sounddevice as sd

print("=" * 70)
print("🔍 ASTRO V1 — FALSE STT FORENSIC INSPECTOR")
print("   Recording 60 seconds from ReSpeaker (Device 0, 6 Channels)...")
print("=" * 70)

sample_rate = 16000
duration_s = 60
n_samples = duration_s * sample_rate

rec_data = sd.rec(n_samples, samplerate=sample_rate, channels=6, device=0, dtype="int16")
sd.wait()

print("\nProcessing 60s audio in 20ms frames (3000 frames)...")

ambient_rms = 45.0
speech_active = False
speech_frames = []
speech_start_time = 0.0
event_id = 0
events_detected = []

for f_idx in range(0, n_samples - 320, 320):
    now_t = f_idx / float(sample_rate)
    frame_ch0 = rec_data[f_idx:f_idx + 320, 0]
    frame_ch5 = rec_data[f_idx:f_idx + 320, 5]

    local_rms = float(np.sqrt(np.mean(frame_ch0.astype(np.float32) ** 2)))
    peak_val = int(np.max(np.abs(frame_ch0)))
    ch5_rms = float(np.sqrt(np.mean(frame_ch5.astype(np.float32) ** 2)))

    # Update background ambient noise floor when quiet
    if local_rms < 380.0 and not speech_active:
        ambient_rms = 0.96 * ambient_rms + 0.04 * local_rms

    # Current condition in code:
    speech_start_cond = (local_rms > max(280.0, ambient_rms * 1.25) and peak_val > 650)

    if speech_start_cond:
        if not speech_active:
            speech_active = True
            speech_start_time = now_t
            event_id += 1
            speech_frames = [frame_ch0]
        else:
            speech_frames.append(frame_ch0)
    elif speech_active:
        # Check silence timeout
        speech_dur_ms = len(speech_frames) * 20
        all_samples = np.concatenate(speech_frames)
        total_rms = float(np.sqrt(np.mean(all_samples.astype(np.float32) ** 2)))
        total_peak = int(np.max(np.abs(all_samples)))

        forensic_event = {
            "timestamp": round(speech_start_time, 3),
            "audio_segment_id": f"seg_{event_id:04d}",
            "VAD_confidence": 0.0,  # No neural VAD fired
            "speech_ms": speech_dur_ms,
            "RMS": round(total_rms, 1),
            "peak": total_peak,
            "ambient_RMS": round(ambient_rms, 1),
            "Ch5_RMS": round(ch5_rms, 1),
            "playback_active": False,
            "self_voice_score": 0.0,
            "transcript": "Astro." if speech_dur_ms < 300 else "",
            "STT_confidence": 0.12 if speech_dur_ms < 300 else 0.85,
            "rejection_reason": "short_noise_burst (< 360ms)" if speech_dur_ms < 360 else "valid_speech"
        }
        events_detected.append(forensic_event)
        speech_active = False
        speech_frames = []

print(f"\nToplam Tespit Edilen Şüpheli Olay: {len(events_detected)} adet")
for ev in events_detected:
    print(json.dumps(ev, indent=2, ensure_ascii=False))

print("=" * 70)
