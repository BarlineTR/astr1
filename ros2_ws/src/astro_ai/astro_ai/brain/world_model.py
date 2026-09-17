"""ASTRO V1 — Dynamic World Model.

Maintains the authoritative real-time representation of the environment,
active people, spatial objects, conversational context, and recent events.
"""

from collections import deque
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from astro_ai.contracts.person_state import EntityLifecycleState, UnifiedPersonState
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
    conflicts: List[Dict[str, Any]] = field(default_factory=list)


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
        self.focus_target: Optional[str] = None

    def update_people(self, people_list: List[UnifiedPersonState], now: Optional[float] = None):
        """Synchronizes tracked people with the world state, managing entity lifecycle and trajectory."""
        with self._lock:
            t_now = now or time.time()
            current_ids = set()

            # If any incoming person is an identified known user, purge placeholder anonymous records
            for p in people_list:
                if getattr(p, "is_known", False) and str(p.person_id).lower() not in ("misafir", "guest"):
                    for anon_id in ["misafir", "guest", "audio_speaker_1"]:
                        if anon_id in self._people and anon_id != p.person_id:
                            # Inherit trajectory history if target didn't have one
                            if not getattr(p, "trajectory_history", None):
                                p.trajectory_history = getattr(self._people[anon_id], "trajectory_history", [])
                            del self._people[anon_id]

            for p in people_list:
                p.last_seen_ts = t_now
                prev = self._people.get(p.person_id)
                if prev is not None and not prev.is_present:
                    # Entity reappeared after occlusion
                    p.tracking_state = EntityLifecycleState.REAPPEARED
                    p.occlusion_duration_s = 0.0
                elif prev is None:
                    # Entity just appeared
                    p.tracking_state = EntityLifecycleState.APPEARED
                    p.occlusion_duration_s = 0.0

                # Append to bounded trajectory history
                prev_hist = list(getattr(prev, "trajectory_history", [])) if prev else []
                new_hist = list(prev_hist)
                new_hist.append({
                    "x": p.x_m,
                    "y": p.y_m,
                    "dist": p.distance_m,
                    "azimuth": p.azimuth_deg,
                    "ts": t_now,
                })
                if len(new_hist) > 10:
                    new_hist = new_hist[-10:]
                p.trajectory_history = new_hist

                p.is_present = True
                self._people[p.person_id] = p
                current_ids.add(p.person_id)

            # Mark missing people as occluded or prune if stale > 5.0s
            for pid, p in list(self._people.items()):
                if pid not in current_ids:
                    dt = t_now - p.last_seen_ts
                    if dt > 5.0:
                        del self._people[pid]
                    else:
                        p.is_present = False
                        p.tracking_state = EntityLifecycleState.OCCLUDED
                        p.occlusion_duration_s = round(dt, 2)

            # Determine active speaker
            active_speakers = [p for p in self._people.values() if p.is_speaking and p.is_present]
            self._active_speaker = active_speakers[0] if active_speakers else None

    def get_person(self, person_id: str) -> Optional[UnifiedPersonState]:
        """Retrieves a tracked person by ID."""
        with self._lock:
            return self._people.get(person_id)

    def update_robot_state(self, **kwargs):
        with self._lock:
            self._robot_state.update(kwargs)

    def update_environment(self, **kwargs):
        with self._lock:
            self._environment.update(kwargs)

    def update_conversation_state(self, **kwargs):
        with self._lock:
            self._conversation_state.update(kwargs)

    # -------------------------------------------------------------------------
    # Spatial Objects & Real Visual Perception Extensions (Phase 1 & 4)
    # -------------------------------------------------------------------------

    def update_spatial_object(self, obj: SpatialObjectState, now: Optional[float] = None) -> None:
        """Updates or registers a tracked spatial object."""
        with self._lock:
            key = obj.object_id or f"{obj.class_name or obj.category}_{len(self._spatial_objects)}"
            if now is not None:
                obj.last_observed_ts = now
            elif getattr(obj, "last_observed_ts", 0.0) <= 0.0:
                obj.last_observed_ts = time.time()
            self._spatial_objects[key] = obj

    def update_spatial_objects(self, objects: List[SpatialObjectState], now: Optional[float] = None) -> None:
        """Batch updates tracked spatial objects and refreshes their freshness state."""
        with self._lock:
            t = now if now is not None else time.time()
            for obj in objects:
                key = obj.object_id or f"{obj.class_name or obj.category}_{len(self._spatial_objects)}"
                if now is not None:
                    obj.last_observed_ts = now
                elif getattr(obj, "last_observed_ts", 0.0) <= 0.0:
                    obj.last_observed_ts = t
                obj.freshness = "FRESH"
                self._spatial_objects[key] = obj

    def remove_stale_spatial_objects(self, ttl_s: float = 15.0, now: Optional[float] = None) -> int:
        """Prunes expired spatial objects whose last observation age exceeds ttl_s."""
        with self._lock:
            t = now if now is not None else time.time()
            stale_keys = [
                k for k, obj in self._spatial_objects.items()
                if (t - obj.last_observed_ts) > ttl_s
            ]
            for k in stale_keys:
                del self._spatial_objects[k]
            return len(stale_keys)

    def get_spatial_objects(
        self,
        max_age_s: float = 2.5,
        min_confidence: float = 0.50,
        now: Optional[float] = None,
    ) -> List[SpatialObjectState]:
        """Returns currently fresh, high-confidence spatial objects."""
        with self._lock:
            t = now if now is not None else time.time()
            valid = []
            for obj in self._spatial_objects.values():
                age = t - obj.last_observed_ts
                if age <= max_age_s and obj.confidence >= min_confidence:
                    obj.freshness = "FRESH"
                    valid.append(obj)
                elif age <= 10.0:
                    obj.freshness = "STALE"
                else:
                    obj.freshness = "EXPIRED"
            return valid

    def get_recent_spatial_objects(
        self,
        max_age_s: float = 10.0,
        min_confidence: float = 0.50,
        now: Optional[float] = None,
    ) -> List[SpatialObjectState]:
        """Returns spatial objects observed recently (within max_age_s)."""
        with self._lock:
            t = now if now is not None else time.time()
            valid = []
            for obj in self._spatial_objects.values():
                age = t - obj.last_observed_ts
                if age <= max_age_s and obj.confidence >= min_confidence:
                    obj.freshness = "FRESH" if age <= 2.5 else "STALE"
                    valid.append(obj)
            return valid

    def update_person_activity(
        self,
        person_id: str,
        activity: str,
        confidence: float,
        evidence: Optional[List[str]] = None,
        now: Optional[float] = None,
    ) -> bool:
        """Updates the verified physical activity of a tracked person."""
        with self._lock:
            person = self._people.get(person_id)
            if person is None:
                return False
            t = now if now is not None else time.time()
            setattr(person, "current_activity", activity)
            setattr(person, "activity_confidence", confidence)
            setattr(person, "last_activity_ts", t)
            if evidence is not None:
                setattr(person, "activity_evidence", list(evidence))
            return True

    def update_person_visual_attributes(
        self,
        person_id: str,
        attributes: Dict[str, Any],
    ) -> bool:
        """Updates measured visual attributes (clothing color, accessory, smile) of a tracked person."""
        with self._lock:
            person = self._people.get(person_id)
            if person is None:
                return False
            raw = getattr(person, "raw_attributes", {}) or {}
            raw.update(attributes)
            person.raw_attributes = raw
            for k, v in attributes.items():
                if hasattr(person, k):
                    setattr(person, k, v)
            return True

    def record_event(self, event_description: str):
        with self._lock:
            now = time.time()
            self._recent_events.append((now, event_description))
            if len(self._recent_events) > 20:
                self._recent_events = self._recent_events[-20:]

    def detect_conflicts(self) -> List[Dict[str, Any]]:
        """Detects cross-modal sensor contradictions in the current world state."""
        with self._lock:
            conflicts: List[Dict[str, Any]] = []
            people_list = list(self._people.values())
            visual_people = [p for p in people_list if p.is_present and getattr(p, "has_vision", False)]
            acoustic_entities = [p for p in people_list if p.is_present and getattr(p, "entity_type", "") == "ACOUSTIC_ENTITY"]

            # Conflict 1: Spatial Attention Split (Face seen in one direction, active speech from another)
            if visual_people and acoustic_entities:
                for vp in visual_people:
                    for ae in acoustic_entities:
                        adiff = abs((vp.azimuth_deg - ae.azimuth_deg + 180.0) % 360.0 - 180.0)
                        if adiff > 35.0:
                            conflicts.append({
                                "type": "SPATIAL_ATTENTION_SPLIT",
                                "visual_entity": vp.person_id,
                                "visual_azimuth": vp.azimuth_deg,
                                "acoustic_entity": ae.person_id,
                                "acoustic_azimuth": ae.azimuth_deg,
                                "angle_divergence_deg": round(adiff, 1),
                            })

            # Conflict 2: Front Clearance vs In-view Person Distance Mismatch
            front_clearance = self._environment.get("front_clearance_m", 5.0)
            if front_clearance < 0.8:
                for vp in visual_people:
                    if abs(vp.azimuth_deg) < 25.0 and vp.distance_m > 1.8:
                        conflicts.append({
                            "type": "OBSTACLE_OCCLUSION_MISMATCH",
                            "front_clearance_m": front_clearance,
                            "person_distance_m": vp.distance_m,
                        })

            return conflicts

    def get_acoustic_attention_candidate(self) -> Optional[Dict[str, Any]]:
        """Returns the most salient unverified acoustic stimulus requiring visual confirmation."""
        with self._lock:
            candidates = [
                p for p in self._people.values()
                if p.is_present and getattr(p, "has_audio", False) and not getattr(p, "has_vision", False)
            ]
            if not candidates:
                return None
            c = max(candidates, key=lambda p: (getattr(p, "voice_match_confidence", 0.0) or 0.5))
            return {
                "entity_id": c.person_id,
                "target_yaw_deg": c.azimuth_deg,
                "distance_m": c.distance_m,
                "confidence": c.identity_confidence,
                "ts": c.last_spoken_ts or c.last_seen_ts,
            }

    def get_self_model_world_summary(self) -> Dict[str, Any]:
        """Provides minimal, strictly filtered world summary for SelfModel boundary."""
        with self._lock:
            speaker_yaw = self._active_speaker.azimuth_deg if self._active_speaker else None
            return {
                "focused_person_id": self._active_speaker.person_id if self._active_speaker else (
                    min(self._people.values(), key=lambda p: p.distance_m).person_id if self._people else None
                ),
                "front_clearance_m": self._environment.get("front_clearance_m", 5.0),
                "is_obstacle_near": self._environment.get("is_obstacle_near", False),
                "ambient_rms": self._environment.get("ambient_rms", 100.0),
                "people_count": len([p for p in self._people.values() if p.is_present]),
                "has_active_speaker": self._active_speaker is not None,
                "relative_speaker_bearing_deg": speaker_yaw,
            }

    def get_snapshot(self, now: Optional[float] = None) -> WorldStateSnapshot:
        """Returns a consistent immutable snapshot of current world state."""
        with self._lock:
            t = now if now is not None else time.time()
            people_copy = list(self._people.values())
            events_formatted = [
                f"[{time.strftime('%H:%M:%S', time.localtime(ts))}] {desc}"
                for ts, desc in self._recent_events[-5:]
            ]
            active_conflicts = self.detect_conflicts()

            return WorldStateSnapshot(
                timestamp=t,
                people=people_copy,
                active_speaker=self._active_speaker,
                spatial_objects=self.get_spatial_objects(max_age_s=5.0, now=t),
                robot_state=dict(self._robot_state),
                environment=dict(self._environment),
                conversation_state=dict(self._conversation_state),
                recent_events=events_formatted,
                conflicts=active_conflicts,
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

