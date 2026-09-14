"""ASTRO V1 — Multi-Sensory Attention and Interlocutor Selection Engine.

Features:
1. Multi-cue attention saliency calculation.
2. Multi-modal identity certainty evaluation (KNOWN, PROBABLE, UNKNOWN, AMBIGUOUS).
3. Temporal Attention State Machine with Hysteresis (NO_ATTENTION, POSSIBLE_ATTENTION,
   ATTENTION_ACQUIRED, ENGAGED, ATTENTION_LOST with 2.0s grace period).
"""

import math
import time
from typing import List, Optional, Tuple

from astro_ai.contracts.interaction_gate_types import (
    IdentityCertainty,
    TemporalAttentionState,
)
from astro_ai.contracts.person_state import UnifiedPersonState


class AttentionManager:
    """Calculates saliency, tracks temporal attention hysteresis, and resolves identity certainty."""

    def __init__(self, acquire_threshold_s: float = 0.5, grace_period_s: float = 2.0):
        self._current_attended_id: Optional[str] = None
        self.acquire_threshold_s: float = acquire_threshold_s
        self.grace_period_s: float = grace_period_s

        # Temporal Hysteresis State
        self._state: TemporalAttentionState = TemporalAttentionState.NO_ATTENTION
        self._cue_start_time: Optional[float] = None
        self._cue_lost_time: Optional[float] = None
        self._last_cue_time: float = 0.0

    @property
    def current_state(self) -> TemporalAttentionState:
        return self._state

    def evaluate_identity_certainty(
        self,
        face_name: Optional[str] = None,
        face_confidence: float = 0.0,
        voice_name: Optional[str] = None,
        voice_confidence: float = 0.0,
    ) -> Tuple[IdentityCertainty, Optional[str]]:
        """Evaluates multimodal identity fusion certainty and detects conflicts."""
        f_name_clean = face_name.strip() if face_name and face_name.lower() != "misafir" else None
        v_name_clean = voice_name.strip() if voice_name and voice_name.lower() != "misafir" else None

        # Conflict check: Both modalities have candidate names but they differ
        if f_name_clean and v_name_clean:
            if f_name_clean.lower() != v_name_clean.lower():
                # Both modalities assert different identities with non-trivial confidence
                if face_confidence >= 0.45 and voice_confidence >= 0.45:
                    return IdentityCertainty.AMBIGUOUS, None

            # Both agree on identity
            if face_confidence >= 0.70 or voice_confidence >= 0.65:
                return IdentityCertainty.KNOWN, f_name_clean
            elif face_confidence >= 0.45 or voice_confidence >= 0.45:
                return IdentityCertainty.PROBABLE, f_name_clean

        # Face-only evidence
        if f_name_clean:
            if face_confidence >= 0.70:
                return IdentityCertainty.KNOWN, f_name_clean
            elif face_confidence >= 0.45:
                return IdentityCertainty.PROBABLE, f_name_clean

        # Voice-only evidence
        if v_name_clean:
            if voice_confidence >= 0.65:
                return IdentityCertainty.KNOWN, v_name_clean
            elif voice_confidence >= 0.45:
                return IdentityCertainty.PROBABLE, v_name_clean

        return IdentityCertainty.UNKNOWN, None

    def update_temporal_attention(
        self,
        has_cue: bool,
        now: Optional[float] = None,
    ) -> TemporalAttentionState:
        """Transitions the temporal attention state machine enforcing hysteresis delays."""
        t = now if now is not None else time.time()

        if self._state == TemporalAttentionState.NO_ATTENTION:
            if has_cue:
                self._cue_start_time = t
                self._last_cue_time = t
                self._state = TemporalAttentionState.POSSIBLE_ATTENTION

        elif self._state == TemporalAttentionState.POSSIBLE_ATTENTION:
            if has_cue:
                self._last_cue_time = t
                elapsed = t - (self._cue_start_time or t)
                if elapsed >= self.acquire_threshold_s:
                    self._state = TemporalAttentionState.ENGAGED
            else:
                self._cue_start_time = None
                self._state = TemporalAttentionState.NO_ATTENTION

        elif self._state in (TemporalAttentionState.ATTENTION_ACQUIRED, TemporalAttentionState.ENGAGED):
            if has_cue:
                self._last_cue_time = t
                self._state = TemporalAttentionState.ENGAGED
            else:
                self._cue_lost_time = t
                self._state = TemporalAttentionState.ATTENTION_LOST

        elif self._state == TemporalAttentionState.ATTENTION_LOST:
            if has_cue:
                # Recovered within grace period!
                self._last_cue_time = t
                self._cue_lost_time = None
                self._state = TemporalAttentionState.ENGAGED
            else:
                elapsed_loss = t - (self._cue_lost_time or t)
                if elapsed_loss >= self.grace_period_s:
                    self._state = TemporalAttentionState.NO_ATTENTION
                    self._cue_start_time = None
                    self._cue_lost_time = None

        return self._state

    def select_focus_target(
        self,
        people: List[UnifiedPersonState],
    ) -> Tuple[Optional[UnifiedPersonState], float]:
        """Calculates multi-cue attention scores and returns (AttendedPerson, AttentionScore)."""
        if not people:
            self._current_attended_id = None
            return None, 0.0

        best_person = None
        best_score = -1.0

        for p in people:
            # 1. Speech Activity Cue (Weight: 0.35)
            speech_cue = 1.0 if p.is_speaking else 0.0

            # 2. Gaze / Looking Cue (Weight: 0.25)
            gaze_cue = 1.0 if p.is_looking_at_robot else 0.0

            # 3. Proximity Cue (Weight: 0.20) - Max at 1.0m, decays with distance
            dist = max(0.5, p.distance_m)
            proximity_cue = max(0.0, 1.0 - (dist / 4.0))

            # 4. Familiarity / Known Person Cue (Weight: 0.10)
            fam_cue = p.familiarity_score if p.is_known else 0.2

            # 5. Conversation Continuity / Hysteresis (Weight: 0.10)
            continuity_cue = 1.0 if (self._current_attended_id == p.person_id) else 0.0

            total_score = (
                0.35 * speech_cue
                + 0.25 * gaze_cue
                + 0.20 * proximity_cue
                + 0.10 * fam_cue
                + 0.10 * continuity_cue
            )

            if total_score > best_score:
                best_score = total_score
                best_person = p

        if best_person is not None:
            self._current_attended_id = best_person.person_id

        return best_person, round(best_score, 3)
