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

    def test_07_multimodal_scoring_rejects_static_clutter_and_picks_gaze_target(self):
        """Verify that a stationary 0.83m obstacle is rejected when gaze and DOA point to user at 1.85m."""
        import time
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = MagicMock(spec=AstroRealtimeNode)
        node.lidar_tracker = LidarTracker()
        node._azimuth_to_sector = AstroRealtimeNode._azimuth_to_sector
        node.get_spatial_user_perception = AstroRealtimeNode.get_spatial_user_perception.__get__(node, AstroRealtimeNode)

        # Static clutter at 0.83m on the right/side (table leg)
        node.lidar_tracker._active_tracks["track_clutter"] = SpatialPersonTrack(
            track_id="track_clutter",
            current_x=0.35,
            current_y=-0.75,
            distance_m=0.83,
            azimuth_deg=-65.0,
            velocity_mps=0.00,
            heading_deg=0.0,
            last_update_ts=time.monotonic(),
            is_dynamic=False,
        )

        # Real moving human at 1.85m @ +20.0° (front-left)
        node.lidar_tracker._active_tracks["track_human"] = SpatialPersonTrack(
            track_id="track_human",
            current_x=1.74,
            current_y=0.63,
            distance_m=1.85,
            azimuth_deg=20.0,
            velocity_mps=-0.16,
            heading_deg=0.0,
            last_update_ts=time.monotonic(),
            is_dynamic=True,
        )

        # Gaze tracker locked on person at +22.0°
        node._tracked_gaze_yaw = 22.0
        node._last_tracked_gaze_time = time.monotonic()
        node._gaze_active_target = "person_4"

        # DOA heard speech from +18.0°
        node._speaker_angle = 18.0
        node._last_doa_time = time.monotonic()

        perception = node.get_spatial_user_perception()
        self.assertTrue(perception["has_target"])
        self.assertEqual(perception["distance_m"], 1.85)
        self.assertEqual(perception["azimuth_deg"], 20.0)
        self.assertEqual(perception["sector"], "tam karşımda / önümde")
        self.assertEqual(perception["motion"], "bana doğru yaklaşıyor")

    def test_08_dynamic_motion_alone_beats_static_clutter(self):
        """Verify that when no gaze or DOA is available, a walking user at 2.10m beats a static 0.83m obstacle."""
        import time
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = MagicMock(spec=AstroRealtimeNode)
        node.lidar_tracker = LidarTracker()
        node._azimuth_to_sector = AstroRealtimeNode._azimuth_to_sector
        node.get_spatial_user_perception = AstroRealtimeNode.get_spatial_user_perception.__get__(node, AstroRealtimeNode)

        # Static clutter at 0.83m behind robot (+126°)
        node.lidar_tracker._active_tracks["track_desk"] = SpatialPersonTrack(
            track_id="track_desk",
            current_x=-0.49,
            current_y=0.67,
            distance_m=0.83,
            azimuth_deg=126.0,
            velocity_mps=0.00,
            heading_deg=0.0,
            last_update_ts=time.monotonic(),
            is_dynamic=False,
        )

        # Moving user in front at 2.10m @ +10.0°
        node.lidar_tracker._active_tracks["track_user"] = SpatialPersonTrack(
            track_id="track_user",
            current_x=2.07,
            current_y=0.36,
            distance_m=2.10,
            azimuth_deg=10.0,
            velocity_mps=-0.20,
            heading_deg=0.0,
            last_update_ts=time.monotonic(),
            is_dynamic=True,
        )

        node._tracked_gaze_yaw = None
        node._gaze_active_target = "NONE"
        node._speaker_angle = None
        node._last_doa_time = 0.0

        perception = node.get_spatial_user_perception()
        self.assertTrue(perception["has_target"])
        self.assertEqual(perception["distance_m"], 2.10)
        self.assertEqual(perception["azimuth_deg"], 10.0)
        self.assertEqual(perception["motion"], "bana doğru yaklaşıyor")

    def test_09_laser_scan_passes_angle_increment_and_head_cmd_pos_callback(self):
        """Verify _on_laser_scan feeds scan angles and _on_head_cmd_pos updates gaze state."""
        import time
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = MagicMock(spec=AstroRealtimeNode)
        node.lidar_tracker = MagicMock()
        node.get_logger.return_value = MagicMock()
        node._evaluate_lidar_blindspot_approach = MagicMock()
        node.office_concierge = None
        node._on_laser_scan = AstroRealtimeNode._on_laser_scan.__get__(node, AstroRealtimeNode)
        node._on_head_cmd_pos = AstroRealtimeNode._on_head_cmd_pos.__get__(node, AstroRealtimeNode)

        # Fake LaserScan msg with RPLIDAR A1 params (~1150 samples, increment ~0.0054 rad)
        fake_scan = MagicMock()
        fake_scan.ranges = [2.0] * 1150
        fake_scan.angle_min = -math.pi
        fake_scan.angle_increment = 0.00546
        fake_scan.range_min = 0.15
        fake_scan.range_max = 12.0

        node._on_laser_scan(fake_scan)
        node.lidar_tracker.process_scan.assert_called_once()
        _, kwargs = node.lidar_tracker.process_scan.call_args
        self.assertAlmostEqual(kwargs["angle_increment"], 0.00546)
        self.assertAlmostEqual(kwargs["angle_min"], -math.pi)

        # Test _on_head_cmd_pos
        cmd_msg = MagicMock()
        cmd_msg.data = -45.5
        node._on_head_cmd_pos(cmd_msg)
        self.assertEqual(node._tracked_gaze_yaw, -45.5)
        self.assertGreater(node._last_tracked_gaze_time, 0.0)

    def test_10_mirror_resilience_aligns_inverted_lidar_track(self):
        """Verify that if LiDAR track is mirrored (+60° vs camera -60°), scoring pairs them and auto-aligns azimuth."""
        import time
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = MagicMock(spec=AstroRealtimeNode)
        node.lidar_tracker = LidarTracker()
        node._azimuth_to_sector = AstroRealtimeNode._azimuth_to_sector
        node.get_spatial_user_perception = AstroRealtimeNode.get_spatial_user_perception.__get__(node, AstroRealtimeNode)

        # Static clutter behind robot at 0.83m (+126°)
        node.lidar_tracker._active_tracks["track_desk"] = SpatialPersonTrack(
            track_id="track_desk",
            current_x=-0.49,
            current_y=0.67,
            distance_m=0.83,
            azimuth_deg=126.0,
            velocity_mps=0.00,
            heading_deg=0.0,
            last_update_ts=time.monotonic(),
            is_dynamic=False,
        )

        # Mirrored LiDAR track at +58.0° (Right side in reality, but seen as +Left in mirrored scan)
        node.lidar_tracker._active_tracks["track_mirrored_person"] = SpatialPersonTrack(
            track_id="track_mirrored_person",
            current_x=0.74,
            current_y=1.18,
            distance_m=1.40,
            azimuth_deg=58.0,
            velocity_mps=-0.05,
            heading_deg=0.0,
            last_update_ts=time.monotonic(),
            is_dynamic=True,
        )

        # Active gaze camera is locked to the RIGHT at -60.0°
        node._tracked_gaze_yaw = -60.0
        node._last_tracked_gaze_time = time.monotonic()
        node._gaze_active_target = "person_4"
        node._speaker_angle = None
        node._last_doa_time = 0.0

        perception = node.get_spatial_user_perception()
        self.assertTrue(perception["has_target"])
        self.assertEqual(perception["distance_m"], 1.40)
        # Verify auto-alignment flipped the azimuth from +58.0 to -58.0 to match camera
        self.assertEqual(perception["azimuth_deg"], -58.0)
        self.assertIn("sağ", perception["sector"].lower())

    def test_11_active_gaze_lock_fallback_never_blind(self):
        """Verify that when camera is locked onto person_4 but LiDAR has no track, perception returns active gaze target."""
        import time
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = MagicMock(spec=AstroRealtimeNode)
        node.lidar_tracker = LidarTracker()
        node._azimuth_to_sector = AstroRealtimeNode._azimuth_to_sector
        node.get_spatial_user_perception = AstroRealtimeNode.get_spatial_user_perception.__get__(node, AstroRealtimeNode)

        # Empty LiDAR tracks
        node.lidar_tracker._active_tracks = {}

        # Camera actively tracking person_7 at +35.0°
        node._tracked_gaze_yaw = 35.0
        node._last_tracked_gaze_time = time.monotonic()
        node._gaze_active_target = "person_7"
        node._user_distance = 1.25
        node._last_user_distance_time = time.monotonic()
        node._speaker_angle = None
        node._last_doa_time = 0.0

        perception = node.get_spatial_user_perception()
        self.assertTrue(perception["has_target"])
        self.assertEqual(perception["distance_m"], 1.25)
        self.assertEqual(perception["azimuth_deg"], 35.0)
        self.assertEqual(perception["source"], "vision_gaze")


if __name__ == "__main__":
    unittest.main()

