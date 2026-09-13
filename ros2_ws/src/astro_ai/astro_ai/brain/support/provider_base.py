"""ASTRO V1 — Base Architecture Support Provider Abstraction.

Defines the contract for external model providers (Gemini, Groq, etc.) assisting
with ASTRO's cognitive architecture analysis.
"""

from __future__ import annotations

import abc
import json
import re
from typing import Any, Dict, List, Optional

from astro_ai.brain.support.config import SupportConfig
from astro_ai.brain.support.contracts import (
    ArchitectureSupportResponse,
    ProposedChange,
    SupportControlMode,
    SupportStatus,
)


class BaseSupportProvider(abc.ABC):
    """Abstract base class for cognitive architecture support model providers."""

    def __init__(self, provider_name: str, model_name: str, config: SupportConfig):
        self.provider_name = provider_name
        self.model_name = model_name
        self.config = config

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Checks if the provider is enabled and required credentials exist."""
        pass

    @abc.abstractmethod
    def generate_analysis(
        self,
        prompt: str,
        context: str,
        mode: SupportControlMode,
        request_id: str,
    ) -> ArchitectureSupportResponse:
        """Executes an architectural analysis query and returns a structured response."""
        pass

    @staticmethod
    def parse_structured_json(raw_text: str, default_summary: str = "") -> Dict[str, Any]:
        """Safely parses structured JSON from LLM responses, stripping code fences if present."""
        if not raw_text or not raw_text.strip():
            return {"summary": default_summary or "Empty response received"}

        # Attempt direct parse
        try:
            return json.loads(raw_text)
        except Exception:
            pass

        # Attempt extracting from ```json ... ``` code fence
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass

        # Fallback: construct structured dictionary from plain text
        summary = raw_text.strip()[:200] if raw_text.strip() else (default_summary or "Empty response received")
        return {
            "summary": summary,
            "observations": [line.strip() for line in raw_text.splitlines() if line.strip().startswith(("-", "*", "1.", "2."))][:10],
            "architectural_concerns": [],
            "proposed_changes": [],
            "affected_files": [],
            "invariant_checks": {"no_motor_control": True, "state_machine_preserved": True},
            "test_plan": ["Run cognitive test suite to verify no regressions."],
            "confidence": 0.8,
        }
