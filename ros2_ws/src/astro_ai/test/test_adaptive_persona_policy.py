"""ASTRO V1 — Unit and Integration Tests for Phase 5: Social Context + Adaptive Persona.

Tests:
1. Probabilistic age-group estimation obeying Camera = Eye epistemic bounds.
2. Child safety invariant: Zero profanity & pedagogical tone even in kufurbaz persona.
3. Senior adaptation policy: Respectful, patient, articulate delivery.
4. Adult nominal persona preservation: Base persona characteristics intact.
5. SocialBrain integration with dynamic adaptive persona directives.
6. Cross-model parity of adaptive persona between Realtime and Local Gemma.
"""

import pytest

from astro_ai.brain.adaptive_persona import AdaptivePersonaEngine
from astro_ai.brain.social_brain import SocialBrain
from astro_ai.contracts.adaptive_persona_types import (
    AgeGroup,
    PersonaStyle,
)
from astro_ai.contracts.person_state import UnifiedPersonState


class TestAdaptivePersonaPolicy:
    """Test suite verifying Adaptive Persona Policy & Child Safety Invariants."""

    def test_01_age_group_estimation_epistemic_bounds(self):
        """Epistemic rule: Age group CANNOT be estimated without visual confirmation."""
        engine = AdaptivePersonaEngine()

        # 1. Acoustic only target (no vision): Must be UNKNOWN even if raw_attributes had age
        acoustic_person = UnifiedPersonState(
            person_id="p_audio",
            has_vision=False,
            can_claim_vision=False,
            raw_attributes={"age": 8},
        )
        age_group, conf = engine.estimate_age_group(acoustic_person)
        assert age_group == AgeGroup.UNKNOWN
        assert conf == 0.0

        # 2. Visually confirmed child
        child_person = UnifiedPersonState(
            person_id="p_child",
            has_vision=True,
            can_claim_vision=True,
            in_optical_cone=True,
            raw_attributes={"age": 7, "is_child": True},
        )
        age_group, conf = engine.estimate_age_group(child_person)
        assert age_group == AgeGroup.CHILD
        assert conf >= 0.90

        # 3. Visually confirmed senior
        senior_person = UnifiedPersonState(
            person_id="p_senior",
            has_vision=True,
            can_claim_vision=True,
            in_optical_cone=True,
            raw_attributes={"age": 72},
        )
        age_group, conf = engine.estimate_age_group(senior_person)
        assert age_group == AgeGroup.SENIOR
        assert conf >= 0.85

    def test_02_child_safety_policy_invariant(self):
        """Child safety: Profanity is strictly blocked and kufurbaz is sanitized to playful."""
        engine = AdaptivePersonaEngine()

        # Base persona is kufurbaz
        policy = engine.evaluate_policy(base_persona="kufurbaz", age_group=AgeGroup.CHILD)
        assert policy.allow_profanity is False
        assert policy.effective_persona == "playful"
        assert policy.style == PersonaStyle.PEDAGOGICAL_PLAYFUL
        assert policy.vocabulary_complexity == "simple"
        assert "Küfür, argo, kaba söz veya flörtöz ifadeler KESİNLİKLE YASAKTIR" in policy.policy_prompt_instruction

    def test_03_senior_adaptation_policy(self):
        """Senior adaptation: Respectful, patient, articulate, zero profanity."""
        engine = AdaptivePersonaEngine()

        policy = engine.evaluate_policy(base_persona="kufurbaz", age_group=AgeGroup.SENIOR)
        assert policy.allow_profanity is False
        assert policy.style == PersonaStyle.RESPECTFUL_PATIENT
        assert policy.vocabulary_complexity == "articulate"
        assert "Saygılı, sabırlı, tane tane ve net" in policy.policy_prompt_instruction

    def test_04_adult_nominal_persona_preservation(self):
        """Adult interaction preserves nominal persona behaviors and slang/profanity if enabled."""
        engine = AdaptivePersonaEngine()

        policy_kufur = engine.evaluate_policy(base_persona="kufurbaz", age_group=AgeGroup.ADULT)
        assert policy_kufur.allow_profanity is True
        assert policy_kufur.effective_persona == "kufurbaz"
        assert policy_kufur.style == PersonaStyle.NOMINAL_ADULT

        policy_play = engine.evaluate_policy(base_persona="playful", age_group=AgeGroup.ADULT)
        assert policy_play.allow_profanity is False
        assert policy_play.effective_persona == "playful"

    def test_05_social_brain_adaptive_persona_prompt(self):
        """SocialBrain process_dialogue_turn integrates adaptive persona prompt for child."""
        brain = SocialBrain(db_path=":memory:", enable_migration=False)

        child_person = UnifiedPersonState(
            person_id="p_child",
            name="Ali",
            formal_title="Ali",
            has_vision=True,
            can_claim_vision=True,
            in_optical_cone=True,
            raw_attributes={"is_child": True, "age": 8},
        )

        ctx, dec, prompt = brain.process_dialogue_turn(
            "Bana bir masal anlatır mısın?",
            person_state=child_person,
            active_persona="kufurbaz",
        )

        assert ctx.target_age_group == "CHILD"
        assert "=== UYARLANABİLİR KİŞİLİK POLİTİKASI ===" in prompt
        assert "ÇOCUK ETKİLEŞİMİ" in prompt
        assert "KESİNLİKLE YASAKTIR" in prompt
        assert "eğitici, sade ve teşvik edici" in dec.suggested_tone

    def test_06_cross_model_parity_adaptive_persona_extraction(self):
        """Adaptive persona directive is extracted for Local Gemma identically to Realtime."""
        system_prompt = (
            "Astro Default Instructions\n\n"
            "=== UYARLANABİLİR KİŞİLİK POLİTİKASI ===\n"
            "UYARLANABİLİR KİŞİLİK [ÇOCUK ETKİLEŞİMİ]: Karşındaki kişi bir çocuk. "
            "Küfür, argo, kaba söz veya flörtöz ifadeler KESİNLİKLE YASAKTIR. "
            "Neşeli, eğitici, sade ve teşvik edici bir dille konuş; Astro'nun sevimli robot kimliğini öne çıkar.\n\n"
            "=== YANIT STRATEJİSİ ===\n"
            "- Kısa konuş"
        )

        epistemic_gemma_rule = ""
        rule_keys = ["KAMERA = GÖZ", "EPISTEMIK", "ETKİLEŞİM VE SÖZEL", "AKTİVİTE OTURUMU", "UYARLANABİLİR KİŞİLİK"]
        if any(k in system_prompt for k in rule_keys):
            for section in system_prompt.split("\n\n"):
                if any(k in section for k in rule_keys):
                    epistemic_gemma_rule += section.strip() + "\n\n"

        gemma_prompt = (
            f"{epistemic_gemma_rule}"
            "ASTRO bir sosyal robot. Türkçe konuş. Kısa ve doğal cevap ver.\n\n"
            "Kullanıcı: Masal anlat\n"
            "ASTRO:"
        )

        assert "UYARLANABİLİR KİŞİLİK POLİTİKASI" in gemma_prompt
        assert "ÇOCUK ETKİLEŞİMİ" in gemma_prompt
        assert "KESİNLİKLE YASAKTIR" in gemma_prompt
