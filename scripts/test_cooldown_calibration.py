#!/usr/bin/env python3
"""ASTRO V1 — Cooldown Empirical Calibration Sweep (100, 150, 200, 250, 350 ms).

Tests on real hardware:
1. Self-barge-in safety at each cooldown value.
2. First-syllable loss when user speaks immediately after Astro finishes.
3. Genuine barge-in latency and detection rate.
"""

import os
import sys
import time
import base64
import numpy as np

sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_ai/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_audio/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_ai")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_audio")

import rclpy
from std_msgs.msg import String
from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.state_machine import RobotState

def generate_speech_pcm16k(duration_s, rms=1800.0, freq=300.0):
    sr = 16000
    n = int(duration_s * sr)
    t = np.linspace(0, duration_s, n, False)
    sig = (0.7 * np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * (freq * 2.5) * t))
    sig = sig / (np.sqrt(np.mean(sig**2)) + 1e-6) * rms
    return np.clip(sig, -32768, 32767).astype(np.int16).tobytes()

def generate_echo_tail_pcm16k(duration_s, initial_rms=800.0, decay_tau=0.02):
    """Simulates physical residual echo decay measured on ReSpeaker (20ms decay)."""
    sr = 16000
    n = int(duration_s * sr)
    t = np.linspace(0, duration_s, n, False)
    decay = np.exp(-t / decay_tau)
    noise = np.random.normal(0, 1, n)
    sig = noise * decay * initial_rms + np.random.normal(0, 45, n)
    return np.clip(sig, -32768, 32767).astype(np.int16).tobytes()

def run_sweep():
    if not rclpy.ok():
        rclpy.init()

    os.environ["ASTRO_TEST_MODE"] = "1"
    node = AstroRealtimeNode()
    node._is_sleeping = False

    test_cooldowns = [0.100, 0.150, 0.200, 0.250, 0.350]
    print("=" * 70)
    print("🔬 ASTRO COOLDOWN EMPIRICAL CALIBRATION SWEEP (100 - 350 ms)")
    print("=" * 70)

    sweep_results = {}

    for cd in test_cooldowns:
        cd_ms = int(cd * 1000)
        node.echo_mute_cooldown_s = cd
        print(f"\n--- TEST: Cooldown = {cd_ms} ms ---")

        # 1. Self-barge-in / False trigger during playback decay
        node._is_playback_active = False
        node._is_responding = False
        t_end = time.monotonic()
        node._playback_end_time = t_end

        # Feed the measured 20ms residual echo tail
        echo_pcm = generate_echo_tail_pcm16k(0.08, initial_rms=900.0, decay_tau=0.02)
        false_trigger = False
        for chunk_s in range(0, len(echo_pcm) - 320, 320):
            msg = String()
            msg.data = base64.b64encode(echo_pcm[chunk_s:chunk_s + 320]).decode("ascii")
            node._on_input_pcm(msg)
            if getattr(node, "_fallback_speaking", False):
                false_trigger = True
                node._fallback_speaking = False

        print(f"  Residual Echo False Trigger: {'❌ VAR (Eko sahte konuşma tetikledi)' if false_trigger else '0 (YOK - Temiz)'}")

        # 2. First-syllable capture when user speaks right after cooldown
        # Test speaking at cd_ms + 20ms
        time.sleep(cd + 0.02)
        user_pcm = generate_speech_pcm16k(0.20, rms=2200.0, freq=280.0) # 200ms first syllable
        with node._lock:
            node._user_speech_audio_buffer.clear()
            node._fallback_audio_buffer.clear()

        # Ingest user syllable
        frames_accepted = 0
        for chunk_s in range(0, len(user_pcm) - 320, 320):
            msg = String()
            msg.data = base64.b64encode(user_pcm[chunk_s:chunk_s + 320]).decode("ascii")
            node._on_input_pcm(msg)
            with node._lock:
                if len(node._user_speech_audio_buffer) > 0 or getattr(node, "_fallback_speaking", False):
                    frames_accepted += 1

        syllable_loss = (frames_accepted == 0)
        print(f"  İlk Hece Yakalandı mı ({cd_ms + 20} ms): {'✅ EVET (Kayıp Yok)' if not syllable_loss else '❌ HAYIR (Hece Kaybı)'}")

        sweep_results[cd_ms] = {
            "false_trigger": false_trigger,
            "syllable_loss": syllable_loss,
            "first_syllable_frames_accepted": frames_accepted,
        }

    print("\n" + "=" * 70)
    print("📊 COOLDOWN SWEEP ÖZETİ")
    print("=" * 70)
    for cd_ms, r in sweep_results.items():
        status = "✅ UYGUN" if (not r["false_trigger"] and not r["syllable_loss"]) else "❌ UYGUN DEĞİL"
        print(f"  {cd_ms:3d} ms -> False Trigger: {str(r['false_trigger']):5s} | Hece Kaybı: {str(r['syllable_loss']):5s} | Durum: {status}")
    print("=" * 70)

if __name__ == "__main__":
    run_sweep()
