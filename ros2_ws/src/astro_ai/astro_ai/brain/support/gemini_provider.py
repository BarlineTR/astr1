"""ASTRO V1 — Gemini Flash Architecture Support Provider.

Integrates Google Gemini Flash as an independent cognitive architecture support model.

SAFETY & BUDGET RULES:
  1. Never polled continuously.
  2. Never retried automatically upon 429 or timeout.
  3. Returns degraded/structured error responses without throwing uncaught exceptions.
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


class GeminiFlashProvider(BaseSupportProvider):
    """Google Gemini Flash provider implementation for architecture reviews."""

    def __init__(self, config: Optional[SupportConfig] = None, client: Optional[Any] = None):
        cfg = config if config is not None else SupportConfig.from_env()
        super().__init__(
            provider_name="gemini",
            model_name=cfg.gemini_support_model,
            config=cfg,
        )
        self._client = client

    def is_available(self) -> bool:
        """Checks if Gemini support is enabled and API key is present."""
        import os
        if os.getenv("USE_REALTIME", "true").lower() in ("false", "0", "no"):
            return False
        return bool(self.config.gemini_support_enabled and self.config.gemini_api_key)

    def _get_client(self) -> Any:
        """Returns initialized Gemini client or raises RuntimeError."""
        if self._client is not None:
            return self._client

        try:
            from google import genai
            return genai.Client(api_key=self.config.gemini_api_key)
        except Exception as exc:
            _LOG.warning(f"Failed to instantiate google.genai Client: {exc}")
            raise RuntimeError(f"Gemini client initialization failed: {exc}") from exc

    def generate_analysis(
        self,
        prompt: str,
        context: str,
        mode: SupportControlMode,
        request_id: str,
    ) -> ArchitectureSupportResponse:
        """Invokes Gemini Flash for architecture reasoning."""
        if not self.is_available():
            import os
            is_local = os.getenv("USE_REALTIME", "true").lower() in ("false", "0", "no")
            return ArchitectureSupportResponse(
                request_id=request_id,
                provider=self.provider_name,
                model=self.model_name,
                mode=mode,
                status=SupportStatus.PROVIDER_UNAVAILABLE,
                summary="Gemini support is disabled in local mode (USE_REALTIME=false)." if is_local else "Gemini support is disabled or GEMINI_API_KEY is not configured.",
                error_code="LOCAL_MODE_ACTIVE" if is_local else "GEMINI_UNAVAILABLE",
                confidence=0.0,
            )

        system_instruction = (
            "You are ASTRO's Cognitive Architecture Support System. "
            "You review code, epistemic limits, invariants, and cognitive contracts. "
            "You do NOT possess runtime consciousness or motor command capabilities. "
            "Always respond with a valid JSON object containing keys: "
            "'summary', 'observations', 'architectural_concerns', 'proposed_changes', "
            "'invariant_checks', 'test_plan', 'confidence'. "
            "The 'proposed_changes' field must be a JSON array of objects, where each object has "
            "the fields 'file_path' (string), 'description' (string), 'rationale' (string), "
            "and optionally 'diff_snippet' (string) and 'target_invariants' (list of strings). "
            "If no architectural changes are proposed or needed, 'proposed_changes' MUST be an empty array []."
        )

        full_prompt = f"{system_instruction}\n\n[ARCHITECTURAL CONTEXT]:\n{context}\n\n[QUERY]:\n{prompt}"

        try:
            client = self._get_client()
            # Support both genai.Client and mock interfaces
            if hasattr(client, "models") and hasattr(client.models, "generate_content"):
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=full_prompt,
                )
                raw_text = getattr(response, "text", str(response))
            elif hasattr(client, "generate_content"):
                response = client.generate_content(full_prompt)
                raw_text = getattr(response, "text", str(response))
            else:
                raw_text = str(client(full_prompt))

            parsed = self.parse_structured_json(raw_text, default_summary="Gemini analysis completed.")
            changes = self.normalize_proposed_changes(parsed.get("proposed_changes", []))

            return ArchitectureSupportResponse(
                request_id=request_id,
                provider=self.provider_name,
                model=self.model_name,
                mode=mode,
                status=SupportStatus.SUCCESS,
                summary=parsed.get("summary", "Gemini analysis completed."),
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
            if "429" in err_str or "quota" in err_str or "exhausted" in err_str:
                error_code = "429_RATE_LIMIT"
                status = SupportStatus.ERROR
            elif "timeout" in err_str or "timed out" in err_str:
                error_code = "TIMEOUT"
                status = SupportStatus.ERROR
            else:
                error_code = "PROVIDER_ERROR"
                status = SupportStatus.ERROR

            _LOG.warning(f"Gemini provider call failed ({error_code}): {exc}")

            return ArchitectureSupportResponse(
                request_id=request_id,
                provider=self.provider_name,
                model=self.model_name,
                mode=mode,
                status=status,
                summary=f"Gemini analysis failed: {exc}",
                error_code=error_code,
                confidence=0.0,
            )
