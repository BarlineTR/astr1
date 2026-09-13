"""ASTRO V1 — Phase 2 Test Suite: Self Model, Introspection, and Affective State.

Validates:
  1. StateMachine IDLE -> SelfState
  2. StateMachine LISTENING -> SelfState
  3. Speaking state -> SelfState
  4. Head yaw -> SelfState
  5. Operational / cognitive state ownership separation (SelfState cannot mutate StateMachine)
  6. Confidence update and clamping [0.1, 1.0]
  7. Uncertainty update and clamping [0.0, 1.0]
  8. Affective initialization defaults
  9. Affective step decay towards baselines
  10. Arousal modulation
  11. Urgency modulation
  12. Social engagement modulation
  13. Frustration update on failures / recovery on success
  14. Introspection snapshot and queries
  15. Deterministic replay of SelfState and AffectiveState
  16. Empty / no-perception cycle stability
  17. Phase 0A regression (contracts & event bus)
  18. Phase 0B regression (cognitive loop & temporal history)
  19. Phase 1 regression (perception event transitions)
  20. Invariant: AffectiveState cannot directly emit ActionIntent
"""

import time
import unittest

from astro_ai.brain.affective_state import AffectiveStateManager
from astro_ai.brain.cognitive_event_bus import CognitiveEventBus
from astro_ai.brain.cognitive_loop import CognitiveLoop
from astro_ai.brain.perception_event_detector import PerceptionEventDetector
from astro_ai.brain.self_model import SelfModel
from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.consciousness_types import (
    ActionIntent,
    CognitiveEvent,
    CognitiveEventType,
    Goal,
    GoalStatus,
    GoalType,
    Prediction,
    PredictionStatus,
    RobotAffectiveState,
    SelfState,
)
from astro_ai.state_machine import RobotState, StateMachine


class TestPhase2SelfModelAndIntrospection(unittest.TestCase):
    """Phase 2 Acceptance Tests for SelfModel, SelfState, Introspection, and Affective State."""

    def setUp(self):
        self.state_machine = StateMachine(RobotState.IDLE)
        self.self_state = SelfState()
        self.affective_mgr = AffectiveStateManager()
        self.self_model = SelfModel(
            self_state=self.self_state,
            affective_manager=self.affective_mgr,
        )

    # -------------------------------------------------------------------------
    # Test 1: StateMachine IDLE -> SelfState
    # -------------------------------------------------------------------------
    def test_01_state_machine_idle_to_self_state(self):
        """1. StateMachine in IDLE reflects properly in SelfState."""
        self.assertEqual(self.state_machine.current_state, RobotState.IDLE)
        self.self_state.update_from_state_machine(self.state_machine)

        self.assertEqual(self.self_state.operational_state, RobotState.IDLE)
        self.assertEqual(self.self_state.get_operational_state(), RobotState.IDLE)
        self.assertFalse(self.self_state.is_listening)
        self.assertFalse(self.self_state.is_speaking)

    # -------------------------------------------------------------------------
    # Test 2: StateMachine LISTENING -> SelfState
    # -------------------------------------------------------------------------
    def test_02_state_machine_listening_to_self_state(self):
        """2. StateMachine transition to LISTENING updates SelfState."""
        self.state_machine.transition_to(RobotState.LISTENING)
        self.self_state.update_from_state_machine(self.state_machine)

        self.assertEqual(self.self_state.operational_state, RobotState.LISTENING)
        self.assertEqual(self.self_state.get_operational_state(), RobotState.LISTENING)
        self.assertTrue(self.self_state.is_listening)
        self.assertIn("Listening", self.self_state.get_current_activity())

    # -------------------------------------------------------------------------
    # Test 3: Speaking state -> SelfState
    # -------------------------------------------------------------------------
    def test_03_speaking_state_to_self_state(self):
        """3. Speaking status from StateMachine or perception feeds into SelfState."""
        # Via StateMachine transition
        self.state_machine.transition_to(RobotState.SPEAKING)
        self.self_state.update_from_state_machine(self.state_machine)
        self.assertTrue(self.self_state.is_speaking)
        self.assertTrue(self.self_state.is_executing_action())
        self.assertIn("Speaking", self.self_state.get_current_activity())

        # Via perception observation
        self.self_state.update_from_perception({"tts_speaking": True, "focused_person_id": "baran"})
        self.assertTrue(self.self_state.is_speaking)
        self.assertEqual(self.self_state.focused_person_id, "baran")
        self.assertIn("Speaking with baran", self.self_state.get_current_activity())

    # -------------------------------------------------------------------------
    # Test 4: Head yaw -> SelfState
    # -------------------------------------------------------------------------
    def test_04_head_yaw_to_self_state(self):
        """4. Head yaw angle from perception updates SelfState."""
        self.self_state.update_from_perception({"head_yaw_deg": 42.5})
        self.assertAlmostEqual(self.self_state.current_head_yaw_deg, 42.5)

        # Also support nested robot_state dictionary
        self.self_state.update_from_perception({"robot_state": {"head_yaw_deg": -18.2}})
        self.assertAlmostEqual(self.self_state.current_head_yaw_deg, -18.2)

    # -------------------------------------------------------------------------
    # Test 5: Operational / Cognitive State Ownership Separation
    # -------------------------------------------------------------------------
    def test_05_state_machine_ownership_separation(self):
        """5. SelfState reads from StateMachine but cannot unilaterally mutate it."""
        sm = StateMachine(RobotState.IDLE)
        self_state = SelfState()
        self_state.update_from_state_machine(sm)
        self.assertEqual(self_state.operational_state, RobotState.IDLE)

        # Mutating SelfState directly MUST NOT alter StateMachine
        self_state.operational_state = RobotState.SPEAKING
        self_state.is_speaking = True
        self.assertEqual(sm.current_state, RobotState.IDLE)
        self.assertFalse(sm.is_speaking())

    # -------------------------------------------------------------------------
    # Test 6: Confidence Update and Clamping
    # -------------------------------------------------------------------------
    def test_06_confidence_update_and_clamping(self):
        """6. Epistemic confidence is clamped to [0.1, 1.0] and updates properly."""
        mgr = AffectiveStateManager()
        mgr.set_confidence(0.9)
        self.assertAlmostEqual(mgr.state.confidence, 0.9)

        # Upper bound clamp
        mgr.set_confidence(1.5)
        self.assertAlmostEqual(mgr.state.confidence, 1.0)

        # Lower bound clamp: strictly >= 0.1
        mgr.set_confidence(-0.5)
        self.assertAlmostEqual(mgr.state.confidence, 0.1)

        # SelfState confidence API
        self.self_state.set_confidence(0.85)
        self.assertAlmostEqual(self.self_state.get_confidence(), 0.85)
        self.self_state.set_confidence(0.0)
        self.assertAlmostEqual(self.self_state.get_confidence(), 0.1)

    # -------------------------------------------------------------------------
    # Test 7: Uncertainty Update and Clamping
    # -------------------------------------------------------------------------
    def test_07_uncertainty_update_and_clamping(self):
        """7. Uncertainty level is clamped to [0.0, 1.0] and updates properly."""
        mgr = AffectiveStateManager()
        mgr.set_uncertainty(0.65)
        self.assertAlmostEqual(mgr.state.uncertainty, 0.65)

        # Upper bound clamp
        mgr.set_uncertainty(2.0)
        self.assertAlmostEqual(mgr.state.uncertainty, 1.0)

        # Lower bound clamp
        mgr.set_uncertainty(-0.3)
        self.assertAlmostEqual(mgr.state.uncertainty, 0.0)

        # SelfState uncertainty API
        self.self_state.set_uncertainty(0.4)
        self.assertAlmostEqual(self.self_state.get_uncertainty(), 0.4)
        self.self_state.set_uncertainty(-0.1)
        self.assertAlmostEqual(self.self_state.get_uncertainty(), 0.0)

    # -------------------------------------------------------------------------
    # Test 8: Affective Initialization Defaults
    # -------------------------------------------------------------------------
    def test_08_affective_initialization_defaults(self):
        """8. Affective state initializes with canonical baseline equilibria."""
        mgr = AffectiveStateManager()
        s = mgr.state

        self.assertAlmostEqual(s.arousal, 0.2)
        self.assertAlmostEqual(s.urgency, 0.0)
        self.assertAlmostEqual(s.social_engagement, 0.0)
        self.assertAlmostEqual(s.confidence, 0.7)
        self.assertAlmostEqual(s.uncertainty, 0.3)
        self.assertAlmostEqual(s.curiosity, 0.3)
        self.assertAlmostEqual(s.frustration, 0.0)

    # -------------------------------------------------------------------------
    # Test 9: Affective Step Decay Towards Baselines
    # -------------------------------------------------------------------------
    def test_09_affective_step_decay_towards_baselines(self):
        """9. Elevated modulators decay smoothly towards baseline equilibria."""
        elevated = RobotAffectiveState(
            arousal=0.85,
            urgency=0.75,
            social_engagement=0.80,
            confidence=0.25,
            uncertainty=0.75,
            curiosity=0.90,
            frustration=0.60,
        )
        mgr = AffectiveStateManager(initial_state=elevated)

        # Perform 25 decay steps (dt=0.1s -> 2.5s simulated time)
        for _ in range(25):
            mgr.step_decay(dt=0.1)

        s = mgr.state
        self.assertLess(s.arousal, 0.85)
        self.assertGreater(s.arousal, 0.2)

        self.assertLess(s.urgency, 0.75)
        self.assertGreaterEqual(s.urgency, 0.0)

        self.assertLess(s.social_engagement, 0.80)
        self.assertGreaterEqual(s.social_engagement, 0.0)

        self.assertLess(s.curiosity, 0.90)
        self.assertGreater(s.curiosity, 0.3)

        self.assertLess(s.frustration, 0.60)
        self.assertGreaterEqual(s.frustration, 0.0)

        # Depressed confidence drifts upwards towards baseline 0.7
        self.assertGreater(s.confidence, 0.25)
        self.assertLessEqual(s.confidence, 0.7)

        # Elevated uncertainty drifts downwards towards baseline 0.3
        self.assertLess(s.uncertainty, 0.75)
        self.assertGreaterEqual(s.uncertainty, 0.3)

    # -------------------------------------------------------------------------
    # Test 10: Arousal Modulation
    # -------------------------------------------------------------------------
    def test_10_arousal_modulation(self):
        """10. Interruptions and novelty events increase arousal."""
        mgr = AffectiveStateManager()
        initial_arousal = mgr.state.arousal

        # Interruption event
        evt_interrupt = CognitiveEvent(
            event_type=CognitiveEventType.ROBOT_INTERRUPTED,
            source="audio",
        )
        mgr.update_from_event(evt_interrupt)
        self.assertGreater(mgr.state.arousal, initial_arousal)
        self.assertGreater(mgr.state.frustration, 0.0)

        # Novelty event
        prev_arousal = mgr.state.arousal
        prev_curiosity = mgr.state.curiosity
        evt_novelty = CognitiveEvent(
            event_type=CognitiveEventType.NOVELTY_DETECTED,
            source="vision",
        )
        mgr.update_from_event(evt_novelty)
        self.assertGreater(mgr.state.arousal, prev_arousal)
        self.assertGreater(mgr.state.curiosity, prev_curiosity)

    # -------------------------------------------------------------------------
    # Test 11: Urgency Modulation
    # -------------------------------------------------------------------------
    def test_11_urgency_modulation(self):
        """11. Critical obstacle clearance and sensor degradation elevate urgency."""
        mgr = AffectiveStateManager()
        self.assertAlmostEqual(mgr.state.urgency, 0.0)

        # Urgent obstacle < 0.5m
        mgr.update_from_perception({"environment": {"front_clearance_m": 0.35}})
        self.assertGreaterEqual(mgr.state.urgency, 0.7)
        self.assertGreaterEqual(mgr.state.arousal, 0.6)

        # Sensor loss event
        mgr.reset()
        evt_sensor_lost = CognitiveEvent(
            event_type=CognitiveEventType.SENSOR_LOST,
            source="lidar_watchdog",
        )
        mgr.update_from_event(evt_sensor_lost)
        self.assertGreater(mgr.state.urgency, 0.0)
        self.assertGreater(mgr.state.uncertainty, 0.3)

    # -------------------------------------------------------------------------
    # Test 12: Social Engagement Modulation
    # -------------------------------------------------------------------------
    def test_12_social_engagement_modulation(self):
        """12. Speaking person, VAD, and gaze elevate social engagement."""
        mgr = AffectiveStateManager()
        self.assertAlmostEqual(mgr.state.social_engagement, 0.0)

        # Person appearance & speech
        mgr.update_from_event(CognitiveEvent(
            event_type=CognitiveEventType.PERSON_APPEARED,
            source="vision",
        ))
        self.assertGreater(mgr.state.social_engagement, 0.0)

        prev_social = mgr.state.social_engagement
        mgr.update_from_perception({"vad": True, "looking_at_robot": True})
        self.assertGreater(mgr.state.social_engagement, prev_social)

    # -------------------------------------------------------------------------
    # Test 13: Frustration on Failures / Recovery on Success
    # -------------------------------------------------------------------------
    def test_13_frustration_on_failures_and_recovery_on_success(self):
        """13. Action/prediction errors increase frustration; successes recover confidence."""
        mgr = AffectiveStateManager()
        self.assertAlmostEqual(mgr.state.frustration, 0.0)
        initial_confidence = mgr.state.confidence

        # Action failure
        mgr.update_from_event(CognitiveEvent(
            event_type=CognitiveEventType.ACTION_FAILED,
            source="action_manager",
            data={"action_id": "act_navigate"},
        ))
        self.assertGreater(mgr.state.frustration, 0.0)
        self.assertLess(mgr.state.confidence, initial_confidence)

        # Prediction error
        prev_frustration = mgr.state.frustration
        mgr.update_from_event(CognitiveEvent(
            event_type=CognitiveEventType.PREDICTION_ERROR,
            source="outcome_arbiter",
        ))
        self.assertGreater(mgr.state.frustration, prev_frustration)

        # Success event relieves frustration
        frustration_before_success = mgr.state.frustration
        mgr.update_from_event(CognitiveEvent(
            event_type=CognitiveEventType.ACTION_SUCCEEDED,
            source="action_manager",
        ))
        self.assertLess(mgr.state.frustration, frustration_before_success)
        self.assertGreater(mgr.state.confidence, 0.1)

    # -------------------------------------------------------------------------
    # Test 14: Introspection Snapshot and Queries
    # -------------------------------------------------------------------------
    def test_14_introspection_snapshot_and_queries(self):
        """14. Basic Introspection answers core self-state queries consistently."""
        goal = Goal(
            goal_id="goal_safety_01",
            goal_type=GoalType.SAFETY,
            description="Clear foreground obstacle",
            priority=1.0,
        )
        pred = Prediction(
            prediction_id="pred_01",
            action_id="act_turn_head",
            expected_state={"yaw": 30.0},
            expected_by=time.time() + 2.0,
        )

        model = SelfModel()
        model.self_state.operational_state = RobotState.THINKING
        model.self_state.focused_person_id = "person_baran"
        model.self_state.current_goal = goal
        model.self_state.active_prediction = pred
        model.self_state.degraded_capabilities.add("lidar_planar")

        # Query methods on SelfModel
        self.assertIn("Executing action (act_turn_head)", model.get_current_activity())
        self.assertEqual(model.get_operational_state(), RobotState.THINKING)
        self.assertEqual(model.get_focused_person(), "person_baran")
        self.assertEqual(model.get_active_goal().goal_id, "goal_safety_01")
        self.assertTrue(model.is_executing_action())
        self.assertIn("lidar_planar", model.get_degraded_capabilities())

        # Comprehensive introspection summary dictionary
        summary = model.get_introspection_summary()
        self.assertIn("activity", summary)
        self.assertIn("operational_state", summary)
        self.assertEqual(summary["operational_state"], "THINKING")
        self.assertEqual(summary["focused_person_id"], "person_baran")
        self.assertEqual(summary["active_goal_id"], "goal_safety_01")
        self.assertEqual(summary["active_action_id"], "act_turn_head")
        self.assertTrue(summary["is_executing_action"])
        self.assertIn("confidence", summary)
        self.assertIn("uncertainty", summary)
        self.assertIn("lidar_planar", summary["degraded_capabilities"])
        self.assertIn("affective_modulators", summary)
        self.assertIn("identity", summary)
        self.assertEqual(summary["identity"]["creator"], "Baran")

    # -------------------------------------------------------------------------
    # Test 15: Deterministic Replay
    # -------------------------------------------------------------------------
    def test_15_deterministic_replay(self):
        """15. Replaying identical perception sequences yields identical cognitive state."""
        seq = [
            {"vad": False, "person_detected": True, "head_yaw_deg": 10.0},
            {"vad": True, "person_detected": True, "head_yaw_deg": 12.0},
            {"vad": False, "tts_speaking": True, "head_yaw_deg": 12.0},
            {"environment": {"front_clearance_m": 0.40}},
            {"environment": {"front_clearance_m": 1.80}},
        ]

        loop_a = CognitiveLoop()
        loop_b = CognitiveLoop()

        results_a = loop_a.run_consecutive_steps(len(seq), seq)
        results_b = loop_b.run_consecutive_steps(len(seq), seq)

        for step_idx in range(len(seq)):
            state_a = results_a[step_idx].self_state
            state_b = results_b[step_idx].self_state
            aff_a = results_a[step_idx].affective_state
            aff_b = results_b[step_idx].affective_state

            self.assertEqual(state_a.is_speaking, state_b.is_speaking)
            self.assertEqual(state_a.is_listening, state_b.is_listening)
            self.assertAlmostEqual(state_a.current_head_yaw_deg, state_b.current_head_yaw_deg)
            self.assertAlmostEqual(aff_a.arousal, aff_b.arousal, places=4)
            self.assertAlmostEqual(aff_a.urgency, aff_b.urgency, places=4)
            self.assertAlmostEqual(aff_a.confidence, aff_b.confidence, places=4)
            self.assertAlmostEqual(aff_a.uncertainty, aff_b.uncertainty, places=4)

    # -------------------------------------------------------------------------
    # Test 16: Empty / No-Perception Cycle Stability
    # -------------------------------------------------------------------------
    def test_16_empty_no_perception_cycle_stability(self):
        """16. Empty perception cycles execute smoothly, fast, and decay modulators."""
        loop = CognitiveLoop()
        # Prime with elevated state
        loop.affective_manager.modulate_arousal(0.5)
        loop.affective_manager.modulate_urgency(0.6)

        results = loop.run_consecutive_steps(10, None)
        self.assertEqual(len(results), 10)

        for res in results:
            self.assertIsNotNone(res.self_state)
            self.assertIsNotNone(res.affective_state)
            self.assertLess(res.duration_ms, 10.0)

        # Final step must be closer to baselines
        final_aff = results[-1].affective_state
        self.assertLess(final_aff.arousal, 0.7)
        self.assertLess(final_aff.urgency, 0.6)

    # -------------------------------------------------------------------------
    # Test 17: Phase 0A Regression Check
    # -------------------------------------------------------------------------
    def test_17_phase0a_regression_check(self):
        """17. Foundation contracts and event bus remain 100% operational."""
        bus = CognitiveEventBus(max_capacity=50)
        evt = bus.create_and_publish(
            event_type=CognitiveEventType.PERSON_APPEARED,
            source="vision",
            data={"person_id": "test_user"},
        )
        self.assertIsNotNone(evt)
        unprocessed = bus.get_unprocessed_events()
        self.assertEqual(len(unprocessed), 1)
        self.assertEqual(unprocessed[0].event_type, CognitiveEventType.PERSON_APPEARED)

    # -------------------------------------------------------------------------
    # Test 18: Phase 0B Regression Check
    # -------------------------------------------------------------------------
    def test_18_phase0b_regression_check(self):
        """18. Temporal ring-buffer in WorldModel continues accumulating correctly."""
        wm = WorldModel(temporal_history_size=10)
        wm.record_event("test_event_01")
        snap = wm.commit_temporal_snapshot()
        self.assertIsNotNone(snap)
        self.assertEqual(wm.temporal_history_len, 1)

    # -------------------------------------------------------------------------
    # Test 19: Phase 1 Regression Check
    # -------------------------------------------------------------------------
    def test_19_phase1_regression_check(self):
        """19. Perception event detector emits transitions without event storms."""
        detector = PerceptionEventDetector()
        # Transition False -> True
        events = detector.detect_transitions({"person_detected": True}, timestamp=100.0)
        self.assertTrue(any(e.event_type == CognitiveEventType.PERSON_APPEARED for e in events))

        # Static scene True -> True produces no storm
        events_static = detector.detect_transitions({"person_detected": True}, timestamp=100.1)
        self.assertFalse(any(e.event_type == CognitiveEventType.PERSON_APPEARED for e in events_static))

    # -------------------------------------------------------------------------
    # Test 20: Invariant — AffectiveState Cannot Directly Emit ActionIntent
    # -------------------------------------------------------------------------
    def test_20_affective_state_cannot_directly_emit_action_intent(self):
        """20. Invariant: RobotAffectiveState & AffectiveStateManager have NO action emission methods."""
        forbidden_substrings = ["action_intent", "emit", "publish", "command", "actuate", "motor"]

        aff_state_methods = [m for m in dir(RobotAffectiveState) if not m.startswith("__")]
        for m in aff_state_methods:
            for forbidden in forbidden_substrings:
                self.assertNotIn(
                    forbidden,
                    m.lower(),
                    f"RobotAffectiveState violates invariant by defining action method '{m}'",
                )

        aff_mgr_methods = [m for m in dir(AffectiveStateManager) if not m.startswith("__")]
        for m in aff_mgr_methods:
            for forbidden in forbidden_substrings:
                self.assertNotIn(
                    forbidden,
                    m.lower(),
                    f"AffectiveStateManager violates invariant by defining action method '{m}'",
                )


if __name__ == "__main__":
    unittest.main()
