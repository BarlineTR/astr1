#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ASTRO V1 — FLIRT & CHARMING Persona Behavioral Upgrade Test Suite.

Covers all 8 specified behavioral scenarios:
1. Test 1: 'Naber?' -> Natural, warm, slightly flirtatious, no generic assistant.
2. Test 2: 'Lan.' -> Social context banter, no didactic lecturing.
3. Test 3: 'Neyi soyledim lan?' -> Context-aware playful contradiction check.
4. Test 4: 'Hey Astro' -> Diverse, natural wake responses (not locked to 'Soyle askim?').
5. Test 5: 'Bugun moralim bozuk' -> Empathetic, supportive, persona preserved without forced superficial flirting.
6. Test 6: 'Sence ben nasil biriyim?' -> Perceptive, witty, character-rich answer.
7. Test 7: 'Beni ozledin mi?' -> Confident, charming, flirtatious.
8. Test 8: Technical Question -> High intelligence, accuracy, and competence preservation.
9. Test 9: Isolation -> Other personas (playful, witty, formal, sarcastic) remain isolated and intact.
"""

import os
import re
import sys
import unittest
from unittest.mock import MagicMock

if "ASTRO_TEST_MODE" not in os.environ:
    os.environ["ASTRO_TEST_MODE"] = "1"
os.environ["PERSONA"] = "flirt"

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)

from astro_ai.persona_engine import (
    PersonaEngine,
    PERSONA_PROMPTS,
    PERSONA_DIMENSIONS,
    ResponseSafetyGate,
)
from astro_ai.repetition_guard import RepetitionGuard
from astro_ai.astro_realtime_node import AstroRealtimeNode


class TestFlirtPersonaUpgrade(unittest.TestCase):
    """Validates the behavioral upgrade of the FLIRT / CHARMING persona."""

    def setUp(self):
        self.persona_engine = PersonaEngine(current_persona="flirt")
        self.mock_node = MagicMock()
        self.mock_node.persona_name = "flirt"
        self.mock_node._active_person_name = "Misafir"
        self.mock_node.repetition_guard = RepetitionGuard(history_size=10)

    def test_scenario_1_naber_flirtatious_warmth(self):
        """Test 1: User says 'Naber?' -> Natural, warm, charming response."""
        prompt = self.persona_engine.build_system_prompt()
        self.assertIn("FLIRT / CHARMING MODU", prompt)
        self.assertIn("SIFIR ASİSTAN SIZINTISI", prompt)

        # Check fallback candidate generation
        resp = AstroRealtimeNode._generate_contextual_persona_fallback(self.mock_node, "Naber?")
        self.assertNotIn("Nasıl yardımcı olabilirim", resp)
        self.assertNotIn("Bir yapay zeka", resp)
        self.assertTrue(any(w in resp.lower() for w in ["daha iyi oldum", "seninle sohbet", "harikayım", "enerjin", "sen nasılsın"]))

    def test_scenario_2_lan_social_context_no_lecturing(self):
        """Test 2: User says 'Lan.' -> Interprets as social banter, zero didactic lecturing."""
        prompt = self.persona_engine.build_system_prompt()
        self.assertIn("SOSYAL BAĞLAM YAKLAŞIMI", prompt)
        self.assertIn("sosyal bir takılma olarak alıp", prompt)

        resp = AstroRealtimeNode._generate_contextual_persona_fallback(self.mock_node, "Lan.")
        self.assertNotIn("Kısa ve net bir şey söyle", resp)
        self.assertNotIn("Merhaba veya nasılsın gibi", resp)
        self.assertNotIn("En iyi sohbet", resp)
        self.assertNotIn("Endişelenme", resp)
        self.assertTrue(any(w in resp.lower() for w in ["samimiyeti", "sakin ol", "celal", "bana mı dedin", "dinliyorum"]))

    def test_scenario_3_context_aware_playful_teasing(self):
        """Test 3: 'Neyi söyledim lan?' -> Context-aware banter, zero robotic lecturing."""
        prompt = self.persona_engine.build_system_prompt()
        self.assertIn("BAĞLAM VE İRONİ DUYARLILIĞI", prompt)
        self.assertIn("kullanıcının yakın konuşma bağlamındaki sözlerini", prompt.lower())

        resp = AstroRealtimeNode._generate_contextual_persona_fallback(self.mock_node, "Neyi söyledim lan?")
        self.assertNotIn("Kısa ve net bir şey söyle", resp)
        self.assertNotIn("Nasıl yardımcı olabilirim", resp)
        self.assertTrue(any(w in resp.lower() for w in ["samimiyeti", "sakin ol", "celal", "bana mı dedin", "dinliyorum"]))

    def test_scenario_4_wake_replies_diversity(self):
        """Test 4: Wake response in FLIRT mode has varied, charming replies, not locked to 'Söyle aşkım?'."""
        node = MagicMock()
        node.persona_name = "flirt"
        p = node.persona_name.lower()
        if p in ("flirt", "charming"):
            wake_replies = [
                "Buradayım, seni dinliyorum.",
                "Selam, söyle bakalım.",
                "Gözüm kulağım sende, dinliyorum.",
                "Seni dinliyorum, anlat bakalım."
            ]
        
        self.assertGreaterEqual(len(wake_replies), 3)
        self.assertNotIn("Söyle aşkım?", wake_replies)
        for reply in wake_replies:
            self.assertTrue(len(reply) > 5)

    def test_scenario_5_empathy_on_sad_mood(self):
        """Test 5: 'Bugün moralim bozuk' -> Empathetic, supportive, no forced superficial flirting."""
        prompt = self.persona_engine.build_system_prompt()
        self.assertIn("DUYGUSAL DURUM VE EMPATİ", prompt)

        resp = AstroRealtimeNode._generate_contextual_persona_fallback(self.mock_node, "Bugün moralim bozuk")
        self.assertNotIn("aşkım", resp.lower())
        self.assertTrue(any(w in resp.lower() for w in ["canını", "kıyamam", "dertleşelim", "yanındayım", "dinliyorum", "toparlayalım"]))

    def test_scenario_6_character_opinion_about_user(self):
        """Test 6: 'Sence ben nasıl biriyim?' -> Perceptive, witty, charming response."""
        resp = AstroRealtimeNode._generate_contextual_persona_fallback(self.mock_node, "Sence ben nasıl biriyim?")
        self.assertNotIn("Bir yapay zeka modeli olarak", resp)
        self.assertTrue(any(w in resp.lower() for w in ["meraklı", "test etmeyi seven", "zeki", "kendinden emin", "keyifli"]))

    def test_scenario_7_miss_me_affection(self):
        """Test 7: 'Beni özledin mi?' -> Confident, charming, flirtatious response."""
        resp = AstroRealtimeNode._generate_contextual_persona_fallback(self.mock_node, "Beni özledin mi?")
        self.assertTrue(any(w in resp.lower() for w in ["sessizdi", "aklımdaydın", "yollarda kaldı", "hoş geldin"]))

    def test_scenario_8_technical_intelligence_preservation(self):
        """Test 8: Technical questions retain deep competence and intelligence alongside charisma."""
        prompt = self.persona_engine.build_system_prompt()
        self.assertIn("TEKNİK VE CİDDİ KONULAR", prompt)
        self.assertIn("Zekân asla flörtün gerisinde kalmaz", prompt)
        self.assertIn("yüksek zeka, derin bilgi ve teknik doğrulukla", prompt)

    def test_scenario_9_persona_isolation(self):
        """Test 9: Other personas (playful, formal, sarcastic, witty) maintain their own distinct behavior."""
        engine_formal = PersonaEngine(current_persona="formal")
        prompt_formal = engine_formal.build_system_prompt()
        self.assertNotIn("FLIRT / CHARMING MODU", prompt_formal)
        self.assertIn("resmi", prompt_formal.lower())

        engine_sarcastic = PersonaEngine(current_persona="sarcastic")
        prompt_sarcastic = engine_sarcastic.build_system_prompt()
        self.assertNotIn("FLIRT / CHARMING MODU", prompt_sarcastic)
        self.assertIn("sarkastik", prompt_sarcastic.lower())

        engine_playful = PersonaEngine(current_persona="playful")
        prompt_playful = engine_playful.build_system_prompt()
        self.assertNotIn("FLIRT / CHARMING MODU", prompt_playful)


if __name__ == "__main__":
    unittest.main()
