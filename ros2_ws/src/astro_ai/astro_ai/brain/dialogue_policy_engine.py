"""ASTRO V1 — Dialogue Policy Engine (Phase 5).

Translates deterministic cognitive state, information sufficiency, affective
modulators, and metacognitive decisions into bounded, actionable dialogue directives.
Maintains conversational focus across brief third-party interruptions.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from astro_ai.contracts.consciousness_types import (
    CognitiveDecision,
    CognitiveDecisionType,
    InformationSufficiency,
    MetacognitiveState,
    RobotAffectiveState,
)
from astro_ai.contracts.social_dialogue_types import (
    ConfidenceBracket,
    DialogueContext,
    DialogueDirective,
    EpistemicDirective,
    VerbosityLevel,
)

_LOG = logging.getLogger(__name__)


class DialoguePolicyEngine:
    """Deterministic policy engine that translates cognitive state into dialogue directives."""

    def __init__(self, interruption_timeout_s: float = 5.0):
        self.interruption_timeout_s: float = float(interruption_timeout_s)
        self.primary_person_id: Optional[str] = None
        self.primary_person_name: str = ""
        self.last_primary_interaction_ts: float = 0.0

    def set_primary_interlocutor(self, person_id: Optional[str], person_name: str = "", now: Optional[float] = None) -> None:
        """Explicitly sets or resets the primary conversational partner."""
        self.primary_person_id = person_id
        self.primary_person_name = person_name or (person_id or "")
        self.last_primary_interaction_ts = time.time() if now is None else float(now)

    def handle_interlocutor_turn(
        self, speaker_id: Optional[str], speaker_name: str = "", now: Optional[float] = None
    ) -> Tuple[bool, str]:
        """Evaluates conversational continuity when a turn occurs.

        Returns (is_brief_interruption, reason).
        """
        current_time = time.time() if now is None else float(now)

        if not speaker_id:
            return False, "no_speaker_identified"

        if self.primary_person_id is None:
            self.set_primary_interlocutor(speaker_id, speaker_name, current_time)
            return False, "primary_established"

        if speaker_id == self.primary_person_id:
            self.last_primary_interaction_ts = current_time
            if speaker_name:
                self.primary_person_name = speaker_name
            return False, "primary_active"

        # Third-party speaker detected
        elapsed = current_time - self.last_primary_interaction_ts
        if elapsed <= self.interruption_timeout_s:
            # Brief interruption: preserve primary thread
            return True, f"brief_interruption: elapsed={elapsed:.1f}s <= threshold={self.interruption_timeout_s:.1f}s"
        else:
            # Timeout exceeded: transition focus to new speaker
            old_id = self.primary_person_id
            self.set_primary_interlocutor(speaker_id, speaker_name, current_time)
            return False, f"focus_switched: from {old_id} to {speaker_id}"

    def evaluate_policy(
        self,
        context: DialogueContext,
        affective_state: Optional[Dict[str, float] | RobotAffectiveState] = None,
        cognitive_decision: Optional[CognitiveDecision] = None,
        now: Optional[float] = None,
    ) -> DialogueDirective:
        """Determines the appropriate DialogueDirective based on cognitive and social state."""
        directive = DialogueDirective()

        # 1. Epistemic Guidance from Information Sufficiency
        suff = (context.information_sufficiency or "SUFFICIENT").upper()
        if suff == "INSUFFICIENT":
            directive.epistemic_directive = EpistemicDirective.CLARIFY_OR_DECLINE
            directive.clarification_needed = True
            directive.clarification_prompt = (
                "Bilgiler eksiktir; doğrudan iddiada bulunma, açıklama iste veya 'bilmiyorum' de."
            )
            directive.epistemic_guidance = (
                "Eksik bilgi hakkında varsayımda bulunma; netleştirme iste veya 'bilmiyorum' de."
            )
        elif suff == "STALE":
            directive.epistemic_directive = EpistemicDirective.QUALIFIED
            directive.epistemic_guidance = (
                "Gözlem güncelliğini yitirmiştir; 'en son kontrol ettiğimde ... idi' şeklinde zamansal niteleme kullan."
            )
        elif suff == "CONFLICTING":
            directive.epistemic_directive = EpistemicDirective.UNCERTAIN
            directive.epistemic_guidance = (
                "Sensörler veya veriler arasında çelişki vardır; kesin hüküm vermeden belirsizliği açıkla."
            )
        elif suff == "UNKNOWN":
            directive.epistemic_directive = EpistemicDirective.CLARIFY_OR_DECLINE
            directive.epistemic_guidance = "Bu konuda kayıtlı bilgin yok; bilmediğini dürüstçe ifade et."
        else:
            directive.epistemic_directive = EpistemicDirective.FACTUAL
            directive.epistemic_guidance = "Gözlem ve hafıza verilerine dayanarak net, dürüst ve doğrudan cevap ver."

        # 2. Affective Modulation (urgency, frustration, curiosity, uncertainty)
        urgency = 0.0
        frustration = 0.0
        curiosity = 0.0
        uncertainty = 0.0

        if isinstance(affective_state, dict):
            urgency = float(affective_state.get("urgency", context.urgency_level))
            frustration = float(affective_state.get("frustration", 0.0))
            curiosity = float(affective_state.get("curiosity", 0.0))
            uncertainty = float(affective_state.get("uncertainty", 0.0))
        elif isinstance(affective_state, RobotAffectiveState):
            urgency = float(affective_state.urgency)
            frustration = float(affective_state.frustration)
            curiosity = float(affective_state.curiosity)
            uncertainty = float(affective_state.uncertainty)
        else:
            urgency = float(context.urgency_level)

        if urgency >= 0.7:
            directive.verbosity = VerbosityLevel.CONCISE
            directive.max_words = 15
            directive.tone_guidance = "Acil, doğrudan ve işlevsel (en fazla 15 kelime)"
        elif frustration >= 0.6:
            directive.verbosity = VerbosityLevel.CONCISE
            directive.max_words = 18
            directive.tone_guidance = "Sakinleştirici, sade ve çözüm odaklı"
        elif curiosity >= 0.7 and uncertainty < 0.4:
            directive.verbosity = VerbosityLevel.DETAILED
            directive.max_words = 35
            directive.tone_guidance = "İlgili, meraklı ve tamamlayıcı takip sorusu içeren"
        elif uncertainty >= 0.6:
            directive.verbosity = VerbosityLevel.BALANCED
            directive.max_words = 20
            directive.tone_guidance = "Epistemik olarak temkinli ve dikkatli"
            directive.epistemic_directive = EpistemicDirective.QUALIFIED
        else:
            directive.verbosity = VerbosityLevel.BALANCED
            directive.max_words = 25
            directive.tone_guidance = "Doğal, samimi ve net"

        # 3. Metacognitive Decision Translation
        dec_type = context.cognitive_decision_type
        if cognitive_decision is not None:
            dec_type = (
                cognitive_decision.decision_type.value
                if hasattr(cognitive_decision.decision_type, "value")
                else str(cognitive_decision.decision_type)
            )

        if dec_type:
            dt = dec_type.upper()
            if dt == CognitiveDecisionType.SEEK_INFORMATION.value:
                directive.clarification_needed = True
                directive.clarification_prompt = "Eksik bilgiyi tamamlamak için kullanıcıdan netleştirme iste."
                directive.tone_guidance = "Meraklı ve netleştirici"
            elif dt == CognitiveDecisionType.REASSESS.value:
                directive.epistemic_directive = EpistemicDirective.UNCERTAIN
                directive.epistemic_guidance = (
                    "Bilişsel durum yeniden değerlendiriliyor; desteklenmeyen iddialardan kaçın."
                )
            elif dt == CognitiveDecisionType.REVIEW_STRATEGY.value:
                directive.epistemic_directive = EpistemicDirective.CLARIFY_OR_DECLINE
                directive.epistemic_guidance = (
                    "Mevcut strateji yetersiz kaldı; alternatif yaklaşım veya yardım öner."
                )
            elif dt == CognitiveDecisionType.REEVALUATE_GOAL.value:
                directive.tone_guidance = (
                    "Hedef güncelleniyor; konuşma amacını mevcut duruma göre uyarla."
                )
            elif dt == CognitiveDecisionType.WAIT_FOR_OUTCOME.value:
                directive.epistemic_guidance = (
                    "Eylemin sonucu beklenmektedir; erken ve kesin iddialarda bulunma."
                )

        # 4. Critical Safety Preemption (LiDAR Obstacle / Safety Conflict)
        has_safety_conflict = any(
            "SAFETY" in str(c).upper() or "OBSTACLE" in str(c).upper()
            for c in context.active_conflicts
        )
        if has_safety_conflict or (context.distance_m is not None and context.distance_m < 0.50):
            directive.safety_warning = (
                "DİKKAT: Güvenlik mesafesi ihlali veya engel var! Hareketi durdur ve kullanıcıyı uyar."
            )
            directive.verbosity = VerbosityLevel.CONCISE
            directive.max_words = 10
            directive.tone_guidance = "Uyarıcı, keskin ve net (en fazla 10 kelime)"

        return directive
