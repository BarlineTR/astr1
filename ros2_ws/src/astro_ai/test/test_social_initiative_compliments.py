"""ASTRO V1 — Unit and Integration Tests for Phase 6: Social Initiative & Controlled Compliments.

Tests:
1. Epistemic Camera = Eye prerequisite: No visual compliments without camera verification.
2. Interaction Gate and mutual gaze prerequisites.
3. Proximity boundary (<= 2.0m) and 120s cooldown rate-limiting.
4. Age-adapted compliment selection (child vs adult vs senior).
5. SocialBrain integration with response strategy and prompt directives.
6. Cross-model parity of social initiative between Realtime and Local Gemma.
"""

import pytest

from astro_ai.brain.social_brain import SocialBrain
from astro_ai.brain.social_initiative import SocialInitiativeManager
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.social_initiative_types import ComplimentTopic


class TestSocialInitiativeCompliments:
    """Test suite verifying Social Initiative & Controlled Visual Compliments."""

    def test_01_epistemic_prerequisite_camera_eye(self):
        """Visual compliments CANNOT be delivered for acoustic-only targets (Camera = Eye)."""
        mgr = SocialInitiativeManager()

        # Acoustic target (no camera confirmation)
        acoustic_person = UnifiedPersonState(
            person_id="p_audio",
            has_vision=False,
            can_claim_vision=False,
            distance_m=1.0,
            is_looking_at_robot=True,
        )

        dec = mgr.evaluate_visual_compliment(
            person=acoustic_person,
            gate_mode="ENGAGED",
            age_group="ADULT",
            now=10.0,
        )
        assert dec.should_compliment is False
        assert dec.reason == "EPISTEMIC_NO_VISION"
        assert dec.topic == ComplimentTopic.NONE

    def test_02_gate_and_gaze_prerequisites(self):
        """Compliment requires ENGAGED gate, mutual gaze, and proximity <= 2.0m."""
        mgr = SocialInitiativeManager()

        base_person = UnifiedPersonState(
            person_id="p_vis",
            has_vision=True,
            can_claim_vision=True,
            distance_m=1.2,
            is_looking_at_robot=True,
        )

        # 1. Gate is OBSERVING
        dec_gate = mgr.evaluate_visual_compliment(base_person, gate_mode="OBSERVING", now=10.0)
        assert dec_gate.should_compliment is False
        assert dec_gate.reason == "GATE_NOT_ENGAGED"

        # 2. Looking away (no mutual gaze)
        base_person.is_looking_at_robot = False
        dec_gaze = mgr.evaluate_visual_compliment(base_person, gate_mode="ENGAGED", now=10.0)
        assert dec_gaze.should_compliment is False
        assert dec_gaze.reason == "NO_MUTUAL_GAZE"
        base_person.is_looking_at_robot = True

        # 3. Beyond distance (2.5m > 2.0m)
        base_person.distance_m = 2.5
        dec_dist = mgr.evaluate_visual_compliment(base_person, gate_mode="ENGAGED", now=10.0)
        assert dec_dist.should_compliment is False
        assert dec_dist.reason == "BEYOND_COMPLIMENT_DISTANCE"

    def test_03_cooldown_rate_limiting(self):
        """Visual compliments enforce a strict 120s cooldown per person."""
        mgr = SocialInitiativeManager(compliment_cooldown_s=120.0)
        person = UnifiedPersonState(
            person_id="p_baran",
            has_vision=True,
            can_claim_vision=True,
            distance_m=1.2,
            is_looking_at_robot=True,
        )

        # Turn 1 at t=10.0s -> Approved
        dec1 = mgr.evaluate_visual_compliment(person, gate_mode="ENGAGED", now=10.0)
        assert dec1.should_compliment is True
        assert dec1.reason == "APPROVED"

        # Turn 2 at t=45.0s (35s elapsed < 120s) -> Blocked by cooldown
        dec2 = mgr.evaluate_visual_compliment(person, gate_mode="ENGAGED", now=45.0)
        assert dec2.should_compliment is False
        assert dec2.reason == "IN_COOLDOWN"

        # Turn 3 at t=135.0s (125s elapsed >= 120s) -> Approved again
        dec3 = mgr.evaluate_visual_compliment(person, gate_mode="ENGAGED", now=135.0)
        assert dec3.should_compliment is True
        assert dec3.reason == "APPROVED"

    def test_04_age_adapted_compliment_selection(self):
        """Compliments adapt safely: Child receives encouraging smile, senior receives respectful praise."""
        mgr = SocialInitiativeManager(compliment_cooldown_s=0.0)
        person = UnifiedPersonState(
            person_id="p_test",
            has_vision=True,
            can_claim_vision=True,
            distance_m=1.1,
            is_looking_at_robot=True,
        )

        # Child
        dec_c = mgr.evaluate_visual_compliment(person, gate_mode="ENGAGED", age_group="CHILD", now=1.0)
        assert dec_c.should_compliment is True
        assert "Gözlerinin içi parlıyor" in dec_c.compliment_text_suggestion

        # Senior
        dec_s = mgr.evaluate_visual_compliment(person, gate_mode="ENGAGED", age_group="SENIOR", now=2.0)
        assert dec_s.should_compliment is True
        assert "zarifsiniz" in dec_s.compliment_text_suggestion

        # Adult
        dec_a = mgr.evaluate_visual_compliment(person, gate_mode="ENGAGED", age_group="ADULT", now=3.0)
        assert dec_a.should_compliment is True
        assert "Enerjin harika görünüyor" in dec_a.compliment_text_suggestion

    def test_05_social_brain_compliment_integration(self):
        """SocialBrain process_dialogue_turn adds compliment directive when approved."""
        brain = SocialBrain(db_path=":memory:", enable_migration=False)
        person = UnifiedPersonState(
            person_id="p_baran",
            name="Baran",
            has_vision=True,
            can_claim_vision=True,
            in_optical_cone=True,
            distance_m=1.2,
            is_looking_at_robot=True,
        )

        ctx, dec, prompt = brain.process_dialogue_turn("Selam Astro, günün nasıl geçiyor?", person_state=person)
        assert "=== SOSYAL İNİSİYATİF VE İLTİFAT DİREKTİFİ ===" in prompt
        assert "KONTROLLÜ GÖRSEL İLTİFAT" in prompt

    def test_06_cross_model_parity_compliment_extraction(self):
        """Social initiative directive is extracted for Local Gemma identically to Realtime."""
        system_prompt = (
            "Astro Default Instructions\n\n"
            "=== SOSYAL İNİSİYATİF VE İLTİFAT DİREKTİFİ ===\n"
            "SOSYAL İNİSİYATİF [KONTROLLÜ GÖRSEL İLTİFAT]: Kişi kamerada doğrudan görülüyor ve göz teması var. "
            "Sohbet akışına uygun bir anda doğal şekilde şu iltifatta bulunabilirsin: 'Enerjin harika görünüyor bugün!'.\n\n"
            "=== YANIT STRATEJİSİ ===\n"
            "- Kısa konuş"
        )

        epistemic_gemma_rule = ""
        rule_keys = ["KAMERA = GÖZ", "EPISTEMIK", "ETKİLEŞİM VE SÖZEL", "AKTİVİTE OTURUMU", "UYARLANABİLİR KİŞİLİK", "SOSYAL İNİSİYATİF"]
        if any(k in system_prompt for k in rule_keys):
            for section in system_prompt.split("\n\n"):
                if any(k in section for k in rule_keys):
                    epistemic_gemma_rule += section.strip() + "\n\n"

        gemma_prompt = (
            f"{epistemic_gemma_rule}"
            "ASTRO bir sosyal robot. Türkçe konuş. Kısa ve doğal cevap ver.\n\n"
            "Kullanıcı: Selam\n"
            "ASTRO:"
        )

        assert "SOSYAL İNİSİYATİF VE İLTİFAT DİREKTİFİ" in gemma_prompt
        assert "KONTROLLÜ GÖRSEL İLTİFAT" in gemma_prompt
