"""ASTRO V1 — Semantic Perception Event Detector.

Translates raw and operational sensory streams (Vision, Audio, LiDAR, Social FSM, Gaze)
into discrete, transition-based CognitiveEvents without event storms.

Key Behavioral Invariants:
  - Transition-based: False -> True generates an event; True -> True produces ZERO duplicates.
  - Identity vs. Anonymous: Only reliably identified/known individuals can trigger PERSON_RETURNED.
    Anonymous guests ("Misafir") strictly trigger PERSON_APPEARED upon every appearance.
  - Sensor Health Watchdog: Detects stale sensory streams (SENSOR_LOST) and re-acquisitions (SENSOR_RECOVERED).
  - Anti-Storm Rate Limiting: Identical consecutive states emit 0 redundant events.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from astro_ai.contracts.consciousness_types import CognitiveEvent, CognitiveEventType
from astro_ai.contracts.intent_emotion_types import ConversationPhase
from astro_ai.contracts.person_state import UnifiedPersonState


ANONYMOUS_NAMES = {"misafir", "unknown", "guest", "none", ""}


class PerceptionEventDetector:
    """Evaluates multi-modal sensory transitions and emits typed semantic CognitiveEvents."""

    def __init__(
        self,
        person_timeout_s: float = 3.0,
        return_window_s: float = 300.0,
        sensor_timeouts: Optional[Dict[str, float]] = None,
    ):
        self._lock = threading.RLock()

        self.person_timeout_s = person_timeout_s
        self.return_window_s = return_window_s
        self.sensor_timeouts: Dict[str, float] = sensor_timeouts or {
            "camera": 3.0,
            "lidar": 2.5,
            "audio": 5.0,
            "head": 2.5,
        }

        # Person tracking state
        self._present_person_ids: Set[str] = set()
        self._person_identities: Dict[str, Dict[str, Any]] = {}  # pid -> {name, is_known}
        self._known_person_departures: Dict[str, float] = {}    # normalized_name -> departure_ts

        # Speech and Audio states
        self._user_speaking_state: bool = False
        self._robot_speaking_state: bool = False

        # Social and Gaze states
        self._current_social_phase: Optional[str] = None
        self._current_target_id: Optional[str] = None

        # Sensor health watchdog tracking
        self._sensor_last_seen: Dict[str, float] = {}
        self._sensor_lost_status: Dict[str, bool] = {s: False for s in self.sensor_timeouts}

    def detect_transitions(
        self,
        perception: Dict[str, Any],
        timestamp: Optional[float] = None,
    ) -> List[CognitiveEvent]:
        """Evaluates perception delta against internal state and emits transition events."""
        now = timestamp if timestamp is not None else time.time()
        events: List[CognitiveEvent] = []

        with self._lock:
            # -----------------------------------------------------------------
            # 1. SENSOR HEALTH & WATCHDOG (Stale / Recovery)
            # -----------------------------------------------------------------
            if "sensor_activity" in perception and isinstance(perception["sensor_activity"], dict):
                for sensor_name, act_ts in perception["sensor_activity"].items():
                    if sensor_name in self.sensor_timeouts:
                        self._sensor_last_seen[sensor_name] = act_ts

            # Evaluate sensor staleness
            for sensor_name, timeout_s in self.sensor_timeouts.items():
                last_seen = self._sensor_last_seen.get(sensor_name, None)
                if last_seen is not None:
                    silence = now - last_seen
                    if silence > timeout_s:
                        if not self._sensor_lost_status.get(sensor_name, False):
                            self._sensor_lost_status[sensor_name] = True
                            events.append(
                                CognitiveEvent(
                                    event_type=CognitiveEventType.SENSOR_LOST,
                                    source=f"{sensor_name}_watchdog",
                                    timestamp=now,
                                    data={"sensor": sensor_name, "silence_s": round(silence, 2)},
                                    salience=0.95,
                                )
                            )
                    else:
                        if self._sensor_lost_status.get(sensor_name, False):
                            self._sensor_lost_status[sensor_name] = False
                            events.append(
                                CognitiveEvent(
                                    event_type=CognitiveEventType.SENSOR_RECOVERED,
                                    source=f"{sensor_name}_watchdog",
                                    timestamp=now,
                                    data={"sensor": sensor_name},
                                    salience=0.60,
                                )
                            )

            # -----------------------------------------------------------------
            # 2. PERSON PRESENCE, RETURN, & RECOGNITION
            # -----------------------------------------------------------------
            raw_people = perception.get("people", None)
            if raw_people is not None and isinstance(raw_people, list):
                incoming_present_ids: Set[str] = set()

                for p in raw_people:
                    pid = getattr(p, "person_id", None) or p.get("person_id")
                    if not pid:
                        continue

                    is_present = getattr(p, "is_present", True) if hasattr(p, "is_present") else p.get("is_present", True)
                    if hasattr(p, "is_present") and not is_present:
                        p.is_present = True
                        is_present = True
                    if not is_present:
                        continue

                    incoming_present_ids.add(pid)
                    name = (getattr(p, "name", "Misafir") if hasattr(p, "name") else p.get("name", "Misafir")).strip()
                    is_known = bool(getattr(p, "is_known", False) if hasattr(p, "is_known") else p.get("is_known", False))
                    norm_name = name.lower()
                    is_truly_known = is_known and (norm_name not in ANONYMOUS_NAMES)

                    # Check if this is a newly appearing person
                    if pid not in self._present_person_ids:
                        is_returned = False
                        departure_ts = self._known_person_departures.get(norm_name, None)

                        # PERSON_RETURNED: Strictly only for known, non-anonymous individuals
                        if is_truly_known and departure_ts is not None:
                            elapsed = now - departure_ts
                            if elapsed <= self.return_window_s:
                                is_returned = True
                                del self._known_person_departures[norm_name]
                                events.append(
                                    CognitiveEvent(
                                        event_type=CognitiveEventType.PERSON_RETURNED,
                                        source="vision_presence",
                                        timestamp=now,
                                        data={
                                            "person_id": pid,
                                            "name": name,
                                            "is_known": True,
                                            "away_duration_s": round(elapsed, 2),
                                        },
                                        salience=0.85,
                                    )
                                )

                        if not is_returned:
                            # Standard appearance
                            events.append(
                                CognitiveEvent(
                                    event_type=CognitiveEventType.PERSON_APPEARED,
                                    source="vision_presence",
                                    timestamp=now,
                                    data={"person_id": pid, "name": name, "is_known": is_known},
                                    salience=0.75,
                                )
                            )

                        self._present_person_ids.add(pid)
                        self._person_identities[pid] = {"name": name, "is_known": is_known}

                    else:
                        # Existing person: Check for mid-interaction recognition transition
                        prev_identity = self._person_identities.get(pid, {})
                        was_known = prev_identity.get("is_known", False)
                        if is_known and not was_known:
                            self._person_identities[pid] = {"name": name, "is_known": True}
                            events.append(
                                CognitiveEvent(
                                    event_type=CognitiveEventType.PERSON_RECOGNIZED,
                                    source="face_recognizer",
                                    timestamp=now,
                                    data={"person_id": pid, "name": name, "formal_title": getattr(p, "formal_title", name)},
                                    salience=0.70,
                                )
                            )

                # Check for departures
                departed_pids = self._present_person_ids - incoming_present_ids
                for d_pid in departed_pids:
                    ident = self._person_identities.get(d_pid, {})
                    d_name = ident.get("name", "Misafir")
                    d_is_known = ident.get("is_known", False)
                    norm_d_name = d_name.lower()

                    if d_is_known and norm_d_name not in ANONYMOUS_NAMES:
                        self._known_person_departures[norm_d_name] = now

                    events.append(
                        CognitiveEvent(
                            event_type=CognitiveEventType.PERSON_DISAPPEARED,
                            source="vision_presence",
                            timestamp=now,
                            data={"person_id": d_pid, "name": d_name},
                            salience=0.60,
                        )
                    )
                    self._present_person_ids.discard(d_pid)
                    self._person_identities.pop(d_pid, None)

            elif "person_detected" in perception:
                # Binary person detection fallback (e.g. from /vision/person_detected topic)
                val = bool(perception["person_detected"])
                had_someone = len(self._present_person_ids) > 0
                if val and not had_someone:
                    self._present_person_ids.add("anon_person")
                    self._person_identities["anon_person"] = {"name": "Misafir", "is_known": False}
                    events.append(
                        CognitiveEvent(
                            event_type=CognitiveEventType.PERSON_APPEARED,
                            source="vision_person_detected",
                            timestamp=now,
                            data={"person_id": "anon_person", "name": "Misafir", "is_known": False},
                            salience=0.75,
                        )
                    )
                elif not val and had_someone:
                    self._present_person_ids.clear()
                    self._person_identities.clear()
                    events.append(
                        CognitiveEvent(
                            event_type=CognitiveEventType.PERSON_DISAPPEARED,
                            source="vision_person_detected",
                            timestamp=now,
                            data={"person_id": "anon_person", "name": "Misafir"},
                            salience=0.60,
                        )
                    )

            # -----------------------------------------------------------------
            # 3. USER SPEECH & VAD TRANSITIONS
            # -----------------------------------------------------------------
            if "vad" in perception or "is_user_speaking" in perception:
                user_speaking = bool(perception.get("vad", perception.get("is_user_speaking", False)))
                if user_speaking and not self._user_speaking_state:
                    self._user_speaking_state = True
                    events.append(
                        CognitiveEvent(
                            event_type=CognitiveEventType.PERSON_SPOKE,
                            source="audio_vad",
                            timestamp=now,
                            data={
                                "doa_deg": perception.get("doa_deg", 0.0),
                                "text": perception.get("speech_text", ""),
                            },
                            salience=0.80,
                        )
                    )
                elif not user_speaking and self._user_speaking_state:
                    self._user_speaking_state = False

            # -----------------------------------------------------------------
            # 4. ROBOT SPEAKING STATE TRANSITIONS
            # -----------------------------------------------------------------
            if "tts_speaking" in perception or "is_robot_speaking" in perception:
                robot_speaking = bool(perception.get("tts_speaking", perception.get("is_robot_speaking", False)))
                if robot_speaking and not self._robot_speaking_state:
                    self._robot_speaking_state = True
                    events.append(
                        CognitiveEvent(
                            event_type=CognitiveEventType.ROBOT_STARTED_SPEAKING,
                            source="tts_monitor",
                            timestamp=now,
                            salience=0.40,
                        )
                    )
                elif not robot_speaking and self._robot_speaking_state:
                    self._robot_speaking_state = False
                    events.append(
                        CognitiveEvent(
                            event_type=CognitiveEventType.ROBOT_FINISHED_SPEAKING,
                            source="tts_monitor",
                            timestamp=now,
                            salience=0.40,
                        )
                    )

            # -----------------------------------------------------------------
            # 5. SOCIAL FSM PHASE OBSERVATION
            # -----------------------------------------------------------------
            if "social_phase" in perception:
                phase_raw = perception["social_phase"]
                phase_val = phase_raw.value if hasattr(phase_raw, "value") else str(phase_raw)
                if self._current_social_phase is not None and phase_val != self._current_social_phase:
                    events.append(
                        CognitiveEvent(
                            event_type=CognitiveEventType.SOCIAL_PHASE_CHANGED,
                            source="social_fsm_observer",
                            timestamp=now,
                            data={"old_phase": self._current_social_phase, "new_phase": phase_val},
                            salience=0.40,
                        )
                    )
                self._current_social_phase = phase_val

            # -----------------------------------------------------------------
            # 6. GAZE TARGET OBSERVATION
            # -----------------------------------------------------------------
            if "active_target_id" in perception:
                new_target = perception["active_target_id"]
                if self._current_target_id is not None and new_target != self._current_target_id:
                    events.append(
                        CognitiveEvent(
                            event_type=CognitiveEventType.TARGET_CHANGED,
                            source="gaze_target_observer",
                            timestamp=now,
                            data={"old_target_id": self._current_target_id, "new_target_id": new_target},
                            salience=0.50,
                        )
                    )
                self._current_target_id = new_target

        return events

    def notify_sensor_active(self, sensor_name: str, timestamp: Optional[float] = None) -> None:
        """Explicit hook called by ROS2 topic callbacks to update sensor freshness."""
        with self._lock:
            self._sensor_last_seen[sensor_name] = timestamp if timestamp is not None else time.time()

    def reset(self) -> None:
        """Resets all tracked transition and presence states."""
        with self._lock:
            self._present_person_ids.clear()
            self._person_identities.clear()
            self._known_person_departures.clear()
            self._user_speaking_state = False
            self._robot_speaking_state = False
            self._current_social_phase = None
            self._current_target_id = None
            self._sensor_last_seen.clear()
            self._sensor_lost_status = {s: False for s in self.sensor_timeouts}
