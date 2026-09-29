import sounddevice as sd
import numpy as np

rec = sd.rec(16000 * 5, samplerate=16000, channels=6, device=0, dtype='int16')
sd.wait()

for c in range(6):
    ch = rec[:, c]
    rms = float(np.sqrt(np.mean(ch.astype(np.float32)**2)))
    peak = int(np.max(np.abs(ch)))
    print(f"Ch {c}: RMS={rms:7.1f}, Peak={peak:5d}")
