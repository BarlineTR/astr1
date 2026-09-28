"""ASTRO V1 — Cognitive Architecture Support Layer Package.

Provides offline and development-time architectural analysis using Gemini Flash
and Groq Qwen with strict local rate/budget gating and context minimization.
"""

from astro_ai.brain.support.assistant import CognitiveArchitectureAssistant
from astro_ai.brain.support.budget_gate import LocalBudgetGate
from astro_ai.brain.support.cache import ArchitectureSupportCache
from astro_ai.brain.support.config import SupportConfig
from astro_ai.brain.support.context_builder import ArchitectureContextBuilder, TokenBudgetExceededError
from astro_ai.brain.support.contracts import (
    ApplyResult,
    ArchitectureComparisonResult,
    ArchitectureSupportResponse,
    BudgetDecision,
    ProposedChange,
    SupportControlMode,
    SupportRequest,
    SupportStatus,
)
from astro_ai.brain.support.cooldown import TopicCooldownDebouncer
from astro_ai.brain.support.gemini_provider import GeminiFlashProvider
from astro_ai.brain.support.groq_provider import GroqQwenProvider
from astro_ai.brain.support.provider_base import BaseSupportProvider

__all__ = [
    "CognitiveArchitectureAssistant",
    "BaseSupportProvider",
    "GeminiFlashProvider",
    "GroqQwenProvider",
    "LocalBudgetGate",
    "ArchitectureSupportCache",
    "TopicCooldownDebouncer",
    "ArchitectureContextBuilder",
    "TokenBudgetExceededError",
    "SupportConfig",
    "SupportControlMode",
    "SupportRequest",
    "ArchitectureSupportResponse",
    "ArchitectureComparisonResult",
    "BudgetDecision",
    "ProposedChange",
    "ApplyResult",
    "SupportStatus",
]
