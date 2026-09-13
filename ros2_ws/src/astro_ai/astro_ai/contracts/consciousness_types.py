"""ASTRO V1 — Consciousness Architecture Data Contracts and Types.

Provides foundational type definitions, enums, and dataclasses for:
  - Cognitive Events and Salience
  - Goal Management and Status
  - Action Predictions and Expectations
  - Robot Affective Modulators
  - Introspective Self-State
  - Ephemeral Cognitive Workspace
  - Action Intents
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from astro_ai.contracts.intent_emotion_types import ConversationPhase
from astro_ai.contracts.memory_models import MemoryRecord
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.state_machine import RobotState


# =============================================================================
# 1. ENUMS
# =============================================================================

class CognitiveEventType(str, Enum):
    """Semantic events processed by the Consciousness Core."""
    # Person Perception Events
    PERSON_APPEARED = "PERSON_APPEARED"
    PERSON_DISAPPEARED = "PERSON_DISAPPEARED"
    PERSON_RETURNED = "PERSON_RETURNED"
    PERSON_RECOGNIZED = "PERSON_RECOGNIZED"
    PERSON_SPOKE = "PERSON_SPOKE"
    
    # Robot State Events
    ROBOT_STARTED_SPEAKING = "ROBOT_STARTED_SPEAKING"
    ROBOT_FINISHED_SPEAKING = "ROBOT_FINISHED_SPEAKING"
    ROBOT_INTERRUPTED = "ROBOT_INTERRUPTED"
    OPERATIONAL_STATE_CHANGED = "OPERATIONAL_STATE_CHANGED"
    SOCIAL_PHASE_CHANGED = "SOCIAL_PHASE_CHANGED"
    
    # Action & Prediction Events
    ACTION_STARTED = "ACTION_STARTED"
    ACTION_SUCCEEDED = "ACTION_SUCCEEDED"
    ACTION_FAILED = "ACTION_FAILED"
    PREDICTION_CONFIRMED = "PREDICTION_CONFIRMED"
    PREDICTION_ERROR = "PREDICTION_ERROR"
    PREDICTION_EXPIRED = "PREDICTION_EXPIRED"
    
    # Goal & Decision Events
    GOAL_CREATED = "GOAL_CREATED"
    GOAL_COMPLETED = "GOAL_COMPLETED"
    GOAL_FAILED = "GOAL_FAILED"
    GOAL_CONFLICT = "GOAL_CONFLICT"
    
    # Attention & Cognitive Events
    NOVELTY_DETECTED = "NOVELTY_DETECTED"
    ATTENTION_SHIFTED = "ATTENTION_SHIFTED"
    TARGET_CHANGED = "TARGET_CHANGED"
    REASONING_REQUESTED = "REASONING_REQUESTED"
    
    # System & Degradation Events
    SENSOR_LOST = "SENSOR_LOST"
    SENSOR_RECOVERED = "SENSOR_RECOVERED"
    CAPABILITY_DEGRADED = "CAPABILITY_DEGRADED"


class GoalType(str, Enum):
    """Categories of goals governed by Consciousness."""
    SAFETY = "SAFETY"          # Hard constraint: obstacle, hardware protection, e-stop
    SOCIAL = "SOCIAL"          # Greet, converse, farewell, engage user
    TASK = "TASK"              # Reminder, question answer, user command execution
    MAINTENANCE = "MAINTENANCE" # Calibration, memory consolidation, self-diagnostics


class GoalStatus(str, Enum):
    """Lifecycle status of a cognitive goal."""
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SUSPENDED = "SUSPENDED"


class PredictionStatus(str, Enum):
    """Lifecycle state of an action expectation."""
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    MISMATCH = "MISMATCH"
    EXPIRED = "EXPIRED"


# =============================================================================
# 2. DATACLASSES
# =============================================================================

@dataclass
class CognitiveEvent:
    """Represents a discrete semantic event evaluated by the Cognitive Event Bus."""
    event_type: CognitiveEventType
    source: str
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:10]}")
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    salience: float = 0.5            # Importance score: 0.0 to 1.0
    is_novel: bool = False           # Novelty flag
    processed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["event_type"] = self.event_type.value
        return d


@dataclass
class Goal:
    """A cognitive objective pursued by ASTRO."""
    goal_id: str
    goal_type: GoalType
    description: str
    priority: float = 0.5            # 0.0 (lowest) to 1.0 (highest, Safety = 1.0)
    status: GoalStatus = GoalStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    deadline: Optional[float] = None
    progress: float = 0.0            # 0.0 to 1.0
    parent_goal_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["goal_type"] = self.goal_type.value
        d["status"] = self.status.value
        return d


@dataclass
class Prediction:
    """An action outcome expectation evaluated against subsequent observations."""
    prediction_id: str
    action_id: str
    expected_state: Dict[str, Any]   # What state features we expect
    expected_by: float               # Expiry timestamp
    created_at: float = field(default_factory=time.time)
    status: PredictionStatus = PredictionStatus.PENDING
    confidence_weight: float = 1.0   # Impact weight on confidence on mismatch
    source: str = ""
    related_goal_id: Optional[str] = None
    target_person_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: Optional[float] = None) -> bool:
        """Returns True if the expectation's deadline has passed."""
        current = time.time() if now is None else now
        return current > self.expected_by

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class ActualOutcome:
    """A structured representation of an observed real-world outcome."""
    outcome_id: str
    actual_state: Dict[str, Any]
    expectation_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PredictionError:
    """Discrepancy calculation between an expectation and actual outcome."""
    expectation_id: str
    matched: bool
    mismatch_score: float              # 0.0 (exact match) to 1.0 (total mismatch)
    mismatch_type: str = "NONE"       # NONE, VALUE_MISMATCH, MISSING_KEY, TIMEOUT_EXPIRED
    confidence_impact: float = 0.0    # Signed delta applied to confidence
    uncertainty_impact: float = 0.0   # Signed delta applied to uncertainty
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GoalChangeCause(str, Enum):
    """Machine-readable causes for goal state changes."""
    USER_REQUEST = "USER_REQUEST"
    SAFETY_OVERRIDE = "SAFETY_OVERRIDE"
    PREDICTION_ERROR = "PREDICTION_ERROR"
    TIMEOUT = "TIMEOUT"
    COMPLETION = "COMPLETION"
    PERCEPTION_TRIGGER = "PERCEPTION_TRIGGER"
    MANUAL = "MANUAL"
    INTERNAL_HOMEOSTASIS = "INTERNAL_HOMEOSTASIS"


@dataclass
class CognitiveTransition:
    """Structured record of a cognitive state change."""
    transition_id: str
    timestamp: float
    transition_type: str
    previous_value: Any
    new_value: Any
    cause: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RobotAffectiveState:
    """Behavioral modulators governing reaction speed, verbosity, and attention bias.
    
    IMPORTANT: These are numerical behavioral modulators, NOT biological emotions.
    They must never directly issue motor commands or unilaterally mutate state.
    """
    arousal: float = 0.2             # 0.0 (calm/baseline) to 1.0 (high alert)
    urgency: float = 0.0             # 0.0 (relaxed) to 1.0 (strict deadline/safety)
    social_engagement: float = 0.0   # 0.0 (isolated) to 1.0 (active dialogue)
    confidence: float = 0.7          # 0.1 (confused) to 1.0 (self-assured)
    uncertainty: float = 0.3         # 0.0 (clear certainty) to 1.0 (high ambiguity)
    curiosity: float = 0.3           # 0.0 (passive) to 1.0 (explorative/novelty seeking)
    frustration: float = 0.0         # 0.0 (smooth execution) to 1.0 (repeated failures)

    def clamp(self) -> None:
        """Clamps all modulators to their respective valid ranges."""
        self.arousal = min(1.0, max(0.0, float(self.arousal)))
        self.urgency = min(1.0, max(0.0, float(self.urgency)))
        self.social_engagement = min(1.0, max(0.0, float(self.social_engagement)))
        self.confidence = min(1.0, max(0.1, float(self.confidence)))
        self.uncertainty = min(1.0, max(0.0, float(self.uncertainty)))
        self.curiosity = min(1.0, max(0.0, float(self.curiosity)))
        self.frustration = min(1.0, max(0.0, float(self.frustration)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def get_reaction_speed_multiplier(self) -> float:
        """Computes reaction speed factor (1.0 = normal, >1.0 = faster)."""
        return 1.0 + (self.arousal * 0.4) + (self.urgency * 0.6)

    def get_verbosity_multiplier(self) -> float:
        """Computes dialogue verbosity factor (higher = more verbose, lower = concise)."""
        base = 1.0 + (self.social_engagement * 0.3) + (self.confidence * 0.2)
        penalty = (self.urgency * 0.5) + (self.frustration * 0.3)
        return max(0.2, base - penalty)

    def get_attention_sensitivity(self) -> float:
        """Computes attention salience threshold sensitivity (higher = more reactive)."""
        return 1.0 + (self.arousal * 0.5) + (self.curiosity * 0.3)


@dataclass
class SelfState:
    """Aggregate introspective representation of ASTRO's dynamic runtime state.
    
    Reads from StateMachine and hardware feedback, but does NOT own the StateMachine.
    """
    operational_state: RobotState = RobotState.IDLE
    is_speaking: bool = False
    is_listening: bool = False
    current_head_yaw_deg: float = 0.0
    
    # Cognitive focus & continuity
    focused_person_id: Optional[str] = None
    current_goal: Optional[Goal] = None
    active_prediction: Optional[Prediction] = None
    
    # Introspection metrics
    overall_confidence: float = 0.7
    uncertainty_level: float = 0.3
    
    # Diagnostics & Capabilities
    active_capabilities: Set[str] = field(default_factory=set)
    degraded_capabilities: Set[str] = field(default_factory=set)
    cycle_time_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    # -------------------------------------------------------------------------
    # Basic Introspection Queries
    # -------------------------------------------------------------------------

    def get_current_activity(self) -> str:
        """Introspective answer to 'What am I doing?'"""
        if self.is_speaking:
            if self.focused_person_id:
                return f"Speaking with {self.focused_person_id}"
            return "Speaking"
        if self.is_listening:
            if self.focused_person_id:
                return f"Listening to {self.focused_person_id}"
            return "Listening"
        if self.active_prediction is not None:
            return f"Executing action ({self.active_prediction.action_id})"
        if self.current_goal is not None:
            return f"Pursuing goal: {self.current_goal.description}"
        if self.operational_state == RobotState.THINKING:
            return "Deliberating / reasoning"
        if self.operational_state == RobotState.THINKING_ACK:
            return "Processing acknowledgment"
        if self.operational_state == RobotState.WAKE:
            return "Awakening and orienting"
        if self.operational_state == RobotState.ENROLLING:
            return "Enrolling user profile"
        if self.operational_state == RobotState.INTERRUPTED:
            return "Interrupted / adapting"
        if self.operational_state == RobotState.DEEP_IDLE:
            return "Deep idle power-saving"
        return "Idling / monitoring surroundings"

    def get_operational_state(self) -> RobotState:
        """Returns current operational state read from StateMachine."""
        return self.operational_state

    def get_focused_person(self) -> Optional[str]:
        """Returns the ID of the person ASTRO is actively focusing on."""
        return self.focused_person_id

    def get_active_goal(self) -> Optional[Goal]:
        """Returns the active cognitive goal if any."""
        return self.current_goal

    def is_executing_action(self) -> bool:
        """Returns True if an action or vocal expression is actively executing."""
        return self.active_prediction is not None or self.is_speaking

    def get_confidence(self) -> float:
        """Returns current epistemic confidence [0.1, 1.0]."""
        return self.overall_confidence

    def get_uncertainty(self) -> float:
        """Returns current uncertainty level [0.0, 1.0]."""
        return self.uncertainty_level

    def get_degraded_capabilities(self) -> Set[str]:
        """Returns set of degraded capabilities/sensors."""
        return set(self.degraded_capabilities)

    def get_introspection_summary(self) -> Dict[str, Any]:
        """Returns a consolidated introspective snapshot answering core self-queries."""
        return {
            "activity": self.get_current_activity(),
            "operational_state": self.operational_state.value if isinstance(self.operational_state, RobotState) else str(self.operational_state),
            "focused_person_id": self.focused_person_id,
            "active_goal_id": self.current_goal.goal_id if self.current_goal else None,
            "active_action_id": self.active_prediction.action_id if self.active_prediction else None,
            "is_executing_action": self.is_executing_action(),
            "confidence": round(self.overall_confidence, 3),
            "uncertainty": round(self.uncertainty_level, 3),
            "degraded_capabilities": sorted(list(self.degraded_capabilities)),
            "cycle_time_ms": round(self.cycle_time_ms, 2),
            "timestamp": round(self.timestamp, 3),
        }

    # -------------------------------------------------------------------------
    # State Synchronization (Strictly Read-Only from Source of Truth)
    # -------------------------------------------------------------------------

    def update_from_state_machine(self, state_machine: Any) -> None:
        """Synchronizes operational state from StateMachine without mutating StateMachine."""
        if hasattr(state_machine, "current_state"):
            self.operational_state = state_machine.current_state
            if self.operational_state == RobotState.LISTENING:
                self.is_listening = True
            elif self.operational_state == RobotState.SPEAKING:
                self.is_speaking = True
            elif self.operational_state == RobotState.IDLE:
                self.is_speaking = False
                self.is_listening = False

    def update_from_perception(self, perception_data: Dict[str, Any]) -> None:
        """Updates internal physical self-state from perception observation dictionary."""
        if not perception_data:
            return

        if "tts_speaking" in perception_data:
            self.is_speaking = bool(perception_data["tts_speaking"])
        if "vad" in perception_data:
            self.is_listening = bool(perception_data["vad"])

        robot_state = perception_data.get("robot_state")
        if isinstance(robot_state, dict):
            if "is_speaking" in robot_state:
                self.is_speaking = bool(robot_state["is_speaking"])
            if "is_listening" in robot_state:
                self.is_listening = bool(robot_state["is_listening"])
            if "head_yaw_deg" in robot_state:
                self.current_head_yaw_deg = float(robot_state["head_yaw_deg"])
        elif "head_yaw_deg" in perception_data:
            self.current_head_yaw_deg = float(perception_data["head_yaw_deg"])

        if "active_target_id" in perception_data:
            self.focused_person_id = perception_data["active_target_id"]
        elif "focused_person_id" in perception_data:
            self.focused_person_id = perception_data["focused_person_id"]

    def set_confidence(self, val: float) -> None:
        """Sets confidence clamped to [0.1, 1.0]."""
        self.overall_confidence = min(1.0, max(0.1, float(val)))

    def set_uncertainty(self, val: float) -> None:
        """Sets uncertainty clamped to [0.0, 1.0]."""
        self.uncertainty_level = min(1.0, max(0.0, float(val)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operational_state": self.operational_state.value if isinstance(self.operational_state, RobotState) else str(self.operational_state),
            "is_speaking": self.is_speaking,
            "is_listening": self.is_listening,
            "current_head_yaw_deg": round(self.current_head_yaw_deg, 2),
            "focused_person_id": self.focused_person_id,
            "current_goal": self.current_goal.to_dict() if self.current_goal else None,
            "active_prediction": self.active_prediction.to_dict() if self.active_prediction else None,
            "overall_confidence": round(self.overall_confidence, 3),
            "uncertainty_level": round(self.uncertainty_level, 3),
            "active_capabilities": sorted(list(self.active_capabilities)),
            "degraded_capabilities": sorted(list(self.degraded_capabilities)),
            "cycle_time_ms": round(self.cycle_time_ms, 2),
            "timestamp": round(self.timestamp, 3),
        }


@dataclass
class ActionIntent:
    """A proposed action emitted by Consciousness to existing ROS2 subsystems."""
    intent_id: str
    action_type: str                 # e.g., "gaze_hint", "speak_request", "tool_call", "motion_request"
    target: Optional[str] = None     # Target person/entity ID or direction
    parameters: Dict[str, Any] = field(default_factory=dict)
    priority: float = 0.5            # 0.0 to 1.0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CognitiveWorkspace:
    """Ephemeral in-memory workspace synthesizing the active cognitive context."""
    timestamp: float = field(default_factory=time.time)
    
    # Active focus
    active_person: Optional[UnifiedPersonState] = None
    present_people: List[UnifiedPersonState] = field(default_factory=list)
    
    # Active event & recent summary
    trigger_event: Optional[CognitiveEvent] = None
    recent_events_summary: List[str] = field(default_factory=list)
    
    # Active pursuit
    active_goal: Optional[Goal] = None
    pending_action: Optional[ActionIntent] = None
    expected_prediction: Optional[Prediction] = None
    
    # Retrieved memories (from memory_v2)
    retrieved_facts: List[MemoryRecord] = field(default_factory=list)
    relationship_context: Dict[str, Any] = field(default_factory=dict)
    
    # Robot self-representation
    self_state_snapshot: Optional[SelfState] = None
    affective_modulators: Optional[RobotAffectiveState] = None
    
    # Reasoning indication
    reasoning_flag: bool = False
    reasoning_rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": round(self.timestamp, 3),
            "active_person_id": self.active_person.person_id if self.active_person else None,
            "present_people_count": len(self.present_people),
            "trigger_event": self.trigger_event.to_dict() if self.trigger_event else None,
            "recent_events_summary": self.recent_events_summary,
            "active_goal": self.active_goal.to_dict() if self.active_goal else None,
            "pending_action": self.pending_action.to_dict() if self.pending_action else None,
            "expected_prediction": self.expected_prediction.to_dict() if self.expected_prediction else None,
            "retrieved_facts_count": len(self.retrieved_facts),
            "self_state": self.self_state_snapshot.to_dict() if self.self_state_snapshot else None,
            "affective_modulators": self.affective_modulators.to_dict() if self.affective_modulators else None,
            "reasoning_flag": self.reasoning_flag,
            "reasoning_rationale": self.reasoning_rationale,
        }


@dataclass(frozen=True)
class CognitiveContext:
    """Immutable read-model synthesizing ASTRO's integrated machine cognitive state.

    Integrates SelfState, SelfModel identity, capabilities, active goal,
    predictions, affective modulators, and recent transitions into a unified
    read snapshot.
    Does NOT own or mutate operational state or StateMachine.
    """
    timestamp: float = 0.0
    activity: str = "Idling"
    operational_state: str = "IDLE"
    focused_person_id: Optional[str] = None
    active_goal: Optional[Dict[str, Any]] = None
    active_prediction: Optional[Dict[str, Any]] = None
    confidence: float = 0.7
    uncertainty: float = 0.3
    affective_state: Dict[str, float] = field(default_factory=dict)
    degraded_capabilities: List[str] = field(default_factory=list)
    identity: Dict[str, str] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=list)
    recent_transitions: List[Dict[str, Any]] = field(default_factory=list)
    recent_events_summary: List[str] = field(default_factory=list)
    perception_summary: Dict[str, Any] = field(default_factory=dict)
    self_state_snapshot: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": round(self.timestamp, 3),
            "activity": self.activity,
            "operational_state": self.operational_state,
            "focused_person_id": self.focused_person_id,
            "active_goal": self.active_goal,
            "active_prediction": self.active_prediction,
            "confidence": round(self.confidence, 3),
            "uncertainty": round(self.uncertainty, 3),
            "affective_state": dict(self.affective_state),
            "degraded_capabilities": list(self.degraded_capabilities),
            "identity": dict(self.identity),
            "capabilities": list(self.capabilities),
            "recent_transitions": list(self.recent_transitions),
            "recent_events_summary": list(self.recent_events_summary),
            "perception_summary": dict(self.perception_summary),
            "self_state_snapshot": self.self_state_snapshot,
        }
