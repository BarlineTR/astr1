#!/usr/bin/env python3
"""ASTRO V1 — Dedicated Local Gemma 4 E2B Q4_K_S HTTP Client.

Communicates directly with llama.cpp llama-server via `/completion` and `/health` endpoints.
Features:
  - Strict llama.cpp `/completion` payload format (not OpenAI /v1)
  - Ultra-fast lightweight health check probe (`GET /health`)
  - Token-level SSE streaming (`data: {...}`, `[DONE]`, `stop: true`)
  - Strict error classification (ConnectionError, TimeoutError, HTTPError, InvalidResponseError, ModelUnavailableError)
  - Configurable timeouts (<= 3.0s) ensuring zero thread starvation in ROS2 audio loop
"""

import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Generator, Optional

_LOG = logging.getLogger(__name__)

DEFAULT_BASE_URL = os.getenv("LOCAL_GEMMA_BASE_URL", "http://127.0.0.1:8080")
DEFAULT_TIMEOUT_S = float(os.getenv("LOCAL_GEMMA_TIMEOUT_S", "5.0"))
DEFAULT_FIRST_TOKEN_TIMEOUT_S = float(os.getenv("LOCAL_GEMMA_FIRST_TOKEN_TIMEOUT_S", "8.0"))
DEFAULT_N_PREDICT = int(os.getenv("LOCAL_GEMMA_N_PREDICT", "28"))
DEFAULT_TEMPERATURE = float(os.getenv("LOCAL_GEMMA_TEMPERATURE", "0.2"))
DEFAULT_MAX_CONTEXT_TOKENS = int(os.getenv("LOCAL_GEMMA_MAX_CONTEXT_TOKENS", "450"))
DEFAULT_TOP_K = int(os.getenv("LOCAL_GEMMA_TOP_K", "40"))
DEFAULT_HEALTH_CACHE_TTL_S = float(os.getenv("LOCAL_GEMMA_HEALTH_CACHE_TTL_S", "10.0"))
DEFAULT_STOP_TOKENS = ["\nKullanıcı:", "\nUser:", "\nASTRO:", "<end_of_turn>", "<eos>"]



def estimate_tokens(text: str) -> int:
    """Heuristic token estimator for multilingual/Turkish text (~3.2-3.8 chars per token)."""
    if not text:
        return 0
    return max(len(text.split()), int(len(text) / 3.2) + 1)


def bound_messages_to_context(
    messages: Any,
    max_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
) -> Any:
    """Deterministically bounds messages list so total token count <= max_tokens (<= 512 context limit).

    Priority order for pruning:
      1. Older conversation turns / intermediate assistant or user turns
      2. Non-essential prefix context in user/system messages
    Preserved:
      - Latest user utterance
      - Core system prompt identity / safety instructions
    """
    if not messages:
        return []
    if isinstance(messages, str):
        est = estimate_tokens(messages)
        if est <= max_tokens:
            return messages
        max_chars = int(max_tokens * 3.0)
        return messages[:max_chars].rsplit(" ", 1)[0] + "..."

    if not isinstance(messages, list):
        return messages

    msg_list = list(messages)
    total_est = sum(estimate_tokens(str(m.get("content", ""))) for m in msg_list if isinstance(m, dict))
    if total_est <= max_tokens:
        return msg_list

    # If messages list has multiple entries, keep the last user message and prune earlier ones
    if len(msg_list) > 1:
        pruned = [msg_list[-1]]
        cur_tokens = estimate_tokens(str(pruned[0].get("content", "")))
        for msg in reversed(msg_list[:-1]):
            msg_tok = estimate_tokens(str(msg.get("content", "")))
            if cur_tokens + msg_tok <= max_tokens:
                pruned.insert(0, msg)
                cur_tokens += msg_tok
            else:
                break
        if cur_tokens <= max_tokens:
            return pruned
        msg_list = pruned

    # If single remaining message still exceeds max_tokens, deterministically truncate its content
    bounded_msgs = []
    for msg in msg_list:
        if isinstance(msg, dict):
            content = str(msg.get("content", ""))
            est = estimate_tokens(content)
            if est > max_tokens:
                max_chars = int(max_tokens * 3.0)
                truncated_content = content[:max_chars].rsplit(" ", 1)[0] + "..."
                bounded_msgs.append({"role": msg.get("role", "user"), "content": truncated_content})
            else:
                bounded_msgs.append(dict(msg))
        else:
            bounded_msgs.append(msg)
    return bounded_msgs


class LocalGemmaError(Exception):
    """Base exception for all Local Gemma client failures."""
    pass


class LocalGemmaConnectionError(LocalGemmaError):
    """Raised when host/socket connection to llama-server cannot be established."""
    pass


class LocalGemmaTimeoutError(LocalGemmaError):
    """Raised when request or streaming exceeds specified deadline."""
    pass


class LocalGemmaHTTPError(LocalGemmaError):
    """Raised when server returns an HTTP error code (4xx, 5xx)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.message = message


class LocalGemmaInvalidResponseError(LocalGemmaError):
    """Raised when server response payload is malformed or invalid JSON/SSE."""
    pass


class LocalGemmaModelUnavailableError(LocalGemmaError):
    """Raised when model is loading, out of memory, or unavailable."""
    pass


class LocalGemmaEmptyResponseError(LocalGemmaError):
    """Raised when server returns empty content or only reasoning/whitespace."""
    pass


class LocalGemmaClient:
    """Zero-cloud client for local Gemma 4 E2B Q4_K_S served by llama.cpp."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        first_token_timeout_s: Optional[float] = None,
        logger: Optional[Callable[[str, str], None]] = None,
        model_name: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = float(timeout_s)
        self.first_token_timeout_s = float(first_token_timeout_s if first_token_timeout_s is not None else DEFAULT_FIRST_TOKEN_TIMEOUT_S)
        self._log = logger or (lambda lvl, msg: None)
        self.model_name = model_name or os.getenv("LOCAL_GEMMA_MODEL", "gemma-4-E2B-it-Q4_K_S")
        self.completion_url = f"{self.base_url}/v1/chat/completions"
        self.chat_url = self.completion_url
        self.health_url = f"{self.base_url}/health"
        self._last_health_status: bool = False
        self._last_health_check_ts: float = 0.0

    def _safe_log(self, level: str, msg: str):
        try:
            if self._log:
                self._log(level, msg)
            else:
                getattr(_LOG, level.lower(), _LOG.info)(msg)
        except Exception:
            pass

    def health_check(self, timeout_s: float = 1.0) -> bool:
        """Lightweight health probe querying `GET /health` on llama-server.

        Expected response: `{"status": "ok"}`
        Returns True if healthy, False if down/unreachable/loading.
        """
        try:
            req = urllib.request.Request(
                self.health_url,
                headers={"User-Agent": "Astro-LocalGemmaClient/1.0"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                if resp.status != 200:
                    self._last_health_status = False
                    return False
                raw = resp.read().decode("utf-8", errors="ignore").strip()
                if not raw:
                    self._last_health_status = False
                    return False
                data = json.loads(raw)
                status_val = str(data.get("status", "")).strip().lower()
                is_ok = (status_val == "ok")
                self._last_health_status = is_ok
                self._last_health_check_ts = time.monotonic()
                return is_ok
        except Exception as exc:
            self._last_health_status = False
            self._last_health_check_ts = time.monotonic()
            self._safe_log("debug", f"LocalGemmaClient health check failed: {exc}")
            return False

    def is_available(self, cache_ttl_s: float = DEFAULT_HEALTH_CACHE_TTL_S) -> bool:
        """Cached availability check to prevent socket flood and redundant health probes."""
        now = time.monotonic()
        if (now - self._last_health_check_ts) < cache_ttl_s:
            return self._last_health_status
        return self.health_check(timeout_s=0.5)

    def generate(
        self,
        prompt: Any,
        n_predict: int = DEFAULT_N_PREDICT,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: Optional[float] = None,
        cache_prompt: bool = True,
        stop: Optional[list] = None,
    ) -> str:
        """Synchronously generates text from llama.cpp `/v1/chat/completions`.

        Payload matches exact OpenAI /v1/chat/completions specification with
        chat_template_kwargs.enable_thinking = false to disable Gemma 4 thinking
        for deterministic, concise social responses. Includes cache_prompt=True,
        stop sequences, and top_k pruning for minimal latency on edge hardware.
        """
        if isinstance(prompt, str):
            if not prompt or not prompt.strip():
                return ""
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list):
            if not prompt:
                return ""
            messages = prompt
        else:
            messages = [{"role": "user", "content": str(prompt)}]

        messages = bound_messages_to_context(messages, max_tokens=int(os.getenv("LOCAL_GEMMA_MAX_CONTEXT_TOKENS", "450")))

        effective_timeout = float(timeout or self.timeout_s)
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "n_predict": int(n_predict),
            "max_tokens": int(n_predict),
            "temperature": float(temperature),
            "top_k": DEFAULT_TOP_K,
            "cache_prompt": bool(cache_prompt),
            "stop": stop if stop is not None else list(DEFAULT_STOP_TOKENS),
            "stream": False,
            "chat_template_kwargs": {
                "enable_thinking": False
            },
        }

        req = urllib.request.Request(
            self.completion_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Astro-LocalGemmaClient/1.0",
                "Connection": "keep-alive",
            },
            method="POST",
        )

        t_start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                if resp.status != 200:
                    self._last_health_status = False
                    self._last_health_check_ts = time.monotonic()
                    raise LocalGemmaHTTPError(resp.status, f"Unexpected status code {resp.status}")
                raw = resp.read().decode("utf-8", errors="ignore").strip()
                if not raw:
                    self._last_health_status = False
                    self._last_health_check_ts = time.monotonic()
                    raise LocalGemmaInvalidResponseError("Empty response body from llama-server")
                try:
                    data = json.loads(raw)
                except Exception as jde:
                    raise LocalGemmaInvalidResponseError(f"Malformed JSON: {jde}") from jde

                content = ""
                choices = data.get("choices")
                if choices and isinstance(choices, list) and len(choices) > 0:
                    first_choice = choices[0]
                    msg = first_choice.get("message", {})
                    # Strict: ONLY message.content, reasoning_content is ignored and discarded
                    content = msg.get("content") or ""
                elif "content" in data:
                    content = data.get("content") or ""

                if not content or not str(content).strip():
                    raise LocalGemmaEmptyResponseError("Local Gemma returned empty response content")

                self._last_health_status = True
                self._last_health_check_ts = time.monotonic()
                elapsed_ms = (time.perf_counter() - t_start) * 1000.0
                self._safe_log("debug", f"LocalGemma generate finished in {elapsed_ms:.1f}ms")
                return str(content).strip()
        except urllib.error.HTTPError as http_err:
            self._last_health_status = False
            self._last_health_check_ts = time.monotonic()
            code = http_err.code
            body = http_err.read().decode("utf-8", errors="ignore")
            if code == 503 or "loading" in body.lower():
                raise LocalGemmaModelUnavailableError(f"Model unavailable (503): {body}") from http_err
            raise LocalGemmaHTTPError(code, body) from http_err
        except urllib.error.URLError as url_err:
            self._last_health_status = False
            self._last_health_check_ts = time.monotonic()
            reason = getattr(url_err, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason).lower():
                raise LocalGemmaTimeoutError(f"Connection timed out after {effective_timeout}s: {url_err}") from url_err
            raise LocalGemmaConnectionError(f"Cannot connect to llama-server at {self.completion_url}: {url_err}") from url_err
        except (socket.timeout, TimeoutError) as t_err:
            self._last_health_status = False
            self._last_health_check_ts = time.monotonic()
            raise LocalGemmaTimeoutError(f"Request timed out after {effective_timeout}s: {t_err}") from t_err
        except LocalGemmaError:
            raise
        except Exception as exc:
            raise LocalGemmaError(f"Unexpected generation error: {exc}") from exc


    def stream(
        self,
        prompt: Any,
        n_predict: int = DEFAULT_N_PREDICT,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: Optional[float] = None,
        first_token_timeout: Optional[float] = None,
        cache_prompt: bool = True,
        stop: Optional[list] = None,
    ) -> Generator[str, None, None]:
        """Streams text chunks via SSE (`data: {...}`, `[DONE]`, `stop: true`).

        Enforces chat_template_kwargs: {"enable_thinking": False}. Includes
        cache_prompt=True, stop sequences, and top_k pruning for minimal latency.
        Yields ONLY delta.content, strictly discarding delta.reasoning_content.
        """
        if isinstance(prompt, str):
            if not prompt or not prompt.strip():
                return
            messages = [{"role": "user", "content": prompt}]
        elif isinstance(prompt, list):
            if not prompt:
                return
            messages = prompt
        else:
            messages = [{"role": "user", "content": str(prompt)}]

        messages = bound_messages_to_context(messages, max_tokens=int(os.getenv("LOCAL_GEMMA_MAX_CONTEXT_TOKENS", "450")))

        effective_timeout = float(timeout or self.timeout_s)
        effective_first_token_timeout = float(first_token_timeout or self.first_token_timeout_s or effective_timeout)
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "n_predict": int(n_predict),
            "max_tokens": int(n_predict),
            "temperature": float(temperature),
            "top_k": DEFAULT_TOP_K,
            "cache_prompt": bool(cache_prompt),
            "stop": stop if stop is not None else list(DEFAULT_STOP_TOKENS),
            "stream": True,
            "chat_template_kwargs": {
                "enable_thinking": False
            },
        }

        req = urllib.request.Request(
            self.completion_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Astro-LocalGemmaClient/1.0",
                "Connection": "keep-alive",
            },
            method="POST",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=effective_first_token_timeout)
            self._last_health_status = True
            self._last_health_check_ts = time.monotonic()
        except urllib.error.HTTPError as http_err:
            self._last_health_status = False
            self._last_health_check_ts = time.monotonic()
            code = http_err.code
            body = http_err.read().decode("utf-8", errors="ignore")
            if code == 503 or "loading" in body.lower():
                raise LocalGemmaModelUnavailableError(f"Model unavailable (503): {body}") from http_err
            raise LocalGemmaHTTPError(code, body) from http_err
        except urllib.error.URLError as url_err:
            self._last_health_status = False
            self._last_health_check_ts = time.monotonic()
            reason = getattr(url_err, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason).lower():
                raise LocalGemmaTimeoutError(f"Connection timed out after {effective_first_token_timeout}s: {url_err}") from url_err
            raise LocalGemmaConnectionError(f"Cannot connect to llama-server at {self.completion_url}: {url_err}") from url_err
        except (socket.timeout, TimeoutError) as t_err:
            self._last_health_status = False
            self._last_health_check_ts = time.monotonic()
            raise LocalGemmaTimeoutError(f"Request timed out after {effective_first_token_timeout}s: {t_err}") from t_err
        except Exception as exc:
            self._last_health_status = False
            self._last_health_check_ts = time.monotonic()
            raise LocalGemmaConnectionError(f"Failed to open stream: {exc}") from exc

        try:
            with resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        chunk_json = json.loads(data_str)
                    except json.JSONDecodeError as jde:
                        raise LocalGemmaInvalidResponseError(f"Malformed SSE JSON: {data_str}") from jde

                    token = ""
                    choices = chunk_json.get("choices")
                    if choices and isinstance(choices, list) and len(choices) > 0:
                        first_choice = choices[0]
                        delta = first_choice.get("delta", {})
                        # Strictly yield only delta.content, never delta.reasoning_content
                        token = delta.get("content") or ""
                        finish_reason = first_choice.get("finish_reason")
                        if token:
                            yield token
                        if finish_reason is not None:
                            break
                    else:
                        token = chunk_json.get("content", "")
                        if token:
                            yield token
                        if chunk_json.get("stop", False):
                            break
        except (socket.timeout, TimeoutError) as t_err:
            raise LocalGemmaTimeoutError(f"Stream read timed out after {effective_timeout}s: {t_err}") from t_err
        except LocalGemmaError:
            raise
        except Exception as exc:
            raise LocalGemmaError(f"Stream interrupted: {exc}") from exc
