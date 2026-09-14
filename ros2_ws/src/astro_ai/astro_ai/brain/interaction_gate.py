"""ASTRO V1 — Interaction Gate Engine.

Three-tier gate governing conversational engagement:
- ENGAGED: Robot actively attends, speaks, and responds.
- OBSERVING: Robot tracks visually and listens, but remains verbally silent unless directly addressed.
- BYPASS: Out-of-scope / background event, ignored.
"""

from typing import Optional

from astro_ai.contracts.interaction_gate_types import (
    IdentityCertainty,
    InteractionGateDecision,
    InteractionGateMode,
    TemporalAttentionState,
)
from astro_ai.contracts.quiet_awareness_types import (
    QuietDecisionMode,
)
from astro_ai.brain.quiet_awareness import QuietAwarenessEvaluator
from astro_ai.contracts.person_state import UnifiedPersonState


class InteractionGate:
    """Evaluates whether ASTRO should engage verbally, observe silently, or bypass."""

    def __init__(self, social_distance_limit_m: float = 3.0):
        self.social_distance_limit_m = social_distance_limit_m
        self.quiet_evaluator = QuietAwarenessEvaluator()

    def is_directly_addressed(self, user_text: str) -> bool:
        """Checks if text contains direct vocatives or references to Astro."""
        if not user_text:
            return False
        clean = user_text.lower().strip()
        wake_words = ["astro", "astrom", "hey astro", "selam astro", "robot"]
        for w in wake_words:
            if w in clean:
                return True
        return False

    def evaluate(
        self,
        person: Optional[UnifiedPersonState],
        attention_state: TemporalAttentionState,
        identity_certainty: IdentityCertainty,
        user_text: str = "",
        is_quiet_mode: bool = False,
    ) -> InteractionGateDecision:
        """Computes authoritative InteractionGateDecision."""
        # Rule 0: Quiet/Sleep Social Awareness (Phase 7)
        if is_quiet_mode:
            quiet_dec = self.quiet_evaluator.evaluate_overhearing(
                user_text=user_text, person=person, is_quiet_mode=True
            )
            if quiet_dec.mode == QuietDecisionMode.ENGAGE:
                return InteractionGateDecision(
                    mode=InteractionGateMode.ENGAGED,
                    attention_state=attention_state,
                    identity_certainty=identity_certainty,
                    should_respond_verbally=True,
                    should_track_with_gaze=True,
                    reason=f"QUIET_MODE_WAKEUP_{quiet_dec.reason}",
                    gating_prompt_instruction=quiet_dec.prompt_instruction,
                )
            else:
                return InteractionGateDecision(
                    mode=InteractionGateMode.OBSERVING,
                    attention_state=attention_state,
                    identity_certainty=identity_certainty,
                    should_respond_verbally=False,
                    should_track_with_gaze=True,
                    reason=f"QUIET_MODE_SILENT_{quiet_dec.reason}",
                    gating_prompt_instruction=quiet_dec.prompt_instruction,
                )

        addressed = self.is_directly_addressed(user_text)

        # Rule 1: Explicit direct address ALWAYS forces ENGAGED
        if addressed:
            return InteractionGateDecision(
                mode=InteractionGateMode.ENGAGED,
                attention_state=attention_state,
                identity_certainty=identity_certainty,
                should_respond_verbally=True,
                should_track_with_gaze=True,
                reason="DIRECT_ADDRESS",
                gating_prompt_instruction=(
                    "ETKİLEŞİM KAPISI [AÇIK — DOĞRUDAN HİTAP]: Kullanıcı doğrudan sana seslendi. "
                    "Doğal ve net bir şekilde sözel yanıt ver."
                ),
            )

        # Rule 3: No person or target out of range (> 5.0m) -> BYPASS
        if person is None:
            return InteractionGateDecision(
                mode=InteractionGateMode.BYPASS,
                attention_state=attention_state,
                identity_certainty=identity_certainty,
                should_respond_verbally=False,
                should_track_with_gaze=False,
                reason="NO_TARGET",
                gating_prompt_instruction="ETKİLEŞİM KAPISI [BYPASS]: Dikkat odağında kimse yok. Sessiz kal.",
            )

        dist = getattr(person, "distance_m", 2.0)
        if dist > 5.0:
            return InteractionGateDecision(
                mode=InteractionGateMode.BYPASS,
                attention_state=attention_state,
                identity_certainty=identity_certainty,
                should_respond_verbally=False,
                should_track_with_gaze=False,
                reason="TARGET_OUT_OF_RANGE",
                gating_prompt_instruction="ETKİLEŞİM KAPISI [BYPASS]: Hedef çok uzakta (> 5m). Sessiz kal.",
            )

        # Rule 4: Target is far away (> social distance limit)
        dist = getattr(person, "distance_m", 2.0)
        if dist > self.social_distance_limit_m:
            return InteractionGateDecision(
                mode=InteractionGateMode.OBSERVING,
                attention_state=attention_state,
                identity_certainty=identity_certainty,
                should_respond_verbally=False,
                should_track_with_gaze=True,
                reason="DISTANCE_BEYOND_SOCIAL_ZONE",
                gating_prompt_instruction=(
                    f"ETKİLEŞİM KAPISI [GÖZLEMLEME]: Kişi uzakta ({dist:.1f}m > {self.social_distance_limit_m:.1f}m). "
                    "Doğrudan hitap gelmedikçe sözel olarak lafa atlama; başınla takip et."
                ),
            )

        # Rule 5: Target looking away and not addressing robot (e.g. side conversation)
        is_looking = getattr(person, "is_looking_at_robot", False)
        if not is_looking and attention_state != TemporalAttentionState.ENGAGED:
            return InteractionGateDecision(
                mode=InteractionGateMode.OBSERVING,
                attention_state=attention_state,
                identity_certainty=identity_certainty,
                should_respond_verbally=False,
                should_track_with_gaze=True,
                reason="SIDE_CONVERSATION_LOOKING_AWAY",
                gating_prompt_instruction=(
                    "ETKİLEŞİM KAPISI [GÖZLEMLEME]: Kişi robota bakmıyor, yan konuşma olabilir. "
                    "Sözel yanıttan kaçın, dinlemede kal."
                ),
            )

        # Rule 6: Attention is ENGAGED or ATTENTION_ACQUIRED within social zone
        if attention_state in (TemporalAttentionState.ENGAGED, TemporalAttentionState.ATTENTION_ACQUIRED):
            return InteractionGateDecision(
                mode=InteractionGateMode.ENGAGED,
                attention_state=attention_state,
                identity_certainty=identity_certainty,
                should_respond_verbally=True,
                should_track_with_gaze=True,
                reason="ATTENTION_ENGAGED",
                gating_prompt_instruction="ETKİLEŞİM KAPISI [AÇIK — ETKİLEŞİMDE]: Karşılıklı dikkat sağlandı. Sözel diyaloğu sürdür.",
            )

        # Default fallback: OBSERVING
        return InteractionGateDecision(
            mode=InteractionGateMode.OBSERVING,
            attention_state=attention_state,
            identity_certainty=identity_certainty,
            should_respond_verbally=False,
            should_track_with_gaze=True,
            reason="ATTENTION_PENDING_OBSERVATION",
            gating_prompt_instruction="ETKİLEŞİM KAPISI [GÖZLEMLEME]: Dikkat henüz tam olgunlaşmadı. Gözlemle.",
        )
