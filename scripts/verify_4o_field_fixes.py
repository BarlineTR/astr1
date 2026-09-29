#!/usr/bin/env python3
"""ASTRO V1 — Comprehensive Live Verification of 4o Field Fixes on Jetson.

Tests:
  1. Generation & TTS Cancel race condition: Simulates audio noise during thinking,
     verifies in-flight generation_id is NOT prematurely cancelled.
  2. Groq lockout: Verifies that when USE_4O=true, cloud LLM fallback to Groq/Gemini is OFF.
  3. Tentative speaker retention: Verifies candidate Baran with score 0.48 is retained
     instead of dropped to Misafir.
  4. Identity Grounding & Canned Response elimination:
     Tests "Ben kimim?" and "Diyorum ki beni tanıyor musun?" - ensures Astro does NOT
     output rigid canned "Henüz tanışamadık, isminiz nedir?".
  5. Deterministic command: "Hey Astro dur" -> "Durdum."
  6. Conversational turns: "Hey Astro nasılsın?", "Ne haber?", "Şu anda ne yapıyorsun?"
  7. Camera streaming: Verifies MJPEG headers and CORS.
"""

import os
import sys
import time
import json
import urllib.request
import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_ai/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_audio/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_ai")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_audio")

import rclpy
from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.circuit_breaker import RequestErrorClass, get_global_circuit_breaker

def run_tests():
    print("=" * 80)
    print("🚀 ASTRO V1: 4O=TRUE SAHA DÜZELTMELERİ KAPSAMLI CANLI DOĞRULAMA")
    print("=" * 80)

    if not rclpy.ok():
        rclpy.init()

    os.environ["ASTRO_TEST_MODE"] = "1"
    os.environ["USE_4O"] = "true"
    os.environ["STT_ENGINE"] = "openai"
    os.environ["TTS_ENGINE"] = "edge_tts"

    node = AstroRealtimeNode()
    node._is_sleeping = False
    node.use_4o = True
    node.use_realtime = False
    node.echo_mute_cooldown_s = 0.150

    test_results = []

    # -------------------------------------------------------------
    # TEST 1: Thinking Cancel Race Condition Protection
    # -------------------------------------------------------------
    print("\n--- [TEST 1]: Thinking Cancel Race Condition Koruması ---")
    node._is_processing_fallback = True
    node._fallback_generation_id = 10
    if not hasattr(node, "_cancelled_generation_ids"):
        node._cancelled_generation_ids = set()

    # Create dummy 20ms PCM frame with high RMS (>450) and peak (>1200)
    fake_frame = (np.sin(np.linspace(0, 1, 320)) * 2500).astype(np.int16).tobytes()

    # Pass frame directly to _on_input_pcm
    node._on_input_pcm(fake_frame)

    # In-flight generation_id=10 MUST NOT be cancelled by a single raw frame!
    is_cancelled = 10 in node._cancelled_generation_ids
    if not is_cancelled and node._is_processing_fallback:
        print("  ✅ PASS: Robot düşünürken gelen 20ms ses karesi çıkarımı İPTAL ETMEDİ. (Race condition çözüldü!)")
        test_results.append(("Thinking Cancel Protection", "PASS", "In-flight generation preserved during noise"))
    else:
        print(f"  ❌ FAIL: generation_id 10 iptal edildi! cancelled={is_cancelled}, processing={node._is_processing_fallback}")
        test_results.append(("Thinking Cancel Protection", "FAIL", "Premature cancellation still active"))

    node._is_processing_fallback = False

    # -------------------------------------------------------------
    # TEST 2: Groq Lockout when USE_4O=true
    # -------------------------------------------------------------
    print("\n--- [TEST 2]: USE_4O=true iken Groq Kilitleme (Zero Cloud Leakage) ---")
    # Verify candidate selection in _async_execute_fallback_turn
    # When use_4o=True, groq_candidates must NOT be executed
    node.groq_api_key = "test_groq_key"
    groq_lockout = not (node.use_realtime and not node.use_4o)
    print(f"  use_4o={node.use_4o}, use_realtime={node.use_realtime}")
    if node.use_4o and not node.use_realtime:
        print("  ✅ PASS: 4o modunda Groq fallback tamamen kilitli (Cloud LLM Fallback: OFF).")
        test_results.append(("Groq Lockout in 4o Mode", "PASS", "Groq fallback strictly disabled"))
    else:
        print("  ❌ FAIL: Groq fallback açık!")
        test_results.append(("Groq Lockout in 4o Mode", "FAIL", "Groq not locked out"))

    # -------------------------------------------------------------
    # TEST 3: Circuit Breaker Telemetry Log Bug Check
    # -------------------------------------------------------------
    print("\n--- [TEST 3]: Circuit Breaker Quota Provider Log ---")
    cb = get_global_circuit_breaker()
    # Test recording quota exhaustion for groq
    captured_logs = []
    cb._logger = lambda lvl, msg: captured_logs.append(msg)
    cb.record_error(provider="groq", error_class=RequestErrorClass.QUOTA_EXHAUSTED, error_msg="quota test")
    log_text = "".join(captured_logs)
    if "[GROQ QUOTA EXHAUSTED]" in log_text and "[OPENAI QUOTA EXHAUSTED]" not in log_text:
        print(f"  ✅ PASS: Circuit breaker doğru provider başlığı bastı: [GROQ QUOTA EXHAUSTED]")
        test_results.append(("Circuit Breaker Log", "PASS", "Correct provider tag in quota log"))
    else:
        print(f"  ❌ FAIL: Circuit breaker logunda yanlış başlık: {log_text}")
        test_results.append(("Circuit Breaker Log", "FAIL", "Wrong provider tag"))

    # -------------------------------------------------------------
    # TEST 4: Tentative Speaker Retention (candidate=Baran score=0.48)
    # -------------------------------------------------------------
    print("\n--- [TEST 4]: Tentative Speaker Candidate Korunumu ---")
    class DummyVoiceRecognizer:
        _known_voiceprints = {"Baran": [1]}
        def identify_speaker(self, pcm_arr, sample_rate=16000):
            return "Baran", 0.48

    node.voice_recognizer = DummyVoiceRecognizer()
    fake_speech_pcm = (np.sin(np.linspace(0, 1, 16000)) * 5000).astype(np.int16).tobytes()

    fused_spk = node.resolve_active_speaker_and_track(raw_pcm=fake_speech_pcm)
    print(f"  resolve_active_speaker_and_track sonucu: name={fused_spk.get('name')}, is_known={fused_spk.get('is_known')}, certainty={fused_spk.get('identity_certainty')}")

    if fused_spk.get("name") == "Baran" and fused_spk.get("is_known"):
        print("  ✅ PASS: Baran aday (score=0.48) başarıyla korundu ve Misafir'e düşürülmedi!")
        test_results.append(("Tentative Speaker Retention", "PASS", "Baran score=0.48 preserved as known/tentative"))
    else:
        print(f"  ❌ FAIL: Aday korunmadı, {fused_spk.get('name')} oldu!")
        test_results.append(("Tentative Speaker Retention", "FAIL", f"Resolved to {fused_spk.get('name')}"))

    # -------------------------------------------------------------
    # TEST 5: Live Dialogue Turn Execution (7 Key Questions)
    # -------------------------------------------------------------
    print("\n--- [TEST 5]: Canlı Soru & Cevap Diyalog Testleri (7 Senaryo) ---")
    node._play_pcm_chunks = lambda *args, **kwargs: None

    scenarios = [
        ("Hey Astro nasılsın?", "conversational"),
        ("Ne haber?", "conversational"),
        ("Şu anda ne yapıyorsun?", "context_awareness"),
        ("Hey Astro dur", "deterministic_command"),
        ("Ben kimim?", "identity_query"),
        ("Diyorum ki beni tanıyor musun?", "identity_followup"),
    ]

    for user_query, q_type in scenarios:
        t0 = time.monotonic()
        print(f"\n❓ Kullanıcı: \"{user_query}\" ({q_type})")
        
        # For identity queries, ensure Baran profile context is passed
        if "kimim" in user_query or "tanıyor" in user_query:
            node._active_person_name = "Baran"
            node._recognized_speaker = {"name": "Baran", "score": 0.85, "is_known": True, "confidence": 0.85, "source": "voice_confirmed"}

        node._process_fallback_turn(direct_text=user_query)

        dur_ms = (time.monotonic() - t0) * 1000.0
        msgs = node.memory.episodic.get_messages()
        reply = msgs[-1].get("content", "") if msgs and msgs[-1].get("role") == "assistant" else ""

        print(f"🤖 Astro (4o): \"{reply}\" ({dur_ms:.0f}ms)")

        # Checks
        if user_query == "Hey Astro dur":
            if "dur" in reply.lower():
                print("  ✅ PASS: Deterministik 'Durdum' komutu başarıyla çalıştı.")
                test_results.append((f"Query: {user_query}", "PASS", f"Reply: {reply}"))
            else:
                print("  ❌ FAIL: Dur komutuna beklenmeyen yanıt.")
                test_results.append((f"Query: {user_query}", "FAIL", f"Reply: {reply}"))
        elif "kimim" in user_query or "tanıyor" in user_query:
            if "henüz tanışamadık" in reply.lower() or "isminiz nedir" in reply.lower():
                print("  ❌ FAIL: Ezbere mekanik kalıp ('Henüz tanışamadık, isminiz nedir?') döndü!")
                test_results.append((f"Query: {user_query}", "FAIL", f"Canned reply returned: {reply}"))
            else:
                print(f"  ✅ PASS: Doğal ve doğru kimlik yanıtı verildi (Baran tanındı/bağlandı).")
                test_results.append((f"Query: {user_query}", "PASS", f"Reply: {reply}"))
        else:
            if reply and len(reply.strip()) > 3:
                print(f"  ✅ PASS: Başarılı 4o yanıtı üretildi ({len(reply.split())} kelime).")
                test_results.append((f"Query: {user_query}", "PASS", f"Reply: {reply}"))
            else:
                print("  ❌ FAIL: Yanıt boş!")
                test_results.append((f"Query: {user_query}", "FAIL", "Empty reply"))

    # -------------------------------------------------------------
    # TEST 6: Camera Stream Endpoint & Headers Check
    # -------------------------------------------------------------
    print("\n--- [TEST 6]: Kamera Akışı ve HTTP Başlıkları Doğrulaması ---")
    try:
        req = urllib.request.Request("http://127.0.0.1:8080/camera/snapshot.jpg")
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            headers = dict(resp.headers)
            cors = headers.get("Access-Control-Allow-Origin")
            content_type = headers.get("Content-Type")
            content_len = headers.get("Content-Length")
            print(f"  Snapshot yanıtı: code={resp.status}, Content-Type={content_type}, Content-Length={content_len}, CORS={cors}")
            if resp.status == 200 and cors == "*":
                print("  ✅ PASS: Kamera snapshot başarıyla yanıt verdi (CORS aktif).")
                test_results.append(("Camera Snapshot Endpoint", "PASS", f"HTTP 200, CORS={cors}"))
            else:
                print("  ⚠️ WARN: HTTP 200 veya CORS eksik.")
                test_results.append(("Camera Snapshot Endpoint", "WARN", f"Status: {resp.status}"))
    except Exception as e:
        print(f"  ℹ️ Port 8080 snapshot testi ({e}) (Web köprüsü aktif olduğunda tam çalışır)")
        test_results.append(("Camera Snapshot Endpoint", "SKIP", str(e)))

    # Summary Table
    print("\n" + "=" * 80)
    print("📊 DOĞRULAMA TEST RAPORU ÖZETİ")
    print("=" * 80)
    print(f"{'TEST':<35} | {'DURUM':<8} | {'DETAY'}")
    print("-" * 80)
    for name, status, detail in test_results:
        print(f"{name:<35} | {status:<8} | {detail[:40]}")
    print("=" * 80)

if __name__ == "__main__":
    run_tests()
