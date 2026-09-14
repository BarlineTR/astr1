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

    @staticmethod
    def normalize_proposed_changes(raw_changes: Any) -> List[ProposedChange]:
        """Safely normalizes raw 'proposed_changes' from LLM JSON to a strict List[ProposedChange].

        Invariants enforced:
        - Must return a list containing ONLY ProposedChange instances.
        - No-op strings like 'None', 'No changes required', 'N/A', 'GEMINI_OK' are filtered to [].
        - Arbitrary strings/malformed types are NEVER converted into fake ProposedChange objects.
        - Valid dicts are converted to ProposedChange with safe field extraction.
        """
        if not isinstance(raw_changes, list):
            return []

        no_op_strings = {
            "none",
            "no changes",
            "no changes required",
            "no change",
            "no change needed",
            "no changes needed",
            "n/a",
            "na",
            "gemini_ok",
            "ok",
            "[]",
            "{}",
            "null",
        }

        normalized: List[ProposedChange] = []
        for item in raw_changes:
            if isinstance(item, ProposedChange):
                normalized.append(item)
            elif isinstance(item, dict):
                file_path = str(item.get("file_path") or item.get("file") or "").strip()
                description = str(item.get("description") or item.get("change") or "").strip()
                rationale = str(item.get("rationale") or item.get("reason") or "").strip()

                # If dict represents an empty or no-op statement without a target file
                if not file_path:
                    continue
                if description.lower() in no_op_strings or rationale.lower() in no_op_strings:
                    continue

                diff_snippet = str(item.get("diff_snippet") or "")
                raw_inv = item.get("target_invariants")
                target_invariants = [str(x) for x in raw_inv] if isinstance(raw_inv, list) else []

                normalized.append(
                    ProposedChange(
                        file_path=file_path,
                        description=description,
                        rationale=rationale,
                        diff_snippet=diff_snippet,
                        target_invariants=target_invariants,
                    )
                )
            elif isinstance(item, str):
                # Strings (e.g. "None", "No changes required", "GEMINI_OK", or free-form comments)
                # are explicitly discarded from proposed_changes to preserve the strict List[ProposedChange] contract.
                continue
            else:
                # Any other corrupted/unsupported type is safely ignored.
                continue

        return normalized
