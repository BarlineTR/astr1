#!/usr/bin/env python3
"""ASTRO V1 — Memory & Identity Persistence Lifecycle Test.

Tests Requirement 7:
  1. Register / Write identity to persistent memory ("Eren").
  2. Query "Ben kimim?" -> Verify recognition ("Sen Eren'sin").
  3. Simulate Process Restart (destroy node and create brand new instance from DB).
  4. Query "Ben kimim?" -> Verify persistent recognition after restart.
"""

import os
import sys
import rclpy

sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_ai/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/install/astro_audio/lib/python3.10/site-packages")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_ai")
sys.path.insert(0, "/home/okistech/Desktop/astr1/ros2_ws/src/astro_audio")

from astro_ai.astro_realtime_node import AstroRealtimeNode

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def test_identity_lifecycle():
    if not rclpy.ok():
        rclpy.init()

    os.environ["ASTRO_TEST_MODE"] = "1"
    os.environ["STT_ENGINE"] = "openai"
    os.environ["TTS_ENGINE"] = "edge_tts"

    print("=" * 75)
    print("🧠 ASTRO V1 — BELLEK & KİMLİK KALICILIK DOĞRULAMA TESTİ")
    print("=" * 75)

    # PHASE 1: İlk Oturum — Kullanıcı Kaydı & Belleğe Yazma
    print("\n[FAZ 1] İlk Düğüm Başlatılıyor ve Kullanıcı Tanımlanıyor...")
    node1 = AstroRealtimeNode()
    
    test_user = "Eren"
    print(f"  📝 Kullanıcı Belleğe Kaydediliyor: {test_user}")
    
    # Save to memory profile and cognitive DB
    if hasattr(node1, "memory") and hasattr(node1.memory, "profile"):
        node1.memory.profile.data["owner_name"] = test_user
        if hasattr(node1.memory.profile, "save"):
            node1.memory.profile.save()
    
    # Also save to social_brain cognitive DB if available
    if hasattr(node1, "social_brain") and node1.social_brain:
        try:
            node1.social_brain.record_person(test_user, role="owner", confidence=0.98)
        except Exception as e:
            print(f"  ⚠️ social_brain.record_person uyarısı: {e}")

    # Set as active session identity
    node1._active_person_name = test_user
    node1._recognized_person = {"name": test_user, "confidence": 0.95}

    # Query "Ben kimim?"
    reply1 = node1._generate_contextual_persona_fallback("ben kimim")
    print(f"  🤖 Astro Yanıtı (Oturum 1): \"{reply1}\"")
    success1 = (test_user.lower() in reply1.lower())
    print(f"  ✅ Tanıma Durumu 1: {'BAŞARILI' if success1 else 'BAŞARISIZ'}")

    # PHASE 2: Process Restart Simülasyonu
    print("\n[FAZ 2] Düğüm Kapatılıyor (Process Shutdown Simülasyonu)...")
    node1.destroy_node()
    del node1

    print("[FAZ 2] Yeni Düğüm Sıfırdan Başlatılıyor (Process Restart)...")
    node2 = AstroRealtimeNode()

    # Query "Ben kimim?" on fresh node without manually injecting identity
    reply2 = node2._generate_contextual_persona_fallback("ben kimim")
    print(f"  🤖 Astro Yanıtı (Oturum 2 - Restart Sonrası): \"{reply2}\"")
    
    # Also check identity resolution
    ident = node2.resolve_identities()
    print(f"  🔍 Çözümlenen Kimlik: {ident.get('session_identity')} (Kaynak: {ident.get('identity_source')})")

    success2 = (test_user.lower() in reply2.lower() or ident.get("session_identity", "").lower() == test_user.lower())
    print(f"  ✅ Restart Sonrası Tanıma: {'BAŞARILI' if success2 else 'BAŞARISIZ'}")

    print("\n" + "=" * 75)
    print(f"🏆 NİHAİ BELLEK KALICILIK SONUCU: {'PASS' if (success1 and success2) else 'FAIL'}")
    print("=" * 75)

if __name__ == "__main__":
    test_identity_lifecycle()
