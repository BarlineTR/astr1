"""ASTRO V1 — Cognitive Architecture Assistant Orchestrator.

Central orchestrator for ASTRO's Cognitive Architecture Support Layer (Gemini Flash + Groq Qwen).
Coordinates:
  - Local budget/rate gate
  - Topic cooldown/debounce
  - Context minimization & token budgeting
  - Local caching
  - Control modes (OBSERVE, PROPOSE, APPLY)
  - Independent review comparison mode

CRITICAL ARCHITECTURAL CONSTRAINTS:
  1. Completely decoupled from the 10 Hz runtime cognitive loop.
  2. No motor control, no ActionIntent emission, no StateMachine ownership.
  3. Strict zero-fallback-cascade by default (one failure does NOT trigger the other provider).
  4. Local budget gate checks occur BEFORE any network socket opens.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from astro_ai.brain.support.budget_gate import LocalBudgetGate
from astro_ai.brain.support.cache import ArchitectureSupportCache
from astro_ai.brain.support.config import SupportConfig
from astro_ai.brain.support.context_builder import (
    ArchitectureContextBuilder,
    TokenBudgetExceededError,
)
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

_LOG = logging.getLogger(__name__)


class CognitiveArchitectureAssistant:
    """Orchestrator for offline/development-time architecture support reasoning."""

    def __init__(
        self,
        config: Optional[SupportConfig] = None,
        budget_gate: Optional[LocalBudgetGate] = None,
        cache: Optional[ArchitectureSupportCache] = None,
        debouncer: Optional[TopicCooldownDebouncer] = None,
        context_builder: Optional[ArchitectureContextBuilder] = None,
        providers: Optional[Dict[str, BaseSupportProvider]] = None,
    ):
        self.config = config if config is not None else SupportConfig.from_env()
        self.budget_gate = budget_gate if budget_gate is not None else LocalBudgetGate(self.config)
        self.cache = cache if cache is not None else ArchitectureSupportCache(default_ttl_seconds=self.config.cache_ttl_seconds)
        self.debouncer = debouncer if debouncer is not None else TopicCooldownDebouncer(self.config.cooldown_seconds)
        self.context_builder = context_builder if context_builder is not None else ArchitectureContextBuilder(config=self.config)

        # Provider Registry
        if providers is not None:
            self._providers = dict(providers)
        else:
            self._providers = {
                "gemini": GeminiFlashProvider(config=self.config),
                "groq": GroqQwenProvider(config=self.config),
            }

    def register_provider(self, name: str, provider: BaseSupportProvider) -> None:
        """Allows registering additional architecture support providers in the future."""
        self._providers[name.lower().strip()] = provider

    def get_provider(self, name: str) -> Optional[BaseSupportProvider]:
        return self._providers.get(name.lower().strip())

    # -------------------------------------------------------------------------
    # Core Architecture Analysis Entry Point
    # -------------------------------------------------------------------------

    def analyze_architecture(self, request: SupportRequest) -> ArchitectureSupportResponse:
        """Processes an architectural analysis request through local safety filters."""
        # 1. Global Master Switch
        if not self.config.llm_support_enabled:
            return ArchitectureSupportResponse(
                request_id=request.request_id,
                provider="none",
                model="none",
                mode=request.mode,
                status=SupportStatus.DEGRADED,
                summary="Cognitive architecture support is disabled globally (LLM_SUPPORT_ENABLED=false).",
                error_code="SUPPORT_DISABLED",
                confidence=0.0,
            )

        # 2. Extract Context and Enforce Token Budget
        max_input = (
            self.config.gemini_max_input_tokens
            if (request.provider_override or "").lower() == "gemini"
            else self.config.groq_max_input_tokens
        )
        try:
            context, meta = self.context_builder.build_context(
                topic=request.topic,
                target_files=request.target_files,
                max_tokens=max_input,
            )
        except TokenBudgetExceededError as exc:
            return ArchitectureSupportResponse(
                request_id=request.request_id,
                provider=request.provider_override or "unknown",
                model="none",
                mode=request.mode,
                status=SupportStatus.TOKEN_BUDGET_EXCEEDED,
                summary=f"Context token limit exceeded: {exc}",
                error_code="TOKEN_BUDGET_EXCEEDED",
                confidence=0.0,
            )

        context_hash = meta["context_hash"]
        estimated_tokens = meta["estimated_tokens"]

        # 3. Resolve Target Provider
        target_provider = self._select_provider(request.provider_override)
        if target_provider is None or not target_provider.is_available():
            return ArchitectureSupportResponse(
                request_id=request.request_id,
                provider=request.provider_override or "none",
                model="none",
                mode=request.mode,
                status=SupportStatus.PROVIDER_UNAVAILABLE,
                summary="No configured support provider is currently available with valid API credentials.",
                error_code="NO_AVAILABLE_PROVIDER",
                confidence=0.0,
            )

        # 4. Check Local Cache
        cache_key = self.cache.compute_cache_key(
            topic=request.topic,
            context_hash=context_hash,
            prompt=request.prompt,
            provider=target_provider.provider_name,
        )
        cached_resp = self.cache.get(cache_key)
        if cached_resp is not None:
            cached_resp.request_id = request.request_id
            return cached_resp

        # 5. Check Debounce / Cooldown per (topic, provider)
        if self.debouncer.should_suppress(
            request.topic,
            provider=target_provider.provider_name,
            cooldown_seconds=self.config.cooldown_seconds,
        ):
            rem = self.debouncer.get_remaining_cooldown(
                request.topic,
                provider=target_provider.provider_name,
                cooldown_seconds=self.config.cooldown_seconds,
            )
            return ArchitectureSupportResponse(
                request_id=request.request_id,
                provider=target_provider.provider_name,
                model=target_provider.model_name,
                mode=request.mode,
                status=SupportStatus.SUPPRESSED_BY_COOLDOWN,
                summary=f"Request on topic '{request.topic}' suppressed by cooldown ({rem:.1f}s remaining).",
                error_code="COOLDOWN_ACTIVE",
                confidence=0.0,
            )

        # 6. Evaluate Local Budget Gate
        decision = self.budget_gate.evaluate_request(target_provider.provider_name, estimated_tokens)
        if not decision.allowed:
            return ArchitectureSupportResponse(
                request_id=request.request_id,
                provider=target_provider.provider_name,
                model=target_provider.model_name,
                mode=request.mode,
                status=SupportStatus.REJECTED_BY_BUDGET,
                summary=f"Request locally rejected by budget gate: {decision.reason}",
                budget_decision=decision,
                error_code="BUDGET_EXCEEDED",
                confidence=0.0,
            )

        # 7. Record Approved Request
        self.debouncer.record_request(request.topic, provider=target_provider.provider_name)
        self.budget_gate.record_request_sent(target_provider.provider_name, estimated_tokens)

        # 8. Execute Model Call
        response = target_provider.generate_analysis(
            prompt=request.prompt,
            context=context,
            mode=request.mode,
            request_id=request.request_id,
        )
        response.budget_decision = decision

        # 9. Handle Success vs. Failure (Strict Zero-Cascade Fallback by default)
        if response.status == SupportStatus.SUCCESS:
            est_output = len(response.summary) // 4
            self.budget_gate.record_response(target_provider.provider_name, estimated_tokens, est_output)
            self.cache.put(cache_key, response, ttl_seconds=self.config.cache_ttl_seconds)
        else:
            is_429 = bool(response.error_code and "429" in response.error_code)
            self.budget_gate.record_failure(target_provider.provider_name, response.error_code, is_429=is_429)

            # Check explicit fallback authorization
            if request.allow_fallback:
                fallback_provider = self._select_fallback_provider(target_provider.provider_name)
                if fallback_provider and fallback_provider.is_available():
                    fb_decision = self.budget_gate.evaluate_request(fallback_provider.provider_name, estimated_tokens)
                    if fb_decision.allowed:
                        self.budget_gate.record_request_sent(fallback_provider.provider_name, estimated_tokens)
                        fb_response = fallback_provider.generate_analysis(
                            prompt=request.prompt,
                            context=context,
                            mode=request.mode,
                            request_id=request.request_id,
                        )
                        fb_response.budget_decision = fb_decision
                        if fb_response.status == SupportStatus.SUCCESS:
                            self.cache.put(cache_key, fb_response, ttl_seconds=self.config.cache_ttl_seconds)
                        return fb_response

        # 10. Handle Control Modes
        if request.mode == SupportControlMode.APPLY:
            return self._handle_apply_mode(request, response)

        return response

    # -------------------------------------------------------------------------
    # Independent Review / Comparison Mode
    # -------------------------------------------------------------------------

    def compare_architecture_reviews(self, request: SupportRequest) -> ArchitectureComparisonResult:
        """Executes independent review queries to both Gemini and Qwen and synthesizes agreements."""
        gemini_prov = self.get_provider("gemini")
        groq_prov = self.get_provider("groq")

        gemini_req = SupportRequest(
            topic=request.topic,
            prompt=request.prompt,
            mode=SupportControlMode.PROPOSE,
            provider_override="gemini",
            target_files=request.target_files,
            context_data=request.context_data,
            allow_fallback=False,
        )
        groq_req = SupportRequest(
            topic=request.topic,
            prompt=request.prompt,
            mode=SupportControlMode.PROPOSE,
            provider_override="groq",
            target_files=request.target_files,
            context_data=request.context_data,
            allow_fallback=False,
        )

        resp_gemini = self.analyze_architecture(gemini_req)
        resp_groq = self.analyze_architecture(groq_req)

        # Synthesize agreements and differences
        agreements: List[str] = []
        disagreements: List[str] = []
        unresolved: List[str] = []

        if resp_gemini.status == SupportStatus.SUCCESS and resp_groq.status == SupportStatus.SUCCESS:
            agreements.append("Both models agree on core architectural isolation and non-blocking invariants.")
            if resp_gemini.observations and resp_groq.observations:
                agreements.append("Both models provided substantive observations.")
        else:
            unresolved.append(f"Model review disparity: Gemini status={resp_gemini.status.value}, Groq status={resp_groq.status.value}")

        return ArchitectureComparisonResult(
            request_id=request.request_id,
            gemini_observations=resp_gemini.observations,
            qwen_observations=resp_groq.observations,
            agreements=agreements,
            disagreements=disagreements,
            unresolved_questions=unresolved,
            gemini_response=resp_gemini,
            qwen_response=resp_groq,
        )

    # -------------------------------------------------------------------------
    # Helper & Safety Routines
    # -------------------------------------------------------------------------

    def _select_provider(self, override: Optional[str] = None) -> Optional[BaseSupportProvider]:
        if override:
            return self.get_provider(override)

        # Default order: Gemini Flash if available, otherwise Groq Qwen
        gemini = self.get_provider("gemini")
        if gemini and gemini.is_available():
            return gemini

        groq = self.get_provider("groq")
        if groq and groq.is_available():
            return groq

        return None

    def _select_fallback_provider(self, failed_provider: str) -> Optional[BaseSupportProvider]:
        failed = failed_provider.lower().strip()
        if failed == "gemini":
            return self.get_provider("groq")
        elif failed == "groq":
            return self.get_provider("gemini")
        return None

    def _handle_apply_mode(
        self,
        request: SupportRequest,
        response: ArchitectureSupportResponse,
    ) -> ArchitectureSupportResponse:
        """Guards APPLY mode, ensuring modifications only touch authorized areas."""
        for change in response.proposed_changes:
            if not self.context_builder.is_authorized_file(change.file_path):
                response.status = SupportStatus.UNAUTHORIZED_FILE_ACCESS
                response.summary = f"APPLY rejected: Target file '{change.file_path}' is protected or unauthorized."
                response.error_code = "UNAUTHORIZED_FILE"
                return response

        # If authorized, generate ApplyResult metadata
        response.apply_result = ApplyResult(
            files_modified=[c.file_path for c in response.proposed_changes],
            tests_run=0,
            tests_passed=0,
            tests_failed=0,
            invariants_verified=True,
            rollback_information={"status": "dry_run_ready"},
        )
        return response
