"""ASTRO V1 — Phase 0A Consciousness Foundation Test Suite.

Verifies:
  1. Consciousness Contracts & Types (CognitiveEvent, Goal, Prediction, SelfState, etc.)
  2. Cognitive Event Bus (Salience mapping, novelty detection, bounded deque, thread-safety)
  3. ConsciousnessNode ROS2 Skeleton (Parameter declaration, non-blocking perception caching,
     perception-to-event generation, cycle execution, telemetry output)
"""

import json
import os
import sys
import threading
import time
import unittest

# Ensure package import paths
pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if pkg_root not in sys.path:
    sys.path.insert(0, pkg_root)
sub_pkg = os.path.join(pkg_root, "astro_ai")
if sub_pkg not in sys.path:
    sys.path.insert(0, sub_pkg)

from astro_ai.brain.cognitive_event_bus import CognitiveEventBus, DEFAULT_SALIENCE_MAP
from astro_ai.consciousness_node import ConsciousnessNode
from astro_ai.contracts.consciousness_types import (
    ActionIntent,
    CognitiveEvent,
    CognitiveEventType,
    CognitiveWorkspace,
    Goal,
    GoalStatus,
    GoalType,
    Prediction,
    PredictionStatus,
    RobotAffectiveState,
    SelfState,
)
from astro_ai.state_machine import RobotState


class TestConsciousnessTypes(unittest.TestCase):
    """Verifies all Phase 0A data contracts, serialization, and default invariants."""

    def test_01_cognitive_event_type_enums(self):
        """1. CognitiveEventType enum defines all core perception, robot, and goal events."""
        self.assertEqual(CognitiveEventType.PERSON_APPEARED.value, "PERSON_APPEARED")
        self.assertEqual(CognitiveEventType.PERSON_DISAPPEARED.value, "PERSON_DISAPPEARED")
        self.assertEqual(CognitiveEventType.PERSON_RETURNED.value, "PERSON_RETURNED")
        self.assertEqual(CognitiveEventType.PREDICTION_ERROR.value, "PREDICTION_ERROR")
        self.assertEqual(CognitiveEventType.GOAL_CONFLICT.value, "GOAL_CONFLICT")
        self.assertEqual(CognitiveEventType.NOVELTY_DETECTED.value, "NOVELTY_DETECTED")

    def test_02_cognitive_event_creation_and_dict(self):
        """2. CognitiveEvent initializes with uuid, timestamp, and serializes cleanly to dict."""
        evt = CognitiveEvent(
            event_type=CognitiveEventType.PERSON_APPEARED,
            source="vision",
            data={"distance_m": 1.45, "person_id": "p_01"},
            salience=0.85,
            is_novel=True,
        )
        self.assertTrue(evt.event_id.startswith("evt_"))
        self.assertAlmostEqual(evt.timestamp, time.time(), delta=1.0)
        
        d = evt.to_dict()
        self.assertEqual(d["event_type"], "PERSON_APPEARED")
        self.assertEqual(d["source"], "vision")
        self.assertEqual(d["data"]["distance_m"], 1.45)
        self.assertTrue(d["is_novel"])
        # JSON encodable
        dumped = json.dumps(d)
        self.assertIn("PERSON_APPEARED", dumped)

    def test_03_goal_contract(self):
        """3. Goal contract correctly tracks priority, status, and serialization."""
        goal = Goal(
            goal_id="g_safety_01",
            goal_type=GoalType.SAFETY,
            description="Prevent collision with foreground obstacle",
            priority=1.0,
            status=GoalStatus.ACTIVE,
        )
        self.assertEqual(goal.goal_type, GoalType.SAFETY)
        self.assertEqual(goal.priority, 1.0)
        d = goal.to_dict()
        self.assertEqual(d["goal_type"], "SAFETY")
        self.assertEqual(d["status"], "ACTIVE")

    def test_04_prediction_contract(self):
        """4. Prediction contract tracks expected state and expiry."""
        exp_time = time.time() + 1.2
        pred = Prediction(
            prediction_id="pred_gaze_01",
            action_id="act_turn_right",
            expected_state={"face_detected": True},
            expected_by=exp_time,
            status=PredictionStatus.PENDING,
        )
        self.assertEqual(pred.status, PredictionStatus.PENDING)
        d = pred.to_dict()
        self.assertEqual(d["status"], "PENDING")
        self.assertTrue(d["expected_state"]["face_detected"])

    def test_05_robot_affective_state(self):
        """5. RobotAffectiveState maintains numerical behavioral modulators."""
        aff = RobotAffectiveState(
            arousal=0.4,
            urgency=0.2,
            social_engagement=0.8,
            confidence=0.9,
            uncertainty=0.1,
            curiosity=0.5,
            frustration=0.0,
        )
        self.assertAlmostEqual(aff.arousal, 0.4)
        self.assertAlmostEqual(aff.social_engagement, 0.8)
        d = aff.to_dict()
        self.assertIn("confidence", d)
        self.assertIn("frustration", d)

    def test_06_self_state_introspection(self):
        """6. SelfState aggregates introspection metrics without owning StateMachine."""
        self_state = SelfState(
            operational_state=RobotState.LISTENING,
            is_speaking=False,
            is_listening=True,
            current_head_yaw_deg=12.5,
            focused_person_id="baran",
            overall_confidence=0.85,
            uncertainty_level=0.15,
        )
        d = self_state.to_dict()
        self.assertEqual(d["operational_state"], "LISTENING")
        self.assertTrue(d["is_listening"])
        self.assertFalse(d["is_speaking"])
        self.assertEqual(d["focused_person_id"], "baran")
        self.assertEqual(d["current_head_yaw_deg"], 12.5)

    def test_07_cognitive_workspace_composition(self):
        """7. CognitiveWorkspace safely serializes active context snapshot."""
        ws = CognitiveWorkspace(
            trigger_event=CognitiveEvent(
                event_type=CognitiveEventType.PERSON_SPOKE,
                source="audio",
                data={"text": "merhaba astro"},
            ),
            recent_events_summary=["PERSON_APPEARED: vision", "PERSON_SPOKE: audio"],
            self_state_snapshot=SelfState(operational_state=RobotState.IDLE),
            affective_modulators=RobotAffectiveState(social_engagement=0.6),
            reasoning_flag=False,
        )
        d = ws.to_dict()
        self.assertEqual(d["trigger_event"]["event_type"], "PERSON_SPOKE")
        self.assertEqual(len(d["recent_events_summary"]), 2)
        self.assertEqual(d["self_state"]["operational_state"], "IDLE")
        # Ensure json encodable
        dumped = json.dumps(d, ensure_ascii=False)
        self.assertIn("merhaba astro", dumped)


class TestCognitiveEventBus(unittest.TestCase):
    """Verifies event bus queuing, novelty tracking, salience scoring, and thread safety."""

    def setUp(self):
        self.bus = CognitiveEventBus(max_capacity=100)

    def test_08_publish_and_retrieve_unprocessed(self):
        """8. Published events are retrieved in chronological order."""
        e1 = self.bus.create_and_publish(CognitiveEventType.PERSON_APPEARED, source="vision")
        e2 = self.bus.create_and_publish(CognitiveEventType.PERSON_SPOKE, source="audio")
        
        unprocessed = self.bus.get_unprocessed_events()
        self.assertEqual(len(unprocessed), 2)
        self.assertEqual(unprocessed[0].event_type, CognitiveEventType.PERSON_APPEARED)
        self.assertEqual(unprocessed[1].event_type, CognitiveEventType.PERSON_SPOKE)

    def test_09_mark_processed(self):
        """9. Marking events as processed removes them from unprocessed queue."""
        e1 = self.bus.create_and_publish(CognitiveEventType.PERSON_APPEARED, source="vision")
        e2 = self.bus.create_and_publish(CognitiveEventType.PERSON_SPOKE, source="audio")
        
        count = self.bus.mark_processed([e1.event_id])
        self.assertEqual(count, 1)
        
        remaining = self.bus.get_unprocessed_events()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].event_id, e2.event_id)

    def test_10_automatic_salience_mapping(self):
        """10. EventBus assigns default salience matching priority requirements."""
        e_crit = self.bus.create_and_publish(CognitiveEventType.SENSOR_LOST, source="camera_watchdog")
        e_norm = self.bus.create_and_publish(CognitiveEventType.OPERATIONAL_STATE_CHANGED, source="fsm")
        
        self.assertGreater(e_crit.salience, 0.9)
        self.assertLess(e_norm.salience, 0.5)

    def test_11_novelty_detection(self):
        """11. Novel events are tagged is_novel=True once, and False on recurrence."""
        e1 = self.bus.create_and_publish(
            CognitiveEventType.PERSON_APPEARED,
            source="vision",
            data={"person_id": "new_guest_42"},
        )
        self.assertTrue(e1.is_novel)

        # Same signature again
        e2 = self.bus.create_and_publish(
            CognitiveEventType.PERSON_APPEARED,
            source="vision",
            data={"person_id": "new_guest_42"},
        )
        self.assertFalse(e2.is_novel)

    def test_12_bounded_capacity(self):
        """12. EventBus drops oldest events when exceeding maximum capacity."""
        small_bus = CognitiveEventBus(max_capacity=50)
        for i in range(70):
            small_bus.create_and_publish(
                CognitiveEventType.OPERATIONAL_STATE_CHANGED,
                source="test",
                data={"index": i},
            )
        self.assertEqual(len(small_bus), 50)
        recent = small_bus.get_recent_events(limit=5)
        self.assertEqual(recent[0].data["index"], 69)

    def test_13_thread_safety(self):
        """13. Concurrent publishers publish events without race conditions."""
        num_threads = 5
        events_per_thread = 20

        def worker(thread_idx):
            for i in range(events_per_thread):
                self.bus.create_and_publish(
                    CognitiveEventType.ACTION_SUCCEEDED,
                    source=f"thread_{thread_idx}",
                    data={"idx": i},
                )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(self.bus), num_threads * events_per_thread)


class TestConsciousnessNode(unittest.TestCase):
    """Verifies ConsciousnessNode ROS2 skeleton, non-blocking callbacks, and cycle timing."""

    def setUp(self):
        self.node = ConsciousnessNode(node_name="test_consciousness_node")

    def test_14_node_initialization(self):
        """14. ConsciousnessNode initializes with correct defaults and loop frequency."""
        self.assertEqual(self.node.get_name(), "test_consciousness_node")
        self.assertEqual(self.node.loop_hz, 10.0)
        self.assertAlmostEqual(self.node.timer_period, 0.1, places=3)
        self.assertIsNotNone(self.node.event_bus)
        self.assertIsNotNone(self.node.self_state)

    def test_15_perception_transition_events(self):
        """15. Vision person detection transitions emit PERSON_APPEARED and PERSON_DISAPPEARED."""
        class _Msg:
            def __init__(self, val):
                self.data = val

        # Initially false -> True
        self.node._on_person_detected_msg(_Msg(True))
        events = self.node.event_bus.get_unprocessed_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, CognitiveEventType.PERSON_APPEARED)

        # True -> False
        self.node._on_person_detected_msg(_Msg(False))
        events = self.node.event_bus.get_unprocessed_events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[1].event_type, CognitiveEventType.PERSON_DISAPPEARED)

    def test_16_audio_vad_speaking_transitions(self):
        """16. VAD and TTS transitions update SelfState and generate respective events."""
        class _Msg:
            def __init__(self, val):
                self.data = val

        # VAD speech start
        self.node._on_audio_vad_msg(_Msg(True))
        self.assertTrue(self.node.self_state.is_listening)
        
        # TTS speaking start
        self.node._on_tts_speaking_msg(_Msg(True))
        self.assertTrue(self.node.self_state.is_speaking)

        events = self.node.event_bus.get_unprocessed_events()
        types = [e.event_type for e in events]
        self.assertIn(CognitiveEventType.PERSON_SPOKE, types)
        self.assertIn(CognitiveEventType.ROBOT_STARTED_SPEAKING, types)

    def test_17_cycle_execution_and_telemetry(self):
        """17. Cognitive cycle executes under budget, drains events, and updates telemetry."""
        class _Msg:
            def __init__(self, val):
                self.data = val

        # Ingest an event
        self.node._on_person_detected_msg(_Msg(True))
        self.assertEqual(len(self.node.event_bus.get_unprocessed_events()), 1)

        # Run one cycle
        self.node._on_cycle()

        # Unprocessed events should now be drained/marked
        self.assertEqual(len(self.node.event_bus.get_unprocessed_events()), 0)
        
        # Latency should be recorded and well within non-blocking budget (<50ms)
        self.assertLess(self.node.self_state.cycle_time_ms, 50.0)
        self.assertEqual(self.node._cycle_count, 1)

    def test_18_emit_action_intent(self):
        """18. Node emits valid ActionIntent message to /consciousness/action_intent."""
        intent = ActionIntent(
            intent_id="intent_01",
            action_type="gaze_hint",
            target="speaker_left",
            parameters={"azimuth_deg": -35.0},
            priority=0.8,
        )
        self.node.emit_action_intent(intent)
        pub = self.node._pub_action_intent
        self.assertGreater(pub.count, 0)
        self.assertIn("gaze_hint", pub.last_msg.data)


if __name__ == "__main__":
    unittest.main()
