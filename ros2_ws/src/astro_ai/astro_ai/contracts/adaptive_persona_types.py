"""ASTRO V1 — Adaptive Persona Data Contracts.

Contracts for probabilistic age-group estimation and dynamic persona policy
adaptation (e.g. child safety zero-profanity, senior respectful clarity).
"""

from dataclasses import dataclass
from enum import Enum


class AgeGroup(str, Enum):
    """Categorical age group classification."""

    CHILD = "CHILD"      # 0 - 12 years old
    TEEN = "TEEN"        # 13 - 17 years old
    ADULT = "ADULT"      # 18 - 64 years old
    SENIOR = "SENIOR"    # 65+ years old
    UNKNOWN = "UNKNOWN"  # Not visually detected or unconfirmed


class PersonaStyle(str, Enum):
    """Behavioral adaptation style applied to base persona."""

    PEDAGOGICAL_PLAYFUL = "PEDAGOGICAL_PLAYFUL"  # Simple words, encouraging, zero vulgarity
    NOMINAL_ADULT = "NOMINAL_ADULT"              # Standard persona style (playful, witty, kufurbaz, etc.)
    RESPECTFUL_PATIENT = "RESPECTFUL_PATIENT"    # Articulate, polite, patient


@dataclass
class AdaptivePersonaPolicy:
    """Actionable persona policy adapted to interlocutor's social context."""

    target_age_group: AgeGroup
    age_confidence: float
    effective_persona: str
    style: PersonaStyle
    allow_profanity: bool
    vocabulary_complexity: str
    recommended_tone: str
    policy_prompt_instruction: str
