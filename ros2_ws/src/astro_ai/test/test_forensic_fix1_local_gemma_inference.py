#!/usr/bin/env python3
"""Forensic Fix 1: Local Gemma Inference Proof and Truthful Telemetry Tests.

Verifies:
1. In local mode (use_realtime=False), user query 'ben şu anda ne yapıyorum?' enters Local Gemma.
2. Prompt, model, inference duration, and success/failure are measured.
3. Telemetry accurately distinguishes actual local_gemma inference vs hardcoded_template / deterministic_policy.
4. If Local Gemma fails or is unavailable, telemetry NEVER claims local_gemma as provider.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

from astro_ai.local_gemma_client import LocalGemmaClient, LocalGemmaConnectionError
from astro_ai.astro_realtime_node import AstroRealtimeNode


class TestForensicFix1LocalGemmaInference(unittest.TestCase):
    """Forensic Fix 1 unit test suite."""

    def setUp(self):
        try:
            import rclpy
            if not rclpy.ok():
                rclpy.init(args=None)
        except Exception:
            pass

        self.node = AstroRealtimeNode(connect_realtime=False)
        self.node.use_realtime = False
        self.node._is_processing_fallback = False
        self.node._is_responding = False

    def tearDown(self):
        try:
            self.node.destroy_node()
        except Exception:
            pass

    def test_01_user_query_routes_to_local_gemma_inference(self):
        """'ben şu anda ne yapıyorum?' must route into Local Gemma inference in local mode."""
        mock_client = MagicMock(spec=LocalGemmaClient)
        mock_client.is_available.return_value = True
        mock_client.model_name = "gemma-4-E2B-it-Q4_K_S"

        captured_prompt = []
        def fake_stream(prompt, **kwargs):
            captured_prompt.append(prompt)
            yield "Bilgisayar başında "
            yield "çalışıyorsun."

        mock_client.stream.side_effect = fake_stream
        self.node.local_gemma_client = mock_client

        mock_pcm = b"\x00\x00" * 2400
        mock_route = MagicMock(pcm=mock_pcm, duration_ms=100.0, infer_ms=10.0, queue_wait_ms=0.0,
                               actual_provider="edge_tts", source_name="edge_tts_cloud", model_name="tr_tr_ahmet")

        with patch.object(self.node.tts_router, "synthesize", return_value=mock_route), \
             patch.object(self.node, "_play_pcm_chunks"):
            self.node._process_fallback_turn(direct_text="ben şu anda ne yapıyorum?")

        mock_client.stream.assert_called_once()
        self.assertTrue(len(captured_prompt) > 0)
        self.assertIn("ben şu anda ne yapıyorum?", captured_prompt[0])

        telem = getattr(self.node, "_last_turn_telemetry", {})
        self.assertEqual(telem.get("llm_provider"), "local_gemma")
        self.assertEqual(telem.get("llm_model"), "gemma-4-E2B-it-Q4_K_S")
        self.assertTrue(telem.get("llm_inference_started"))
        self.assertTrue(telem.get("llm_inference_completed"))
        self.assertEqual(telem.get("response_origin"), "local_gemma")

    def test_02_local_gemma_failure_never_reports_local_gemma(self):
        """When Local Gemma raises an exception, telemetry must NOT report local_gemma as provider."""
        mock_client = MagicMock(spec=LocalGemmaClient)
        mock_client.is_available.return_value = True
        mock_client.model_name = "gemma-4-E2B-it-Q4_K_S"
        mock_client.stream.side_effect = LocalGemmaConnectionError("Connection refused")
        self.node.local_gemma_client = mock_client

        mock_pcm = b"\x00\x00" * 2400
        mock_route = MagicMock(pcm=mock_pcm, duration_ms=100.0, infer_ms=10.0, queue_wait_ms=0.0,
                               actual_provider="edge_tts", source_name="edge_tts_cloud", model_name="tr_tr_ahmet")

        with patch.object(self.node.tts_router, "synthesize", return_value=mock_route), \
             patch.object(self.node, "_play_pcm_chunks"):
            self.node._process_fallback_turn(direct_text="ben şu anda ne yapıyorum?")

        telem = getattr(self.node, "_last_turn_telemetry", {})
        self.assertNotEqual(telem.get("llm_provider"), "local_gemma")
        self.assertFalse(telem.get("llm_inference_completed"))
        self.assertEqual(telem.get("response_origin"), "hardcoded_template")
        self.assertEqual(telem.get("llm_provider"), "local_persona")

    def test_03_deterministic_policy_reports_deterministic_policy(self):
        """Direct deterministic queries (e.g. angle) must report response_origin='deterministic_policy'."""
        mock_pcm = b"\x00\x00" * 2400
        mock_route = MagicMock(pcm=mock_pcm, duration_ms=50.0, infer_ms=5.0, queue_wait_ms=0.0,
                               actual_provider="edge_tts", source_name="edge_tts_cloud", model_name="tr_tr_ahmet")

        with patch.object(self.node.tts_router, "synthesize", return_value=mock_route), \
             patch.object(self.node, "_play_pcm_chunks"):
            self.node._process_fallback_turn(direct_text="0 dereceye dön")

        telem = getattr(self.node, "_last_turn_telemetry", {})
        self.assertEqual(telem.get("response_origin"), "deterministic_policy")
        self.assertEqual(telem.get("llm_provider"), "none")
        self.assertFalse(telem.get("llm_inference_started"))
        self.assertFalse(telem.get("llm_inference_completed"))


if __name__ == "__main__":
    unittest.main()
