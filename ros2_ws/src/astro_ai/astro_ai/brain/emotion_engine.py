"""ASTRO V1 — Multi-Dimensional Affect and Emotion Estimation Engine."""

from typing import Any, Dict, Optional, Tuple

from astro_ai.contracts.intent_emotion_types import EmotionSignal


class EmotionEngine:
    """Estimates continuous Valence-Arousal dimensions and categorical user mood."""

    VALENCE_AROUSAL_MAP = {
        EmotionSignal.HAPPY: (0.80, 0.70),
        EmotionSignal.CURIOUS: (0.40, 0.60),
        EmotionSignal.NEUTRAL: (0.00, 0.20),
        EmotionSignal.SURPRISED: (0.30, 0.85),
        EmotionSignal.SAD: (-0.75, 0.25),
        EmotionSignal.FRUSTRATED: (-0.70, 0.80),
        EmotionSignal.ANGRY: (-0.85, 0.90),
        EmotionSignal.STRESSED: (-0.60, 0.75),
    }

    @classmethod
    def estimate_affect(
        cls,
        visual_emotion: EmotionSignal = EmotionSignal.NEUTRAL,
        text_sentiment: Optional[str] = None,
        is_looking: bool = True,
        acoustic_energy_rms: float = 500.0,
    ) -> Dict[str, Any]:
        """Calculates combined Valence, Arousal, Engagement, and primary Mood."""
        base_v, base_a = cls.VALENCE_AROUSAL_MAP.get(visual_emotion, (0.0, 0.2))

        # Adjust arousal based on vocal volume / energy
        if acoustic_energy_rms > 1200.0:
            base_a = min(1.0, base_a + 0.15)

        # Calculate Engagement score
        engagement = 0.5
        if is_looking:
            engagement += 0.35
        if visual_emotion in (EmotionSignal.HAPPY, EmotionSignal.CURIOUS):
            engagement += 0.15

        mood_label = visual_emotion.value

        return {
            "primary_mood": mood_label,
            "valence": round(base_v, 2),
            "arousal": round(base_a, 2),
            "engagement": round(min(1.0, engagement), 2),
            "is_stressed": base_v < -0.4 and base_a > 0.6,
        }
