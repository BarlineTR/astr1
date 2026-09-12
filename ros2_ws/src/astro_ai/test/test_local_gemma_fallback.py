#!/usr/bin/env python3
"""Comprehensive Unit & Integration Tests for ASTRO Local Gemma 4 E2B Q4_K_S Fallback.

Tests:
  - LocalGemmaClient HTTP contract, health probe, SSE stream parsing, and error hierarchy
  - ProviderRegistry local_gemma registration and telemetry tracking
  - AstroRealtimeNode Attempt 0 local_gemma priority routing
  - Cloud fall-through (Local Gemma -> Groq -> Gemini -> Persona)
  - Barge-in cancellation guard during streaming
  - Protected files immutability verification (Realtime API red line preservation)
"""

import io
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
from typing import Generator
from unittest.mock import MagicMock, patch

# Ensure paths
ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

from astro_ai.local_gemma_client import (
    LocalGemmaClient,
    LocalGemmaError,
    LocalGemmaConnectionError,
    LocalGemmaTimeoutError,
    LocalGemmaHTTPError,
    LocalGemmaInvalidResponseError,
    LocalGemmaModelUnavailableError,
)
from astro_ai.provider_registry import (
    ProviderRegistry,
    ProviderError,
    ProviderHealth,
    ErrorClass,
    LOCAL_GEMMA_PRODUCTION_MODELS,
)


class TestLocalGemmaClient(unittest.TestCase):
    """Unit tests for LocalGemmaClient HTTP/SSE implementation."""

    def setUp(self):
        self.client = LocalGemmaClient(base_url="http://127.0.0.1:8080", timeout_s=1.0)

    @patch("urllib.request.urlopen")
    def test_health_check_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        self.assertTrue(self.client.health_check())
        self.assertTrue(self.client.is_available())

    @patch("urllib.request.urlopen")
    def test_health_check_failure(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        self.assertFalse(self.client.health_check())
        self.assertFalse(self.client.is_available())

    @patch("urllib.request.urlopen")
    def test_generate_sync(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"content": "Merhaba dünya!"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        result = self.client.generate("Selam")
        self.assertEqual(result, "Merhaba dünya!")

        # Verify request parameters
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "http://127.0.0.1:8080/completion")
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["prompt"], "Selam")
        self.assertEqual(body["n_predict"], 28)
        self.assertEqual(body["temperature"], 0.2)
        self.assertFalse(body["stream"])

    def test_generate_empty_prompt(self):
        self.assertEqual(self.client.generate(""), "")
        self.assertEqual(self.client.generate("   "), "")

    @patch("urllib.request.urlopen")
    def test_stream_sse_parsing(self, mock_urlopen):
        sse_data = [
            b"data: {\"content\": \"Ben \", \"stop\": false}\n\n",
            b": keep-alive comment\n\n",
            b"data: {\"content\": \"Astro, \", \"stop\": false}\n\n",
            b"data: {\"content\": \"yard\xc4\xb1mc\xc4\xb1y\xc4\xb1m.\", \"stop\": true}\n\n",
            b"data: [DONE]\n\n",
        ]
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__iter__.return_value = iter(sse_data)
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        chunks = list(self.client.stream("Kimsin?"))
        self.assertEqual(chunks, ["Ben ", "Astro, ", "yardımcıyım."])

    @patch("urllib.request.urlopen")
    def test_stream_connection_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        with self.assertRaises(LocalGemmaConnectionError):
            list(self.client.stream("Selam"))

    @patch("urllib.request.urlopen")
    def test_stream_timeout_error(self, mock_urlopen):
        mock_urlopen.side_effect = socket.timeout("timed out")
        with self.assertRaises(LocalGemmaTimeoutError):
            list(self.client.stream("Selam"))

    @patch("urllib.request.urlopen")
    def test_stream_http_503_unavailable(self, mock_urlopen):
        mock_err = urllib.error.HTTPError(
            url="http://127.0.0.1:8080/completion",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=io.BytesIO(b"Model is loading"),
        )
        mock_urlopen.side_effect = mock_err
        with self.assertRaises(LocalGemmaModelUnavailableError):
            list(self.client.stream("Selam"))


class TestProviderRegistryLocalGemma(unittest.TestCase):
    """Tests for ProviderRegistry local_gemma integration."""

    def setUp(self):
        self.registry = ProviderRegistry()

    def test_local_gemma_registered(self):
        models = self.registry.get_candidate_models("local_gemma")
        self.assertIn("gemma-4-E2B-it-Q4_K_S", models)
        self.assertEqual(self.registry.get_provider_health("local_gemma"), ProviderHealth.HEALTHY)

    def test_stream_local_gemma_completion_success(self):
        mock_client = MagicMock(spec=LocalGemmaClient)
        mock_client.stream.return_value = iter(["Merhaba", " ", "insan!"])

        tokens = list(self.registry.stream_local_gemma_completion(
            prompt="Selam",
            client=mock_client,
            n_predict=12,
            temperature=0.2,
        ))
        self.assertEqual(tokens, ["Merhaba", " ", "insan!"])
        model_cap = self.registry.get_model("local_gemma", "gemma-4-E2B-it-Q4_K_S")
        self.assertIsNotNone(model_cap)
        self.assertEqual(model_cap.consecutive_errors, 0)

    def test_stream_local_gemma_completion_mapped_error(self):
        mock_client = MagicMock(spec=LocalGemmaClient)
        mock_client.stream.side_effect = LocalGemmaConnectionError("Connection refused")

        with self.assertRaises(ProviderError) as cm:
            list(self.registry.stream_local_gemma_completion(
                prompt="Selam",
                client=mock_client,
            ))
        self.assertEqual(cm.exception.error_class, ErrorClass.NETWORK_ERROR)
        self.assertEqual(cm.exception.provider, "local_gemma")


class TestAstroRealtimeNodeLocalGemmaFallback(unittest.TestCase):
    """Unit tests for fallback execution in AstroRealtimeNode."""

    def setUp(self):
        try:
            import rclpy
            if not rclpy.ok():
                rclpy.init(args=None)
        except Exception:
            pass

        from astro_ai.astro_realtime_node import AstroRealtimeNode
        self.node = AstroRealtimeNode(connect_realtime=False)
        self.node._is_processing_fallback = False
        self.node._is_responding = False

    def tearDown(self):
        try:
            self.node.destroy_node()
        except Exception:
            pass

    def test_local_gemma_attempt_0_executed_when_available(self):
        """Verify Attempt 0 (Local Gemma) executes and synthesizes audio when available."""
        mock_client = MagicMock(spec=LocalGemmaClient)
        mock_client.is_available.return_value = True
        mock_client.stream.return_value = iter(["Selam ", "dostum, ", "ben ", "Astro!"])

        self.node.local_gemma_client = mock_client
        self.node.groq_api_key = "mock_groq_key"

        mock_pcm = b"\x00\x00" * 2400  # 100ms dummy PCM
        mock_route_res = MagicMock()
        mock_route_res.pcm = mock_pcm
        mock_route_res.duration_ms = 100.0
        mock_route_res.infer_ms = 15.0
        mock_route_res.queue_wait_ms = 0.0
        mock_route_res.actual_provider = "edge_tts"
        mock_route_res.source_name = "edge_tts_cloud"
        mock_route_res.model_name = "tr_tr_ahmet"

        played_pcm_list = []
        with patch.object(self.node.tts_router, "synthesize", return_value=mock_route_res), \
             patch.object(self.node, "_play_pcm_chunks", side_effect=lambda pcm, **kw: played_pcm_list.append(pcm)):
            self.node._process_fallback_turn(direct_text="Nasılsın?")

        mock_client.stream.assert_called_once()
        self.assertTrue(len(played_pcm_list) >= 1)

    def test_local_gemma_failure_falls_through_to_groq(self):
        """Verify that when Local Gemma fails, execution falls through to Groq without crashing."""
        mock_client = MagicMock(spec=LocalGemmaClient)
        mock_client.is_available.return_value = True
        mock_client.stream.side_effect = LocalGemmaConnectionError("Server down")

        self.node.local_gemma_client = mock_client
        self.node.groq_api_key = "mock_groq_key"

        groq_streamed = []
        def mock_stream_groq(*args, **kwargs):
            groq_streamed.append(True)
            yield "Cevap Groq'tan geldi."

        with patch.object(self.node.provider_registry, "stream_groq_completion", side_effect=mock_stream_groq), \
             patch.object(self.node.tts_router, "synthesize", return_value=MagicMock(pcm=b"\x00" * 100, duration_ms=10.0, infer_ms=5.0, queue_wait_ms=0.0, actual_provider="edge_tts", source_name="edge_tts_cloud", model_name="tr_tr_ahmet")), \
             patch.object(self.node, "_play_pcm_chunks"):
            self.node._process_fallback_turn(direct_text="Naber?")

        self.assertTrue(len(groq_streamed) > 0, "Groq should have been called when Local Gemma failed")

    def test_local_gemma_barge_in_cancellation(self):
        """Verify barge-in latched aborts Local Gemma streaming immediately."""
        tokens_emitted = []

        def token_generator():
            for t in ["Bir", " ", "iki", " ", "üç", " ", "dört"]:
                tokens_emitted.append(t)
                if len(tokens_emitted) >= 3:
                    # Simulate user interrupt
                    self.node._barge_in_latched = True
                yield t

        mock_client = MagicMock(spec=LocalGemmaClient)
        mock_client.is_available.return_value = True
        mock_client.stream.return_value = token_generator()

        self.node.local_gemma_client = mock_client

        with patch.object(self.node.tts_router, "synthesize", return_value=MagicMock(pcm=b"", duration_ms=0.0, infer_ms=0.0, queue_wait_ms=0.0, actual_provider="none", source_name="none", model_name="none")), \
             patch.object(self.node, "_play_pcm_chunks"):
            self.node._process_fallback_turn(direct_text="Say bakalım")

        # Generator should have stopped early
        self.assertLess(len(tokens_emitted), 7)


class TestProtectedFilesIntegrity(unittest.TestCase):
    """Verifies that the Red Line files have zero git modifications."""

    def test_protected_files_have_zero_diff(self):
        protected_files = [
            "ros2_ws/src/astro_audio/astro_audio/realtime_engine.py",
            "ros2_ws/src/astro_audio/astro_audio/audio_stream_node.py",
            "ros2_ws/src/astro_audio/astro_audio/edge_tts_engine.py",
        ]
        repo_root = os.path.abspath(os.path.join(ws_src, ".."))
        for pf in protected_files:
            res = subprocess.run(
                ["git", "diff", "--name-only", pf],
                capture_output=True,
                text=True,
                cwd=repo_root,
            )
            diff_output = res.stdout.strip()
            self.assertEqual(
                diff_output,
                "",
                f"PROTECTED RED LINE VIOLATION: File {pf} has uncommitted diff: {diff_output}",
            )


if __name__ == "__main__":
    unittest.main()
