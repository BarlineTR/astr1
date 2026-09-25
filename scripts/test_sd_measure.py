#!/usr/bin/env python3
"""Test capture via sounddevice and measure Channel 0 vs Channels 1..4."""

import time
import sounddevice as sd
import numpy as np

def test_sd_capture():
    print("=== SOUNDDEVICE DEVICES ===")
    devs = sd.query_devices()
    respeaker_idx = None
    for i, d in enumerate(devs):
        print(f"  [{i:2d}] {d['name']} (in={d['max_input_channels']}, out={d['max_output_channels']})")
        if "respeaker" in d['name'].lower() or "arrayuac" in d['name'].lower():
            if d['max_input_channels'] > 0 and respeaker_idx is None:
                respeaker_idx = i

    print("\nRecording 2.0s across 6 channels from default PulseAudio ReSpeaker...")
    rec = sd.rec(int(2.0 * 16000), samplerate=16000, channels=6, dtype='int16')
    sd.wait()
    print(f"✅ Captured shape: {rec.shape}")
    for ch in range(rec.shape[1]):
        ch_f = rec[:, ch].astype(np.float32)
        rms = np.sqrt(np.mean(ch_f**2))
        peak = np.max(np.abs(ch_f))
        name = "Processed (AEC)" if ch == 0 else (f"Raw Mic {ch}" if ch < 5 else "Playback Ref")
        print(f"  Channel {ch} ({name:15s}): RMS = {rms:6.1f} | Peak = {peak:5.0f}")

if __name__ == "__main__":
    test_sd_capture()
