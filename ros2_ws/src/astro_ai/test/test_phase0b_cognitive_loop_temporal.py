"""ASTRO V1 — Phase 0B Cognitive Loop & World Model Temporal Extension Test Suite.

Verifies:
  1. Synthetic perception replay
  2. Temporal snapshot accumulation
  3. Ring-buffer bounded capacity
  4. Snapshot immutability / read-only behavior
  5. Empty / no-perception cycle execution
  6. Multiple consecutive cycles
  7. Deterministic replay across separate loops
  8. Existing WorldModel APIs and behavior regression
  9. Cycle timing, metrics tracking, and non-blocking performance
  10. Event bus integration and high-salience event mirroring
"""

import copy
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
from astro_ai.brain.cognitive_loop import CognitiveLoop, CognitiveCycleResult
from astro_ai.brain.world_model import WorldModel, WorldStateSnapshot
from astro_ai.contracts.consciousness_types import CognitiveEventType
from astro_ai.contracts.person_state import UnifiedPersonState


class TestPhase0BCognitiveLoopTemporal(unittest.TestCase):
    """Evaluation suite for Phase 0B Cognitive Loop and World Model temporal extensions."""

    def setUp(self):
        self.world_model = WorldModel(temporal_history_size=20)
        self.event_bus = CognitiveEventBus(max_capacity=100)
        self.loop = CognitiveLoop(
            world_model=self.world_model,
            event_bus=self.event_bus,
            target_hz=10.0,
            temporal_history_size=20,
        )

    # -------------------------------------------------------------------------
    # 1. Synthetic Perception Replay
    # -------------------------------------------------------------------------

    def test_01_synthetic_perception_replay(self):
        """1. CognitiveLoop ingests sequential synthetic perception frames and updates state."""
        p1 = UnifiedPersonState(person_id="p1", name="Baran", distance_m=2.0, is_present=True)
        p2 = UnifiedPersonState(person_id="p2", name="Misafir", distance_m=1.2, is_present=True, is_speaking=True)

        frames = [
            {"people": [p1], "environment": {"front_clearance_m": 4.5}},
            {"people": [p1, p2], "environment": {"front_clearance_m": 1.2}},
            {"people": [p2], "robot_state": {"head_yaw_deg": 15.0}},
        ]

        results = self.loop.run_consecutive_steps(count=len(frames), perception_inputs=frames)
        self.assertEqual(len(results), 3)

        # Frame 0: Baran present, front clearance 4.5m
        self.assertEqual(results[0].active_people_count, 1)
        self.assertAlmostEqual(results[0].world_snapshot.environment["front_clearance_m"], 4.5)
        self.assertFalse(results[0].has_active_speaker)

        # Frame 1: 2 people, p2 is speaking
        self.assertEqual(results[1].active_people_count, 2)
        self.assertTrue(results[1].has_active_speaker)
        self.assertEqual(results[1].world_snapshot.active_speaker.person_id, "p2")

        # Frame 2: 1 person, head yaw 15.0 deg
        self.assertEqual(results[2].active_people_count, 1)
        self.assertAlmostEqual(results[2].world_snapshot.robot_state["head_yaw_deg"], 15.0)

    # -------------------------------------------------------------------------
    # 2. Temporal Snapshot Accumulation
    # -------------------------------------------------------------------------

    def test_02_temporal_snapshot_accumulation(self):
        """2. Temporal snapshots accumulate in WorldModel with monotonically increasing timestamps."""
        for i in range(5):
            time.sleep(0.01)
            self.loop.step({"robot_state": {"tick": i}})

        window = self.world_model.get_temporal_window()
        self.assertEqual(len(window), 5)
        self.assertEqual(self.world_model.temporal_history_len, 5)

        # Verify strictly increasing timestamps
        timestamps = [s.timestamp for s in window]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertTrue(all(t2 > t1 for t1, t2 in zip(timestamps, timestamps[1:])))

        # Verify latest snapshot matches last committed
        latest = self.world_model.get_latest_temporal_snapshot()
        self.assertIsNotNone(latest)
        self.assertEqual(latest.robot_state.get("tick"), 4)

    # -------------------------------------------------------------------------
    # 3. Ring-Buffer Bounded Capacity
    # -------------------------------------------------------------------------

    def test_03_ring_buffer_bounded_capacity(self):
        """3. Bounded ring buffer strictly limits temporal history and evicts oldest frames."""
        capacity = 15
        wm = WorldModel(temporal_history_size=capacity)
        test_loop = CognitiveLoop(world_model=wm, temporal_history_size=capacity)

        total_steps = 35
        for i in range(total_steps):
            test_loop.step({"robot_state": {"frame_id": i}})

        self.assertEqual(wm.temporal_history_len, capacity)
        window = wm.get_temporal_window()
        self.assertEqual(len(window), capacity)

        # Oldest retained frame should be frame 20 (35 - 15)
        self.assertEqual(window[0].robot_state["frame_id"], 20)
        # Newest should be frame 34
        self.assertEqual(window[-1].robot_state["frame_id"], 34)

        # Window with limit
        sub_window = wm.get_temporal_window(limit=5)
        self.assertEqual(len(sub_window), 5)
        self.assertEqual(sub_window[-1].robot_state["frame_id"], 34)

    # -------------------------------------------------------------------------
    # 4. Snapshot Immutability / Read-Only Behavior
    # -------------------------------------------------------------------------

    def test_04_snapshot_immutability_and_safety(self):
        """4. Manipulating returned temporal windows does not corrupt internal WorldModel state."""
        self.loop.step({"robot_state": {"head_yaw_deg": 10.0}})
        window = self.world_model.get_temporal_window()
        self.assertEqual(len(window), 1)

        # Attempt to mutate the returned list
        window.clear()
        self.assertEqual(self.world_model.temporal_history_len, 1)
        self.assertEqual(len(self.world_model.get_temporal_window()), 1)

        # Snapshot robot_state copy independence
        snap = self.world_model.get_latest_temporal_snapshot()
        snap.robot_state["head_yaw_deg"] = 999.0

        fresh_snap = self.world_model.get_snapshot()
        self.assertAlmostEqual(fresh_snap.robot_state["head_yaw_deg"], 10.0)

    # -------------------------------------------------------------------------
    # 5. Empty / No-Perception Cycle Execution
    # -------------------------------------------------------------------------

    def test_05_empty_no_perception_cycle(self):
        """5. CognitiveLoop runs stably and without errors when no perception data is supplied."""
        # Empty dict
        res1 = self.loop.step({})
        self.assertEqual(res1.cycle_index, 1)
        self.assertEqual(res1.active_people_count, 0)
        self.assertFalse(res1.has_active_speaker)
        self.assertGreaterEqual(res1.duration_ms, 0.0)

        # None input
        res2 = self.loop.step(None)
        self.assertEqual(res2.cycle_index, 2)
        self.assertEqual(self.loop.cycle_count, 2)
        self.assertEqual(self.world_model.temporal_history_len, 2)

    # -------------------------------------------------------------------------
    # 6. Multiple Consecutive Cycles
    # -------------------------------------------------------------------------

    def test_06_multiple_consecutive_cycles(self):
        """6. Executes 50 consecutive cycles continuously maintaining non-blocking performance."""
        results = self.loop.run_consecutive_steps(count=50)
        self.assertEqual(len(results), 50)
        self.assertEqual(self.loop.cycle_count, 50)
        self.assertEqual(results[-1].cycle_index, 50)

        # Check that average duration is tracked and low
        self.assertGreater(self.loop.average_cycle_duration_ms, 0.0)
        self.assertLess(self.loop.average_cycle_duration_ms, 25.0)

    # -------------------------------------------------------------------------
    # 7. Deterministic Replay Across Separate Loops
    # -------------------------------------------------------------------------

    def test_07_deterministic_replay(self):
        """7. Identical perception sequence yields identical world states on separate loops."""
        p_seq = [
            {"people": [UnifiedPersonState(person_id="p1", distance_m=3.0, is_present=True)]},
            {"people": [UnifiedPersonState(person_id="p1", distance_m=2.5, is_present=True)]},
            {"people": [UnifiedPersonState(person_id="p1", distance_m=2.0, is_present=True, is_speaking=True)]},
            {"robot_state": {"execution_state": "LISTENING"}},
        ]

        # Loop A
        loop_a = CognitiveLoop(temporal_history_size=10)
        res_a = loop_a.run_consecutive_steps(count=len(p_seq), perception_inputs=p_seq)

        # Loop B
        loop_b = CognitiveLoop(temporal_history_size=10)
        res_b = loop_b.run_consecutive_steps(count=len(p_seq), perception_inputs=p_seq)

        for i in range(len(p_seq)):
            snap_a = res_a[i].world_snapshot
            snap_b = res_b[i].world_snapshot

            self.assertEqual(len(snap_a.people), len(snap_b.people))
            if snap_a.people and snap_b.people:
                self.assertEqual(snap_a.people[0].person_id, snap_b.people[0].person_id)
                self.assertAlmostEqual(snap_a.people[0].distance_m, snap_b.people[0].distance_m)
            self.assertEqual(
                snap_a.active_speaker is not None,
                snap_b.active_speaker is not None,
            )
            self.assertEqual(
                snap_a.robot_state["execution_state"],
                snap_b.robot_state["execution_state"],
            )

    # -------------------------------------------------------------------------
    # 8. Existing WorldModel Regression & Backward Compatibility
    # -------------------------------------------------------------------------

    def test_08_existing_world_model_regression(self):
        """8. WorldModel existing update APIs remain 100% backward compatible."""
        wm = WorldModel()  # Default constructor without arguments
        self.assertEqual(wm.temporal_history_len, 0)

        # update_robot_state
        wm.update_robot_state(execution_state="SPEAKING", head_yaw_deg=45.0)
        self.assertEqual(wm._robot_state["execution_state"], "SPEAKING")
        self.assertAlmostEqual(wm._robot_state["head_yaw_deg"], 45.0)

        # update_environment
        wm.update_environment(location_name="Ankara Ar-Ge", ambient_rms=250.0)
        self.assertEqual(wm._environment["location_name"], "Ankara Ar-Ge")

        # update_conversation_state
        wm.update_conversation_state(turn_count=3, is_session_active=True)
        self.assertTrue(wm._conversation_state["is_session_active"])
        self.assertEqual(wm._conversation_state["turn_count"], 3)

        # record_event
        wm.record_event("Test event 1")
        wm.record_event("Test event 2")
        snap = wm.get_snapshot()
        self.assertEqual(len(snap.recent_events), 2)
        self.assertIn("Test event 2", snap.recent_events[-1])

        # clear_temporal_history
        wm.commit_temporal_snapshot()
        self.assertEqual(wm.temporal_history_len, 1)
        wm.clear_temporal_history()
        self.assertEqual(wm.temporal_history_len, 0)

    # -------------------------------------------------------------------------
    # 9. High-Salience Event Mirroring Into World Model
    # -------------------------------------------------------------------------

    def test_09_high_salience_event_mirroring(self):
        """9. High-salience events in event bus are automatically mirrored into WorldModel recent events."""
        # Salience >= 0.5 event (PERSON_APPEARED default is 0.75)
        self.event_bus.create_and_publish(
            CognitiveEventType.PERSON_APPEARED,
            source="vision",
            data={"person_id": "baran_01"},
        )
        self.loop.step()

        snap = self.world_model.get_snapshot()
        self.assertTrue(any("PERSON_APPEARED" in e for e in snap.recent_events))
        self.assertTrue(any("baran_01" in e for e in snap.recent_events))

    # -------------------------------------------------------------------------
    # 10. Reset Functionality
    # -------------------------------------------------------------------------

    def test_10_loop_reset(self):
        """10. CognitiveLoop.reset cleanly resets cycle count, history, and caches."""
        self.loop.run_consecutive_steps(count=10)
        self.assertEqual(self.loop.cycle_count, 10)
        self.assertGreater(self.world_model.temporal_history_len, 0)

        self.loop.reset()
        self.assertEqual(self.loop.cycle_count, 0)
        self.assertEqual(self.world_model.temporal_history_len, 0)
        self.assertEqual(len(self.event_bus), 0)


if __name__ == "__main__":
    unittest.main()
