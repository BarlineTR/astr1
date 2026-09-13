"""ASTRO V1 — Dynamic World Model.

Maintains the authoritative real-time representation of the environment,
active people, spatial objects, conversational context, and recent events.
"""

from collections import deque
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.spatial_state import SpatialObjectState


@dataclass
class WorldStateSnapshot:
    """Immutable snapshot of the world at a specific instant."""

    timestamp: float
    people: List[UnifiedPersonState]
    active_speaker: Optional[UnifiedPersonState]
    spatial_objects: List[SpatialObjectState]
    robot_state: Dict[str, Any]
    environment: Dict[str, Any]
    conversation_state: Dict[str, Any]
    recent_events: List[str]


class WorldModel:
    """Thread-safe dynamic world model coordinating all sensory and situational state."""

    def __init__(self, temporal_history_size: int = 50):
        self._lock = threading.RLock()
        self._temporal_history_size = max(10, temporal_history_size)
        self._temporal_history: deque[WorldStateSnapshot] = deque(maxlen=self._temporal_history_size)

        self._people: Dict[str, UnifiedPersonState] = {}
        self._active_speaker: Optional[UnifiedPersonState] = None
        self._spatial_objects: Dict[str, SpatialObjectState] = {}

        self._robot_state: Dict[str, Any] = {
            "execution_state": "IDLE",
            "social_phase": "UNATTENDED",
            "is_sleeping": False,
            "head_yaw_deg": 0.0,
            "head_pitch_deg": 0.0,
            "active_persona": "playful",
            "battery_pct": 100.0,
        }

        self._environment: Dict[str, Any] = {
            "ambient_rms": 100.0,
            "location_name": "Bitlis / Ahlat Robotik Ar-Ge Alanı",
            "is_obstacle_near": False,
            "front_clearance_m": 5.0,
        }

        self._conversation_state: Dict[str, Any] = {
            "is_session_active": False,
            "active_topic": None,
            "recent_topics": [],
            "silence_duration_s": 0.0,
            "turn_count": 0,
            "last_interaction_ts": 0.0,
        }

        self._recent_events: List[Tuple[float, str]] = []  # (ts, desc)

    def update_people(self, people_list: List[UnifiedPersonState]):
        """Synchronizes tracked people with the world state."""
        with self._lock:
            now = time.time()
            current_ids = set()

            for p in people_list:
                self._people[p.person_id] = p
                current_ids.add(p.person_id)

            # Mark missing people as not present
            for pid, p in list(self._people.items()):
                if pid not in current_ids:
                    if (now - p.last_seen_ts) > 5.0:
                        del self._people[pid]
                    else:
                        p.is_present = False

            # Determine active speaker
            active_speakers = [p for p in self._people.values() if p.is_speaking and p.is_present]
            self._active_speaker = active_speakers[0] if active_speakers else None

    def update_robot_state(self, **kwargs):
        with self._lock:
            self._robot_state.update(kwargs)

    def update_environment(self, **kwargs):
        with self._lock:
            self._environment.update(kwargs)

    def update_conversation_state(self, **kwargs):
        with self._lock:
            self._conversation_state.update(kwargs)

    def record_event(self, event_description: str):
        with self._lock:
            now = time.time()
            self._recent_events.append((now, event_description))
            if len(self._recent_events) > 20:
                self._recent_events = self._recent_events[-20:]

    def get_snapshot(self) -> WorldStateSnapshot:
        """Returns a consistent immutable snapshot of current world state."""
        with self._lock:
            now = time.time()
            people_copy = list(self._people.values())
            events_formatted = [
                f"[{time.strftime('%H:%M:%S', time.localtime(ts))}] {desc}"
                for ts, desc in self._recent_events[-5:]
            ]

            return WorldStateSnapshot(
                timestamp=now,
                people=people_copy,
                active_speaker=self._active_speaker,
                spatial_objects=list(self._spatial_objects.values()),
                robot_state=dict(self._robot_state),
                environment=dict(self._environment),
                conversation_state=dict(self._conversation_state),
                recent_events=events_formatted,
            )

    # -------------------------------------------------------------------------
    # Temporal History & Short-Window Memory Extensions
    # -------------------------------------------------------------------------

    def commit_temporal_snapshot(
        self, snapshot: Optional[WorldStateSnapshot] = None
    ) -> WorldStateSnapshot:
        """Commits an immutable snapshot into the bounded temporal ring buffer."""
        with self._lock:
            snap = snapshot or self.get_snapshot()
            self._temporal_history.append(snap)
            return snap

    def get_temporal_window(
        self, limit: Optional[int] = None
    ) -> List[WorldStateSnapshot]:
        """Returns a read-only list of recent world snapshots in chronological order."""
        with self._lock:
            history_list = list(self._temporal_history)
            if limit is not None and limit > 0:
                return history_list[-limit:]
            return history_list

    def get_latest_temporal_snapshot(self) -> Optional[WorldStateSnapshot]:
        """Returns the most recent committed temporal snapshot, if any."""
        with self._lock:
            if self._temporal_history:
                return self._temporal_history[-1]
            return None

    def clear_temporal_history(self) -> None:
        """Clears the temporal history buffer."""
        with self._lock:
            self._temporal_history.clear()

    @property
    def temporal_history_len(self) -> int:
        """Returns current number of snapshots stored in the temporal ring buffer."""
        with self._lock:
            return len(self._temporal_history)

