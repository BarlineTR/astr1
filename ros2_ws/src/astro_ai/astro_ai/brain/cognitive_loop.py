"""ASTRO V1 — Core Continuous Cognitive Loop.

Pure Python, ROS2-independent substrate orchestrating the periodic cognitive cycle:
  1. PERCEIVE               — Ingests perception inputs into WorldModel without blocking
  2. EVENT                  — Evaluates unprocessed events from CognitiveEventBus
  3. WORLD TEMPORAL UPDATE  — Commits bounded temporal snapshot to WorldModel ring buffer
  4. CYCLE RESULT & METRICS — Evaluates loop timing, non-blocking metrics, and yields result

Subsequent phases extend this loop via dedicated extension points (SelfState, Workspace,
Goals, Prediction/Outcome).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any, Dict, List, Optional

from astro_ai.brain.affective_state import AffectiveStateManager
from astro_ai.brain.cognitive_continuity import CognitiveContinuityTracker
from astro_ai.brain.cognitive_event_bus import CognitiveEventBus
from astro_ai.brain.perception_event_detector import PerceptionEventDetector
from astro_ai.brain.prediction_engine import PredictionEngine
from astro_ai.brain.world_model import WorldModel, WorldStateSnapshot
from astro_ai.contracts.consciousness_types import (
    CognitiveContext,
    CognitiveEvent,
    CognitiveEventType,
    PredictionError,
    RobotAffectiveState,
    SelfState,
)


@dataclass
class CognitiveCycleResult:
    """Snapshot result emitted at the end of each cognitive loop cycle."""

    cycle_index: int
    timestamp: float
    duration_ms: float
    world_snapshot: WorldStateSnapshot
    unprocessed_event_count: int
    temporal_history_len: int
    active_people_count: int
    has_active_speaker: bool
    events_drained: List[str] = field(default_factory=list)
    self_state: Optional[SelfState] = None
    affective_state: Optional[RobotAffectiveState] = None
    cognitive_context: Optional[CognitiveContext] = None
    prediction_errors: List[PredictionError] = field(default_factory=list)


class CognitiveLoop:
    """Orchestrates the continuous non-blocking cognitive cycle of ASTRO."""

    def __init__(
        self,
        world_model: Optional[WorldModel] = None,
        event_bus: Optional[CognitiveEventBus] = None,
        event_detector: Optional[PerceptionEventDetector] = None,
        self_state: Optional[SelfState] = None,
        affective_manager: Optional[AffectiveStateManager] = None,
        prediction_engine: Optional[PredictionEngine] = None,
        continuity_tracker: Optional[CognitiveContinuityTracker] = None,
        target_hz: float = 10.0,
        temporal_history_size: int = 50,
    ):
        self._lock = threading.RLock()
        self.world_model = (
            world_model
            if world_model is not None
            else WorldModel(temporal_history_size=temporal_history_size)
        )
        self.event_bus = (
            event_bus
            if event_bus is not None
            else CognitiveEventBus(max_capacity=250)
        )
        self.event_detector = (
            event_detector
            if event_detector is not None
            else PerceptionEventDetector()
        )
        self.self_state = (
            self_state
            if self_state is not None
            else SelfState()
        )
        self.affective_manager = (
            affective_manager
            if affective_manager is not None
            else AffectiveStateManager()
        )
        self.prediction_engine = (
            prediction_engine
            if prediction_engine is not None
            else PredictionEngine()
        )
        self.continuity_tracker = (
            continuity_tracker
            if continuity_tracker is not None
            else CognitiveContinuityTracker()
        )

        self.target_hz = max(1.0, min(50.0, float(target_hz)))
        self.target_period_s = 1.0 / self.target_hz

        self.cycle_count = 0
        self.last_cycle_duration_ms = 0.0
        self.last_cycle_timestamp = 0.0
        self.total_execution_time_ms = 0.0
        self._last_focused_person: Optional[str] = None

        # Cached latest perception state for standalone/async feeds
        self._cached_perception: Dict[str, Any] = {}

    def update_perception(self, perception_data: Dict[str, Any]) -> None:
        """Thread-safe update of cached perception inputs."""
        with self._lock:
            self._cached_perception.update(perception_data or {})

    def step(
        self, perception_input: Optional[Dict[str, Any]] = None
    ) -> CognitiveCycleResult:
        """Executes one single deterministic cognitive cycle.

        Args:
            perception_input: Optional immediate perception feed. If None,
                              uses previously cached perception state.

        Returns:
            CognitiveCycleResult containing execution metrics and state snapshot.
        """
        t_start = time.perf_counter()
        now = time.time()

        with self._lock:
            self.cycle_count += 1
            self.last_cycle_timestamp = now

            # -----------------------------------------------------------------
            # 1. PERCEIVE: Ingest sensory inputs into WorldModel
            # -----------------------------------------------------------------
            active_perception = (
                dict(perception_input)
                if perception_input is not None
                else dict(self._cached_perception)
            )

            # Synchronize people
            if "people" in active_perception and isinstance(active_perception["people"], list):
                self.world_model.update_people(active_perception["people"])

            # Synchronize robot state
            if "robot_state" in active_perception and isinstance(active_perception["robot_state"], dict):
                self.world_model.update_robot_state(**active_perception["robot_state"])

            # Synchronize environment
            if "environment" in active_perception and isinstance(active_perception["environment"], dict):
                self.world_model.update_environment(**active_perception["environment"])

            # Synchronize conversation state
            if "conversation_state" in active_perception and isinstance(active_perception["conversation_state"], dict):
                self.world_model.update_conversation_state(**active_perception["conversation_state"])

            # -----------------------------------------------------------------
            # 2. EVENT: Detect perception transitions & process event bus
            # -----------------------------------------------------------------
            new_events = self.event_detector.detect_transitions(active_perception, timestamp=now)
            for evt in new_events:
                self.event_bus.publish(evt)

            unprocessed_events = self.event_bus.get_unprocessed_events()
            drained_event_ids: List[str] = []

            if unprocessed_events:
                for evt in unprocessed_events:
                    # Mirror high-salience events into world model recent events
                    if evt.salience >= 0.5:
                        desc = f"{evt.event_type.value}: {evt.source}"
                        if "person_id" in evt.data:
                            desc += f" (person={evt.data['person_id']})"
                        self.world_model.record_event(desc)
                    drained_event_ids.append(evt.event_id)

                self.event_bus.mark_processed(drained_event_ids)

            # -----------------------------------------------------------------
            # [Phase 2 Extension Point: SelfState & Affective Modulator Update]
            # -----------------------------------------------------------------
            # 1. Update SelfState dynamic physical and operational state
            self.self_state.update_from_perception(active_perception)
            self.self_state.timestamp = now

            # 2. Modulate AffectiveState from events processed this cycle
            if unprocessed_events:
                for evt in unprocessed_events:
                    self.affective_manager.update_from_event(evt)

            # 3. Modulate AffectiveState from active perception features
            self.affective_manager.update_from_perception(active_perception)

            # 4. Perform step decay on affective modulators towards baselines
            self.affective_manager.step_decay(dt=self.target_period_s)

            # 5. Synchronize confidence and uncertainty into SelfState
            self.self_state.overall_confidence = self.affective_manager.state.confidence
            self.self_state.uncertainty_level = self.affective_manager.state.uncertainty

            # -----------------------------------------------------------------
            # [Phase 3 Extension Point: Prediction Expirations & Continuity Tracking]
            # -----------------------------------------------------------------
            # 1. Check expired predictions
            pred_errors: List[PredictionError] = []
            expired_errors = self.prediction_engine.check_expirations(now=now)
            for err in expired_errors:
                self.affective_manager.update_confidence(err.confidence_impact)
                self.affective_manager.update_uncertainty(err.uncertainty_impact)
                self.affective_manager.modulate_frustration(0.1)
                self.continuity_tracker.record_transition(
                    transition_type="PREDICTION_EXPIRED",
                    previous_value=err.expectation_id,
                    new_value="EXPIRED",
                    cause="timeout",
                    metadata=err.to_dict(),
                )
                pred_errors.append(err)

            # 2. Check focus change
            current_focus = self.self_state.focused_person_id
            if current_focus != self._last_focused_person:
                self.continuity_tracker.record_transition(
                    transition_type="FOCUS_CHANGE",
                    previous_value=self._last_focused_person,
                    new_value=current_focus,
                    cause="perception_update",
                )
                self._last_focused_person = current_focus

            # 3. Assemble CognitiveContext integration/read snapshot
            events_summary = [
                f"{evt.event_type.value}: {evt.source}"
                for evt in (unprocessed_events or [])
            ]
            cog_context = CognitiveContext(
                timestamp=now,
                activity=self.self_state.get_current_activity(),
                operational_state=(
                    self.self_state.operational_state.value
                    if hasattr(self.self_state.operational_state, "value")
                    else str(self.self_state.operational_state)
                ),
                focused_person_id=current_focus,
                active_goal=self.self_state.current_goal.to_dict() if self.self_state.current_goal else None,
                active_prediction=self.self_state.active_prediction.to_dict() if self.self_state.active_prediction else None,
                confidence=round(self.self_state.overall_confidence, 3),
                uncertainty=round(self.self_state.uncertainty_level, 3),
                affective_state=self.affective_manager.state.to_dict(),
                degraded_capabilities=sorted(list(self.self_state.degraded_capabilities)),
                identity={
                    "name": "Astro",
                    "creator": "Baran",
                    "location": "Bitlis / Ahlat",
                    "version": "ASTRO V1 (Cognitive Embodied Social Robot)",
                },
                capabilities=[],
                recent_transitions=self.continuity_tracker.to_list()[-10:],
                recent_events_summary=events_summary[-10:],
                perception_summary=dict(active_perception),
                self_state_snapshot=self.self_state.to_dict(),
            )

            # -----------------------------------------------------------------
            # [Phase 4 Extension Point: Goal Management & Action Intent Decision]
            # -----------------------------------------------------------------

            # -----------------------------------------------------------------
            # [Phase 5 Extension Point: Action Prediction & Outcome Evaluation]
            # -----------------------------------------------------------------

            # -----------------------------------------------------------------
            # 3. WORLD TEMPORAL UPDATE: Commit ring-buffer snapshot
            # -----------------------------------------------------------------
            world_snap = self.world_model.commit_temporal_snapshot()

            # -----------------------------------------------------------------
            # 4. CYCLE RESULT & TIMING: Evaluate cycle performance
            # -----------------------------------------------------------------
            duration_ms = (time.perf_counter() - t_start) * 1000.0
            self.last_cycle_duration_ms = duration_ms
            self.total_execution_time_ms += duration_ms
            self.self_state.cycle_time_ms = duration_ms

            active_people = [p for p in world_snap.people if getattr(p, "is_present", True)]
            has_speaker = world_snap.active_speaker is not None

            return CognitiveCycleResult(
                cycle_index=self.cycle_count,
                timestamp=now,
                duration_ms=duration_ms,
                world_snapshot=world_snap,
                unprocessed_event_count=len(self.event_bus.get_unprocessed_events()),
                temporal_history_len=self.world_model.temporal_history_len,
                active_people_count=len(active_people),
                has_active_speaker=has_speaker,
                events_drained=drained_event_ids,
                self_state=self.self_state,
                affective_state=self.affective_manager.state,
                cognitive_context=cog_context,
                prediction_errors=pred_errors,
            )

    def run_consecutive_steps(
        self,
        count: int,
        perception_inputs: Optional[List[Optional[Dict[str, Any]]]] = None,
    ) -> List[CognitiveCycleResult]:
        """Executes N consecutive cycles deterministically.

        Ideal for synthetic perception replay and offline benchmarks.
        """
        results: List[CognitiveCycleResult] = []
        for i in range(count):
            p_in = (
                perception_inputs[i]
                if perception_inputs and i < len(perception_inputs)
                else None
            )
            res = self.step(p_in)
            results.append(res)
        return results

    def reset(self) -> None:
        """Resets cycle counter, world model temporal history, and event bus."""
        with self._lock:
            self.cycle_count = 0
            self.last_cycle_duration_ms = 0.0
            self.last_cycle_timestamp = 0.0
            self.total_execution_time_ms = 0.0
            self._cached_perception.clear()
            self.event_detector.reset()
            self.world_model.clear_temporal_history()
            self.event_bus.clear()
            self.self_state = SelfState()
            self.affective_manager.reset()
            self.prediction_engine.clear()
            self.continuity_tracker.clear()
            self._last_focused_person = None

    @property
    def average_cycle_duration_ms(self) -> float:
        """Returns the mean execution duration per cycle in milliseconds."""
        with self._lock:
            if self.cycle_count == 0:
                return 0.0
            return self.total_execution_time_ms / self.cycle_count
