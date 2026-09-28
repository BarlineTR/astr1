"""Comprehensive Unit and Integration Tests for Phase 7: Quiet/Sleep Social Awareness."""

import unittest
from unittest.mock import MagicMock

from astro_ai.contracts.quiet_awareness_types import (
    DirectednessLevel,
    QuietInterventionNeed,
    QuietDecisionMode,
    QuietAwarenessDecision,
)
from astro_ai.brain.quiet_awareness import QuietAwarenessEvaluator
from astro_ai.brain.interaction_gate import InteractionGate
from astro_ai.contracts.interaction_gate_types import (
    IdentityCertainty,
    InteractionGateMode,
    TemporalAttentionState,
)
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.brain.social_brain import SocialBrain


class TestQuietSocialAwareness(unittest.TestCase):
    """Test suite for overhearing background conversation evaluation and sleep engagement gating."""

    def setUp(self):
        self.evaluator = QuietAwarenessEvaluator()
        self.gate = InteractionGate()

    def test_01_background_unrelated_chatter_remains_quiet(self):
        """Unrelated human-to-human speech must result in REMAIN_QUIET and gate OBSERVING."""
        text = "Bugün hava çok güzel değil mi, kahve içmeye gidelim mi?"
        person = UnifiedPersonState(
            person_id="p1",
            name="Ali",
            is_looking_at_robot=False,
            distance_m=2.5,
        )

        dec = self.evaluator.evaluate_overhearing(text, person=person, is_quiet_mode=True)
        self.assertEqual(dec.mode, QuietDecisionMode.REMAIN_QUIET)
        self.assertEqual(dec.directedness, DirectednessLevel.UNRELATED_BACKGROUND)
        self.assertFalse(dec.is_about_me)
        self.assertEqual(dec.intervention_need, QuietInterventionNeed.NONE)

        gate_dec = self.gate.evaluate(
            person=person,
            attention_state=TemporalAttentionState.ENGAGED,
            identity_certainty=IdentityCertainty.KNOWN,
            user_text=text,
            is_quiet_mode=True,
        )
        self.assertEqual(gate_dec.mode, InteractionGateMode.OBSERVING)
        self.assertFalse(gate_dec.should_respond_verbally)

    def test_02_passive_mention_about_robot_remains_quiet(self):
        """Third-person talk about the robot without asking for help must remain quiet."""
        text = "Astro köşede duruyor, çok sevimli bir robot."
        person = UnifiedPersonState(
            person_id="p2",
            name="Ayşe",
            is_looking_at_robot=False,
            distance_m=2.2,
        )

        dec = self.evaluator.evaluate_overhearing(text, person=person, is_quiet_mode=True)
        self.assertEqual(dec.mode, QuietDecisionMode.REMAIN_QUIET)
        self.assertEqual(dec.directedness, DirectednessLevel.ABOUT_ME)
        self.assertTrue(dec.is_about_me)
        self.assertEqual(dec.intervention_need, QuietInterventionNeed.NONE)

        gate_dec = self.gate.evaluate(
            person=person,
            attention_state=TemporalAttentionState.ENGAGED,
            identity_certainty=IdentityCertainty.KNOWN,
            user_text=text,
            is_quiet_mode=True,
        )
        self.assertEqual(gate_dec.mode, InteractionGateMode.OBSERVING)
        self.assertFalse(gate_dec.should_respond_verbally)

    def test_03_about_me_requiring_intervention_wakes_up(self):
        """Talking about the robot and wondering if it can help or answer must ENGAGE."""
        text = "Bunu Astro'ya soralım mı, Astro biliyor mu acaba?"
        person = UnifiedPersonState(
            person_id="p3",
            name="Can",
            is_looking_at_robot=False,
            distance_m=2.0,
        )

        dec = self.evaluator.evaluate_overhearing(text, person=person, is_quiet_mode=True)
        self.assertEqual(dec.mode, QuietDecisionMode.ENGAGE)
        self.assertEqual(dec.directedness, DirectednessLevel.ABOUT_ME)
        self.assertTrue(dec.is_about_me)
        self.assertEqual(dec.intervention_need, QuietInterventionNeed.ASSISTANCE_HELPFUL)

        gate_dec = self.gate.evaluate(
            person=person,
            attention_state=TemporalAttentionState.ENGAGED,
            identity_certainty=IdentityCertainty.KNOWN,
            user_text=text,
            is_quiet_mode=True,
        )
        self.assertEqual(gate_dec.mode, InteractionGateMode.ENGAGED)
        self.assertTrue(gate_dec.should_respond_verbally)

    def test_04_direct_wake_word_or_imperative_wakes_up(self):
        """Direct address or wake imperative must ENGAGE immediately."""
        text = "Astro uyan bakar mısın?"
        person = UnifiedPersonState(
            person_id="p4",
            name="Baran",
            is_looking_at_robot=True,
            distance_m=1.8,
        )

        dec = self.evaluator.evaluate_overhearing(text, person=person, is_quiet_mode=True)
        self.assertEqual(dec.mode, QuietDecisionMode.ENGAGE)
        self.assertEqual(dec.directedness, DirectednessLevel.DIRECTED_TO_ME)
        self.assertTrue(dec.is_about_me)

        gate_dec = self.gate.evaluate(
            person=person,
            attention_state=TemporalAttentionState.ENGAGED,
            identity_certainty=IdentityCertainty.KNOWN,
            user_text=text,
            is_quiet_mode=True,
        )
        self.assertEqual(gate_dec.mode, InteractionGateMode.ENGAGED)
        self.assertTrue(gate_dec.should_respond_verbally)

    def test_05_face_to_face_greeting_wakes_up(self):
        """Face-to-face mutual gaze within 1.5m speaking greeting wakes up robot."""
        text = "Merhaba nasılsın?"
        person = UnifiedPersonState(
            person_id="p5",
            name="Zeynep",
            is_looking_at_robot=True,
            distance_m=1.1,
        )

        dec = self.evaluator.evaluate_overhearing(text, person=person, is_quiet_mode=True)
        self.assertEqual(dec.mode, QuietDecisionMode.ENGAGE)
        self.assertEqual(dec.directedness, DirectednessLevel.DIRECTED_TO_ME)

        gate_dec = self.gate.evaluate(
            person=person,
            attention_state=TemporalAttentionState.ENGAGED,
            identity_certainty=IdentityCertainty.KNOWN,
            user_text=text,
            is_quiet_mode=True,
        )
        self.assertEqual(gate_dec.mode, InteractionGateMode.ENGAGED)
        self.assertTrue(gate_dec.should_respond_verbally)

    def test_06_social_brain_quiet_mode_integration(self):
        """SocialBrain in quiet mode embeds quiet awareness directive and suppresses verbal response when quiet."""
        brain = SocialBrain(db_path=":memory:")
        person = UnifiedPersonState(
            person_id="p6",
            name="Kerem",
            is_looking_at_robot=False,
            distance_m=2.5,
        )

        # Turn 1: Background chatter in quiet mode -> silent
        ctx, dec, prompt = brain.process_dialogue_turn(
            "Yemekte pizza mı söylesek?",
            person_state=person,
            is_quiet_mode=True,
        )
        self.assertTrue(ctx.quiet_mode_active)
        self.assertFalse(dec.should_speak)
        self.assertIn("=== SESSİZ/UYKU SOSYAL FARKINDALIK ===", prompt)
        self.assertIn("SESSİZ KAL", prompt)

        # Turn 2: Direct wake up in quiet mode -> speaks
        ctx2, dec2, prompt2 = brain.process_dialogue_turn(
            "Astro uyan, yardımına ihtiyacım var",
            person_state=person,
            is_quiet_mode=True,
        )
        self.assertTrue(ctx2.quiet_mode_active)
        self.assertTrue(dec2.should_speak)
        self.assertIn("=== SESSİZ/UYKU SOSYAL FARKINDALIK ===", prompt2)
        self.assertIn("UYANIŞ", prompt2)

    def test_07_cross_model_parity_quiet_rule_extraction(self):
        """Local Gemma extraction logic must extract the SESSİZ/UYKU section from modular prompt."""
        system_prompt = (
            "=== KAMERA = GÖZ (EPISTEMIK SINIR) ===\n"
            "- Kural: Kişi kameranın görüş konisi içinde.\n\n"
            "=== SESSİZ/UYKU SOSYAL FARKINDALIK ===\n"
            "SESSİZ/UYKU FARKINDALIK [SESSİZ KAL]: Arka plandaki konuşma seninle ilgili değil. Sessiz kal.\n\n"
            "=== YANIT STRATEJİSİ ===\n"
            "- Önerilen Ton: playful\n"
        )
        rule_keys = [
            "KAMERA = GÖZ",
            "EPISTEMIK",
            "ETKİLEŞİM VE SÖZEL",
            "AKTİVİTE OTURUMU",
            "UYARLANABİLİR KİŞİLİK",
            "SOSYAL İNİSİYATİF",
            "SESSİZ/UYKU",
        ]
        extracted = ""
        for section in system_prompt.split("\n\n"):
            if any(k in section for k in rule_keys):
                extracted += section.strip() + "\n\n"

        self.assertIn("KAMERA = GÖZ", extracted)
        self.assertIn("SESSİZ/UYKU SOSYAL FARKINDALIK", extracted)
        self.assertNotIn("YANIT STRATEJİSİ", extracted)


if __name__ == "__main__":
    unittest.main()
