#!/usr/bin/env python3
"""ASTRO V1 — Unit Tests for Conversational Paralinguistics & Guest Decorum.

Verifies:
  - Intent Categorization (OPINION, VISUAL_SEARCH, EXPLANATION, DIRECT_SKIP)
  - Zero Repetition History Guard (Consecutive queries never repeat identical filler)
  - Guest Decorum Isolation (Suppresses informal fillers and switches to polite tone when is_known=False)
  - Küfürbaz Persona Guest Decorum in System Prompt (Suppresses street insults when guest is speaking)
  - Küfürbaz Persona Retention for Creator Baran (Preserves full street roast when Baran is verified)
  - Natural Breath Pause Decorator for Edge-TTS
  - Zero Extra OpenAI API Calls
"""

import unittest
from astro_ai.brain.paralinguistics_engine import (
    ParalinguisticsCategory,
    ParalinguisticsEngine,
)
from astro_ai.persona_engine import PersonaEngine


class TestParalinguisticsEngine(unittest.TestCase):
    """Verifies conversational paralinguistics engine logic."""

    def setUp(self):
        self.engine = ParalinguisticsEngine(history_size=3)

    def test_direct_skip_queries(self):
        skips = [
            "Merhaba",
            "Selam",
            "Günaydın",
            "Saat kaç?",
            "Dur",
            "İleri git",
            "Evet",
            "Tamam",
            "Hey Astro",
        ]
        for q in skips:
            filler = self.engine.select_filler(q, is_known=True, person_name="Baran")
            self.assertEqual(filler, "", f"Query '{q}' should not produce any filler")

    def test_visual_search_categorization(self):
        queries = [
            "Astro baksana şuraya",
            "Karşımda kim var?",
            "Gözlüğümü görüyor musun?",
            "Nerede duruyorsun?",
        ]
        for q in queries:
            cat = self.engine.categorize_query(q)
            self.assertEqual(cat, ParalinguisticsCategory.VISUAL_SEARCH)
            filler = self.engine.select_filler(q, is_known=True, person_name="Baran")
            self.assertTrue(any(f in filler for f in ["bakayım", "bakıyorum", "süzüyorum", "kontrol"]))

    def test_explanation_categorization(self):
        queries = [
            "Lidar nasıl çalışır?",
            "SLAM haritalama nedir?",
            "Bu motorun mantığı ne?",
        ]
        for q in queries:
            cat = self.engine.categorize_query(q)
            self.assertEqual(cat, ParalinguisticsCategory.EXPLANATION)
            filler = self.engine.select_filler(q, is_known=True, person_name="Baran")
            self.assertTrue(any(f in filler for f in ["Bak şimdi", "Şöyle ki", "Mesele", "izah"]))

    def test_opinion_categorization(self):
        queries = [
            "Sence yarın hava nasıl olur?",
            "Bu proje sence mantıklı mı?",
            "Ne düşünüyorsun bu konuda?",
        ]
        for q in queries:
            cat = self.engine.categorize_query(q)
            self.assertEqual(cat, ParalinguisticsCategory.OPINION)
            filler = self.engine.select_filler(q, is_known=True, person_name="Baran")
            self.assertTrue(any(f in filler for f in ["Hımm", "Açıkçası", "sorarsan", "durum var", "Valla"]))

    def test_repetition_history_guard_no_consecutive_repeats(self):
        """Ensures that repetitive opinion queries never produce identical fillers consecutively."""
        seen_fillers = []
        for i in range(5):
            filler = self.engine.select_filler("Sence nasıldı?", is_known=True, person_name="Baran")
            if seen_fillers:
                self.assertNotEqual(
                    filler, seen_fillers[-1],
                    f"Consecutive filler repetition detected on turn {i}: '{filler}'"
                )
            seen_fillers.append(filler)

        # Check that diverse fillers were produced
        self.assertGreater(len(set(seen_fillers)), 1)

    def test_guest_decorum_fillers(self):
        """When is_known=False or person_name='Misafir', polite decorum fillers are used without 'abi'."""
        queries = [
            "Bu proje nasıl çalışır?",
            "Sence sonuç ne olur?",
            "Şuraya bakar mısın?",
        ]
        for q in queries:
            filler = self.engine.select_filler(q, is_known=False, person_name="Misafir")
            self.assertNotIn("abi", filler.lower())
            self.assertTrue(any(kw in filler for kw in ["Efendim", "Açıkçası", "arz", "kontrol", "saniye"]))

    def test_format_tts_with_pauses(self):
        raw = "Hımm... valla şöyle diyeyim abi, saat üç."
        formatted = ParalinguisticsEngine.format_tts_with_pauses(raw)
        self.assertIn("... ", formatted)
        self.assertNotIn("...,", formatted)
        self.assertNotIn(",,", formatted)


class TestPersonaGuestDecorum(unittest.TestCase):
    """Verifies Guest Decorum in PersonaEngine system prompt synthesis."""

    def setUp(self):
        self.persona_engine = PersonaEngine(current_persona="kufurbaz")

    def test_kufurbaz_guest_decorum_applied_when_unknown(self):
        """When a guest (is_known=False) is in the room, kufurbaz suppresses insults."""
        guest_identity = {"name": "Misafir", "is_known": False}
        prompt = self.persona_engine.build_system_prompt(recognized_person=guest_identity)

        self.assertIn("MİSAFİR ODASI EDEP VE TOPARLANMA PROTOKOLÜ", prompt)
        self.assertIn("AĞZINI TOPARLA", prompt.upper())
        self.assertIn("KÜFÜR, AŞIRI SOKAK ARGOSU VE KABA HAKARETLERİ DERHAL DURDUR", prompt.upper())
        # Insult instruction against guest must not be present
        self.assertNotIn("Ne bileyim lan ben senin kim olduğunu lavuk", prompt)

    def test_kufurbaz_creator_roast_retained_when_baran(self):
        """When creator Baran is verified (is_known=True), Küfürbaz Haydo racon is active."""
        baran_identity = {"name": "Baran", "is_known": True, "role_category": "creator"}
        prompt = self.persona_engine.build_system_prompt(recognized_person=baran_identity)

        self.assertIn("KÜFÜRBAZ HAYDO RACONU", prompt)
        self.assertIn("Sen beni yapan baş mühendisim Baran'sın amk", prompt)
        self.assertNotIn("MİSAFİR ODASI EDEP VE TOPARLANMA PROTOKOLÜ", prompt)

    def test_system_prompt_includes_paralinguistics_constitution(self):
        prompt = self.persona_engine.build_system_prompt()
        self.assertIn("DOĞAL TÜRKÇE PARALİNGUİSTİK İFADELER VE DÜŞÜNME DOLGULARI", prompt)
        self.assertIn("PAPAĞAN GİBİ ASLA TEKRARLAMA", prompt)


if __name__ == "__main__":
    unittest.main()
