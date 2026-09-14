"""ASTRO V1 — Social Initiative & Controlled Visual Compliments Engine.

Enforces strict epistemic gating, rate-limiting (cooldown), and mutual gaze
prerequisites on visual compliments.
"""

import time
from typing import Dict, Optional

from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.social_initiative_types import (
    ComplimentTopic,
    VisualComplimentDecision,
)


class SocialInitiativeManager:
    """Manages proactive social initiatives and rate-limited visual compliments."""

    def __init__(self, compliment_cooldown_s: float = 120.0):
        self.compliment_cooldown_s = compliment_cooldown_s
        self._last_compliment_ts: Dict[str, float] = {}

    def evaluate_visual_compliment(
        self,
        person: Optional[UnifiedPersonState],
        gate_mode: str,
        age_group: str = "ADULT",
        now: Optional[float] = None,
    ) -> VisualComplimentDecision:
        """Evaluates prerequisites for delivering a spontaneous visual compliment."""
        t = now if now is not None else time.time()

        # Prerequisite 1: Epistemic boundary — Must have confirmed visual perception
        if person is None or not getattr(person, "can_claim_vision", False):
            return VisualComplimentDecision(
                should_compliment=False,
                topic=ComplimentTopic.NONE,
                compliment_text_suggestion="",
                prompt_directive="",
                reason="EPISTEMIC_NO_VISION",
                timestamp=t,
            )

        # Prerequisite 2: Interaction Gate must be ENGAGED
        if gate_mode != "ENGAGED":
            return VisualComplimentDecision(
                should_compliment=False,
                topic=ComplimentTopic.NONE,
                compliment_text_suggestion="",
                prompt_directive="",
                reason="GATE_NOT_ENGAGED",
                timestamp=t,
            )

        # Prerequisite 3: Mutual gaze is required
        if not getattr(person, "is_looking_at_robot", False):
            return VisualComplimentDecision(
                should_compliment=False,
                topic=ComplimentTopic.NONE,
                compliment_text_suggestion="",
                prompt_directive="",
                reason="NO_MUTUAL_GAZE",
                timestamp=t,
            )

        # Prerequisite 4: Within close social distance (<= 2.0m)
        dist = getattr(person, "distance_m", 2.0)
        if dist > 2.0:
            return VisualComplimentDecision(
                should_compliment=False,
                topic=ComplimentTopic.NONE,
                compliment_text_suggestion="",
                prompt_directive="",
                reason="BEYOND_COMPLIMENT_DISTANCE",
                timestamp=t,
            )

        # Prerequisite 5: Per-person cooldown check (120s)
        pid = person.person_id
        if pid in self._last_compliment_ts:
            last_t = self._last_compliment_ts[pid]
            if (t - last_t) < self.compliment_cooldown_s:
                return VisualComplimentDecision(
                    should_compliment=False,
                    topic=ComplimentTopic.NONE,
                    compliment_text_suggestion="",
                    prompt_directive="",
                    reason="IN_COOLDOWN",
                    timestamp=t,
                )

        # Topic & content selection adapted to age group
        if age_group == "CHILD":
            topic = ComplimentTopic.SMILE_ENERGY
            suggestion = "Gözlerinin içi parlıyor, çok neşelisin!"
        elif age_group == "SENIOR":
            topic = ComplimentTopic.PRESENCE_AURA
            suggestion = "Sizinle sohbet etmek çok keyifli, çok zarifsiniz."
        else:
            topic = ComplimentTopic.SMILE_ENERGY
            suggestion = "Enerjin harika görünüyor bugün!"

        directive = (
            f"SOSYAL İNİSİYATİF [KONTROLLÜ GÖRSEL İLTİFAT]: Kişi kamerada doğrudan görülüyor ve göz teması var. "
            f"Sohbet akışına uygun bir anda doğal şekilde şu iltifatta bulunabilirsin: '{suggestion}'."
        )

        self._last_compliment_ts[pid] = t
        return VisualComplimentDecision(
            should_compliment=True,
            topic=topic,
            compliment_text_suggestion=suggestion,
            prompt_directive=directive,
            reason="APPROVED",
            timestamp=t,
        )
