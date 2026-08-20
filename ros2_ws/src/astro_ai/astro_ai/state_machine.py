#!/usr/bin/env python3
"""ASTRO V1 — Finite State Machine for Conversational States."""

import enum
import threading
import time
from typing import Callable, Optional


class RobotState(enum.Enum):
    DEEP_IDLE = "DEEP_IDLE"
    WAKE = "WAKE"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    ENROLLING = "ENROLLING"



class StateMachine:
    """Thread-safe state machine managing Astro's conversational states and transitions."""

    def __init__(self, initial_state: RobotState = RobotState.IDLE):
        self._state = initial_state
        self._lock = threading.RLock()
        self._last_transition_time = time.monotonic()
        self._listeners: list[Callable[[RobotState, RobotState], None]] = []

    @property
    def current_state(self) -> RobotState:
        with self._lock:
            return self._state

    @property
    def time_in_current_state(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_transition_time

    def add_listener(self, callback: Callable[[RobotState, RobotState], None]):
        """Adds a callback triggered on state transitions (old_state, new_state)."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[RobotState, RobotState], None]):
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def transition_to(self, new_state: RobotState) -> bool:
        """Transitions to a new state if valid. Returns True if transition occurred."""
        with self._lock:
            old_state = self._state
            if old_state == new_state:
                return False
            self._state = new_state
            self._last_transition_time = time.monotonic()
            # Snapshot listeners under lock, then call them OUTSIDE the lock
            # to prevent deadlocks if any listener blocks on another lock.
            listeners_snapshot = list(self._listeners)

        for listener in listeners_snapshot:
            try:
                listener(old_state, new_state)
            except Exception:
                pass

        return True

    def is_deep_idle(self) -> bool:
        return self.current_state == RobotState.DEEP_IDLE

    def is_wake(self) -> bool:
        return self.current_state == RobotState.WAKE

    def is_idle(self) -> bool:
        return self.current_state == RobotState.IDLE

    def is_listening(self) -> bool:
        return self.current_state == RobotState.LISTENING

    def is_thinking(self) -> bool:
        return self.current_state == RobotState.THINKING

    def is_speaking(self) -> bool:
        return self.current_state == RobotState.SPEAKING

    def is_interrupted(self) -> bool:
        return self.current_state == RobotState.INTERRUPTED
