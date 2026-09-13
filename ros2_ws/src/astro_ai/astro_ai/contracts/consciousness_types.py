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

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class RobotAffectiveState:
    """Behavioral modulators governing reaction speed, verbosity, and attention bias.
    
    IMPORTANT: These are numerical behavioral modulators, NOT biological emotions.
    They must never directly issue motor commands or unilaterally mutate state.
    """
    arousal: float = 0.2             # 0.0 (calm/baseline) to 1.0 (high alert)
    urgency: float = 0.0             # 0.0 (relaxed) to 1.0 (strict deadline/safety)
    social_engagement: float = 0.0   # 0.0 (isolated) to 1.0 (active dialogue)
    confidence: float = 0.7          # 0.0 (confused) to 1.0 (self-assured)
    uncertainty: float = 0.3         # 0.0 (clear certainty) to 1.0 (high ambiguity)
    curiosity: float = 0.3           # 0.0 (passive) to 1.0 (explorative/novelty seeking)
    frustration: float = 0.0         # 0.0 (smooth execution) to 1.0 (repeated failures)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
    overall_confidence: float = 0.8
    uncertainty_level: float = 0.2
    
    # Diagnostics & Capabilities
    active_capabilities: Set[str] = field(default_factory=set)
    degraded_capabilities: Set[str] = field(default_factory=set)
    cycle_time_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

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
            "active_capabilities": list(self.active_capabilities),
            "degraded_capabilities": list(self.degraded_capabilities),
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
