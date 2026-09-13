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

from astro_ai.brain.cognitive_event_bus import CognitiveEventBus
from astro_ai.brain.world_model import WorldModel, WorldStateSnapshot
from astro_ai.contracts.consciousness_types import CognitiveEvent, CognitiveEventType


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


class CognitiveLoop:
    """Orchestrates the continuous non-blocking cognitive cycle of ASTRO."""

    def __init__(
        self,
        world_model: Optional[WorldModel] = None,
        event_bus: Optional[CognitiveEventBus] = None,
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

        self.target_hz = max(1.0, min(50.0, float(target_hz)))
        self.target_period_s = 1.0 / self.target_hz

        self.cycle_count = 0
        self.last_cycle_duration_ms = 0.0
        self.last_cycle_timestamp = 0.0
        self.total_execution_time_ms = 0.0

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
            # 2. EVENT: Process cognitive event bus & record significant changes
            # -----------------------------------------------------------------
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

            # -----------------------------------------------------------------
            # [Phase 3 Extension Point: Cognitive Attention & Workspace Assembly]
            # -----------------------------------------------------------------

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
            self.world_model.clear_temporal_history()
            self.event_bus.clear()

    @property
    def average_cycle_duration_ms(self) -> float:
        """Returns the mean execution duration per cycle in milliseconds."""
        with self._lock:
            if self.cycle_count == 0:
                return 0.0
            return self.total_execution_time_ms / self.cycle_count
