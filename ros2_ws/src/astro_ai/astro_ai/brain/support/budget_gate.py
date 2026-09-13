"""ASTRO V1 — Local Provider Budget and Rate Gate.

Enforces strict local safety budgets BEFORE any network request is sent to
external LLM support providers (Gemini, Groq, etc.).

KEY PRINCIPLES:
  - The local budget gate is intentionally LOWER than the provider's actual limits.
  - Never discover maximum limits by hitting 429s.
  - Rejections occur locally in O(1) time before opening any socket.
  - 429 responses trigger an immediate mandatory local backoff cooldown.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from astro_ai.brain.support.config import SupportConfig
from astro_ai.brain.support.contracts import BudgetDecision

_LOG = logging.getLogger(__name__)


class ProviderUsageTracker:
    """Tracks rolling window request counts and token usage for a single provider."""

    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        self.request_timestamps: List[float] = []
        self.token_records: List[tuple[float, int]] = []  # (timestamp, total_tokens)
        self.recent_failures: int = 0
        self.recent_429s: int = 0
        self.last_429_time: float = 0.0
        self.last_request_time: float = 0.0

    def purge_old_entries(self, now: float) -> None:
        """Purges entries older than 24 hours (86400s)."""
        cutoff_24h = now - 86400.0
        self.request_timestamps = [t for t in self.request_timestamps if t >= cutoff_24h]
        self.token_records = [rec for rec in self.token_records if rec[0] >= cutoff_24h]

    def count_in_window(self, window_seconds: float, now: float) -> int:
        cutoff = now - window_seconds
        return sum(1 for t in self.request_timestamps if t >= cutoff)

    def tokens_in_window(self, window_seconds: float, now: float) -> int:
        cutoff = now - window_seconds
        return sum(tokens for t, tokens in self.token_records if t >= cutoff)


class LocalBudgetGate:
    """Thread-safe rate and token budget gate protecting provider quotas."""

    def __init__(self, config: Optional[SupportConfig] = None):
        self._lock = threading.RLock()
        self.config = config if config is not None else SupportConfig.from_env()
        self._trackers: Dict[str, ProviderUsageTracker] = {}
        self._429_cooldown_seconds: float = 60.0  # Mandatory 60s freeze on 429

    def _get_tracker(self, provider: str) -> ProviderUsageTracker:
        prov = provider.lower().strip()
        if prov not in self._trackers:
            self._trackers[prov] = ProviderUsageTracker(prov)
        return self._trackers[prov]

    def evaluate_request(
        self,
        provider: str,
        estimated_input_tokens: int,
        timestamp: Optional[float] = None,
    ) -> BudgetDecision:
        """Evaluates whether a prospective request complies with local safety limits.

        Returns BudgetDecision(allowed=True/False, reason=...).
        """
        now = timestamp if timestamp is not None else time.time()

        with self._lock:
            tracker = self._get_tracker(provider)
            tracker.purge_old_entries(now)

            reqs_min = tracker.count_in_window(60.0, now)
            reqs_hour = tracker.count_in_window(3600.0, now)
            reqs_day = tracker.count_in_window(86400.0, now)
            tokens_day = tracker.tokens_in_window(86400.0, now)

            # 1. Check recent 429 cooldown
            if tracker.last_429_time > 0 and (now - tracker.last_429_time) < self._429_cooldown_seconds:
                remaining = self._429_cooldown_seconds - (now - tracker.last_429_time)
                return BudgetDecision(
                    allowed=False,
                    reason=f"Provider '{provider}' is cooling down after recent 429 rate limit ({remaining:.1f}s remaining)",
                    provider=provider,
                    requests_minute=reqs_min,
                    requests_hour=reqs_hour,
                    requests_day=reqs_day,
                    estimated_input_tokens=estimated_input_tokens,
                    daily_tokens_used=tokens_day,
                )

            # 2. Check rolling minute requests
            if reqs_min >= self.config.max_requests_per_minute:
                return BudgetDecision(
                    allowed=False,
                    reason=f"Rate limit: Max requests per minute ({self.config.max_requests_per_minute}) reached for '{provider}'",
                    provider=provider,
                    requests_minute=reqs_min,
                    requests_hour=reqs_hour,
                    requests_day=reqs_day,
                    estimated_input_tokens=estimated_input_tokens,
                    daily_tokens_used=tokens_day,
                )

            # 3. Check rolling hour requests
            if reqs_hour >= self.config.max_requests_per_hour:
                return BudgetDecision(
                    allowed=False,
                    reason=f"Rate limit: Max requests per hour ({self.config.max_requests_per_hour}) reached for '{provider}'",
                    provider=provider,
                    requests_minute=reqs_min,
                    requests_hour=reqs_hour,
                    requests_day=reqs_day,
                    estimated_input_tokens=estimated_input_tokens,
                    daily_tokens_used=tokens_day,
                )

            # 4. Check rolling day requests
            if reqs_day >= self.config.max_requests_per_day:
                return BudgetDecision(
                    allowed=False,
                    reason=f"Budget limit: Max requests per day ({self.config.max_requests_per_day}) reached for '{provider}'",
                    provider=provider,
                    requests_minute=reqs_min,
                    requests_hour=reqs_hour,
                    requests_day=reqs_day,
                    estimated_input_tokens=estimated_input_tokens,
                    daily_tokens_used=tokens_day,
                )

            # 5. Check per-request token ceiling
            max_input = (
                self.config.gemini_max_input_tokens
                if "gemini" in provider.lower()
                else self.config.groq_max_input_tokens
            )
            if estimated_input_tokens > max_input:
                return BudgetDecision(
                    allowed=False,
                    reason=f"Token limit: Estimated input tokens ({estimated_input_tokens}) exceeds single-request limit ({max_input}) for '{provider}'",
                    provider=provider,
                    requests_minute=reqs_min,
                    requests_hour=reqs_hour,
                    requests_day=reqs_day,
                    estimated_input_tokens=estimated_input_tokens,
                    daily_tokens_used=tokens_day,
                )

            # 6. Check total daily token budget
            if (tokens_day + estimated_input_tokens) > self.config.max_total_tokens_per_day:
                return BudgetDecision(
                    allowed=False,
                    reason=f"Budget limit: Daily token limit ({self.config.max_total_tokens_per_day}) would be exceeded for '{provider}'",
                    provider=provider,
                    requests_minute=reqs_min,
                    requests_hour=reqs_hour,
                    requests_day=reqs_day,
                    estimated_input_tokens=estimated_input_tokens,
                    daily_tokens_used=tokens_day,
                )

            return BudgetDecision(
                allowed=True,
                reason="OK",
                provider=provider,
                requests_minute=reqs_min,
                requests_hour=reqs_hour,
                requests_day=reqs_day,
                estimated_input_tokens=estimated_input_tokens,
                daily_tokens_used=tokens_day,
            )

    def record_request_sent(
        self,
        provider: str,
        estimated_input_tokens: int,
        timestamp: Optional[float] = None,
    ) -> None:
        """Records that an approved request has been dispatched."""
        now = timestamp if timestamp is not None else time.time()
        with self._lock:
            tracker = self._get_tracker(provider)
            tracker.request_timestamps.append(now)
            tracker.token_records.append((now, estimated_input_tokens))
            tracker.last_request_time = now

    def record_response(
        self,
        provider: str,
        actual_input_tokens: int,
        actual_output_tokens: int,
        timestamp: Optional[float] = None,
    ) -> None:
        """Records response metrics upon successful completion."""
        now = timestamp if timestamp is not None else time.time()
        with self._lock:
            tracker = self._get_tracker(provider)
            total = actual_input_tokens + actual_output_tokens
            # Replace latest estimate with actual if available
            if tracker.token_records and abs(tracker.token_records[-1][0] - tracker.last_request_time) < 5.0:
                tracker.token_records[-1] = (tracker.token_records[-1][0], total)
            else:
                tracker.token_records.append((now, total))

    def record_failure(
        self,
        provider: str,
        error_code: Optional[str] = None,
        is_429: bool = False,
        timestamp: Optional[float] = None,
    ) -> None:
        """Records a request failure, activating backoff on 429."""
        now = timestamp if timestamp is not None else time.time()
        with self._lock:
            tracker = self._get_tracker(provider)
            tracker.recent_failures += 1
            if is_429 or (error_code and "429" in error_code):
                tracker.recent_429s += 1
                tracker.last_429_time = now
                _LOG.warning(f"LocalBudgetGate: 429 recorded for provider '{provider}'. Mandatory 60s cooldown engaged.")

    def reset(self, provider: Optional[str] = None) -> None:
        """Resets tracking metrics (primarily for test harnesses)."""
        with self._lock:
            if provider:
                prov = provider.lower().strip()
                if prov in self._trackers:
                    del self._trackers[prov]
            else:
                self._trackers.clear()
