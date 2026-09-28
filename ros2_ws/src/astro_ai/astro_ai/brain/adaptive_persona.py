"""ASTRO V1 — Adaptive Persona Engine.

Adapts ASTRO's tone, vocabulary complexity, and profanity policies dynamically
based on interlocutor age-group and social context, while strictly preserving
core robotic identity and humor.
"""

from typing import Optional, Tuple

from astro_ai.contracts.adaptive_persona_types import (
    AdaptivePersonaPolicy,
    AgeGroup,
    PersonaStyle,
)
from astro_ai.contracts.person_state import UnifiedPersonState


class AdaptivePersonaEngine:
    """Estimates age-group and adapts conversational persona policies."""

    def estimate_age_group(
        self,
        person: Optional[UnifiedPersonState],
    ) -> Tuple[AgeGroup, float]:
        """Estimates age group from visual perception obeying Camera = Eye epistemic bounds."""
        if person is None:
            return AgeGroup.UNKNOWN, 0.0

        # Epistemic invariant: Without visual confirmation, cannot assert visual age group
        if not getattr(person, "can_claim_vision", False):
            return AgeGroup.UNKNOWN, 0.0

        raw = getattr(person, "raw_attributes", {}) or {}

        # 1. Direct child flag
        if raw.get("is_child") is True or raw.get("age_category") == "child":
            return AgeGroup.CHILD, 0.95

        # 2. Explicit numeric age estimate from face detector
        age_val = raw.get("age")
        if age_val is not None:
            try:
                age_num = float(age_val)
                if age_num <= 12.0:
                    return AgeGroup.CHILD, 0.90
                elif 13.0 <= age_num <= 17.0:
                    return AgeGroup.TEEN, 0.85
                elif 18.0 <= age_num <= 64.0:
                    return AgeGroup.ADULT, 0.90
                elif age_num >= 65.0:
                    return AgeGroup.SENIOR, 0.90
            except (ValueError, TypeError):
                pass

        # 3. Direct string category from real vision pipeline
        cat_val = str(raw.get("age_group", "") or getattr(person, "estimated_age_group", "")).upper()
        if cat_val in AgeGroup.__members__ and cat_val != "UNKNOWN":
            age_conf = float(raw.get("age_confidence", getattr(person, "age_confidence", 0.80)) or 0.80)
            return AgeGroup[cat_val], age_conf

        # Epistemic truthfulness: If no vision model confirmed age, state UNKNOWN
        return AgeGroup.UNKNOWN, 0.0

    def evaluate_policy(
        self,
        base_persona: str,
        age_group: AgeGroup,
    ) -> AdaptivePersonaPolicy:
        """Derives actionable persona policy with strict child safety invariants."""
        p_clean = (base_persona or "playful").lower()

        if age_group == AgeGroup.CHILD:
            # Child Safety Invariant: Zero profanity, pedagogical, friendly
            eff_p = "playful" if p_clean in ("kufurbaz", "flirt") else p_clean
            return AdaptivePersonaPolicy(
                target_age_group=AgeGroup.CHILD,
                age_confidence=0.90,
                effective_persona=eff_p,
                style=PersonaStyle.PEDAGOGICAL_PLAYFUL,
                allow_profanity=False,
                vocabulary_complexity="simple",
                recommended_tone="neşeli, eğitici, sade ve teşvik edici",
                policy_prompt_instruction=(
                    "UYARLANABİLİR KİŞİLİK [ÇOCUK ETKİLEŞİMİ]: Karşındaki kişi bir çocuk. "
                    "Küfür, argo, kaba söz veya flörtöz ifadeler KESİNLİKLE YASAKTIR. "
                    "Neşeli, eğitici, sade ve teşvik edici bir dille konuş; Astro'nun sevimli robot kimliğini öne çıkar."
                ),
            )

        elif age_group == AgeGroup.SENIOR:
            # Senior Invariant: Respectful, articulate, patient
            eff_p = "playful" if p_clean == "kufurbaz" else p_clean
            return AdaptivePersonaPolicy(
                target_age_group=AgeGroup.SENIOR,
                age_confidence=0.90,
                effective_persona=eff_p,
                style=PersonaStyle.RESPECTFUL_PATIENT,
                allow_profanity=False,
                vocabulary_complexity="articulate",
                recommended_tone="saygılı, sabırlı, tane tane ve net",
                policy_prompt_instruction=(
                    "UYARLANABİLİR KİŞİLİK [KIDEMLİ / YAŞLI ETKİLEŞİMİ]: Karşındaki kişi kıdemli bir yetişkin. "
                    "Saygılı, sabırlı, tane tane ve net konuş. Kaba veya laubali ifadelerden kaçın."
                ),
            )

        elif age_group == AgeGroup.UNKNOWN:
            # Unknown Age: Safe, respectful, balanced baseline. Profanity blocked.
            eff_p = "playful" if p_clean in ("kufurbaz", "flirt") else p_clean
            return AdaptivePersonaPolicy(
                target_age_group=AgeGroup.UNKNOWN,
                age_confidence=0.0,
                effective_persona=eff_p,
                style=PersonaStyle.NOMINAL_ADULT,
                allow_profanity=False,
                vocabulary_complexity="normal",
                recommended_tone="nazik, saygılı, dengeli ve doğal",
                policy_prompt_instruction=(
                    "UYARLANABİLİR KİŞİLİK [BİLİNMEYEN YAŞ GRUBU]: Karşındaki kişinin yaş grubu henüz doğrulanmadı. "
                    "Nazik, dengeli ve doğal Astro kimliğini koru; kaba veya aşırı laubali ifadelerden kaçın."
                ),
            )

        # Nominal Adult
        allow_prof = (p_clean == "kufurbaz")
        return AdaptivePersonaPolicy(
            target_age_group=AgeGroup.ADULT,
            age_confidence=0.80,
            effective_persona=p_clean,
            style=PersonaStyle.NOMINAL_ADULT,
            allow_profanity=allow_prof,
            vocabulary_complexity="normal",
            recommended_tone="samimi, esprili ve doğal",
            policy_prompt_instruction=(
                f"UYARLANABİLİR KİŞİLİK [YETİŞKİN ETKİLEŞİMİ]: Nominal '{p_clean}' tarzını doğal olarak sürdür."
            ),
        )
