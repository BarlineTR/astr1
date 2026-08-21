#!/usr/bin/env python3
"""ASTRO V1 — Single Authoritative Global Provider Circuit Breaker.

Centralizes provider availability, error classification, rate limiting (cooldown),
and quota exhaustion across all ROS2 nodes, threads, and audio/vision/LLM pipelines.
"""

import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


class ProviderState(str, Enum):
    AVAILABLE = "AVAILABLE"
    CONNECTING = "CONNECTING"
    COOLDOWN = "COOLDOWN"
    EXHAUSTED = "EXHAUSTED"
    DISABLED = "DISABLED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


class RequestErrorClass(str, Enum):
    NONE = "none"
    QUOTA_EXHAUSTED = "quota_exhausted"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    AUTH_ERROR = "auth_error"
    MODEL_UNAVAILABLE = "model_unavailable"
    BAD_REQUEST = "bad_request"
    SERVER_ERROR = "server_error"
    UNKNOWN = "unknown"


@dataclass
class ProviderStatusRecord:
    name: str
    state: ProviderState = ProviderState.AVAILABLE
    cooldown_until: float = 0.0
    failure_count: int = 0
    last_error: str = ""
    last_error_class: RequestErrorClass = RequestErrorClass.NONE
    last_updated: float = field(default_factory=time.monotonic)


class GlobalProviderCircuitBreaker:
    """Thread-safe Singleton Circuit Breaker governing all cloud and local providers."""

    _instance: Optional["GlobalProviderCircuitBreaker"] = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "GlobalProviderCircuitBreaker":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> "GlobalProviderCircuitBreaker":
        """Used in testing to reset circuit breaker states cleanly."""
        with cls._singleton_lock:
            cls._instance = cls()
            return cls._instance

    def reset_all(self):
        """Resets all provider states, sub-providers, model states, and failure counts."""
        with self._lock:
            for p in self._providers.values():
                p.state = ProviderState.AVAILABLE
                p.failure_count = 0
                p.consecutive_errors = 0
                p.cooldown_until = 0.0
                p.last_error = ""
                p.last_error_class = RequestErrorClass.NONE
            for _, sub in self._sub_providers.values():
                sub.state = ProviderState.AVAILABLE
                sub.failure_count = 0
                sub.consecutive_errors = 0
                sub.cooldown_until = 0.0
                sub.last_error = ""
                sub.last_error_class = RequestErrorClass.NONE
            self._model_states.clear()
            self._model_cooldowns.clear()

    def __init__(self, logger: Optional[Callable[[str, str], None]] = None):
        self._lock = threading.RLock()
        self._logger = logger
        self.groq_cooldown_s: float = float(os.getenv("GROQ_COOLDOWN_S", "30.0"))
        self.openai_cooldown_s: float = float(os.getenv("OPENAI_COOLDOWN_S", "30.0"))

        # Parent Providers
        self._providers: Dict[str, ProviderStatusRecord] = {
            "openai": ProviderStatusRecord("openai"),
            "groq": ProviderStatusRecord("groq"),
            "gemini": ProviderStatusRecord("gemini"),
            "edge_tts": ProviderStatusRecord("edge_tts"),
            "local_offline": ProviderStatusRecord("local_offline"),
        }

        # Sub-providers mapped to their parent
        self._sub_providers: Dict[str, Tuple[str, ProviderStatusRecord]] = {
            "openai_realtime": ("openai", ProviderStatusRecord("openai_realtime")),
            "openai_rest": ("openai", ProviderStatusRecord("openai_rest")),
            "openai_vision": ("openai", ProviderStatusRecord("openai_vision")),
            "openai_stt": ("openai", ProviderStatusRecord("openai_stt")),
            "groq_llm": ("groq", ProviderStatusRecord("groq_llm")),
            "groq_stt": ("groq", ProviderStatusRecord("groq_stt")),
            "groq_vision": ("groq", ProviderStatusRecord("groq_vision")),
            "gemini_text": ("gemini", ProviderStatusRecord("gemini_text")),
            "gemini_vision": ("gemini", ProviderStatusRecord("gemini_vision")),
        }

        # Per-model specific states (e.g. "groq:invalid-model-name" -> MODEL_UNAVAILABLE)
        self._model_states: Dict[str, ProviderState] = {}
        self._model_cooldowns: Dict[str, float] = {}

    def _log(self, level: str, msg: str):
        if self._logger:
            try:
                self._logger(level, msg)
            except Exception:
                pass
        else:
            try:
                print(f"[{level.upper()}] {msg}", flush=True)
            except UnicodeEncodeError:
                safe_msg = msg.encode("ascii", "replace").decode("ascii")
                print(f"[{level.upper()}] {safe_msg}", flush=True)

    def classify_error(
        self,
        exc: Optional[Exception] = None,
        status_code: int = 0,
        err_msg: str = "",
    ) -> RequestErrorClass:
        """Deterministically classifies any exception or status code into RequestErrorClass."""
        raw = f"{err_msg} {str(exc) if exc else ''}".lower()

        # Quota Exhaustion
        if (
            status_code == 402
            or "insufficient_quota" in raw
            or "credit_balance_exhausted" in raw
            or "quota" in raw and ("exhaust" in raw or "exceed" in raw or "zero" in raw)
            or "billing" in raw
            or "1013" in raw
        ):
            return RequestErrorClass.QUOTA_EXHAUSTED

        # Rate Limiting
        if (
            status_code == 429
            or "rate limit" in raw
            or "rpm" in raw
            or "tpm" in raw
            or "too many requests" in raw
        ):
            return RequestErrorClass.RATE_LIMITED

        # Authentication Failure
        if (
            status_code in (401, 403)
            or "invalid_api_key" in raw
            or "authentication" in raw
            or "unauthorized" in raw
            or "api key not valid" in raw
        ):
            return RequestErrorClass.AUTH_ERROR

        # Model Not Found / Unsupported
        if (
            status_code == 404
            or "model_not_found" in raw
            or "does not exist" in raw
            or "unsupported_model" in raw
            or "deprecated" in raw
            or "not found" in raw
        ):
            return RequestErrorClass.MODEL_UNAVAILABLE

        # Bad Request
        if status_code == 400 or "bad request" in raw or "invalid_request_error" in raw:
            return RequestErrorClass.BAD_REQUEST

        # Timeout
        if "timed out" in raw or "timeout" in raw or status_code in (408, 504):
            return RequestErrorClass.TIMEOUT

        # Network Error
        if (
            "connection refused" in raw
            or "network is unreachable" in raw
            or "nodename nor servname provided" in raw
            or "name or service not known" in raw
            or "temporary failure in name resolution" in raw
            or "gaierror" in raw
            or "ssl" in raw and "error" in raw
        ):
            return RequestErrorClass.NETWORK_ERROR

        # Server Error
        if status_code in (500, 502, 503) or "server error" in raw:
            return RequestErrorClass.SERVER_ERROR

        return RequestErrorClass.UNKNOWN

    def is_available(
        self,
        provider: str,
        sub_provider: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> bool:
        """Returns True if the provider, sub-provider, and model are currently available for requests."""
        now = self._get_time()
        with self._lock:
            # 1. Check parent provider state
            parent_key = provider.lower()
            if parent_key in self._providers:
                p_rec = self._providers[parent_key]
                if p_rec.state == ProviderState.EXHAUSTED:
                    return False
                if p_rec.state == ProviderState.DISABLED:
                    return False
                if p_rec.state == ProviderState.COOLDOWN:
                    if now < p_rec.cooldown_until:
                        return False
                    else:
                        # Cooldown expired, restore state
                        p_rec.state = ProviderState.AVAILABLE
                        self._log("info", f"🟢 [PROVIDER CIRCUIT BREAKER] {parent_key} cooldown ended -> AVAILABLE")

            # 2. Check sub-provider state
            if sub_provider:
                sub_key = sub_provider.lower()
                if sub_key in self._sub_providers:
                    p_name, sub_rec = self._sub_providers[sub_key]
                    # If parent is exhausted, sub-provider is exhausted
                    if self._providers.get(p_name, ProviderStatusRecord(p_name)).state == ProviderState.EXHAUSTED:
                        return False
                    if sub_rec.state == ProviderState.EXHAUSTED or sub_rec.state == ProviderState.DISABLED:
                        return False
                    if sub_rec.state == ProviderState.COOLDOWN:
                        if now < sub_rec.cooldown_until:
                            return False
                        else:
                            sub_rec.state = ProviderState.AVAILABLE

            # 3. Check model-specific state
            if model_id:
                m_key = f"{provider}:{model_id}".lower()
                if self._model_states.get(m_key) in (ProviderState.MODEL_UNAVAILABLE, ProviderState.DISABLED):
                    return False
                if m_key in self._model_cooldowns and now < self._model_cooldowns[m_key]:
                    return False

            return True

    def record_error(
        self,
        provider: str,
        sub_provider: Optional[str] = None,
        error_class: RequestErrorClass = RequestErrorClass.UNKNOWN,
        error_msg: str = "",
        model_id: Optional[str] = None,
    ) -> ProviderState:
        """Updates the circuit breaker state based on the classified error."""
        now = time.monotonic()
        with self._lock:
            parent_key = provider.lower()
            p_rec = self._providers.setdefault(parent_key, ProviderStatusRecord(parent_key))
            p_rec.last_error = error_msg
            p_rec.last_error_class = error_class
            p_rec.last_updated = now
            p_rec.failure_count += 1

            # QUOTA EXHAUSTED: Marks parent and all its sub-providers as EXHAUSTED session-wide
            if error_class == RequestErrorClass.QUOTA_EXHAUSTED:
                p_rec.state = ProviderState.EXHAUSTED
                self._log(
                    "error",
                    f"🚨 [PROVIDER CIRCUIT BREAKER]\n"
                    f"  provider={parent_key}\n"
                    f"  state=EXHAUSTED\n"
                    f"  reason={error_msg or error_class.value}\n"
                    f"  action=ALL_SUBPROVIDERS_DISABLED_SESSION_WIDE"
                )
                # Propagate to all sub-providers of this parent
                for sub_k, (parent_name, sub_rec) in self._sub_providers.items():
                    if parent_name == parent_key:
                        sub_rec.state = ProviderState.EXHAUSTED
                        sub_rec.last_error = error_msg
                        sub_rec.last_error_class = error_class
                return ProviderState.EXHAUSTED

            # RATE LIMITED: Enforce Cooldown
            if error_class == RequestErrorClass.RATE_LIMITED:
                cooldown_dur = self.groq_cooldown_s if "groq" in parent_key else self.openai_cooldown_s
                p_rec.state = ProviderState.COOLDOWN
                p_rec.cooldown_until = now + cooldown_dur
                self._log(
                    "warn",
                    f"⚠️ [PROVIDER CIRCUIT BREAKER]\n"
                    f"  provider={parent_key}\n"
                    f"  state=COOLDOWN\n"
                    f"  cooldown_s={cooldown_dur:.1f}s\n"
                    f"  reason={error_msg or 'rate_limit'}"
                )
                if sub_provider:
                    sub_key = sub_provider.lower()
                    if sub_key in self._sub_providers:
                        _, s_rec = self._sub_providers[sub_key]
                        s_rec.state = ProviderState.COOLDOWN
                        s_rec.cooldown_until = p_rec.cooldown_until
                return ProviderState.COOLDOWN

            # MODEL UNAVAILABLE: Disable specific model
            if error_class == RequestErrorClass.MODEL_UNAVAILABLE and model_id:
                m_key = f"{provider}:{model_id}".lower()
                self._model_states[m_key] = ProviderState.MODEL_UNAVAILABLE
                self._log("warn", f"⚠️ [PROVIDER CIRCUIT BREAKER] Model marked MODEL_UNAVAILABLE: {m_key}")
                return ProviderState.MODEL_UNAVAILABLE

            # AUTH ERROR: Permanent disable
            if error_class == RequestErrorClass.AUTH_ERROR:
                p_rec.state = ProviderState.DISABLED
                self._log("error", f"🚨 [PROVIDER CIRCUIT BREAKER] {parent_key} disabled due to auth error.")
                return ProviderState.DISABLED

            return p_rec.state

    def record_success(
        self,
        provider: str,
        sub_provider: Optional[str] = None,
        model_id: Optional[str] = None,
    ):
        """Clears failure counters and restores AVAILABLE state on successful call."""
        now = time.monotonic()
        with self._lock:
            parent_key = provider.lower()
            if parent_key in self._providers:
                p_rec = self._providers[parent_key]
                if p_rec.state == ProviderState.COOLDOWN:
                    p_rec.state = ProviderState.AVAILABLE
                p_rec.failure_count = 0
                p_rec.last_updated = now

            if sub_provider:
                sub_key = sub_provider.lower()
                if sub_key in self._sub_providers:
                    _, s_rec = self._sub_providers[sub_key]
                    if s_rec.state == ProviderState.COOLDOWN:
                        s_rec.state = ProviderState.AVAILABLE
                    s_rec.failure_count = 0
                    s_rec.last_updated = now

            if model_id:
                m_key = f"{provider}:{model_id}".lower()
                if m_key in self._model_cooldowns:
                    del self._model_cooldowns[m_key]

    def _get_time(self) -> float:
        return time.monotonic()

    def is_exhausted(self, provider: str, sub_provider: Optional[str] = None) -> bool:
        return self.get_state(provider, sub_provider) == ProviderState.EXHAUSTED

    def get_state(self, provider: str, sub_provider: Optional[str] = None) -> ProviderState:
        with self._lock:
            if sub_provider and sub_provider.lower() in self._sub_providers:
                p_name, s_rec = self._sub_providers[sub_provider.lower()]
                if self._providers.get(p_name, ProviderStatusRecord(p_name)).state == ProviderState.EXHAUSTED:
                    return ProviderState.EXHAUSTED
                return s_rec.state
            parent_key = provider.lower()
            if parent_key in self._providers:
                return self._providers[parent_key].state
            return ProviderState.AVAILABLE


def get_global_circuit_breaker() -> GlobalProviderCircuitBreaker:
    """Convenience getter for the global circuit breaker singleton."""
    return GlobalProviderCircuitBreaker.get_instance()
