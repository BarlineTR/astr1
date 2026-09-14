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
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

_LOG = logging.getLogger(__name__)

from astro_ai.brain.affective_state import AffectiveStateManager
from astro_ai.brain.behavior_engine import BehaviorEngine
from astro_ai.brain.cognitive_continuity import CognitiveContinuityTracker
from astro_ai.brain.cognitive_event_bus import CognitiveEventBus
from astro_ai.brain.metacognitive_engine import MetacognitiveEngine
from astro_ai.brain.perception_event_detector import PerceptionEventDetector
from astro_ai.brain.prediction_engine import PredictionEngine
from astro_ai.brain.world_model import WorldModel, WorldStateSnapshot
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.behavior_types import (
    BehavioralIntent,
    behavior_intent_to_action_intent,
)
from astro_ai.contracts.consciousness_types import (
    ActionIntent,
    ActualOutcome,
    CognitiveContext,
    CognitiveDecision,
    CognitiveDecisionType,
    CognitiveEvent,
    CognitiveEventType,
    MetacognitiveState,
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
    metacognitive_state: Optional[MetacognitiveState] = None
    cognitive_decision: Optional[CognitiveDecision] = None
    behavioral_intent: Optional[BehavioralIntent] = None
    action_intent: Optional[ActionIntent] = None


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
        metacognitive_engine: Optional[MetacognitiveEngine] = None,
        behavior_engine: Optional[BehaviorEngine] = None,
        target_hz: float = 10.0,
        temporal_history_size: int = 50,
        on_telemetry: Optional[Callable[[str], None]] = None,
    ):
        self._lock = threading.RLock()
        self._on_telemetry = on_telemetry
        self._last_telemetry_sig: Optional[Tuple[Any, ...]] = None
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
        self.metacognitive_engine = (
            metacognitive_engine
            if metacognitive_engine is not None
            else MetacognitiveEngine()
        )
        self.behavior_engine = (
            behavior_engine
            if behavior_engine is not None
            else BehaviorEngine()
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

            # Synchronize people with lifecycle tracking
            if "people" in active_perception and isinstance(active_perception["people"], list):
                self.world_model.update_people(active_perception["people"], now=now)

            # Ingest active acoustic stimulus when VAD is active and DOA is reported
            if active_perception.get("vad") and "doa_deg" in active_perception:
                doa_val = float(active_perception["doa_deg"])
                has_acoustic = any(
                    getattr(p, "has_audio", False) and p.is_present
                    for p in self.world_model._people.values()
                )
                if not has_acoustic:
                    ac_entity = UnifiedPersonState(
                        person_id="acoustic_source",
                        distance_m=2.0,
                        azimuth_deg=doa_val,
                        is_present=True,
                        has_audio=True,
                        has_vision=False,
                        is_speaking=True,
                        entity_type="ACOUSTIC_ENTITY",
                    )
                    self.world_model.update_people([ac_entity], now=now)

            # Synchronize robot state
            if "robot_state" in active_perception and isinstance(active_perception["robot_state"], dict):
                self.world_model.update_robot_state(**active_perception["robot_state"])

            # Synchronize environment
            if "environment" in active_perception and isinstance(active_perception["environment"], dict):
                self.world_model.update_environment(**active_perception["environment"])

            # Synchronize conversation state
            if "conversation_state" in active_perception and isinstance(active_perception["conversation_state"], dict):
                self.world_model.update_conversation_state(**active_perception["conversation_state"])

            # Phase 6: Augment active perception with World Model situational intelligence
            world_conflicts = self.world_model.detect_conflicts()
            if world_conflicts:
                active_perception["world_conflicts"] = world_conflicts
                active_perception["conflicting_signals"] = True

            acoustic_cand = self.world_model.get_acoustic_attention_candidate()
            if acoustic_cand:
                active_perception["acoustic_attention_candidate"] = acoustic_cand

            curr_focus = self.self_state.focused_person_id
            if curr_focus and curr_focus in self.world_model._people:
                fp = self.world_model._people[curr_focus]
                if not fp.is_present and getattr(fp, "occlusion_duration_s", 0.0) >= 0:
                    active_perception["focused_person_occluded"] = True

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
                self.metacognitive_engine.record_outcome_for_strategy(
                    success=False,
                    prediction_error=err,
                    confidence=self.self_state.overall_confidence,
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

            # 3. [Phase 4 Extension Point: Metacognitive Evaluation & Reflective Control]
            prev_strat_id = self.metacognitive_engine.current_state.current_strategy_id
            meta_state, cog_decision = self.metacognitive_engine.evaluate_metacognitive_state(
                active_goal=self.self_state.current_goal,
                perception_data=active_perception,
                confidence=self.self_state.overall_confidence,
                uncertainty=self.self_state.uncertainty_level,
                now=now,
            )

            # Track transitions in cognitive continuity
            if meta_state.current_strategy_id != prev_strat_id and meta_state.current_strategy_id is not None:
                self.continuity_tracker.record_transition(
                    transition_type="STRATEGY_CHANGE",
                    previous_value=prev_strat_id,
                    new_value=meta_state.current_strategy_id,
                    cause="metacognitive_evaluation",
                )

            if meta_state.cognitive_conflict_state == "DETECTED":
                self.continuity_tracker.record_transition(
                    transition_type="CONFLICT_DETECTED",
                    previous_value="NONE",
                    new_value="DETECTED",
                    cause=meta_state.last_reassessment_reason or "conflict",
                    metadata={"load": meta_state.current_cognitive_load_estimate},
                )

            if meta_state.need_for_reassessment:
                self.continuity_tracker.record_transition(
                    transition_type="REASSESSMENT_TRIGGERED",
                    previous_value="NORMAL",
                    new_value="REASSESS",
                    cause=meta_state.last_reassessment_reason,
                )

            # Phase 6: Active Perception Attention Reallocation & Expectation Loop
            if (
                cog_decision
                and getattr(cog_decision, "decision_type", None) == CognitiveDecisionType.SEEK_INFORMATION
                and hasattr(cog_decision, "metadata")
                and cog_decision.metadata.get("stimulus_type") == "AUDIO"
            ):
                target_yaw = float(cog_decision.metadata.get("target_yaw_deg", 0.0))
                self.continuity_tracker.record_transition(
                    transition_type="ATTENTION_REALLOCATION",
                    previous_value=self.self_state.current_head_yaw_deg,
                    new_value=f"BEARING_{round(target_yaw, 1)}",
                    cause="active_perception_acoustic_attention",
                    metadata=cog_decision.metadata,
                )
                self.prediction_engine.create_perceptual_prediction(
                    prediction_type="EXPECT_FACE_AFTER_HEAD_ATTENTION",
                    target_id=str(cog_decision.metadata.get("entity_id", "acoustic_source")),
                    expected_state={"face_detected": True},
                    timeout_seconds=2.0,
                    now=now,
                )

            # Perceptual outcome verification for active expectations
            active_preds = self.prediction_engine.get_active_predictions()
            for p in active_preds:
                if p.action_id == "EXPECT_FACE_AFTER_HEAD_ATTENTION":
                    visual_people = [
                        per for per in self.world_model._people.values()
                        if per.is_present and getattr(per, "has_vision", False)
                    ]
                    if visual_people:
                        outcome = ActualOutcome(
                            outcome_id=f"out_face_{int(now * 1000)}",
                            expectation_id=p.prediction_id,
                            actual_state={"face_detected": True},
                            timestamp=now,
                        )
                        p_err = self.prediction_engine.evaluate_outcome(outcome, now=now)
                        pred_errors.append(p_err)
                        self.affective_manager.update_confidence(p_err.confidence_impact)
                        self.affective_manager.update_uncertainty(p_err.uncertainty_impact)

            # 4. Assemble CognitiveContext integration/read snapshot
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
                metacognitive_state=meta_state.to_dict(),
            )

            # -----------------------------------------------------------------
            # [Phase 7 Extension Point: Behavioral Intelligence & Action Mapping]
            # -----------------------------------------------------------------
            prev_beh_id = (
                self.behavior_engine.active_behavior.behavior_id
                if self.behavior_engine.active_behavior
                else None
            )
            beh_intent = self.behavior_engine.step(
                world_model=self.world_model,
                self_state=self.self_state,
                active_goal=self.self_state.current_goal,
                cognitive_decision=cog_decision,
                affective_state=self.affective_manager.state,
                social_phase=self.world_model._robot_state.get("social_phase"),
                now=now,
            )
            act_intent = behavior_intent_to_action_intent(beh_intent) if beh_intent else None

            if beh_intent and beh_intent.behavior_id != prev_beh_id:
                self.continuity_tracker.record_transition(
                    transition_type="BEHAVIOR_CHANGE",
                    previous_value=prev_beh_id,
                    new_value=beh_intent.behavior_type.value,
                    cause=beh_intent.reason or "behavior_selection",
                    metadata=beh_intent.to_dict(),
                )

            # -----------------------------------------------------------------
            # 5. WORLD TEMPORAL UPDATE: Commit ring-buffer snapshot
            # -----------------------------------------------------------------
            world_snap = self.world_model.commit_temporal_snapshot()

            # -----------------------------------------------------------------
            # 6. CYCLE RESULT & TIMING: Evaluate cycle performance
            # -----------------------------------------------------------------
            duration_ms = (time.perf_counter() - t_start) * 1000.0
            self.last_cycle_duration_ms = duration_ms
            self.total_execution_time_ms += duration_ms
            self.self_state.cycle_time_ms = duration_ms

            active_people = [p for p in world_snap.people if getattr(p, "is_present", True)]
            has_speaker = world_snap.active_speaker is not None

            result = CognitiveCycleResult(
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
                metacognitive_state=meta_state,
                cognitive_decision=cog_decision,
                behavioral_intent=beh_intent,
                action_intent=act_intent,
            )

            # Runtime Telemetry Evaluation (Transition-Driven, Anti-Spam)
            current_sig = (
                self.self_state.focused_person_id,
                cog_decision.decision_type.value if (cog_decision and hasattr(cog_decision.decision_type, "value")) else (cog_decision.decision_type if cog_decision else None),
                cog_decision.reason if cog_decision else None,
                beh_intent.behavior_type.value if (beh_intent and hasattr(beh_intent.behavior_type, "value")) else (beh_intent.behavior_type if beh_intent else None),
                beh_intent.reason if beh_intent else None,
                beh_intent.target_id if beh_intent else None,
                self.self_state.is_listening,
                self.self_state.is_speaking,
                world_snap.active_speaker.person_id if world_snap.active_speaker else None,
                len(active_people),
                meta_state.cognitive_conflict_state if meta_state else None,
                meta_state.information_sufficiency.value if (meta_state and hasattr(meta_state.information_sufficiency, "value")) else None,
            )

            if current_sig != self._last_telemetry_sig:
                self._last_telemetry_sig = current_sig
                telemetry_banner = self.format_runtime_telemetry(result)
                if self._on_telemetry is not None:
                    self._on_telemetry(telemetry_banner)
                else:
                    _LOG.info(telemetry_banner)

            return result

    def format_runtime_telemetry(self, result: CognitiveCycleResult) -> str:
        """Formats an INFO-level, human-readable runtime telemetry snapshot.

        Output fields:
          - focus
          - world model state
          - confidence
          - uncertainty
          - information sufficiency
          - cognitive decision
          - selected BehavioralIntent
          - behavior reason
          - related target
          Followed by deep structured trace for all 10 cognitive subsystems.
        """
        # 1. Focus
        focus = result.self_state.focused_person_id or "None"

        # 2. World Model State
        active_people = [p for p in (result.world_snapshot.people or []) if getattr(p, "is_present", True)]
        people_part = f"{len(active_people)} person" if len(active_people) == 1 else f"{len(active_people)} people"
        if active_people:
            names = [p.name for p in active_people if getattr(p, "name", None)]
            if names:
                people_part += f" ({', '.join(names[:2])})"
        if result.world_snapshot.active_speaker:
            spk = result.world_snapshot.active_speaker
            spk_name = getattr(spk, "name", None) or getattr(spk, "person_id", "speaker")
            speaker_part = f"speaker={spk_name}"
        else:
            speaker_part = "speaker=None"
        env = getattr(result.world_snapshot, "environment", {}) or {}
        clear_m = float(env.get("front_clearance_m", 5.0))
        clear_part = f"clear={clear_m:.1f}m"
        world_parts = [people_part, speaker_part, clear_part]
        if getattr(result.world_snapshot, "conflicts", None):
            world_parts.append(f"conflicts={len(result.world_snapshot.conflicts)}")
        world_desc = ", ".join(world_parts)

        # 3. Confidence & Uncertainty
        conf_str = f"{result.self_state.overall_confidence:.2f}"
        unc_str = f"{result.self_state.uncertainty_level:.2f}"

        # 4. Information Sufficiency & Metacognitive Status
        suff = "UNKNOWN"
        meta_status = "NORMAL"
        conflict_state = "NONE"
        if result.metacognitive_state:
            info_suff = getattr(result.metacognitive_state, "information_sufficiency", None)
            suff = info_suff.value if hasattr(info_suff, "value") else str(info_suff or "UNKNOWN")
            meta_status = getattr(result.metacognitive_state, "cognitive_status", "NORMAL")
            conflict_state = getattr(result.metacognitive_state, "cognitive_conflict_state", "NONE")

        # 5. Cognitive Decision
        dec_str = "NONE"
        if result.cognitive_decision:
            d_val = (
                result.cognitive_decision.decision_type.value
                if hasattr(result.cognitive_decision.decision_type, "value")
                else str(result.cognitive_decision.decision_type)
            )
            dec_str = d_val
            if result.cognitive_decision.reason:
                dec_str += f" ({result.cognitive_decision.reason})"

        # 6. Selected BehavioralIntent & Reason & Target
        intent_str = "NONE"
        reason_str = "none"
        priority_val = 0.5
        target_str = (
            result.behavioral_intent.target_id
            if (result.behavioral_intent and result.behavioral_intent.target_id)
            else (result.self_state.focused_person_id or "None")
        )
        if result.behavioral_intent:
            b_val = (
                result.behavioral_intent.behavior_type.value
                if hasattr(result.behavioral_intent.behavior_type, "value")
                else str(result.behavioral_intent.behavior_type)
            )
            intent_str = b_val
            reason_str = result.behavioral_intent.reason or "routine"
            priority_val = result.behavioral_intent.priority

        # Base banner (strictly preserves 100% backward compatibility with tests)
        banner = (
            f"🧠 [Cognition -> Behavior] "
            f"focus={focus} | "
            f"world={world_desc} | "
            f"conf={conf_str} unc={unc_str} suff={suff} | "
            f"decision={dec_str} | "
            f"intent={intent_str} | "
            f"reason={reason_str} | "
            f"target={target_str}"
        )

        # ---------------------------------------------------------------------
        # Deep Subsystem Cognitive Telemetry Trace (Phase 7 Runtime Audit)
        # ---------------------------------------------------------------------
        # 1. Perception
        events_str = ", ".join(result.events_drained) if result.events_drained else "none"
        vad_str = "ACTIVE" if result.self_state.is_listening else "idle"
        yaw_str = f"{result.self_state.current_head_yaw_deg:.1f}°"
        perc_line = f"  ├── PERCEPTION   : events=[{events_str}], vad={vad_str}, head_yaw={yaw_str}, clearance={clear_m:.2f}m"

        # 2. World Model
        people_detail_list = []
        for p in (result.world_snapshot.people or []):
            st = p.tracking_state.value if hasattr(p.tracking_state, "value") else str(p.tracking_state)
            p_desc = f"{p.person_id}({st}, {p.distance_m:.1f}m, {p.azimuth_deg:.0f}°)"
            people_detail_list.append(p_desc)
        people_detail = ", ".join(people_detail_list) if people_detail_list else "none"
        conflicts_str = str([c.get("type", "conflict") for c in (result.world_snapshot.conflicts or [])]) if result.world_snapshot.conflicts else "none"
        speaker_val = speaker_part.replace("speaker=", "")
        world_line = f"  ├── WORLD        : people=[{people_detail}], active_speaker={speaker_val}, conflicts={conflicts_str}"

        # 3. Self
        activity = result.self_state.get_current_activity()
        op_state = (
            result.self_state.operational_state.value
            if hasattr(result.self_state.operational_state, "value")
            else str(result.self_state.operational_state)
        )
        goal_str = result.self_state.current_goal.description if result.self_state.current_goal else "None"
        self_line = f"  ├── SELF         : activity=\"{activity}\", op_state={op_state}, focus={focus}, goal={goal_str}, conf={conf_str}, unc={unc_str}"

        # 4. Affective State
        aff = result.affective_state
        if aff:
            aff_line = f"  ├── AFFECT       : arousal={aff.arousal:.2f}, urgency={aff.urgency:.2f}, curiosity={aff.curiosity:.2f}, frustration={aff.frustration:.2f}, social={aff.social_engagement:.2f}"
        else:
            aff_line = "  ├── AFFECT       : default"

        # 5. Prediction
        active_preds = self.prediction_engine.get_active_predictions()
        if active_preds:
            preds_desc = ", ".join([f"{p.action_id}(target={p.target_person_id or 'none'})" for p in active_preds[:2]])
            pred_line = f"  ├── PREDICTION   : active_count={len(active_preds)}, pending=[{preds_desc}]"
        else:
            pred_line = "  ├── PREDICTION   : active_count=0, pending=[]"

        # 6. Outcome
        if result.prediction_errors:
            err_desc = ", ".join([f"{e.expectation_id}(matched={e.matched}, score={e.mismatch_score:.2f})" for e in result.prediction_errors[:2]])
            out_line = f"  ├── OUTCOME      : evaluated={len(result.prediction_errors)}, details=[{err_desc}]"
        else:
            succ_rate = round(self.metacognitive_engine.get_recent_success_rate() * 100)
            out_line = f"  ├── OUTCOME      : evaluated=0 (recent_match_rate={succ_rate}%)"

        # 7. Continuity
        recent_trans = self.continuity_tracker.to_list()
        if recent_trans:
            last_t = recent_trans[-1]
            last_trans_str = f"{last_t.get('transition_type')}: {last_t.get('previous_value')} -> {last_t.get('new_value')} (cause={last_t.get('cause')})"
        else:
            last_trans_str = "none"
        cont_line = f"  ├── CONTINUITY   : last_transition={last_trans_str}"

        # 8. Metacognition
        meta_line = f"  ├── METACOGNITION: sufficiency={suff}, status={meta_status}, conflicts={conflict_state}, decision={dec_str}"

        # 9. Behavior
        dwell_status = "active" if (self.behavior_engine.active_behavior and self.behavior_engine.active_behavior.status.value == "ACTIVE") else "idle"
        beh_line = f"  ├── BEHAVIOR     : selected={intent_str} (priority={priority_val:.2f}), target={target_str}, reason=\"{reason_str}\", dwell={dwell_status}"

        # 10. Execution
        if result.action_intent:
            act_p = str(result.action_intent.parameters)
            exec_line = f"  └── EXECUTION    : ActionIntent(type={result.action_intent.action_type}, target={result.action_intent.target}, params={act_p}) [Gated by ActionManager: Safe & LLM-free]"
        else:
            exec_line = "  └── EXECUTION    : ActionIntent=None (quiescent / non-physical) [LLM Isolated]"

        return f"{banner}\n{perc_line}\n{world_line}\n{self_line}\n{aff_line}\n{pred_line}\n{out_line}\n{cont_line}\n{meta_line}\n{beh_line}\n{exec_line}"

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
            self.metacognitive_engine.reset()
            self.behavior_engine.reset()
            self._last_focused_person = None
            self._last_telemetry_sig = None

    @property
    def average_cycle_duration_ms(self) -> float:
        """Returns the mean execution duration per cycle in milliseconds."""
        with self._lock:
            if self.cycle_count == 0:
                return 0.0
            return self.total_execution_time_ms / self.cycle_count
