"""ASTRO V1 — Cognitive Continuity & Bounded Introspective Transition Tracking.

Maintains a strictly bounded ring buffer of recent cognitive state transitions,
such as goal changes, prediction results, focus shifts, and confidence deltas.

ARCHITECTURAL INVARIANTS:
  1. STRICTLY BOUNDED: Maximum capacity enforced by collections.deque(maxlen=N).
  2. NO UNBOUNDED GROWTH: Oldest transitions are automatically evicted in O(1) time.
  3. INTROSPECTABLE: Provides machine-readable queries for 'why' and 'what changed'.
"""

from __future__ import annotations

from collections import deque
import logging
import threading
import time
from typing import Any, Dict, List, Optional
import uuid

from astro_ai.contracts.consciousness_types import CognitiveTransition

_LOG = logging.getLogger(__name__)

DEFAULT_MAX_HISTORY: int = 50


class CognitiveContinuityTracker:
    """Thread-safe, bounded ring-buffer tracking recent cognitive transitions."""

    def __init__(self, max_history: int = DEFAULT_MAX_HISTORY):
        self._lock = threading.RLock()
        self._max_history = max(5, int(max_history))
        self._history: deque[CognitiveTransition] = deque(maxlen=self._max_history)

    @property
    def max_history(self) -> int:
        return self._max_history

    def record_transition(
        self,
        transition_type: str,
        previous_value: Any,
        new_value: Any,
        cause: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> CognitiveTransition:
        """Records a new cognitive state transition into the bounded ring-buffer.

        Args:
            transition_type: Semantic category (e.g. 'GOAL_CHANGE', 'CONFIDENCE_CHANGE').
            previous_value: Machine-readable prior value.
            new_value: Machine-readable new value.
            cause: Machine-readable reason or trigger for the change.
            metadata: Optional dictionary of contextual attributes.
            timestamp: Optional explicit timestamp (defaults to current time).

        Returns:
            The newly created and recorded CognitiveTransition instance.
        """
        with self._lock:
            ts = time.time() if timestamp is None else timestamp
            trans_id = f"trans_{uuid.uuid4().hex[:10]}"
            transition = CognitiveTransition(
                transition_id=trans_id,
                timestamp=ts,
                transition_type=str(transition_type),
                previous_value=previous_value,
                new_value=new_value,
                cause=str(cause),
                metadata=dict(metadata or {}),
            )
            self._history.append(transition)
            return transition

    def get_recent_transitions(self, limit: int = 10) -> List[CognitiveTransition]:
        """Returns the most recent transitions up to limit, ordered chronologically."""
        with self._lock:
            if not self._history:
                return []
            lim = max(1, min(len(self._history), int(limit)))
            return list(self._history)[-lim:]

    def get_transitions_by_type(self, transition_type: str) -> List[CognitiveTransition]:
        """Returns all stored transitions matching the specified type."""
        with self._lock:
            return [t for t in self._history if t.transition_type == transition_type]

    def get_last_transition(self) -> Optional[CognitiveTransition]:
        """Returns the most recently recorded transition, or None if history is empty."""
        with self._lock:
            return self._history[-1] if self._history else None

    def get_history_len(self) -> int:
        """Returns current number of transitions stored."""
        with self._lock:
            return len(self._history)

    def clear(self) -> None:
        """Clears all stored transitions."""
        with self._lock:
            self._history.clear()

    def to_list(self) -> List[Dict[str, Any]]:
        """Returns all transitions serialized as dictionaries."""
        with self._lock:
            return [t.to_dict() for t in self._history]
