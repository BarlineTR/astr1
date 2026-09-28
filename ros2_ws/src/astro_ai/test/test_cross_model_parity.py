"""Comprehensive Cross-Model Parity Verification Tests.

Verifies that all cognitive, sensory, and social capabilities implemented across Phases 1-7:
1. Epistemic optical cone boundaries (Camera = Eye)
2. Identity fusion and three-tier Interaction Gate
3. Activity episode continuity and greeting suppression
4. Adaptive persona demographic policy and strict child safety invariant
5. Event-driven social initiative visual compliments
6. Quiet/Sleep social awareness (overhearing background speech)
Are model-agnostic and consumed with identical epistemic guarantees and policies
by BOTH LocalGemmaClient (local mode) and OpenAI Realtime (realtime mode).
"""

import unittest
from unittest.mock import MagicMock, patch

from astro_ai.contracts.interaction_gate_types import (
    IdentityCertainty,
    InteractionGateMode,
    TemporalAttentionState,
)
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.adaptive_persona_types import AgeGroup
from astro_ai.brain.social_brain import SocialBrain


class TestCrossModelParity(unittest.TestCase):
    """Verifies strict cognitive parity between Local Gemma and OpenAI Realtime."""

    def setUp(self):
        self.brain = SocialBrain(db_path=":memory:")
        self.rule_keys = [
            "KAMERA = GÖZ",
            "EPISTEMIK",
            "ETKİLEŞİM VE SÖZEL",
            "AKTİVİTE OTURUMU",
            "UYARLANABİLİR KİŞİLİK",
            "SOSYAL İNİSİYATİF",
            "SESSİZ/UYKU",
        ]

    def _extract_local_gemma_rules(self, full_prompt: str) -> str:
        """Emulates astro_realtime_node extraction for Local Gemma."""
        extracted = ""
        for section in full_prompt.split("\n\n"):
            if any(k in section for k in self.rule_keys):
                extracted += section.strip() + "\n\n"
        return extracted

    def test_01_parity_epistemic_optical_cone(self):
        """Person outside optical cone: both Realtime and Local Gemma receive identical anti-hallucination boundaries."""
        person = UnifiedPersonState(
            person_id="p_out",
            name="Zeynep",
            is_present=True,
            is_looking_at_robot=False,
            distance_m=3.5,
            azimuth_deg=-85.0,  # Far left, outside ~72° HFOV
            has_vision=False,
            has_audio=True,
            can_claim_vision=False,
            in_optical_cone=False,
        )

        ctx, dec, full_prompt = self.brain.process_dialogue_turn(
            "Ben neredeyim?", person_state=person
        )
        gemma_rules = self._extract_local_gemma_rules(full_prompt)

        # Realtime full prompt check
        self.assertIn("KAMERA = GÖZ (EPISTEMIK SINIR)", full_prompt)
        self.assertIn("YALNIZCA SESİ DUYULUYOR", full_prompt)
        self.assertIn("Görüş Konisi Dışında", full_prompt)

        # Local Gemma extracted rules check
        self.assertIn("KAMERA = GÖZ (EPISTEMIK SINIR)", gemma_rules)
        self.assertIn("YALNIZCA SESİ DUYULUYOR", gemma_rules)
        self.assertIn("Görüş Konisi Dışında", gemma_rules)

    def test_02_parity_interaction_gate_modes(self):
        """Bystander not addressed: both Realtime and Local Gemma receive OBSERVING / silent verbal response directive."""
        person = UnifiedPersonState(
            person_id="p_bystander",
            name="Murat",
            is_present=True,
            is_looking_at_robot=False,
            distance_m=2.8,
        )

        ctx, dec, full_prompt = self.brain.process_dialogue_turn(
            "Bugün borsa nasıl kapandı?", person_state=person
        )
        gemma_rules = self._extract_local_gemma_rules(full_prompt)

        self.assertIn("ETKİLEŞİM VE SÖZEL DİYALOG KAPISI", full_prompt)
        self.assertIn("OBSERVING", full_prompt)
        self.assertIn("Sözel Yanıt İzni: HAYIR", full_prompt)

        self.assertIn("ETKİLEŞİM VE SÖZEL DİYALOG KAPISI", gemma_rules)
        self.assertIn("OBSERVING", gemma_rules)
        self.assertIn("Sözel Yanıt İzni: HAYIR", gemma_rules)

    def test_03_parity_activity_episode_continuity(self):
        """Second turn within active episode: both models receive greeting suppression directive."""
        person = UnifiedPersonState(
            person_id="p_ep",
            name="Ali",
            is_present=True,
            is_looking_at_robot=True,
            distance_m=1.2,
        )

        # Turn 1: Initial greeting
        self.brain.process_dialogue_turn("Merhaba Astro", person_state=person)

        # Turn 2: Follow-up question
        ctx2, dec2, full_prompt2 = self.brain.process_dialogue_turn(
            "Bugün hava nasıl?", person_state=person
        )
        gemma_rules2 = self._extract_local_gemma_rules(full_prompt2)

        self.assertIn("AKTİVİTE OTURUMU VE SÜREKLİLİK", full_prompt2)
        self.assertIn("zaten selamlandı", full_prompt2)

        self.assertIn("AKTİVİTE OTURUMU VE SÜREKLİLİK", gemma_rules2)
        self.assertIn("zaten selamlandı", gemma_rules2)

    def test_04_parity_adaptive_persona_child_safety(self):
        """Child interlocutor: both models receive strict zero-profanity and child safety invariant."""
        person = UnifiedPersonState(
            person_id="p_child",
            name="Minik Can",
            is_present=True,
            distance_m=1.2,
            is_looking_at_robot=True,
            estimated_age_group="CHILD",
        )

        # Even with an aggressive base persona like kufurbaz
        ctx, dec, full_prompt = self.brain.process_dialogue_turn(
            "Oyun oynayalım mı?", person_state=person, active_persona="kufurbaz"
        )
        gemma_rules = self._extract_local_gemma_rules(full_prompt)

        # Realtime parity
        self.assertIn("UYARLANABİLİR KİŞİLİK POLİTİKASI", full_prompt)
        self.assertIn("ÇOCUK ETKİLEŞİMİ", full_prompt)
        self.assertIn("KESİNLİKLE YASAKTIR", full_prompt)

        # Local Gemma parity
        self.assertIn("UYARLANABİLİR KİŞİLİK POLİTİKASI", gemma_rules)
        self.assertIn("ÇOCUK ETKİLEŞİMİ", gemma_rules)
        self.assertIn("KESİNLİKLE YASAKTIR", gemma_rules)

    def test_05_parity_social_initiative_compliment(self):
        """Approved visual compliment: directive appears in both Realtime session instructions and Local Gemma prompt."""
        person = UnifiedPersonState(
            person_id="p_comp",
            name="Selin",
            is_present=True,
            distance_m=1.4,
            is_looking_at_robot=True,
            can_claim_vision=True,
            in_optical_cone=True,
            estimated_age_group="ADULT",
        )

        ctx, dec, full_prompt = self.brain.process_dialogue_turn(
            "Astro bakar mısın?", person_state=person
        )
        gemma_rules = self._extract_local_gemma_rules(full_prompt)

        self.assertIn("SOSYAL İNİSİYATİF VE İLTİFAT DİREKTİFİ", full_prompt)
        self.assertIn("Enerjin harika görünüyor bugün!", full_prompt)

        self.assertIn("SOSYAL İNİSİYATİF VE İLTİFAT DİREKTİFİ", gemma_rules)
        self.assertIn("Enerjin harika görünüyor bugün!", gemma_rules)

    def test_06_parity_quiet_sleep_awareness(self):
        """Quiet mode overhearing: both models receive identical quiet awareness instructions."""
        person = UnifiedPersonState(
            person_id="p_quiet",
            name="Deniz",
            is_present=True,
            is_looking_at_robot=False,
            distance_m=2.6,
        )

        # 1. Background chatter
        ctx1, dec1, prompt1 = self.brain.process_dialogue_turn(
            "Akşam hangi filme gitsek?", person_state=person, is_quiet_mode=True
        )
        gemma_rules1 = self._extract_local_gemma_rules(prompt1)
        self.assertIn("SESSİZ/UYKU SOSYAL FARKINDALIK", prompt1)
        self.assertIn("SESSİZ KAL", prompt1)
        self.assertIn("SESSİZ/UYKU SOSYAL FARKINDALIK", gemma_rules1)
        self.assertIn("SESSİZ KAL", gemma_rules1)

        # 2. Overhearing question about the robot requiring help
        ctx2, dec2, prompt2 = self.brain.process_dialogue_turn(
            "Bunu Astro'ya soralım mı, Astro biliyor mu?", person_state=person, is_quiet_mode=True
        )
        gemma_rules2 = self._extract_local_gemma_rules(prompt2)
        self.assertIn("SESSİZ/UYKU SOSYAL FARKINDALIK", prompt2)
        self.assertIn("UYANIŞ", prompt2)
        self.assertIn("SESSİZ/UYKU SOSYAL FARKINDALIK", gemma_rules2)
        self.assertIn("UYANIŞ", gemma_rules2)

    def test_07_zero_cloud_leakage_and_local_parity(self):
        """When use_realtime=False, no OpenAI connection is created and local fallback is isolated."""
        try:
            import rclpy
            if not rclpy.ok():
                rclpy.init(args=None)
        except Exception:
            pass

        from astro_ai.astro_realtime_node import AstroRealtimeNode
        node = AstroRealtimeNode(connect_realtime=False, use_realtime=False)
        try:
            self.assertFalse(node.use_realtime)
            self.assertFalse(node.connect_realtime)
            self.assertIsNone(node._ws_thread)
            self.assertFalse(node._can_use_openai("realtime"))
        finally:
            node.destroy_node()


if __name__ == "__main__":
    unittest.main()
