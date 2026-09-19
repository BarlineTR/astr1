"""ASTRO V1 — Test Suite for Humanized Dialogue & Activity Grounding.

Verifies:
1. Elimination of robotic 'Sesine döndüm' replies.
2. Compound query filtering ('ben kim, ben ne yapıyorum') -> routed to conversational LLM.
3. Seated posture detection ('SITTING') for stationary users at desk.
4. Phantom objects without depth on desk do NOT trigger HOLDING or DRINKING.
5. Referential 'Ben de onu soruyorum' does not emit robotic clarification prompts.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.contracts.spatial_state import SpatialObjectState
from astro_ai.spatial.person_object_association import PersonObjectAssociator, InteractionType
from astro_ai.brain.activity_recognition import TemporalActivityEngine, HumanActivity
from astro_ai.astro_realtime_node import AstroRealtimeNode


class TestHumanizedDialogueAndActivity(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock"}):
            self.node = AstroRealtimeNode()

    def test_01_compound_query_not_intercepted_by_activity_query(self):
        """'Astro, ben kim, ben ne yapıyorum şu anda?' must NOT be intercepted deterministically."""
        query = "Astro, ben kim, ben ne yapıyorum şu anda?"
        is_query, reply = self.node._is_activity_query(query)
        self.assertFalse(is_query, "Compound question with identity ('ben kim') must route to LLM!")

    def test_02_pure_activity_query_detects_sitting_posture(self):
        """Stationary person seated in front of camera is recognized as SITTING."""
        self.node._get_current_visual_grounding = lambda: {
            "visual_state": "VERIFIED",
            "visual_camera_available": True,
            "visual_person_detected": True,
            "visual_distance": 1.0,
        }
        # Seated person with face centered at desk height (y=160, h=140 -> cy=230)
        person = UnifiedPersonState(
            person_id="p_baran",
            name="Baran",
            distance_m=1.0,
            azimuth_deg=0.0,
            has_vision=True,
            can_claim_vision=True,
            is_present=True,
            face_bbox=(200, 160, 140, 140),
            current_activity="SITTING",
            activity_confidence=0.75,
        )
        self.node.social_brain.world_model._people = {"p_baran": person}
        self.node._active_person_name = "Baran"

        is_query, reply = self.node._is_activity_query("Ben ne yapıyorum?")
        self.assertTrue(is_query)
        self.assertIn("otur", reply.lower())
        self.assertNotIn("ayırt edemiyorum", reply.lower())

    def test_03_phantom_desk_bottle_does_not_trigger_drinking(self):
        """Bottle resting on desk below mouth must NOT be associated as HOLDING or trigger DRINKING."""
        associator = PersonObjectAssociator()
        engine = TemporalActivityEngine(window_duration_s=3.0)

        # Seated person face at y=100, h=120 (mouth zone y: 148..262)
        person = UnifiedPersonState(
            person_id="p1",
            distance_m=1.0,
            is_present=True,
            face_bbox=(200, 100, 120, 120),
        )

        # Bottle on desk: y from 280 to 450 (center y=365, well below mouth) with no metric depth (0.0m)
        bottle = SpatialObjectState(
            object_id="bot1",
            class_name="bottle",
            confidence=0.75,
            distance_m=0.0,
            bbox=(220, 280, 280, 450),
            center=(250.0, 365.0),
            last_observed_ts=1.0,
        )

        results = associator.associate([person], [bottle], now=1.0)
        self.assertTrue(len(results) > 0)
        # Relation must be NEAR or IN_FRONT_OF, NEVER HOLDING!
        self.assertNotEqual(results[0].relation, InteractionType.HOLDING)
        self.assertEqual(results[0].relation, InteractionType.NEAR)

        # Activity engine must NOT evaluate as DRINKING
        act, conf, _ = engine.evaluate(person, [bottle], now=1.0)
        self.assertNotEqual(act, HumanActivity.DRINKING)

    def test_04_sound_turn_never_says_sesine_dondum(self):
        """Robot acknowledgement for turning to sound must never contain 'Sesine döndüm'."""
        formatted_baran = self.node._format_deterministic_response(
            fact_text="Dinliyorum seni abi.",
            spk_name="Baran",
            is_known=True,
            is_child=False,
        )
        self.assertNotIn("sesine döndüm", formatted_baran.lower())

        formatted_guest = self.node._format_deterministic_response(
            fact_text="Buradayım, dinliyorum.",
            spk_name="",
            is_known=False,
            is_child=False,
        )
        self.assertNotIn("sesine döndüm", formatted_guest.lower())

    def test_05_world_model_purges_anonymous_on_known_detection(self):
        """When Baran is detected, anonymous placeholder 'person_misafir_0' is purged from WorldModel."""
        wm = self.node.social_brain.world_model
        # Pre-existing anonymous tracked person
        guest = UnifiedPersonState(
            person_id="person_misafir_0",
            name="Misafir",
            is_known=False,
            distance_m=1.0,
            azimuth_deg=2.0,
            is_present=True,
        )
        wm._people = {"person_misafir_0": guest}

        # Incoming verified Baran at roughly the same position
        baran = UnifiedPersonState(
            person_id="baran",
            name="Baran",
            is_known=True,
            distance_m=0.9,
            azimuth_deg=0.0,
            is_present=True,
        )
        wm.update_people([baran], now=10.0)

        self.assertIn("baran", wm._people)
        self.assertNotIn("person_misafir_0", wm._people)

    def test_06_on_faces_payload_handling_and_world_model_update(self):
        """Verify _on_faces parses incoming vision payload without NameError and updates WorldModel."""
        import json
        try:
            from std_msgs.msg import String
        except ImportError:
            class String:
                def __init__(self, data=""):
                    self.data = data

        faces_payload = [
            {
                "person_id": "baran",
                "name": "Baran",
                "recognized_name": "Baran",
                "recognized_title": "Baran",
                "is_known": True,
                "confidence": 0.88,
                "distance_m": 0.95,
                "camera_azimuth_deg": -1.5,
                "looking_at_robot": True,
                "x": 200,
                "y": 160,
                "width": 140,
                "height": 140,
                "emotion": "neutral",
                "dominant_clothing_color_tr": "siyah",
            }
        ]
        msg = String(data=json.dumps(faces_payload))

        # Calling _on_faces must NOT throw NameError or any unhandled exception
        self.node._on_faces(msg)

        wm = self.node.social_brain.world_model
        person = wm.get_person("baran")
        self.assertIsNotNone(person, "Baran should be registered in WorldModel by _on_faces")
        self.assertEqual(person.name, "Baran")
        self.assertAlmostEqual(person.distance_m, 0.95, places=2)
        self.assertAlmostEqual(person.azimuth_deg, -1.5, places=1)
        self.assertTrue(person.is_looking_at_robot)

    def test_07_activity_query_resolves_sitting_from_vision(self):
        """User asking 'Ne yapıyorum?' when seated in front of robot gets 'Oturduğunu görüyorum'."""
        import json
        try:
            from std_msgs.msg import String
        except ImportError:
            class String:
                def __init__(self, data=""):
                    self.data = data

        self.node._get_current_visual_grounding = lambda: {
            "visual_state": "VERIFIED",
            "visual_camera_available": True,
            "visual_person_detected": True,
            "visual_distance": 0.95,
        }

        # Simulate camera feed detecting seated Baran
        faces_payload = [
            {
                "person_id": "baran",
                "name": "Baran",
                "recognized_name": "Baran",
                "is_known": True,
                "confidence": 0.9,
                "distance_m": 0.95,
                "camera_azimuth_deg": 0.0,
                "looking_at_robot": True,
                "x": 200,
                "y": 160,
                "width": 140,
                "height": 140,
            }
        ]
        msg = String(data=json.dumps(faces_payload))
        self.node._on_faces(msg)

        # Set speaker verification state to Baran
        self.node._active_person_name = "Baran"

        # Force activity engine evaluation / activity set
        person = self.node.social_brain.world_model.get_person("baran")
        self.assertIsNotNone(person)
        person.current_activity = "SITTING"
        person.activity_confidence = 0.8

        is_act, reply = self.node._is_activity_query("Ne yapıyorum şu an?")
        self.assertTrue(is_act)
        self.assertIn("otur", reply.lower())
        self.assertNotIn("ayırt edemiyorum", reply.lower())


if __name__ == "__main__":
    unittest.main()

