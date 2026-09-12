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
DEFAULT_TIMEOUT_S = float(os.getenv("LOCAL_GEMMA_TIMEOUT_S", "3.0"))
DEFAULT_N_PREDICT = int(os.getenv("LOCAL_GEMMA_N_PREDICT", "12"))
DEFAULT_TEMPERATURE = float(os.getenv("LOCAL_GEMMA_TEMPERATURE", "0.2"))


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


class LocalGemmaClient:
    """Zero-cloud client for local Gemma 4 E2B Q4_K_S served by llama.cpp."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        logger: Optional[Callable[[str, str], None]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_s = float(timeout_s)
        self._log = logger or (lambda lvl, msg: None)
        self.completion_url = f"{self.base_url}/completion"
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

    def is_available(self, cache_ttl_s: float = 2.0) -> bool:
        """Cached availability check to prevent socket flood during high-frequency evaluation."""
        now = time.monotonic()
        if (now - self._last_health_check_ts) < cache_ttl_s:
            return self._last_health_status
        return self.health_check(timeout_s=0.5)

    def generate(
        self,
        prompt: str,
        n_predict: int = DEFAULT_N_PREDICT,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: Optional[float] = None,
    ) -> str:
        """Synchronously generates text from llama.cpp `/completion`.

        Payload matches exact llama.cpp specification.
        """
        if not prompt or not prompt.strip():
            return ""

        effective_timeout = float(timeout or self.timeout_s)
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "n_predict": int(n_predict),
            "temperature": float(temperature),
            "stream": False,
            "cache_prompt": True,
        }

        req = urllib.request.Request(
            self.completion_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Astro-LocalGemmaClient/1.0",
            },
            method="POST",
        )

        t_start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                if resp.status != 200:
                    raise LocalGemmaHTTPError(resp.status, f"Unexpected status code {resp.status}")
                raw = resp.read().decode("utf-8", errors="ignore").strip()
                if not raw:
                    raise LocalGemmaInvalidResponseError("Empty response body from llama-server")
                try:
                    data = json.loads(raw)
                except Exception as jde:
                    raise LocalGemmaInvalidResponseError(f"Malformed JSON: {jde}") from jde

                content = data.get("content", "")
                elapsed_ms = (time.perf_counter() - t_start) * 1000.0
                self._safe_log("debug", f"LocalGemma generate finished in {elapsed_ms:.1f}ms")
                return str(content)
        except urllib.error.HTTPError as http_err:
            code = http_err.code
            body = http_err.read().decode("utf-8", errors="ignore")
            if code == 503 or "loading" in body.lower():
                raise LocalGemmaModelUnavailableError(f"Model unavailable (503): {body}") from http_err
            raise LocalGemmaHTTPError(code, body) from http_err
        except urllib.error.URLError as url_err:
            reason = getattr(url_err, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason).lower():
                raise LocalGemmaTimeoutError(f"Connection timed out after {effective_timeout}s: {url_err}") from url_err
            raise LocalGemmaConnectionError(f"Cannot connect to llama-server at {self.completion_url}: {url_err}") from url_err
        except (socket.timeout, TimeoutError) as t_err:
            raise LocalGemmaTimeoutError(f"Request timed out after {effective_timeout}s: {t_err}") from t_err
        except LocalGemmaError:
            raise
        except Exception as exc:
            raise LocalGemmaError(f"Unexpected generation error: {exc}") from exc

    def stream(
        self,
        prompt: str,
        n_predict: int = DEFAULT_N_PREDICT,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: Optional[float] = None,
    ) -> Generator[str, None, None]:
        """Streams text chunks via SSE (`data: {...}`, `[DONE]`, `stop: true`).

        Yields individual token strings as they arrive from llama-server.
        """
        if not prompt or not prompt.strip():
            return

        effective_timeout = float(timeout or self.timeout_s)
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "n_predict": int(n_predict),
            "temperature": float(temperature),
            "stream": True,
            "cache_prompt": True,
        }

        req = urllib.request.Request(
            self.completion_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Astro-LocalGemmaClient/1.0",
            },
            method="POST",
        )

        try:
            resp = urllib.request.urlopen(req, timeout=effective_timeout)
        except urllib.error.HTTPError as http_err:
            code = http_err.code
            body = http_err.read().decode("utf-8", errors="ignore")
            if code == 503 or "loading" in body.lower():
                raise LocalGemmaModelUnavailableError(f"Model unavailable (503): {body}") from http_err
            raise LocalGemmaHTTPError(code, body) from http_err
        except urllib.error.URLError as url_err:
            reason = getattr(url_err, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason).lower():
                raise LocalGemmaTimeoutError(f"Connection timed out after {effective_timeout}s: {url_err}") from url_err
            raise LocalGemmaConnectionError(f"Cannot connect to llama-server at {self.completion_url}: {url_err}") from url_err
        except (socket.timeout, TimeoutError) as t_err:
            raise LocalGemmaTimeoutError(f"Request timed out after {effective_timeout}s: {t_err}") from t_err
        except Exception as exc:
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
