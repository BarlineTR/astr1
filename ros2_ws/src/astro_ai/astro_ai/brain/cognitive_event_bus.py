"""ASTRO V1 — Cognitive Event Bus and Novelty Detection Engine.

Provides a thread-safe, bounded in-memory event bus that:
  - Ingests semantic events from perception and subsystem transitions
  - Automatically assesses base event salience
  - Tracks event novelty across temporal interaction windows
  - Serves unprocessed events to the Cognitive Loop without blocking
"""

from __future__ import annotations

from collections import deque
import threading
import time
from typing import Any, Dict, List, Optional, Set

from astro_ai.contracts.consciousness_types import CognitiveEvent, CognitiveEventType


# Base default salience mappings
DEFAULT_SALIENCE_MAP: Dict[CognitiveEventType, float] = {
    # Safety and critical anomalies (Highest priority)
    CognitiveEventType.SENSOR_LOST: 0.95,
    CognitiveEventType.CAPABILITY_DEGRADED: 0.90,
    CognitiveEventType.GOAL_CONFLICT: 0.85,
    CognitiveEventType.PREDICTION_ERROR: 0.80,
    CognitiveEventType.ACTION_FAILED: 0.80,
    
    # Social perception transitions
    CognitiveEventType.PERSON_APPEARED: 0.75,
    CognitiveEventType.PERSON_RETURNED: 0.85,
    CognitiveEventType.PERSON_SPOKE: 0.80,
    CognitiveEventType.PERSON_RECOGNIZED: 0.70,
    CognitiveEventType.PERSON_DISAPPEARED: 0.60,
    
    # Robot actions and feedback
    CognitiveEventType.ROBOT_INTERRUPTED: 0.85,
    CognitiveEventType.ROBOT_STARTED_SPEAKING: 0.40,
    CognitiveEventType.ROBOT_FINISHED_SPEAKING: 0.40,
    CognitiveEventType.ACTION_STARTED: 0.40,
    CognitiveEventType.ACTION_SUCCEEDED: 0.50,
    CognitiveEventType.PREDICTION_CONFIRMED: 0.45,
    CognitiveEventType.PREDICTION_EXPIRED: 0.65,
    
    # Cognitive and internal states
    CognitiveEventType.NOVELTY_DETECTED: 0.85,
    CognitiveEventType.REASONING_REQUESTED: 0.75,
    CognitiveEventType.GOAL_CREATED: 0.50,
    CognitiveEventType.GOAL_COMPLETED: 0.55,
    CognitiveEventType.GOAL_FAILED: 0.75,
    CognitiveEventType.ATTENTION_SHIFTED: 0.45,
    CognitiveEventType.TARGET_CHANGED: 0.50,
    CognitiveEventType.OPERATIONAL_STATE_CHANGED: 0.30,
    CognitiveEventType.SOCIAL_PHASE_CHANGED: 0.40,
    CognitiveEventType.SENSOR_RECOVERED: 0.60,
}


class CognitiveEventBus:
    """Thread-safe, bounded event bus for cognitive events."""

    def __init__(self, max_capacity: int = 250):
        self._lock = threading.RLock()
        self._max_capacity = max(50, max_capacity)
        self._events: deque[CognitiveEvent] = deque(maxlen=self._max_capacity)
        self._seen_signatures: deque[str] = deque(maxlen=1000)
        self._seen_signatures_set: Set[str] = set()

    def publish(self, event: CognitiveEvent) -> CognitiveEvent:
        """Publishes a CognitiveEvent into the bus with salience and novelty evaluation."""
        with self._lock:
            # Auto-assign salience if default 0.5 and type has explicit baseline
            if event.salience == 0.5 and event.event_type in DEFAULT_SALIENCE_MAP:
                event.salience = DEFAULT_SALIENCE_MAP[event.event_type]

            # Novelty detection if not explicitly set
            if not event.is_novel:
                sig = self._derive_signature(event)
                if sig not in self._seen_signatures_set:
                    event.is_novel = True
                    event.salience = min(1.0, event.salience + 0.15)
                    self._record_signature(sig)
                else:
                    event.is_novel = False

            self._events.append(event)
            return event

    def create_and_publish(
        self,
        event_type: CognitiveEventType,
        source: str,
        data: Optional[Dict[str, Any]] = None,
        salience: Optional[float] = None,
        is_novel: bool = False,
    ) -> CognitiveEvent:
        """Convenience factory to create and publish a new event."""
        assigned_salience = (
            salience
            if salience is not None
            else DEFAULT_SALIENCE_MAP.get(event_type, 0.5)
        )
        event = CognitiveEvent(
            event_type=event_type,
            source=source,
            timestamp=time.time(),
            data=data or {},
            salience=assigned_salience,
            is_novel=is_novel,
            processed=False,
        )
        return self.publish(event)

    def get_unprocessed_events(self) -> List[CognitiveEvent]:
        """Returns all currently unprocessed events in chronological order."""
        with self._lock:
            return [e for e in self._events if not e.processed]

    def mark_processed(self, event_ids: List[str]) -> int:
        """Marks events matching the provided IDs as processed."""
        if not event_ids:
            return 0
        id_set = set(event_ids)
        count = 0
        with self._lock:
            for e in self._events:
                if e.event_id in id_set and not e.processed:
                    e.processed = True
                    count += 1
        return count

    def drain_events(self) -> List[CognitiveEvent]:
        """Marks all unprocessed events as processed and returns them."""
        with self._lock:
            unprocessed = [e for e in self._events if not e.processed]
            for e in unprocessed:
                e.processed = True
            return unprocessed

    def get_recent_events(self, limit: int = 10) -> List[CognitiveEvent]:
        """Returns the most recent N events (newest first)."""
        with self._lock:
            events_list = list(self._events)
            events_list.reverse()
            return events_list[:limit]

    def clear(self) -> None:
        """Clears all events and novelty cache."""
        with self._lock:
            self._events.clear()
            self._seen_signatures.clear()
            self._seen_signatures_set.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def _derive_signature(self, event: CognitiveEvent) -> str:
        """Derives a semantic novelty signature for deduplication and novelty detection."""
        key_data = ""
        if "person_id" in event.data:
            key_data = f":person={event.data['person_id']}"
        elif "target_id" in event.data:
            key_data = f":target={event.data['target_id']}"
        elif "action_id" in event.data:
            key_data = f":action={event.data['action_id']}"
        elif "name" in event.data:
            key_data = f":name={event.data['name']}"

        return f"{event.event_type.value}:{event.source}{key_data}"

    def _record_signature(self, sig: str) -> None:
        if len(self._seen_signatures) >= self._seen_signatures.maxlen:
            oldest = self._seen_signatures.popleft()
            self._seen_signatures_set.discard(oldest)
        self._seen_signatures.append(sig)
        self._seen_signatures_set.add(sig)
