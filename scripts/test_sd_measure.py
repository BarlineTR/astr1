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

    print(f"\nTarget ReSpeaker index: {respeaker_idx}")
    target_idx = respeaker_idx if respeaker_idx is not None else sd.default.device[0]
    dev_info = sd.query_devices(target_idx)
    max_in = dev_info['max_input_channels']
    print(f"Opening device [{target_idx}] '{dev_info['name']}' with {max_in} channels @ 16000Hz...")

    # Record 2 seconds
    dur = 2.0
    rec = sd.rec(int(dur * 16000), samplerate=16000, channels=max_in, dtype='int16', device=target_idx)
    sd.wait()
    
    print(f"\n✅ Captured {rec.shape[0]} samples across {rec.shape[1]} channels:")
    for ch in range(rec.shape[1]):
        ch_f = rec[:, ch].astype(np.float32)
        rms = np.sqrt(np.mean(ch_f**2))
        peak = np.max(np.abs(ch_f))
        name = "Processed (AEC)" if ch == 0 else (f"Raw Mic {ch}" if ch < 5 else "Playback Ref")
        print(f"  Channel {ch} ({name:15s}): RMS = {rms:6.1f} | Peak = {peak:5.0f}")

if __name__ == "__main__":
    test_sd_capture()
