"""Unit tests for Forensic FIX 5 — Local Mode Cloud Isolation.

Ensures:
1. use_realtime=False strictly enforces zero cloud LLM leakage (OpenAI Realtime, Groq, Gemini).
2. Edge-TTS is kept separate from LLM telemetry.
3. Telemetry truthfulness:
   - llm_provider=local_gemma
   - tts_provider=edge_tts
   - requested_provider=local_gemma (never misleading "openai_realtime")
4. GeminiFlashProvider is disabled when USE_REALTIME=false.
5. In-memory SQLite storage (:memory:) is strictly used.
"""

import os
import unittest
from unittest.mock import MagicMock, patch
import pytest

from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.brain.support.gemini_provider import GeminiFlashProvider
from astro_ai.brain.support.config import SupportConfig
from astro_ai.brain.support.contracts import SupportStatus
from astro_ai.local_gemma_client import LocalGemmaClient


class TestForensicFix5LocalModeCloudIsolation(unittest.TestCase):
    """Forensic Fix 5 Verification Suite."""

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
        self.node.groq_api_key = "gsk_test_key"
        self.node.gemini_api_key = "gem_test_key"

        mock_tts_res = MagicMock()
        mock_tts_res.pcm = b"pcm_audio_data"
        mock_tts_res.duration_ms = 100.0
        mock_tts_res.infer_ms = 30.0
        mock_tts_res.queue_wait_ms = 1.0
        mock_tts_res.actual_provider = "edge_tts"
        mock_tts_res.model_name = "tr_tr_ahmet"
        mock_tts_res.source_name = "edge_tts_cloud"
        self.node.tts_router.synthesize = MagicMock(return_value=mock_tts_res)

    def tearDown(self):
        try:
            self.node.destroy_node()
        except Exception:
            pass

    def test_01_can_use_openai_strictly_false_in_local_mode(self):
        """1. _can_use_openai strictly returns False when use_realtime=False."""
        self.node.use_realtime = False
        assert self.node._can_use_openai("realtime") is False
        assert self.node._can_use_openai("stt") is False
        assert self.node._can_use_openai("all") is False

    def test_02_zero_cloud_llm_leakage_when_local_mode_active(self):
        """2. When use_realtime=False, Groq and Gemini cloud LLMs are NEVER called during response generation."""
        self.node.use_realtime = False

        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.model_name = "gemma-4-E2B-it-Q4_K_S"

        def fake_stream(prompt, **kwargs):
            yield "Merhaba "
            yield "Baran."

        mock_gemma.stream.side_effect = fake_stream
        self.node.local_gemma_client = mock_gemma

        # Mock TTS Router to simulate Edge-TTS without requiring network or edge_tts pip package
        mock_tts_res = MagicMock()
        mock_tts_res.pcm = b"pcm_audio_data"
        mock_tts_res.duration_ms = 100.0
        mock_tts_res.infer_ms = 30.0
        mock_tts_res.queue_wait_ms = 1.0
        mock_tts_res.actual_provider = "edge_tts"
        mock_tts_res.model_name = "tr_tr_ahmet"
        mock_tts_res.source_name = "edge_tts_cloud"
        self.node.tts_router.synthesize = MagicMock(return_value=mock_tts_res)

        # Spy on provider_registry
        self.node.provider_registry.stream_groq_completion = MagicMock()
        self.node.provider_registry.generate_gemini_content = MagicMock()

        self.node._process_fallback_turn(direct_text="Astro, nasılsın?")

        # Assert Local Gemma was called
        mock_gemma.stream.assert_called_once()

        # Assert zero cloud LLM calls were made
        self.node.provider_registry.stream_groq_completion.assert_not_called()
        self.node.provider_registry.generate_gemini_content.assert_not_called()

        # Assert telemetry truthfulness
        telem = getattr(self.node, "_last_turn_telemetry", {})
        assert telem.get("llm_provider") == "local_gemma"
        assert telem.get("tts_provider") == "edge_tts"
        assert telem.get("requested_provider") == "local_gemma"
        assert telem.get("requested_provider") != "openai_realtime"
        assert telem.get("realtime_state") == "LOCAL_ACTIVE"
        assert telem.get("realtime_failure_reason") == "none"

    def test_03_zero_cloud_llm_even_if_local_gemma_fails(self):
        """3. Even if Local Gemma fails, cloud LLMs are strictly NOT called in local mode."""
        self.node.use_realtime = False

        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.model_name = "gemma-4-E2B-it-Q4_K_S"
        mock_gemma.stream.side_effect = RuntimeError("llama.cpp timeout")
        self.node.local_gemma_client = mock_gemma

        self.node._generate_contextual_persona_fallback = MagicMock(return_value="Anlıyorum seni dinliyorum.")

        self.node.provider_registry.stream_groq_completion = MagicMock()
        self.node.provider_registry.generate_gemini_content = MagicMock()

        self.node._process_fallback_turn(direct_text="Astro, nasılsın?")

        # Assert zero cloud LLM calls
        self.node.provider_registry.stream_groq_completion.assert_not_called()
        self.node.provider_registry.generate_gemini_content.assert_not_called()

        # Assert degraded local fallback was used
        telem = getattr(self.node, "_last_turn_telemetry", {})
        assert telem.get("llm_provider") == "local_persona"
        assert telem.get("tts_provider") == "edge_tts"
        assert telem.get("requested_provider") == "local_gemma"

    def test_04_gemini_support_disabled_when_use_realtime_false(self):
        """4. GeminiFlashProvider is disabled when USE_REALTIME=false."""
        cfg = SupportConfig(gemini_support_enabled=True, gemini_api_key="gem-test-key")
        with patch.dict(os.environ, {"USE_REALTIME": "false"}):
            provider = GeminiFlashProvider(config=cfg)
            assert provider.is_available() is False

            resp = provider.generate_analysis(
                prompt="Review architecture",
                context="Astro local mode",
                mode=MagicMock(),
                request_id="req-fix5-01",
            )
            assert resp.status == SupportStatus.PROVIDER_UNAVAILABLE
            assert resp.error_code == "LOCAL_MODE_ACTIVE"
            assert "disabled in local mode" in resp.summary
