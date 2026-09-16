#!/usr/bin/env python3
"""Yerel modda kullanıcı adı kalıcı hafızaya yazılmalı.

Canlı testte (2026-09-15) "Ben Yunus Emre tamam, beni yeniden kaydet." denildi,
robot "Tamam, Yunus Emre." dedi, ama memory.json'da known_people yalnızca seed
kaydı ("baran") olarak kaldı. Sebep: kalıcı hafızaya yazan tek yol
`_execute_realtime_tool` (save_user_memory / enroll_user_biometrics) ve bu yol
sadece OpenAI Realtime araç çağrısıyla erişilebiliyor. use_realtime=false olan
yerel/Ollama modunda hiçbir araç çalışmıyor, dolayısıyla hiçbir şey kaydedilmiyor.
"""

import os
import sys
import unittest

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

from astro_ai.astro_realtime_node import AstroRealtimeNode


class TestLocalNameMemory(unittest.TestCase):

    def setUp(self):
        try:
            import rclpy
            if not rclpy.ok():
                rclpy.init(args=None)
        except Exception:
            pass
        self.node = AstroRealtimeNode(connect_realtime=False)
        self.node.use_realtime = False

    def tearDown(self):
        try:
            self.node.destroy_node()
        except Exception:
            pass

    def test_01_kendini_tanitma_ismi_cikariliyor(self):
        cases = {
            "Ben Yunus Emre tamam, beni yeniden kaydet.": "Yunus Emre",
            "Benim adım Yunus Emre.": "Yunus Emre",
            "İsmim Ayşe, unutma.": "Ayşe",
            "adım Mehmet": "Mehmet",
        }
        for text, expected in cases.items():
            self.assertEqual(self.node._extract_self_introduced_name(text), expected, f"girdi: {text!r}")

    def test_02_yanlis_pozitif_yok(self):
        for text in (
            "Ben kimim?",
            "Ben de iyiyim, teşekkür ederim.",
            "Ben neredeyim şu anda?",
            "Bana hızlı bir hikaye anlat.",
            "Ben kameranın neresindeyim şu anda?",
            "Hey Astro, nasılsın?",
        ):
            self.assertIsNone(self.node._extract_self_introduced_name(text), f"yanlış pozitif: {text!r}")

    def test_03_yerel_modda_profile_yaziliyor(self):
        learned = self.node._learn_user_name_locally("Ben Yunus Emre tamam, beni yeniden kaydet.")
        self.assertEqual(learned, "Yunus Emre")

        person = self.node.memory.profile.get_known_person("Yunus Emre")
        self.assertIsNotNone(person, "known_people'a yazılmadı")
        self.assertEqual(person.get("name"), "Yunus Emre")
        # add_person_preference anahtarı küçük harfe indiriyor (memory_manager.py:390).
        self.assertEqual(self.node.memory.profile.get_user_facts("Yunus Emre").get("ad"), "Yunus Emre")

    def test_04_ogrenilen_isim_prompt_baglamina_giriyor(self):
        self.node._learn_user_name_locally("Benim adım Yunus Emre.")
        ctx = self.node.memory.get_prompt_context()
        self.assertIn("Yunus Emre", ctx)


if __name__ == "__main__":
    unittest.main()
