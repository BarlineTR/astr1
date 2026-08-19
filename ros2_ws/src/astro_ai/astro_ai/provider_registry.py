#!/usr/bin/env python3
"""ASTRO V1 — Dynamic Provider & Model Capability Registry.

Features:
  - Runtime REST discovery of active models for Groq & Gemini
  - Capability filtering (chat, streaming, vision, tool calling)
  - Strict error classification (quota_exhausted, rate_limited, unsupported_model, etc.)
  - Model blacklisting on 400/404 to prevent retry storms
  - Dynamic fallback model routing with cooldowns
"""

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generator, List, Optional, Tuple


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


# Fallback verified seed models (used only if initial discovery network fails)
VERIFIED_GROQ_SEEDS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama-3.1-70b-versatile",
    "gemma2-9b-it",
    "llama3-70b-8192",
    "llama3-8b-8192",
    "mixtral-8x7b-32768",
]

VERIFIED_GEMINI_SEEDS = [
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]


class ProviderRegistry:
    """Registry maintaining real-time model capabilities, availability, and error states."""

    def __init__(self, logger: Optional[Any] = None):
        self.logger = logger
        self._models: Dict[str, ModelCapability] = {}
        self._discovered_providers: set = set()

    def _log(self, level: str, msg: str) -> None:
        if self.logger:
            fn = getattr(self.logger, level, None) or getattr(self.logger, "info", print)
            fn(msg)

    def register_model(self, model: ModelCapability) -> None:
        key = f"{model.provider}:{model.model_id}"
        self._models[key] = model

    def get_model(self, provider: str, model_id: str) -> Optional[ModelCapability]:
        return self._models.get(f"{provider}:{model_id}")

    def discover_groq_models(self, api_key: str) -> List[str]:
        """Queries Groq /models API at runtime and registers active capability-filtered models."""
        if not api_key:
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
                # Exclude non-chat / lightweight / special task models
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

            # Sort by preferred priority
            preferred = [m for m in VERIFIED_GROQ_SEEDS if m in active_ids]
            for m in active_ids:
                if m not in preferred:
                    preferred.append(m)

            self._discovered_providers.add("groq")
            self._log("info", f"✅ [ProviderRegistry] Groq aktif modelleri doğrulandı: {preferred[:5]}")
            return preferred

        except Exception as e:
            self._log("warn", f"⚠️ [ProviderRegistry] Groq discovery başarısız ({e}), doğrulanmış seed listesi kullanılıyor.")
            for m_id in VERIFIED_GROQ_SEEDS:
                self.register_model(ModelCapability(provider="groq", model_id=m_id))
            return VERIFIED_GROQ_SEEDS

    def discover_gemini_models(self, api_key: str) -> List[str]:
        """Queries Google Gemini /models API at runtime and registers active capability-filtered models."""
        if not api_key:
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

            preferred = [m for m in VERIFIED_GEMINI_SEEDS if m in active_ids]
            for m in active_ids:
                if m not in preferred:
                    preferred.append(m)

            self._discovered_providers.add("gemini")
            self._log("info", f"✅ [ProviderRegistry] Gemini aktif modelleri doğrulandı: {preferred[:4]}")
            return preferred

        except Exception as e:
            self._log("warn", f"⚠️ [ProviderRegistry] Gemini discovery başarısız ({e}), doğrulanmış seed listesi kullanılıyor.")
            for m_id in VERIFIED_GEMINI_SEEDS:
                self.register_model(ModelCapability(provider="gemini", model_id=m_id))
            return VERIFIED_GEMINI_SEEDS

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
            if any(u in body_lower for u in ("not found", "model", "unsupported", "does not exist", "deprecated", "unknown")):
                return ErrorClass.UNSUPPORTED_MODEL
            return ErrorClass.UNSUPPORTED_MODEL

        if http_code in (500, 502, 503, 504):
            return ErrorClass.SERVER_ERROR

        if isinstance(exc, (TimeoutError, urllib.error.URLError)):
            if "timed out" in str(exc).lower():
                return ErrorClass.TIMEOUT
            return ErrorClass.NETWORK_ERROR

        return ErrorClass.SERVER_ERROR

    def record_error(self, provider: str, model_id: str, error_class: ErrorClass, error_msg: str) -> None:
        """Records an error for a model and applies appropriate cooldown or permanent blacklisting."""
        key = f"{provider}:{model_id}"
        model = self._models.get(key)
        if not model:
            model = ModelCapability(provider=provider, model_id=model_id)
            self._models[key] = model

        model.last_error = error_msg
        model.last_error_class = error_class
        model.consecutive_errors += 1
        now = time.monotonic()

        if error_class in (ErrorClass.UNSUPPORTED_MODEL, ErrorClass.MODEL_NOT_FOUND, ErrorClass.AUTHENTICATION_ERROR):
            model.is_blacklisted = True
            model.available = False
            self._log("error", f"⛔ [ProviderRegistry] Model kara listeye alındı ({error_class.value}): {provider}/{model_id} - {error_msg}")
        elif error_class == ErrorClass.QUOTA_EXHAUSTED:
            # Entire provider quota exhausted: cooldown 5 minutes
            model.cooldown_until = now + 300.0
            self._log("warn", f"⏳ [ProviderRegistry] Kota tükendi ({provider}/{model_id}): 300s cooldown.")
        elif error_class == ErrorClass.RATE_LIMITED:
            model.cooldown_until = now + 45.0
            self._log("warn", f"⏳ [ProviderRegistry] Rate limit ({provider}/{model_id}): 45s cooldown.")
        elif error_class == ErrorClass.SERVER_ERROR:
            model.cooldown_until = now + 20.0
        elif error_class in (ErrorClass.TIMEOUT, ErrorClass.NETWORK_ERROR):
            model.cooldown_until = now + 10.0

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

    def get_candidate_models(self, provider: str) -> List[str]:
        """Returns list of currently available, non-blacklisted models for provider."""
        now = time.monotonic()
        candidates = []
        for key, model in self._models.items():
            if model.provider == provider and not model.is_blacklisted and model.available:
                if model.cooldown_until <= now:
                    candidates.append(model.model_id)

        # If registry had none registered yet, load seed list
        if not candidates:
            seeds = VERIFIED_GROQ_SEEDS if provider == "groq" else VERIFIED_GEMINI_SEEDS
            for s in seeds:
                m = self.get_model(provider, s)
                if not m or (not m.is_blacklisted and m.cooldown_until <= now):
                    candidates.append(s)

        return candidates

    def stream_groq_completion(
        self,
        api_key: str,
        model_id: str,
        messages: List[Dict[str, str]],
        max_tokens: int = 100,
        temperature: float = 0.65,
        timeout: float = 2.5,
    ) -> Generator[str, None, None]:
        """Streams tokens from Groq Chat Completions API with strict error classification."""
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
        """Generates text from Google Gemini REST API with strict error classification."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
        
        # Build contents structure with system instruction and history
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
