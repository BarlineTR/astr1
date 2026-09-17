"""Test Suite for Multimodal Identity Fusion and Object Grounding.

Verifies:
1. When voice biometrics verify user as 'Baran', _cognitive_cycle_tick assigns 'Baran' to the visual interlocutor.
2. WorldModel.update_people purges placeholder 'misafir' entities when an identified person is updated.
3. StandaloneGazeRosNode initializes pub_detected_objects and pub_faces.
4. When object_engine detects objects, /vision/detected_objects publishes valid JSON array.
5. astro_realtime_node._is_visual_state_query correctly grounds detected objects in response.
"""

import json
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.brain.world_model import WorldModel
from astro_base.standalone_gaze_ros_node import StandaloneGazeRosNode
from astro_vision.object_detector import DetectedObject


class TestMultimodalIdentityAndObjectGrounding(unittest.TestCase):
    """Verifies identity fusion and object grounding across the social gaze stack."""

    def test_world_model_purges_misafir_on_known_person_arrival(self):
        """When an identified known user arrives, placeholder 'misafir' and 'guest' entities must be purged."""
        wm = WorldModel()
        now = 100.0

        # Step 1: Initial visual observation creates unverified guest
        guest = UnifiedPersonState(
            person_id="misafir",
            name="Misafir",
            distance_m=0.8,
            azimuth_deg=0.0,
            is_known=False,
            is_present=True,
        )
        wm.update_people([guest], now=now)
        self.assertIn("misafir", wm._people)
        self.assertEqual(len(wm._people), 1)

        # Step 2: Speaker speaks and is verified as Baran
        now += 0.5
        baran = UnifiedPersonState(
            person_id="baran",
            name="Baran",
            formal_title="Baran",
            distance_m=0.8,
            azimuth_deg=0.0,
            is_known=True,
            is_present=True,
        )
        wm.update_people([baran], now=now)

        # 'misafir' must be purged, NOT marked as occluded!
        self.assertNotIn("misafir", wm._people)
        self.assertIn("baran", wm._people)
        self.assertEqual(len(wm._people), 1)
        self.assertTrue(wm._people["baran"].is_present)

    def test_cognitive_cycle_tick_fuses_voice_identity_into_visual_track(self):
        """When voice is verified, _cognitive_cycle_tick must label the person in front as the verified user."""
        with patch.dict("os.environ", {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-test1234"}):
            node = AstroRealtimeNode(connect_realtime=False)
            node.cognitive_loop = MagicMock()

            # Speaker recognized by voice
            node._recognized_speaker = {
                "name": "Baran",
                "confidence": 0.85,
                "is_known": True,
            }
            # Unidentified visual face from camera
            node._recognized_person = {
                "name": "Misafir",
                "confidence": 0.0,
                "is_known": False,
            }
            node._user_distance = 0.85
            node._speaker_angle = 5.0
            node._user_speaking_active = True

            node._cognitive_cycle_tick()

            # Check argument passed to cognitive_loop.step
            self.assertTrue(node.cognitive_loop.step.called)
            call_args = node.cognitive_loop.step.call_args[0][0]
            people = call_args.get("people", [])
            self.assertEqual(len(people), 1)
            p = people[0]
            self.assertEqual(p.name, "Baran")
            self.assertEqual(p.person_id, "baran")
            self.assertTrue(p.is_known)
            self.assertTrue(p.has_audio)
            self.assertTrue(p.is_speaking)

    def test_standalone_gaze_object_detection_publisher(self):
        """StandaloneGazeRosNode should initialize pub_detected_objects and pub_faces."""
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        self.assertIsNotNone(node.pub_detected_objects)
        self.assertIsNotNone(node.pub_faces)

        # Mock object engine
        mock_oe = MagicMock()
        det_cup = DetectedObject(
            object_id="cup_1",
            class_name="cup",
            confidence=0.88,
            bbox=(10, 20, 50, 60),
            center=(30.0, 40.0),
            distance_m=0.9,
        )
        mock_oe.process_frame.return_value = [det_cup]
        node.object_engine = mock_oe
        node._last_object_det_time = 0.0

        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        node._maybe_detect_objects(dummy_frame)

        # Wait for thread
        time.sleep(0.1)

        self.assertIsNotNone(node.pub_detected_objects.last_msg)
        raw_json = node.pub_detected_objects.last_msg.data
        data = json.loads(raw_json)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["class_name"], "cup")
        self.assertEqual(data[0]["class_name_tr"], "bardak")

    def test_visual_state_query_with_detected_objects(self):
        """_is_visual_state_query includes detected objects in natural Turkish response."""
        with patch.dict("os.environ", {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-test1234", "ASTRO_MOCK_CAMERA_AVAILABLE": "1"}):
            node = AstroRealtimeNode(connect_realtime=False)
            now = time.monotonic()
            node._oak_connection_state = "CONNECTED"
            node._oak_last_frame_time = now
            node._last_vision_faces_time = now
            node._user_distance = 1.2
            node._last_vision_distance_time = now
            node._recognized_person = {"name": "Baran", "is_known": True}

            det_laptop = DetectedObject(
                object_id="laptop_1",
                class_name="laptop",
                confidence=0.92,
                bbox=(100, 100, 300, 300),
                center=(200.0, 200.0),
                distance_m=1.0,
            )
            node._last_detected_objects = [det_laptop]
            node._last_detected_objects_time = now

            is_query, reply = node._is_visual_state_query("kameranda neler görüyorsun?")
            self.assertTrue(is_query)
            self.assertIn("dizüstü bilgisayar", reply.lower())


if __name__ == "__main__":
    unittest.main()
