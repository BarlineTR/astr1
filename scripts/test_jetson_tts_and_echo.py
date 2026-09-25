#!/usr/bin/env python3
"""Hardware & Pipeline verification on Jetson: Edge-TTS synthesis and Self-Voice Echo Elimination."""

import os
import sys
import time

# Ensure ROS packages are importable
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_ai/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_audio/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_ai")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_audio")

from astro_ai.astro_realtime_node import compute_self_voice_score, clean_tts_text
from astro_audio.edge_tts_engine import EdgeTTSEngine

def test_edge_tts_synthesis():
    print("\n--- 1. Edge-TTS Sentez Testi ---")
    engine = EdgeTTSEngine(voice="tr-TR-AhmetNeural", logger=lambda lvl, msg: print(f"    [{lvl}] {msg}"))
    test_cases = [
        "Ne robotu lan zibidi,",
        "ne var söyle !",
        "Merhaba, nasılsın?",
        "Ben ASTRO, sana nasıl yardımcı olabilirim?"
    ]
    for text in test_cases:
        t0 = time.perf_counter()
        pcm = engine.synthesize_sentence(text, generation_id=101)
        dur = (time.perf_counter() - t0) * 1000.0
        if pcm and len(pcm) > 1000:
            print(f"  [BAŞARILI] '{text}' -> {len(pcm)} bayt PCM ({dur:.1f}ms)")
        else:
            print(f"  [BAŞARISIZ] '{text}' -> Sentez başarısız!")
            return False
    return True

def test_self_voice_echo_rejection():
    print("\n--- 2. Kendi Sesini / Yankıyı Yakalama (Echo Suppression) Testi ---")
    recent_phrases = [
        "ne robotu lan zibidi",
        "ne var söyle"
    ]
    
    # 1. Exact or partial echo matches from microphone
    echo_inputs = [
        "ne robotu lan zibidi",
        "ne robotu",
        "ne var söyle",
        "robotu lan zibidi"
    ]
    for echo in echo_inputs:
        score = compute_self_voice_score(echo, recent_phrases)
        is_rejected = score >= 0.20
        print(f"  Girdi: '{echo}' -> Self-Voice Skoru: {score:.2f} | Yankı Olarak Engellendi: {'EVET' if is_rejected else 'HAYIR'}")
        assert is_rejected, f"Echo '{echo}' should have been rejected!"

    # 2. Genuine user queries (should NOT be rejected as self-voice)
    user_inputs = [
        "hava bugün nasıl",
        "saat kaç",
        "sen kimsin",
        "adın ne"
    ]
    for user_text in user_inputs:
        score = compute_self_voice_score(user_text, recent_phrases)
        is_safe = score < 0.20
        print(f"  Kullanıcı: '{user_text}' -> Self-Voice Skoru: {score:.2f} | Geçerli Kullanıcı Sözü: {'EVET' if is_safe else 'HAYIR'}")
        assert is_safe, f"Genuine input '{user_text}' false positive rejection!"

    print("  ✅ Tüm yankı / öz-ses engelleme kuralları doğrulandı.")
    return True

if __name__ == "__main__":
    ok_tts = test_edge_tts_synthesis()
    ok_echo = test_self_voice_echo_rejection()
    if ok_tts and ok_echo:
        print("\n🎉 [TÜM JETSON DOĞRULAMA TESTLERİ BAŞARIYLA GEÇTİ]")
        sys.exit(0)
    else:
        print("\n❌ [BAZI TESTLER BAŞARISIZ OLDU]")
        sys.exit(1)
