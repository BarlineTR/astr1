#!/usr/bin/env python3
"""Acoustic Level & AEC Measurement on Jetson ReSpeaker 6-Channel Hardware."""

import os
import sys
import time
import wave
import subprocess
import numpy as np

CHANNELS = 6
RATE = 16000
DEV = "plughw:CARD=ArrayUAC10,DEV=0"

def record_audio(duration_s=2.0, out_wav="/tmp/measure_6ch.wav"):
    frames = int(RATE * duration_s)
    cmd = [
        "arecord",
        "-D", DEV,
        "-f", "S16_LE",
        "-r", str(RATE),
        "-c", str(CHANNELS),
        "-d", str(int(duration_s + 0.5)),
        out_wav
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.exists(out_wav):
        return None
    with wave.open(out_wav, "rb") as wf:
        n_f = wf.getnframes()
        data = wf.readframes(n_f)
        arr = np.frombuffer(data, dtype=np.int16).reshape(-1, CHANNELS)
        return arr

def measure_levels():
    print("=== 1. SESSİZLİK / ARKA PLAN ÖLÇÜMÜ (1.5s) ===")
    quiet_arr = record_audio(1.5, "/tmp/quiet_6ch.wav")
    if quiet_arr is not None:
        for ch in range(CHANNELS):
            ch_data = quiet_arr[:, ch].astype(np.float32)
            rms = np.sqrt(np.mean(ch_data**2))
            peak = np.max(np.abs(ch_data))
            name = "Processed (AEC)" if ch == 0 else (f"Raw Mic {ch}" if ch < 5 else "Playback Ref")
            print(f"  Channel {ch} ({name:15s}): RMS = {rms:6.1f} | Peak = {peak:5.0f}")
    
    print("\n=== 2. TTS OYNATMA SIRASINDA AEC BASTIRMA ÖLÇÜMÜ ===")
    # Generate a simple 1-second 440Hz test beep or speech sound to play via aplay while recording
    test_tone_wav = "/tmp/test_tone.wav"
    with wave.open(test_tone_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        t = np.linspace(0, 2.0, 32000, False)
        # Tone + harmonics (speech-like amplitude)
        tone = (0.5 * np.sin(2 * np.pi * 440 * t) + 0.3 * np.sin(2 * np.pi * 880 * t)) * 20000
        wf.writeframes(tone.astype(np.int16).tobytes())

    # Start playback in background
    play_proc = subprocess.Popen(["aplay", "-D", DEV, test_tone_wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.3)
    
    # Record during active playback
    play_arr = record_audio(1.5, "/tmp/playback_6ch.wav")
    play_proc.wait()

    if play_arr is not None:
        ch0_f = play_arr[:, 0].astype(np.float32)
        ch0_rms = np.sqrt(np.mean(ch0_f**2))
        ch0_peak = np.max(np.abs(ch0_f))

        ch1_f = play_arr[:, 1].astype(np.float32)
        ch1_rms = np.sqrt(np.mean(ch1_f**2))
        ch1_peak = np.max(np.abs(ch1_f))

        ch5_f = play_arr[:, 5].astype(np.float32)
        ch5_rms = np.sqrt(np.mean(ch5_f**2))

        print(f"  Channel 0 (Processed AEC)  : RMS = {ch0_rms:7.1f} | Peak = {ch0_peak:6.0f}")
        print(f"  Channel 1 (Raw Mic 1)      : RMS = {ch1_rms:7.1f} | Peak = {ch1_peak:6.0f}")
        print(f"  Channel 5 (Playback Ref)   : RMS = {ch5_rms:7.1f}")
        if ch1_rms > 0:
            aec_attenuation_db = 20 * np.log10(max(1.0, ch1_rms) / max(1.0, ch0_rms))
            print(f"\n  🎯 ReSpeaker Hardware AEC Bastırma Oranı: ~{aec_attenuation_db:.1f} dB (Ch1 Raw vs Ch0 Processed)")

if __name__ == "__main__":
    measure_levels()
