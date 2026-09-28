"""ASTRO V1 — Behavioral Intelligence Data Contracts and Types (Phase 7).

Defines core enums, dataclasses, and mapping utilities for:
  - Behavioral Intent and Lifecycle Status
  - Behavior Types grounded in ASTRO's physical morphology
  - Priority Categories and Arbitration Rankings
  - Decoupled Action Translation (BehavioralIntent -> ActionIntent)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid

from astro_ai.contracts.consciousness_types import ActionIntent


# =============================================================================
# 1. BEHAVIOR ENUMS
# =============================================================================

class BehaviorType(str, Enum):
    """High-level behavioral postures/activities grounded in ASTRO's physical morphology.

    IMPORTANT: These represent high-level embodied intentions, NOT raw motor commands.
    """
    # Safety & Protective
    SAFETY_HALT = "SAFETY_HALT"                         # Emergency stop / obstacle proximity lock

    # Social Interaction & Attention
    ACTIVE_SOCIAL_ENGAGEMENT = "ACTIVE_SOCIAL_ENGAGEMENT" # Engaged in active dialogue
    MAINTAIN_GAZE = "MAINTAIN_GAZE"                     # Maintaining eye contact / head tracking on interlocutor
    ATTENTIVE_LISTENING = "ATTENTIVE_LISTENING"         # Attentive listening with nod cues
    THINKING_AVERSION = "THINKING_AVERSION"             # Gaze aversion during thinking/processing
    PUZZLED_TILT = "PUZZLED_TILT"                       # Head tilt on confusion, contradiction, or insufficient info
    ORIENT_TO_STIMULUS = "ORIENT_TO_STIMULUS"           # Orienting head towards person/social stimulus

    # Active Perception & Epistemic Search
    ACTIVE_PERCEPTION_SEARCH = "ACTIVE_PERCEPTION_SEARCH" # Orienting to unverified acoustic stimulus to seek face

    # Mobile Base & Proxemics Regulation
    APPROACH_INTERLOCUTOR = "APPROACH_INTERLOCUTOR"     # Gentle approach towards distant interlocutor
    MAINTAIN_SOCIAL_DISTANCE = "MAINTAIN_SOCIAL_DISTANCE" # Backing up to maintain comfortable social distance
    ALIGN_BODY_TO_TARGET = "ALIGN_BODY_TO_TARGET"       # Rotating base to center head with interlocutor
    STOP_AND_HOLD = "STOP_AND_HOLD"                     # Holding zero velocity at interaction distance

    # Idle & Baseline
    IDLE_ATTENTIVE = "IDLE_ATTENTIVE"                   # Ambient idle with baseline awareness


class BehaviorStatus(str, Enum):
    """Lifecycle status of a behavioral intent."""
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"


class BehaviorPriority:
    """Standardized deterministic priority weights for arbitration [0.0, 1.0]."""
    CRITICAL_SAFETY: float = 1.0
    ACTIVE_ENGAGEMENT: float = 0.8
    ACTIVE_PERCEPTION: float = 0.7
    SOCIAL_REGULATION: float = 0.6
    CONFUSION_RECOVERY: float = 0.55
    INTERACTION_INITIATION: float = 0.50
    GAZE_TRACKING: float = 0.45
    IDLE: float = 0.1


# =============================================================================
# 2. BEHAVIORAL INTENT DATACLASS
# =============================================================================

@dataclass
class BehavioralIntent:
    """A high-level behavioral intention selected by Behavioral Intelligence.

    Represents what ASTRO wants to embody/pursue right now, separated from
    the physical actuator commands (ActionIntent).
    """
    behavior_type: BehaviorType
    behavior_id: str = field(default_factory=lambda: f"beh_{uuid.uuid4().hex[:8]}")
    priority: float = 0.5
    target_id: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    status: BehaviorStatus = BehaviorStatus.CREATED
    reason: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    timeout_s: float = 5.0
    related_prediction_id: Optional[str] = None
    source_decision_id: Optional[str] = None

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Returns True if this intent has exceeded its timeout duration."""
        current = time.time() if now is None else now
        reference_time = self.started_at or self.created_at
        return (current - reference_time) > self.timeout_s

    def mark_active(self, now: Optional[float] = None) -> None:
        """Transitions intent to ACTIVE state."""
        self.status = BehaviorStatus.ACTIVE
        self.started_at = time.time() if now is None else now

    def mark_completed(self, reason: str = "", now: Optional[float] = None) -> None:
        """Transitions intent to COMPLETED state."""
        self.status = BehaviorStatus.COMPLETED
        self.completed_at = time.time() if now is None else now
        if reason:
            self.reason = reason

    def mark_failed(self, reason: str = "", now: Optional[float] = None) -> None:
        """Transitions intent to FAILED state."""
        self.status = BehaviorStatus.FAILED
        self.completed_at = time.time() if now is None else now
        if reason:
            self.reason = reason

    def mark_interrupted(self, reason: str = "", now: Optional[float] = None) -> None:
        """Transitions intent to INTERRUPTED state."""
        self.status = BehaviorStatus.INTERRUPTED
        self.completed_at = time.time() if now is None else now
        if reason:
            self.reason = reason

    def mark_cancelled(self, reason: str = "", now: Optional[float] = None) -> None:
        """Transitions intent to CANCELLED state."""
        self.status = BehaviorStatus.CANCELLED
        self.completed_at = time.time() if now is None else now
        if reason:
            self.reason = reason

    def to_dict(self) -> Dict[str, Any]:
        """Serializes BehavioralIntent to JSON-compatible dictionary."""
        d = asdict(self)
        d["behavior_type"] = self.behavior_type.value if hasattr(self.behavior_type, "value") else str(self.behavior_type)
        d["status"] = self.status.value if hasattr(self.status, "value") else str(self.status)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BehavioralIntent:
        """Deserializes BehavioralIntent from dictionary."""
        btype_val = data.get("behavior_type", BehaviorType.IDLE_ATTENTIVE.value)
        if isinstance(btype_val, str):
            try:
                btype_enum = BehaviorType(btype_val)
            except ValueError:
                btype_enum = BehaviorType.IDLE_ATTENTIVE
        else:
            btype_enum = btype_val

        status_val = data.get("status", BehaviorStatus.CREATED.value)
        if isinstance(status_val, str):
            try:
                status_enum = BehaviorStatus(status_val)
            except ValueError:
                status_enum = BehaviorStatus.CREATED
        else:
            status_enum = status_val

        return cls(
            behavior_id=data.get("behavior_id", f"beh_{uuid.uuid4().hex[:8]}"),
            behavior_type=btype_enum,
            priority=float(data.get("priority", 0.5)),
            target_id=data.get("target_id"),
            parameters=dict(data.get("parameters", {})),
            status=status_enum,
            reason=data.get("reason", ""),
            created_at=float(data.get("created_at", time.time())),
            started_at=float(data["started_at"]) if data.get("started_at") is not None else None,
            completed_at=float(data["completed_at"]) if data.get("completed_at") is not None else None,
            timeout_s=float(data.get("timeout_s", 5.0)),
            related_prediction_id=data.get("related_prediction_id"),
            source_decision_id=data.get("source_decision_id"),
        )


# =============================================================================
# 3. ACTION TRANSLATION (Decoupled Action Layer Bridge)
# =============================================================================

def behavior_intent_to_action_intent(behavior: BehavioralIntent) -> Optional[ActionIntent]:
    """Translates high-level BehavioralIntent to atomic ActionIntent.

    This function lives in the Action Layer boundary:
    BehaviorEngine emits BehavioralIntent -> Translation maps to ActionIntent -> ActionManager executes.
    """
    if behavior.status not in (BehaviorStatus.CREATED, BehaviorStatus.ACTIVE):
        return None

    now = time.time()
    btype = behavior.behavior_type
    params = behavior.parameters

    if btype == BehaviorType.SAFETY_HALT:
        return ActionIntent(
            intent_id=f"act_halt_{behavior.behavior_id}",
            action_type="move_robot",
            parameters={"direction": "stop"},
            priority=1.0,
            created_at=now,
        )

    elif btype in (BehaviorType.ORIENT_TO_STIMULUS, BehaviorType.ACTIVE_PERCEPTION_SEARCH):
        target_yaw = float(params.get("target_yaw_deg", params.get("azimuth_deg", 0.0)))
        return ActionIntent(
            intent_id=f"act_orient_{behavior.behavior_id}",
            action_type="turn_head",
            target=behavior.target_id,
            parameters={
                "target_yaw_deg": target_yaw,
                "confidence": float(params.get("confidence", 0.8)),
                "source": "behavior_orient",
            },
            priority=behavior.priority,
            created_at=now,
        )

    elif btype == BehaviorType.MAINTAIN_GAZE:
        target_yaw = float(params.get("target_yaw_deg", params.get("azimuth_deg", 0.0)))
        return ActionIntent(
            intent_id=f"act_gaze_{behavior.behavior_id}",
            action_type="track_gaze",
            target=behavior.target_id,
            parameters={
                "target_yaw_deg": target_yaw,
                "selector": "CURRENT_SPEAKER",
            },
            priority=behavior.priority,
            created_at=now,
        )

    elif btype == BehaviorType.THINKING_AVERSION:
        offset_yaw = float(params.get("offset_yaw_deg", 3.0))
        return ActionIntent(
            intent_id=f"act_avert_{behavior.behavior_id}",
            action_type="gaze_aversion",
            parameters={"offset_yaw_deg": offset_yaw},
            priority=behavior.priority,
            created_at=now,
        )

    elif btype == BehaviorType.ATTENTIVE_LISTENING:
        return ActionIntent(
            intent_id=f"act_nod_{behavior.behavior_id}",
            action_type="gesture",
            parameters={"gesture_name": "nod", "duration_ms": int(params.get("duration_ms", 600))},
            priority=behavior.priority,
            created_at=now,
        )

    elif btype == BehaviorType.PUZZLED_TILT:
        return ActionIntent(
            intent_id=f"act_tilt_{behavior.behavior_id}",
            action_type="gesture",
            parameters={"gesture_name": "tilt", "duration_ms": int(params.get("duration_ms", 600))},
            priority=behavior.priority,
            created_at=now,
        )

    elif btype == BehaviorType.APPROACH_INTERLOCUTOR:
        speed = float(params.get("speed", 0.20))
        duration = float(params.get("duration", 1.0))
        return ActionIntent(
            intent_id=f"act_approach_{behavior.behavior_id}",
            action_type="move_robot",
            parameters={"direction": "forward", "speed": speed, "duration": duration},
            priority=behavior.priority,
            created_at=now,
        )

    elif btype == BehaviorType.MAINTAIN_SOCIAL_DISTANCE:
        speed = float(params.get("speed", 0.15))
        duration = float(params.get("duration", 0.8))
        return ActionIntent(
            intent_id=f"act_retreat_{behavior.behavior_id}",
            action_type="move_robot",
            parameters={"direction": "backward", "speed": speed, "duration": duration},
            priority=behavior.priority,
            created_at=now,
        )

    elif btype == BehaviorType.ALIGN_BODY_TO_TARGET:
        direction = "left" if float(params.get("target_yaw_deg", 0.0)) > 0 else "right"
        speed = float(params.get("angular_speed", 0.15))
        return ActionIntent(
            intent_id=f"act_align_{behavior.behavior_id}",
            action_type="move_robot",
            parameters={"direction": direction, "speed": speed, "duration": 0.5},
            priority=behavior.priority,
            created_at=now,
        )

    elif btype == BehaviorType.STOP_AND_HOLD:
        return ActionIntent(
            intent_id=f"act_stop_{behavior.behavior_id}",
            action_type="move_robot",
            parameters={"direction": "stop"},
            priority=behavior.priority,
            created_at=now,
        )

    elif btype == BehaviorType.IDLE_ATTENTIVE:
        return None

    return None
