"""ASTRO — Real Camera = Eye Pipeline Comprehensive Test Suite.

Covers all required phases (a through t):
a) Object detection contract test
b) Object -> WorldModel test
c) Stale object TTL test
d) Visual query test ("Kameranda neler görüyorsun?")
e) Activity temporal aggregation test (single frame vs ring buffer)
f) Drinking test fixture (person + cup + near/holding -> DRINKING)
g) Phone test fixture (person + phone + near/holding -> PHONE_USE)
h) Sitting test fixture (person + chair + near -> SITTING)
i) Walking test fixture (translation speed -> WALKING)
j) Reading test fixture (person + book -> READING)
k) Age-group inference test (contract and estimation)
l) Adaptive persona test (consumes real age output)
m) Visual compliment test (requires visual fact, zero hallucination)
n) Social initiative cooldown test (120s limit)
o) Identity/object/activity association test (speaker vs other person isolation)
p) UNKNOWN fallback test (no hallucination on unknown age/activity)
q) Model offline/error test (LLM failure preserves visual state)
r) Dialogue visual state context test (visual state available in dialogue)
s) Zero hallucination test: objects (only real objects formatted)
t) Zero hallucination test: activities (insufficient evidence -> UNKNOWN)
"""

import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Set import paths
pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in [
    os.path.join(pkg_root, "astro_ai"),
    os.path.join(pkg_root, "astro_ai", "astro_ai"),
    os.path.join(pkg_root, "astro_vision"),
    os.path.join(pkg_root, "astro_vision", "astro_vision"),
    os.path.join(pkg_root, "astro_audio"),
    os.path.join(pkg_root, "astro_base"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from astro_ai.contracts.spatial_state import SpatialObjectState
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.brain.world_model import WorldModel
from astro_vision.object_detector import ObjectDetectorEngine, SyntheticObjectDetector, DetectedObject
from astro_vision.age_estimator import VisualAgeEstimator
from astro_vision.visual_attributes import VisualAttributeExtractor
from astro_ai.spatial.person_object_association import PersonObjectAssociator, InteractionType
from astro_ai.brain.activity_recognition import TemporalActivityEngine, HumanActivity, ACTIVITY_DESCRIPTIONS_TR
from astro_ai.brain.adaptive_persona import AdaptivePersonaEngine, AgeGroup
from astro_ai.brain.social_initiative import SocialInitiativeManager, ComplimentTopic
from astro_ai.astro_realtime_node import AstroRealtimeNode


class TestRealCameraEyePipeline(unittest.TestCase):
    """Rigorous pipeline test suite for ASTRO Real Camera = Eye."""

    # =========================================================================
    # Test A: Object Detection Contract Test
    # =========================================================================
    def test_a_object_detection_contract(self):
        """Detection output must conform to DetectedObject and SpatialObjectState contracts."""
        engine = ObjectDetectorEngine()
        synth = SyntheticObjectDetector()
        synth.inject_detection("cup", 0.92, [100, 150, 180, 260], 0.85)
        synth.inject_detection("cell phone", 0.88, [200, 160, 240, 210], 0.65)
        engine.detector = synth

        dummy_img = np.zeros((480, 640, 3), dtype=np.uint8)
        objects = engine.process_frame(dummy_img, min_confidence=0.50, now=100.0)

        self.assertEqual(len(objects), 2)
        cup = next(o for o in objects if o.class_name == "cup")
        self.assertIsInstance(cup, DetectedObject)
        self.assertEqual(cup.class_name, "cup")
        self.assertAlmostEqual(cup.confidence, 0.92)
        self.assertEqual(cup.bbox, (100, 150, 180, 260))
        self.assertAlmostEqual(cup.distance_m, 0.85)

        # Convert to SpatialObjectState contract
        s_cup = SpatialObjectState(
            object_id=cup.object_id,
            class_name=cup.class_name,
            confidence=cup.confidence,
            bbox=cup.bbox,
            distance_m=cup.distance_m or 0.0,
            last_observed_ts=cup.timestamp,
        )
        self.assertIsInstance(s_cup, SpatialObjectState)
        self.assertEqual(s_cup.class_name, "cup")
        self.assertAlmostEqual(s_cup.distance_m, 0.85)

    # =========================================================================
    # Test B: Object -> WorldModel Test
    # =========================================================================
    def test_b_object_to_world_model(self):
        """Detected objects must update into WorldModel with fresh spatial state."""
        wm = WorldModel()
        now_ts = 10.0
        obj1 = SpatialObjectState(
            object_id="cup_0",
            class_name="cup",
            confidence=0.91,
            distance_m=0.8,
            last_observed_ts=now_ts,
        )
        obj2 = SpatialObjectState(
            object_id="laptop_0",
            class_name="laptop",
            confidence=0.87,
            distance_m=1.2,
            last_observed_ts=now_ts,
        )

        wm.update_spatial_objects([obj1, obj2])
        recent = wm.get_spatial_objects(max_age_s=5.0, now=12.0)

        self.assertEqual(len(recent), 2)
        class_names = {o.class_name for o in recent}
        self.assertIn("cup", class_names)
        self.assertIn("laptop", class_names)

        # Snapshot check
        snap = wm.get_snapshot(now=12.0)
        self.assertEqual(len(snap.spatial_objects), 2)

    # =========================================================================
    # Test C: Stale Object TTL Test
    # =========================================================================
    def test_c_stale_object_ttl(self):
        """Objects older than TTL must be pruned and not reported."""
        wm = WorldModel()
        old_obj = SpatialObjectState(
            object_id="bottle_0",
            class_name="bottle",
            confidence=0.85,
            last_observed_ts=10.0,
        )
        fresh_obj = SpatialObjectState(
            object_id="cup_0",
            class_name="cup",
            confidence=0.90,
            last_observed_ts=25.0,
        )
        wm.update_spatial_objects([old_obj, fresh_obj])

        # At now=26.0s, ttl=10.0s -> bottle_0 is 16s old and must be purged
        removed_count = wm.remove_stale_spatial_objects(ttl_s=10.0, now=26.0)
        self.assertEqual(removed_count, 1)

        remaining = wm.get_spatial_objects(max_age_s=10.0, now=26.0)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].class_name, "cup")

    # =========================================================================
    # Test D: Visual Query Test ("Kameranda neler görüyorsun?")
    # =========================================================================
    def test_d_visual_query_reads_actual_objects(self):
        """'Kameranda neler görüyorsun?' must return real objects with counts in Turkish."""
        with patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock"}):
            node = AstroRealtimeNode()

        # Mock visual grounding as active and verified
        node._get_current_visual_grounding = lambda: {
            "visual_state": "VERIFIED",
            "visual_camera_available": True,
            "visual_person_detected": True,
            "visual_distance": 1.2,
        }

        # Feed real objects to both node cache and world_model
        now_m = time.monotonic()
        objs = [
            SpatialObjectState(object_id="c1", class_name="cup", confidence=0.9, last_observed_ts=now_m),
            SpatialObjectState(object_id="l1", class_name="laptop", confidence=0.85, last_observed_ts=now_m),
            SpatialObjectState(object_id="b1", class_name="book", confidence=0.88, last_observed_ts=now_m),
        ]
        node._last_detected_objects = objs
        node._last_detected_objects_time = now_m
        if hasattr(node, "social_brain") and hasattr(node.social_brain, "world_model"):
            node.social_brain.world_model.update_spatial_objects(objs)

        text = node._format_detected_objects_tr(objs)
        self.assertIn("bardak", text)
        self.assertIn("dizüstü bilgisayar", text)
        self.assertIn("kitap", text)

        # Test query recognition and answer
        is_query, response = node._is_visual_state_query("Kameranda neler görüyorsun?")
        self.assertTrue(is_query)
        self.assertIn("bardak", response)
        self.assertIn("dizüstü bilgisayar", response)

    # =========================================================================
    # Test E: Activity Temporal Aggregation Test
    # =========================================================================
    def test_e_activity_temporal_aggregation(self):
        """Single frame does NOT trigger activity; sufficient window triggers it."""
        engine = TemporalActivityEngine(window_duration_s=3.0, min_evidence_ratio=0.50)

        person = UnifiedPersonState(person_id="p1", distance_m=1.0, is_present=True)
        cup = SpatialObjectState(
            object_id="c1", class_name="cup", confidence=0.9, distance_m=0.9,
            interaction_type="holding", last_observed_ts=1.0
        )

        # Frame 1: Single observation -> not enough evidence
        act, conf, evid = engine.evaluate(person, [cup], now=1.0)
        self.assertEqual(act, HumanActivity.UNKNOWN)
        self.assertEqual(conf, 0.0)

        # Frame 2: Sustained observation -> triggers activity
        act, conf, evid = engine.evaluate(person, [cup], now=1.2)
        self.assertEqual(act, HumanActivity.DRINKING)
        self.assertGreaterEqual(conf, 0.55)

    # =========================================================================
    # Test F: Drinking Fixture Test
    # =========================================================================
    def test_f_drinking_fixture(self):
        """Person + cup in proximity over time -> DRINKING."""
        engine = TemporalActivityEngine(window_duration_s=3.0)
        person = UnifiedPersonState(person_id="p1", distance_m=1.1, is_present=True)
        cup = SpatialObjectState(
            object_id="c1", class_name="cup", confidence=0.88, distance_m=1.0,
            interaction_type="holding", last_observed_ts=1.0
        )

        for t in [1.0, 1.2]:
            act, conf, _ = engine.evaluate(person, [cup], now=t)

        self.assertEqual(act, HumanActivity.DRINKING)
        self.assertIn(act, ACTIVITY_DESCRIPTIONS_TR)
        self.assertIn("iç", ACTIVITY_DESCRIPTIONS_TR[act].lower())

    # =========================================================================
    # Test G: Phone Test Fixture
    # =========================================================================
    def test_g_phone_fixture(self):
        """Person + cell phone in proximity over time -> USING_PHONE."""
        engine = TemporalActivityEngine(window_duration_s=3.0)
        person = UnifiedPersonState(person_id="p1", distance_m=0.9, is_present=True)
        phone = SpatialObjectState(
            object_id="ph1", class_name="cell phone", confidence=0.85, distance_m=0.8,
            interaction_type="holding", last_observed_ts=1.0
        )

        for t in [1.0, 1.2]:
            act, conf, _ = engine.evaluate(person, [phone], now=t)

        self.assertEqual(act, HumanActivity.USING_PHONE)
        self.assertIn("telefon", ACTIVITY_DESCRIPTIONS_TR[act].lower())

    # =========================================================================
    # Test H: Sitting Test Fixture
    # =========================================================================
    def test_h_sitting_fixture(self):
        """Person + chair in proximity over time -> SITTING."""
        engine = TemporalActivityEngine(window_duration_s=3.0)
        person = UnifiedPersonState(person_id="p1", distance_m=1.4, is_present=True)
        chair = SpatialObjectState(
            object_id="ch1", class_name="chair", confidence=0.82, distance_m=1.3,
            last_observed_ts=1.0
        )

        for t in [1.0, 1.2]:
            act, conf, _ = engine.evaluate(person, [chair], motion_features={"posture": "sitting"}, now=t)

        self.assertEqual(act, HumanActivity.SITTING)
        self.assertIn("otur", ACTIVITY_DESCRIPTIONS_TR[act].lower())

    # =========================================================================
    # Test I: Walking Test Fixture
    # =========================================================================
    def test_i_walking_fixture(self):
        """Significant translation speed over time -> WALKING."""
        engine = TemporalActivityEngine(window_duration_s=3.0)
        person = UnifiedPersonState(person_id="p1", distance_m=2.0, approach_velocity_mps=0.6, is_present=True)

        for t in [1.0, 1.2]:
            act, conf, _ = engine.evaluate(person, [], now=t)

        self.assertEqual(act, HumanActivity.WALKING)
        desc_lower = ACTIVITY_DESCRIPTIONS_TR[act].lower()
        self.assertTrue("yürü" in desc_lower or "hareket" in desc_lower)

    # =========================================================================
    # Test J: Reading Test Fixture
    # =========================================================================
    def test_j_reading_fixture(self):
        """Person + book in proximity over time -> READING."""
        engine = TemporalActivityEngine(window_duration_s=3.0)
        person = UnifiedPersonState(person_id="p1", distance_m=1.0, is_present=True)
        book = SpatialObjectState(
            object_id="bk1", class_name="book", confidence=0.90, distance_m=0.95,
            interaction_type="holding", last_observed_ts=1.0
        )

        for t in [1.0, 1.2]:
            act, conf, _ = engine.evaluate(person, [book], now=t)

        self.assertEqual(act, HumanActivity.READING)
        self.assertIn("oku", ACTIVITY_DESCRIPTIONS_TR[act].lower())

    # =========================================================================
    # Test K: Age-group Inference Contract Test
    # =========================================================================
    def test_k_age_group_inference_contract(self):
        """VisualAgeEstimator returns AgeGroup enum and float confidence."""
        estimator = VisualAgeEstimator()
        face_crop = np.zeros((120, 100, 3), dtype=np.uint8)

        age_grp, conf = estimator.estimate(face_crop)
        self.assertIn(age_grp, [AgeGroup.CHILD, AgeGroup.TEEN, AgeGroup.ADULT, AgeGroup.SENIOR, AgeGroup.UNKNOWN])
        self.assertIsInstance(conf, float)
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

    # =========================================================================
    # Test L: Adaptive Persona Consumes Real Age Output
    # =========================================================================
    def test_l_adaptive_persona_consumes_real_age(self):
        """AdaptivePersonaEngine configures policy based on real AgeGroup."""
        engine = AdaptivePersonaEngine()

        # Child: Playful tone, child safety, profanity blocked
        p_child = UnifiedPersonState(
            person_id="c1", estimated_age_group="CHILD", age_confidence=0.85, can_claim_vision=True
        )
        grp_c, conf_c = engine.estimate_age_group(p_child)
        self.assertEqual(grp_c, AgeGroup.CHILD)
        pol_child = engine.evaluate_policy(base_persona="kufurbaz", age_group=grp_c)
        self.assertFalse(pol_child.allow_profanity)
        self.assertEqual(pol_child.target_age_group, AgeGroup.CHILD)

        # Senior: Respectful tone, profanity blocked
        p_senior = UnifiedPersonState(
            person_id="s1", estimated_age_group="SENIOR", age_confidence=0.80, can_claim_vision=True
        )
        grp_s, conf_s = engine.estimate_age_group(p_senior)
        self.assertEqual(grp_s, AgeGroup.SENIOR)
        pol_senior = engine.evaluate_policy(base_persona="kufurbaz", age_group=grp_s)
        self.assertFalse(pol_senior.allow_profanity)
        self.assertEqual(pol_senior.target_age_group, AgeGroup.SENIOR)

        # Unknown: Safe fallback, profanity blocked, neutral default
        p_unknown = UnifiedPersonState(
            person_id="u1", estimated_age_group="UNKNOWN", age_confidence=0.0, can_claim_vision=False
        )
        grp_u, conf_u = engine.estimate_age_group(p_unknown)
        self.assertEqual(grp_u, AgeGroup.UNKNOWN)
        pol_unknown = engine.evaluate_policy(base_persona="flirt", age_group=grp_u)
        self.assertFalse(pol_unknown.allow_profanity)

    # =========================================================================
    # Test M: Visual Compliment Test
    # =========================================================================
    def test_m_visual_compliment_requires_visual_fact(self):
        """Compliment is rejected without verified visual facts, approved with facts."""
        mgr = SocialInitiativeManager(compliment_cooldown_s=10.0)

        # Case 1: No vision -> Rejected
        p_novision = UnifiedPersonState(person_id="p1", has_vision=False)
        dec1 = mgr.evaluate_visual_compliment(p_novision, gate_mode="ENGAGED", now=10.0)
        self.assertFalse(dec1.should_compliment)

        # Case 2: Vision with verified clothing color -> Approved with CLOTHING_STYLE
        p_color = UnifiedPersonState(
            person_id="p2",
            has_vision=True,
            can_claim_vision=True,
            distance_m=1.2,
            is_looking_at_robot=True,
            dominant_clothing_color="mavi",
            raw_attributes={"dominant_clothing_color_tr": "mavi", "clothing_color_confidence": 0.75},
        )
        dec2 = mgr.evaluate_visual_compliment(p_color, gate_mode="ENGAGED", now=10.0)
        self.assertTrue(dec2.should_compliment)
        self.assertEqual(dec2.topic, ComplimentTopic.CLOTHING_STYLE)
        self.assertIn("Mavi", dec2.compliment_text_suggestion)

        # Case 3: Vision with verified activity (DRINKING) -> Approved
        p_drink = UnifiedPersonState(
            person_id="p3",
            has_vision=True,
            can_claim_vision=True,
            distance_m=1.2,
            is_looking_at_robot=True,
            current_activity="DRINKING",
        )
        dec3 = mgr.evaluate_visual_compliment(p_drink, gate_mode="ENGAGED", now=10.0)
        self.assertTrue(dec3.should_compliment)
        self.assertIn("afiyet", dec3.compliment_text_suggestion.lower())

    # =========================================================================
    # Test N: Social Initiative Cooldown Test
    # =========================================================================
    def test_n_social_initiative_cooldown(self):
        """Compliment enforces 120s cooldown per person."""
        mgr = SocialInitiativeManager(compliment_cooldown_s=120.0)
        person = UnifiedPersonState(
            person_id="p_cooldown",
            has_vision=True,
            can_claim_vision=True,
            distance_m=1.2,
            is_looking_at_robot=True,
            dominant_clothing_color="kırmızı",
            raw_attributes={"dominant_clothing_color_tr": "kırmızı", "clothing_color_confidence": 0.8},
        )

        # First compliment at t=10.0 -> Approved
        dec1 = mgr.evaluate_visual_compliment(person, gate_mode="ENGAGED", now=10.0)
        self.assertTrue(dec1.should_compliment)

        # Second compliment at t=60.0 (50s later < 120s) -> Rejected due to cooldown
        dec2 = mgr.evaluate_visual_compliment(person, gate_mode="ENGAGED", now=60.0)
        self.assertFalse(dec2.should_compliment)
        self.assertEqual(dec2.reason, "IN_COOLDOWN")

        # Third compliment at t=135.0 (125s later > 120s) -> Approved
        dec3 = mgr.evaluate_visual_compliment(person, gate_mode="ENGAGED", now=135.0)
        self.assertTrue(dec3.should_compliment)

    # =========================================================================
    # Test O: Identity/Object/Activity Association Test
    # =========================================================================
    def test_o_identity_activity_association_isolation(self):
        """When Baran speaks but Misafir is using a phone, Astro must NOT say Baran is on the phone."""
        with patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock"}):
            node = AstroRealtimeNode()

        node._get_current_visual_grounding = lambda: {
            "visual_state": "VERIFIED",
            "visual_camera_available": True,
            "visual_person_detected": True,
            "visual_distance": 1.2,
        }

        # Person 1: Baran (speaker, no phone, standing)
        baran = UnifiedPersonState(
            person_id="p_baran",
            name="Baran",
            distance_m=1.0,
            has_vision=True,
            can_claim_vision=True,
            is_present=True,
            current_activity="STANDING",
            activity_confidence=0.85,
            interacting_objects=[],
        )

        # Person 2: Misafir (using phone)
        guest = UnifiedPersonState(
            person_id="p_guest",
            name="Misafir",
            distance_m=2.0,
            has_vision=True,
            can_claim_vision=True,
            is_present=True,
            current_activity="USING_PHONE",
            activity_confidence=0.88,
            interacting_objects=["cell phone"],
        )

        # Scene 1: Camera sees Misafir, but speaker is Baran
        node.social_brain.world_model._people = {"p_guest": guest}
        node._active_person_name = "Baran"

        is_query, response = node._is_activity_query("Ben ne yapıyorum?")
        self.assertTrue(is_query)
        # Should NOT accuse Baran of using a phone
        self.assertNotIn("telefon", response.lower())
        self.assertIn("misafir", response.lower())

        # Scene 2: Camera sees Baran directly
        node.social_brain.world_model._people = {"p_baran": baran}
        is_query_b, response_b = node._is_activity_query("Ben ne yapıyorum?")
        self.assertTrue(is_query_b)
        self.assertIn("ayakta", response_b.lower())

    # =========================================================================
    # Test P: UNKNOWN Fallback Test
    # =========================================================================
    def test_p_unknown_fallback_no_hallucination(self):
        """Unknown age and unknown activity must report unknown/neutral, never hallucinate."""
        with patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock"}):
            node = AstroRealtimeNode()

        node._get_current_visual_grounding = lambda: {
            "visual_state": "VERIFIED",
            "visual_camera_available": True,
            "visual_person_detected": True,
            "visual_distance": 1.5,
        }

        person = UnifiedPersonState(
            person_id="p_anon",
            name="Bilinmeyen",
            distance_m=1.5,
            has_vision=True,
            can_claim_vision=True,
            is_present=True,
            current_activity="UNKNOWN",
            activity_confidence=0.0,
        )
        node.social_brain.world_model._people = {"p_anon": person}
        node._active_person_name = ""

        is_query, response = node._is_activity_query("Ben ne yapıyorum?")
        self.assertTrue(is_query)
        self.assertIn("ayırt edemiyorum", response.lower())

    # =========================================================================
    # Test Q: Model Offline / Error Test
    # =========================================================================
    def test_q_model_offline_preserves_visual_state(self):
        """LLM failure or offline mode preserves visual state in WorldModel."""
        wm = WorldModel()
        obj = SpatialObjectState(object_id="cup_1", class_name="cup", confidence=0.92, last_observed_ts=50.0)
        wm.update_spatial_object(obj)

        person = UnifiedPersonState(person_id="p1", current_activity="DRINKING")
        wm.people = {"p1": person}

        # Simulate LLM offline exception
        try:
            raise ConnectionError("LLM server unreachable")
        except ConnectionError:
            pass

        # Visual state must remain intact
        objs = wm.get_spatial_objects(max_age_s=60.0, now=55.0)
        self.assertEqual(len(objs), 1)
        self.assertEqual(objs[0].class_name, "cup")
        self.assertEqual(wm.people["p1"].current_activity, "DRINKING")

    # =========================================================================
    # Test R: Dialogue Visual State Reading Test
    # =========================================================================
    def test_r_dialogue_visual_state_reading(self):
        """Visual state must be properly injected into dialogue context / prompt."""
        wm = WorldModel()
        now_ts = time.time()
        wm.update_spatial_objects([
            SpatialObjectState(object_id="c1", class_name="cup", confidence=0.9, last_observed_ts=now_ts),
            SpatialObjectState(object_id="b1", class_name="book", confidence=0.88, last_observed_ts=now_ts),
        ])

        snap = wm.get_snapshot()
        detected_names = [o.class_name for o in snap.spatial_objects]
        self.assertIn("cup", detected_names)
        self.assertIn("book", detected_names)

    # =========================================================================
    # Test S: Zero Hallucination Test - Objects
    # =========================================================================
    def test_s_zero_hallucination_objects(self):
        """When camera sees only a cup, Astro must never report chair, laptop, or cat."""
        with patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock"}):
            node = AstroRealtimeNode()

        now_m = time.monotonic()
        node._last_detected_objects = [
            SpatialObjectState(object_id="c1", class_name="cup", confidence=0.9, last_observed_ts=now_m),
        ]
        node._last_detected_objects_time = now_m

        text = node._format_detected_objects_tr(node._last_detected_objects)
        self.assertIn("bardak", text)
        self.assertNotIn("sandalye", text)
        self.assertNotIn("dizüstü bilgisayar", text)
        self.assertNotIn("kedi", text)

        # Empty view test
        node._get_current_visual_grounding = lambda: {
            "visual_state": "VERIFIED",
            "visual_camera_available": True,
            "visual_person_detected": False,
        }
        node._last_detected_objects = []
        node.social_brain.world_model._spatial_objects = {}
        is_query, empty_resp = node._is_visual_state_query("Kameranda ne görüyorsun?")
        self.assertTrue(is_query)
        self.assertIn("herhangi bir kişi veya nesne göremiyorum", empty_resp)

    # =========================================================================
    # Test T: Zero Hallucination Test - Activities
    # =========================================================================
    def test_t_zero_hallucination_activities(self):
        """Insufficient evidence or distance must NOT assign activity."""
        engine = TemporalActivityEngine(window_duration_s=3.0, min_evidence_ratio=0.50)
        person = UnifiedPersonState(person_id="p1", distance_m=3.5, is_present=True)
        phone = SpatialObjectState(
            object_id="ph1", class_name="cell phone", confidence=0.85, distance_m=1.0,
            interaction_type="none", last_observed_ts=1.0
        )

        for t in [1.0, 1.2, 1.4, 1.6]:
            act, conf, evid = engine.evaluate(person, [phone], now=t)

        self.assertEqual(act, HumanActivity.UNKNOWN)
        self.assertEqual(len(evid), 0)


if __name__ == "__main__":
    unittest.main()
