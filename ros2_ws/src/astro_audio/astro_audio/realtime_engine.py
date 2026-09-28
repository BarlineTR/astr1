"""ASTRO V1 — OpenAI Realtime Engine (Primary Speech Engine).

Coordinates WebSocket connection lifecycle, error classification, and state machine transitions.

State Machine:
  - REALTIME_STARTING
  - REALTIME_ACTIVE
  - REALTIME_DEGRADED
  - REALTIME_QUOTA_EXHAUSTED
  - REALTIME_OFFLINE
  - REALTIME_FAILED
"""

import enum
import time
from typing import Any, Callable, Dict, Optional, Tuple

from astro_audio.base_tts_engine import BaseTTSEngine


class RealtimeState(enum.Enum):
    REALTIME_STARTING = "REALTIME_STARTING"
    REALTIME_ACTIVE = "REALTIME_ACTIVE"
    REALTIME_DEGRADED = "REALTIME_DEGRADED"
    REALTIME_QUOTA_EXHAUSTED = "REALTIME_QUOTA_EXHAUSTED"
    REALTIME_OFFLINE = "REALTIME_OFFLINE"
    REALTIME_FAILED = "REALTIME_FAILED"


def classify_realtime_error(err_code: Any, err_msg: str) -> Tuple[RealtimeState, str]:
    """Deterministically classifies OpenAI Realtime error codes and exception messages."""
    code_str = str(err_code or "").lower()
    msg_str = str(err_msg or "").lower()
    combined = f"{code_str} {msg_str}"

    # 1. Quota & Credit exhaustion (402, insufficient_quota, credit_balance_exhausted, quota_exhausted, billing)
    if any(k in combined for k in ("402", "insufficient_quota", "quota_exhausted", "credit_balance_exhausted", "exceeded your current quota", "exceeded your credit", "billing", "quota")):
        return RealtimeState.REALTIME_QUOTA_EXHAUSTED, "realtime_quota_exhausted"

    # 2. Temporary overload / WS 1013 without quota error (Server overload, NOT Quota Exhaustion)
    if "1013" in combined or "temporary" in combined or "try again later" in combined or "overloaded" in combined:
        return RealtimeState.REALTIME_DEGRADED, "realtime_temporary_1013"

    # 3. Authentication / Authorization failure
    if any(k in combined for k in ("401", "403", "invalid_api_key", "unauthorized", "forbidden", "auth_error")):
        return RealtimeState.REALTIME_FAILED, "realtime_auth_error"

    # 4. Network / DNS / WebSocket disconnect
    if any(k in combined for k in ("1006", "connection timeout", "timed out", "connection reset", "broken pipe", "dns", "getaddrinfo", "network", "websocket closed")):
        return RealtimeState.REALTIME_OFFLINE, "realtime_network_unavailable"

    # 5. Rate limiting (429 RPM / TPM)
    if "429" in combined or "rate" in combined:
        return RealtimeState.REALTIME_DEGRADED, "realtime_rate_limited"

    # 6. Generic session / server error
    return RealtimeState.REALTIME_DEGRADED, "realtime_session_error"


class RealtimeEngine(BaseTTSEngine):
    """Authoritative OpenAI Realtime WebSocket Speech Engine."""

    def __init__(
        self,
        model: str = "gpt-realtime-2.1-mini",
        voice: str = "echo",
        logger: Optional[Callable[[str, str], None]] = None,
        on_state_change: Optional[Callable[[RealtimeState, str], None]] = None,
    ):
        self._log = logger or (lambda lvl, msg: None)
        self.model = model
        self.voice = voice
        self._state = RealtimeState.REALTIME_STARTING
        self._last_failure_reason = "none"
        self._on_state_change_cb = on_state_change
        self._consecutive_errors = 0

        self._last_telemetry: Dict[str, Any] = {
            "model": model,
            "voice": voice,
            "state": self._state.value,
            "connected": False,
            "failure_reason": "none",
        }

    def _safe_log(self, lvl: str, msg: str):
        try:
            if self._log:
                self._log(lvl, msg)
            else:
                print(f"[{lvl.upper()}] {msg}", flush=True)
        except Exception:
            pass

    @property
    def name(self) -> str:
        return "openai_realtime"

    @property
    def state(self) -> RealtimeState:
        return self._state

    @property
    def _quota_exhausted(self) -> bool:
        return self._state == RealtimeState.REALTIME_QUOTA_EXHAUSTED

    @property
    def _rate_limited(self) -> bool:
        return self._state == RealtimeState.REALTIME_DEGRADED

    @property
    def _is_connected(self) -> bool:
        return self._state == RealtimeState.REALTIME_ACTIVE

    def is_ready(self) -> bool:
        return self._state == RealtimeState.REALTIME_ACTIVE

    def set_connected(self, connected: bool) -> None:
        """Sets connection state, transitioning to REALTIME_ACTIVE on successful connection."""
        prev = self._state
        if connected:
            self._state = RealtimeState.REALTIME_ACTIVE
            self._consecutive_errors = 0
            self._last_failure_reason = "none"
            self._safe_log("info", f"✅ [RealtimeEngine] OpenAI Realtime WebSocket Aktif ({self.model}, voice={self.voice})")
        else:
            if self._state == RealtimeState.REALTIME_ACTIVE:
                self._state = RealtimeState.REALTIME_OFFLINE
                self._last_failure_reason = "realtime_websocket_disconnected"
                self._safe_log(
                    "warn",
                    f"🚨 [REALTIME DEGRADED]\n"
                    f"  reason=realtime_websocket_disconnected\n"
                    f"  previous_state={prev.value}\n"
                    f"  fallback_provider=edge_tts"
                )

        self._last_telemetry["state"] = self._state.value
        self._last_telemetry["connected"] = connected
        self._last_telemetry["failure_reason"] = self._last_failure_reason

        if self._on_state_change_cb and prev != self._state:
            self._on_state_change_cb(self._state, self._last_failure_reason)

    def mark_error(self, err_code: Any, err_msg: str) -> Tuple[RealtimeState, str]:
        """Classifies error, updates state machine, and emits deterministic degradation log."""
        new_state, failure_reason = classify_realtime_error(err_code, err_msg)
        prev = self._state
        self._state = new_state
        self._last_failure_reason = failure_reason
        self._consecutive_errors += 1

        self._safe_log(
            "warn",
            f"🚨 [REALTIME DEGRADED]\n"
            f"  reason={failure_reason}\n"
            f"  previous_state={prev.value}\n"
            f"  fallback_provider=edge_tts\n"
            f"  raw_error={err_code}: {err_msg}"
        )

        self._last_telemetry.update({
            "state": self._state.value,
            "connected": False,
            "failure_reason": failure_reason,
            "last_raw_error": f"{err_code}: {err_msg}",
        })

        if self._on_state_change_cb and prev != self._state:
            self._on_state_change_cb(self._state, failure_reason)

        return new_state, failure_reason

    def handle_websocket_error(self, err_code: Any, err_msg: str) -> Tuple[RealtimeState, str]:
        """Convenience alias for mark_error."""
        return self.mark_error(err_code, err_msg)

    def reset_quota_status(self) -> None:
        """Resets quota state on recovery probe."""
        self._state = RealtimeState.REALTIME_ACTIVE
        self._consecutive_errors = 0
        self._last_failure_reason = "none"
        self._last_telemetry["state"] = self._state.value
        self._last_telemetry["failure_reason"] = "none"

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
