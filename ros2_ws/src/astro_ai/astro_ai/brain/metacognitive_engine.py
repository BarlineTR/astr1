"""ASTRO V1 — Metacognitive Control & Reflective Cognition Engine.

Governs ASTRO's internal meta-level cognitive monitoring:
  - Strategy tracking and empirical performance evaluation
  - Cognitive conflict detection (goal vs safety, confidence vs performance)
  - Information sufficiency assessment (SUFFICIENT, INSUFFICIENT, STALE, CONFLICTING)
  - Confidence calibration analysis (WELL_CALIBRATED, OVERCONFIDENT, UNDERCONFIDENT)
  - Rate-limited, bounded reassessment triggers
  - Emission of internal CognitiveDecision intents (STRICTLY != ActionIntent)

ARCHITECTURAL INVARIANTS:
  1. DETERMINISTIC & BOUNDED: Pure Python calculations, zero LLMs in the loop, clamped metrics.
  2. NO MOTOR CONTROL: CognitiveDecision represents internal cognitive processing, NOT ActionIntent.
  3. READ/ASSESSMENT LAYER: MetacognitiveState evaluates cognitive health without owning StateMachine.
  4. NO UNBOUNDED GROWTH: Uses bounded collections for recent outcomes and conflict histories.
"""

from __future__ import annotations

from collections import deque
import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from astro_ai.contracts.consciousness_types import (
    CognitiveConflict,
    CognitiveDecision,
    CognitiveDecisionType,
    CognitiveStrategy,
    Goal,
    GoalType,
    InformationSufficiency,
    MetacognitiveState,
    StrategyStatus,
)

_LOG = logging.getLogger(__name__)

# =============================================================================
# Centralized Configurable Constants
# =============================================================================
DEFAULT_REPEATED_FAILURE_THRESHOLD: int = 3
DEFAULT_REASSESSMENT_COOLDOWN_SECONDS: float = 2.0
DEFAULT_HIGH_CONFIDENCE_THRESHOLD: float = 0.70
DEFAULT_LOW_CONFIDENCE_THRESHOLD: float = 0.40
DEFAULT_HIGH_ERROR_RATE_THRESHOLD: float = 0.50
DEFAULT_HIGH_SUCCESS_RATE_THRESHOLD: float = 0.80
DEFAULT_STALE_PERCEPTION_SECONDS: float = 2.0
DEFAULT_CRITICAL_PROXIMITY_M: float = 0.50
DEFAULT_HIGH_UNCERTAINTY_THRESHOLD: float = 0.75
DEFAULT_HISTORY_WINDOW_SIZE: int = 20


class MetacognitiveEngine:
    """Thread-safe engine for deterministic metacognitive monitoring and control."""

    def __init__(
        self,
        repeated_failure_threshold: int = DEFAULT_REPEATED_FAILURE_THRESHOLD,
        reassessment_cooldown_s: float = DEFAULT_REASSESSMENT_COOLDOWN_SECONDS,
        history_window_size: int = DEFAULT_HISTORY_WINDOW_SIZE,
    ):
        self._lock = threading.RLock()
        self.repeated_failure_threshold = max(1, int(repeated_failure_threshold))
        self.reassessment_cooldown_s = max(0.5, float(reassessment_cooldown_s))

        # Active & registered strategies
        self._strategies: Dict[str, CognitiveStrategy] = {}
        self._active_strategy_id: Optional[str] = None

        # Bounded outcome window: deque of bool (True = matched, False = mismatch)
        self._recent_outcomes: deque[bool] = deque(maxlen=max(5, int(history_window_size)))
        self._consecutive_failures: int = 0

        # Active conflicts (bounded list)
        self._active_conflicts: List[CognitiveConflict] = []

        # Reassessment tracking
        self._last_reassessment_time: float = 0.0
        self._last_reassessment_reason: str = ""

        # Default initial state
        self._current_state = MetacognitiveState()

    # -------------------------------------------------------------------------
    # Strategy Management
    # -------------------------------------------------------------------------

    def register_strategy(self, strategy: CognitiveStrategy) -> None:
        """Registers a cognitive strategy."""
        with self._lock:
            self._strategies[strategy.strategy_id] = strategy
            if self._active_strategy_id is None:
                self._active_strategy_id = strategy.strategy_id
                self._current_state.current_strategy_id = strategy.strategy_id

    def set_active_strategy(
        self, strategy_id: str, rationale: str = ""
    ) -> Optional[CognitiveStrategy]:
        """Sets the currently active cognitive strategy."""
        with self._lock:
            if strategy_id in self._strategies:
                strat = self._strategies[strategy_id]
                strat.status = StrategyStatus.ACTIVE
                strat.last_used = time.time()
                if rationale:
                    strat.rationale = rationale
                self._active_strategy_id = strategy_id
                self._current_state.current_strategy_id = strategy_id
                self._current_state.strategy_confidence = strat.confidence
                return strat
            return None

    def get_active_strategy(self) -> Optional[CognitiveStrategy]:
        """Returns the currently active cognitive strategy if any."""
        with self._lock:
            if self._active_strategy_id:
                return self._strategies.get(self._active_strategy_id)
            return None

    def get_strategy(self, strategy_id: str) -> Optional[CognitiveStrategy]:
        """Retrieves a strategy by its ID."""
        with self._lock:
            return self._strategies.get(strategy_id)

    def get_all_strategies(self) -> List[CognitiveStrategy]:
        """Retrieves all registered strategies."""
        with self._lock:
            return list(self._strategies.values())

    def record_outcome_for_strategy(
        self,
        matched: bool = True,
        strategy_id: Optional[str] = None,
        success: Optional[bool] = None,
        prediction_error: Optional[Any] = None,
        confidence: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        """Records a prediction outcome and updates strategy metrics."""
        outcome = matched if success is None else success
        with self._lock:
            self._recent_outcomes.append(bool(outcome))
            if outcome:
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1

            target_id = strategy_id or self._active_strategy_id
            if target_id and target_id in self._strategies:
                strat = self._strategies[target_id]
                strat.record_outcome(outcome)

            # Synchronize rolling metrics into current state snapshot
            self._current_state.repeated_failure_count = self._consecutive_failures
            self._current_state.recent_prediction_success_rate = self.get_recent_success_rate()
            self._current_state.recent_prediction_error_rate = self.get_recent_error_rate()

    # -------------------------------------------------------------------------
    # Strategy Performance Metrics
    # -------------------------------------------------------------------------

    def get_recent_success_rate(self) -> float:
        """Calculates prediction success rate in the recent bounded window [0.0, 1.0]."""
        with self._lock:
            if not self._recent_outcomes:
                return 1.0
            return sum(1 for m in self._recent_outcomes if m) / float(len(self._recent_outcomes))

    def get_recent_error_rate(self) -> float:
        """Calculates prediction error rate in the recent bounded window [0.0, 1.0]."""
        with self._lock:
            if not self._recent_outcomes:
                return 0.0
            return sum(1 for m in self._recent_outcomes if not m) / float(len(self._recent_outcomes))

    @property
    def repeated_failure_count(self) -> int:
        with self._lock:
            return self._consecutive_failures

    # -------------------------------------------------------------------------
    # Information Sufficiency Assessment
    # -------------------------------------------------------------------------

    def assess_information_sufficiency(
        self,
        active_goal: Optional[Goal] = None,
        perception_data: Optional[Dict[str, Any]] = None,
        uncertainty: float = 0.3,
        now: Optional[float] = None,
    ) -> InformationSufficiency:
        """Evaluates whether available perception and epistemic certainty suffice for active pursuit."""
        with self._lock:
            ts = time.time() if now is None else now
            perc = perception_data or {}

            # 1. Staleness check: if perception timestamp is older than threshold
            last_ts = perc.get("timestamp") or perc.get("last_sensor_update_ts")
            if last_ts is not None and (ts - float(last_ts)) > DEFAULT_STALE_PERCEPTION_SECONDS:
                return InformationSufficiency.STALE

            # 2. Epistemic uncertainty check
            if uncertainty >= DEFAULT_HIGH_UNCERTAINTY_THRESHOLD:
                if perc.get("conflicting_signals", False):
                    return InformationSufficiency.CONFLICTING
                return InformationSufficiency.INSUFFICIENT

            # 3. Goal-specific information requirements
            if active_goal is not None:
                if active_goal.goal_type == GoalType.SOCIAL:
                    # Social goals require a detectable or focused person
                    has_person = (
                        perc.get("active_target_id") is not None
                        or perc.get("focused_person_id") is not None
                        or len(perc.get("people", [])) > 0
                        or perc.get("person_detected", False)
                    )
                    if not has_person:
                        return InformationSufficiency.INSUFFICIENT

                    target_pid = (
                        active_goal.metadata.get("target_person_id")
                        if hasattr(active_goal, "metadata") and isinstance(active_goal.metadata, dict)
                        else None
                    )
                    if target_pid:
                        people = perc.get("people", [])
                        pids = [
                            p.get("person_id") if isinstance(p, dict) else getattr(p, "person_id", None)
                            for p in people
                        ]
                        if target_pid not in pids and perc.get("active_target_id") != target_pid:
                            return InformationSufficiency.INSUFFICIENT

            if not perc:
                return InformationSufficiency.UNKNOWN

            return InformationSufficiency.SUFFICIENT

    # -------------------------------------------------------------------------
    # Cognitive Conflict Detection
    # -------------------------------------------------------------------------

    def detect_conflicts(
        self,
        active_goal: Optional[Goal] = None,
        perception_data: Optional[Dict[str, Any]] = None,
        confidence: float = 0.7,
        uncertainty: float = 0.3,
        now: Optional[float] = None,
    ) -> List[CognitiveConflict]:
        """Detects contradictions between goals, safety constraints, confidence, and empirical data."""
        with self._lock:
            ts = time.time() if now is None else now
            conflicts: List[CognitiveConflict] = []
            perc = perception_data or {}

            # Conflict 1: GOAL_SAFETY_CONFLICT
            front_m = perc.get("min_front_distance_m")
            if front_m is None and "environment" in perc:
                front_m = perc["environment"].get("front_clearance_m")

            if (
                front_m is not None
                and float(front_m) < DEFAULT_CRITICAL_PROXIMITY_M
                and active_goal is not None
                and active_goal.goal_type != GoalType.SAFETY
            ):
                conflicts.append(
                    CognitiveConflict(
                        conflict_id=f"conf_safety_{uuid.uuid4().hex[:6]}",
                        conflict_type="GOAL_SAFETY_CONFLICT",
                        severity=0.9,
                        involved_goal_ids=[active_goal.goal_id],
                        evidence={"front_clearance_m": float(front_m), "threshold_m": DEFAULT_CRITICAL_PROXIMITY_M},
                        detected_at=ts,
                        resolution_notes="Active task goal conflicts with close-proximity obstacle clearance",
                    )
                )

            # Conflict 2: CONFIDENCE_PERFORMANCE_MISMATCH (Overconfidence)
            if confidence >= DEFAULT_HIGH_CONFIDENCE_THRESHOLD and self._consecutive_failures >= 2:
                conflicts.append(
                    CognitiveConflict(
                        conflict_id=f"conf_calib_{uuid.uuid4().hex[:6]}",
                        conflict_type="CONFIDENCE_PERFORMANCE_MISMATCH",
                        severity=0.7,
                        involved_strategy_ids=[self._active_strategy_id] if self._active_strategy_id else [],
                        evidence={
                            "confidence": round(confidence, 3),
                            "consecutive_failures": self._consecutive_failures,
                            "error_rate": round(self.get_recent_error_rate(), 3),
                        },
                        detected_at=ts,
                        resolution_notes="High epistemic confidence contradicts empirical repeated prediction mismatches",
                    )
                )

            # Conflict 3: STRATEGY_PERSISTENCE_FAILURE
            active_strat = self.get_active_strategy()
            if (
                active_strat is not None
                and (
                    self._consecutive_failures >= self.repeated_failure_threshold
                    or (active_strat.failure_count >= 3 and active_strat.get_success_rate() < 0.4)
                )
            ):
                conflicts.append(
                    CognitiveConflict(
                        conflict_id=f"conf_strat_{uuid.uuid4().hex[:6]}",
                        conflict_type="STRATEGY_PERSISTENCE_FAILURE",
                        severity=0.8,
                        involved_strategy_ids=[active_strat.strategy_id],
                        evidence={
                            "strategy_id": active_strat.strategy_id,
                            "consecutive_failures": self._consecutive_failures,
                            "success_rate": round(active_strat.get_success_rate(), 3),
                        },
                        detected_at=ts,
                        resolution_notes="Active strategy persisted despite meeting repeated failure criteria",
                    )
                )

            self._active_conflicts = conflicts[:10]  # Bounded storage
            return list(self._active_conflicts)

    # -------------------------------------------------------------------------
    # Confidence Calibration Analysis
    # -------------------------------------------------------------------------

    def get_confidence_calibration(self, confidence: float) -> str:
        """Determines calibration category comparing confidence against empirical performance."""
        with self._lock:
            err_rate = self.get_recent_error_rate()
            succ_rate = self.get_recent_success_rate()

            if confidence >= DEFAULT_HIGH_CONFIDENCE_THRESHOLD and err_rate >= DEFAULT_HIGH_ERROR_RATE_THRESHOLD:
                return "OVERCONFIDENT"
            if confidence <= DEFAULT_LOW_CONFIDENCE_THRESHOLD and succ_rate >= DEFAULT_HIGH_SUCCESS_RATE_THRESHOLD:
                return "UNDERCONFIDENT"
            return "WELL_CALIBRATED"

    # -------------------------------------------------------------------------
    # Reassessment Triggers & Cooldown
    # -------------------------------------------------------------------------

    def trigger_reassessment(
        self, reason: str, now: Optional[float] = None
    ) -> Tuple[bool, Optional[CognitiveDecision]]:
        """Evaluates and triggers a rate-limited cognitive reassessment."""
        with self._lock:
            ts = time.time() if now is None else now
            time_since_last = ts - self._last_reassessment_time

            if self._last_reassessment_time > 0 and time_since_last < self.reassessment_cooldown_s:
                # Suppressed by mandatory cooldown
                return False, None

            self._last_reassessment_time = ts
            self._last_reassessment_reason = str(reason)

            decision = CognitiveDecision(
                decision_id=f"dec_reassess_{uuid.uuid4().hex[:8]}",
                decision_type=CognitiveDecisionType.REASSESS,
                reason=str(reason),
                target_strategy_id=self._active_strategy_id,
                timestamp=ts,
            )
            return True, decision

    # -------------------------------------------------------------------------
    # Comprehensive Metacognitive State Evaluation
    # -------------------------------------------------------------------------

    def evaluate_metacognitive_state(
        self,
        active_goal: Optional[Goal] = None,
        perception_data: Optional[Dict[str, Any]] = None,
        confidence: float = 0.7,
        uncertainty: float = 0.3,
        now: Optional[float] = None,
    ) -> Tuple[MetacognitiveState, Optional[CognitiveDecision]]:
        """Evaluates cognitive health, conflicts, and policy to produce MetacognitiveState and CognitiveDecision."""
        with self._lock:
            ts = time.time() if now is None else now

            # 1. Assess information sufficiency
            info_sufficiency = self.assess_information_sufficiency(
                active_goal=active_goal,
                perception_data=perception_data,
                uncertainty=uncertainty,
                now=ts,
            )

            # 2. Detect conflicts
            conflicts = self.detect_conflicts(
                active_goal=active_goal,
                perception_data=perception_data,
                confidence=confidence,
                uncertainty=uncertainty,
                now=ts,
            )

            # 3. Evaluate need for reassessment
            need_reassessment = False
            reassess_reason = ""
            decision: Optional[CognitiveDecision] = None

            if conflicts:
                critical_conflict = any(c.severity >= 0.8 for c in conflicts)
                if critical_conflict:
                    need_reassessment = True
                    reassess_reason = f"critical_conflict:{conflicts[0].conflict_type}"
                    triggered, dec = self.trigger_reassessment(reassess_reason, now=ts)
                    if triggered:
                        decision = dec
                    elif active_goal and conflicts[0].conflict_type == "GOAL_SAFETY_CONFLICT":
                        decision = CognitiveDecision(
                            decision_id=f"dec_goal_{uuid.uuid4().hex[:8]}",
                            decision_type=CognitiveDecisionType.REEVALUATE_GOAL,
                            reason="safety_proximity_preempts_goal",
                            target_goal_id=active_goal.goal_id,
                            timestamp=ts,
                        )

            elif self._consecutive_failures >= self.repeated_failure_threshold:
                need_reassessment = True
                reassess_reason = f"repeated_prediction_failures:{self._consecutive_failures}"
                triggered, dec = self.trigger_reassessment(reassess_reason, now=ts)
                if triggered:
                    decision = dec
                else:
                    decision = CognitiveDecision(
                        decision_id=f"dec_strat_{uuid.uuid4().hex[:8]}",
                        decision_type=CognitiveDecisionType.REVIEW_STRATEGY,
                        reason="repeated_failures_on_strategy",
                        target_strategy_id=self._active_strategy_id,
                        timestamp=ts,
                    )

            elif info_sufficiency in (InformationSufficiency.INSUFFICIENT, InformationSufficiency.STALE):
                decision = CognitiveDecision(
                    decision_id=f"dec_info_{uuid.uuid4().hex[:8]}",
                    decision_type=CognitiveDecisionType.SEEK_INFORMATION,
                    reason=f"information_sufficiency_{info_sufficiency.value}",
                    target_goal_id=active_goal.goal_id if active_goal else None,
                    timestamp=ts,
                )

            else:
                decision = CognitiveDecision(
                    decision_id=f"dec_cont_{uuid.uuid4().hex[:8]}",
                    decision_type=CognitiveDecisionType.CONTINUE,
                    reason="normal_execution_parameters",
                    target_goal_id=active_goal.goal_id if active_goal else None,
                    timestamp=ts,
                )

            # 4. Status designation
            if conflicts:
                status = "CONFLICTED"
            elif need_reassessment:
                status = "REASSESSING"
            elif info_sufficiency == InformationSufficiency.INSUFFICIENT:
                status = "DEGRADED"
            else:
                status = "NORMAL"

            active_strat = self.get_active_strategy()
            strat_conf = active_strat.confidence if active_strat else 0.7

            state = MetacognitiveState(
                cognitive_status=status,
                current_strategy_id=self._active_strategy_id,
                strategy_confidence=round(strat_conf, 3),
                knowledge_confidence=round(confidence, 3),
                uncertainty_level=round(uncertainty, 3),
                information_sufficiency=info_sufficiency,
                recent_prediction_success_rate=round(self.get_recent_success_rate(), 3),
                recent_prediction_error_rate=round(self.get_recent_error_rate(), 3),
                repeated_failure_count=self._consecutive_failures,
                cognitive_conflict_state="DETECTED" if conflicts else "NONE",
                need_for_reassessment=need_reassessment,
                last_reassessment_reason=reassess_reason or self._last_reassessment_reason,
                current_cognitive_load_estimate=min(1.0, 0.2 + (len(conflicts) * 0.2) + (self._consecutive_failures * 0.1)),
                timestamp=ts,
            )
            state.clamp()
            self._current_state = state
            return state, decision

    @property
    def current_state(self) -> MetacognitiveState:
        with self._lock:
            return self._current_state

    def reset(self) -> None:
        """Resets all strategy records, failure counters, and conflict logs."""
        with self._lock:
            self._strategies.clear()
            self._active_strategy_id = None
            self._recent_outcomes.clear()
            self._consecutive_failures = 0
            self._active_conflicts.clear()
            self._last_reassessment_time = 0.0
            self._last_reassessment_reason = ""
            self._current_state = MetacognitiveState()
