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


class InformationSufficiency(str, Enum):
    """Machine evaluation of whether sensory information is adequate for current goal."""
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"
    STALE = "STALE"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


class CognitiveDecisionType(str, Enum):
    """Internal cognitive-level intent categories.

    IMPORTANT: These are cognitive processing decisions, NOT motor/ActionIntent commands.
    """
    CONTINUE = "CONTINUE"
    REASSESS = "REASSESS"
    SEEK_INFORMATION = "SEEK_INFORMATION"
    REEVALUATE_GOAL = "REEVALUATE_GOAL"
    REVIEW_STRATEGY = "REVIEW_STRATEGY"
    WAIT_FOR_OUTCOME = "WAIT_FOR_OUTCOME"


class StrategyStatus(str, Enum):
    """Lifecycle status of a cognitive strategy."""
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


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


@dataclass
class CognitiveStrategy:
    """An explicit, machine-readable pattern of cognitive processing."""
    strategy_id: str
    strategy_type: str = "DEFAULT"
    name: str = ""
    description: str = ""
    related_goal_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    confidence: float = 0.7
    status: StrategyStatus = StrategyStatus.ACTIVE
    rationale: str = ""
    success_count: int = 0
    failure_count: int = 0
    last_used: float = field(default_factory=time.time)
    cooldown_until: float = 0.0
    parameters: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_on_cooldown(self, now: Optional[float] = None) -> bool:
        """Returns True if this strategy is in cooldown."""
        current = time.time() if now is None else now
        return current < self.cooldown_until

    def record_success(self) -> None:
        """Increments success counter."""
        self.success_count += 1
        self.last_used = time.time()

    def record_failure(self) -> None:
        """Increments failure counter."""
        self.failure_count += 1
        self.last_used = time.time()

    def record_outcome(self, success: bool) -> None:
        """Convenience method to record success or failure."""
        if success:
            self.record_success()
        else:
            self.record_failure()

    def get_success_rate(self) -> float:
        """Returns empirical success rate in [0.0, 1.0]."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return float(self.success_count) / float(total)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if hasattr(self.status, "value") else str(self.status)
        d["success_rate"] = round(self.get_success_rate(), 3)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CognitiveStrategy:
        status_val = data.get("status", StrategyStatus.ACTIVE.value)
        if isinstance(status_val, str):
            try:
                status_enum = StrategyStatus(status_val)
            except ValueError:
                status_enum = StrategyStatus.ACTIVE
        else:
            status_enum = status_val

        return cls(
            strategy_id=data["strategy_id"],
            strategy_type=data.get("strategy_type", "DEFAULT"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            related_goal_id=data.get("related_goal_id"),
            created_at=float(data.get("created_at", time.time())),
            confidence=float(data.get("confidence", 0.7)),
            status=status_enum,
            rationale=data.get("rationale", ""),
            success_count=int(data.get("success_count", 0)),
            failure_count=int(data.get("failure_count", 0)),
            last_used=float(data.get("last_used", time.time())),
            cooldown_until=float(data.get("cooldown_until", 0.0)),
            parameters=dict(data.get("parameters", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class CognitiveConflict:
    """A detected contradiction or structural incompatibility in active cognition."""
    conflict_id: str
    conflict_type: str
    severity: float = 0.5            # 0.0 (minor) to 1.0 (critical safety override)
    involved_goal_ids: List[str] = field(default_factory=list)
    involved_strategy_ids: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    detected_at: float = field(default_factory=time.time)
    status: str = "ACTIVE"           # ACTIVE, RESOLVED, IGNORED
    resolution_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CognitiveConflict:
        return cls(
            conflict_id=data["conflict_id"],
            conflict_type=data["conflict_type"],
            severity=float(data.get("severity", 0.5)),
            involved_goal_ids=list(data.get("involved_goal_ids", [])),
            involved_strategy_ids=list(data.get("involved_strategy_ids", [])),
            evidence=dict(data.get("evidence", {})),
            detected_at=float(data.get("detected_at", time.time())),
            status=data.get("status", "ACTIVE"),
            resolution_notes=data.get("resolution_notes", ""),
        )


@dataclass
class CognitiveDecision:
    """An internal cognitive processing intent emitted by metacognitive control.

    IMPORTANT: CognitiveDecision != ActionIntent.
    It guides internal processing (e.g. REASSESS, SEEK_INFORMATION), not hardware actuators.
    """
    decision_id: str
    decision_type: CognitiveDecisionType
    reason: str
    target_goal_id: Optional[str] = None
    target_strategy_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["decision_type"] = self.decision_type.value if hasattr(self.decision_type, "value") else str(self.decision_type)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CognitiveDecision:
        dtype_val = data.get("decision_type", CognitiveDecisionType.CONTINUE.value)
        if isinstance(dtype_val, str):
            try:
                dtype_enum = CognitiveDecisionType(dtype_val)
            except ValueError:
                dtype_enum = CognitiveDecisionType.CONTINUE
        else:
            dtype_enum = dtype_val

        return cls(
            decision_id=data["decision_id"],
            decision_type=dtype_enum,
            reason=data.get("reason", ""),
            target_goal_id=data.get("target_goal_id"),
            target_strategy_id=data.get("target_strategy_id"),
            timestamp=float(data.get("timestamp", time.time())),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class MetacognitiveState:
    """Aggregate assessment snapshot of ASTRO's cognitive health and strategy efficacy.

    Strictly an evaluative read representation: does NOT own operational state or StateMachine.
    """
    cognitive_status: str = "NORMAL" # NORMAL, EVALUATING, DEGRADED, CONFLICTED, REASSESSING
    current_strategy_id: Optional[str] = None
    strategy_confidence: float = 0.7
    knowledge_confidence: float = 0.7
    uncertainty_level: float = 0.3
    information_sufficiency: InformationSufficiency = InformationSufficiency.UNKNOWN
    recent_prediction_success_rate: float = 1.0
    recent_prediction_error_rate: float = 0.0
    repeated_failure_count: int = 0
    cognitive_conflict_state: str = "NONE" # NONE, DETECTED, RESOLVING
    need_for_reassessment: bool = False
    last_reassessment_reason: str = ""
    current_cognitive_load_estimate: float = 0.2
    timestamp: float = field(default_factory=time.time)

    def clamp(self) -> None:
        """Clamps all metrics to valid bounded intervals and prevents NaNs/infinities."""
        self.strategy_confidence = min(1.0, max(0.0, float(self.strategy_confidence)))
        self.knowledge_confidence = min(1.0, max(0.0, float(self.knowledge_confidence)))
        self.uncertainty_level = min(1.0, max(0.0, float(self.uncertainty_level)))
        self.recent_prediction_success_rate = min(1.0, max(0.0, float(self.recent_prediction_success_rate)))
        self.recent_prediction_error_rate = min(1.0, max(0.0, float(self.recent_prediction_error_rate)))
        self.current_cognitive_load_estimate = min(1.0, max(0.0, float(self.current_cognitive_load_estimate)))
        self.repeated_failure_count = max(0, int(self.repeated_failure_count))

    def to_dict(self) -> Dict[str, Any]:
        self.clamp()
        return {
            "cognitive_status": self.cognitive_status,
            "current_strategy_id": self.current_strategy_id,
            "strategy_confidence": round(self.strategy_confidence, 3),
            "knowledge_confidence": round(self.knowledge_confidence, 3),
            "uncertainty_level": round(self.uncertainty_level, 3),
            "information_sufficiency": (
                self.information_sufficiency.value
                if hasattr(self.information_sufficiency, "value")
                else str(self.information_sufficiency)
            ),
            "recent_prediction_success_rate": round(self.recent_prediction_success_rate, 3),
            "recent_prediction_error_rate": round(self.recent_prediction_error_rate, 3),
            "repeated_failure_count": self.repeated_failure_count,
            "cognitive_conflict_state": self.cognitive_conflict_state,
            "need_for_reassessment": self.need_for_reassessment,
            "last_reassessment_reason": self.last_reassessment_reason,
            "current_cognitive_load_estimate": round(self.current_cognitive_load_estimate, 3),
            "timestamp": round(self.timestamp, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MetacognitiveState:
        info_suff_val = data.get("information_sufficiency", InformationSufficiency.UNKNOWN.value)
        if isinstance(info_suff_val, str):
            try:
                info_suff_enum = InformationSufficiency(info_suff_val)
            except ValueError:
                info_suff_enum = InformationSufficiency.UNKNOWN
        else:
            info_suff_enum = info_suff_val

        state = cls(
            cognitive_status=data.get("cognitive_status", "NORMAL"),
            current_strategy_id=data.get("current_strategy_id"),
            strategy_confidence=float(data.get("strategy_confidence", 0.7)),
            knowledge_confidence=float(data.get("knowledge_confidence", 0.7)),
            uncertainty_level=float(data.get("uncertainty_level", 0.3)),
            information_sufficiency=info_suff_enum,
            recent_prediction_success_rate=float(data.get("recent_prediction_success_rate", 1.0)),
            recent_prediction_error_rate=float(data.get("recent_prediction_error_rate", 0.0)),
            repeated_failure_count=int(data.get("repeated_failure_count", 0)),
            cognitive_conflict_state=data.get("cognitive_conflict_state", "NONE"),
            need_for_reassessment=bool(data.get("need_for_reassessment", False)),
            last_reassessment_reason=data.get("last_reassessment_reason", ""),
            current_cognitive_load_estimate=float(data.get("current_cognitive_load_estimate", 0.2)),
            timestamp=float(data.get("timestamp", time.time())),
        )
        state.clamp()
        return state


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
    metacognitive_state: Optional[Dict[str, Any]] = None

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
            "metacognitive_state": self.metacognitive_state,
        }
