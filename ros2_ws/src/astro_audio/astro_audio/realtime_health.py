"""Authoritative OpenAI Realtime health derived from socket + session state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RealtimeHealthSnapshot:
    provider_state: str = "AVAILABLE"
    connection_state: str = "DISCONNECTED"
    session_state: str = "NOT_READY"
    response_state: str = "IDLE"
    realtime_audio_received: bool = False
    session_id: str = ""
    model: str = ""
    requested_provider: str = "openai_realtime"
    actual_provider: str = "openai_realtime"
    fallback_reason: str = "none"

    def is_primary_eligible(self) -> bool:
        return (
            self.provider_state == "AVAILABLE"
            and self.connection_state == "CONNECTED"
            and self.session_state == "READY"
        )


class RealtimeHealthTracker:
    """Tracks Realtime socket/session state separately from circuit breaker."""

    def __init__(self) -> None:
        self.provider_state: str = "AVAILABLE"
        self.connection_state: str = "DISCONNECTED"
        self.session_state: str = "NOT_READY"
        self.response_state: str = "IDLE"
        self.realtime_audio_received: bool = False
        self.session_id: str = ""
        self.model: str = ""
        self.requested_provider: str = "openai_realtime"
        self.actual_provider: str = "openai_realtime"
        self.fallback_reason: str = "none"

    def set_provider_state(self, state: str) -> None:
        self.provider_state = state

    def mark_connecting(self, model: str) -> None:
        self.model = model
        self.connection_state = "CONNECTING"
        self.session_state = "NOT_READY"
        self.response_state = "IDLE"
        self.realtime_audio_received = False
        self.actual_provider = "openai_realtime"
        self.fallback_reason = "none"

    def mark_connected(self, session_id: str = "") -> None:
        self.connection_state = "CONNECTED"
        self.session_state = "READY"
        self.session_id = session_id or self.session_id or "active"
        self.actual_provider = "openai_realtime"
        self.fallback_reason = "none"

    def mark_disconnected(self, reason: str = "realtime_unavailable") -> None:
        self.connection_state = "DISCONNECTED"
        self.session_state = "NOT_READY"
        self.response_state = "IDLE"
        if self.provider_state == "AVAILABLE":
            self.fallback_reason = reason

    def mark_response_started(self) -> None:
        self.response_state = "GENERATING"
        self.realtime_audio_received = False
        self.actual_provider = "openai_realtime"
        self.fallback_reason = "none"

    def mark_audio_delta(self) -> None:
        self.realtime_audio_received = True
        self.actual_provider = "openai_realtime"
        self.fallback_reason = "none"

    def mark_response_done(self) -> None:
        self.response_state = "IDLE"

    def mark_fallback(self, actual_provider: str, reason: str) -> None:
        self.actual_provider = actual_provider
        self.fallback_reason = reason

    def is_primary_eligible(self) -> bool:
        return RealtimeHealthSnapshot(
            provider_state=self.provider_state,
            connection_state=self.connection_state,
            session_state=self.session_state,
            response_state=self.response_state,
        ).is_primary_eligible()

    def snapshot(
        self,
        requested_provider: Optional[str] = None,
        actual_provider: Optional[str] = None,
        fallback_reason: Optional[str] = None,
    ) -> RealtimeHealthSnapshot:
        return RealtimeHealthSnapshot(
            provider_state=self.provider_state,
            connection_state=self.connection_state,
            session_state=self.session_state,
            response_state=self.response_state,
            realtime_audio_received=self.realtime_audio_received,
            session_id=self.session_id,
            model=self.model,
            requested_provider=requested_provider or self.requested_provider,
            actual_provider=actual_provider or self.actual_provider,
            fallback_reason=fallback_reason or self.fallback_reason,
        )

    def format_turn_telemetry(self, **overrides: str) -> str:
        snap = self.snapshot(**{k: v for k, v in overrides.items() if k in RealtimeHealthSnapshot.__dataclass_fields__})
        return (
            f"realtime_provider_state={snap.provider_state}\n"
            f"realtime_connection_state={snap.connection_state}\n"
            f"realtime_session_state={snap.session_state}\n"
            f"realtime_response_state={snap.response_state}\n"
            f"realtime_audio_received={str(snap.realtime_audio_received).lower()}\n"
            f"realtime_model={snap.model or 'unknown'}\n"
            f"realtime_session_id={snap.session_id or 'none'}\n"
            f"requested_provider={snap.requested_provider}\n"
            f"actual_provider={snap.actual_provider}\n"
            f"fallback_reason={snap.fallback_reason}"
        )
