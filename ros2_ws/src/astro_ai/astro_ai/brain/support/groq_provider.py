"""ASTRO V1 — Groq Qwen Architecture Support Provider.

Integrates Groq-hosted Qwen (e.g., Qwen 2.5 / 3.6) as an independent cognitive
architecture support model.

SAFETY & BUDGET RULES:
  1. Never polled continuously.
  2. Never retried automatically upon 429 or timeout.
  3. Strict zero-fallback-cascade: Groq failure does NOT automatically invoke Gemini.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from astro_ai.brain.support.config import SupportConfig
from astro_ai.brain.support.contracts import (
    ArchitectureSupportResponse,
    ProposedChange,
    SupportControlMode,
    SupportStatus,
)
from astro_ai.brain.support.provider_base import BaseSupportProvider

_LOG = logging.getLogger(__name__)


class GroqQwenProvider(BaseSupportProvider):
    """Groq-hosted Qwen provider implementation for cognitive architecture reviews."""

    def __init__(self, config: Optional[SupportConfig] = None, client: Optional[Any] = None):
        cfg = config if config is not None else SupportConfig.from_env()
        super().__init__(
            provider_name="groq",
            model_name=cfg.groq_support_model,
            config=cfg,
        )
        self._client = client

    def is_available(self) -> bool:
        """Checks if Groq support is enabled and API key is present."""
        return bool(self.config.groq_support_enabled and self.config.groq_api_key)

    def _get_client(self) -> Any:
        """Returns initialized Groq or OpenAI-compatible client."""
        if self._client is not None:
            return self._client

        try:
            from groq import Groq
            return Groq(api_key=self.config.groq_api_key)
        except Exception as exc:
            _LOG.warning(f"Failed to instantiate groq.Groq client: {exc}")
            raise RuntimeError(f"Groq client initialization failed: {exc}") from exc

    def generate_analysis(
        self,
        prompt: str,
        context: str,
        mode: SupportControlMode,
        request_id: str,
    ) -> ArchitectureSupportResponse:
        """Invokes Groq Qwen for architecture reasoning."""
        if not self.is_available():
            return ArchitectureSupportResponse(
                request_id=request_id,
                provider=self.provider_name,
                model=self.model_name,
                mode=mode,
                status=SupportStatus.PROVIDER_UNAVAILABLE,
                summary="Groq support is disabled or GROQ_API_KEY is not configured.",
                error_code="GROQ_UNAVAILABLE",
                confidence=0.0,
            )

        system_instruction = (
            "You are ASTRO's Cognitive Architecture Support System (Groq/Qwen). "
            "You review cognitive architecture invariants, memory boundaries, and self models. "
            "You do NOT possess runtime consciousness or motor control authority. "
            "Always respond with a valid JSON object containing keys: "
            "'summary', 'observations', 'architectural_concerns', 'proposed_changes', "
            "'invariant_checks', 'test_plan', 'confidence'."
        )

        user_content = f"[ARCHITECTURAL CONTEXT]:\n{context}\n\n[QUERY]:\n{prompt}"

        try:
            client = self._get_client()
            chat_completion = client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                max_tokens=2048,
            )

            raw_text = chat_completion.choices[0].message.content or ""
            parsed = self.parse_structured_json(raw_text, default_summary="Groq Qwen analysis completed.")
            changes = [
                ProposedChange(**c) if isinstance(c, dict) else c
                for c in parsed.get("proposed_changes", [])
            ]

            return ArchitectureSupportResponse(
                request_id=request_id,
                provider=self.provider_name,
                model=self.model_name,
                mode=mode,
                status=SupportStatus.SUCCESS,
                summary=parsed.get("summary", "Groq Qwen analysis completed."),
                observations=parsed.get("observations", []),
                architectural_concerns=parsed.get("architectural_concerns", []),
                proposed_changes=changes,
                affected_files=parsed.get("affected_files", []),
                invariant_checks=parsed.get("invariant_checks", {}),
                test_plan=parsed.get("test_plan", []),
                confidence=float(parsed.get("confidence", 0.85)),
                requires_human_approval=True,
            )

        except Exception as exc:
            err_str = str(exc).lower()
            if "429" in err_str or "rate" in err_str or "quota" in err_str:
                error_code = "429_RATE_LIMIT"
                status = SupportStatus.ERROR
            elif "timeout" in err_str or "timed out" in err_str:
                error_code = "TIMEOUT"
                status = SupportStatus.ERROR
            else:
                error_code = "PROVIDER_ERROR"
                status = SupportStatus.ERROR

            _LOG.warning(f"Groq provider call failed ({error_code}): {exc}")

            return ArchitectureSupportResponse(
                request_id=request_id,
                provider=self.provider_name,
                model=self.model_name,
                mode=mode,
                status=status,
                summary=f"Groq analysis failed: {exc}",
                error_code=error_code,
                confidence=0.0,
            )
