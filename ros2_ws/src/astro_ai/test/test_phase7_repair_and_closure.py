"""ASTRO V1 — Phase 7 Closure & Architecture Repair Regression Test Suite.

Verifies the 14 mandatory closure invariants:
  1. test_selfmodel_shared_live_state
  2. test_selfmodel_no_duplicate_engines
  3. test_acoustic_entity_runtime_path
  4. test_focus_never_orphaned
  5. test_acoustic_focus_information_sufficiency
  6. test_action_creates_prediction
  7. test_move_creates_prediction
  8. test_head_turn_prediction
  9. test_prediction_not_duplicated_per_cycle
 10. test_prediction_confirmed_by_sensor_outcome
 11. test_prediction_mismatch_updates_error
 12. test_behavior_same_state_no_transition
 13. test_safety_halt_reason_jitter_no_transition
 14. test_activity_matches_live_behavior
"""

from __future__ import annotations

import time
import pytest

from astro_ai.brain.cognitive_loop import CognitiveLoop
from astro_ai.brain.metacognitive_engine import MetacognitiveEngine
from astro_ai.brain.outcome_resolver import OutcomeResolver
from astro_ai.brain.prediction_engine import PredictionEngine
from astro_ai.brain.prediction_factory import ActionExpectationFactory
from astro_ai.brain.self_model import SelfModel
from astro_ai.brain.social_brain import SocialBrain
from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.behavior_types import BehaviorPriority, BehaviorStatus, BehaviorType, BehavioralIntent
from astro_ai.contracts.consciousness_types import (
    ActionIntent,
    ActualOutcome,
    CognitiveDecision,
    CognitiveDecisionType,
    InformationSufficiency,
    PredictionStatus,
    SelfState,
)
from astro_ai.contracts.person_state import EntityLifecycleState, UnifiedPersonState
from astro_ai.spatial.spatial_fusion import SpatialFusionEngine


class TestPhase7RepairAndClosure:

    # -------------------------------------------------------------------------
    # Test 1: SelfModel shares authoritative live SelfState
    # -------------------------------------------------------------------------
    def test_selfmodel_shared_live_state(self):
        loop = CognitiveLoop()
        self_model = loop.self_model

        assert self_model is not None
        assert self_model.self_state is loop.self_state

        # Mutate loop self_state and verify SelfModel sees identical live state
        loop.self_state.confidence = 0.88
        loop.self_state.current_head_yaw_deg = 24.5
        assert self_model.self_state.confidence == 0.88
        assert self_model.get_self_state().current_head_yaw_deg == 24.5

    # -------------------------------------------------------------------------
    # Test 2: SelfModel creates NO duplicate engines
    # -------------------------------------------------------------------------
    def test_selfmodel_no_duplicate_engines(self):
        loop = CognitiveLoop()
        self_model = loop.self_model

        assert self_model.prediction_engine is loop.prediction_engine
        assert self_model.metacognitive_engine is loop.metacognitive_engine
        assert self_model.continuity_tracker is loop.continuity_tracker
        assert self_model.affective_manager is loop.affective_manager

        # SocialBrain sharing CognitiveLoop's engines
        sb = SocialBrain(cognitive_loop=loop)
        assert sb.self_model.self_state is loop.self_state
        assert sb.self_model.prediction_engine is loop.prediction_engine
        assert sb.world_model is loop.world_model

    # -------------------------------------------------------------------------
    # Test 3: Acoustic-only ReSpeaker input enters WorldModel as ACOUSTIC_ENTITY
    # -------------------------------------------------------------------------
    def test_acoustic_entity_runtime_path(self):
        spatial = SpatialFusionEngine()
        spatial.update_audio_perception(doa_deg=45.0, is_speaking=True, vad_active=True)

        people = spatial.compute_fusion()
        assert len(people) >= 1
        acoustic_p = people[0]

        assert acoustic_p.entity_type == "ACOUSTIC_ENTITY"
        assert acoustic_p.person_id == "audio_speaker_1"
        assert acoustic_p.has_vision is False
        assert acoustic_p.has_audio is True
        assert acoustic_p.azimuth_deg == 45.0

        wm = WorldModel()
        wm.update_people(people)
        assert "audio_speaker_1" in wm._people
        assert wm.get_person("audio_speaker_1") is not None
        assert wm.get_person("audio_speaker_1").has_audio is True

    # -------------------------------------------------------------------------
    # Test 4: Focus never points to an orphan entity outside WorldModel
    # -------------------------------------------------------------------------
    def test_focus_never_orphaned(self):
        loop = CognitiveLoop()

        # Step with an orphan target ID that does not exist in perception or WorldModel
        res = loop.step({"active_target_id": "non_existent_orphan_99", "people": []})

        assert loop.world_model.focus_target is None
        assert loop.world_model.focus_target != "non_existent_orphan_99"

        # Now add a valid person and attempt to pass an orphan active target
        p_valid = UnifiedPersonState(
            person_id="valid_person_1",
            distance_m=1.8,
            azimuth_deg=10.0,
            is_present=True,
            tracking_state=EntityLifecycleState.STATIONARY,
        )
        res2 = loop.step({
            "active_target_id": "non_existent_orphan_99",
            "people": [p_valid],
        })
        # Focus must be valid entity or None; never orphan
        assert loop.world_model.focus_target in [None, "valid_person_1"]
        assert loop.world_model.focus_target != "non_existent_orphan_99"

    # -------------------------------------------------------------------------
    # Test 5: Acoustic focus without vision is flagged INSUFFICIENT
    # -------------------------------------------------------------------------
    def test_acoustic_focus_information_sufficiency(self):
        meta = MetacognitiveEngine()
        wm = WorldModel()
        acoustic_p = UnifiedPersonState(
            person_id="audio_speaker_1",
            entity_type="ACOUSTIC_ENTITY",
            has_vision=False,
            has_audio=True,
            is_present=True,
            azimuth_deg=50.0,
        )
        wm.update_people([acoustic_p])
        wm.focus_target = "audio_speaker_1"

        suff = meta.assess_information_sufficiency(perception_data=wm)
        assert suff == InformationSufficiency.INSUFFICIENT

    # -------------------------------------------------------------------------
    # Test 6: Action creates measurable prediction (no bool placeholders)
    # -------------------------------------------------------------------------
    def test_action_creates_prediction(self):
        action = ActionIntent(
            action_type="turn_head",
            target="target_speaker",
            parameters={"target_yaw_deg": 35.0},
        )
        exp = ActionExpectationFactory.create_expectation_for_action(action)

        assert exp is not None
        assert exp.action_type == "turn_head"
        assert len(exp.expected_outcome) > 0
        assert "head_yaw_deg" in exp.expected_outcome
        assert exp.expected_outcome["head_yaw_deg"] == 35.0
        # Measurable outcome verification (no boolean placeholders)
        for key, val in exp.expected_outcome.items():
            assert not isinstance(val, bool), f"Placeholder boolean found for {key}"

    # -------------------------------------------------------------------------
    # Test 7: Robot movement creates measurable outcome prediction
    # -------------------------------------------------------------------------
    def test_move_creates_prediction(self):
        # Move forward
        action_move = ActionIntent(
            action_type="move_robot",
            parameters={"linear_x": 0.25, "distance_m": 0.75},
        )
        exp_move = ActionExpectationFactory.create_expectation_for_action(action_move)
        assert exp_move.expected_outcome.get("velocity") == 0.25
        assert exp_move.expected_outcome.get("distance_traveled_m") == 0.75

        # Stop command
        action_stop = ActionIntent(
            action_type="move_robot",
            parameters={"linear_x": 0.0, "angular_z": 0.0},
        )
        exp_stop = ActionExpectationFactory.create_expectation_for_action(action_stop)
        assert exp_stop.expected_outcome.get("velocity") == 0.0
        assert exp_stop.expected_outcome.get("is_stopped") == 1.0

    # -------------------------------------------------------------------------
    # Test 8: Head turn creates target head yaw outcome prediction
    # -------------------------------------------------------------------------
    def test_head_turn_prediction(self):
        action = ActionIntent(
            action_type="turn_head",
            parameters={"target_yaw_deg": -30.0},
        )
        exp = ActionExpectationFactory.create_expectation_for_action(action)
        assert exp.expected_outcome.get("head_yaw_deg") == -30.0

    # -------------------------------------------------------------------------
    # Test 9: Prediction is NOT duplicated per 10 Hz cycle for ongoing action
    # -------------------------------------------------------------------------
    def test_prediction_not_duplicated_per_cycle(self):
        loop = CognitiveLoop()
        p = UnifiedPersonState(
            person_id="p1",
            distance_m=2.0,
            azimuth_deg=25.0,
            is_present=True,
            tracking_state=EntityLifecycleState.APPEARED,
        )

        # Step 1: generates action and registers prediction
        res1 = loop.step({"people": [p]})
        initial_preds_count = len(loop.prediction_engine.active_predictions)
        assert initial_preds_count >= 1

        # Step 2: same ongoing stimulus, same action signature
        res2 = loop.step({"people": [p]})
        assert len(loop.prediction_engine.active_predictions) == initial_preds_count

    # -------------------------------------------------------------------------
    # Test 10: Prediction confirmed by sensor outcome updates confidence
    # -------------------------------------------------------------------------
    def test_prediction_confirmed_by_sensor_outcome(self):
        pe = PredictionEngine()
        pred = pe.create_perceptual_prediction(
            prediction_type="turn_head",
            target_id="target_1",
            expected_state={"head_yaw_deg": 30.0},
            confidence_weight=1.0,
        )
        # Outcome matching within tolerance (30.0 vs 31.0)
        outcome = ActualOutcome(
            outcome_id="out_1",
            expectation_id=pred.prediction_id,
            actual_state={"head_yaw_deg": 31.0},
        )
        err = pe.evaluate_outcome(outcome)

        assert err.matched is True
        assert err.mismatch_score == 0.0
        assert err.confidence_impact > 0.0
        assert pred.status == PredictionStatus.CONFIRMED

    # -------------------------------------------------------------------------
    # Test 11: Prediction mismatch updates prediction_error and drops confidence
    # -------------------------------------------------------------------------
    def test_prediction_mismatch_updates_error(self):
        pe = PredictionEngine()
        pred = pe.create_perceptual_prediction(
            prediction_type="turn_head",
            target_id="target_1",
            expected_state={"head_yaw_deg": 45.0},
            confidence_weight=1.0,
        )
        # Outcome significantly deviating (0.0° vs 45.0°)
        outcome = ActualOutcome(
            outcome_id="out_2",
            expectation_id=pred.prediction_id,
            actual_state={"head_yaw_deg": 0.0},
        )
        err = pe.evaluate_outcome(outcome)

        assert err.matched is False
        assert err.mismatch_score > 0.5
        assert err.confidence_impact < 0.0
        assert pred.status == PredictionStatus.MISMATCH

    # -------------------------------------------------------------------------
    # Test 12: Same behavior state produces NO redundant transition event
    # -------------------------------------------------------------------------
    def test_behavior_same_state_no_transition(self):
        loop = CognitiveLoop()
        # Cycle 1: Obstacle at 0.3m -> enters SAFETY_HALT
        res1 = loop.step({"environment": {"front_clearance_m": 0.3}})
        assert res1.behavioral_intent is not None
        assert res1.behavioral_intent.behavior_type == BehaviorType.SAFETY_HALT

        # Drain initial events
        loop.event_bus.drain_events()

        # Cycle 2: Obstacle still at 0.3m -> remains in SAFETY_HALT
        res2 = loop.step({"environment": {"front_clearance_m": 0.3}})
        assert res2.behavioral_intent.behavior_type == BehaviorType.SAFETY_HALT

        events = loop.event_bus.get_unprocessed_events()
        # No new behavior transition event for staying in the same state
        transition_events = [e for e in events if "TRANSITION" in str(e.event_type)]
        assert len(transition_events) == 0

    # -------------------------------------------------------------------------
    # Test 13: Sensor distance jitter during SAFETY_HALT produces NO telemetry churn
    # -------------------------------------------------------------------------
    def test_safety_halt_reason_jitter_no_transition(self):
        loop = CognitiveLoop()
        # Cycle 1: 0.38m
        loop.step({"environment": {"front_clearance_m": 0.38}})
        sig1 = loop._last_telemetry_sig

        # Cycle 2: 0.40m (both < 0.45m threshold)
        loop.step({"environment": {"front_clearance_m": 0.40}})
        sig2 = loop._last_telemetry_sig

        # Telemetry signature filters out floating-point jitter
        assert sig1 == sig2

    # -------------------------------------------------------------------------
    # Test 14: Introspection current_activity matches live behavior
    # -------------------------------------------------------------------------
    def test_activity_matches_live_behavior(self):
        self_state = SelfState()

        self_state.current_behavior = "SAFETY_HALT"
        assert self_state.get_current_activity() == "Safety halt"

        self_state.current_behavior = "ATTEND"
        assert self_state.get_current_activity() == "Attending acoustic source"

        self_state.current_behavior = "TRACK"
        assert self_state.get_current_activity() == "Tracking interlocutor"

        self_state.current_behavior = "APPROACH"
        assert self_state.get_current_activity() == "Approaching target"

        self_state.current_behavior = "RETREAT"
        assert self_state.get_current_activity() == "Retreating for proxemic comfort"

        self_state.current_behavior = "EXPLORE"
        assert self_state.get_current_activity() == "Exploring surroundings"

        self_state.current_behavior = "SEARCH_ACOUSTIC_CANDIDATE"
        assert self_state.get_current_activity() == "Searching for acoustic source"
