"""ASTRO V1 — Real-Time LiDAR Spatial Distance and Bearing Grounding Tests.

Verifies that:
1. Azimuth angle conversion to Turkish spatial sectors is accurate.
2. get_spatial_user_perception accurately extracts the closest/aligned speaker track.
3. System prompt and per-turn instructions inject live LiDAR distance and strictly prevent refusal.
4. get_spatial_surroundings function tool returns structured 360° radar status.
5. SelfModel epistemic description includes LiDAR distance sensing.
"""

import math
import os
import unittest
from unittest.mock import MagicMock, patch

from astro_ai.brain.self_model import SelfModel
from astro_ai.contracts.spatial_state import SpatialPersonTrack
from astro_ai.spatial.lidar_tracker import LidarTracker


class TestRealtimeSpatialDistanceGrounding(unittest.TestCase):

    def setUp(self):
        os.environ["ASTRO_TEST_MODE"] = "1"

    def test_01_azimuth_to_sector_conversions(self):
        """Verify angle conversion to natural Turkish sectors matches ASTRO coordinate conventions."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        # Forward
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(0.0), "tam karşımda / önümde")
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(15.0), "tam karşımda / önümde")
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(-15.0), "tam karşımda / önümde")

        # Left sectors (> 0)
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(45.0), "sol ön çaprazımda")
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(90.0), "tam solumda")
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(130.0), "sol arkamda")

        # Right sectors (< 0)
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(-45.0), "sağ ön çaprazımda")
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(-81.8), "tam sağımda")
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(-90.0), "tam sağımda")
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(-130.0), "sağ arkamda")

        # Directly Behind
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(175.0), "tam arkamda")
        self.assertEqual(AstroRealtimeNode._azimuth_to_sector(-175.0), "tam arkamda")

    def test_02_get_spatial_user_perception_lidar_track(self):
        """Verify that an active LiDAR track at 0.85m @ -81.8° is parsed into user perception."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        # Instantiate mock node
        node = MagicMock(spec=AstroRealtimeNode)
        node.lidar_tracker = LidarTracker()
        node._speaker_angle = -80.0
        node._azimuth_to_sector = AstroRealtimeNode._azimuth_to_sector
        node.get_spatial_user_perception = AstroRealtimeNode.get_spatial_user_perception.__get__(node, AstroRealtimeNode)

        # Inject track matching user's real log
        track = SpatialPersonTrack(
            track_id="track_28",
            current_x=0.12,
            current_y=-0.84,
            distance_m=0.85,
            azimuth_deg=-81.8,
            velocity_mps=0.01,
            heading_deg=0.0,
            last_update_ts=100.0,
        )
        node.lidar_tracker._active_tracks["track_28"] = track

        perception = node.get_spatial_user_perception()
        self.assertTrue(perception["has_target"])
        self.assertEqual(perception["source"], "lidar")
        self.assertEqual(perception["distance_m"], 0.85)
        self.assertEqual(perception["azimuth_deg"], -81.8)
        self.assertEqual(perception["sector"], "tam sağımda")
        self.assertEqual(perception["motion"], "sabit duruyor")

    def test_03_get_spatial_user_perception_fallback_vision(self):
        """Verify that when LiDAR tracks are empty, vision user distance is used."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = MagicMock(spec=AstroRealtimeNode)
        node.lidar_tracker = LidarTracker()
        node._speaker_angle = None
        node._user_distance = 1.25
        node._azimuth_to_sector = AstroRealtimeNode._azimuth_to_sector
        node.get_spatial_user_perception = AstroRealtimeNode.get_spatial_user_perception.__get__(node, AstroRealtimeNode)

        perception = node.get_spatial_user_perception()
        self.assertTrue(perception["has_target"])
        self.assertEqual(perception["source"], "vision")
        self.assertEqual(perception["distance_m"], 1.25)
        self.assertEqual(perception["sector"], "tam karşımda / önümde")

    def test_04_system_prompt_includes_spatial_rule(self):
        """Verify _build_current_system_prompt injects distance and explicit refusal prevention."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = MagicMock(spec=AstroRealtimeNode)
        node.resolve_identities.return_value = {
            "name": "Baran",
            "is_known": True,
            "confidence": 0.95,
            "source": "biometric_voice",
        }
        node.get_logger.return_value = MagicMock()
        node.memory = MagicMock()
        node.memory.profile.get_person_recent_sessions.return_value = []
        node.memory.get_prompt_context.return_value = ""
        node.persona_name = "default"
        node.persona_engine = None
        node.social_brain = None

        node.get_spatial_user_perception = MagicMock(return_value={
            "has_target": True,
            "source": "lidar",
            "distance_m": 0.85,
            "azimuth_deg": -81.8,
            "sector": "tam sağımda",
            "motion": "sabit duruyor",
            "velocity_mps": 0.0,
            "all_tracks_count": 1,
        })
        node._build_current_system_prompt = AstroRealtimeNode._build_current_system_prompt.__get__(node, AstroRealtimeNode)

        prompt = node._build_current_system_prompt()
        self.assertIn("[MEKÂNSAL RADAR (LİDAR) VE MESAFE ALGILAMA]", prompt)
        self.assertIn("0.85 metre", prompt)
        self.assertIn("tam sağımda", prompt)
        self.assertIn("KESİNLİKLE 'mesafeni ölçemem'", prompt)
        self.assertIn("GPS'im yok", prompt)

    def test_05_get_spatial_surroundings_tool_execution(self):
        """Verify _execute_realtime_tool handles get_spatial_surroundings."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = MagicMock(spec=AstroRealtimeNode)
        node.lidar_tracker = LidarTracker()
        track = SpatialPersonTrack(
            track_id="track_1",
            current_x=1.2,
            current_y=0.0,
            distance_m=1.20,
            azimuth_deg=0.0,
            velocity_mps=-0.25,
            heading_deg=0.0,
            last_update_ts=100.0,
        )
        node.lidar_tracker._active_tracks["track_1"] = track
        node._speaker_angle = 0.0
        node._azimuth_to_sector = AstroRealtimeNode._azimuth_to_sector
        node.get_spatial_user_perception = AstroRealtimeNode.get_spatial_user_perception.__get__(node, AstroRealtimeNode)
        node.get_spatial_surroundings_report = AstroRealtimeNode.get_spatial_surroundings_report.__get__(node, AstroRealtimeNode)
        node._execute_realtime_tool = AstroRealtimeNode._execute_realtime_tool.__get__(node, AstroRealtimeNode)

        res = node._execute_realtime_tool("get_spatial_surroundings", {})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["detected_objects_count"], 1)
        self.assertEqual(res["speaker_perception"]["distance_m"], 1.20)
        self.assertIn("1.20 metre", res["summary_for_user"])

    def test_06_self_model_epistemic_radar_description(self):
        """Verify SelfModel explicitly includes RPLiDAR distance measurement capability."""
        model = SelfModel()
        prompt = model.get_self_description_prompt()
        self.assertIn("360° RPLiDAR A1", prompt)
        self.assertIn("santimetre hassasiyetinde", prompt)
        self.assertIn("GPS'im yok / ölçemem' deme", prompt)


if __name__ == "__main__":
    unittest.main()
