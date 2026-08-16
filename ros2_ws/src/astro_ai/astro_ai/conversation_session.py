#!/usr/bin/env python3
"""ASTRO V1 — Adaptive Conversation Session Manager & Latency Tracker.

Features:
  - Adaptive Session Lifecycle: Gaze, voice activity, and dynamic attention
  - Turn-taking detection with pause tolerance
  - Real-Time Timestamp-based Latency Benchmarking (p50 / p95 metrics)
"""

import collections
import re
import threading
import time
from typing import Callable, List, Optional


class LatencyTracker:
    """Tracks end-to-end turn latencies and computes real-time p50 / p95 statistics."""

    def __init__(self, history_size: int = 50):
        self.history_size = history_size
        self._stt_latencies: collections.deque[float] = collections.deque(maxlen=history_size)
        self._llm_first_token_latencies: collections.deque[float] = collections.deque(maxlen=history_size)
        self._total_turn_latencies: collections.deque[float] = collections.deque(maxlen=history_size)
        self._lock = threading.Lock()

    def record_turn(self, stt_ms: float, llm_first_token_ms: float, total_turn_ms: float):
        with self._lock:
            self._stt_latencies.append(stt_ms)
            self._llm_first_token_latencies.append(llm_first_token_ms)
            self._total_turn_latencies.append(total_turn_ms)

    def get_stats(self) -> dict:
        with self._lock:
            if not self._total_turn_latencies:
                return {"p50_total_ms": 0.0, "p95_total_ms": 0.0, "samples": 0}

            totals = sorted(self._total_turn_latencies)
            n = len(totals)
            # Clamp both indexes to valid range to handle small sample sizes correctly
            p50_idx = min(n - 1, int(n * 0.50))
            p95_idx = min(n - 1, int(n * 0.95))

            return {
                "p50_total_ms": round(totals[p50_idx], 1),
                "p95_total_ms": round(totals[p95_idx], 1),
                "samples": n
            }


class ConversationSession:
    """Manages adaptive conversation sessions, wake-word triggering, and turn timeouts."""

    def __init__(
        self,
        base_timeout_s: float = 45.0,
        gaze_extension_s: float = 15.0,
        on_session_start: Optional[Callable[[], None]] = None,
        on_session_end: Optional[Callable[[], None]] = None,
    ):
        self.base_timeout_s = base_timeout_s
        self.gaze_extension_s = gaze_extension_s
        self.on_session_start = on_session_start
        self.on_session_end = on_session_end

        self._is_active: bool = False
        self._last_user_speech_time: float = 0.0
        self._last_robot_speech_time: float = 0.0
        self._last_gaze_time: float = 0.0
        self._is_gaze_active: bool = False
        self._lock = threading.RLock()

        self.latency_tracker = LatencyTracker()

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._is_active

    def activate_session(self, reason: str = "wake_word"):
        with self._lock:
            was_active = self._is_active
            self._is_active = True
            now = time.monotonic()
            self._last_user_speech_time = now
            if not was_active and self.on_session_start:
                try:
                    self.on_session_start()
                except Exception:
                    pass

    def record_user_speech(self):
        with self._lock:
            self._last_user_speech_time = time.monotonic()
            if not self._is_active:
                self.activate_session(reason="speech")

    def record_robot_speech(self):
        with self._lock:
            self._last_robot_speech_time = time.monotonic()

    def update_gaze(self, looking_at_robot: bool):
        with self._lock:
            self._is_gaze_active = looking_at_robot
            if looking_at_robot:
                self._last_gaze_time = time.monotonic()

    def check_and_update_session_lifecycle(self) -> bool:
        """Periodic check to determine if the active session should time out."""
        with self._lock:
            if not self._is_active:
                return False

            now = time.monotonic()
            time_since_user = now - self._last_user_speech_time
            time_since_robot = now - self._last_robot_speech_time

            # Adaptive Timeout: If user is actively looking, extend timeout
            allowed_timeout = self.base_timeout_s
            if self._is_gaze_active or (now - self._last_gaze_time) < 5.0:
                allowed_timeout += self.gaze_extension_s

            if time_since_user > allowed_timeout and time_since_robot > allowed_timeout:
                self._is_active = False
                if self.on_session_end:
                    try:
                        self.on_session_end()
                    except Exception:
                        pass
                return True  # Timed out
            return False

    def is_wake_word(self, text: str, wake_word: str = "hey astro") -> tuple[bool, str]:
        """Detects wake words and returns (has_wake_word, clean_text_without_wake_word)."""
        triggers = [
            wake_word.lower(),
            "hey astro", "astro", "esmer", "hey groq", "grok", "merhaba", "asistan"
        ]
        text_lower = text.lower()
        has_wake = any(w in text_lower for w in triggers)

        clean = text
        if has_wake:
            for w in triggers:
                clean = re.sub(rf"(?i)\b{re.escape(w)}\b", "", clean).strip()
            clean = re.sub(r"\s+", " ", clean).strip(" ,.!?:;")

        return has_wake, clean
