"""ASTRO V1 — Social Initiative & Controlled Compliments Data Contracts.

Contracts for rate-limited, epistemically-gated visual compliments and proactive
social timing decisions.
"""

from dataclasses import dataclass
from enum import Enum
import time
from typing import Optional


class ComplimentTopic(str, Enum):
    """Subject category of an approved visual compliment."""

    SMILE_ENERGY = "SMILE_ENERGY"        # Smiling, positive aura, radiant vibe
    CLOTHING_STYLE = "CLOTHING_STYLE"    # Colors, neat appearance
    PRESENCE_AURA = "PRESENCE_AURA"      # Friendly calm, polite demeanor
    NONE = "NONE"


@dataclass
class VisualComplimentDecision:
    """Decision output for delivering a controlled visual compliment."""

    should_compliment: bool
    topic: ComplimentTopic
    compliment_text_suggestion: str
    prompt_directive: str
    reason: str
    timestamp: float = time.time()
