"""Tests for FIX 1: OAK-D Visual Evidence Decay and Freshness Evaluation."""

import time
import unittest
from unittest.mock import MagicMock, patch

from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.contracts.person_state import UnifiedPersonState


class TestFix1VisualEvidenceDecay(unittest.TestCase):
    """Verifies that OAK-D visual evidence decays properly and avoids stale Camera=Eye claims."""

    def setUp(self):
        try:
            import rclpy
            if not rclpy.ok():
                rclpy.init(args=None)
        except Exception:
            pass

        self.node = AstroRealtimeNode(connect_realtime=False, use_realtime=False)
        self.node.visual_evidence_ttl_s = 2.0  # 2.0s TTL for tests

    def tearDown(self):
        try:
            self.node.destroy_node()
        except Exception:
            pass

    def test_01_fresh_visual_observation_is_visible(self):
        """Fresh visual distance and looking observation is recognized as visible within TTL."""
        now = time.monotonic()
        self.node._user_distance = 1.2
        self.node._last_vision_distance_time = now
        self.node._looking_at_robot = True
        self.node._last_vision_looking_time = now

        self.assertTrue(self.node.is_visual_evidence_fresh(now=now + 0.5))
        self.assertEqual(self.node.get_fresh_visual_distance(now=now + 0.5), 1.2)
        self.assertTrue(self.node.get_fresh_looking_at_robot(now=now + 0.5))

    def test_02_stale_visual_observation_is_not_visible(self):
        """Visual evidence older than TTL decays and is no longer fresh or visible."""
        t0 = time.monotonic() - 5.0  # 5 seconds ago (> 2.0s TTL)
        self.node._user_distance = 1.5
        self.node._last_vision_distance_time = t0
        self.node._looking_at_robot = True
        self.node._last_vision_looking_time = t0

        t_current = time.monotonic()
        self.assertFalse(self.node.is_visual_evidence_fresh(now=t_current))
        self.assertEqual(self.node.get_fresh_visual_distance(now=t_current), 0.0)
        self.assertFalse(self.node.get_fresh_looking_at_robot(now=t_current))

    def test_03_stale_observation_cannot_satisfy_camera_eye(self):
        """When visual observation decays, Camera=Eye forbids visual claims and flags audio-only evidence."""
        t0 = time.monotonic() - 10.0
        self.node._user_distance = 1.3
        self.node._last_vision_distance_time = t0
        self.node._looking_at_robot = False
        self.node._last_vision_looking_time = t0

        prompt = self.node._build_current_system_prompt()
        self.assertIn("KAMERA = GÖZ (EPISTEMIK SINIR)", prompt)
        self.assertIn("YALNIZCA SESİ DUYULUYOR", prompt)
        self.assertIn("sahte görsel iddialarda bulunma", prompt)

    def test_04_fresh_observation_restores_visibility(self):
        """New observation after stale decay immediately restores visual confirmation."""
        t_stale = time.monotonic() - 10.0
        self.node._user_distance = 1.3
        self.node._last_vision_distance_time = t_stale

        self.assertFalse(self.node.is_visual_evidence_fresh())

        # Fresh message arrives
        now = time.monotonic()
        self.node._user_distance = 1.1
        self.node._last_vision_distance_time = now
        self.node._looking_at_robot = True
        self.node._last_vision_looking_time = now

        self.assertTrue(self.node.is_visual_evidence_fresh(now=now))
        self.assertEqual(self.node.get_fresh_visual_distance(now=now), 1.1)
        self.assertTrue(self.node.get_fresh_looking_at_robot(now=now))


if __name__ == "__main__":
    unittest.main()
