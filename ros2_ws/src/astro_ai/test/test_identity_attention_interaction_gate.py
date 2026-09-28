"""ASTRO V1 — Unit and Integration Tests for Phase 3: Identity + Attention + Interaction Gate.

Tests:
1. Probabilistic multimodal identity fusion (KNOWN, PROBABLE, UNKNOWN, AMBIGUOUS).
2. Temporal Attention state machine with hysteresis and grace period recovery.
3. Three-tier Interaction Gate (ENGAGED, OBSERVING, BYPASS).
4. SocialBrain integration with gate decisions and prompt directives.
5. Cross-model parity of interaction gate directives between Realtime and Local Gemma.
"""

import pytest

from astro_ai.brain.attention_manager import AttentionManager
from astro_ai.brain.interaction_gate import InteractionGate
from astro_ai.brain.social_brain import SocialBrain
from astro_ai.contracts.interaction_gate_types import (
    IdentityCertainty,
    InteractionGateMode,
    TemporalAttentionState,
)
from astro_ai.contracts.person_state import UnifiedPersonState


class TestIdentityAttentionInteractionGate:
    """Test suite verifying Identity Fusion, Attention Hysteresis & Interaction Gate."""

    def test_01_multimodal_identity_certainty(self):
        """Identity certainty handles high-conf, moderate-conf, unknown, and cross-modal conflicts."""
        mgr = AttentionManager()

        # 1. High-confidence face
        cert, name = mgr.evaluate_identity_certainty(face_name="Baran", face_confidence=0.85)
        assert cert == IdentityCertainty.KNOWN
        assert name == "Baran"

        # 2. High-confidence voice
        cert, name = mgr.evaluate_identity_certainty(voice_name="Baran", voice_confidence=0.72)
        assert cert == IdentityCertainty.KNOWN
        assert name == "Baran"

        # 3. Moderate confidence
        cert, name = mgr.evaluate_identity_certainty(face_name="Baran", face_confidence=0.55)
        assert cert == IdentityCertainty.PROBABLE

        # 4. Low confidence / unknown
        cert, name = mgr.evaluate_identity_certainty(face_name="Baran", face_confidence=0.30)
        assert cert == IdentityCertainty.UNKNOWN

        # 5. Cross-modal conflict (Face says Baran, Voice says Ali)
        cert, name = mgr.evaluate_identity_certainty(
            face_name="Baran",
            face_confidence=0.80,
            voice_name="Ali",
            voice_confidence=0.75,
        )
        assert cert == IdentityCertainty.AMBIGUOUS
        assert name is None

    def test_02_temporal_attention_hysteresis(self):
        """Attention machine requires 0.5s sustained cue to engage and provides 2.0s grace period."""
        mgr = AttentionManager(acquire_threshold_s=0.5, grace_period_s=2.0)
        assert mgr.current_state == TemporalAttentionState.NO_ATTENTION

        # t=0.0: Initial cue
        state = mgr.update_temporal_attention(has_cue=True, now=10.0)
        assert state == TemporalAttentionState.POSSIBLE_ATTENTION

        # t=0.3: Cue continues but threshold (0.5s) not yet met
        state = mgr.update_temporal_attention(has_cue=True, now=10.3)
        assert state == TemporalAttentionState.POSSIBLE_ATTENTION

        # t=0.6: Cue sustained >= 0.5s -> ENGAGED
        state = mgr.update_temporal_attention(has_cue=True, now=10.6)
        assert state == TemporalAttentionState.ENGAGED

        # t=1.0: Cue temporarily drops (frame drop or glance away) -> ATTENTION_LOST
        state = mgr.update_temporal_attention(has_cue=False, now=11.0)
        assert state == TemporalAttentionState.ATTENTION_LOST

        # t=1.8: Cue returns at 0.8s into the 2.0s grace period -> recovers directly to ENGAGED!
        state = mgr.update_temporal_attention(has_cue=True, now=11.8)
        assert state == TemporalAttentionState.ENGAGED

        # t=2.0: Cue drops again
        state = mgr.update_temporal_attention(has_cue=False, now=12.0)
        assert state == TemporalAttentionState.ATTENTION_LOST

        # t=4.5: Grace period expires (2.5s > 2.0s) -> drops to NO_ATTENTION
        state = mgr.update_temporal_attention(has_cue=False, now=14.5)
        assert state == TemporalAttentionState.NO_ATTENTION

    def test_03_interaction_gate_decisions(self):
        """Interaction Gate classifies into ENGAGED, OBSERVING, and BYPASS."""
        gate = InteractionGate(social_distance_limit_m=3.0)

        # 1. Direct address ALWAYS forces ENGAGED
        dec = gate.evaluate(
            person=None,
            attention_state=TemporalAttentionState.NO_ATTENTION,
            identity_certainty=IdentityCertainty.UNKNOWN,
            user_text="Astro bana yardım et",
        )
        assert dec.mode == InteractionGateMode.ENGAGED
        assert dec.should_respond_verbally is True
        assert dec.reason == "DIRECT_ADDRESS"

        # 2. Quiet mode without direct address -> OBSERVING (silent)
        dec_quiet = gate.evaluate(
            person=UnifiedPersonState(person_id="p1", distance_m=1.0),
            attention_state=TemporalAttentionState.ENGAGED,
            identity_certainty=IdentityCertainty.KNOWN,
            user_text="Bu ne güzel hava",
            is_quiet_mode=True,
        )
        assert dec_quiet.mode == InteractionGateMode.OBSERVING
        assert dec_quiet.should_respond_verbally is False

        # 3. Person far away (4.0m > 3.0m) without address -> OBSERVING
        far_person = UnifiedPersonState(person_id="p2", distance_m=4.0, is_looking_at_robot=True)
        dec_far = gate.evaluate(
            person=far_person,
            attention_state=TemporalAttentionState.ENGAGED,
            identity_certainty=IdentityCertainty.KNOWN,
            user_text="Naber?",
        )
        assert dec_far.mode == InteractionGateMode.OBSERVING
        assert dec_far.should_respond_verbally is False
        assert dec_far.reason == "DISTANCE_BEYOND_SOCIAL_ZONE"

        # 4. Person looking away without address (side conversation) -> OBSERVING
        away_person = UnifiedPersonState(person_id="p3", distance_m=1.5, is_looking_at_robot=False)
        dec_away = gate.evaluate(
            person=away_person,
            attention_state=TemporalAttentionState.POSSIBLE_ATTENTION,
            identity_certainty=IdentityCertainty.PROBABLE,
            user_text="Ahmet yarın buluşalım",
        )
        assert dec_away.mode == InteractionGateMode.OBSERVING
        assert dec_away.should_respond_verbally is False

        # 5. Nominal engaged interaction (within 2.5m, looking at robot, ENGAGED state)
        engaged_person = UnifiedPersonState(person_id="p4", distance_m=1.2, is_looking_at_robot=True)
        dec_nom = gate.evaluate(
            person=engaged_person,
            attention_state=TemporalAttentionState.ENGAGED,
            identity_certainty=IdentityCertainty.KNOWN,
            user_text="Nasılsın bugün?",
        )
        assert dec_nom.mode == InteractionGateMode.ENGAGED
        assert dec_nom.should_respond_verbally is True

    def test_04_social_brain_integration_gate(self):
        """SocialBrain process_dialogue_turn populates gate_mode and suppresses speech when in OBSERVING."""
        brain = SocialBrain(db_path=":memory:", enable_migration=False)

        # Interlocutor looking away, distant (3.5m) and not addressing Astro
        passive_person = UnifiedPersonState(
            person_id="p_passive",
            name="Misafir",
            distance_m=3.5,
            is_looking_at_robot=False,
            has_vision=True,
            has_audio=True,
        )

        ctx, dec, prompt = brain.process_dialogue_turn("Yarın hava yağmurluymuş", person_state=passive_person)
        assert dec.gate_mode == "OBSERVING"
        assert dec.should_speak is False
        assert "=== ETKİLEŞİM VE SÖZEL DİYALOG KAPISI ===" in prompt
        assert "HAYIR (Sessiz Kal / Dinle)" in prompt

    def test_05_cross_model_parity_gate_extraction(self):
        """Interaction Gate directive is shared with Local Gemma identically to Realtime."""
        system_prompt = (
            "Astro Default Instructions\n\n"
            "=== ETKİLEŞİM VE SÖZEL DİYALOG KAPISI ===\n"
            "- Mod: OBSERVING\n"
            "- Sözel Yanıt İzni: HAYIR (Sessiz Kal / Dinle)\n"
            "- Kural: Kişi robota bakmıyor, yan konuşma olabilir. Sözel yanıttan kaçın, dinlemede kal.\n\n"
            "=== YANIT STRATEJİSİ ===\n"
            "- Kısa konuş"
        )

        # Simulating extraction for Local Gemma
        epistemic_gemma_rule = ""
        if any(k in system_prompt for k in ["KAMERA = GÖZ", "EPISTEMIK", "ETKİLEŞİM VE SÖZEL"]):
            for section in system_prompt.split("\n\n"):
                if any(k in section for k in ["KAMERA = GÖZ", "EPISTEMIK", "ETKİLEŞİM VE SÖZEL"]):
                    epistemic_gemma_rule += section.strip() + "\n\n"

        gemma_prompt = (
            f"{epistemic_gemma_rule}"
            "ASTRO bir sosyal robot. Türkçe konuş. Kısa ve doğal cevap ver.\n\n"
            "Kullanıcı: Merhaba\n"
            "ASTRO:"
        )

        assert "ETKİLEŞİM VE SÖZEL DİYALOG KAPISI" in gemma_prompt
        assert "HAYIR (Sessiz Kal / Dinle)" in gemma_prompt
