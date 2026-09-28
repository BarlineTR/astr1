"""ASTRO V1 — Social Interaction Finite State Machine (Social FSM)."""

import time
from typing import Optional

from astro_ai.contracts.intent_emotion_types import ConversationPhase
from astro_ai.contracts.person_state import UnifiedPersonState


class SocialFSM:
    """Manages high-level social phases of human-robot encounter and interaction."""

    def __init__(self):
        self._current_phase = ConversationPhase.UNATTENDED
        self._phase_entered_time = time.time()
        self._last_interaction_time = 0.0

    @property
    def current_phase(self) -> ConversationPhase:
        return self._current_phase

    def step(
        self,
        primary_person: Optional[UnifiedPersonState],
        is_user_speaking: bool,
        is_robot_speaking: bool,
        silence_duration_s: float,
    ) -> ConversationPhase:
        """Evaluates sensory cues and transitions social phase."""
        now = time.time()

        if primary_person is None or not primary_person.is_present:
            if self._current_phase != ConversationPhase.UNATTENDED:
                if (now - self._phase_entered_time) > 4.0:
                    self._transition(ConversationPhase.UNATTENDED)
            return self._current_phase

        # Person is present
        if self._current_phase == ConversationPhase.UNATTENDED:
            if primary_person.is_looking_at_robot or primary_person.distance_m < 2.0:
                self._transition(ConversationPhase.ORIENTING)
            else:
                self._transition(ConversationPhase.NOTICE_PERSON)

        elif self._current_phase == ConversationPhase.NOTICE_PERSON:
            if primary_person.is_looking_at_robot or primary_person.distance_m < 2.0:
                self._transition(ConversationPhase.ORIENTING)

        elif self._current_phase == ConversationPhase.ORIENTING:
            if is_user_speaking:
                self._transition(ConversationPhase.ENGAGED)
            elif (now - self._phase_entered_time) > 2.0:
                self._transition(ConversationPhase.GREETING)

        elif self._current_phase in (ConversationPhase.GREETING, ConversationPhase.ENGAGED, ConversationPhase.RESPONDING):
            if is_user_speaking:
                self._transition(ConversationPhase.LISTENING)
            elif is_robot_speaking:
                self._transition(ConversationPhase.RESPONDING)
            elif silence_duration_s > 18.0:
                self._transition(ConversationPhase.DISENGAGING)

        elif self._current_phase == ConversationPhase.DISENGAGING:
            if is_user_speaking:
                self._transition(ConversationPhase.ENGAGED)
            elif silence_duration_s > 25.0:
                self._transition(ConversationPhase.FAREWELL)

        elif self._current_phase == ConversationPhase.FAREWELL:
            if (now - self._phase_entered_time) > 3.0:
                self._transition(ConversationPhase.UNATTENDED)

        return self._current_phase

    def _transition(self, new_phase: ConversationPhase):
        if self._current_phase != new_phase:
            self._current_phase = new_phase
            self._phase_entered_time = time.time()
