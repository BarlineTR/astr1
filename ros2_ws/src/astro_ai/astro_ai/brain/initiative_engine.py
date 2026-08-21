"""ASTRO V1 — Proactive Initiative and Social Timing Engine."""

import time
from typing import Optional, Tuple

from astro_ai.contracts.intent_emotion_types import ConversationPhase
from astro_ai.contracts.person_state import UnifiedPersonState


class InitiativeEngine:
    """Calculates proactive engagement probabilities and social timing decisions."""

    def __init__(self, cooldown_s: float = 30.0):
        self.cooldown_s = cooldown_s
        self._last_initiative_time = 0.0

    def evaluate_initiative(
        self,
        social_phase: ConversationPhase,
        primary_person: Optional[UnifiedPersonState],
        silence_duration_s: float,
        is_robot_speaking: bool,
    ) -> Tuple[bool, str, float]:
        """Returns (ShouldInitiate, Reason, ProbabilityScore)."""
        now = time.time()

        # Rule 1: Never interrupt when robot or user is already speaking
        if is_robot_speaking or primary_person is None or not primary_person.is_present:
            return False, "not_appropriate", 0.0

        # Rule 2: Cooldown check
        if (now - self._last_initiative_time) < self.cooldown_s:
            return False, "in_cooldown", 0.0

        # Scenario A: Greet when Orienting or Noticing a known/close person
        if social_phase == ConversationPhase.GREETING or (social_phase == ConversationPhase.ORIENTING and primary_person.is_looking_at_robot):
            self._last_initiative_time = now
            return True, "proactive_greeting", 0.90

        # Scenario B: Contextual check-in when silence extends between 8s and 14s while person is still engaged
        if social_phase == ConversationPhase.ENGAGED and 8.0 <= silence_duration_s <= 14.0 and primary_person.is_looking_at_robot:
            self._last_initiative_time = now
            return True, "re_engagement_prompt", 0.75

        # Scenario C: Polite farewell when disengaging
        if social_phase == ConversationPhase.DISENGAGING and silence_duration_s > 20.0:
            self._last_initiative_time = now
            return True, "polite_farewell", 0.85

        return False, "wait_silently", 0.0
