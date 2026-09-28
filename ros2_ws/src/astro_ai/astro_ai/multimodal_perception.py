#!/usr/bin/env python3
"""ASTRO V1 — Multimodal Perception State & Social Context Engine.

Fuses Radar/LiDAR, ReSpeaker Microphone DOA/VAD, and OAK-D Camera vision into a
unified timestamped state, and derives high-level social contexts:
  - DIRECT_INTERACTION
  - PASSIVE_PRESENCE
  - ROOM_ACTIVE
  - ISOLATED_IDLE
"""

from dataclasses import dataclass, field
from enum import Enum
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple


class SocialContextState(str, Enum):
    DIRECT_INTERACTION = "DIRECT_INTERACTION"
    PASSIVE_PRESENCE = "PASSIVE_PRESENCE"
    ROOM_ACTIVE = "ROOM_ACTIVE"
    ISOLATED_IDLE = "ISOLATED_IDLE"


@dataclass
class LidarPerceptionState:
    nearest_distance_m: float = 0.0
    nearest_angle_deg: float = 0.0
    obstacle_count: int = 0
    motion_detected: bool = False
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class AudioPerceptionState:
    doa_angle_deg: float = 0.0
    voice_activity: bool = False
    speech_detected: bool = False
    speaker_confidence: float = 0.0
    audio_event: bool = False
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class VisualPerceptionState:
    person_detected: bool = False
    person_count: int = 0
    face_distance_m: float = 0.0
    gaze_direction: float = 0.0
    looking_at_robot: bool = False
    emotion: str = "neutral"
    scene_signature: str = ""
    object_candidates: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class MultimodalPerceptionState:
    lidar: LidarPerceptionState = field(default_factory=LidarPerceptionState)
    audio: AudioPerceptionState = field(default_factory=AudioPerceptionState)
    visual: VisualPerceptionState = field(default_factory=VisualPerceptionState)
    social_context: SocialContextState = SocialContextState.ISOLATED_IDLE
    timestamp: float = field(default_factory=time.monotonic)

    def get_snapshot(self) -> Dict[str, Any]:
        """Returns a serializable dictionary snapshot of the unified multimodal state."""
        return {
            "lidar": {
                "nearest_distance_m": round(self.lidar.nearest_distance_m, 2),
                "nearest_angle_deg": round(self.lidar.nearest_angle_deg, 1),
                "obstacle_count": self.lidar.obstacle_count,
                "motion_detected": self.lidar.motion_detected,
                "timestamp": round(self.lidar.timestamp, 3),
            },
            "audio": {
                "doa_angle_deg": round(self.audio.doa_angle_deg, 1),
                "voice_activity": self.audio.voice_activity,
                "speech_detected": self.audio.speech_detected,
                "speaker_confidence": round(self.audio.speaker_confidence, 2),
                "audio_event": self.audio.audio_event,
                "timestamp": round(self.audio.timestamp, 3),
            },
            "visual": {
                "person_detected": self.visual.person_detected,
                "person_count": self.visual.person_count,
                "face_distance_m": round(self.visual.face_distance_m, 2),
                "gaze_direction": round(self.visual.gaze_direction, 1),
                "looking_at_robot": self.visual.looking_at_robot,
                "emotion": self.visual.emotion,
                "scene_signature": self.visual.scene_signature,
                "object_candidates": list(self.visual.object_candidates),
                "timestamp": round(self.visual.timestamp, 3),
            },
            "social_context": self.social_context.value,
            "timestamp": round(self.timestamp, 3),
        }


class SocialContextEngine:
    """Thread-safe engine aggregating multi-sensor streams and classifying social context."""

    def __init__(self):
        self._lock = threading.RLock()
        self._state = MultimodalPerceptionState()
        self._last_snapshot: Optional[Dict[str, Any]] = None

    def update_lidar(
        self,
        nearest_distance_m: float = 0.0,
        nearest_angle_deg: float = 0.0,
        obstacle_count: int = 0,
        motion_detected: bool = False,
    ):
        with self._lock:
            now = time.monotonic()
            self._state.lidar.nearest_distance_m = float(nearest_distance_m)
            self._state.lidar.nearest_angle_deg = float(nearest_angle_deg)
            self._state.lidar.obstacle_count = int(obstacle_count)
            self._state.lidar.motion_detected = bool(motion_detected)
            self._state.lidar.timestamp = now
            self._state.timestamp = now
            self._state.social_context = self._evaluate_context_locked()

    def update_audio(
        self,
        doa_angle_deg: float = 0.0,
        voice_activity: bool = False,
        speech_detected: bool = False,
        speaker_confidence: float = 0.0,
        audio_event: bool = False,
    ):
        with self._lock:
            now = time.monotonic()
            self._state.audio.doa_angle_deg = float(doa_angle_deg)
            self._state.audio.voice_activity = bool(voice_activity)
            self._state.audio.speech_detected = bool(speech_detected)
            self._state.audio.speaker_confidence = float(speaker_confidence)
            self._state.audio.audio_event = bool(audio_event)
            self._state.audio.timestamp = now
            self._state.timestamp = now
            self._state.social_context = self._evaluate_context_locked()

    def update_visual(self, **kwargs):
        """Update visual perception state. Only provided fields are updated; others are preserved."""
        with self._lock:
            now = time.monotonic()
            v = self._state.visual
            if "person_detected" in kwargs:
                v.person_detected = bool(kwargs["person_detected"])
            if "person_count" in kwargs:
                v.person_count = int(kwargs["person_count"])
            if "face_distance_m" in kwargs:
                v.face_distance_m = float(kwargs["face_distance_m"])
            if "gaze_direction" in kwargs:
                v.gaze_direction = float(kwargs["gaze_direction"])
            if "looking_at_robot" in kwargs:
                v.looking_at_robot = bool(kwargs["looking_at_robot"])
            if "emotion" in kwargs:
                v.emotion = str(kwargs["emotion"])
            if "scene_signature" in kwargs and kwargs["scene_signature"]:
                v.scene_signature = str(kwargs["scene_signature"])
            if "object_candidates" in kwargs and kwargs["object_candidates"] is not None:
                v.object_candidates = list(kwargs["object_candidates"])
            v.timestamp = now
            self._state.timestamp = now
            self._state.social_context = self._evaluate_context_locked()

    def get_state(self) -> MultimodalPerceptionState:
        with self._lock:
            return self._state

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self._state.get_snapshot()

    def _evaluate_context_locked(self) -> SocialContextState:
        vis = self._state.visual
        aud = self._state.audio
        lid = self._state.lidar

        # 1. DIRECT_INTERACTION: Person detected + (Looking at robot OR Voice/Speech detected near front)
        if vis.person_detected:
            if vis.looking_at_robot:
                return SocialContextState.DIRECT_INTERACTION
            if aud.voice_activity or aud.speech_detected:
                # If audio direction aligns roughly with face or frontal angle
                if abs(aud.doa_angle_deg - vis.gaze_direction) <= 50.0 or abs(aud.doa_angle_deg) <= 35.0:
                    return SocialContextState.DIRECT_INTERACTION
            return SocialContextState.PASSIVE_PRESENCE

        # 2. PASSIVE_PRESENCE: Person visible or close frontal obstacle but no active conversation
        if vis.person_count > 0:
            return SocialContextState.PASSIVE_PRESENCE

        # 3. ROOM_ACTIVE: Motion detected by LiDAR/Radar or environmental audio event
        if lid.motion_detected or (0.1 < lid.nearest_distance_m < 2.5) or aud.audio_event:
            return SocialContextState.ROOM_ACTIVE

        # 4. ISOLATED_IDLE: No significant sensory events
        return SocialContextState.ISOLATED_IDLE

    def has_perception_change(self, old_snap: Optional[Dict[str, Any]], new_snap: Dict[str, Any]) -> Tuple[bool, str]:
        """Compares two snapshots and determines whether an autonomous idle perception trigger should fire."""
        if not old_snap:
            return True, "initial_cycle"

        # Check visual person change
        if old_snap["visual"]["person_detected"] != new_snap["visual"]["person_detected"]:
            return True, "person_change"

        # Check scene signature change
        if old_snap["visual"]["scene_signature"] != new_snap["visual"]["scene_signature"] and new_snap["visual"]["scene_signature"]:
            return True, "scene_change"

        # Check object candidate count change
        if len(old_snap["visual"]["object_candidates"]) != len(new_snap["visual"]["object_candidates"]):
            return True, "object_change"

        # Check audio event
        if not old_snap["audio"]["audio_event"] and new_snap["audio"]["audio_event"]:
            return True, "audio_event"

        # Check lidar motion change
        if not old_snap["lidar"]["motion_detected"] and new_snap["lidar"]["motion_detected"]:
            return True, "motion_detected"

        # Check social context change
        if old_snap["social_context"] != new_snap["social_context"]:
            return True, "context_transition"

        return False, "no_perception_change"
