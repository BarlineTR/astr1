"""ASTRO V1 — Phase 4 Metacognitive Control & Reflective Cognition Test Suite.

Verifies:
  1. MetacognitiveState default creation and clamping
  2. CognitiveStrategy creation and mutation
  3. CognitiveStrategy success rate computation with 0 outcomes
  4. CognitiveStrategy success rate computation with mixed outcomes
  5. MetacognitiveEngine strategy registration and retrieval
  6. MetacognitiveEngine set_active_strategy transitions
  7. MetacognitiveEngine outcome recording updates active strategy
  8. MetacognitiveEngine outcome recording with no active strategy
  9. InformationSufficiency assessment with sufficient data
  10. InformationSufficiency assessment with missing goal perception
  11. InformationSufficiency assessment with stale perception
  12. InformationSufficiency assessment with high uncertainty
  13. Conflict detection: GOAL_SAFETY_CONFLICT on obstacle
  14. Conflict detection: CONFIDENCE_PERFORMANCE_MISMATCH (overconfidence)
  15. Conflict detection: STRATEGY_PERSISTENCE_FAILURE on repeated errors
  16. Conflict detection: no conflict under normal nominal conditions
  17. Confidence calibration: OVERCONFIDENT categorization
  18. Confidence calibration: UNDERCONFIDENT categorization
  19. Confidence calibration: WELL_CALIBRATED categorization
  20. Reassessment trigger produces CognitiveDecision with REASSESS type
  21. Reassessment trigger respects cooldown suppression
  22. Reassessment trigger cooldown expires allowing subsequent trigger
  23. CognitiveDecision is emitted as SEEK_INFORMATION when data is insufficient
  24. CognitiveDecision is emitted as REEVALUATE_GOAL or REASSESS on safety conflict
  25. CognitiveDecision is emitted as CONTINUE under nominal state
  26. CognitiveDecision serialization to_dict / from_dict roundtrip
  27. SelfModel.get_metacognitive_state integration
  28. SelfModel.evaluate_outcome updates MetacognitiveEngine
  29. CognitiveLoop.step produces MetacognitiveState in result
  30. CognitiveLoop.step produces CognitiveDecision and records continuity transitions
"""

import time
import pytest

from astro_ai.brain.cognitive_loop import CognitiveLoop, CognitiveCycleResult
from astro_ai.brain.metacognitive_engine import (
    DEFAULT_CRITICAL_PROXIMITY_M,
    DEFAULT_HIGH_CONFIDENCE_THRESHOLD,
    DEFAULT_HIGH_ERROR_RATE_THRESHOLD,
    DEFAULT_HIGH_SUCCESS_RATE_THRESHOLD,
    DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    DEFAULT_REPEATED_FAILURE_THRESHOLD,
    DEFAULT_STALE_PERCEPTION_SECONDS,
    MetacognitiveEngine,
)
from astro_ai.brain.self_model import SelfModel
from astro_ai.contracts.consciousness_types import (
    ActualOutcome,
    CognitiveConflict,
    CognitiveDecision,
    CognitiveDecisionType,
    CognitiveStrategy,
    Goal,
    GoalType,
    InformationSufficiency,
    MetacognitiveState,
    Prediction,
    PredictionError,
    StrategyStatus,
)


# =============================================================================
# 1. MetacognitiveState default creation and clamping
# =============================================================================

def test_metacognitive_state_defaults_and_clamping():
    state = MetacognitiveState()
    assert state.cognitive_status == "NORMAL"
    assert state.current_strategy_id is None
    assert state.strategy_confidence == 0.7
    assert state.knowledge_confidence == 0.7
    assert state.uncertainty_level == 0.3
    assert state.information_sufficiency == InformationSufficiency.UNKNOWN
    assert state.recent_prediction_success_rate == 1.0
    assert state.recent_prediction_error_rate == 0.0
    assert state.repeated_failure_count == 0
    assert state.cognitive_conflict_state == "NONE"
    assert state.need_for_reassessment is False
    assert state.current_cognitive_load_estimate == 0.2

    # Test clamping out-of-bounds metrics
    state.strategy_confidence = 1.8
    state.knowledge_confidence = -0.4
    state.uncertainty_level = 2.0
    state.recent_prediction_success_rate = 1.5
    state.recent_prediction_error_rate = -0.1
    state.current_cognitive_load_estimate = 3.5

    state.clamp()

    assert state.strategy_confidence == 1.0
    assert state.knowledge_confidence == 0.0
    assert state.uncertainty_level == 1.0
    assert state.recent_prediction_success_rate == 1.0
    assert state.recent_prediction_error_rate == 0.0
    assert state.current_cognitive_load_estimate == 1.0

    # Serialization roundtrip
    d = state.to_dict()
    restored = MetacognitiveState.from_dict(d)
    assert restored.cognitive_status == state.cognitive_status
    assert restored.strategy_confidence == state.strategy_confidence
    assert restored.uncertainty_level == state.uncertainty_level


# =============================================================================
# 2. CognitiveStrategy creation and mutation
# =============================================================================

def test_cognitive_strategy_creation_and_mutation():
    strat = CognitiveStrategy(
        strategy_id="strat_face_track",
        name="Face Tracking Gaze",
        description="Tracks face yaw with proportional controller",
    )
    assert strat.strategy_id == "strat_face_track"
    assert strat.name == "Face Tracking Gaze"
    assert strat.status == StrategyStatus.ACTIVE
    assert strat.success_count == 0
    assert strat.failure_count == 0
    assert strat.confidence == 0.7
    assert strat.parameters == {}

    # Mutate strategy
    strat.status = StrategyStatus.SUSPENDED
    strat.confidence = 0.85
    strat.parameters["gain"] = 1.5
    strat.rationale = "Target person is seated directly ahead"

    d = strat.to_dict()
    restored = CognitiveStrategy.from_dict(d)
    assert restored.strategy_id == "strat_face_track"
    assert restored.status == StrategyStatus.SUSPENDED
    assert restored.confidence == 0.85
    assert restored.parameters["gain"] == 1.5
    assert restored.rationale == "Target person is seated directly ahead"


# =============================================================================
# 3. CognitiveStrategy success rate computation with 0 outcomes
# =============================================================================

def test_cognitive_strategy_success_rate_zero_outcomes():
    strat = CognitiveStrategy(strategy_id="s0", name="Zero Outcomes")
    assert strat.success_count == 0
    assert strat.failure_count == 0
    # Prior belief default with zero outcomes is 1.0
    assert strat.get_success_rate() == 1.0


# =============================================================================
# 4. CognitiveStrategy success rate computation with mixed outcomes
# =============================================================================

def test_cognitive_strategy_success_rate_mixed_outcomes():
    strat = CognitiveStrategy(strategy_id="s1", name="Mixed Outcomes")
    strat.record_outcome(True)
    strat.record_outcome(True)
    strat.record_outcome(True)
    strat.record_outcome(False)

    assert strat.success_count == 3
    assert strat.failure_count == 1
    assert strat.get_success_rate() == pytest.approx(0.75, abs=1e-3)


# =============================================================================
# 5. MetacognitiveEngine strategy registration and retrieval
# =============================================================================

def test_metacognitive_engine_strategy_registration_and_retrieval():
    engine = MetacognitiveEngine()
    s1 = CognitiveStrategy(strategy_id="s1", name="Strategy 1")
    s2 = CognitiveStrategy(strategy_id="s2", name="Strategy 2")

    engine.register_strategy(s1)
    engine.register_strategy(s2)

    assert engine.get_strategy("s1") == s1
    assert engine.get_strategy("s2") == s2
    assert engine.get_strategy("nonexistent") is None

    all_strats = engine.get_all_strategies()
    assert len(all_strats) == 2
    # First registered strategy is active by default
    assert engine.get_active_strategy() == s1


# =============================================================================
# 6. MetacognitiveEngine set_active_strategy transitions
# =============================================================================

def test_metacognitive_engine_set_active_strategy_transitions():
    engine = MetacognitiveEngine()
    s1 = CognitiveStrategy(strategy_id="s1", name="Strategy 1")
    s2 = CognitiveStrategy(strategy_id="s2", name="Strategy 2")
    engine.register_strategy(s1)
    engine.register_strategy(s2)

    active = engine.set_active_strategy("s2", rationale="Transitioned due to crowd noise")
    assert active is not None
    assert active.strategy_id == "s2"
    assert active.status == StrategyStatus.ACTIVE
    assert active.rationale == "Transitioned due to crowd noise"
    assert engine.get_active_strategy() == s2

    # Setting unknown strategy returns None and does not change active strategy
    assert engine.set_active_strategy("s_unknown") is None
    assert engine.get_active_strategy() == s2


# =============================================================================
# 7. MetacognitiveEngine outcome recording updates active strategy
# =============================================================================

def test_metacognitive_engine_outcome_recording_updates_active_strategy():
    engine = MetacognitiveEngine()
    s1 = CognitiveStrategy(strategy_id="s1", name="Active Strat")
    engine.register_strategy(s1)
    engine.set_active_strategy("s1")

    # Record success
    engine.record_outcome_for_strategy(success=True)
    assert s1.success_count == 1
    assert s1.failure_count == 0
    assert engine.get_recent_success_rate() == 1.0
    assert engine.get_recent_error_rate() == 0.0

    # Record failure
    err = PredictionError(
        expectation_id="exp_1",
        matched=False,
        mismatch_score=0.8,
        mismatch_type="VALUE_MISMATCH",
        confidence_impact=-0.1,
        uncertainty_impact=0.1,
    )
    engine.record_outcome_for_strategy(success=False, prediction_error=err)
    assert s1.failure_count == 1
    assert engine.current_state.repeated_failure_count == 1

    # Record another success resets consecutive failure counter
    engine.record_outcome_for_strategy(success=True)
    assert engine.current_state.repeated_failure_count == 0


# =============================================================================
# 8. MetacognitiveEngine outcome recording with no active strategy
# =============================================================================

def test_metacognitive_engine_outcome_recording_no_active_strategy():
    engine = MetacognitiveEngine()
    assert engine.get_active_strategy() is None

    # Should not crash even with no registered or active strategy
    engine.record_outcome_for_strategy(success=False)
    assert engine.current_state.repeated_failure_count == 1
    assert engine.get_recent_error_rate() == 1.0


# =============================================================================
# 9. InformationSufficiency assessment with sufficient data
# =============================================================================

def test_information_sufficiency_assessment_sufficient_data():
    engine = MetacognitiveEngine()
    goal = Goal(
        goal_id="g1",
        goal_type=GoalType.SOCIAL,
        description="Interact with p1",
        metadata={"target_person_id": "p1"},
    )
    perception = {
        "people": [{"person_id": "p1", "is_present": True}],
        "environment": {"front_clearance_m": 2.0},
        "last_sensor_update_ts": time.time(),
    }
    suff = engine.assess_information_sufficiency(
        active_goal=goal,
        perception_data=perception,
        uncertainty=0.2,
        now=time.time(),
    )
    assert suff == InformationSufficiency.SUFFICIENT


# =============================================================================
# 10. InformationSufficiency assessment with missing goal perception
# =============================================================================

def test_information_sufficiency_assessment_missing_goal_perception():
    engine = MetacognitiveEngine()
    goal = Goal(
        goal_id="g1",
        goal_type=GoalType.SOCIAL,
        description="Interact with p_missing",
        metadata={"target_person_id": "p_missing"},
    )
    perception = {
        "people": [{"person_id": "other_person", "is_present": True}],
        "environment": {"front_clearance_m": 2.0},
        "last_sensor_update_ts": time.time(),
    }
    suff = engine.assess_information_sufficiency(
        active_goal=goal,
        perception_data=perception,
        uncertainty=0.2,
        now=time.time(),
    )
    assert suff == InformationSufficiency.INSUFFICIENT


# =============================================================================
# 11. InformationSufficiency assessment with stale perception
# =============================================================================

def test_information_sufficiency_assessment_stale_perception():
    engine = MetacognitiveEngine()
    now = 1000.0
    perception = {
        "people": [{"person_id": "p1"}],
        "last_sensor_update_ts": now - 10.0,  # 10s old, exceeds DEFAULT_STALE_PERCEPTION_SECONDS
    }
    suff = engine.assess_information_sufficiency(
        perception_data=perception,
        uncertainty=0.2,
        now=now,
    )
    assert suff == InformationSufficiency.STALE


# =============================================================================
# 12. InformationSufficiency assessment with high uncertainty
# =============================================================================

def test_information_sufficiency_assessment_high_uncertainty():
    engine = MetacognitiveEngine()
    perception = {
        "people": [{"person_id": "p1"}],
        "last_sensor_update_ts": time.time(),
    }
    suff = engine.assess_information_sufficiency(
        perception_data=perception,
        uncertainty=0.85,  # High uncertainty >= 0.75
        now=time.time(),
    )
    assert suff == InformationSufficiency.INSUFFICIENT


# =============================================================================
# 13. Conflict detection: GOAL_SAFETY_CONFLICT on obstacle
# =============================================================================

def test_conflict_detection_goal_safety_conflict_on_obstacle():
    engine = MetacognitiveEngine()
    goal = Goal(goal_id="g_nav", goal_type=GoalType.TASK, description="Navigate")
    perception = {
        "environment": {"front_clearance_m": 0.35},  # Critical proximity < 0.50m
    }
    conflicts = engine.detect_conflicts(
        active_goal=goal,
        perception_data=perception,
        confidence=0.7,
        uncertainty=0.2,
        now=time.time(),
    )
    assert len(conflicts) >= 1
    safety_conflict = next(c for c in conflicts if c.conflict_type == "GOAL_SAFETY_CONFLICT")
    assert safety_conflict.severity >= 0.8
    assert safety_conflict.evidence["front_clearance_m"] == 0.35


# =============================================================================
# 14. Conflict detection: CONFIDENCE_PERFORMANCE_MISMATCH (overconfidence)
# =============================================================================

def test_conflict_detection_overconfidence_mismatch():
    engine = MetacognitiveEngine()
    # Record two consecutive failures
    engine.record_outcome_for_strategy(success=False)
    engine.record_outcome_for_strategy(success=False)

    conflicts = engine.detect_conflicts(
        confidence=0.85,  # High confidence contradicts failures
        uncertainty=0.2,
        now=time.time(),
    )
    assert len(conflicts) >= 1
    calib_conflict = next(c for c in conflicts if c.conflict_type == "CONFIDENCE_PERFORMANCE_MISMATCH")
    assert calib_conflict.severity == pytest.approx(0.7, abs=1e-3)


# =============================================================================
# 15. Conflict detection: STRATEGY_PERSISTENCE_FAILURE on repeated errors
# =============================================================================

def test_conflict_detection_strategy_persistence_failure():
    engine = MetacognitiveEngine(repeated_failure_threshold=3)
    strat = CognitiveStrategy(strategy_id="strat_stuck", name="Stuck Strategy")
    engine.register_strategy(strat)
    engine.set_active_strategy("strat_stuck")

    for _ in range(3):
        engine.record_outcome_for_strategy(success=False)

    conflicts = engine.detect_conflicts(
        confidence=0.5,
        uncertainty=0.5,
        now=time.time(),
    )
    assert len(conflicts) >= 1
    persist_conflict = next(c for c in conflicts if c.conflict_type == "STRATEGY_PERSISTENCE_FAILURE")
    assert persist_conflict.severity == pytest.approx(0.8, abs=1e-3)
    assert "strat_stuck" in persist_conflict.involved_strategy_ids


# =============================================================================
# 16. Conflict detection: no conflict under normal nominal conditions
# =============================================================================

def test_conflict_detection_nominal_no_conflicts():
    engine = MetacognitiveEngine()
    goal = Goal(goal_id="g_norm", goal_type=GoalType.SOCIAL, description="Social")
    perception = {
        "environment": {"front_clearance_m": 2.5},
    }
    conflicts = engine.detect_conflicts(
        active_goal=goal,
        perception_data=perception,
        confidence=0.7,
        uncertainty=0.2,
        now=time.time(),
    )
    assert len(conflicts) == 0


# =============================================================================
# 17. Confidence calibration: OVERCONFIDENT categorization
# =============================================================================

def test_confidence_calibration_overconfident():
    engine = MetacognitiveEngine()
    for _ in range(4):
        engine.record_outcome_for_strategy(success=False)

    calib = engine.get_confidence_calibration(confidence=0.85)
    assert calib == "OVERCONFIDENT"


# =============================================================================
# 18. Confidence calibration: UNDERCONFIDENT categorization
# =============================================================================

def test_confidence_calibration_underconfident():
    engine = MetacognitiveEngine()
    for _ in range(5):
        engine.record_outcome_for_strategy(success=True)

    calib = engine.get_confidence_calibration(confidence=0.35)
    assert calib == "UNDERCONFIDENT"


# =============================================================================
# 19. Confidence calibration: WELL_CALIBRATED categorization
# =============================================================================

def test_confidence_calibration_well_calibrated():
    engine = MetacognitiveEngine()
    engine.record_outcome_for_strategy(success=True)
    engine.record_outcome_for_strategy(success=True)
    engine.record_outcome_for_strategy(success=False)

    calib = engine.get_confidence_calibration(confidence=0.65)
    assert calib == "WELL_CALIBRATED"


# =============================================================================
# 20. Reassessment trigger produces CognitiveDecision with REASSESS type
# =============================================================================

def test_reassessment_trigger_produces_decision():
    engine = MetacognitiveEngine()
    triggered, decision = engine.trigger_reassessment("prediction_divergence", now=100.0)

    assert triggered is True
    assert decision is not None
    assert decision.decision_type == CognitiveDecisionType.REASSESS
    assert decision.reason == "prediction_divergence"
    assert decision.timestamp == 100.0


# =============================================================================
# 21. Reassessment trigger respects cooldown suppression
# =============================================================================

def test_reassessment_trigger_cooldown_suppression():
    engine = MetacognitiveEngine(reassessment_cooldown_s=2.0)
    triggered1, dec1 = engine.trigger_reassessment("first_anomaly", now=100.0)
    assert triggered1 is True

    # Immediate call within 2.0s cooldown must be suppressed
    triggered2, dec2 = engine.trigger_reassessment("second_anomaly", now=101.0)
    assert triggered2 is False
    assert dec2 is None


# =============================================================================
# 22. Reassessment trigger cooldown expires allowing subsequent trigger
# =============================================================================

def test_reassessment_trigger_cooldown_expires():
    engine = MetacognitiveEngine(reassessment_cooldown_s=2.0)
    triggered1, _ = engine.trigger_reassessment("first_anomaly", now=100.0)
    assert triggered1 is True

    # After 2.5s (> 2.0s cooldown), second trigger succeeds
    triggered2, dec2 = engine.trigger_reassessment("second_anomaly", now=102.5)
    assert triggered2 is True
    assert dec2 is not None
    assert dec2.decision_type == CognitiveDecisionType.REASSESS


# =============================================================================
# 23. CognitiveDecision is emitted as SEEK_INFORMATION when data is insufficient
# =============================================================================

def test_cognitive_decision_seek_information_on_insufficient_data():
    engine = MetacognitiveEngine()
    goal = Goal(
        goal_id="g_target",
        goal_type=GoalType.SOCIAL,
        description="Target person",
        metadata={"target_person_id": "p_target"},
    )
    perception = {"people": []}  # Missing required person

    state, decision = engine.evaluate_metacognitive_state(
        active_goal=goal,
        perception_data=perception,
        confidence=0.7,
        uncertainty=0.2,
        now=100.0,
    )
    assert state.information_sufficiency == InformationSufficiency.INSUFFICIENT
    assert decision is not None
    assert decision.decision_type == CognitiveDecisionType.SEEK_INFORMATION
    assert decision.target_goal_id == "g_target"


# =============================================================================
# 24. CognitiveDecision is emitted as REEVALUATE_GOAL or REASSESS on safety conflict
# =============================================================================

def test_cognitive_decision_reevaluate_goal_on_safety_conflict():
    engine = MetacognitiveEngine(reassessment_cooldown_s=2.0)
    goal = Goal(goal_id="g_nav", goal_type=GoalType.TASK, description="Navigate")
    perception = {"environment": {"front_clearance_m": 0.2}}  # Critical obstacle

    # 1. First trigger emits REASSESS (due to critical conflict)
    state, decision = engine.evaluate_metacognitive_state(
        active_goal=goal,
        perception_data=perception,
        now=100.0,
    )
    assert state.cognitive_conflict_state == "DETECTED"
    assert decision is not None
    assert decision.decision_type in (CognitiveDecisionType.REASSESS, CognitiveDecisionType.REEVALUATE_GOAL)

    # 2. Inside cooldown, critical conflict falls back to REEVALUATE_GOAL
    state2, decision2 = engine.evaluate_metacognitive_state(
        active_goal=goal,
        perception_data=perception,
        now=100.5,
    )
    assert decision2 is not None
    assert decision2.decision_type == CognitiveDecisionType.REEVALUATE_GOAL
    assert decision2.target_goal_id == "g_nav"


# =============================================================================
# 25. CognitiveDecision is emitted as CONTINUE under nominal state
# =============================================================================

def test_cognitive_decision_continue_under_nominal_state():
    engine = MetacognitiveEngine()
    goal = Goal(goal_id="g_nominal", goal_type=GoalType.MAINTENANCE, description="Nominal maintenance")
    perception = {
        "environment": {"front_clearance_m": 3.0},
        "last_sensor_update_ts": 100.0,
    }

    state, decision = engine.evaluate_metacognitive_state(
        active_goal=goal,
        perception_data=perception,
        confidence=0.8,
        uncertainty=0.1,
        now=100.0,
    )
    assert state.cognitive_status == "NORMAL"
    assert decision is not None
    assert decision.decision_type == CognitiveDecisionType.CONTINUE


# =============================================================================
# 26. CognitiveDecision serialization to_dict / from_dict roundtrip
# =============================================================================

def test_cognitive_decision_serialization_roundtrip():
    dec = CognitiveDecision(
        decision_id="dec_roundtrip_001",
        decision_type=CognitiveDecisionType.REVIEW_STRATEGY,
        reason="success_rate_fell_below_tolerance",
        target_strategy_id="strat_voice_id",
        target_goal_id="goal_listen",
        metadata={"rolling_avg": 0.35, "threshold": 0.50},
        timestamp=1234567.89,
    )
    d = dec.to_dict()
    restored = CognitiveDecision.from_dict(d)

    assert restored.decision_id == "dec_roundtrip_001"
    assert restored.decision_type == CognitiveDecisionType.REVIEW_STRATEGY
    assert restored.reason == "success_rate_fell_below_tolerance"
    assert restored.target_strategy_id == "strat_voice_id"
    assert restored.target_goal_id == "goal_listen"
    assert restored.metadata["rolling_avg"] == 0.35
    assert restored.timestamp == 1234567.89


# =============================================================================
# 27. SelfModel.get_metacognitive_state integration
# =============================================================================

def test_self_model_metacognitive_state_integration():
    model = SelfModel()
    strat = CognitiveStrategy(strategy_id="strat_model", name="Model Strat")
    model.metacognitive_engine.register_strategy(strat)
    model.set_active_strategy("strat_model")

    meta_state = model.get_metacognitive_state()
    assert isinstance(meta_state, MetacognitiveState)
    assert meta_state.current_strategy_id == "strat_model"

    # Context inclusion
    ctx = model.get_cognitive_context()
    assert ctx.metacognitive_state is not None
    assert ctx.metacognitive_state["current_strategy_id"] == "strat_model"


# =============================================================================
# 28. SelfModel.evaluate_outcome updates MetacognitiveEngine
# =============================================================================

def test_self_model_evaluate_outcome_updates_metacognitive_engine():
    model = SelfModel()
    strat = CognitiveStrategy(strategy_id="strat_eval", name="Evaluation Strat")
    model.metacognitive_engine.register_strategy(strat)
    model.set_active_strategy("strat_eval")

    pred = Prediction(
        prediction_id="pred_eval_01",
        action_id="act_move",
        expected_state={"front_distance": 2.0},
        expected_by=time.time() + 10.0,
    )
    model.register_prediction(pred)

    # Actual outcome with severe discrepancy
    actual = ActualOutcome(
        outcome_id="out_eval_01",
        expectation_id=pred.prediction_id,
        actual_state={"front_distance": 0.5},
        timestamp=time.time(),
    )
    err = model.evaluate_outcome(actual)
    assert err is not None
    assert err.matched is False

    # Verify MetacognitiveEngine recorded the failure
    assert strat.failure_count == 1
    assert model.metacognitive_engine.current_state.repeated_failure_count == 1


# =============================================================================
# 29. CognitiveLoop.step produces MetacognitiveState in result
# =============================================================================

def test_cognitive_loop_step_produces_metacognitive_state():
    loop = CognitiveLoop()
    result = loop.step({"people": [], "environment": {"front_clearance_m": 2.0}})

    assert isinstance(result, CognitiveCycleResult)
    assert result.metacognitive_state is not None
    assert isinstance(result.metacognitive_state, MetacognitiveState)
    assert result.cognitive_decision is not None
    assert isinstance(result.cognitive_decision, CognitiveDecision)
    assert result.cognitive_context is not None
    assert result.cognitive_context.metacognitive_state is not None


# =============================================================================
# 30. CognitiveLoop.step produces CognitiveDecision and records continuity transitions
# =============================================================================

def test_cognitive_loop_step_records_continuity_transitions():
    loop = CognitiveLoop()
    s1 = CognitiveStrategy(strategy_id="strat_nav_fast", name="Fast Nav")
    loop.metacognitive_engine.register_strategy(s1)
    loop.metacognitive_engine.set_active_strategy("strat_nav_fast")

    # Step 1: Nominal step
    res1 = loop.step({"environment": {"front_clearance_m": 2.5}})
    assert res1.metacognitive_state.cognitive_status == "NORMAL"

    # Step 2: Critical obstacle to trigger GOAL_SAFETY_CONFLICT and transition
    loop.self_state.current_goal = Goal(goal_id="g_nav", goal_type=GoalType.TASK, description="Navigate")
    res2 = loop.step({"environment": {"front_clearance_m": 0.2}})

    assert res2.metacognitive_state.cognitive_conflict_state == "DETECTED"
    transitions = loop.continuity_tracker.get_recent_transitions()
    conflict_txs = [t for t in transitions if t.transition_type == "CONFLICT_DETECTED"]
    assert len(conflict_txs) >= 1
    assert conflict_txs[-1].new_value == "DETECTED"

    # Reset cleans everything cleanly
    loop.reset()
    assert loop.metacognitive_engine.current_state.cognitive_conflict_state == "NONE"
    assert len(loop.continuity_tracker.get_recent_transitions()) == 0
