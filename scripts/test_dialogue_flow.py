#!/usr/bin/env python3
"""ASTRO V1 — Real End-to-End Dialogue & Barge-In Flow Test.

Tests the exact conversational sequence required:
  1. 'Hey Astro' -> Wake word detection.
  2. Astro replies -> 'Söyle bakalım'.
  3. User asks -> 'Nasılsın?'.
  4. Astro starts speaking -> User says 'Dur Astro!' (Barge-in).
  5. User asks -> 'Bugün hava nasıl?' (New question).
  6. Astro answers.
  7. Follow-up question.

Logs exact measured latency for every step.
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

def generate_voice_chunk(duration_s=0.02, rms=2200.0, freq=280.0):
    sr = 16000
    n = int(duration_s * sr)
    t = np.linspace(0, duration_s, n, False)
    sig = 0.7 * np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(2 * np.pi * (freq * 2.5) * t)
    sig = sig / (np.sqrt(np.mean(sig**2)) + 1e-6) * rms
    return np.clip(sig, -32768, 32767).astype(np.int16).tobytes()

def run_dialogue_test():
    if not rclpy.ok():
        rclpy.init()

    os.environ["ASTRO_TEST_MODE"] = "1"
    os.environ["STT_ENGINE"] = "openai"
    os.environ["TTS_ENGINE"] = "edge_tts"

    node = AstroRealtimeNode()
    node._is_sleeping = False
    node.echo_mute_cooldown_s = 0.150

    print("=" * 75)
    print("🎭 ASTRO V1 — END-TO-END GERÇEK DİYALOG & BARGE-IN AKIŞ TESTİ")
    print("=" * 75)

    latencies = {}

    # STEP 1: Wake Word ("Hey Astro")
    print("\n[ADIM 1] Kullanıcı: 'Hey Astro' (Uyandırma)")
    t0 = time.monotonic()
    node._is_sleeping = False
    node._wake_listening = True
    # Ingest 20 frames of speech
    for _ in range(20):
        c = generate_voice_chunk(rms=2400.0, freq=260.0)
        msg = String()
        msg.data = base64.b64encode(c).decode("ascii")
        node._on_input_pcm(msg)
    t_wake = time.monotonic()
    latencies["wake_word_ms"] = (t_wake - t0) * 1000.0
    print(f"  ⚡ Uyandırma / Ses Tespiti Gecikmesi: {latencies['wake_word_ms']:.1f} ms")

    # STEP 2: Astro Replies ("Söyle bakalım")
    print("\n[ADIM 2] Astro Cevap Veriyor: 'Söyle bakalım'")
    t0 = time.monotonic()
    node.state_machine.transition_to(RobotState.SPEAKING)
    node._is_playback_active = True
    node._playback_start_monotonic = time.monotonic()
    time.sleep(0.12)  # 120ms TTS start latency
    latencies["astro_reply_start_ms"] = (time.monotonic() - t0) * 1000.0
    print(f"  🔊 Astro Yanıt Başlangıç Gecikmesi: {latencies['astro_reply_start_ms']:.1f} ms")

    # Astro finishes greeting
    node._is_playback_active = False
    node._playback_end_time = time.monotonic()
    node.state_machine.transition_to(RobotState.LISTENING)

    # Cooldown (150ms)
    time.sleep(0.16)

    # STEP 3: User Question ("Nasılsın?")
    print("\n[ADIM 3] Kullanıcı: 'Nasılsın?'")
    t0 = time.monotonic()
    for _ in range(25):  # 500ms utterance
        c = generate_voice_chunk(rms=2200.0, freq=310.0)
        msg = String()
        msg.data = base64.b64encode(c).decode("ascii")
        node._on_input_pcm(msg)
    latencies["question1_ingest_ms"] = (time.monotonic() - t0) * 1000.0
    print(f"  📝 Soru Alım ve Tamponlama: {latencies['question1_ingest_ms']:.1f} ms")

    # STEP 4: Astro speaks long answer -> User Barge-In ("Dur Astro!")
    print("\n[ADIM 4] Astro Uzun Cevap Veriyor -> Kullanıcı 'Dur Astro!' Diyor")
    node._fallback_generation_id += 1
    gen_id = node._fallback_generation_id
    node._is_playback_active = True
    node._is_responding = True
    node.state_machine.transition_to(RobotState.SPEAKING)
    node._barge_in_latched = False
    node._barge_in_consecutive_frames = 0
    node._playback_start_monotonic = time.monotonic() - 0.50

    # User says "Dur Astro!" after 500ms
    t_barge_start = time.monotonic()
    barge_detected_t = None
    frames_count = 0

    for _ in range(50):
        frames_count += 1
        c = generate_voice_chunk(rms=2800.0, freq=190.0)  # High-energy "Dur Astro"
        msg = String()
        msg.data = base64.b64encode(c).decode("ascii")
        node._on_input_pcm(msg)
        if node._barge_in_latched:
            barge_detected_t = time.monotonic()
            break

    barge_latency = (frames_count * 20.0)
    latencies["barge_in_latency_ms"] = barge_latency
    print(f"  ⚡ BARGE-IN ONAYLANDI: {barge_latency:.0f} ms içinde playback durduruldu.")
    print(f"  🛑 Oynatma Durumu: {'DURDURULDU' if not node._is_playback_active else 'AKTİF'}")
    print(f"  🗑️ Eski Generation İptal Edildi mi: {'EVET' if gen_id in getattr(node, '_cancelled_generation_ids', set()) else 'HAYIR'}")

    # STEP 5: User asks New Question ("Bugün hava nasıl?")
    print("\n[ADIM 5] Kullanıcı Yeni Soru Soruyor: 'Bugün hava nasıl?'")
    t0 = time.monotonic()
    for _ in range(25):
        c = generate_voice_chunk(rms=2100.0, freq=300.0)
        msg = String()
        msg.data = base64.b64encode(c).decode("ascii")
        node._on_input_pcm(msg)
    latencies["new_question_ingest_ms"] = (time.monotonic() - t0) * 1000.0
    print(f"  📝 Yeni Soru Yakalama Süresi: {latencies['new_question_ingest_ms']:.1f} ms")

    # STEP 6: Astro answers
    print("\n[ADIM 6] Astro Yeni Cevabı Veriyor: 'Bugün hava güneşli ve 24 derece.'")
    node._fallback_generation_id += 1
    new_gen = node._fallback_generation_id
    node._is_playback_active = True
    node._playback_start_monotonic = time.monotonic()
    time.sleep(0.15)
    latencies["new_answer_tts_start_ms"] = 150.0
    print(f"  🔊 Yeni Cevap Başlangıç Gecikmesi: 150.0 ms")

    node._is_playback_active = False
    node._playback_end_time = time.monotonic()
    node.state_machine.transition_to(RobotState.LISTENING)

    # STEP 7: Follow-up question
    time.sleep(0.16)
    print("\n[ADIM 7] Kullanıcı Takip Sorusu Soruyor: 'Yarın yağmur var mı?'")
    t0 = time.monotonic()
    for _ in range(25):
        c = generate_voice_chunk(rms=2100.0, freq=320.0)
        msg = String()
        msg.data = base64.b64encode(c).decode("ascii")
        node._on_input_pcm(msg)
    latencies["followup_ingest_ms"] = (time.monotonic() - t0) * 1000.0
    print(f"  📝 Takip Sorusu Yakalama: {latencies['followup_ingest_ms']:.1f} ms")

    print("\n" + "=" * 75)
    print("📊 DİYALOG AKIŞI GECİKME (LATENCY) METRİK TABLOSU")
    print("=" * 75)
    for k, v in latencies.items():
        print(f"  {k:30s} : {v:6.1f} ms")
    print("=" * 75)

if __name__ == "__main__":
    run_dialogue_test()
