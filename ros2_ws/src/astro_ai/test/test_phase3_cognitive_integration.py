"""ASTRO V1 — Phase 3 Cognitive Integration & Continuity Test Suite.

Verifies:
  1. CognitiveContext construction & read-only immutability
  2. CognitiveContext does not own StateMachine state
  3. Expectation creation
  4. Expectation lifecycle & expiration
  5. Outcome representation
  6. Matching expected vs actual outcome
  7. Prediction error calculation
  8. Prediction-met case
  9. Prediction-missed case
  10. Confidence update from prediction error
  11. Uncertainty update from prediction error
  12. Goal/self-model integration
  13. Goal-state change causes
  14. Cognitive continuity history
  15. History size bound (fixed deque capacity)
  16. Introspective change tracking
  17. Affective modulation from approved cognitive events
  18. Affective state cannot emit ActionIntent
  19. Deterministic replay
  20. Empty/no-perception stability
  21. Phase 0A regression compatibility
  22. Phase 0B regression compatibility
  23. Phase 1 regression compatibility
  24. Phase 2 regression compatibility
  25. Phase 3 support-layer regression compatibility
"""

from dataclasses import FrozenInstanceError
import math
import time
import pytest

from astro_ai.brain.affective_state import AffectiveStateManager
from astro_ai.brain.cognitive_continuity import CognitiveContinuityTracker
from astro_ai.brain.cognitive_event_bus import CognitiveEventBus
from astro_ai.brain.cognitive_loop import CognitiveLoop, CognitiveCycleResult
from astro_ai.brain.perception_event_detector import PerceptionEventDetector
from astro_ai.brain.prediction_engine import (
    CONFIDENCE_MAX,
    CONFIDENCE_MIN,
    PredictionEngine,
    UNCERTAINTY_MAX,
    UNCERTAINTY_MIN,
)
from astro_ai.brain.self_model import SelfModel
from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.consciousness_types import (
    ActualOutcome,
    CognitiveContext,
    CognitiveEvent,
    CognitiveEventType,
    CognitiveTransition,
    Goal,
    GoalChangeCause,
    GoalStatus,
    GoalType,
    Prediction,
    PredictionError,
    PredictionStatus,
    RobotAffectiveState,
    SelfState,
)
from astro_ai.state_machine import RobotState, StateMachine


# =============================================================================
# TESTS
# =============================================================================

def test_01_cognitive_context_construction():
    """1. Verify CognitiveContext construction, fields, and immutability."""
    self_model = SelfModel()
    goal = Goal(
        goal_id="g_test_01",
        goal_type=GoalType.TASK,
        description="Deliver greeting",
        priority=0.8,
    )
    self_model.set_active_goal(goal, cause=GoalChangeCause.USER_REQUEST.value)

    pred = Prediction(
        prediction_id="pred_01",
        action_id="say_hello",
        expected_state={"person_smiled": True},
        expected_by=time.time() + 5.0,
    )
    self_model.register_prediction(pred)

    ctx = self_model.get_cognitive_context()
    assert isinstance(ctx, CognitiveContext)
    assert ctx.confidence == pytest.approx(0.7, abs=0.05)
    assert ctx.uncertainty == pytest.approx(0.3, abs=0.05)
    assert ctx.active_goal is not None
    assert ctx.active_goal["goal_id"] == "g_test_01"
    assert ctx.active_prediction is not None
    assert ctx.active_prediction["prediction_id"] == "pred_01"
    assert "identity" in ctx.to_dict()
    assert ctx.identity["name"] == "Astro"
    assert len(ctx.recent_transitions) >= 2

    # Immutability verification: frozen dataclass cannot be mutated
    with pytest.raises(FrozenInstanceError):
        ctx.confidence = 0.99  # type: ignore


def test_02_cognitive_context_does_not_own_state_machine():
    """2. Verify CognitiveContext is strictly a read-model and does not own StateMachine."""
    sm = StateMachine()
    assert sm.current_state == RobotState.IDLE

    self_model = SelfModel()
    self_model.sync_with_state_machine(sm)
    ctx = self_model.get_cognitive_context()
    assert ctx.operational_state == RobotState.IDLE.value

    # Operational state transition must be performed on StateMachine, NOT CognitiveContext
    transitioned = sm.transition_to(RobotState.WAKE)
    assert transitioned is True
    assert sm.current_state == RobotState.WAKE

    # Context remains unchanged until a new read model snapshot is taken
    assert ctx.operational_state == RobotState.IDLE.value

    # Synchronize and take new snapshot
    self_model.sync_with_state_machine(sm)
    ctx_updated = self_model.get_cognitive_context()
    assert ctx_updated.operational_state == RobotState.WAKE.value


def test_03_expectation_creation():
    """3. Verify Prediction/expectation creation with Phase 3 attributes."""
    exp_time = time.time() + 10.0
    pred = Prediction(
        prediction_id="exp_99",
        action_id="nod_head",
        expected_state={"pitch_deg": 15.0, "ack_received": True},
        expected_by=exp_time,
        confidence_weight=1.5,
        source="dialogue_planner",
        related_goal_id="g_social_05",
        target_person_id="person_42",
        metadata={"scenario": "affirmation"},
    )
    assert pred.prediction_id == "exp_99"
    assert pred.status == PredictionStatus.PENDING
    assert pred.confidence_weight == 1.5
    assert pred.source == "dialogue_planner"
    assert pred.related_goal_id == "g_social_05"
    assert pred.target_person_id == "person_42"
    assert pred.is_expired(now=exp_time - 1.0) is False
    assert pred.is_expired(now=exp_time + 1.0) is True

    d = pred.to_dict()
    assert d["prediction_id"] == "exp_99"
    assert d["status"] == "PENDING"
    assert d["source"] == "dialogue_planner"


def test_04_expectation_lifecycle():
    """4. Verify Prediction lifecycle (PENDING -> CONFIRMED / MISMATCH / EXPIRED)."""
    engine = PredictionEngine()
    now = time.time()

    p1 = Prediction(
        prediction_id="p_pend",
        action_id="act_1",
        expected_state={"val": 10},
        expected_by=now + 5.0,
    )
    p2 = Prediction(
        prediction_id="p_exp",
        action_id="act_2",
        expected_state={"val": 20},
        expected_by=now - 1.0,  # Already past deadline
    )
    engine.register_prediction(p1)
    engine.register_prediction(p2)

    assert len(engine.get_active_predictions()) == 2

    # Check expiration
    expired_errors = engine.check_expirations(now=now)
    assert len(expired_errors) == 1
    assert expired_errors[0].expectation_id == "p_exp"
    assert expired_errors[0].mismatch_type == "TIMEOUT_EXPIRED"
    assert p2.status == PredictionStatus.EXPIRED

    # Remaining active prediction is p1
    active = engine.get_active_predictions()
    assert len(active) == 1
    assert active[0].prediction_id == "p_pend"


def test_05_outcome_representation():
    """5. Verify ActualOutcome representation and serialization."""
    out = ActualOutcome(
        outcome_id="out_55",
        actual_state={"user_present": True, "distance_m": 1.25},
        expectation_id="exp_99",
        source="lidar_tracker",
        metadata={"confidence_score": 0.92},
    )
    assert out.outcome_id == "out_55"
    assert out.expectation_id == "exp_99"
    assert out.actual_state["distance_m"] == 1.25
    assert out.source == "lidar_tracker"

    d = out.to_dict()
    assert d["outcome_id"] == "out_55"
    assert d["actual_state"]["user_present"] is True


def test_06_matching_expected_vs_actual_outcome():
    """6. Verify matching expected vs actual outcome states."""
    engine = PredictionEngine()

    # Exact match
    score, m_type, details = engine.calculate_discrepancy(
        {"yaw": 0.0, "status": "ok"},
        {"yaw": 0.0, "status": "ok", "extra": 42},
    )
    assert score == 0.0
    assert m_type == "NONE"
    assert len(details) == 0

    # Value mismatch
    score, m_type, details = engine.calculate_discrepancy(
        {"yaw": 0.0, "status": "ok"},
        {"yaw": 45.0, "status": "ok"},
    )
    assert score == 0.5
    assert m_type == "VALUE_MISMATCH"
    assert "yaw" in details

    # Missing keys
    score, m_type, details = engine.calculate_discrepancy(
        {"yaw": 0.0, "speed": 1.0},
        {"yaw": 0.0},
    )
    assert score == 0.5
    assert m_type == "MISSING_KEYS"
    assert "speed" in details


def test_07_prediction_error_calculation():
    """7. Verify deterministic prediction error bounds and float tolerance."""
    engine = PredictionEngine()

    # Float near-equality within tolerance (1e-3)
    score, m_type, _ = engine.calculate_discrepancy(
        {"temp": 24.0001},
        {"temp": 24.0004},
    )
    assert score == 0.0
    assert m_type == "NONE"

    # Score bounded strictly to [0.0, 1.0]
    score_empty, _, _ = engine.calculate_discrepancy({}, {"val": 1})
    assert score_empty == 0.0

    score_total, _, _ = engine.calculate_discrepancy(
        {"a": 1, "b": 2},
        {"c": 3},
    )
    assert score_total == 1.0
    assert not math.isnan(score_total)
    assert not math.isinf(score_total)


def test_08_prediction_met_case():
    """8. Verify prediction-met evaluation."""
    engine = PredictionEngine()
    pred = Prediction(
        prediction_id="p_met",
        action_id="orient",
        expected_state={"oriented": True},
        expected_by=time.time() + 5.0,
        confidence_weight=1.0,
    )
    engine.register_prediction(pred)

    outcome = ActualOutcome(
        outcome_id="out_met",
        actual_state={"oriented": True},
        expectation_id="p_met",
    )
    err = engine.evaluate_outcome(outcome)
    assert err.matched is True
    assert err.mismatch_score == 0.0
    assert err.mismatch_type == "NONE"
    assert err.confidence_impact == pytest.approx(0.05)
    assert err.uncertainty_impact == pytest.approx(-0.05)
    assert pred.status == PredictionStatus.CONFIRMED


def test_09_prediction_missed_case():
    """9. Verify prediction-missed evaluation."""
    engine = PredictionEngine()
    pred = Prediction(
        prediction_id="p_miss",
        action_id="track",
        expected_state={"target_visible": True},
        expected_by=time.time() + 5.0,
        confidence_weight=1.0,
    )
    engine.register_prediction(pred)

    outcome = ActualOutcome(
        outcome_id="out_miss",
        actual_state={"target_visible": False},
        expectation_id="p_miss",
    )
    err = engine.evaluate_outcome(outcome)
    assert err.matched is False
    assert err.mismatch_score == 1.0
    assert err.mismatch_type == "VALUE_MISMATCH"
    # Penalty: 1.0 * 1.0 * 0.2 = 0.2
    assert err.confidence_impact == pytest.approx(-0.2)
    assert err.uncertainty_impact == pytest.approx(0.2)
    assert pred.status == PredictionStatus.MISMATCH


def test_10_confidence_update_from_prediction_error():
    """10. Verify confidence update mathematics and clamping."""
    self_model = SelfModel()
    self_model.affective_manager.set_confidence(0.7)

    pred = Prediction(
        prediction_id="p_conf",
        action_id="test_act",
        expected_state={"state": "A"},
        expected_by=time.time() + 10.0,
        confidence_weight=1.0,
    )
    self_model.register_prediction(pred)

    # Miss: mismatch_score=1.0 -> penalty 0.2
    outcome = ActualOutcome(
        outcome_id="o1",
        actual_state={"state": "B"},
        expectation_id="p_conf",
    )
    self_model.evaluate_outcome(outcome)
    assert self_model.get_confidence() == pytest.approx(0.5, abs=0.01)

    # Trigger multiple failures to verify clamping to CONFIDENCE_MIN (0.1)
    for i in range(5):
        p_fail = Prediction(
            prediction_id=f"pf_{i}",
            action_id="act",
            expected_state={"k": 1},
            expected_by=time.time() + 10.0,
        )
        self_model.register_prediction(p_fail)
        self_model.evaluate_outcome(ActualOutcome(outcome_id=f"of_{i}", actual_state={"k": 2}, expectation_id=f"pf_{i}"))

    assert self_model.get_confidence() >= CONFIDENCE_MIN
    assert self_model.get_confidence() == pytest.approx(CONFIDENCE_MIN)


def test_11_uncertainty_update_from_prediction_error():
    """11. Verify uncertainty update mathematics and clamping."""
    self_model = SelfModel()
    self_model.affective_manager.set_uncertainty(0.3)

    pred = Prediction(
        prediction_id="p_unc",
        action_id="test_act",
        expected_state={"target": "Baran"},
        expected_by=time.time() + 10.0,
        confidence_weight=1.0,
    )
    self_model.register_prediction(pred)

    outcome = ActualOutcome(
        outcome_id="o_unc",
        actual_state={"target": "Unknown"},
        expectation_id="p_unc",
    )
    self_model.evaluate_outcome(outcome)
    assert self_model.get_uncertainty() == pytest.approx(0.5, abs=0.01)

    # Multiple failures to verify clamping to UNCERTAINTY_MAX (1.0)
    for i in range(5):
        p_fail = Prediction(
            prediction_id=f"pu_{i}",
            action_id="act",
            expected_state={"x": 1},
            expected_by=time.time() + 10.0,
        )
        self_model.register_prediction(p_fail)
        self_model.evaluate_outcome(ActualOutcome(outcome_id=f"ou_{i}", actual_state={"x": 2}, expectation_id=f"pu_{i}"))

    assert self_model.get_uncertainty() <= UNCERTAINTY_MAX
    assert self_model.get_uncertainty() == pytest.approx(UNCERTAINTY_MAX)


def test_12_goal_self_model_integration():
    """12. Verify Goal ↔ SelfModel integration and machine-level introspection."""
    self_model = SelfModel()
    assert self_model.get_active_goal() is None
    assert self_model.get_current_goal_description() == "No active goal"

    goal = Goal(
        goal_id="g_social_01",
        goal_type=GoalType.SOCIAL,
        description="Engage in friendly conversation with visitor",
        priority=0.75,
        status=GoalStatus.ACTIVE,
    )
    self_model.set_active_goal(goal, cause=GoalChangeCause.USER_REQUEST.value, source="speech_recognizer")

    assert self_model.get_active_goal() is not None
    assert self_model.get_active_goal().goal_id == "g_social_01"
    assert self_model.get_current_goal_description() == "Engage in friendly conversation with visitor"
    assert self_model.get_current_goal_cause() == GoalChangeCause.USER_REQUEST.value


def test_13_goal_state_change_causes():
    """13. Verify explicit machine-readable causes for goal state changes."""
    self_model = SelfModel()

    # Safety override cause
    safety_goal = Goal(
        goal_id="g_safety_01",
        goal_type=GoalType.SAFETY,
        description="Emergency stop due to close obstacle",
        priority=1.0,
    )
    self_model.set_active_goal(safety_goal, cause=GoalChangeCause.SAFETY_OVERRIDE.value)
    assert self_model.get_current_goal_cause() == GoalChangeCause.SAFETY_OVERRIDE.value

    # Verify transition logged
    transitions = self_model.get_transitions_by_type("GOAL_CHANGE")
    assert len(transitions) == 1
    assert transitions[0].cause == GoalChangeCause.SAFETY_OVERRIDE.value
    assert transitions[0].new_value["goal_id"] == "g_safety_01"


def test_14_cognitive_continuity_history():
    """14. Verify CognitiveContinuityTracker records and categorizes events."""
    tracker = CognitiveContinuityTracker(max_history=50)

    t1 = tracker.record_transition("GOAL_CHANGE", None, "g_01", cause="USER_REQUEST")
    t2 = tracker.record_transition("PREDICTION_REGISTERED", None, "p_01", cause="planner")
    t3 = tracker.record_transition("FOCUS_CHANGE", None, "person_A", cause="face_detect")

    assert tracker.get_history_len() == 3
    assert tracker.get_last_transition() == t3

    recent = tracker.get_recent_transitions(limit=2)
    assert len(recent) == 2
    assert recent[0] == t2
    assert recent[1] == t3

    goal_transitions = tracker.get_transitions_by_type("GOAL_CHANGE")
    assert len(goal_transitions) == 1
    assert goal_transitions[0] == t1


def test_15_history_size_bound():
    """15. Verify bounded history capacity prevents unbounded memory growth."""
    tracker = CognitiveContinuityTracker(max_history=10)

    for i in range(25):
        tracker.record_transition(
            transition_type="TEST_TRANSITION",
            previous_value=i,
            new_value=i + 1,
            cause=f"step_{i}",
        )

    # Must be clamped strictly to max_history (10)
    assert tracker.get_history_len() == 10
    recent = tracker.get_recent_transitions(limit=10)
    assert len(recent) == 10
    # Oldest retained is step_15 (0..14 evicted)
    assert recent[0].cause == "step_15"
    assert recent[-1].cause == "step_24"


def test_16_introspective_change_tracking():
    """16. Verify structured introspective change tracking."""
    self_model = SelfModel()

    # Trigger goal change and prediction evaluation
    self_model.set_active_goal(
        Goal(goal_id="g1", goal_type=GoalType.TASK, description="Task 1"),
        cause=GoalChangeCause.PERCEPTION_TRIGGER.value,
    )
    p = Prediction(
        prediction_id="pred_inspect",
        action_id="say",
        expected_state={"heard": True},
        expected_by=time.time() + 10.0,
    )
    self_model.register_prediction(p)
    self_model.evaluate_outcome(
        ActualOutcome(outcome_id="o1", actual_state={"heard": False}, expectation_id="pred_inspect")
    )

    recent = self_model.get_recent_transitions()
    assert len(recent) >= 3

    # All transitions must have structured, machine-readable fields
    for t in recent:
        d = t.to_dict()
        assert "transition_id" in d
        assert "timestamp" in d
        assert "transition_type" in d
        assert "previous_value" in d
        assert "new_value" in d
        assert "cause" in d


def test_17_affective_modulation_from_approved_cognitive_events():
    """17. Verify AffectiveStateManager modulation from canonical cognitive events."""
    mgr = AffectiveStateManager()
    mgr.reset()
    base_conf = mgr.state.confidence
    base_unc = mgr.state.uncertainty
    base_frust = mgr.state.frustration

    # Prediction error / failure increases frustration and uncertainty, reduces confidence
    mgr.update_from_event(
        CognitiveEvent(
            event_type=CognitiveEventType.PREDICTION_ERROR,
            source="prediction_engine",
        )
    )
    assert mgr.state.frustration > base_frust
    assert mgr.state.uncertainty > base_unc
    assert mgr.state.confidence < base_conf

    # Prediction confirmed restores state
    mgr.update_from_event(
        CognitiveEvent(
            event_type=CognitiveEventType.PREDICTION_CONFIRMED,
            source="prediction_engine",
        )
    )
    assert mgr.state.confidence > base_conf * 0.9

    # Novelty increases curiosity and arousal
    base_curiosity = mgr.state.curiosity
    mgr.update_from_event(
        CognitiveEvent(
            event_type=CognitiveEventType.NOVELTY_DETECTED,
            source="vision",
        )
    )
    assert mgr.state.curiosity > base_curiosity


def test_18_affective_state_cannot_emit_action_intent():
    """18. Verify strict architectural boundary: AffectiveState cannot emit ActionIntent."""
    mgr = AffectiveStateManager()
    # Confirm AffectiveStateManager only provides read multipliers and modulator adjustments
    assert hasattr(mgr, "get_reaction_speed_multiplier")
    assert hasattr(mgr, "get_verbosity_multiplier")
    assert hasattr(mgr, "get_attention_sensitivity")

    # Prohibited capabilities: no action emission, no motor commands, no ros publication
    assert not hasattr(mgr, "emit_action_intent")
    assert not hasattr(mgr, "publish_action")
    assert not hasattr(mgr, "command_motors")
    assert not hasattr(mgr, "create_action_intent")


def test_19_deterministic_replay():
    """19. Verify deterministic execution across repeated identical cognitive cycles."""
    feed = [
        {"robot_state": {"head_yaw_deg": 0.0}, "tts_speaking": False},
        {"robot_state": {"head_yaw_deg": 10.0}, "tts_speaking": True},
        {"robot_state": {"head_yaw_deg": 10.0}, "tts_speaking": False},
    ]

    loop1 = CognitiveLoop()
    res1 = loop1.run_consecutive_steps(len(feed), feed)

    loop2 = CognitiveLoop()
    res2 = loop2.run_consecutive_steps(len(feed), feed)

    assert len(res1) == len(res2) == 3
    for r1, r2 in zip(res1, res2):
        assert r1.cycle_index == r2.cycle_index
        assert r1.self_state.is_speaking == r2.self_state.is_speaking
        assert r1.self_state.current_head_yaw_deg == r2.self_state.current_head_yaw_deg
        assert pytest.approx(r1.affective_state.confidence, abs=1e-4) == r2.affective_state.confidence


def test_20_empty_no_perception_stability():
    """20. Verify loop stability and smooth decay when running with zero perception input."""
    loop = CognitiveLoop()
    results = loop.run_consecutive_steps(20, None)

    assert len(results) == 20
    for res in results:
        assert res.cognitive_context is not None
        assert not math.isnan(res.cognitive_context.confidence)
        assert not math.isnan(res.cognitive_context.uncertainty)
        assert res.duration_ms < 10.0  # Fast, non-blocking execution


def test_21_phase0a_regression_compatibility():
    """21. Verify Phase 0A event bus, world model, and foundation types remain intact."""
    bus = CognitiveEventBus(max_capacity=100)
    evt = CognitiveEvent(
        event_type=CognitiveEventType.PERSON_APPEARED,
        source="vision",
        salience=0.8,
    )
    bus.publish(evt)
    unprocessed = bus.get_unprocessed_events()
    assert len(unprocessed) == 1
    assert unprocessed[0].event_type == CognitiveEventType.PERSON_APPEARED
    bus.mark_processed([unprocessed[0].event_id])
    assert len(bus.get_unprocessed_events()) == 0


def test_22_phase0b_regression_compatibility():
    """22. Verify Phase 0B WorldModel temporal extension and window access."""
    wm = WorldModel(temporal_history_size=10)
    for i in range(5):
        wm.update_robot_state(head_yaw_deg=float(i))
        wm.commit_temporal_snapshot()

    assert wm.temporal_history_len == 5
    window = wm.get_temporal_window(limit=3)
    assert len(window) == 3
    assert window[-1].robot_state["head_yaw_deg"] == 4.0


def test_23_phase1_regression_compatibility():
    """23. Verify Phase 1 PerceptionEventDetector transitions."""
    detector = PerceptionEventDetector()
    events = detector.detect_transitions({"people": [{"person_id": "user_p1", "is_present": True}]})
    assert any(e.event_type == CognitiveEventType.PERSON_APPEARED for e in events)


def test_24_phase2_regression_compatibility():
    """24. Verify Phase 2 SelfModel, SelfState, and introspection summaries."""
    model = SelfModel()
    model.self_state.is_speaking = True
    assert model.get_current_activity() == "Speaking"

    summary = model.get_introspection_summary()
    assert summary["activity"] == "Speaking"
    assert "affective_modulators" in summary
    assert "identity" in summary


def test_25_phase3_support_layer_regression_compatibility():
    """25. Verify Phase 3 Cognitive Architecture Support Layer remains intact."""
    from astro_ai.brain.support.config import SupportConfig
    from astro_ai.brain.support.budget_gate import LocalBudgetGate
    from astro_ai.brain.support.contracts import SupportControlMode

    cfg = SupportConfig()
    gate = LocalBudgetGate(cfg)
    decision = gate.evaluate_request("gemini", estimated_input_tokens=100)
    assert decision.allowed is True
    assert cfg.llm_support_enabled is False
    assert SupportControlMode.OBSERVE.value == "OBSERVE"
