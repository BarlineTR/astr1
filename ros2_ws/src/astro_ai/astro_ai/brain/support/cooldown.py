"""ASTRO V1 — Topic Cooldown and Request Debouncer.

Prevents rapid successive requests on the same architecture topic from generating
duplicate external model API calls.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional


class TopicCooldownDebouncer:
    """Thread-safe debouncer tracking cooldown intervals per architecture topic and provider."""

    def __init__(self, default_cooldown_seconds: float = 10.0):
        self.default_cooldown = default_cooldown_seconds
        self._lock = threading.RLock()
        self._last_requested: Dict[str, float] = {}

    @staticmethod
    def _make_key(topic: str, provider: Optional[str] = None) -> str:
        if provider:
            return f"{topic.lower().strip()}::{provider.lower().strip()}"
        return topic.lower().strip()

    def should_suppress(
        self,
        topic: str,
        provider: Optional[str] = None,
        cooldown_seconds: Optional[float] = None,
        now: Optional[float] = None,
    ) -> bool:
        """Checks whether a request for this topic/provider arrived within the cooldown window."""
        current_time = now if now is not None else time.time()
        cd = cooldown_seconds if cooldown_seconds is not None else self.default_cooldown
        key = self._make_key(topic, provider)

        with self._lock:
            last_time = self._last_requested.get(key, 0.0)
            if (current_time - last_time) < cd:
                return True
            return False

    def get_remaining_cooldown(
        self,
        topic: str,
        provider: Optional[str] = None,
        cooldown_seconds: Optional[float] = None,
        now: Optional[float] = None,
    ) -> float:
        """Returns remaining cooldown time in seconds (0.0 if expired)."""
        current_time = now if now is not None else time.time()
        cd = cooldown_seconds if cooldown_seconds is not None else self.default_cooldown
        key = self._make_key(topic, provider)

        with self._lock:
            last_time = self._last_requested.get(key, 0.0)
            elapsed = current_time - last_time
            if elapsed < cd:
                return cd - elapsed
            return 0.0

    def record_request(self, topic: str, provider: Optional[str] = None, now: Optional[float] = None) -> None:
        """Records timestamp of a processed request for this topic/provider."""
        current_time = now if now is not None else time.time()
        key = self._make_key(topic, provider)
        with self._lock:
            self._last_requested[key] = current_time

    def reset(self) -> None:
        """Clears all cooldown tracking."""
        with self._lock:
            self._last_requested.clear()
