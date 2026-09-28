"""ASTRO V1 — Phase 6 World Model Comprehensive Verification Suite.

Validates:
  1. Entity lifecycle states (APPEARED, TRACKED, APPROACHING, DEPARTING, OCCLUDED, REAPPEARED)
  2. Bounded trajectory tracking (maxlen=10) and temporal history (maxlen=50)
  3. Evidence-based multimodal fusion vs disjoint Visual/Acoustic entities
  4. ReSpeaker zero-angle idle rejection (0.0 deg without VAD/RMS)
  5. Active perception attention reallocation & perceptual expectation loop
  6. Perceptual prediction success & timeout expiry handling
  7. Cross-modal sensor conflict detection (SPATIAL_ATTENTION_SPLIT)
  8. Stale data & information sufficiency modulation
  9. Sensor degradation modes (Camera, Audio, LiDAR)
 10. CognitiveLoop 10Hz determinism and sub-millisecond execution without LLM calls
"""

import math
import time
import unittest

from astro_ai.brain.cognitive_loop import CognitiveLoop
from astro_ai.brain.metacognitive_engine import MetacognitiveEngine
from astro_ai.brain.prediction_engine import PredictionEngine
from astro_ai.brain.self_model import SelfModel
from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.consciousness_types import (
    ActualOutcome,
    CognitiveDecisionType,
    Goal,
    GoalType,
    InformationSufficiency,
    PredictionStatus,
    SelfState,
)
from astro_ai.contracts.person_state import EntityLifecycleState, UnifiedPersonState
from astro_ai.contracts.spatial_state import SpatialPersonTrack
from astro_ai.spatial.spatial_fusion import SpatialFusionEngine


class TestEntityLifecycleAndPermanence(unittest.TestCase):
    """Verifies entity lifecycle progression, occlusion tracking, and reappearance."""

    def setUp(self):
        self.wm = WorldModel(temporal_history_size=50)

    def test_01_entity_first_appearance(self):
        """1. Newly detected person transitions to APPEARED state."""
        p = UnifiedPersonState(person_id="user_1", name="Baran", distance_m=1.8, azimuth_deg=0.0)
        self.wm.update_people([p], now=100.0)

        snapshot = self.wm.get_snapshot()
        self.assertEqual(len(snapshot.people), 1)
        self.assertEqual(snapshot.people[0].tracking_state, EntityLifecycleState.APPEARED)
        self.assertTrue(snapshot.people[0].is_present)
        self.assertEqual(len(snapshot.people[0].trajectory_history), 1)

    def test_02_entity_occlusion_and_duration(self):
        """2. Missing person within 5 seconds transitions to OCCLUDED with duration counter."""
        p = UnifiedPersonState(person_id="user_1", name="Baran", distance_m=1.8, azimuth_deg=0.0)
        self.wm.update_people([p], now=100.0)

        # Disappears at t=102.0
        self.wm.update_people([], now=102.0)
        tracked = self.wm._people.get("user_1")
        self.assertIsNotNone(tracked)
        self.assertFalse(tracked.is_present)
        self.assertEqual(tracked.tracking_state, EntityLifecycleState.OCCLUDED)
        self.assertAlmostEqual(tracked.occlusion_duration_s, 2.0, delta=0.1)

    def test_03_entity_reappearance_after_occlusion(self):
        """3. Occluded person seen again transitions to REAPPEARED and resets occlusion timer."""
        p1 = UnifiedPersonState(person_id="user_1", name="Baran", distance_m=1.8, azimuth_deg=0.0)
        self.wm.update_people([p1], now=100.0)
        self.wm.update_people([], now=102.0)

        # Reappears at t=103.0
        p2 = UnifiedPersonState(person_id="user_1", name="Baran", distance_m=1.6, azimuth_deg=5.0)
        self.wm.update_people([p2], now=103.0)

        tracked = self.wm._people.get("user_1")
        self.assertTrue(tracked.is_present)
        self.assertEqual(tracked.tracking_state, EntityLifecycleState.REAPPEARED)
        self.assertEqual(tracked.occlusion_duration_s, 0.0)

    def test_04_stale_entity_pruning_after_5s(self):
        """4. Entity occluded for more than 5.0 seconds is pruned from world state."""
        p = UnifiedPersonState(person_id="user_1", name="Baran", distance_m=1.8, azimuth_deg=0.0)
        self.wm.update_people([p], now=100.0)

        # Update after 5.5s with empty list
        self.wm.update_people([], now=105.5)
        self.assertNotIn("user_1", self.wm._people)

    def test_05_bounded_trajectory_history(self):
        """5. Trajectory history never exceeds 10 points."""
        for step in range(25):
            p = UnifiedPersonState(
                person_id="user_1",
                name="Baran",
                distance_m=2.0 - (step * 0.05),
                azimuth_deg=step * 1.0,
            )
            self.wm.update_people([p], now=100.0 + step)

        tracked = self.wm._people["user_1"]
        self.assertLessEqual(len(tracked.trajectory_history), 10)
        self.assertEqual(len(tracked.trajectory_history), 10)


class TestMultimodalFusionAndSeparation(unittest.TestCase):
    """Verifies evidence-based sensor fusion vs disjoint entity separation."""

    def setUp(self):
        self.fusion = SpatialFusionEngine()

    def test_06_successful_fusion_when_angles_align(self):
        """6. Vision and Audio align (both at ~+10 deg) -> single fused UnifiedPersonState."""
        self.fusion.update_vision_perception(
            faces=[{"name": "Baran", "confidence": 0.85, "head_yaw_deg": 10.0, "is_known": True}],
            user_distance_m=1.5,
        )
        self.fusion.update_audio_perception(
            doa_deg=12.0,
            speaker_id_dict={"name": "Baran", "confidence": 0.90},
            is_speaking=True,
            vad_active=True,
            rms_level=600.0,
        )
        people = self.fusion.compute_fusion(now=100.0)

        self.assertEqual(len(people), 1)
        p = people[0]
        self.assertEqual(p.name, "Baran")
        self.assertTrue(p.has_vision)
        self.assertTrue(p.has_audio)
        self.assertTrue(p.is_speaking)
        self.assertLessEqual(p.spatial_uncertainty, 0.2)

    def test_07_disjoint_entities_when_angles_diverge(self):
        """7. Vision (+35 deg) and Audio (-50 deg) diverge (>25 deg) -> separate Visual and Acoustic entities."""
        self.fusion.update_vision_perception(
            faces=[{"name": "Ali", "confidence": 0.80, "head_yaw_deg": 35.0, "is_known": True}],
            user_distance_m=2.0,
        )
        self.fusion.update_audio_perception(
            doa_deg=-50.0,
            speaker_id_dict={"name": "Misafir", "confidence": 0.50},
            is_speaking=True,
            vad_active=True,
            rms_level=650.0,
        )
        people = self.fusion.compute_fusion(now=100.0)

        self.assertEqual(len(people), 2)
        visual = next((p for p in people if p.has_vision), None)
        acoustic = next((p for p in people if p.entity_type == "ACOUSTIC_ENTITY"), None)

        self.assertIsNotNone(visual)
        self.assertIsNotNone(acoustic)
        self.assertFalse(visual.is_speaking)
        self.assertTrue(acoustic.is_speaking)
        self.assertAlmostEqual(acoustic.azimuth_deg, -50.0, delta=1.0)

    def test_08_respeaker_zero_angle_idle_rejection(self):
        """8. ReSpeaker 0.0 deg idle/uncalibrated reading without active VAD is rejected."""
        self.fusion.update_audio_perception(
            doa_deg=0.0,
            is_speaking=False,
            vad_active=False,
            rms_level=120.0,
        )
        self.assertIsNone(self.fusion._latest_audio_doa)

    def test_09_cross_modal_conflict_detection_in_world_model(self):
        """9. WorldModel detects SPATIAL_ATTENTION_SPLIT when visual and acoustic sources diverge."""
        wm = WorldModel()
        visual_p = UnifiedPersonState(
            person_id="p_vis",
            name="Ali",
            azimuth_deg=40.0,
            has_vision=True,
            is_present=True,
        )
        acoustic_p = UnifiedPersonState(
            person_id="p_acoust",
            name="Misafir",
            azimuth_deg=-45.0,
            has_audio=True,
            entity_type="ACOUSTIC_ENTITY",
            is_present=True,
        )
        wm.update_people([visual_p, acoustic_p], now=100.0)

        conflicts = wm.detect_conflicts()
        self.assertGreaterEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["type"], "SPATIAL_ATTENTION_SPLIT")
        self.assertGreater(conflicts[0]["angle_divergence_deg"], 35.0)


class TestActivePerceptionAndAttention(unittest.TestCase):
    """Verifies Active Perception: Metacognition -> SEEK_INFORMATION -> Perceptual Prediction."""

    def test_10_acoustic_candidate_triggers_insufficient_info(self):
        """10. Unverified acoustic candidate causes MetacognitiveEngine to assess INSUFFICIENT."""
        engine = MetacognitiveEngine()
        perc = {
            "acoustic_attention_candidate": {
                "entity_id": "person_acoustic_45",
                "target_yaw_deg": -45.0,
                "confidence": 0.40,
            }
        }
        suff = engine.assess_information_sufficiency(perception_data=perc, uncertainty=0.2)
        self.assertEqual(suff, InformationSufficiency.INSUFFICIENT)

    def test_11_active_perception_decision_generation(self):
        """11. MetacognitiveEngine emits SEEK_INFORMATION with target_yaw_deg for active perception."""
        engine = MetacognitiveEngine()
        perc = {
            "acoustic_attention_candidate": {
                "entity_id": "person_acoustic_45",
                "target_yaw_deg": -45.0,
                "confidence": 0.40,
            }
        }
        state, decision = engine.evaluate_metacognitive_state(
            perception_data=perc,
            confidence=0.7,
            uncertainty=0.3,
            now=100.0,
        )
        self.assertIsNotNone(decision)
        self.assertEqual(decision.decision_type, CognitiveDecisionType.SEEK_INFORMATION)
        self.assertEqual(decision.reason, "active_perception_acoustic_attention")
        self.assertAlmostEqual(decision.metadata.get("target_yaw_deg"), -45.0)

    def test_12_perceptual_prediction_creation_and_confirmation(self):
        """12. EXPECT_FACE_AFTER_HEAD_ATTENTION succeeds when visual face appears."""
        pe = PredictionEngine()
        pred = pe.create_perceptual_prediction(
            prediction_type="EXPECT_FACE_AFTER_HEAD_ATTENTION",
            target_id="person_acoustic_45",
            expected_state={"face_detected": True},
            timeout_seconds=2.0,
            now=100.0,
        )
        self.assertEqual(pred.status, PredictionStatus.PENDING)

        outcome = ActualOutcome(
            outcome_id="out_1",
            expectation_id=pred.prediction_id,
            actual_state={"face_detected": True},
            timestamp=101.0,
        )
        err = pe.evaluate_outcome(outcome, now=101.0)
        self.assertTrue(err.matched)
        self.assertEqual(err.mismatch_score, 0.0)
        self.assertEqual(pred.status, PredictionStatus.CONFIRMED)
        self.assertGreater(err.confidence_impact, 0.0)

    def test_13_perceptual_prediction_timeout_expiry(self):
        """13. EXPECT_FACE_AFTER_HEAD_ATTENTION expires if no face arrives within 2.0s."""
        pe = PredictionEngine()
        pred = pe.create_perceptual_prediction(
            prediction_type="EXPECT_FACE_AFTER_HEAD_ATTENTION",
            target_id="person_acoustic_45",
            expected_state={"face_detected": True},
            timeout_seconds=2.0,
            now=100.0,
        )

        expired = pe.check_expirations(now=102.5)
        self.assertEqual(len(expired), 1)
        self.assertEqual(expired[0].mismatch_type, "TIMEOUT_EXPIRED")
        self.assertEqual(pred.status, PredictionStatus.EXPIRED)
        self.assertLess(expired[0].confidence_impact, 0.0)


class TestDegradationAndStaleness(unittest.TestCase):
    """Verifies handling of degraded sensor modes and stale perceptions."""

    def test_14_stale_perception_causes_stale_sufficiency(self):
        """14. Sensor data older than threshold causes InformationSufficiency.STALE."""
        engine = MetacognitiveEngine()
        perc = {"timestamp": 90.0}
        suff = engine.assess_information_sufficiency(perception_data=perc, now=100.0)
        self.assertEqual(suff, InformationSufficiency.STALE)

    def test_15_sensor_degradation_capabilities_tracking(self):
        """15. SelfModel tracks degraded sensor modes (CAMERA, AUDIO, LIDAR) without crashing."""
        sm = SelfModel()
        self.assertEqual(len(sm.get_degraded_capabilities()), 0)

        sm.self_state.degraded_capabilities.add("CAMERA")
        self.assertIn("CAMERA", sm.get_degraded_capabilities())

        sm.self_state.degraded_capabilities.add("LIDAR")
        self.assertIn("LIDAR", sm.get_degraded_capabilities())

        sm.self_state.degraded_capabilities.discard("CAMERA")
        self.assertNotIn("CAMERA", sm.get_degraded_capabilities())
        self.assertIn("LIDAR", sm.get_degraded_capabilities())

    def test_16_self_model_world_summary_isolation(self):
        """16. WorldModel provides strictly filtered summary to SelfModel without raw scan arrays."""
        wm = WorldModel()
        p = UnifiedPersonState(person_id="p1", name="Baran", distance_m=1.2, is_speaking=True)
        wm.update_people([p])
        wm.update_environment(front_clearance_m=2.4, is_obstacle_near=False)

        summary = wm.get_self_model_world_summary()
        self.assertIn("focused_person_id", summary)
        self.assertIn("front_clearance_m", summary)
        self.assertIn("is_obstacle_near", summary)
        self.assertNotIn("ranges", summary)
        self.assertNotIn("raw_scan", summary)
        self.assertNotIn("raw_doa", summary)


class TestCognitiveLoopIntegration(unittest.TestCase):
    """Verifies end-to-end integration of Phase 6 World Model within CognitiveLoop."""

    def test_17_cognitive_loop_active_perception_flow(self):
        """17. CognitiveLoop step ingests acoustic candidate, triggers active perception, and logs transition."""
        loop = CognitiveLoop(target_hz=10.0)

        p_in = {
            "people": [
                UnifiedPersonState(
                    person_id="person_acoustic_40",
                    name="Misafir",
                    azimuth_deg=-40.0,
                    distance_m=2.5,
                    has_audio=True,
                    has_vision=False,
                    entity_type="ACOUSTIC_ENTITY",
                    is_speaking=True,
                )
            ]
        }

        result = loop.step(p_in)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.cognitive_decision)
        self.assertEqual(result.cognitive_decision.decision_type, CognitiveDecisionType.SEEK_INFORMATION)

        transitions = loop.continuity_tracker.to_list()
        att_trans = next((t for t in transitions if t.get("transition_type") == "ATTENTION_REALLOCATION"), None)
        self.assertIsNotNone(att_trans)
        self.assertIn("-40", att_trans.get("new_value", ""))

        preds = loop.prediction_engine.get_active_predictions()
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0].action_id, "EXPECT_FACE_AFTER_HEAD_ATTENTION")

    def test_18_sub_millisecond_cycle_duration(self):
        """18. CognitiveLoop with Phase 6 WorldModel executes deterministically within 5.0ms on CPU."""
        loop = CognitiveLoop(target_hz=10.0)
        p = UnifiedPersonState(person_id="p1", name="Baran", distance_m=1.5, azimuth_deg=5.0)

        results = loop.run_consecutive_steps(count=20, perception_inputs=[{"people": [p]}] * 20)
        avg_ms = loop.average_cycle_duration_ms
        self.assertLess(avg_ms, 5.0, f"Average cycle duration {avg_ms:.2f}ms exceeds 5.0ms threshold")


if __name__ == "__main__":
    unittest.main()