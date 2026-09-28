#!/usr/bin/env python3
"""Comprehensive test suite for ASTRO Conversation Continuity & Dialogue State v1.

Covers:
  - DialogueState data structures & transient resets
  - DialogueStateManager deterministic resolutions & ambiguity safeguards
  - Choice extraction from assistant utterances
  - Deictic / Pronoun and Ordinal reference resolutions
  - Meta-history questions ("Az önce ne sormuştun?", "Bir önceki sorum neydi?")
  - Local persistent name extraction invariants (negative filters)
  - CognitiveLoop.step() zero LLM/network call behavioral verification
  - Local Gemma prompt bounding (<= 450 tokens)
  - Multi-turn conversation replay scenario (6-turn flow)
"""

from collections import deque
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure ros2_ws paths are loaded
ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))

from astro_ai.contracts.dialogue_state_types import (
    DialogueActType,
    DialogueState,
    TurnRecord,
)
from astro_ai.brain.dialogue_state_manager import (
    CLARIFICATION_PROMPT,
    DialogueStateManager,
)


class TestConversationContinuityAndDialogueState(unittest.TestCase):
    """24 unit tests + 1 six-turn scenario test."""

    def setUp(self):
        self.mgr = DialogueStateManager()

    # ------------------------------------------------------------------
    # Test 01: DialogueState initialization
    # ------------------------------------------------------------------
    def test_01_dialogue_state_initialization(self):
        st = self.mgr.state
        self.assertIsNone(st.active_topic)
        self.assertEqual(st.topic_attributes, {})
        self.assertEqual(st.pending_choices, [])
        self.assertIsNone(st.pending_reference)
        self.assertIsNone(st.unresolved_question)
        self.assertIsNone(st.last_user_question)
        self.assertIsNone(st.last_assistant_question)
        self.assertIsNone(st.last_assistant_statement)
        self.assertIsNone(st.interlocutor_identity)
        self.assertEqual(st.turn_count, 0)
        self.assertEqual(st.current_dialogue_act, DialogueActType.STATEMENT)
        self.assertEqual(len(st.recent_turns), 0)

    # ------------------------------------------------------------------
    # Test 02: Recent turns bounded
    # ------------------------------------------------------------------
    def test_02_recent_turns_bounded(self):
        # Insert 10 turns
        for i in range(10):
            self.mgr.record_assistant_turn(f"Mesaj {i}")
        self.assertEqual(len(self.mgr.state.recent_turns), 6)
        # Ensure only the most recent 6 messages remain
        self.assertEqual(self.mgr.state.recent_turns[-1].text, "Mesaj 9")
        self.assertEqual(self.mgr.state.recent_turns[0].text, "Mesaj 4")

    # ------------------------------------------------------------------
    # Test 03: reset_transient preserves identity
    # ------------------------------------------------------------------
    def test_03_reset_transient_preserves_identity(self):
        self.mgr.update_interlocutor("Eren")
        self.mgr.state.active_topic = "film"
        self.mgr.state.topic_attributes = {"genre": "bilim kurgu"}
        self.mgr.state.pending_choices = ["Interstellar", "Inception"]
        self.mgr.state.pending_reference = "Interstellar"
        self.mgr.state.unresolved_question = "Hangi filmi izleyelim?"
        self.mgr.state.last_user_question = "Ne önerirsin?"
        self.mgr.state.last_assistant_question = "Hangi tür seversin?"

        self.mgr.reset_transient()

        # Transient fields cleared
        self.assertIsNone(self.mgr.state.active_topic)
        self.assertEqual(self.mgr.state.topic_attributes, {})
        self.assertEqual(self.mgr.state.pending_choices, [])
        self.assertIsNone(self.mgr.state.pending_reference)
        self.assertIsNone(self.mgr.state.unresolved_question)
        self.assertIsNone(self.mgr.state.last_user_question)
        self.assertIsNone(self.mgr.state.last_assistant_question)

        # Persistent interlocutor identity preserved
        self.assertEqual(self.mgr.state.interlocutor_identity, "Eren")

    # ------------------------------------------------------------------
    # Test 04: format_dialogue_state_prompt
    # ------------------------------------------------------------------
    def test_04_format_dialogue_state_prompt(self):
        self.mgr.update_interlocutor("Baran")
        self.mgr.state.active_topic = "futbol"
        self.mgr.state.topic_attributes = {"league": "Süper Lig"}
        self.mgr.state.pending_choices = ["Fenerbahçe", "Galatasaray"]
        self.mgr.state.pending_reference = "Galatasaray"
        self.mgr.state.unresolved_question = "Hangi takımı tutuyorsun?"

        prompt = self.mgr.state.format_dialogue_state_prompt()
        self.assertIn("=== DİYALOG DURUMU ===", prompt)
        self.assertIn("Konuştuğun kişi: Baran", prompt)
        self.assertIn("Aktif konu: futbol", prompt)
        self.assertIn("league=Süper Lig", prompt)
        self.assertIn("Fenerbahçe, Galatasaray", prompt)
        self.assertIn("Kullanıcının seçtiği referans: Galatasaray", prompt)
        self.assertIn("Cevap bekleyen soru: Hangi takımı tutuyorsun?", prompt)

    # ------------------------------------------------------------------
    # Test 05: update_interlocutor non-transient
    # ------------------------------------------------------------------
    def test_05_update_interlocutor_non_transient(self):
        self.mgr.update_interlocutor("Zeynep")
        self.assertEqual(self.mgr.state.interlocutor_identity, "Zeynep")
        # 'Misafir' or empty string should reset identity to None
        self.mgr.update_interlocutor("Misafir")
        self.assertIsNone(self.mgr.state.interlocutor_identity)

    # ------------------------------------------------------------------
    # Test 06: Ordinal resolution "birincisi"
    # ------------------------------------------------------------------
    def test_06_ordinal_resolution_birincisi(self):
        self.mgr.state.pending_choices = ["Çay", "Kahve"]
        handled, resolved, res_type = self.mgr.process_user_turn("Birincisi olsun.")
        self.assertFalse(handled)
        self.assertEqual(resolved, "Çay")
        self.assertEqual(res_type, "choice_resolved")
        self.assertEqual(self.mgr.state.pending_reference, "Çay")

    # ------------------------------------------------------------------
    # Test 07: Ordinal resolution "ikincisi"
    # ------------------------------------------------------------------
    def test_07_ordinal_resolution_ikincisi(self):
        self.mgr.state.pending_choices = ["Fenerbahçe", "Galatasaray"]
        handled, resolved, res_type = self.mgr.process_user_turn("İkincisini seçiyorum.")
        self.assertFalse(handled)
        self.assertEqual(resolved, "Galatasaray")
        self.assertEqual(res_type, "choice_resolved")
        self.assertEqual(self.mgr.state.pending_reference, "Galatasaray")

    # ------------------------------------------------------------------
    # Test 08: Ordinal resolution "üçüncüsü"
    # ------------------------------------------------------------------
    def test_08_ordinal_resolution_ucuncusu(self):
        self.mgr.state.pending_choices = ["Elma", "Armut", "Muz"]
        handled, resolved, res_type = self.mgr.process_user_turn("Üçüncüsü lütfen.")
        self.assertFalse(handled)
        self.assertEqual(resolved, "Muz")
        self.assertEqual(res_type, "choice_resolved")
        self.assertEqual(self.mgr.state.pending_reference, "Muz")

    # ------------------------------------------------------------------
    # Test 09: Ordinal resolution out of bounds (ambiguity fallback)
    # ------------------------------------------------------------------
    def test_09_ordinal_resolution_out_of_bounds_ambiguity(self):
        self.mgr.state.pending_choices = ["Yalnızca Bir Seçenek"]
        handled, reply, res_type = self.mgr.process_user_turn("İkincisi")
        self.assertTrue(handled)
        self.assertEqual(reply, CLARIFICATION_PROMPT)
        self.assertEqual(res_type, "clarification")

    # ------------------------------------------------------------------
    # Test 10: Pronoun resolution "onu" with pending reference
    # ------------------------------------------------------------------
    def test_10_pronoun_resolution_onu_with_pending_ref(self):
        self.mgr.state.pending_reference = "Inception"
        handled, resolved, res_type = self.mgr.process_user_turn("Onu biraz anlatır mısın?")
        self.assertFalse(handled)
        self.assertEqual(resolved, "Inception")
        self.assertEqual(res_type, "reference_resolved")

    # ------------------------------------------------------------------
    # Test 11: Pronoun resolution without pending reference (ambiguity)
    # ------------------------------------------------------------------
    def test_11_pronoun_resolution_o_without_pending_ref_ambiguity(self):
        self.mgr.state.pending_reference = None
        handled, reply, res_type = self.mgr.process_user_turn("Onu seçiyorum.")
        self.assertTrue(handled)
        self.assertEqual(reply, CLARIFICATION_PROMPT)
        self.assertEqual(res_type, "clarification")

    # ------------------------------------------------------------------
    # Test 12: Meta-question assistant previous question
    # ------------------------------------------------------------------
    def test_12_meta_question_assistant_previous_question(self):
        self.mgr.record_assistant_turn("Film izlemek ister misin?")
        handled, reply, res_type = self.mgr.process_user_turn("Az önce bana ne sormuştun?")
        self.assertTrue(handled)
        self.assertEqual(res_type, "meta_history_assistant")
        self.assertIn("Film izlemek ister misin?", reply)

    # ------------------------------------------------------------------
    # Test 13: Meta-question assistant previous statement
    # ------------------------------------------------------------------
    def test_13_meta_question_assistant_previous_statement(self):
        self.mgr.record_assistant_turn("Bugün hava çok güzel.")
        handled, reply, res_type = self.mgr.process_user_turn("Az önce ne demiştin?")
        self.assertTrue(handled)
        self.assertEqual(res_type, "meta_history_assistant")
        self.assertIn("Bugün hava çok güzel.", reply)

    # ------------------------------------------------------------------
    # Test 14: Meta-question assistant none asked
    # ------------------------------------------------------------------
    def test_14_meta_question_assistant_none_asked(self):
        handled, reply, res_type = self.mgr.process_user_turn("Sen az önce ne sormuştun?")
        self.assertTrue(handled)
        self.assertEqual(res_type, "meta_history_assistant")
        self.assertEqual(reply, "Az önce henüz sana bir soru sormamıştım.")

    # ------------------------------------------------------------------
    # Test 15: Meta-question user previous question
    # ------------------------------------------------------------------
    def test_15_meta_question_user_previous_question(self):
        self.mgr.process_user_turn("Astro sen kaç yaşındasın?")
        handled, reply, res_type = self.mgr.process_user_turn("Bir önceki sorum neydi?")
        self.assertTrue(handled)
        self.assertEqual(res_type, "meta_history_user")
        self.assertIn("Astro sen kaç yaşındasın?", reply)

    # ------------------------------------------------------------------
    # Test 16: Meta-question user none asked
    # ------------------------------------------------------------------
    def test_16_meta_question_user_none_asked(self):
        handled, reply, res_type = self.mgr.process_user_turn("Önceki sorum neydi?")
        self.assertTrue(handled)
        self.assertEqual(res_type, "meta_history_user")
        self.assertEqual(reply, "Daha önce bana henüz bir soru sormamıştın.")

    # ------------------------------------------------------------------
    # Test 17: Reiterating question
    # ------------------------------------------------------------------
    def test_17_reiterating_question(self):
        self.mgr.state.unresolved_question = "Hangi takımı tutuyorsun?"
        handled, reply, res_type = self.mgr.process_user_turn("Ben sana onu soruyorum zaten.")
        self.assertTrue(handled)
        self.assertEqual(res_type, "reiterate_question")
        self.assertIn("Hangi takımı tutuyorsun?", reply)

    # ------------------------------------------------------------------
    # Test 18: Deterministic choice extraction binary
    # ------------------------------------------------------------------
    def test_18_deterministic_choice_extraction_binary(self):
        self.mgr.record_assistant_turn("Fenerbahçe mi yoksa Galatasaray mı?")
        self.assertEqual(self.mgr.state.pending_choices, ["Fenerbahçe", "Galatasaray"])

    # ------------------------------------------------------------------
    # Test 19: Deterministic choice extraction numbered
    # ------------------------------------------------------------------
    def test_19_deterministic_choice_extraction_numbered(self):
        self.mgr.record_assistant_turn("Şu seçenekler var: 1. Bilim Kurgu 2. Komedi")
        self.assertEqual(self.mgr.state.pending_choices, ["Bilim Kurgu", "Komedi"])

    # ------------------------------------------------------------------
    # Test 20: Deterministic choice extraction negative ambiguous
    # ------------------------------------------------------------------
    def test_20_deterministic_choice_extraction_negative_ambiguous(self):
        self.mgr.record_assistant_turn("Belki sinemaya gidebiliriz veya evde otururuz.")
        self.assertEqual(self.mgr.state.pending_choices, [])

    # ------------------------------------------------------------------
    # Test 21: Topic and attribute detection
    # ------------------------------------------------------------------
    def test_21_topic_and_attribute_detection(self):
        self.mgr.process_user_turn("Bilim kurgu filmleri sever misin?")
        self.assertEqual(self.mgr.state.active_topic, "film")
        self.assertEqual(self.mgr.state.topic_attributes.get("genre"), "bilim kurgu")

    # ------------------------------------------------------------------
    # Test 22: Local name extraction strict with negative filters
    # ------------------------------------------------------------------
    def test_22_local_name_extraction_strict(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        node = AstroRealtimeNode.__new__(AstroRealtimeNode)

        # Valid self-introduction patterns
        self.assertEqual(node._extract_self_introduced_name("Benim adım Baran."), "Baran")
        self.assertEqual(node._extract_self_introduced_name("Adım Zeynep"), "Zeynep")
        self.assertEqual(node._extract_self_introduced_name("İsmim Ali"), "Ali")
        self.assertEqual(node._extract_self_introduced_name("Ben Mehmet, beni kaydet"), "Mehmet")
        self.assertEqual(node._extract_self_introduced_name("Ben Can, beni hatırla"), "Can")

        # Negative tests: ordinary activity, state, or conversation must NEVER be treated as name
        self.assertIsNone(node._extract_self_introduced_name("Ben spor yapıyorum"))
        self.assertIsNone(node._extract_self_introduced_name("Ben iyiyim sen nasılsın"))
        self.assertIsNone(node._extract_self_introduced_name("Ben oturuyorum"))
        self.assertIsNone(node._extract_self_introduced_name("Ben ne yapıyorum?"))
        self.assertIsNone(node._extract_self_introduced_name("Ben ders çalışıyorum"))

    # ------------------------------------------------------------------
    # Test 23: CognitiveLoop.step() zero LLM/network call behavioral check
    # ------------------------------------------------------------------
    def test_23_cognitive_loop_step_zero_llm_zero_network(self):
        from astro_ai.brain.cognitive_loop import CognitiveLoop

        loop = CognitiveLoop()

        with patch("urllib.request.urlopen") as mock_urlopen, \
             patch("http.client.HTTPConnection") as mock_http:
            # Execute step
            result = loop.step()

            # Loop cycle completed normally
            self.assertIsNotNone(result)

            # Zero network calls
            self.assertEqual(mock_urlopen.call_count, 0)
            self.assertEqual(mock_http.call_count, 0)

    # ------------------------------------------------------------------
    # Test 24: Local Gemma prompt bounded under 450 tokens
    # ------------------------------------------------------------------
    def test_24_local_gemma_prompt_bounded_under_450_tokens(self):
        from astro_ai.astro_realtime_node import estimate_tokens

        self.mgr.update_interlocutor("Baran")
        self.mgr.state.active_topic = "film"
        self.mgr.state.pending_reference = "Inception"
        self.mgr.state.pending_choices = ["Inception", "Interstellar"]

        # Long simulated recent history (6 turns)
        hist_lines = [
            "Kullanıcı: Hangi filmleri önerirsin?",
            "ASTRO: Inception veya Interstellar olabilir.",
            "Kullanıcı: Inception konusu nedir?",
            "ASTRO: Rüya içinde rüya katmanlarını anlatan harika bir bilim kurgudur.",
            "Kullanıcı: İkincisi nasıldır?",
            "ASTRO: Uzay zamanda yolculuk ve kara delik üzerine muhteşem bir yapımdır.",
        ]
        history_block = "=== SON KONUŞMA ===\n" + "\n".join(hist_lines)
        ds_block = self.mgr.state.format_dialogue_state_prompt()

        prompt = (
            "Sen ASTRO'sun, sevimli, zeki ve yardımsever bir sosyal robotsun. Türkçe konuş. Kısa ve doğal cevap ver (1-2 cümle).\n"
            "Sohbet zaten başladı: selamlama cümlesi kurma, önceki cevabını tekrarlama, yalnızca son söylenene yanıt ver.\n\n"
            f"{ds_block}\n\n"
            f"{history_block}\n\n"
            "Kullanıcı: Interstellar filmini daha detaylı anlatır mısın?\nASTRO:"
        )
        tokens = estimate_tokens(prompt)
        self.assertLessEqual(tokens, 450, f"Local Gemma prompt {tokens} tokens exceeded 450 token hard limit")

    # ------------------------------------------------------------------
    # Test 25: Multi-turn conversation replay scenario (6 turns)
    # ------------------------------------------------------------------
    def test_25_multi_turn_replay_scenario(self):
        """Replays a 6-turn interaction validating full state continuity."""
        # Turn 1: User introduces topic
        handled, resolved, res_type = self.mgr.process_user_turn("Bana bir film önerir misin?")
        self.assertFalse(handled)
        self.assertEqual(self.mgr.state.active_topic, "film")
        self.assertEqual(self.mgr.state.last_user_question, "Bana bir film önerir misin?")

        # Assistant offers choices
        self.mgr.record_assistant_turn("Inception mı yoksa Interstellar mı?")
        self.assertEqual(self.mgr.state.pending_choices, ["Inception", "Interstellar"])

        # Turn 2: User selects by ordinal
        handled, resolved, res_type = self.mgr.process_user_turn("İkincisi")
        self.assertFalse(handled)
        self.assertEqual(resolved, "Interstellar")
        self.assertEqual(self.mgr.state.pending_reference, "Interstellar")

        # Assistant answers about Interstellar
        self.mgr.record_assistant_turn("Interstellar, solucan deliğinden geçen astronotların hikâyesidir.")

        # Turn 3: User references entity by deictic pronoun
        handled, resolved, res_type = self.mgr.process_user_turn("Onu kim yönetti?")
        self.assertFalse(handled)
        self.assertEqual(resolved, "Interstellar")

        # Assistant responds with director
        self.mgr.record_assistant_turn("Yönetmeni Christopher Nolan'dır.")

        # Turn 4: User asks meta-history question about assistant
        handled, reply, res_type = self.mgr.process_user_turn("Az önce ne demiştin?")
        self.assertTrue(handled)
        self.assertIn("Yönetmeni Christopher Nolan'dır.", reply)

        # Turn 5: User asks meta-history question about self
        handled, reply, res_type = self.mgr.process_user_turn("Bir önceki sorum neydi?")
        self.assertTrue(handled)
        self.assertIn("Onu kim yönetti?", reply)

        # Turn 6: Ambiguous choice without choices available
        self.mgr.state.pending_choices.clear()
        handled, reply, res_type = self.mgr.process_user_turn("İkincisini seçiyorum.")
        self.assertTrue(handled)
        self.assertEqual(reply, CLARIFICATION_PROMPT)


if __name__ == "__main__":
    unittest.main()
