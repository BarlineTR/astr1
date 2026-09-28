"""Unit tests for Forensic FIX 4 — SocialBrain Action Semantics.

Ensures:
1. SocialAction enum distinguishes orient, observe, remain_quiet, engage, dialogue_response.
2. action is never a boolean and action=True does not mean speak.
3. intent=GREETING, directive=dialogue_response, action=SocialAction.DIALOGUE_RESPONSE can ONLY occur
   on a validated user turn (explicit_user_turn=True).
4. Perception events (person_detected, orient_to_stimulus, face_detected, gaze_detected) NEVER
   produce dialogue_response or should_speak=True.
5. In-memory SQLite storage (:memory:) is strictly used to protect astro_cognitive.db.
"""

import pytest
from astro_ai.contracts.intent_emotion_types import (
    ConversationPhase,
    EmotionSignal,
    IntentType,
    RelationshipRole,
)
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.social_context import SocialAction, SocialContext, SocialDecision
from astro_ai.brain.response_planner import ResponsePlanner
from astro_ai.brain.social_brain import SocialBrain


@pytest.fixture
def social_brain():
    """Provides SocialBrain initialized strictly with isolated in-memory DB."""
    brain = SocialBrain(db_path=":memory:", enable_migration=False)
    return brain


class TestForensicFix4SocialActionSemantics:
    """Forensic Fix 4 Verification Suite."""

    def test_01_social_action_enum_semantics(self):
        """1. SocialAction enum distinguishes all required physical and dialogue action states."""
        assert SocialAction.ORIENT == "orient"
        assert SocialAction.OBSERVE == "observe"
        assert SocialAction.REMAIN_QUIET == "remain_quiet"
        assert SocialAction.ENGAGE == "engage"
        assert SocialAction.DIALOGUE_RESPONSE == "dialogue_response"

        # Action is never equal to a boolean True/False
        assert SocialAction.DIALOGUE_RESPONSE is not True
        assert SocialAction.OBSERVE is not True
        assert not isinstance(SocialAction.OBSERVE, bool)
        assert not isinstance(SocialAction.DIALOGUE_RESPONSE, bool)

    def test_02_perception_stimulus_person_detected_never_produces_dialogue(self, social_brain):
        """2. person_detected perception stimulus produces OBSERVE, never DIALOGUE_RESPONSE."""
        p = UnifiedPersonState(
            person_id="p1",
            name="Baran",
            formal_title="Geliştirici",
            is_known=True,
            is_present=True,
        )
        dec = social_brain.process_perception_stimulus(
            stimulus_type="person_detected",
            person_state=p,
            is_quiet_mode=False,
        )
        assert dec.should_speak is False
        assert dec.action == SocialAction.OBSERVE
        assert dec.directive == "observe"
        assert dec.action != SocialAction.DIALOGUE_RESPONSE
        assert dec.directive != "dialogue_response"

    def test_03_perception_stimulus_orient_never_produces_dialogue(self, social_brain):
        """3. orient_to_stimulus perception stimulus produces ORIENT, never DIALOGUE_RESPONSE."""
        p = UnifiedPersonState(
            person_id="p2",
            name="Misafir",
            is_present=True,
        )
        dec = social_brain.process_perception_stimulus(
            stimulus_type="orient_to_stimulus",
            person_state=p,
            is_quiet_mode=False,
        )
        assert dec.should_speak is False
        assert dec.action == SocialAction.ORIENT
        assert dec.directive == "orient"
        assert dec.action != SocialAction.DIALOGUE_RESPONSE
        assert dec.directive != "dialogue_response"

    def test_04_perception_stimulus_quiet_mode_produces_remain_quiet(self, social_brain):
        """4. In quiet mode, perception stimuli strictly produce REMAIN_QUIET."""
        p = UnifiedPersonState(person_id="p3", name="Baran", is_present=True)
        dec = social_brain.process_perception_stimulus(
            stimulus_type="person_detected",
            person_state=p,
            is_quiet_mode=True,
        )
        assert dec.should_speak is False
        assert dec.action == SocialAction.REMAIN_QUIET
        assert dec.directive == "remain_quiet"

    def test_05_greeting_with_no_explicit_user_turn_cannot_produce_dialogue_response(self, social_brain):
        """5. Even if intent is GREETING, explicit_user_turn=False produces OBSERVE and should_speak=False."""
        p = UnifiedPersonState(
            person_id="p4",
            name="Baran",
            formal_title="Geliştirici Baran",
            is_known=True,
            is_present=True,
            is_looking_at_robot=True,
            can_claim_vision=True,
        )

        ctx, dec, prompt = social_brain.process_dialogue_turn(
            user_text="merhaba",
            person_state=p,
            is_quiet_mode=False,
            explicit_user_turn=False,
        )

        assert ctx.user_intent == IntentType.GREETING
        assert dec.should_speak is False
        assert dec.action == SocialAction.OBSERVE
        assert dec.directive == "observe"
        assert dec.action != SocialAction.DIALOGUE_RESPONSE
        assert dec.directive != "dialogue_response"
        assert dec.action is not True

    def test_06_validated_user_turn_allows_dialogue_response(self, social_brain):
        """6. When explicit_user_turn=True, dialogue response is formulated with DIALOGUE_RESPONSE action."""
        p = UnifiedPersonState(
            person_id="p5",
            name="Baran",
            formal_title="Geliştirici Baran",
            is_known=True,
            is_present=True,
            is_looking_at_robot=True,
            can_claim_vision=True,
        )

        ctx, dec, prompt = social_brain.process_dialogue_turn(
            user_text="merhaba",
            person_state=p,
            is_quiet_mode=False,
            explicit_user_turn=True,
        )

        assert ctx.user_intent == IntentType.GREETING
        assert dec.should_speak is True
        assert dec.action == SocialAction.DIALOGUE_RESPONSE
        assert dec.directive == "dialogue_response"
        assert dec.action is not True

    def test_07_activity_query_with_explicit_user_turn(self, social_brain):
        """7. Activity query with explicit_user_turn=True produces DIALOGUE_RESPONSE with should_speak=True."""
        p = UnifiedPersonState(
            person_id="p6",
            name="Baran",
            is_known=True,
            is_present=True,
            is_looking_at_robot=True,
        )

        ctx, dec, prompt = social_brain.process_dialogue_turn(
            user_text="ben şu anda ne yapıyorum?",
            person_state=p,
            is_quiet_mode=False,
            explicit_user_turn=True,
        )

        assert ctx.user_intent == IntentType.ACTIVITY_QUERY
        assert dec.should_speak is True
        assert dec.action == SocialAction.DIALOGUE_RESPONSE
        assert dec.directive == "dialogue_response"

    def test_08_response_planner_explicit_turn_gating(self):
        """8. ResponsePlanner respects explicit_user_turn on SocialContext."""
        ctx_no_turn = SocialContext(
            person_id="p7",
            person_name="Baran",
            formal_title="Baran",
            relationship_role=RelationshipRole.CREATOR,
            familiarity=0.9,
            trust=0.9,
            conversation_phase=ConversationPhase.ENGAGED,
            user_intent=IntentType.GREETING,
            user_mood="neutral",
            user_valence=0.0,
            user_arousal=0.0,
            engagement_level=0.8,
            is_looking_at_robot=True,
            distance_m=1.0,
            explicit_user_turn=False,
        )
        dec_no_turn = ResponsePlanner.plan_response_strategy(ctx_no_turn)
        assert dec_no_turn.should_speak is False
        assert dec_no_turn.action == SocialAction.OBSERVE
        assert dec_no_turn.directive == "observe"

        ctx_turn = SocialContext(
            person_id="p8",
            person_name="Baran",
            formal_title="Baran",
            relationship_role=RelationshipRole.CREATOR,
            familiarity=0.9,
            trust=0.9,
            conversation_phase=ConversationPhase.ENGAGED,
            user_intent=IntentType.GREETING,
            user_mood="neutral",
            user_valence=0.0,
            user_arousal=0.0,
            engagement_level=0.8,
            is_looking_at_robot=True,
            distance_m=1.0,
            explicit_user_turn=True,
        )
        dec_turn = ResponsePlanner.plan_response_strategy(ctx_turn)
        assert dec_turn.should_speak is True
        assert dec_turn.action == SocialAction.DIALOGUE_RESPONSE
        assert dec_turn.directive == "dialogue_response"
