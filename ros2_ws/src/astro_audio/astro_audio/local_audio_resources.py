#!/usr/bin/env python3
"""ASTRO V1 — Zero-Latency Pre-Generated Local Audio Resources (ACK & Emergency Fallback).

Provides ultra-fast (< 10ms) pre-generated 16kHz PCM WAV audio for:
  1. THINKING_ACK: "Bir saniye, bakıyorum.", "İnceliyorum.", "Kontrol ediyorum."
  2. EMERGENCY_FALLBACK: "Şu an bağlantımda sorun var, tekrar kontrol ediyorum."
  3. ACOUSTIC_CHIME: High-clarity earcons for zero-silence contract.

Guarantees playback_started <= 300ms with ZERO network dependency.
"""

import io
import math
import os
import struct
import subprocess
import wave
from typing import Dict, Optional


def create_sine_wave_pcm(
    frequencies: list[float] = [440.0, 880.0],
    durations: list[float] = [0.10, 0.15],
    sample_rate: int = 16000,
    volume: float = 0.5,
) -> bytes:
    """Generates clean multi-tone acoustic earcon PCM (16kHz 16-bit mono)."""
    raw_samples = []
    for freq, dur in zip(frequencies, durations):
        n_samples = int(sample_rate * dur)
        for i in range(n_samples):
            t = float(i) / sample_rate
            # Add simple envelope fade-in/out
            env = 1.0
            if i < 200:
                env = float(i) / 200.0
            elif i > (n_samples - 200):
                env = float(n_samples - i) / 200.0
            val = int(32767.0 * volume * env * math.sin(2.0 * math.pi * freq * t))
            raw_samples.append(max(-32768, min(32767, val)))
    return struct.pack(f"<{len(raw_samples)}h", *raw_samples)


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Wraps raw 16kHz 16-bit mono PCM into standard WAV bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


class LocalAudioResources:
    """Single manager for low-latency local audio buffers."""

    _instance: Optional["LocalAudioResources"] = None

    @classmethod
    def get_instance(cls) -> "LocalAudioResources":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, resource_dir: Optional[str] = None):
        self.resource_dir = resource_dir or os.path.expanduser("~/.astro/resources")
        os.makedirs(self.resource_dir, exist_ok=True)
        self._pcm_cache: Dict[str, bytes] = {}
        self._initialize_resources()

    def _synthesize_local_espeak(self, text: str) -> Optional[bytes]:
        """Tries fast local espeak-ng / espeak to generate PCM bytes."""
        for cmd_name in ("espeak-ng", "espeak"):
            try:
                proc = subprocess.Popen(
                    [cmd_name, "-v", "tr", "-s", "175", "-a", "100", "--stdout", text],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                wav_out, _ = proc.communicate(timeout=0.30)
                if wav_out and len(wav_out) > 44:
                    # Extract raw PCM from WAV
                    with wave.open(io.BytesIO(wav_out), "rb") as wf:
                        raw = wf.readframes(wf.getnframes())
                        sr = wf.getframerate()
                        if sr == 16000:
                            return raw
                        elif sr == 22050:
                            # Quick downsample
                            import numpy as np
                            arr = np.frombuffer(raw, dtype=np.int16)
                            n_out = int(len(arr) * (16000.0 / 22050.0))
                            resampled = np.interp(np.linspace(0, len(arr) - 1, n_out), np.arange(len(arr)), arr.astype(np.float32)).astype(np.int16)
                            return resampled.tobytes()
            except Exception:
                pass
        return None

    def _initialize_resources(self):
        """Generates and pre-buffers standard ACK and emergency audio files."""
        # 1. THINKING_ACK: "Bir saniye, bakıyorum."
        ack_looking_pcm = self._synthesize_local_espeak("Bir saniye, bakıyorum.")
        if not ack_looking_pcm:
            ack_looking_pcm = create_sine_wave_pcm([523.25, 659.25], [0.08, 0.12])
        self._pcm_cache["ack_looking"] = ack_looking_pcm

        # 2. THINKING_ACK: "İnceliyorum."
        ack_examining_pcm = self._synthesize_local_espeak("İnceliyorum.")
        if not ack_examining_pcm:
            ack_examining_pcm = create_sine_wave_pcm([587.33, 783.99], [0.08, 0.12])
        self._pcm_cache["ack_examining"] = ack_examining_pcm

        # 3. THINKING_ACK: "Kontrol ediyorum."
        ack_checking_pcm = self._synthesize_local_espeak("Kontrol ediyorum.")
        if not ack_checking_pcm:
            ack_checking_pcm = create_sine_wave_pcm([659.25, 880.00], [0.08, 0.12])
        self._pcm_cache["ack_checking"] = ack_checking_pcm

        # 4. EMERGENCY_FALLBACK: "Şu an bağlantımda sorun var, tekrar kontrol ediyorum."
        emergency_pcm = self._synthesize_local_espeak("Şu an bağlantımda sorun var, tekrar kontrol ediyorum.")
        if not emergency_pcm:
            emergency_pcm = create_sine_wave_pcm([440.0, 349.23, 440.0], [0.10, 0.10, 0.15])
        self._pcm_cache["emergency_fallback"] = emergency_pcm

    def get_ack_pcm(self, ack_type: str = "looking") -> bytes:
        """Returns raw 16kHz PCM bytes for immediate low-latency ACK."""
        key = f"ack_{ack_type}"
        return self._pcm_cache.get(key, self._pcm_cache["ack_looking"])

    def get_emergency_fallback_pcm(self) -> bytes:
        """Returns raw 16kHz PCM bytes for emergency zero-silence fallback."""
        return self._pcm_cache.get("emergency_fallback", create_sine_wave_pcm([440.0, 330.0], [0.15, 0.20]))


def get_local_audio_resources() -> LocalAudioResources:
    return LocalAudioResources.get_instance()
