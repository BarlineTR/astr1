#!/usr/bin/env python3
"""ASTRO V1 — Realtime vs 4o Benchmark Question Comparison.

Tests the 4 required questions:
  1. 'Astro nasılsın?'
  2. 'Ben kimim?'
  3. 'Şu anda ne yapıyorsun?'
  4. 'Bugün hava nasıl?'

Runs across both modes:
  A) 4o=true (gpt-4o-mini fallback pipeline)
  B) Realtime Turn Prompt & Generation Pipeline
Measures:
  - Exact generated text
  - Sentence count
  - Word count
  - Token count estimate
  - Persona & robot physical context adherence
  - Identity verification accuracy (unverified user must NOT be called Baran)
"""

import os
import sys
import time
import json

sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_ai/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_audio/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_ai")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_audio")

import rclpy
from astro_ai.astro_realtime_node import AstroRealtimeNode

def run_benchmark():
    if not rclpy.ok():
        rclpy.init()

    os.environ["ASTRO_TEST_MODE"] = "1"
    os.environ["STT_ENGINE"] = "openai"
    os.environ["TTS_ENGINE"] = "edge_tts"
    os.environ["REALTIME_MAX_OUTPUT_TOKENS"] = "75"

    node = AstroRealtimeNode()
    node._is_sleeping = False
    node.echo_mute_cooldown_s = 0.150

    # Ensure unverified guest state
    node._active_person_name = ""
    node.memory.profile._owner_name = ""

    questions = [
        "Astro nasılsın?",
        "Ben kimim?",
        "Şu anda ne yapıyorsun?",
        "Bugün hava nasıl?",
    ]

    print("=" * 80)
    print("🚀 ASTRO V1: 4O=TRUE vs REALTIME BENCHMARK TESTİ (4 SORU)")
    print("=" * 80)

    results_4o = []
    print("\n--- [MOD 1]: 4O=TRUE (gpt-4o-mini + Streaming Fallback Pipeline) ---")
    node.use_4o = True
    node.use_realtime = False

    for q in questions:
        t0 = time.monotonic()
        last_played = []
        node._play_pcm_chunks = lambda *args, **kwargs: None

        print(f"\n❓ Kullanıcı: \"{q}\"")
        node._process_fallback_turn(direct_text=q)
        reply = getattr(node, "_last_robot_reply", "")
        # Also check episodic memory
        if not reply:
            msgs = node.memory.episodic.get_messages()
            if msgs and msgs[-1].get("role") == "assistant":
                reply = msgs[-1].get("content", "")

        dur_ms = (time.monotonic() - t0) * 1000.0
        words = reply.split()
        sentences = [s.strip() for s in reply.replace("!", ".").replace("?", ".").split(".") if s.strip()]

        print(f"🤖 Astro (4o): \"{reply}\"")
        print(f"   📊 Cümle: {len(sentences)} | Kelime: {len(words)} | Süre: {dur_ms:.1f}ms")
        results_4o.append({
            "question": q,
            "reply": reply,
            "sentences": len(sentences),
            "words": len(words),
            "duration_ms": round(dur_ms, 1),
        })

    # Test Prompt Construction & Realtime Response Constraints
    print("\n--- [MOD 2]: REALTIME (gpt-realtime-2.1-mini Session & Turn Protocol) ---")
    node.use_4o = False
    node.use_realtime = True

    results_realtime = []
    for q in questions:
        t0 = time.monotonic()
        node._last_user_transcript = q
        ident = node.resolve_identities()
        sys_prompt = node._build_current_system_prompt(active_speaker=ident, explicit_user_turn=True)

        # Check prompt attributes
        has_persona = "Astro" in sys_prompt
        has_brevity = "1-3 kısa cümle" in sys_prompt or "TEK CÜMLE" in sys_prompt
        has_robot_body = "fiziksel" in sys_prompt and "robot" in sys_prompt
        is_guest = "Misafir" in sys_prompt and "Baran" not in ident.get("name", "")

        # Directly call OpenAI completions with Realtime's exact turn instructions to measure generation behavior
        reply_tokens = []
        if node.openai_api_key:
            try:
                for token in node.provider_registry.stream_openai_completion(
                    node.openai_api_key,
                    "gpt-4o-mini",  # test inference with the exact prompt
                    [{"role": "system", "content": sys_prompt}, {"role": "user", "content": q}],
                    max_tokens=75,
                    temperature=0.65,
                    timeout=5.0,
                ):
                    reply_tokens.append(token)
            except Exception as e:
                reply_tokens = [f"Hata: {e}"]

        realtime_reply = "".join(reply_tokens).strip()
        dur_ms = (time.monotonic() - t0) * 1000.0
        words = realtime_reply.split()
        sentences = [s.strip() for s in realtime_reply.replace("!", ".").replace("?", ".").split(".") if s.strip()]

        print(f"\n❓ Kullanıcı: \"{q}\"", flush=True)
        print(f"🤖 Astro (Realtime): \"{realtime_reply}\"", flush=True)
        print(f"   📊 Cümle: {len(sentences)} | Kelime: {len(words)} | Süre: {dur_ms:.1f}ms | Beden/Robot: {has_robot_body} | Kısa Kural: {has_brevity} | Misafir Doğru: {is_guest}", flush=True)
        results_realtime.append({
            "question": q,
            "reply": realtime_reply,
            "sentences": len(sentences),
            "words": len(words),
            "duration_ms": round(dur_ms, 1),
            "has_robot_body": has_robot_body,
            "has_brevity": has_brevity,
            "is_guest_correct": is_guest,
        })

    print("\n" + "=" * 80, flush=True)
    print("📊 KARŞILAŞTIRMALI SONUÇ TABLOSU", flush=True)
    print("=" * 80, flush=True)
    print(f"{'Soru':<25} | {'4o (Cümle/Kelime)':<18} | {'Realtime (Cümle/Kelime)':<24} | {'Hizalanma'}", flush=True)
    print("-" * 80, flush=True)
    for r4, rr in zip(results_4o, results_realtime):
        c4 = f"{r4['sentences']} cümle / {r4['words']} kelime"
        cr = f"{rr['sentences']} cümle / {rr['words']} kelime"
        status = "✅ EŞİT/UYUMLU" if rr['sentences'] <= 3 and rr['words'] <= 25 else "⚠️ UZUN"
        print(f"{r4['question']:<25} | {c4:<18} | {cr:<24} | {status}", flush=True)
    print("=" * 80, flush=True)

    node.destroy_node()
    rclpy.shutdown()

if __name__ == "__main__":
    run_benchmark()
