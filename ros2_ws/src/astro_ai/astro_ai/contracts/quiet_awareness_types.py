"""Contracts and types for Quiet/Sleep Social Awareness."""

from dataclasses import dataclass
from enum import Enum


class DirectednessLevel(str, Enum):
    """Level of address directedness in background speech."""
    DIRECTED_TO_ME = "DIRECTED_TO_ME"
    ABOUT_ME = "ABOUT_ME"
    UNRELATED_BACKGROUND = "UNRELATED_BACKGROUND"


class QuietInterventionNeed(str, Enum):
    """Whether overhearing conversation requires robot intervention."""
    CRITICAL_CALL_OR_COMMAND = "CRITICAL_CALL_OR_COMMAND"
    ASSISTANCE_HELPFUL = "ASSISTANCE_HELPFUL"
    NONE = "NONE"


class QuietDecisionMode(str, Enum):
    """Action decision in quiet/sleep mode."""
    ENGAGE = "ENGAGE"
    REMAIN_QUIET = "REMAIN_QUIET"


@dataclass
class QuietAwarenessDecision:
    """Authoritative decision from quiet social awareness evaluator."""
    mode: QuietDecisionMode
    directedness: DirectednessLevel
    intervention_need: QuietInterventionNeed
    is_about_me: bool
    confidence: float
    reason: str
    prompt_instruction: str
