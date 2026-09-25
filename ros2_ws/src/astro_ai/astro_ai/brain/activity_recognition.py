"""ASTRO V1 — Temporal Human Activity Recognition Engine.

Detects sustained human activities (DRINKING, USING_PHONE, USING_COMPUTER,
READING, EATING, SITTING, STANDING, WALKING, WAVING, TALKING) using multi-frame
temporal evidence accumulation, spatial object associations, and gaze/pose cues.
"""

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.spatial_state import SpatialObjectState


class HumanActivity(str, Enum):
    DRINKING = "DRINKING"
    USING_PHONE = "USING_PHONE"
    LOOKING_AT_PHONE = "LOOKING_AT_PHONE"
    USING_COMPUTER = "USING_COMPUTER"
    READING = "READING"
    EATING = "EATING"
    SITTING = "SITTING"
    STANDING = "STANDING"
    WALKING = "WALKING"
    WAVING = "WAVING"
    TALKING = "TALKING"
    INTERACTING_WITH_OBJECT = "INTERACTING_WITH_OBJECT"
    UNKNOWN = "UNKNOWN"


# Natural Turkish descriptions of activities for truthful verbal responses
ACTIVITY_DESCRIPTIONS_TR: Dict[HumanActivity, str] = {
    HumanActivity.DRINKING: "Bardaktan bir şeyler içtiğini görüyorum, afiyet olsun.",
    HumanActivity.USING_PHONE: "Telefonunla ilgilendiğini görüyorum.",
    HumanActivity.LOOKING_AT_PHONE: "Telefonuna baktığını görüyorum.",
    HumanActivity.USING_COMPUTER: "Bilgisayarında çalıştığını görüyorum.",
    HumanActivity.READING: "Kitap okuduğunu görüyorum, iyi okumalar.",
    HumanActivity.EATING: "Bir şeyler atıştırdığını / yemek yediğini görüyorum, afiyet olsun.",
    HumanActivity.SITTING: "Oturduğunu görüyorum.",
    HumanActivity.STANDING: "Ayakta durduğunu görüyorum.",
    HumanActivity.WALKING: "Yürüdüğünü ve hareket halinde olduğunu görüyorum.",
    HumanActivity.WAVING: "Bana el salladığını görüyorum! Merhaba!",
    HumanActivity.TALKING: "Benimle konuştuğunu görüyorum, seni dinliyorum.",
    HumanActivity.INTERACTING_WITH_OBJECT: "Bir nesneyle ilgilendiğini görüyorum.",
    HumanActivity.UNKNOWN: "Seni görüyorum ama şu an tam olarak ne yaptığını ayırt edemiyorum.",
}


@dataclass
class ActivityObservation:
    timestamp: float
    cues: Set[str] = field(default_factory=set)


class TemporalActivityEngine:
    """Multi-frame temporal aggregator for human activity recognition."""

    def __init__(
        self,
        window_duration_s: float = 3.0,
        min_evidence_ratio: float = 0.50,
        activity_ttl_s: float = 3.5,
    ):
        self.window_duration_s = window_duration_s
        self.min_evidence_ratio = min_evidence_ratio
        self.activity_ttl_s = activity_ttl_s
        self._person_histories: Dict[str, Deque[ActivityObservation]] = {}
        self._last_active_activity: Dict[str, Tuple[HumanActivity, float, float]] = {}  # pid -> (act, conf, ts)

    def evaluate(
        self,
        person: UnifiedPersonState,
        associated_objects: List[SpatialObjectState],
        motion_features: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Tuple[HumanActivity, float, List[str]]:
        t = now if now is not None else time.time()
        pid = person.person_id

        if pid not in self._person_histories:
            self._person_histories[pid] = deque()

        history = self._person_histories[pid]

        # 1. Extract instantaneous cues for current frame
        cues: Set[str] = set()
        interacting = getattr(person, "interacting_objects", []) or []
        obj_classes = {obj.class_name for obj in associated_objects} | set(interacting)

        # A. Drinking cues
        if any(c in obj_classes for c in ("cup", "bottle", "wine glass")):
            # Check if any cup is holding / near mouth
            for obj in associated_objects:
                if obj.class_name in ("cup", "bottle", "wine glass"):
                    if obj.interaction_type == "holding":
                        cues.add("cup_held")
                        cues.add("drinking_motion")
                    elif obj.interaction_type == "near":
                        cues.add("cup_near")

        # B. Phone cues
        if "cell phone" in obj_classes:
            for obj in associated_objects:
                if obj.class_name == "cell phone":
                    if obj.interaction_type == "holding":
                        cues.add("phone_held")
                        cues.add("using_phone_motion")

        # C. Computer cues
        if any(c in obj_classes for c in ("laptop", "keyboard")):
            for obj in associated_objects:
                if obj.class_name in ("laptop", "keyboard"):
                    cues.add("laptop_in_front")

        # D. Reading cues
        if "book" in obj_classes:
            for obj in associated_objects:
                if obj.class_name == "book":
                    cues.add("book_held")

        # E. Eating cues
        if any(c in obj_classes for c in ("fork", "knife", "spoon", "bowl", "sandwich", "apple", "banana", "pizza")):
            for obj in associated_objects:
                if obj.class_name in ("fork", "spoon", "sandwich", "apple", "pizza"):
                    cues.add("food_held")

        # F. Locomotion / Walking cues
        vel = abs(getattr(person, "approach_velocity_mps", 0.0) or 0.0)
        if motion_features and motion_features.get("is_walking"):
            cues.add("walking_motion")
        elif vel > 0.35:
            cues.add("walking_motion")

        # G. Hand Waving cues
        if motion_features and motion_features.get("is_waving"):
            cues.add("waving_motion")

        # H. Talking cues
        if getattr(person, "is_speaking", False) and getattr(person, "is_looking_at_robot", False):
            cues.add("talking_active")

        # I. Posture cues (Sitting vs Standing)
        dist = getattr(person, "distance_m", 1.5) or 1.5
        if "walking_motion" not in cues and dist <= 2.2:
            # Grounded: Sitting requires posture cue, spatial chair/couch, face_bbox geometry, or stationary proximity
            if motion_features and motion_features.get("posture") == "sitting":
                cues.add("posture_sitting")
            elif motion_features and motion_features.get("posture") == "standing":
                cues.add("posture_standing")
            elif any(c in obj_classes for c in ("chair", "couch")):
                # Associated with chair or couch
                cues.add("posture_sitting")
            elif getattr(person, "face_bbox", None):
                fb = person.face_bbox
                if isinstance(fb, (list, tuple)) and len(fb) == 4 and any(fb):
                    cy = fb[1] + (fb[3] / 2.0)
                    if cy >= 180:
                        cues.add("posture_sitting")
                    else:
                        cues.add("posture_standing")

        # Record observation
        history.append(ActivityObservation(timestamp=t, cues=cues))

        # 2. Prune old history outside temporal window
        while history and (t - history[0].timestamp) > self.window_duration_s:
            history.popleft()

        total_frames = len(history)
        if total_frames < 2:
            # Need at least 2 consecutive frames to establish temporal pattern
            return HumanActivity.UNKNOWN, 0.0, []

        # 3. Count temporal frequencies
        counts: Dict[str, int] = {}
        for obs in history:
            for c in obs.cues:
                counts[c] = counts.get(c, 0) + 1

        # 4. Resolve dominant activity with temporal evidence gates
        min_count = max(2, int(total_frames * self.min_evidence_ratio))

        # Priority 1: High-level task interactions (Drinking, Eating, Phone, Computer, Reading)
        if counts.get("drinking_motion", 0) >= min_count:
            conf = min(0.95, 0.70 + 0.05 * counts["drinking_motion"])
            self._last_active_activity[pid] = (HumanActivity.DRINKING, conf, t)
            return HumanActivity.DRINKING, conf, ["cup_holding", f"sustained_{counts['drinking_motion']}_frames"]

        if counts.get("using_phone_motion", 0) >= min_count:
            conf = min(0.92, 0.70 + 0.05 * counts["using_phone_motion"])
            self._last_active_activity[pid] = (HumanActivity.USING_PHONE, conf, t)
            return HumanActivity.USING_PHONE, conf, ["phone_holding", f"sustained_{counts['using_phone_motion']}_frames"]

        if counts.get("laptop_in_front", 0) >= min_count:
            conf = 0.88
            self._last_active_activity[pid] = (HumanActivity.USING_COMPUTER, conf, t)
            return HumanActivity.USING_COMPUTER, conf, ["laptop_proximity", f"sustained_{counts['laptop_in_front']}_frames"]

        if counts.get("book_held", 0) >= min_count:
            conf = 0.85
            self._last_active_activity[pid] = (HumanActivity.READING, conf, t)
            return HumanActivity.READING, conf, ["book_interaction", f"sustained_{counts['book_held']}_frames"]

        if counts.get("food_held", 0) >= min_count:
            conf = 0.85
            self._last_active_activity[pid] = (HumanActivity.EATING, conf, t)
            return HumanActivity.EATING, conf, ["food_tableware_near_mouth", f"sustained_{counts['food_held']}_frames"]

        # Priority 2: Expressive Gestures (Waving, Talking)
        if counts.get("waving_motion", 0) >= max(2, min_count - 1):
            conf = 0.85
            self._last_active_activity[pid] = (HumanActivity.WAVING, conf, t)
            return HumanActivity.WAVING, conf, ["cyclic_hand_motion"]

        if counts.get("talking_active", 0) >= min_count:
            conf = 0.80
            self._last_active_activity[pid] = (HumanActivity.TALKING, conf, t)
            return HumanActivity.TALKING, conf, ["speech_vad", "mutual_gaze"]

        # Priority 3: Locomotion (Walking)
        if counts.get("walking_motion", 0) >= min_count:
            conf = 0.82
            self._last_active_activity[pid] = (HumanActivity.WALKING, conf, t)
            return HumanActivity.WALKING, conf, ["continuous_displacement"]

        # Priority 4: Stationary Posture (Sitting vs Standing)
        if counts.get("posture_sitting", 0) >= min_count:
            conf = 0.75
            self._last_active_activity[pid] = (HumanActivity.SITTING, conf, t)
            return HumanActivity.SITTING, conf, ["stable_seated_geometry"]

        if counts.get("posture_standing", 0) >= min_count:
            conf = 0.75
            self._last_active_activity[pid] = (HumanActivity.STANDING, conf, t)
            return HumanActivity.STANDING, conf, ["stable_standing_geometry"]

        # Check TTL on previous active activity before dropping to UNKNOWN
        if pid in self._last_active_activity:
            prev_act, prev_conf, prev_ts = self._last_active_activity[pid]
            if (t - prev_ts) <= self.activity_ttl_s and prev_act != HumanActivity.UNKNOWN:
                decayed_conf = max(0.55, prev_conf * (1.0 - (t - prev_ts) / self.activity_ttl_s))
                return prev_act, round(decayed_conf, 2), ["decaying_recent_activity"]

        return HumanActivity.UNKNOWN, 0.0, []
