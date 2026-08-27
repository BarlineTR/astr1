"""ASTRO V1 — Multi-Sensory Attention and Interlocutor Selection Engine."""

import math
from typing import List, Optional, Tuple

from astro_ai.contracts.person_state import UnifiedPersonState


class AttentionManager:
    """Calculates saliency and selects the primary attended person in multi-speaker environments."""

    def __init__(self):
        self._current_attended_id: Optional[str] = None

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
