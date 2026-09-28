"""ASTRO V1 — Phase 1 Perception Event Generation Evaluation Suite.

Verifies:
  1. False -> True person appearance triggers PERSON_APPEARED
  2. True -> True consecutive presence emits ZERO duplicate events
  3. True -> False departure triggers PERSON_DISAPPEARED
  4. Known person leaves and returns within temporal window triggers PERSON_RETURNED
  5. Unknown anonymous person leaves and returns does NOT trigger false positive RETURNED (only APPEARED)
  6. VAD False -> True triggers PERSON_SPOKE
  7. VAD True -> True emits ZERO duplicate speech events
  8. Robot speaking False -> True triggers ROBOT_STARTED_SPEAKING
  9. Robot speaking True -> False triggers ROBOT_FINISHED_SPEAKING
  10. Social FSM phase transition triggers SOCIAL_PHASE_CHANGED
  11. Gaze target change triggers TARGET_CHANGED
  12. Stale sensor triggers SENSOR_LOST watchdog event
  13. Sensor re-acquisition triggers SENSOR_RECOVERED event
  14. Novelty behavior via CognitiveEventBus
  15. Deterministic replay of event streams across loop instances
  16. Event ordering and timestamp monotonicity
  17. Anti-storm guarantee: static continuous scene generates ZERO events
  18. Existing WorldModel API compatibility and zero-regression
  19. Full integration of CognitiveLoop with transition event detection
"""

import os
import sys
import time
import unittest

# Ensure package import paths
pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if pkg_root not in sys.path:
    sys.path.insert(0, pkg_root)
sub_pkg = os.path.join(pkg_root, "astro_ai")
if sub_pkg not in sys.path:
    sys.path.insert(0, sub_pkg)

from astro_ai.brain.cognitive_event_bus import CognitiveEventBus
from astro_ai.brain.cognitive_loop import CognitiveLoop
from astro_ai.brain.perception_event_detector import PerceptionEventDetector
from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.consciousness_types import CognitiveEvent, CognitiveEventType
from astro_ai.contracts.intent_emotion_types import ConversationPhase
from astro_ai.contracts.person_state import UnifiedPersonState


class TestPhase1PerceptionEventGeneration(unittest.TestCase):
    """Rigorous evaluation of semantic transition event generation."""

    def setUp(self):
        self.detector = PerceptionEventDetector(
            person_timeout_s=2.0,
            return_window_s=60.0,
            sensor_timeouts={"camera": 1.0, "lidar": 1.0, "audio": 1.0, "head": 1.0},
        )
        self.bus = CognitiveEventBus(max_capacity=100)
        self.loop = CognitiveLoop(
            event_bus=self.bus,
            event_detector=self.detector,
            target_hz=10.0,
            temporal_history_size=20,
        )

    # -------------------------------------------------------------------------
    # 1. Person Appearance: False -> True
    # -------------------------------------------------------------------------

    def test_01_person_appeared_on_false_to_true(self):
        """1. When a person first appears (False -> True), PERSON_APPEARED is emitted."""
        p = UnifiedPersonState(person_id="p1", name="Baran", is_known=True, is_present=True)
        events = self.detector.detect_transitions({"people": [p]})

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, CognitiveEventType.PERSON_APPEARED)
        self.assertEqual(events[0].data["person_id"], "p1")
        self.assertEqual(events[0].data["name"], "Baran")

    # -------------------------------------------------------------------------
    # 2. Continuous Presence: True -> True (Anti-Storm)
    # -------------------------------------------------------------------------

    def test_02_no_duplicate_on_true_to_true(self):
        """2. Consecutive cycles with the same present person emit ZERO duplicate events."""
        p = UnifiedPersonState(person_id="p1", name="Baran", is_known=True, is_present=True)

        # First cycle -> Appeared
        ev1 = self.detector.detect_transitions({"people": [p]})
        self.assertEqual(len(ev1), 1)

        # Subsequent 5 cycles with identical presence -> ZERO events
        for _ in range(5):
            ev_sub = self.detector.detect_transitions({"people": [p]})
            self.assertEqual(len(ev_sub), 0)

    # -------------------------------------------------------------------------
    # 3. Person Departure: True -> False
    # -------------------------------------------------------------------------

    def test_03_person_disappeared_on_true_to_false(self):
        """3. When a present person leaves (True -> False), PERSON_DISAPPEARED is emitted."""
        p = UnifiedPersonState(person_id="p1", name="Baran", is_known=True, is_present=True)
        self.detector.detect_transitions({"people": [p]})

        # Now empty scene
        ev_dep = self.detector.detect_transitions({"people": []})
        self.assertEqual(len(ev_dep), 1)
        self.assertEqual(ev_dep[0].event_type, CognitiveEventType.PERSON_DISAPPEARED)
        self.assertEqual(ev_dep[0].data["person_id"], "p1")

    # -------------------------------------------------------------------------
    # 4. Known Person Returns: PERSON_RETURNED
    # -------------------------------------------------------------------------

    def test_04_known_person_returns_within_window(self):
        """4. Known person leaves and returns within window triggers PERSON_RETURNED."""
        t0 = 1000.0
        p = UnifiedPersonState(person_id="p1", name="Baran", is_known=True, is_present=True)

        # 1. Appeared
        self.detector.detect_transitions({"people": [p]}, timestamp=t0)

        # 2. Departed at t0 + 10s
        self.detector.detect_transitions({"people": []}, timestamp=t0 + 10.0)

        # 3. Returned at t0 + 35s (within 60s window)
        ev_ret = self.detector.detect_transitions({"people": [p]}, timestamp=t0 + 35.0)
        self.assertEqual(len(ev_ret), 1)
        self.assertEqual(ev_ret[0].event_type, CognitiveEventType.PERSON_RETURNED)
        self.assertEqual(ev_ret[0].data["name"], "Baran")
        self.assertAlmostEqual(ev_ret[0].data["away_duration_s"], 25.0, places=1)

    # -------------------------------------------------------------------------
    # 5. Anonymous Person Leaves & Returns: NO False Positive RETURNED
    # -------------------------------------------------------------------------

    def test_05_anonymous_person_never_triggers_person_returned(self):
        """5. Anonymous guest ('Misafir', is_known=False) leaving and returning triggers APPEARED, NOT RETURNED."""
        t0 = 1000.0
        anon = UnifiedPersonState(person_id="p_anon", name="Misafir", is_known=False, is_present=True)

        # 1. Appeared
        ev1 = self.detector.detect_transitions({"people": [anon]}, timestamp=t0)
        self.assertEqual(ev1[0].event_type, CognitiveEventType.PERSON_APPEARED)

        # 2. Departed
        self.detector.detect_transitions({"people": []}, timestamp=t0 + 5.0)

        # 3. Returned -> MUST BE PERSON_APPEARED, NEVER PERSON_RETURNED
        ev_ret = self.detector.detect_transitions({"people": [anon]}, timestamp=t0 + 15.0)
        self.assertEqual(len(ev_ret), 1)
        self.assertEqual(ev_ret[0].event_type, CognitiveEventType.PERSON_APPEARED)
        self.assertNotEqual(ev_ret[0].event_type, CognitiveEventType.PERSON_RETURNED)

    # -------------------------------------------------------------------------
    # 6 & 7. VAD Speech Activity Transitions
    # -------------------------------------------------------------------------

    def test_06_vad_speech_start_emits_person_spoke(self):
        """6. VAD transitioning False -> True triggers PERSON_SPOKE."""
        ev = self.detector.detect_transitions({"vad": True, "doa_deg": 35.0})
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].event_type, CognitiveEventType.PERSON_SPOKE)
        self.assertEqual(ev[0].data["doa_deg"], 35.0)

    def test_07_vad_speech_continuous_emits_no_duplicate(self):
        """7. VAD staying True -> True emits ZERO duplicate speech events."""
        self.detector.detect_transitions({"vad": True})
        for _ in range(5):
            ev = self.detector.detect_transitions({"vad": True})
            self.assertEqual(len(ev), 0)

    # -------------------------------------------------------------------------
    # 8 & 9. Robot Speaking Transitions
    # -------------------------------------------------------------------------

    def test_08_robot_started_speaking_transition(self):
        """8. Robot speaking False -> True triggers ROBOT_STARTED_SPEAKING."""
        ev = self.detector.detect_transitions({"tts_speaking": True})
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].event_type, CognitiveEventType.ROBOT_STARTED_SPEAKING)

    def test_09_robot_finished_speaking_transition(self):
        """9. Robot speaking True -> False triggers ROBOT_FINISHED_SPEAKING."""
        self.detector.detect_transitions({"tts_speaking": True})
        ev = self.detector.detect_transitions({"tts_speaking": False})
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].event_type, CognitiveEventType.ROBOT_FINISHED_SPEAKING)

        # Continuous False -> False emits zero
        ev_none = self.detector.detect_transitions({"tts_speaking": False})
        self.assertEqual(len(ev_none), 0)

    # -------------------------------------------------------------------------
    # 10. Social FSM Phase Transition
    # -------------------------------------------------------------------------

    def test_10_social_phase_transition_emits_social_phase_changed(self):
        """10. Social FSM phase transitions emit SOCIAL_PHASE_CHANGED."""
        # Initial phase
        self.detector.detect_transitions({"social_phase": ConversationPhase.UNATTENDED})

        # Transition to GREETING
        ev = self.detector.detect_transitions({"social_phase": ConversationPhase.GREETING})
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].event_type, CognitiveEventType.SOCIAL_PHASE_CHANGED)
        self.assertEqual(ev[0].data["old_phase"], "UNATTENDED")
        self.assertEqual(ev[0].data["new_phase"], "GREETING")

        # Same phase produces zero events
        ev_same = self.detector.detect_transitions({"social_phase": ConversationPhase.GREETING})
        self.assertEqual(len(ev_same), 0)

    # -------------------------------------------------------------------------
    # 11. Gaze Target Change
    # -------------------------------------------------------------------------

    def test_11_target_changed_transition(self):
        """11. Active gaze target transition emits TARGET_CHANGED."""
        self.detector.detect_transitions({"active_target_id": "target_person_1"})
        ev = self.detector.detect_transitions({"active_target_id": "target_person_2"})
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0].event_type, CognitiveEventType.TARGET_CHANGED)
        self.assertEqual(ev[0].data["old_target_id"], "target_person_1")
        self.assertEqual(ev[0].data["new_target_id"], "target_person_2")

    # -------------------------------------------------------------------------
    # 12 & 13. Stale Sensor Watchdog (Lost and Recovered)
    # -------------------------------------------------------------------------

    def test_12_sensor_lost_watchdog(self):
        """12. Sensor topic silence exceeding threshold triggers SENSOR_LOST."""
        t0 = 2000.0
        # Camera is active at t0
        self.detector.detect_transitions({"sensor_activity": {"camera": t0}}, timestamp=t0)

        # 0.5s later (under 1.0s timeout) -> No loss
        ev_ok = self.detector.detect_transitions({}, timestamp=t0 + 0.5)
        self.assertEqual(len(ev_ok), 0)

        # 1.5s later -> Camera is lost
        ev_lost = self.detector.detect_transitions({}, timestamp=t0 + 1.5)
        types = [e.event_type for e in ev_lost]
        self.assertIn(CognitiveEventType.SENSOR_LOST, types)
        sensor_lost_event = [e for e in ev_lost if e.event_type == CognitiveEventType.SENSOR_LOST][0]
        self.assertEqual(sensor_lost_event.data["sensor"], "camera")

        # Stays lost -> ZERO duplicate SENSOR_LOST events
        ev_still_lost = self.detector.detect_transitions({}, timestamp=t0 + 2.0)
        self.assertEqual(len(ev_still_lost), 0)

    def test_13_sensor_recovered_watchdog(self):
        """13. Re-acquisition of lost sensor stream triggers SENSOR_RECOVERED."""
        t0 = 2000.0
        self.detector.detect_transitions({"sensor_activity": {"camera": t0}}, timestamp=t0)
        # Timeout camera at t0 + 1.5s
        self.detector.detect_transitions({}, timestamp=t0 + 1.5)

        # Re-activate camera at t0 + 2.0s
        ev_rec = self.detector.detect_transitions({"sensor_activity": {"camera": t0 + 2.0}}, timestamp=t0 + 2.0)
        types = [e.event_type for e in ev_rec]
        self.assertIn(CognitiveEventType.SENSOR_RECOVERED, types)
        rec_event = [e for e in ev_rec if e.event_type == CognitiveEventType.SENSOR_RECOVERED][0]
        self.assertEqual(rec_event.data["sensor"], "camera")

    # -------------------------------------------------------------------------
    # 14. Novelty Behavior via CognitiveEventBus
    # -------------------------------------------------------------------------

    def test_14_novelty_behavior(self):
        """14. Novel events have is_novel=True first time, False on recurrence."""
        p1 = UnifiedPersonState(person_id="novel_vip_99", name="Ahmet", is_known=True, is_present=True)

        res1 = self.loop.step({"people": [p1]})
        unprocessed1 = [e for e in self.bus._events if e.event_type == CognitiveEventType.PERSON_APPEARED]
        self.assertEqual(len(unprocessed1), 1)
        self.assertTrue(unprocessed1[0].is_novel)

        # Leave and return
        self.loop.step({"people": []})
        self.loop.step({"people": [p1]})
        unprocessed2 = [e for e in self.bus._events if e.event_type == CognitiveEventType.PERSON_RETURNED]
        self.assertEqual(len(unprocessed2), 1)
        # Returned event signature has not been seen before -> novel
        self.assertTrue(unprocessed2[0].is_novel)

    # -------------------------------------------------------------------------
    # 15. Deterministic Replay Across Cognitive Loops
    # -------------------------------------------------------------------------

    def test_15_deterministic_replay_of_events(self):
        """15. Identical perception sequence yields identical event streams on separate loops."""
        p_seq = [
            {"people": [UnifiedPersonState(person_id="p1", name="Baran", is_known=True, is_present=True)]},
            {"vad": True, "doa_deg": 10.0},
            {"vad": False},
            {"tts_speaking": True},
            {"tts_speaking": False},
            {"people": []},
        ]

        loop_a = CognitiveLoop(temporal_history_size=10)
        res_a = loop_a.run_consecutive_steps(len(p_seq), perception_inputs=p_seq)

        loop_b = CognitiveLoop(temporal_history_size=10)
        res_b = loop_b.run_consecutive_steps(len(p_seq), perception_inputs=p_seq)

        events_a = [e.event_type for e in loop_a.event_bus._events]
        events_b = [e.event_type for e in loop_b.event_bus._events]
        self.assertEqual(events_a, events_b)
        self.assertIn(CognitiveEventType.PERSON_APPEARED, events_a)
        self.assertIn(CognitiveEventType.PERSON_SPOKE, events_a)
        self.assertIn(CognitiveEventType.ROBOT_STARTED_SPEAKING, events_a)
        self.assertIn(CognitiveEventType.ROBOT_FINISHED_SPEAKING, events_a)
        self.assertIn(CognitiveEventType.PERSON_DISAPPEARED, events_a)

    # -------------------------------------------------------------------------
    # 16. Event Ordering & Timestamp Monotonicity
    # -------------------------------------------------------------------------

    def test_16_event_ordering_and_monotonic_timestamps(self):
        """16. All emitted events strictly follow chronological ordering and monotonic timestamps."""
        t_base = time.time()
        p = UnifiedPersonState(person_id="p1", name="Baran", is_present=True)
        self.loop.step({"people": [p]})
        self.loop.step({"vad": True})
        self.loop.step({"vad": False})
        self.loop.step({"people": []})

        events = list(self.bus._events)
        self.assertGreaterEqual(len(events), 3)

        timestamps = [e.timestamp for e in events]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertTrue(all(t >= t_base for t in timestamps))

    # -------------------------------------------------------------------------
    # 17. Anti-Storm Guarantee (Static Continuous Scene)
    # -------------------------------------------------------------------------

    def test_17_no_event_storm_on_static_scene(self):
        """17. A static sensory scene running for 30 cycles produces exactly ZERO new events after initial."""
        p = UnifiedPersonState(person_id="p1", name="Baran", is_present=True)
        static_frame = {
            "people": [p],
            "vad": False,
            "tts_speaking": False,
            "social_phase": ConversationPhase.ENGAGED,
            "active_target_id": "target_p1",
            "robot_state": {"head_yaw_deg": 0.0},
        }

        # Step 0 -> initial events (appearance, target, phase)
        self.loop.step(static_frame)
        initial_event_count = len(self.bus._events)
        self.assertGreater(initial_event_count, 0)

        # 30 subsequent static cycles
        for _ in range(30):
            self.loop.step(static_frame)

        # Count of events in bus should NOT have grown at all
        final_event_count = len(self.bus._events)
        self.assertEqual(final_event_count, initial_event_count)

    # -------------------------------------------------------------------------
    # 18. Existing WorldModel Regression Check
    # -------------------------------------------------------------------------

    def test_18_world_model_regression_check(self):
        """18. WorldModel maintains all baseline capabilities alongside event generation."""
        wm = self.loop.world_model
        p = UnifiedPersonState(person_id="p_test", name="Misafir", is_present=True)
        self.loop.step({"people": [p]})

        snap = wm.get_snapshot()
        self.assertEqual(len(snap.people), 1)
        self.assertEqual(snap.people[0].person_id, "p_test")
        self.assertGreater(wm.temporal_history_len, 0)

    # -------------------------------------------------------------------------
    # 19. Mid-Session Face Recognition (PERSON_RECOGNIZED)
    # -------------------------------------------------------------------------

    def test_19_person_recognized_transition(self):
        """19. Anonymous person recognized mid-session triggers PERSON_RECOGNIZED."""
        # Frame 1: anonymous guest
        p_anon = UnifiedPersonState(person_id="guest_01", name="Misafir", is_known=False, is_present=True)
        ev1 = self.detector.detect_transitions({"people": [p_anon]})
        self.assertEqual(len(ev1), 1)
        self.assertEqual(ev1[0].event_type, CognitiveEventType.PERSON_APPEARED)

        # Frame 2: same person_id recognized as Baran
        p_known = UnifiedPersonState(person_id="guest_01", name="Baran", is_known=True, is_present=True)
        ev2 = self.detector.detect_transitions({"people": [p_known]})
        self.assertEqual(len(ev2), 1)
        self.assertEqual(ev2[0].event_type, CognitiveEventType.PERSON_RECOGNIZED)
        self.assertEqual(ev2[0].data["name"], "Baran")


if __name__ == "__main__":
    unittest.main()
