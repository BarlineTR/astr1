#!/usr/bin/env python3
"""ASTRO V1 — ElevenLabs Flash v2.5 TTS Engine (Production Grade).

Provides low-latency (~75ms) streaming text-to-speech with native Turkish support,
direct 24kHz 16-bit mono PCM output, strict error classification, and barge-in cancellation.

CLI Usage:
    python3 -m astro_audio.elevenlabs_engine --list-voices
"""

import argparse
import logging

_LOG = logging.getLogger(__name__)

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Generator, List, Optional, Tuple

try:
    from astro_audio.base_tts_engine import BaseTTSEngine
except ImportError:
    try:
        from base_tts_engine import BaseTTSEngine
    except ImportError:
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        from astro_audio.base_tts_engine import BaseTTSEngine


class ElevenLabsError(Exception):
    """Exception raised for ElevenLabs API errors with classification."""

    def __init__(self, error_class: str, message: str, status_code: int = 0):
        super().__init__(f"[{error_class}] (HTTP {status_code}): {message}")
        self.error_class = error_class
        self.message = message
        self.status_code = status_code


class ElevenLabsEngine(BaseTTSEngine):
    """ElevenLabs Flash v2.5 Low-Latency Streaming TTS Engine."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
        model_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        logger: Optional[Any] = None,
    ):
        self._enabled = (enabled if enabled is not None else os.getenv("ELEVENLABS_ENABLED", "false").lower() in ("1", "true", "yes"))
        # `or` DEĞİL `is None`: imza Optional[str] olduğuna göre None "ortamdan al"
        # demektir, "" ise "kimlik bilgisi YOK" demektir. `or` kullanıldığında açıkça
        # verilen "" sessizce ortam değişkeniyle doldurulup motoru hazır gösteriyordu
        # — çağıranın açık niyetinin tersi. Ortamda ELEVENLABS_API_KEY bulunduğu anda
        # ortaya çıkan gerçek bir hataydı.
        self._api_key = os.getenv("ELEVENLABS_API_KEY", "") if api_key is None else api_key
        self._voice_id = os.getenv("ELEVENLABS_VOICE_ID", "") if voice_id is None else voice_id
        self._model_id = os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5") if model_id is None else model_id
        self.logger = logger

        self._active_gen_id = 0
        self._is_available = bool(self._enabled and self._api_key and self._voice_id)
        self._last_error_class = "none"
        self._last_error_msg = ""
        self._cooldown_until = 0.0

    def _log(self, level: str, msg: str) -> None:
        if not self.logger:
            return
        lvl = str(level).lower()
        if lvl == "debug":
            fn = getattr(self.logger, "debug", getattr(self.logger, "info", print))
        elif lvl in ("warn", "warning"):
            fn = getattr(self.logger, "warn", getattr(self.logger, "warning", print))
        elif lvl == "error":
            fn = getattr(self.logger, "error", print)
        else:
            fn = getattr(self.logger, "info", print)
        try:
            fn(str(msg))
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "elevenlabs"

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._is_available = bool(self._enabled and self._api_key and self._voice_id)

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def voice_id(self) -> str:
        return self._voice_id

    def set_voice_id(self, voice_id: str) -> None:
        self._voice_id = voice_id
        self._is_available = bool(self._enabled and self._api_key and self._voice_id)

    def set_api_key(self, api_key: str) -> None:
        self._api_key = api_key
        self._is_available = bool(self._enabled and self._api_key and self._voice_id)

    def is_ready(self) -> bool:
        """Returns True ONLY if ElevenLabs is explicitly enabled, configured, and not under cooldown."""
        if not self._enabled or not self._api_key or not self._voice_id:
            return False
        if time.monotonic() < self._cooldown_until:
            return False
        return True

    def classify_error(self, http_code: int, error_body: str, exc: Optional[Exception] = None) -> str:
        """Classifies HTTP error into structured category."""
        body_lower = (error_body or "").lower()

        if http_code == 401:
            return "authentication_error"
        if http_code == 402 or "paid_plan_required" in body_lower or "billing_required" in body_lower:
            return "billing_required"
        if http_code == 404:
            return "voice_not_found"
        if http_code == 400:
            if "model" in body_lower:
                return "model_not_found"
            return "invalid_request"
        if http_code == 429:
            if any(w in body_lower for w in ("quota", "credit", "character", "billing", "unusual_activity")):
                return "quota_exhausted"
            return "rate_limited"
        if http_code in (500, 502, 503, 504):
            return "server_error"
        if isinstance(exc, (TimeoutError, urllib.error.URLError)):
            if "timed out" in str(exc).lower():
                return "timeout"
            return "network_error"
        return "server_error"

    def cancel(self, generation_id: int) -> None:
        """Marks generation cancelled to abort stream consumption."""
        self._active_gen_id = max(self._active_gen_id, generation_id)

    def stream_sentence_pcm(
        self,
        text: str,
        generation_id: int,
        language: str = "tr",
        timeout: float = 4.0,
        **kwargs
    ) -> Generator[bytes, None, None]:
        """Streams raw 24kHz int16 mono PCM chunks directly from ElevenLabs Flash v2.5."""
        if not text or not self.is_ready():
            return

        if generation_id < self._active_gen_id:
            return

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}/stream?output_format=pcm_24000"

        payload = {
            "text": text,
            "model_id": self._model_id,
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.75,
                "style": 0.25,
                "use_speaker_boost": True,
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "audio/pcm",
                "User-Agent": "Astro-V1-SocialRobot/2.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # ElevenLabs returns raw S16LE PCM at 24000Hz mono
                chunk_size = 960 * 2  # 20ms of 24kHz 16-bit audio = 1920 bytes
                while True:
                    if generation_id < self._active_gen_id:
                        # Cancelled mid-stream
                        break
                    chunk = resp.read(chunk_size)
                    if not chunk or generation_id < self._active_gen_id:
                        break
                    yield chunk

            self._last_error_class = "none"
            self._last_error_msg = ""

        except urllib.error.HTTPError as http_e:
            err_body = http_e.read().decode("utf-8", errors="ignore")
            err_class = self.classify_error(http_e.code, err_body, http_e)
            self._last_error_class = err_class
            self._last_error_msg = err_body[:100]

            if err_class in ("voice_not_found", "model_not_found", "authentication_error"):
                self._cooldown_until = time.monotonic() + 3600.0  # 1 hour permanent config cooldown
            elif err_class == "quota_exhausted":
                self._cooldown_until = time.monotonic() + 300.0  # 5 min quota cooldown
            elif err_class == "rate_limited":
                self._cooldown_until = time.monotonic() + 30.0
            else:
                self._cooldown_until = time.monotonic() + 10.0

            self._log("warn", f"⚠️ [ElevenLabs TTS] HTTP error ({err_class}): {err_body[:80]}")
            raise ElevenLabsError(err_class, err_body, http_e.code)

        except Exception as exc:
            err_class = self.classify_error(0, str(exc), exc)
            self._last_error_class = err_class
            self._last_error_msg = str(exc)[:100]
            self._cooldown_until = time.monotonic() + 10.0
            self._log("warn", f"⚠️ [ElevenLabs TTS] Network/system error ({err_class}): {exc}")
            raise ElevenLabsError(err_class, str(exc), 0)

    def synthesize_sentence(
        self,
        text: str,
        generation_id: int,
        language: str = "tr",
        timeout: float = 4.0,
        **kwargs
    ) -> Optional[bytes]:
        """Synthesizes text into complete 24kHz int16 mono PCM bytes."""
        try:
            chunks = []
            for chunk in self.stream_sentence_pcm(text, generation_id, language=language, timeout=timeout, **kwargs):
                if chunk:
                    chunks.append(chunk)
            return b"".join(chunks) if chunks else None
        except Exception:
            return None

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "provider": "elevenlabs",
            "model_id": self._model_id,
            "voice_id": self._voice_id,
            "is_ready": self.is_ready(),
            "last_error_class": self._last_error_class,
            "cooldown_remaining_sec": max(0, int(self._cooldown_until - time.monotonic())),
        }


def list_elevenlabs_voices(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetches list of available ElevenLabs voices without logging the API key."""
    key = api_key or os.getenv("ELEVENLABS_API_KEY", "")
    if not key:
        print("\n[!] ELEVENLABS_API_KEY environment variable is not set.\n")
        return []

    req = urllib.request.Request(
        "https://api.elevenlabs.io/v1/voices",
        headers={"xi-api-key": key, "User-Agent": "Astro-V1-SocialRobot/2.0"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("voices", [])
    except urllib.error.HTTPError as he:
        body = he.read().decode("utf-8", errors="ignore")
        print(f"\n[!] Failed to list voices (HTTP {he.code}): {body[:120]}\n")
        return []
    except Exception as e:
        print(f"\n[!] Failed to list voices: {e}\n")
        return []


def _cli_voices():
    parser = argparse.ArgumentParser(description="ASTRO V1 — ElevenLabs Voice Discovery CLI")
    parser.add_argument("--list-voices", action="store_true", help="List available ElevenLabs voices with metadata")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        env_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path)
        else:
            load_dotenv()
    except ImportError as _exc:
        _LOG.debug("_cli_voices: yok sayılan hata (%s)", _exc)

    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        print("\n[!] ELEVENLABS_API_KEY is not configured in .env or environment.")
        print("    Please set ELEVENLABS_API_KEY=... and ELEVENLABS_VOICE_ID=...\n")
        return

    voices = list_elevenlabs_voices(key)
    if not voices:
        print("[!] No voices found or authentication failed.")
        return

    print("\n" + "=" * 80)
    print(" [*] ASTRO V1 — ElevenLabs Available Voices")
    print("=" * 80)
    print(f"{'Voice ID':<26} | {'Name':<20} | {'Category':<12} | {'Labels / Description'}")
    print("-" * 80)

    for v in voices:
        v_id = v.get("voice_id", "")
        name = v.get("name", "")
        cat = v.get("category", "")
        labels = v.get("labels", {})
        label_str = ", ".join([f"{k}:{val}" for k, val in labels.items() if k in ("accent", "gender", "age", "use case", "language")])
        if not label_str:
            label_str = v.get("description", "") or "No metadata"
        print(f"{v_id:<26} | {name[:20]:<20} | {cat[:12]:<12} | {label_str[:35]}")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    _cli_voices()
