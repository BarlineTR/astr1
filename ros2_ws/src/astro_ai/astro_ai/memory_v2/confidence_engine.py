"""ASTRO V1 — Epistemic Confidence and Source Reliability Engine."""

from typing import Tuple

from astro_ai.contracts.intent_emotion_types import MemorySourceType
from astro_ai.contracts.memory_models import MemoryConfidenceLevel, MemoryType


class ConfidenceEngine:
    """Calculates factual confidence and epistemic classification for incoming memories."""

    SOURCE_RELIABILITY_MAP = {
        MemorySourceType.TRUSTED_SYSTEM_FACT: 1.00,
        MemorySourceType.EXPLICIT_USER_STATEMENT: 0.98,
        MemorySourceType.ROBOT_OBSERVATION: 0.85,
        MemorySourceType.REPEATED_BEHAVIOR: 0.80,
        MemorySourceType.THIRD_PARTY_STATEMENT: 0.45,
        MemorySourceType.UNCERTAIN_INFERENCE: 0.40,
    }

    @classmethod
    def evaluate_confidence(
        cls,
        memory_type: MemoryType,
        source_type: MemorySourceType,
        base_confidence: float = 1.0,
        confirmation_count: int = 1,
    ) -> Tuple[float, MemoryConfidenceLevel]:
        """Calculates final confidence score and qualitative confidence level."""
        source_weight = cls.SOURCE_RELIABILITY_MAP.get(source_type, 0.50)

        # Scale confidence with repeated confirmations
        boost = min(0.15, (confirmation_count - 1) * 0.05)
        raw_score = min(1.0, (base_confidence * source_weight) + boost)
        score = round(raw_score, 3)

        if score >= 0.95:
            level = MemoryConfidenceLevel.VERIFIED_FACT
        elif score >= 0.80:
            level = MemoryConfidenceLevel.STRONG_EVIDENCE
        elif score >= 0.60:
            level = MemoryConfidenceLevel.BEHAVIORAL_INFERENCE
        elif score >= 0.30:
            level = MemoryConfidenceLevel.WEAK_INFERENCE
        else:
            level = MemoryConfidenceLevel.UNRELIABLE

        return score, level

    @classmethod
    def is_eligible_for_facts(cls, confidence: float) -> bool:
        """Determines if memory is certain enough to be stated as absolute truth."""
        return confidence >= 0.80
