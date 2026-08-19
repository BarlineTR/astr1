#!/usr/bin/env python3
"""ASTRO V1 — Dynamic Provider & Model Capability Registry (Production Grade).

Features:
  - Strict Runtime REST discovery of active models for Groq & Gemini (No blind seed fallbacks)
  - Capability filtering (chat, streaming, vision, tool calling)
  - Clear separation of Provider Health vs. Model Availability
  - Strict 8-class error classification
  - Immediate blacklisting on 400/404/unsupported with zero retry storm
  - Dynamic fallback model routing with cooldowns
  - CLI discovery command: `python3 provider_registry.py --discover`
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generator, List, Optional, Set, Tuple


class ErrorClass(str, Enum):
    NONE = "none"
    QUOTA_EXHAUSTED = "quota_exhausted"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    AUTHENTICATION_ERROR = "authentication_error"
    MODEL_NOT_FOUND = "model_not_found"
    UNSUPPORTED_MODEL = "unsupported_model"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"


class ProviderHealth(str, Enum):
    UNINITIALIZED = "uninitialized"
    HEALTHY = "healthy"
    DISCOVERY_UNAVAILABLE = "discovery_unavailable"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_FAILED = "authentication_failed"
    DISABLED = "disabled"


class ProviderError(Exception):
    """Exception raised when an LLM provider request fails."""

    def __init__(self, provider: str, model_id: str, error_class: ErrorClass, message: str, status_code: int = 0):
        super().__init__(f"[{provider}:{model_id}] ({error_class.value}): {message}")
        self.provider = provider
        self.model_id = model_id
        self.error_class = error_class
        self.message = message
        self.status_code = status_code


@dataclass
class ModelCapability:
    provider: str
    model_id: str
    chat_supported: bool = True
    streaming_supported: bool = True
    tool_calling_supported: bool = False
    vision_supported: bool = False
    available: bool = True
    is_blacklisted: bool = False
    cooldown_until: float = 0.0
    consecutive_errors: int = 0
    last_error: str = ""
    last_error_class: ErrorClass = ErrorClass.NONE
    last_latency_ms: float = 0.0


# Preference ordering among DISCOVERED models only (never used as unverified seed fallback)
GROQ_PREFERENCE_ORDER: List[str] = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "llama-3.1-70b-versatile",
    "gemma2-9b-it",
    "qwen-2.5-32b",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
]

GEMINI_PREFERENCE_ORDER: List[str] = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.5-flash",
]


class ProviderRegistry:
    """Registry maintaining real-time model capabilities, availability, and error states."""

    def __init__(self, logger: Optional[Any] = None):
        self.logger = logger
        self._models: Dict[str, ModelCapability] = {}
        self._provider_health: Dict[str, ProviderHealth] = {
            "groq": ProviderHealth.UNINITIALIZED,
            "gemini": ProviderHealth.UNINITIALIZED,
            "openai": ProviderHealth.UNINITIALIZED,
            "local": ProviderHealth.HEALTHY,
        }
        self._discovered_models: Dict[str, List[str]] = {
            "groq": [],
            "gemini": [],
        }

    def _log(self, level: str, msg: str) -> None:
        if self.logger:
            fn = getattr(self.logger, level, None) or getattr(self.logger, "info", print)
            fn(msg)

    def get_provider_health(self, provider: str) -> ProviderHealth:
        return self._provider_health.get(provider, ProviderHealth.UNINITIALIZED)

    def set_provider_health(self, provider: str, health: ProviderHealth) -> None:
        self._provider_health[provider] = health

    def register_model(self, model: ModelCapability) -> None:
        key = f"{model.provider}:{model.model_id}"
        self._models[key] = model

    def get_model(self, provider: str, model_id: str) -> Optional[ModelCapability]:
        return self._models.get(f"{provider}:{model_id}")

    def is_routeable(self, provider: str, model_id: str) -> bool:
        """Returns True if the provider is healthy and the model is discovered, not blacklisted, and not under cooldown."""
        health = self.get_provider_health(provider)
        if health in (ProviderHealth.DISCOVERY_UNAVAILABLE, ProviderHealth.AUTHENTICATION_FAILED, ProviderHealth.DISABLED):
            return False

        model = self.get_model(provider, model_id)
        if not model:
            return False
        if model.is_blacklisted or not model.available:
            return False
        if model.cooldown_until > time.monotonic():
            return False

        return True

    def discover_models(self, provider: str, api_key: str) -> List[str]:
        """Dispatches discovery to the specific provider and updates registry without blind fallbacks."""
        if provider == "groq":
            return self._discover_groq_models(api_key)
        elif provider == "gemini":
            return self._discover_gemini_models(api_key)
        return []

    def _discover_groq_models(self, api_key: str) -> List[str]:
        """Queries Groq /models API at runtime and registers active capability-filtered models."""
        if not api_key:
            self._provider_health["groq"] = ProviderHealth.DISABLED
            return []

        try:
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "Astro-V1-SocialRobot/2.0",
                },
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_models = data.get("data", [])

            active_ids = []
            exclusions = ("whisper", "guard", "embed", "vision", "specdec", "allam", "r1", "deepseek", "compound", "1b", "3b")

            for item in raw_models:
                m_id = item.get("id", "")
                if not m_id:
                    continue
                if any(x in m_id.lower() for x in exclusions):
                    continue
                if item.get("active") is False:
                    continue

                active_ids.append(m_id)
                self.register_model(
                    ModelCapability(
                        provider="groq",
                        model_id=m_id,
                        chat_supported=True,
                        streaming_supported=True,
                        tool_calling_supported="llama" in m_id.lower() or "qwen" in m_id.lower(),
                        vision_supported="vision" in m_id.lower(),
                    )
                )

            # Order by preferred priority among actually discovered models
            ordered = [m for m in GROQ_PREFERENCE_ORDER if m in active_ids]
            for m in active_ids:
                if m not in ordered:
                    ordered.append(m)

            if ordered:
                self._provider_health["groq"] = ProviderHealth.HEALTHY
                self._discovered_models["groq"] = ordered
                self._log("info", f"✅ ProviderRegistry: Groq discovered {len(ordered)} routeable chat models: {ordered[:4]}")
            else:
                self._provider_health["groq"] = ProviderHealth.DISCOVERY_UNAVAILABLE
                self._log("warn", "⚠️ ProviderRegistry: Groq discovery returned 0 routeable chat models.")

            return ordered

        except urllib.error.HTTPError as http_e:
            err_body = http_e.read().decode("utf-8", errors="ignore")
            if http_e.code in (401, 403):
                self._provider_health["groq"] = ProviderHealth.AUTHENTICATION_FAILED
                self._log("error", f"⛔ ProviderRegistry: Groq authentication failed (HTTP {http_e.code}).")
            else:
                self._provider_health["groq"] = ProviderHealth.DISCOVERY_UNAVAILABLE
                self._log("warn", f"⚠️ ProviderRegistry: Groq discovery HTTP error {http_e.code}: {err_body[:100]}")
            return []
        except Exception as e:
            self._provider_health["groq"] = ProviderHealth.DISCOVERY_UNAVAILABLE
            self._log("warn", f"⚠️ ProviderRegistry: Groq discovery failed ({e}). Provider marked DISCOVERY_UNAVAILABLE.")
            return []

    def _discover_gemini_models(self, api_key: str) -> List[str]:
        """Queries Google Gemini /models API at runtime and registers active capability-filtered models."""
        if not api_key:
            self._provider_health["gemini"] = ProviderHealth.DISABLED
            return []

        try:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
                headers={"User-Agent": "Astro-V1-SocialRobot/2.0"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_models = data.get("models", [])

            active_ids = []
            exclusions = ("embedding", "aqa", "imagen", "learnlm", "tts", "stt", "bison", "chat-bison")

            for item in raw_models:
                raw_name = item.get("name", "")
                m_id = raw_name.replace("models/", "")
                methods = item.get("supportedGenerationMethods", [])
                if "generateContent" not in methods:
                    continue
                if any(x in m_id.lower() for x in exclusions):
                    continue

                active_ids.append(m_id)
                self.register_model(
                    ModelCapability(
                        provider="gemini",
                        model_id=m_id,
                        chat_supported=True,
                        streaming_supported=True,
                        tool_calling_supported=True,
                        vision_supported="flash" in m_id.lower() or "pro" in m_id.lower(),
                    )
                )

            ordered = [m for m in GEMINI_PREFERENCE_ORDER if m in active_ids]
            for m in active_ids:
                if m not in ordered:
                    ordered.append(m)

            if ordered:
                self._provider_health["gemini"] = ProviderHealth.HEALTHY
                self._discovered_models["gemini"] = ordered
                self._log("info", f"✅ ProviderRegistry: Gemini discovered {len(ordered)} routeable chat models: {ordered[:4]}")
            else:
                self._provider_health["gemini"] = ProviderHealth.DISCOVERY_UNAVAILABLE
                self._log("warn", "⚠️ ProviderRegistry: Gemini discovery returned 0 routeable chat models.")

            return ordered

        except urllib.error.HTTPError as http_e:
            err_body = http_e.read().decode("utf-8", errors="ignore")
            if http_e.code in (401, 403):
                self._provider_health["gemini"] = ProviderHealth.AUTHENTICATION_FAILED
                self._log("error", f"⛔ ProviderRegistry: Gemini authentication failed (HTTP {http_e.code}).")
            else:
                self._provider_health["gemini"] = ProviderHealth.DISCOVERY_UNAVAILABLE
                self._log("warn", f"⚠️ ProviderRegistry: Gemini discovery HTTP error {http_e.code}: {err_body[:100]}")
            return []
        except Exception as e:
            self._provider_health["gemini"] = ProviderHealth.DISCOVERY_UNAVAILABLE
            self._log("warn", f"⚠️ ProviderRegistry: Gemini discovery failed ({e}). Provider marked DISCOVERY_UNAVAILABLE.")
            return []

    def classify_error(self, http_code: int, error_body: str, exc: Optional[Exception] = None) -> ErrorClass:
        """Classifies HTTP status codes and error payloads into strict ErrorClass."""
        body_lower = (error_body or "").lower()

        if http_code in (401, 403):
            return ErrorClass.AUTHENTICATION_ERROR

        if http_code == 404:
            return ErrorClass.MODEL_NOT_FOUND

        if http_code == 429:
            if any(q in body_lower for q in ("quota", "insufficient_quota", "exceeded", "credit", "billing")):
                return ErrorClass.QUOTA_EXHAUSTED
            return ErrorClass.RATE_LIMITED

        if http_code == 400:
            if any(u in body_lower for u in ("not found", "model", "unsupported", "does not exist", "deprecated", "unknown", "invalid model")):
                return ErrorClass.UNSUPPORTED_MODEL
            return ErrorClass.UNSUPPORTED_MODEL

        if http_code in (500, 502, 503, 504):
            return ErrorClass.SERVER_ERROR

        if isinstance(exc, (TimeoutError, urllib.error.URLError)):
            if "timed out" in str(exc).lower():
                return ErrorClass.TIMEOUT
            return ErrorClass.NETWORK_ERROR

        return ErrorClass.SERVER_ERROR

    def mark_unavailable(
        self,
        provider: str,
        model_id: str,
        error_class: ErrorClass,
        cooldown: Optional[float] = None
    ) -> None:
        """Marks a model as blacklisted or in cooldown and updates provider state."""
        key = f"{provider}:{model_id}"
        model = self._models.get(key)
        if not model:
            model = ModelCapability(provider=provider, model_id=model_id)
            self._models[key] = model

        model.last_error_class = error_class
        model.consecutive_errors += 1
        now = time.monotonic()

        if error_class in (ErrorClass.UNSUPPORTED_MODEL, ErrorClass.MODEL_NOT_FOUND, ErrorClass.AUTHENTICATION_ERROR):
            model.is_blacklisted = True
            model.available = False
            self._log("error", f"⛔ [ProviderRegistry] Model permanently blacklisted ({error_class.value}): {provider}/{model_id}")
        elif error_class == ErrorClass.QUOTA_EXHAUSTED:
            model.cooldown_until = now + (cooldown or 300.0)
            self.set_provider_health(provider, ProviderHealth.RATE_LIMITED)
            self._log("warn", f"⏳ [ProviderRegistry] Quota exhausted ({provider}/{model_id}): {cooldown or 300.0}s cooldown.")
        elif error_class == ErrorClass.RATE_LIMITED:
            model.cooldown_until = now + (cooldown or 45.0)
            self._log("warn", f"⏳ [ProviderRegistry] Rate limit ({provider}/{model_id}): {cooldown or 45.0}s cooldown.")
        elif error_class == ErrorClass.SERVER_ERROR:
            model.cooldown_until = now + (cooldown or 20.0)
        elif error_class in (ErrorClass.TIMEOUT, ErrorClass.NETWORK_ERROR):
            model.cooldown_until = now + (cooldown or 10.0)

    def record_error(self, provider: str, model_id: str, error_class: ErrorClass, error_msg: str) -> None:
        """Legacy helper recording error message and marking unavailable."""
        key = f"{provider}:{model_id}"
        model = self._models.get(key)
        if model:
            model.last_error = error_msg
        self.mark_unavailable(provider, model_id, error_class)

    def record_success(self, provider: str, model_id: str, latency_ms: float) -> None:
        """Records a successful turn completion for a model."""
        key = f"{provider}:{model_id}"
        model = self._models.get(key)
        if model:
            model.consecutive_errors = 0
            model.last_error = ""
            model.last_error_class = ErrorClass.NONE
            model.last_latency_ms = latency_ms
            model.cooldown_until = 0.0
        self.set_provider_health(provider, ProviderHealth.HEALTHY)

    def get_available_models(self, provider: str) -> List[str]:
        """Returns list of currently available, non-blacklisted models for provider."""
        health = self.get_provider_health(provider)
        if health in (ProviderHealth.DISCOVERY_UNAVAILABLE, ProviderHealth.AUTHENTICATION_FAILED, ProviderHealth.DISABLED):
            return []

        now = time.monotonic()
        candidates = []
        # Maintain preference order from discovery
        discovered = self._discovered_models.get(provider, [])
        for m_id in discovered:
            if self.is_routeable(provider, m_id):
                candidates.append(m_id)

        return candidates

    def get_candidate_models(self, provider: str) -> List[str]:
        """Alias for get_available_models."""
        return self.get_available_models(provider)

    def select_best_model(self, provider: str, capabilities: Optional[List[str]] = None) -> Optional[str]:
        """Selects the highest-priority routeable model matching the required capabilities."""
        available = self.get_available_models(provider)
        if not available:
            return None

        if not capabilities:
            return available[0]

        for m_id in available:
            model = self.get_model(provider, m_id)
            if not model:
                continue
            matches = True
            for cap in capabilities:
                if not getattr(model, f"{cap}_supported", False):
                    matches = False
                    break
            if matches:
                return m_id

        return available[0]

    def stream_groq_completion(
        self,
        api_key: str,
        model_id: str,
        messages: List[Dict[str, str]],
        max_tokens: int = 100,
        temperature: float = 0.65,
        timeout: float = 2.5,
    ) -> Generator[str, None, None]:
        """Streams tokens from Groq Chat Completions API with strict error classification and immediate blacklisting."""
        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
            "top_p": 0.9,
            "presence_penalty": 0.2,
            "max_tokens": max_tokens,
            "stream": True,
        }

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Astro-V1-SocialRobot/2.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_json = json.loads(data_str)
                        delta = chunk_json.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            yield token
                    except Exception:
                        pass
        except urllib.error.HTTPError as http_e:
            err_body = http_e.read().decode("utf-8", errors="ignore")
            err_class = self.classify_error(http_e.code, err_body, http_e)
            self.record_error("groq", model_id, err_class, err_body)
            raise ProviderError("groq", model_id, err_class, err_body, http_e.code)
        except Exception as ge:
            err_class = self.classify_error(0, str(ge), ge)
            self.record_error("groq", model_id, err_class, str(ge))
            raise ProviderError("groq", model_id, err_class, str(ge))

    def generate_gemini_content(
        self,
        api_key: str,
        model_id: str,
        system_prompt: str,
        messages: List[Dict[str, str]],
        max_tokens: int = 100,
        temperature: float = 0.65,
        timeout: float = 4.0,
    ) -> str:
        """Generates text from Google Gemini REST API with strict error classification and immediate blacklisting."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"

        conv_text = "\n".join([f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages])
        full_text = f"SİSTEM YÖNERGESİ:\n{system_prompt}\n\nKONUŞMA GEÇMİŞİ:\n{conv_text}"

        gem_payload = {
            "contents": [{"parts": [{"text": full_text}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(gem_payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Astro-V1-SocialRobot/2.0"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res_json = json.loads(resp.read().decode("utf-8"))
                candidates = res_json.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
                return ""
        except urllib.error.HTTPError as http_e:
            err_body = http_e.read().decode("utf-8", errors="ignore")
            err_class = self.classify_error(http_e.code, err_body, http_e)
            self.record_error("gemini", model_id, err_class, err_body)
            raise ProviderError("gemini", model_id, err_class, err_body, http_e.code)
        except Exception as ge:
            err_class = self.classify_error(0, str(ge), ge)
            self.record_error("gemini", model_id, err_class, str(ge))
            raise ProviderError("gemini", model_id, err_class, str(ge))


def _cli_discover():
    parser = argparse.ArgumentParser(description="ASTRO V1 Runtime Provider & Model Discovery Tool")
    parser.add_argument("--discover", action="store_true", help="Queries and prints routeable models for Groq & Gemini")
    args = parser.parse_args()

    # Load environment variables if present
    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
        else:
            load_dotenv()
    except ImportError:
        pass

    groq_key = os.environ.get("GROQ_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")

    registry = ProviderRegistry()
    groq_models = registry.discover_models("groq", groq_key) if groq_key else []
    gemini_models = registry.discover_models("gemini", gemini_key) if gemini_key else []

    print("\n" + "=" * 65)
    print(" [*] ASTRO V1 Runtime Provider Discovery Report")
    print("=" * 65)

    print(f"\n[Groq] Status: {registry.get_provider_health('groq').value.upper()}")
    if groq_models:
        print(f"  Routeable Chat Models ({len(groq_models)}):")
        for m in groq_models:
            print(f"    - {m}")
    else:
        print("  [!] No routeable Groq models discovered.")

    print(f"\n[Gemini] Status: {registry.get_provider_health('gemini').value.upper()}")
    if gemini_models:
        print(f"  Routeable Chat Models ({len(gemini_models)}):")
        for m in gemini_models:
            print(f"    - {m}")
    else:
        print("  [!] No routeable Gemini models discovered.")

    print("=" * 65 + "\n")


if __name__ == "__main__":
    _cli_discover()
