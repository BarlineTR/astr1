#!/usr/bin/env python3
"""ASTRO V1 — ReSpeaker Hardware AEC & Audio Forensic Audit.

Tests and verifies:
1. ReSpeaker 6-channel mapping (Ch0..Ch5).
2. Playback reference presence on Ch5 (Loopback).
3. XMOS XVF3000 AEC active/bypass status via USB vendor control.
4. Real acoustic echo attenuation (Ch0 vs Ch1 dB).
5. Physical residual echo tail duration (ms).
"""

import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import time
import wave
import numpy as np

try:
    import usb.core
except ImportError:
    usb = None

def query_xmos_params():
    """Queries XMOS XVF3000 DSP registers via pyusb control transfer."""
    if usb is None:
        return {"error": "pyusb not installed"}
    dev = usb.core.find(idVendor=0x2886, idProduct=0x0018)
    if dev is None:
        return {"error": "ReSpeaker USB 2886:0018 not found"}

    def read_param(mod_id, offset):
        try:
            data = dev.ctrl_transfer(0xC0, 0, 0xC0 | offset, mod_id, 8, 1000)
            return struct.unpack_from("<i", data)[0]
        except Exception as e:
            return f"err: {e}"

    return {
        "device_found": True,
        "AECFREEZEONOFF": read_param(18, 7),
        "AECNORM": read_param(18, 1),
        "AGCONOFF": read_param(19, 0),
        "SPEECHDETECTED": read_param(19, 22),
        "DOAANGLE": read_param(21, 0),
    }

def generate_test_wav(filepath, duration_s=1.0, freq_hz=1000, sample_rate=16000):
    """Generates a pure sine tone WAV for playback."""
    n_samples = int(duration_s * sample_rate)
    t = np.linspace(0, duration_s, n_samples, endpoint=False)
    # Sine wave with ramp envelope to avoid pop
    envelope = np.ones(n_samples)
    ramp = int(0.05 * sample_rate)
    envelope[:ramp] = np.linspace(0, 1, ramp)
    envelope[-ramp:] = np.linspace(1, 0, ramp)
    audio = (np.sin(2 * np.pi * freq_hz * t) * envelope * 24000.0).astype(np.int16)

    with wave.open(filepath, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())

def run_audio_audit(output_device=None, capture_card="hw:CARD=ArrayUAC10,DEV=0", duration_s=3.5):
    """Runs a simultaneous play-and-record test to measure AEC and residual echo."""
    print("=" * 65)
    print("  ASTRO V1 — RESPEAKER AEC & ECHO TAIL FORENSIC AUDIT")
    print("=" * 65)

    # 1. XMOS DSP Register Status
    print("\n[1/5] XMOS XVF3000 Donanım Register Durumu Sorgulanıyor...")
    xmos = query_xmos_params()
    print(f"  XMOS Durumu: {json.dumps(xmos, indent=2)}")

    # 2. ALSA Cards & PulseAudio Sinks
    print("\n[2/5] ALSA ve PulseAudio Cihaz Haritası:")
    try:
        cards = subprocess.check_output(["cat", "/proc/asound/cards"]).decode()
        print(f"  /proc/asound/cards:\n{cards.strip()}")
    except Exception as e:
        print(f"  asound/cards okunamadı: {e}")

    try:
        sinks = subprocess.check_output(["pactl", "list", "short", "sinks"]).decode()
        print(f"  PulseAudio Sinks:\n{sinks.strip()}")
    except Exception as e:
        print(f"  pactl sinks okunamadı: {e}")

    # 3. Simultaneous Playback & 6-Channel Recording
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as test_wav:
        wav_path = test_wav.name
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as rec_raw:
        raw_path = rec_raw.name

    try:
        generate_test_wav(wav_path, duration_s=1.0, freq_hz=1000)
        
        # Decide playback command
        # If output_device is specified, use aplay -D, otherwise test ReSpeaker DAC first
        pb_dev = output_device or "plughw:CARD=ArrayUAC10,DEV=0"
        print(f"\n[3/5] Ses Testi: Çalma Cihazı = '{pb_dev}', Kayıt = '{capture_card}' (6 kanal)")

        # Start 6-channel arecord
        sample_rate = 16000
        n_channels = 6
        rec_cmd = [
            "arecord",
            "-D", capture_card,
            "-c", str(n_channels),
            "-r", str(sample_rate),
            "-f", "S16_LE",
            "-t", "raw",
            "-d", str(int(duration_s)),
            raw_path
        ]
        
        rec_proc = subprocess.Popen(rec_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(0.5)  # 500ms pre-silence for ambient noise floor

        play_start_t = time.monotonic()
        pb_cmd = ["aplay", "-D", pb_dev, wav_path]
        pb_proc = subprocess.run(pb_cmd, capture_output=True, text=True)
        play_end_t = time.monotonic()
        play_dur_s = play_end_t - play_start_t

        rec_proc.wait(timeout=duration_s + 2.0)
        rec_stderr = rec_proc.stderr.read().decode() if rec_proc.stderr else ""

        if rec_proc.returncode != 0:
            print(f"❌ arecord hatası ({rec_proc.returncode}): {rec_stderr}")
            return

        # 4. Analyze 6-Channel Recorded PCM
        print("\n[4/5] Çok Kanallı PCM Verisi Analiz Ediliyor...")
        with open(raw_path, "rb") as f:
            raw_bytes = f.read()

        arr_int16 = np.frombuffer(raw_bytes, dtype=np.int16)
        total_samples = len(arr_int16) // n_channels
        arr_int16 = arr_int16[:total_samples * n_channels]
        multi = arr_int16.reshape(-1, n_channels).T  # Shape: (6, total_samples)

        time_axis = np.arange(total_samples) / float(sample_rate)

        # Baseline Ambient (first 400ms before tone started)
        ambient_samples = int(0.4 * sample_rate)
        ambient_rms = [
            float(np.sqrt(np.mean(multi[ch, :ambient_samples].astype(np.float32) ** 2)))
            for ch in range(n_channels)
        ]

        # Tone Playback Interval
        tone_start_idx = int(0.5 * sample_rate)
        tone_end_idx = min(total_samples, int((0.5 + play_dur_s) * sample_rate))
        during_rms = [
            float(np.sqrt(np.mean(multi[ch, tone_start_idx:tone_end_idx].astype(np.float32) ** 2)))
            for ch in range(n_channels)
        ]

        ch0_ambient = ambient_rms[0]
        ch1_ambient = ambient_rms[1]
        ch0_tone = during_rms[0]      # Processed (AEC)
        ch1_tone = during_rms[1]      # Raw Mic 0
        ch5_tone = during_rms[5]      # Loopback Reference

        # Attenuation Calculation
        # Attenuation = 20 * log10(Raw_Mic / AEC_Processed)
        if ch0_tone > 0:
            attenuation_db = 20.0 * math.log10(max(1.0, ch1_tone) / max(1.0, ch0_tone))
        else:
            attenuation_db = 0.0

        # Residual Echo Decay Time Calculation
        # After tone_end_idx, find how many ms until ch0 drops below (ambient * 1.15)
        # Using 20ms sliding windows
        window_size = int(0.02 * sample_rate)  # 320 samples
        residual_samples = 0
        threshold_rms = max(ch0_ambient * 1.15, ch0_ambient + 15.0)

        for s_idx in range(tone_end_idx, total_samples - window_size, window_size):
            win_rms = float(np.sqrt(np.mean(multi[0, s_idx:s_idx + window_size].astype(np.float32) ** 2)))
            if win_rms <= threshold_rms:
                residual_samples = s_idx - tone_end_idx
                break
        else:
            residual_samples = total_samples - tone_end_idx

        residual_tail_ms = (residual_samples / float(sample_rate)) * 1000.0

        # 5. Report Table
        print("\n" + "=" * 65)
        print("  📊 METRİK RAPORU (RESPEAKER AEC & ECHO)")
        print("=" * 65)
        print(f"  Toplam Kayıt Süresi          : {total_samples / sample_rate:.2f} s")
        print(f"  Kanal 0 Ambient RMS (Taban)  : {ch0_ambient:.1f}")
        print(f"  Kanal 1 Ambient RMS (Taban)  : {ch1_ambient:.1f}")
        print("-" * 65)
        print(f"  Kanal 0 Çalma Sırası (AEC)   : {ch0_tone:.1f} RMS (Peak: {np.max(np.abs(multi[0, tone_start_idx:tone_end_idx]))})")
        print(f"  Kanal 1 Çalma Sırası (Ham)   : {ch1_tone:.1f} RMS (Peak: {np.max(np.abs(multi[1, tone_start_idx:tone_end_idx]))})")
        print(f"  Kanal 5 Loopback Reference   : {ch5_tone:.1f} RMS")
        print("-" * 65)
        print(f"  🎯 Gerçek Echo Attenuation   : {attenuation_db:+.2f} dB")
        print(f"  ⏱️ Residual Echo Tail Süresi : {residual_tail_ms:.1f} ms")
        print(f"  Loopback Sinyal Varlığı      : {'EVET (Aktif Referans)' if ch5_tone > 50 else 'HAYIR (Loopback Sessiz!)'}")
        print("=" * 65)

        return {
            "xmos": xmos,
            "ch0_ambient": ch0_ambient,
            "ch1_ambient": ch1_ambient,
            "ch0_during": ch0_tone,
            "ch1_during": ch1_tone,
            "ch5_loopback": ch5_tone,
            "attenuation_db": attenuation_db,
            "residual_tail_ms": residual_tail_ms,
            "loopback_present": bool(ch5_tone > 50),
        }

    finally:
        for p in (wav_path, raw_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

if __name__ == "__main__":
    dev = sys.argv[1] if len(sys.argv) > 1 else None
    run_audio_audit(output_device=dev)
