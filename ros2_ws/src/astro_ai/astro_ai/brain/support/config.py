"""ASTRO V1 — Cognitive Architecture Support Layer Configuration.

Loads environment variables with conservative defaults designed to prevent
unintended consumption of free-tier model quotas.

HARD SAFETY INVARIANTS:
  1. Default LLM_SUPPORT_ENABLED is FALSE.
  2. Max auto retries is ZERO by default.
  3. All local safety limits are strictly enforced locally BEFORE network calls.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _bool_env(key: str, default: bool) -> bool:
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _int_env(key: str, default: int) -> int:
    val = os.getenv(key)
    if val is None:
        return default
    try:
        return int(val.strip())
    except ValueError:
        return default


@dataclass
class SupportConfig:
    """Conservative runtime configuration for cognitive architecture support."""
    # Global switches
    llm_support_enabled: bool = False

    # Provider switches
    gemini_support_enabled: bool = False
    groq_support_enabled: bool = False

    # Secrets (API Keys)
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # Model identifiers
    gemini_support_model: str = "gemini-3.6-flash"
    groq_support_model: str = "qwen/qwen-2.5-coder-32b"

    # Local Safety Budget Limits (Conservatively lower than actual provider quotas)
    max_requests_per_minute: int = 3
    max_requests_per_hour: int = 15
    max_requests_per_day: int = 50
    max_total_tokens_per_day: int = 100_000

    # Per-request input token limits
    gemini_max_input_tokens: int = 10_000
    groq_max_input_tokens: int = 8_000

    # Caching and Debounce
    cache_ttl_seconds: int = 86400       # 24 hours
    cooldown_seconds: int = 10           # 10s topic debounce
    max_auto_retries: int = 0            # HARD REQUIREMENT: 0 by default

    @classmethod
    def from_env(cls) -> SupportConfig:
        """Loads configuration from environment variables with safe defaults."""
        return cls(
            llm_support_enabled=_bool_env("LLM_SUPPORT_ENABLED", False),
            gemini_support_enabled=_bool_env("GEMINI_SUPPORT_ENABLED", False),
            groq_support_enabled=_bool_env("GROQ_SUPPORT_ENABLED", False),
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
            gemini_support_model=os.getenv("GEMINI_SUPPORT_MODEL", "gemini-3.6-flash").strip(),
            groq_support_model=os.getenv("GROQ_SUPPORT_MODEL", "qwen/qwen-2.5-coder-32b").strip(),
            max_requests_per_minute=_int_env("SUPPORT_MAX_REQUESTS_PER_MINUTE", 3),
            max_requests_per_hour=_int_env("SUPPORT_MAX_REQUESTS_PER_HOUR", 15),
            max_requests_per_day=_int_env("SUPPORT_MAX_REQUESTS_PER_DAY", 50),
            max_total_tokens_per_day=_int_env("SUPPORT_MAX_TOTAL_TOKENS_PER_DAY", 100_000),
            gemini_max_input_tokens=_int_env("GEMINI_MAX_INPUT_TOKENS_PER_REQUEST", 10_000),
            groq_max_input_tokens=_int_env("GROQ_MAX_INPUT_TOKENS_PER_REQUEST", 8_000),
            cache_ttl_seconds=_int_env("SUPPORT_CACHE_TTL_SECONDS", 86400),
            cooldown_seconds=_int_env("SUPPORT_COOLDOWN_SECONDS", 10),
            max_auto_retries=_int_env("SUPPORT_MAX_AUTO_RETRIES", 0),
        )
