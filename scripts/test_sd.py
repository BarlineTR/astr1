import sounddevice as sd
import numpy as np

print("=== SOUNDDEVICE DEVICES ===")
devs = sd.query_devices()
for idx, d in enumerate(devs):
    print(f"[{idx}] {d['name']} | in: {d['max_input_channels']} | out: {d['max_output_channels']} | default_sr: {d['default_samplerate']}")

# Try recording 1 second 6-channel on ReSpeaker
respeaker_idx = None
for idx, d in enumerate(devs):
    if "respeaker" in d["name"].lower() or "arrayuac" in d["name"].lower():
        if d["max_input_channels"] >= 6:
            respeaker_idx = idx
            break

print(f"\nTarget ReSpeaker index: {respeaker_idx}")
if respeaker_idx is not None:
    try:
        print("Recording 1 second (16000 samples, 6 channels, 16kHz)...")
        rec = sd.rec(16000, samplerate=16000, channels=6, device=respeaker_idx, dtype="int16")
        sd.wait()
        print(f"✅ Success! Recorded shape: {rec.shape}")
        for ch in range(6):
            rms = np.sqrt(np.mean(rec[:, ch].astype(np.float32) ** 2))
            peak = np.max(np.abs(rec[:, ch]))
            print(f"  Channel {ch}: RMS = {rms:.1f}, Peak = {peak}")
    except Exception as e:
        print(f"❌ Recording failed: {e}")
