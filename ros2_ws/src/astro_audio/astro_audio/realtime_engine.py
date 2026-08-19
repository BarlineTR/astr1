#!/usr/bin/env python3
"""ASTRO V1 — OpenAI Realtime Engine (Primary Speech Engine).

Wraps the OpenAI Realtime WebSocket connection state and telemetry.
"""

from typing import Any, Dict, Optional
from astro_audio.base_tts_engine import BaseTTSEngine


class RealtimeEngine(BaseTTSEngine):
    """OpenAI Realtime WebSocket Speech Engine."""

    def __init__(self, model: str = "gpt-realtime", voice: str = "echo", logger=None):
        self._log = logger or (lambda lvl, msg: None)
        self.model = model
        self.voice = voice
        self._is_connected = False
        self._quota_exhausted = False
        self._rate_limited = False
        self._consecutive_errors = 0
        self._last_telemetry: Dict[str, Any] = {
            "model": model,
            "voice": voice,
            "connected": False,
            "quota_exhausted": False,
            "rate_limited": False,
        }

    @property
    def name(self) -> str:
        return "openai_realtime"

    def is_ready(self) -> bool:
        return self._is_connected and not self._quota_exhausted and not self._rate_limited

    def set_connected(self, connected: bool) -> None:
        self._is_connected = connected
        if connected:
            self._consecutive_errors = 0
        self._last_telemetry["connected"] = connected

    def mark_error(self, err_code: str or int, err_msg: str) -> None:
        err_str = str(err_msg).lower()
        if "1013" in str(err_code) or "quota" in err_str or "credit" in err_str:
            self._quota_exhausted = True
            self._last_telemetry["quota_exhausted"] = True
            self._log("warn", "⚠️ [RealtimeEngine] OpenAI Realtime Kredisi Tükendi (1013).")
        elif "429" in str(err_code) or "rate" in err_str:
            self._rate_limited = True
            self._last_telemetry["rate_limited"] = True
        self._consecutive_errors += 1

    def reset_quota_status(self) -> None:
        self._quota_exhausted = False
        self._rate_limited = False
        self._consecutive_errors = 0
        self._last_telemetry["quota_exhausted"] = False
        self._last_telemetry["rate_limited"] = False

    def synthesize_sentence(
        self,
        text: str,
        generation_id: int,
        language: str = "tr",
        **kwargs
    ) -> Optional[bytes]:
        """In Realtime mode, synthesis is streaming via WebSocket server-side audio."""
        return None

    def cancel(self, generation_id: int) -> None:
        pass

    def get_telemetry(self) -> Dict[str, Any]:
        return dict(self._last_telemetry)
