"""Tests for Visual Consciousness & Multimodal Perception Grounding."""

import json
import os
import time
import unittest
from unittest.mock import MagicMock

from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.consciousness_node import ConsciousnessNode
from astro_ai.contracts.consciousness_types import CognitiveEventType


class TestVisualConsciousnessGrounding(unittest.TestCase):
    def setUp(self):
        os.environ["FACE_MATCH_THRESHOLD"] = "0.38"

    def test_01_consciousness_node_receives_faces_and_emits_perception_events(self):
        """ConsciousnessNode detects person appearance/disappearance from /vision/faces."""
        node = ConsciousnessNode()

        # Initial state: no person
        self.assertFalse(node._sensor_cache["person_detected"])

        # Face appears
        face_payload = [{
            "name": "Ali Yerlikaya",
            "recognized_name": "Ali Yerlikaya",
            "recognized_title": "İçişleri Bakanı",
            "is_known": True,
            "confidence": 0.92,
            "looking_at_robot": True,
            "distance_m": 1.2,
        }]
        mock_msg = MagicMock()
        mock_msg.data = json.dumps(face_payload)
        node._on_faces_msg(mock_msg)

        self.assertTrue(node._sensor_cache["person_detected"])
        events = node.event_bus.get_unprocessed_events()
        event_types = [e.event_type for e in events]
        self.assertIn(CognitiveEventType.PERSON_APPEARED, event_types)

        # Step one cycle - processes events and updates affective/introspection state
        node._on_cycle()
        self.assertIsNotNone(node.self_state)

        # Face disappears
        empty_msg = MagicMock()
        empty_msg.data = "[]"
        node._on_faces_msg(empty_msg)

        self.assertFalse(node._sensor_cache["person_detected"])
        events_after = node.event_bus.get_unprocessed_events()
        event_types_after = [e.event_type for e in events_after]
        self.assertIn(CognitiveEventType.PERSON_DISAPPEARED, event_types_after)

    def test_02_consciousness_node_playback_active_subscription(self):
        """ConsciousnessNode detects robot speaking via /audio/playback_active and /robot/is_speaking."""
        node = ConsciousnessNode()
        self.assertFalse(node.self_state.is_speaking)

        # Simulate audio_stream_node publishing playback active
        mock_msg = MagicMock()
        mock_msg.data = True
        node._on_tts_speaking_msg(mock_msg)

        self.assertTrue(node.self_state.is_speaking)
        events = node.event_bus.get_unprocessed_events()
        self.assertIn(CognitiveEventType.ROBOT_STARTED_SPEAKING, [e.event_type for e in events])

        # Playback finishes
        mock_msg.data = False
        node._on_tts_speaking_msg(mock_msg)
        self.assertFalse(node.self_state.is_speaking)
        events_end = node.event_bus.get_unprocessed_events()
        self.assertIn(CognitiveEventType.ROBOT_FINISHED_SPEAKING, [e.event_type for e in events_end])

    def test_03_camera_freshness_anchors_to_live_frames(self):
        """Camera stream freshness must track live frames rather than stale face detections."""
        node = AstroRealtimeNode(connect_realtime=False)
        now = time.monotonic()

        # Simulate an old face detection from 60 seconds ago
        node._last_vision_faces_time = now - 60.0
        # Simulate active live camera frame from 50 milliseconds ago
        node._oak_last_frame_time = now - 0.05
        node._oak_connection_state = "CONNECTED"

        grounding = node._get_current_visual_grounding()
        self.assertTrue(grounding["visual_camera_available"])
        self.assertEqual(grounding["visual_state"], "FRESH")
        self.assertLess(grounding["visual_age_ms"], 200)

        # Now simulate camera disconnect (>4.0s elapsed)
        node._oak_last_frame_time = now - 5.0
        grounding_stale = node._get_current_visual_grounding()
        self.assertEqual(grounding_stale["visual_state"], "STALE")

    def test_04_face_recognition_threshold_alignment(self):
        """AstroRealtimeNode accepts verified face with confidence 0.40 under 0.38 threshold."""
        node = AstroRealtimeNode(connect_realtime=False)

        payload = {
            "name": "Mehmet Simsek",
            "is_known": True,
            "confidence": 0.41,
            "formal_title": "Sayın Bakanım",
            "title": "Hazine ve Maliye Bakanı",
        }
        msg = MagicMock()
        msg.data = json.dumps(payload)
        node._on_recognized_person(msg)

        self.assertEqual(node._active_person_name, "Mehmet Simsek")
        self.assertIsNotNone(node._recognized_person)
        self.assertEqual(node._recognized_person.get("name"), "Mehmet Simsek")

    def test_05_system_prompt_contains_fresh_visual_grounding(self):
        """System prompt reflects live camera freshness and prevents rote ungrounded answers."""
        node = AstroRealtimeNode(connect_realtime=False)
        now = time.monotonic()
        node._oak_last_frame_time = now - 0.05
        node._oak_connection_state = "CONNECTED"

        prompt = node._build_current_system_prompt()
        self.assertIn("GÖRSEL VE MEKÂNSAL FARKINDALIK BİLGİSİ", prompt)
        self.assertIn("Kamera Durumu: AKTİF", prompt)
        self.assertIn("Görüntü Tazeliği: FRESH", prompt)


if __name__ == "__main__":
    unittest.main()
