"""ASTRO V1 — Epistemic Self Model, Capability Representation, and Basic Introspection."""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional, Set

from astro_ai.brain.affective_state import AffectiveStateManager
from astro_ai.brain.cognitive_continuity import CognitiveContinuityTracker
from astro_ai.brain.metacognitive_engine import MetacognitiveEngine
from astro_ai.brain.prediction_engine import PredictionEngine
from astro_ai.contracts.consciousness_types import (
    ActualOutcome,
    CognitiveConflict,
    CognitiveContext,
    CognitiveDecision,
    CognitiveDecisionType,
    CognitiveEvent,
    CognitiveStrategy,
    CognitiveTransition,
    Goal,
    GoalChangeCause,
    InformationSufficiency,
    MetacognitiveState,
    Prediction,
    PredictionError,
    RobotAffectiveState,
    SelfState,
    StrategyStatus,
)
from astro_ai.state_machine import RobotState, StateMachine


@dataclass
class SelfModel:
    """Represents Astro's self-awareness, identity, capabilities, physical limits, and dynamic self-state."""

    name: str = "Astro"
    creator: str = "Baran"
    location: str = "Bitlis / Ahlat"
    version: str = "ASTRO V1 (Cognitive Embodied Social Robot)"

    # Hardware & Subsystems
    hardware_components: List[str] = field(
        default_factory=lambda: [
            "OAK-D Lite RGB-D Stereo Vision",
            "RPLiDAR A1 360° Planar Laser Scanner",
            "ReSpeaker 4-Mic Circular Array (AEC & DOA)",
            "NVIDIA Jetson Orin Nano 8GB GPU",
            "Fine-Tuned XTTS & ReSpeaker High-Gain Output",
        ]
    )

    capabilities: List[str] = field(
        default_factory=lambda: [
            "Canlı sesli Türkçe diyalog kurma",
            "Yüz tanıma ve görsel duygu analizi",
            "Ses izinden (voiceprint) konuşmacı kimliğini doğrulama",
            "LiDAR ile 360 derece mekânsal insan ve engel takibi",
            "360° RPLiDAR lazer radarı ile konuşmacının ve engellerin mesafesini ve yönünü canlı ölçme",
            "Hava durumu sorgulama ve hatırlatıcı kurma",
            "Kişiye özel uzun vadeli anı ve tercih biriktirme",
            "İnternet kesintisinde tam çevrimdışı yerel yapay zekâ ve ses sentezi",
        ]
    )

    physical_limitations: List[str] = field(
        default_factory=lambda: [
            "Fiziksel kolları veya tutucusu yoktur (nesneleri elle taşıyamaz)",
            "Uçamaz veya merdiven tırmanamaz",
            "Göremediği veya arkasında kalan nesnelerin rengini/şeklini tahmin edemez ('şu an göremiyorum' demelidir)",
            "Görsel ya da hafıza bilgisi yoksa uydurma yapamaz ('bilmiyorum' demelidir)",
        ]
    )

    # Dynamic Runtime Self-State & Introspection (Phase 2, 3 & 4 Extensions)
    self_state: SelfState = field(default_factory=SelfState)
    affective_manager: AffectiveStateManager = field(default_factory=AffectiveStateManager)
    prediction_engine: PredictionEngine = field(default_factory=PredictionEngine)
    continuity_tracker: CognitiveContinuityTracker = field(default_factory=CognitiveContinuityTracker)
    metacognitive_engine: MetacognitiveEngine = field(default_factory=MetacognitiveEngine)
    current_goal_cause: str = ""
    current_goal_source: str = ""

    @classmethod
    def from_cognitive_loop(cls, loop: Any, **kwargs) -> SelfModel:
        """Creates a SelfModel directly bound to a live CognitiveLoop's components.

        Prevents duplicate independent engines and secondary SelfState instances.
        """
        return cls(
            self_state=loop.self_state,
            affective_manager=loop.affective_manager,
            prediction_engine=loop.prediction_engine,
            continuity_tracker=loop.continuity_tracker,
            metacognitive_engine=loop.metacognitive_engine,
            **kwargs,
        )

    def bind_cognitive_loop(self, loop: Any) -> None:
        """Binds this SelfModel to a live CognitiveLoop, sharing authoritative references."""
        self.self_state = loop.self_state
        self.affective_manager = loop.affective_manager
        self.prediction_engine = loop.prediction_engine
        self.continuity_tracker = loop.continuity_tracker
        self.metacognitive_engine = loop.metacognitive_engine

    def get_self_state(self) -> SelfState:
        """Returns the authoritative live SelfState."""
        return self.self_state

    def get_self_description_prompt(self) -> str:
        """Returns structured epistemic guidelines for the LLM."""
        return (
            f"=== ROBOT ÖZ-KİMLİK VE EPİSTEMİK SINIRLAR ===\n"
            f"- Adın: {self.name}\n"
            f"- Yaratıcın ve Baş Mühendisin: {self.creator}\n"
            f"- Konumun: {self.location}\n"
            f"- Radar ve Mesafe Algılama: 360° RPLiDAR A1 lazer tarayıcın ve derinlik kameran aktiftir; karşındaki kişinin ve etraftaki nesnelerin robota olan mesafesini santimetre hassasiyetinde canlı olarak bilirsin. Kullanıcı mesafesini sorduğunda 'GPS'im yok / ölçemem' deme; sensöründen gelen mesafeyi doğrudan söyle.\n"
            f"- Temel Kural 1 (Epistemik Dürüstlük): Bildiğin bir olgu ile o an gözlemlediğin şeyi ve tahminini daima ayırt et.\n"
            f"- Temel Kural 2 (Bilmiyorum Deme Yetkisi): Belleğinde veya kameranda olmayan bir bilgiyi asla uydurma, dürüstçe 'Bunu bilmiyorum' veya 'Şu an göremiyorum' de.\n"
            f"- Temel Kural 3 (Fiziksel Sınırlar): Fiziksel tutucun olmadığını bil; kullanıcı bir şey getirmeni isterse yapamayacağını nazikçe açıkla."
        )

    # -------------------------------------------------------------------------
    # Introspection Queries (Phase 2 Core API)
    # -------------------------------------------------------------------------

    def get_current_activity(self) -> str:
        """Introspective answer to 'What am I doing?'"""
        return self.self_state.get_current_activity()

    def get_operational_state(self) -> RobotState:
        """Returns current operational state read from StateMachine."""
        return self.self_state.get_operational_state()

    def get_focused_person(self) -> Optional[str]:
        """Returns the ID of the person ASTRO is actively focusing on."""
        return self.self_state.get_focused_person()

    def get_active_goal(self) -> Optional[Goal]:
        """Returns the active cognitive goal if any."""
        return self.self_state.get_active_goal()

    def is_executing_action(self) -> bool:
        """Returns True if ASTRO is actively executing an action."""
        return self.self_state.is_executing_action()

    def get_confidence(self) -> float:
        """Returns current epistemic confidence [0.1, 1.0]."""
        return self.self_state.get_confidence()

    def get_uncertainty(self) -> float:
        """Returns current uncertainty level [0.0, 1.0]."""
        return self.self_state.get_uncertainty()

    def get_degraded_capabilities(self) -> Set[str]:
        """Returns set of currently degraded capabilities or sensors."""
        return self.self_state.get_degraded_capabilities()

    def get_introspection_summary(self) -> Dict[str, Any]:
        """Returns a comprehensive introspective snapshot combining self-state and affective modulators."""
        summary = self.self_state.get_introspection_summary()
        summary["affective_modulators"] = self.affective_manager.state.to_dict()
        summary["identity"] = {
            "name": self.name,
            "creator": self.creator,
            "version": self.version,
        }
        return summary

    # -------------------------------------------------------------------------
    # Synchronization & Behavioral Modulation
    # -------------------------------------------------------------------------

    def sync_with_state_machine(self, state_machine: StateMachine) -> None:
        """Updates internal operational state by reading StateMachine.

        Preserves strict ownership boundary: SelfState only reads from StateMachine.
        """
        self.self_state.update_from_state_machine(state_machine)

    def sync_with_perception(self, perception_data: Dict[str, Any]) -> None:
        """Updates physical state and affects modulators from perception."""
        self.self_state.update_from_perception(perception_data)
        self.affective_manager.update_from_perception(perception_data)

    def update_affective_from_event(self, event: CognitiveEvent) -> None:
        """Passes cognitive events to internal affective manager."""
        self.affective_manager.update_from_event(event)
        self.self_state.overall_confidence = self.affective_manager.state.confidence
        self.self_state.uncertainty_level = self.affective_manager.state.uncertainty

    def step_decay(self, dt: float = 0.1) -> None:
        """Performs step decay on affective modulators and syncs confidence metrics."""
        self.affective_manager.step_decay(dt)
        self.self_state.overall_confidence = self.affective_manager.state.confidence
        self.self_state.uncertainty_level = self.affective_manager.state.uncertainty

    # -------------------------------------------------------------------------
    # Goal & Prediction Integration (Phase 3 Core API)
    # -------------------------------------------------------------------------

    def set_active_goal(
        self,
        goal: Optional[Goal],
        cause: str = GoalChangeCause.MANUAL.value,
        source: str = "",
    ) -> None:
        """Updates the active cognitive goal and records the transition with its cause."""
        prev_goal = self.self_state.current_goal
        prev_id = prev_goal.goal_id if prev_goal else None
        new_id = goal.goal_id if goal else None

        self.self_state.current_goal = goal
        self.current_goal_cause = str(cause)
        self.current_goal_source = str(source)

        if prev_id != new_id or (prev_goal and goal and prev_goal.status != goal.status):
            self.continuity_tracker.record_transition(
                transition_type="GOAL_CHANGE",
                previous_value=prev_goal.to_dict() if prev_goal else None,
                new_value=goal.to_dict() if goal else None,
                cause=str(cause),
                metadata={"source": source, "previous_id": prev_id, "new_id": new_id},
            )

    def get_current_goal_cause(self) -> str:
        """Returns the machine-readable cause of the current goal assignment."""
        return self.current_goal_cause

    def get_current_goal_description(self) -> str:
        """Introspective answer to 'What am I currently trying to accomplish?'"""
        if self.self_state.current_goal:
            return self.self_state.current_goal.description
        return "No active goal"

    def register_prediction(self, prediction: Prediction) -> None:
        """Registers an action prediction and records the transition."""
        self.prediction_engine.register_prediction(prediction)
        self.self_state.active_prediction = prediction
        self.continuity_tracker.record_transition(
            transition_type="PREDICTION_REGISTERED",
            previous_value=None,
            new_value=prediction.prediction_id,
            cause=prediction.source or "action_execution",
            metadata={"action_id": prediction.action_id, "expected_by": prediction.expected_by},
        )

    def evaluate_outcome(
        self, outcome: ActualOutcome, now: Optional[float] = None
    ) -> PredictionError:
        """Evaluates an actual outcome against active predictions and applies bounded updates."""
        prev_conf = self.affective_manager.state.confidence
        prev_unc = self.affective_manager.state.uncertainty

        pred_error = self.prediction_engine.evaluate_outcome(outcome, now=now)

        # Authoritative update in AffectiveStateManager
        self.affective_manager.update_confidence(pred_error.confidence_impact)
        self.affective_manager.update_uncertainty(pred_error.uncertainty_impact)
        if pred_error.matched:
            self.affective_manager.modulate_frustration(-0.1)
        else:
            self.affective_manager.modulate_frustration(pred_error.mismatch_score * 0.15)

        # Synchronize resulting state to SelfState read representation
        new_conf = self.affective_manager.state.confidence
        new_unc = self.affective_manager.state.uncertainty
        self.self_state.overall_confidence = new_conf
        self.self_state.uncertainty_level = new_unc

        # If active prediction matches evaluated prediction, update or clear it
        if (
            self.self_state.active_prediction
            and self.self_state.active_prediction.prediction_id == pred_error.expectation_id
        ):
            if pred_error.matched:
                self.self_state.active_prediction = None

        # Record transition in continuity tracker
        self.continuity_tracker.record_transition(
            transition_type="PREDICTION_EVALUATED" if pred_error.matched else "PREDICTION_ERROR",
            previous_value={"confidence": round(prev_conf, 3), "uncertainty": round(prev_unc, 3)},
            new_value={"confidence": round(new_conf, 3), "uncertainty": round(new_unc, 3)},
            cause=pred_error.mismatch_type,
            metadata=pred_error.to_dict(),
        )

        if abs(new_conf - prev_conf) >= 0.05:
            self.continuity_tracker.record_transition(
                transition_type="CONFIDENCE_CHANGE",
                previous_value=round(prev_conf, 3),
                new_value=round(new_conf, 3),
                cause="prediction_evaluation",
                metadata={"delta": round(pred_error.confidence_impact, 3)},
            )

        if abs(new_unc - prev_unc) >= 0.05:
            self.continuity_tracker.record_transition(
                transition_type="UNCERTAINTY_CHANGE",
                previous_value=round(prev_unc, 3),
                new_value=round(new_unc, 3),
                cause="prediction_evaluation",
                metadata={"delta": round(pred_error.uncertainty_impact, 3)},
            )

        # Update metacognitive strategy and outcome performance tracking
        self.metacognitive_engine.record_outcome_for_strategy(matched=pred_error.matched)

        return pred_error

    def check_prediction_expirations(
        self, now: Optional[float] = None
    ) -> List[PredictionError]:
        """Checks and processes any expired predictions."""
        expired_errors = self.prediction_engine.check_expirations(now=now)
        for err in expired_errors:
            prev_conf = self.affective_manager.state.confidence
            prev_unc = self.affective_manager.state.uncertainty

            self.affective_manager.update_confidence(err.confidence_impact)
            self.affective_manager.update_uncertainty(err.uncertainty_impact)
            self.affective_manager.modulate_frustration(0.1)

            new_conf = self.affective_manager.state.confidence
            new_unc = self.affective_manager.state.uncertainty
            self.self_state.overall_confidence = new_conf
            self.self_state.uncertainty_level = new_unc

            if (
                self.self_state.active_prediction
                and self.self_state.active_prediction.prediction_id == err.expectation_id
            ):
                self.self_state.active_prediction = None

            self.continuity_tracker.record_transition(
                transition_type="PREDICTION_EXPIRED",
                previous_value=err.expectation_id,
                new_value="EXPIRED",
                cause="timeout",
                metadata=err.to_dict(),
            )
            # Record expiration as an error in strategy tracker
            self.metacognitive_engine.record_outcome_for_strategy(matched=False)
        return expired_errors

    # -------------------------------------------------------------------------
    # Cognitive Continuity & Introspective Transitions
    # -------------------------------------------------------------------------

    def get_recent_transitions(self, limit: int = 10) -> List[CognitiveTransition]:
        """Returns recent cognitive transitions up to limit."""
        return self.continuity_tracker.get_recent_transitions(limit=limit)

    def get_transitions_by_type(self, transition_type: str) -> List[CognitiveTransition]:
        """Returns recent cognitive transitions of a specific type."""
        return self.continuity_tracker.get_transitions_by_type(transition_type=transition_type)

    def get_last_transition(self) -> Optional[CognitiveTransition]:
        """Returns the most recently recorded cognitive transition."""
        return self.continuity_tracker.get_last_transition()

    # -------------------------------------------------------------------------
    # Metacognitive Control & Reflective Cognition (Phase 4 Core API)
    # -------------------------------------------------------------------------

    def get_metacognitive_state(self) -> MetacognitiveState:
        """Returns the current MetacognitiveState assessment snapshot."""
        return self.metacognitive_engine.current_state

    def set_active_strategy(
        self, strategy: CognitiveStrategy | str, rationale: str = ""
    ) -> Optional[CognitiveStrategy]:
        """Registers and/or activates a cognitive strategy, recording the transition."""
        if isinstance(strategy, str):
            strat_obj = self.metacognitive_engine.get_strategy(strategy)
            strat_id = strategy
        else:
            strat_obj = strategy
            strat_id = strategy.strategy_id
            self.metacognitive_engine.register_strategy(strat_obj)

        prev_strat = self.metacognitive_engine.get_active_strategy()
        prev_id = prev_strat.strategy_id if prev_strat else None
        activated = self.metacognitive_engine.set_active_strategy(strat_id, rationale=rationale)

        if activated:
            self.continuity_tracker.record_transition(
                transition_type="STRATEGY_CHANGE",
                previous_value=prev_id,
                new_value=strat_id,
                cause=rationale or (strat_obj.rationale if strat_obj else "") or "strategy_selection",
                metadata=strat_obj.to_dict() if strat_obj else {},
            )
        return activated

    def get_active_strategy(self) -> Optional[CognitiveStrategy]:
        """Returns the active cognitive strategy."""
        return self.metacognitive_engine.get_active_strategy()

    def assess_information_sufficiency(
        self, perception_data: Optional[Dict[str, Any]] = None
    ) -> InformationSufficiency:
        """Evaluates whether current perception data is adequate for the active goal."""
        return self.metacognitive_engine.assess_information_sufficiency(
            active_goal=self.self_state.current_goal,
            perception_data=perception_data,
            uncertainty=self.get_uncertainty(),
        )

    def detect_conflicts(
        self, perception_data: Optional[Dict[str, Any]] = None
    ) -> List[CognitiveConflict]:
        """Detects cognitive conflicts and logs new conflicts in continuity tracker."""
        conflicts = self.metacognitive_engine.detect_conflicts(
            active_goal=self.self_state.current_goal,
            perception_data=perception_data,
            confidence=self.get_confidence(),
            uncertainty=self.get_uncertainty(),
        )
        for conf in conflicts:
            self.continuity_tracker.record_transition(
                transition_type="CONFLICT_DETECTED",
                previous_value=None,
                new_value=conf.conflict_type,
                cause="conflict_detection",
                metadata=conf.to_dict(),
            )
        return conflicts

    def evaluate_cognition(
        self, perception_data: Optional[Dict[str, Any]] = None
    ) -> Tuple[MetacognitiveState, Optional[CognitiveDecision]]:
        """Evaluates cognitive health, conflicts, and policy, returning state and decision."""
        state, decision = self.metacognitive_engine.evaluate_metacognitive_state(
            active_goal=self.self_state.current_goal,
            perception_data=perception_data,
            confidence=self.get_confidence(),
            uncertainty=self.get_uncertainty(),
        )

        if decision and decision.decision_type in (
            CognitiveDecisionType.REASSESS,
            CognitiveDecisionType.REEVALUATE_GOAL,
            CognitiveDecisionType.REVIEW_STRATEGY,
        ):
            self.continuity_tracker.record_transition(
                transition_type="REASSESSMENT_TRIGGERED",
                previous_value=state.cognitive_status,
                new_value=decision.decision_type.value,
                cause=decision.reason,
                metadata=decision.to_dict(),
            )
        return state, decision

    def get_cognitive_context(
        self,
        recent_events: Optional[List[CognitiveEvent]] = None,
        perception_data: Optional[Dict[str, Any]] = None,
    ) -> CognitiveContext:
        """Constructs an immutable CognitiveContext read snapshot."""
        now = time.time()
        events_summary = [
            f"{evt.event_type.value}: {evt.source}"
            for evt in (recent_events or [])
        ]
        return CognitiveContext(
            timestamp=now,
            activity=self.get_current_activity(),
            operational_state=(
                self.get_operational_state().value
                if isinstance(self.get_operational_state(), RobotState)
                else str(self.get_operational_state())
            ),
            focused_person_id=self.get_focused_person(),
            active_goal=self.self_state.current_goal.to_dict() if self.self_state.current_goal else None,
            active_prediction=self.self_state.active_prediction.to_dict() if self.self_state.active_prediction else None,
            confidence=round(self.get_confidence(), 3),
            uncertainty=round(self.get_uncertainty(), 3),
            affective_state=self.affective_manager.state.to_dict(),
            degraded_capabilities=sorted(list(self.get_degraded_capabilities())),
            identity={
                "name": self.name,
                "creator": self.creator,
                "location": self.location,
                "version": self.version,
            },
            capabilities=list(self.capabilities),
            recent_transitions=self.continuity_tracker.to_list()[-10:],
            recent_events_summary=events_summary[-10:],
            perception_summary=dict(perception_data or {}),
            self_state_snapshot=self.self_state.to_dict(),
            metacognitive_state=self.metacognitive_engine.current_state.to_dict(),
        )
