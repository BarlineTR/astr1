"""ASTRO V1 — Phase 7: Behavioral Intelligence & Adaptive Interaction Test Suite.

Verifies:
  1. Person appeared triggers orientation
  2. Distant person triggers approach
  3. Close proximity triggers proxemics retreat
  4. Continuous speech triggers attentive listening nod
  5. Acoustic candidate triggers active perception search
  6. Visual face confirmed completes active perception behavior
  7. Timeout failure on active perception
  8. Multi-person focus retention during dialogue
  9. Spatial attention split prevents rash orientation jump
 10. Critical safety halts immediately preempt lower-priority behaviors
 11. Behavior completion lifecycle (APPROACH -> reached distance -> COMPLETED)
 12. Behavior failure lifecycle (timeout expired -> FAILED)
 13. Behavior interruption lifecycle (preempted by higher priority -> INTERRUPTED)
 14. Distance hysteresis prevents rapid flapping / chattering
 15. PredictionEngine integration (behavior expectation and outcome matching)
 16. Affective state modulation (urgency shortens dwell time)
 17. Zero-LLM deterministic operation (pure Python, 100% offline)
 18. CognitiveLoop end-to-end integration (produces behavioral_intent and action_intent)
 19. ActionManager execution of ActionIntent with hardware safety gates
 20. Sub-millisecond performance benchmark (< 1.0 ms execution per cycle)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock
import pytest

from astro_ai.action_manager import ActionManager, ActionResult
from astro_ai.brain.behavior_engine import BehaviorEngine
from astro_ai.brain.cognitive_loop import CognitiveLoop
from astro_ai.brain.prediction_engine import PredictionEngine
from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.behavior_types import (
    BehaviorPriority,
    BehaviorStatus,
    BehaviorType,
    BehavioralIntent,
    behavior_intent_to_action_intent,
)
from astro_ai.contracts.consciousness_types import (
    ActionIntent,
    ActualOutcome,
    CognitiveDecision,
    CognitiveDecisionType,
    Goal,
    GoalType,
    RobotAffectiveState,
    SelfState,
)
from astro_ai.contracts.person_state import EntityLifecycleState, UnifiedPersonState
from astro_ai.state_machine import RobotState


class TestPhase7BehavioralIntelligence:

    @pytest.fixture
    def world_model(self) -> WorldModel:
        return WorldModel()

    @pytest.fixture
    def self_state(self) -> SelfState:
        return SelfState()

    @pytest.fixture
    def behavior_engine(self) -> BehaviorEngine:
        return BehaviorEngine(min_dwell_time_s=1.0)

    # -------------------------------------------------------------------------
    # Test 1: Person appeared -> ORIENT_TO_STIMULUS
    # -------------------------------------------------------------------------
    def test_01_person_appeared_triggers_orientation(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        now = time.time()
        p = UnifiedPersonState(
            person_id="p_baran",
            name="Baran",
            distance_m=2.0,
            azimuth_deg=35.0,
            is_present=True,
            tracking_state=EntityLifecycleState.APPEARED,
        )
        world_model.update_people([p], now=now)

        intent = behavior_engine.step(world_model, self_state, now=now)
        assert intent.behavior_type == BehaviorType.ORIENT_TO_STIMULUS
        assert intent.status == BehaviorStatus.ACTIVE
        assert intent.parameters.get("target_yaw_deg") == 35.0

        act_intent = behavior_intent_to_action_intent(intent)
        assert act_intent is not None
        assert act_intent.action_type == "turn_head"
        assert act_intent.parameters.get("target_yaw_deg") == 35.0

    # -------------------------------------------------------------------------
    # Test 2: Distant person -> APPROACH_INTERLOCUTOR
    # -------------------------------------------------------------------------
    def test_02_distant_person_triggers_approach(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        now = time.time()
        self_state.focused_person_id = "p_baran"
        self_state.current_goal = Goal(
            goal_id="g_social", goal_type=GoalType.SOCIAL, description="Interact"
        )
        p = UnifiedPersonState(
            person_id="p_baran",
            name="Baran",
            distance_m=3.2,
            azimuth_deg=0.0,
            is_present=True,
        )
        world_model.update_people([p], now=now)
        world_model.update_environment(front_clearance_m=4.0)

        intent = behavior_engine.step(
            world_model, self_state, active_goal=self_state.current_goal, now=now
        )
        assert intent.behavior_type == BehaviorType.APPROACH_INTERLOCUTOR
        assert intent.status == BehaviorStatus.ACTIVE
        assert intent.parameters.get("direction") == "forward"

        act_intent = behavior_intent_to_action_intent(intent)
        assert act_intent is not None
        assert act_intent.action_type == "move_robot"
        assert act_intent.parameters.get("direction") == "forward"

    # -------------------------------------------------------------------------
    # Test 3: Close proximity -> MAINTAIN_SOCIAL_DISTANCE (retreat)
    # -------------------------------------------------------------------------
    def test_03_close_proximity_triggers_retreat(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        now = time.time()
        self_state.focused_person_id = "p_baran"
        p = UnifiedPersonState(
            person_id="p_baran",
            name="Baran",
            distance_m=0.55,  # Too close (<0.70m)
            azimuth_deg=0.0,
            is_present=True,
        )
        world_model.update_people([p], now=now)

        intent = behavior_engine.step(world_model, self_state, now=now)
        assert intent.behavior_type == BehaviorType.MAINTAIN_SOCIAL_DISTANCE
        assert intent.status == BehaviorStatus.ACTIVE
        assert intent.parameters.get("direction") == "backward"

        act_intent = behavior_intent_to_action_intent(intent)
        assert act_intent is not None
        assert act_intent.action_type == "move_robot"
        assert act_intent.parameters.get("direction") == "backward"

    # -------------------------------------------------------------------------
    # Test 4: Continuous user speech -> ATTENTIVE_LISTENING (nod)
    # -------------------------------------------------------------------------
    def test_04_active_speech_triggers_attentive_listening(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        t0 = time.time()
        self_state.focused_person_id = "p_baran"
        self_state.is_listening = True
        p = UnifiedPersonState(
            person_id="p_baran",
            name="Baran",
            distance_m=1.4,
            is_present=True,
            is_speaking=True,
        )
        world_model.update_people([p], now=t0)

        # First cycle: user just started speaking
        intent1 = behavior_engine.step(world_model, self_state, now=t0)
        assert intent1.behavior_type != BehaviorType.ATTENTIVE_LISTENING

        # 3.0 seconds later: continuous speech >= 2.5s triggers attentive nod
        t1 = t0 + 3.0
        intent2 = behavior_engine.step(world_model, self_state, now=t1)
        assert intent2.behavior_type == BehaviorType.ATTENTIVE_LISTENING
        assert intent2.status == BehaviorStatus.ACTIVE

        act_intent = behavior_intent_to_action_intent(intent2)
        assert act_intent is not None
        assert act_intent.action_type == "gesture"
        assert act_intent.parameters.get("gesture_name") == "nod"

    # -------------------------------------------------------------------------
    # Test 5: Acoustic candidate + SEEK_INFORMATION -> ACTIVE_PERCEPTION_SEARCH
    # -------------------------------------------------------------------------
    def test_05_active_perception_acoustic_stimulus(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        now = time.time()
        cog_dec = CognitiveDecision(
            decision_id="dec_seek_1",
            decision_type=CognitiveDecisionType.SEEK_INFORMATION,
            reason="active_perception_acoustic_attention",
            metadata={"stimulus_type": "AUDIO", "target_yaw_deg": -55.0, "entity_id": "ac_1"},
            timestamp=now,
        )

        intent = behavior_engine.step(world_model, self_state, cognitive_decision=cog_dec, now=now)
        assert intent.behavior_type == BehaviorType.ACTIVE_PERCEPTION_SEARCH
        assert intent.status == BehaviorStatus.ACTIVE
        assert intent.parameters.get("target_yaw_deg") == -55.0

        act_intent = behavior_intent_to_action_intent(intent)
        assert act_intent is not None
        assert act_intent.action_type == "turn_head"
        assert act_intent.parameters.get("target_yaw_deg") == -55.0

    # -------------------------------------------------------------------------
    # Test 6: Visual face confirmed completes active perception behavior
    # -------------------------------------------------------------------------
    def test_06_active_perception_face_verified_completion(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        t0 = time.time()
        cog_dec = CognitiveDecision(
            decision_id="dec_seek_2",
            decision_type=CognitiveDecisionType.SEEK_INFORMATION,
            reason="active_perception_acoustic_attention",
            metadata={"stimulus_type": "AUDIO", "target_yaw_deg": 40.0, "entity_id": "ac_2"},
            timestamp=t0,
        )
        active_intent = behavior_engine.step(world_model, self_state, cognitive_decision=cog_dec, now=t0)
        assert active_intent.behavior_type == BehaviorType.ACTIVE_PERCEPTION_SEARCH
        assert active_intent.status == BehaviorStatus.ACTIVE

        # Head turns, camera sees face 0.5s later!
        t1 = t0 + 0.5
        vis_person = UnifiedPersonState(
            person_id="p_found",
            distance_m=1.6,
            azimuth_deg=40.0,
            is_present=True,
            has_vision=True,
        )
        world_model.update_people([vis_person], now=t1)

        # Next step should evaluate completion!
        next_intent = behavior_engine.step(world_model, self_state, now=t1)
        # Check history for completion record
        history = behavior_engine.get_behavior_history()
        assert len(history) >= 1
        completed = [b for b in history if b.behavior_type == BehaviorType.ACTIVE_PERCEPTION_SEARCH]
        assert len(completed) == 1
        assert completed[0].status == BehaviorStatus.COMPLETED
        assert completed[0].reason == "face_verified_by_vision"

    # -------------------------------------------------------------------------
    # Test 7: Active perception timeout failure
    # -------------------------------------------------------------------------
    def test_07_active_perception_timeout_failure(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        t0 = time.time()
        cog_dec = CognitiveDecision(
            decision_id="dec_seek_3",
            decision_type=CognitiveDecisionType.SEEK_INFORMATION,
            reason="active_perception_acoustic_attention",
            metadata={"stimulus_type": "AUDIO", "target_yaw_deg": -70.0, "entity_id": "ghost"},
            timestamp=t0,
        )
        intent = behavior_engine.step(world_model, self_state, cognitive_decision=cog_dec, now=t0)
        assert intent.status == BehaviorStatus.ACTIVE

        # Timeout of active perception search is 2.5s
        t_expired = t0 + 3.0
        # No face ever appears
        behavior_engine.step(world_model, self_state, now=t_expired)

        history = behavior_engine.get_behavior_history()
        failed = [b for b in history if b.behavior_type == BehaviorType.ACTIVE_PERCEPTION_SEARCH]
        assert len(failed) == 1
        assert failed[0].status == BehaviorStatus.FAILED
        assert failed[0].reason == "timeout_expired"

    # -------------------------------------------------------------------------
    # Test 8: Multi-person focus retention during dialogue
    # -------------------------------------------------------------------------
    def test_08_multi_person_focus_retention(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        now = time.time()
        self_state.focused_person_id = "p_primary"
        self_state.operational_state = RobotState.SPEAKING

        p_prim = UnifiedPersonState(person_id="p_primary", distance_m=1.2, azimuth_deg=0.0, is_present=True)
        p_sec = UnifiedPersonState(person_id="p_secondary", distance_m=2.0, azimuth_deg=50.0, is_present=True)
        world_model.update_people([p_prim, p_sec], now=now)

        intent = behavior_engine.step(world_model, self_state, now=now)
        assert intent.behavior_type == BehaviorType.ACTIVE_SOCIAL_ENGAGEMENT
        assert intent.target_id == "p_primary"

    # -------------------------------------------------------------------------
    # Test 9: Spatial attention split does not rashly abandon interlocutor
    # -------------------------------------------------------------------------
    def test_09_sensor_conflict_prevents_rash_jump(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        now = time.time()
        self_state.focused_person_id = "p_primary"
        p_vis = UnifiedPersonState(person_id="p_primary", distance_m=1.3, azimuth_deg=0.0, is_present=True, has_vision=True)
        p_ac = UnifiedPersonState(person_id="ac_lateral", distance_m=2.5, azimuth_deg=65.0, is_present=True, entity_type="ACOUSTIC_ENTITY")
        world_model.update_people([p_vis, p_ac], now=now)

        # Conflict detected between visual and acoustic entities
        conflicts = world_model.detect_conflicts()
        assert len(conflicts) > 0
        assert conflicts[0]["type"] == "SPATIAL_ATTENTION_SPLIT"

        cog_dec = CognitiveDecision(
            decision_id="dec_split",
            decision_type=CognitiveDecisionType.SEEK_INFORMATION,
            reason="active_perception_acoustic_attention",
            metadata={"stimulus_type": "AUDIO", "target_yaw_deg": 65.0, "entity_id": "ac_lateral"},
            timestamp=now,
        )

        intent = behavior_engine.step(world_model, self_state, cognitive_decision=cog_dec, now=now)
        # Should NOT be ACTIVE_PERCEPTION_SEARCH jumping 65 degrees away! Should be PUZZLED_TILT!
        assert intent.behavior_type == BehaviorType.PUZZLED_TILT

    # -------------------------------------------------------------------------
    # Test 10: Critical safety halt immediately preempts lower-priority behaviors
    # -------------------------------------------------------------------------
    def test_10_critical_safety_preemption(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        t0 = time.time()
        self_state.focused_person_id = "p_target"
        p = UnifiedPersonState(person_id="p_target", distance_m=3.0, azimuth_deg=0.0, is_present=True)
        world_model.update_people([p], now=t0)
        world_model.update_environment(front_clearance_m=4.0)

        intent1 = behavior_engine.step(world_model, self_state, now=t0)
        assert intent1.behavior_type == BehaviorType.APPROACH_INTERLOCUTOR
        assert intent1.status == BehaviorStatus.ACTIVE

        # Suddenly an obstacle is detected at 0.35m (< 0.50m)
        t1 = t0 + 0.2
        world_model.update_environment(front_clearance_m=0.35, is_obstacle_near=True)

        intent2 = behavior_engine.step(world_model, self_state, now=t1)
        assert intent2.behavior_type == BehaviorType.SAFETY_HALT
        assert intent2.priority == BehaviorPriority.CRITICAL_SAFETY

        # Verify approach behavior was interrupted
        history = behavior_engine.get_behavior_history()
        interrupted = [b for b in history if b.behavior_type == BehaviorType.APPROACH_INTERLOCUTOR]
        assert len(interrupted) == 1
        assert interrupted[0].status == BehaviorStatus.INTERRUPTED
        assert "preempted_by_SAFETY_HALT" in interrupted[0].reason

    # -------------------------------------------------------------------------
    # Test 11: Approach reaches comfortable distance -> COMPLETED
    # -------------------------------------------------------------------------
    def test_11_behavior_completion_lifecycle(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        t0 = time.time()
        self_state.focused_person_id = "p_baran"
        p = UnifiedPersonState(person_id="p_baran", distance_m=2.8, azimuth_deg=0.0, is_present=True)
        world_model.update_people([p], now=t0)
        world_model.update_environment(front_clearance_m=4.0)

        intent = behavior_engine.step(world_model, self_state, now=t0)
        assert intent.behavior_type == BehaviorType.APPROACH_INTERLOCUTOR
        assert intent.status == BehaviorStatus.ACTIVE

        # After walking, person is now at 1.6m (<= 1.8m)
        t1 = t0 + 1.2
        p.distance_m = 1.6
        world_model.update_people([p], now=t1)

        behavior_engine.step(world_model, self_state, now=t1)
        history = behavior_engine.get_behavior_history()
        completed = [b for b in history if b.behavior_type == BehaviorType.APPROACH_INTERLOCUTOR]
        assert len(completed) == 1
        assert completed[0].status == BehaviorStatus.COMPLETED
        assert completed[0].reason == "reached_interaction_distance"

    # -------------------------------------------------------------------------
    # Test 12: Behavior failure lifecycle on timeout
    # -------------------------------------------------------------------------
    def test_12_behavior_failure_lifecycle(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        t0 = time.time()
        p = UnifiedPersonState(person_id="p_new", distance_m=2.0, azimuth_deg=20.0, is_present=True)
        world_model.update_people([p], now=t0)

        intent = behavior_engine.step(world_model, self_state, now=t0)
        assert intent.behavior_type == BehaviorType.ORIENT_TO_STIMULUS
        assert intent.status == BehaviorStatus.ACTIVE

        # Time exceeds timeout (2.0s for orient)
        t_expired = t0 + 2.5
        behavior_engine.step(world_model, self_state, now=t_expired)

        history = behavior_engine.get_behavior_history()
        failed = [b for b in history if b.behavior_type == BehaviorType.ORIENT_TO_STIMULUS]
        assert len(failed) == 1
        assert failed[0].status == BehaviorStatus.FAILED
        assert failed[0].reason == "timeout_expired"

    # -------------------------------------------------------------------------
    # Test 13: Higher priority behavior preempts active behavior
    # -------------------------------------------------------------------------
    def test_13_behavior_interruption_lifecycle(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        t0 = time.time()
        # Start in idle attentive
        intent_idle = behavior_engine.step(world_model, self_state, now=t0)
        assert intent_idle.behavior_type == BehaviorType.IDLE_ATTENTIVE

        # User starts speaking -> ACTIVE_SOCIAL_ENGAGEMENT (priority 0.8) preempts IDLE (0.1)
        t1 = t0 + 0.1
        self_state.is_speaking = True
        intent_speaking = behavior_engine.step(world_model, self_state, now=t1)
        assert intent_speaking.behavior_type == BehaviorType.ACTIVE_SOCIAL_ENGAGEMENT

        history = behavior_engine.get_behavior_history()
        interrupted = [b for b in history if b.behavior_type == BehaviorType.IDLE_ATTENTIVE]
        assert len(interrupted) == 1
        assert interrupted[0].status == BehaviorStatus.INTERRUPTED

    # -------------------------------------------------------------------------
    # Test 14: Distance hysteresis prevents chattering
    # -------------------------------------------------------------------------
    def test_14_hysteresis_prevents_flapping(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        t0 = time.time()
        self_state.focused_person_id = "p_chatter"
        p = UnifiedPersonState(person_id="p_chatter", distance_m=2.6, azimuth_deg=0.0, is_present=True)
        world_model.update_people([p], now=t0)
        world_model.update_environment(front_clearance_m=4.0)

        # 1. At 2.6m (> 2.5m), start approaching
        intent1 = behavior_engine.step(world_model, self_state, now=t0)
        assert intent1.behavior_type == BehaviorType.APPROACH_INTERLOCUTOR
        assert behavior_engine._is_approaching is True

        # 2. At 2.4m, should CONTINUE approaching (does NOT flap to STOP because hysteresis boundary is 1.8m)
        t1 = t0 + 0.2
        p.distance_m = 2.4
        intent2 = behavior_engine.step(world_model, self_state, now=t1)
        assert intent2.behavior_type == BehaviorType.APPROACH_INTERLOCUTOR
        assert behavior_engine._is_approaching is True

        # 3. At 1.7m (<= 1.8m), stops approaching
        t2 = t0 + 1.2
        p.distance_m = 1.7
        intent3 = behavior_engine.step(world_model, self_state, now=t2)
        assert behavior_engine._is_approaching is False

    # -------------------------------------------------------------------------
    # Test 15: PredictionEngine integration (expectation and outcome verification)
    # -------------------------------------------------------------------------
    def test_15_prediction_engine_integration(self):
        pred_eng = PredictionEngine()
        now = time.time()

        pred = pred_eng.create_perceptual_prediction(
            prediction_type="EXPECT_FACE_AFTER_HEAD_ATTENTION",
            target_id="cand_1",
            expected_state={"face_detected": True},
            timeout_seconds=2.0,
            now=now,
        )
        assert pred is not None
        assert pred.status.value == "PENDING"

        # Simulate camera seeing face
        outcome = ActualOutcome(
            outcome_id="out_face_1",
            expectation_id=pred.prediction_id,
            actual_state={"face_detected": True},
            timestamp=now + 0.5,
        )
        err = pred_eng.evaluate_outcome(outcome, now=now + 0.5)
        assert err.matched is True
        assert err.confidence_impact > 0

    # -------------------------------------------------------------------------
    # Test 16: Affective state urgency modulates dwell time
    # -------------------------------------------------------------------------
    def test_16_affective_state_modulation(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        t0 = time.time()
        aff = RobotAffectiveState(urgency=0.90)  # High urgency
        # Under normal urgency, min dwell time is 1.0s. Under high urgency, it should be 0.5s.
        intent_idle = behavior_engine.step(world_model, self_state, affective_state=aff, now=t0)
        assert intent_idle.behavior_type == BehaviorType.IDLE_ATTENTIVE

        # 0.6s later, lower priority change triggers because effective dwell is 0.5s
        t1 = t0 + 0.6
        p = UnifiedPersonState(person_id="p_new", distance_m=2.0, azimuth_deg=10.0, is_present=True)
        world_model.update_people([p], now=t1)

        intent_next = behavior_engine.step(world_model, self_state, affective_state=aff, now=t1)
        assert intent_next.behavior_type == BehaviorType.ORIENT_TO_STIMULUS

    # -------------------------------------------------------------------------
    # Test 17: Zero-LLM deterministic execution
    # -------------------------------------------------------------------------
    def test_17_zero_llm_deterministic_execution(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        now = time.time()
        p = UnifiedPersonState(person_id="p_det", distance_m=1.5, azimuth_deg=-25.0, is_present=True)
        world_model.update_people([p], now=now)

        # Run 5 times with identical inputs -> identical results guaranteed
        results = [
            behavior_engine.step(world_model, self_state, now=now).behavior_type
            for _ in range(5)
        ]
        assert len(set(results)) == 1
        assert results[0] == BehaviorType.ORIENT_TO_STIMULUS

    # -------------------------------------------------------------------------
    # Test 18: CognitiveLoop end-to-end integration
    # -------------------------------------------------------------------------
    def test_18_cognitive_loop_end_to_end(self):
        loop = CognitiveLoop(target_hz=10.0)
        now = time.time()

        res = loop.step({
            "people": [
                UnifiedPersonState(
                    person_id="p_loop_test",
                    name="TestUser",
                    distance_m=1.2,
                    azimuth_deg=15.0,
                    is_present=True,
                )
            ],
            "environment": {"front_clearance_m": 3.0},
        })

        assert res.behavioral_intent is not None
        assert isinstance(res.behavioral_intent, BehavioralIntent)
        assert res.action_intent is not None
        assert isinstance(res.action_intent, ActionIntent)
        assert res.action_intent.action_type in ("turn_head", "track_gaze")

    # -------------------------------------------------------------------------
    # Test 19: ActionManager execution of ActionIntent with hardware safety gates
    # -------------------------------------------------------------------------
    def test_19_action_manager_executes_action_intent(self):
        pub_vel = MagicMock()
        pub_head = MagicMock()
        pub_gesture = MagicMock()
        node = MagicMock()
        node._arduino_heartbeat_healthy = True
        node._last_heartbeat_ack_time = time.monotonic()
        node._obstacle_detected = False
        node._last_laser_scan_time = time.monotonic()

        mgr = ActionManager(
            pub_cmd_vel=pub_vel,
            pub_head_target_yaw=pub_head,
            pub_head_gesture=pub_gesture,
            node=node,
        )

        # 1. Forward motion ActionIntent
        move_intent = ActionIntent(
            intent_id="act_fwd",
            action_type="move_robot",
            parameters={"direction": "forward", "speed": 0.2, "duration": 1.0},
        )
        res_move = mgr.execute_action_intent(move_intent)
        assert res_move.success is True
        assert pub_vel.publish.called

        # 2. Obstacle detected blocks forward motion ActionIntent
        node._obstacle_detected = True
        blocked_intent = ActionIntent(
            intent_id="act_blocked",
            action_type="move_robot",
            parameters={"direction": "forward"},
        )
        res_blocked = mgr.execute_action_intent(blocked_intent)
        assert res_blocked.success is False
        assert res_blocked.error_code == "OBSTACLE_DETECTED"

        # 3. Gesture ActionIntent
        gesture_intent = ActionIntent(
            intent_id="act_gest",
            action_type="gesture",
            parameters={"gesture_name": "nod"},
        )
        res_gesture = mgr.execute_action_intent(gesture_intent)
        assert res_gesture.success is True
        assert pub_gesture.publish.called

    # -------------------------------------------------------------------------
    # Test 20: Performance benchmark (< 1.0 ms execution per cycle)
    # -------------------------------------------------------------------------
    def test_20_performance_submillisecond(
        self, behavior_engine: BehaviorEngine, world_model: WorldModel, self_state: SelfState
    ):
        p = UnifiedPersonState(person_id="p_perf", distance_m=2.0, azimuth_deg=10.0, is_present=True)
        world_model.update_people([p])

        # Warmup
        for _ in range(10):
            behavior_engine.step(world_model, self_state)

        # Measure 100 cycles
        t0 = time.perf_counter()
        cycles = 100
        for _ in range(cycles):
            behavior_engine.step(world_model, self_state)
        total_time_ms = (time.perf_counter() - t0) * 1000.0
        avg_ms = total_time_ms / cycles

        print(f"\n[Phase 7 Benchmark] BehaviorEngine avg step time: {avg_ms:.4f} ms")
        assert avg_ms < 1.0, f"BehaviorEngine took {avg_ms:.4f} ms, expected < 1.0 ms"

    # -------------------------------------------------------------------------
    # Test 21: Runtime Telemetry Formatting & All 9 Required Fields
    # -------------------------------------------------------------------------
    def test_21_runtime_telemetry_formatting_and_required_fields(self):
        """Verifies that format_runtime_telemetry generates a single-line banner containing all 9 required fields."""
        wm = WorldModel()
        person = UnifiedPersonState(
            person_id="p_baran",
            name="Baran",
            distance_m=2.2,
            azimuth_deg=5.0,
            is_present=True,
            is_looking_at_robot=True,
        )
        wm.update_people([person])
        self_st = SelfState()
        self_st.focused_person_id = "p_baran"

        loop = CognitiveLoop(world_model=wm, self_state=self_st)
        result = loop.step({"people": [person], "person_detected": True})

        banner = loop.format_runtime_telemetry(result)
        assert banner.startswith("🧠 [Cognition -> Behavior]")

        # Verify all 9 required fields
        assert "focus=" in banner
        assert "world=" in banner
        assert "conf=" in banner
        assert "unc=" in banner
        assert "suff=" in banner
        assert "decision=" in banner
        assert "intent=" in banner
        assert "reason=" in banner
        assert "target=" in banner

        # Verify specific content
        assert "Baran" in banner or "p_baran" in banner

    # -------------------------------------------------------------------------
    # Test 22: Runtime Telemetry Transition Gating & Anti-Spam (Speech Onset)
    # -------------------------------------------------------------------------
    def test_22_runtime_telemetry_transition_emission_anti_spam(self):
        """Verifies that telemetry is emitted only on state/decision transitions (anti-spam) and immediately on speech onset."""
        logged_banners = []

        def mock_telemetry(msg: str):
            logged_banners.append(msg)

        person = UnifiedPersonState(
            person_id="p_user",
            name="User",
            distance_m=1.8,
            azimuth_deg=0.0,
            is_present=True,
        )
        loop = CognitiveLoop(on_telemetry=mock_telemetry)

        # 1. First step: Initial state transition -> MUST log 1 banner
        loop.step({"people": [person], "person_detected": True, "vad": False})
        assert len(logged_banners) == 1
        assert "target=p_user" in logged_banners[0] or "target=None" in logged_banners[0]

        # 2. Subsequent 10 steps with identical perception -> MUST NOT spam
        for _ in range(10):
            loop.step({"people": [person], "person_detected": True, "vad": False})
        assert len(logged_banners) == 1, "Spam detected: telemetry was logged on static cycles!"

        # 3. Speech onset (User starts speaking: vad=True) -> MUST log immediately
        loop.step({"people": [person], "person_detected": True, "vad": True})
        assert len(logged_banners) == 2, "Speech onset failed to trigger telemetry transition!"
        assert "🧠 [Cognition -> Behavior]" in logged_banners[1]

        # 4. Continuing speech -> MUST NOT spam while speaking
        for _ in range(5):
            loop.step({"people": [person], "person_detected": True, "vad": True})
        assert len(logged_banners) == 2, "Spam detected during ongoing speech!"

        # 5. Speech ends (vad=False) -> Transition -> MUST log
        loop.step({"people": [person], "person_detected": True, "vad": False})
        assert len(logged_banners) == 3
