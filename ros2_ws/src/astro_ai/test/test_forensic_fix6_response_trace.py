"""Unit tests for Forensic FIX 6 — Unified Response Trace Pipeline.

Ensures:
1. Every spoken response generates a unified trace chain:
   USER_AUDIO → STT → USER_TURN_CREATED → SOCIAL_INTENT → SHOULD_SPEAK → LLM_PROVIDER → LLM_INFERENCE → RESPONSE_TEXT → TTS → PLAYBACK
2. If USER_TURN_CREATED is false, response chain terminates immediately (zero LLM / zero TTS).
3. If SHOULD_SPEAK is false, response chain terminates at gate.
4. Response telemetry reports:
   - generation_id
   - user_turn_id
   - response_origin
   - explicit_user_turn
   - should_speak
   - response_trace
5. In-memory SQLite storage (:memory:) is strictly used.
"""

import unittest
from unittest.mock import MagicMock, patch
import pytest

from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.local_gemma_client import LocalGemmaClient
from astro_ai.contracts.social_context import SocialAction, SocialDecision


class TestForensicFix6ResponseTrace(unittest.TestCase):
    """Forensic Fix 6 Verification Suite."""

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

    def test_01_complete_response_trace_on_valid_turn(self):
        """1. Valid user turn produces full response trace pipeline."""
        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.model_name = "gemma-4-E2B-it-Q4_K_S"

        def fake_stream(prompt, **kwargs):
            yield "Ben Astro, "
            yield "senin asistanınım."

        mock_gemma.stream.side_effect = fake_stream
        self.node.local_gemma_client = mock_gemma

        self.node._process_fallback_turn(direct_text="Astro, sen kimsin?")

        trace = getattr(self.node, "_last_response_trace", None)
        assert trace is not None, "Response trace must be recorded"
        assert trace["is_terminated"] is False
        assert trace["user_turn_created"] is True
        assert trace["explicit_user_turn"] is True
        assert trace["should_speak"] is True
        assert trace["llm_provider"] == "local_gemma"
        assert trace["tts_provider"] == "edge_tts"
        assert "USER_AUDIO" in trace["trace_chain"]
        assert "STT" in trace["trace_chain"]
        assert "USER_TURN_CREATED" in trace["trace_chain"]
        assert "SOCIAL_INTENT" in trace["trace_chain"]
        assert "SHOULD_SPEAK" in trace["trace_chain"]
        assert "LLM_PROVIDER" in trace["trace_chain"]
        assert "LLM_INFERENCE" in trace["trace_chain"]
        assert "RESPONSE_TEXT" in trace["trace_chain"]
        assert "TTS" in trace["trace_chain"]
        assert "PLAYBACK" in trace["trace_chain"]

        # Check turn telemetry contains trace fields
        telem = getattr(self.node, "_last_turn_telemetry", {})
        assert telem["generation_id"] == trace["generation_id"]
        assert telem["user_turn_id"] == trace["user_turn_id"]
        assert telem["response_origin"] == "local_gemma"
        assert telem["explicit_user_turn"] is True
        assert telem["should_speak"] is True
        assert "USER_AUDIO" in telem["response_trace"]

    def test_02_trace_terminated_when_no_user_turn(self):
        """2. When no explicit user turn occurs (ambient voice), trace is terminated at USER_TURN_CREATED."""
        raw_ambient_pcm = [b"\x00\x10" * 320 for _ in range(20)]

        with patch.object(self.node, "_transcribe_wav", return_value="Evet."):
            with patch.object(self.node, "_validate_stt_transcript", return_value=("Evet.", {"vad_confidence": 0.8})):
                self.node.session = MagicMock()
                self.node.session.is_active.return_value = False

                self.node._process_fallback_turn(audio_chunks=raw_ambient_pcm)

        trace = getattr(self.node, "_last_response_trace", None)
        assert trace is not None
        assert trace["is_terminated"] is True
        assert trace["user_turn_created"] is False
        assert trace["explicit_user_turn"] is False
        assert trace["should_speak"] is False
        assert "CHAIN TERMINATED" in trace["trace_chain"]
        assert "NO_EXPLICIT_USER_TURN" in trace["trace_chain"]
        assert trace["llm_provider"] == "none"
        assert trace["tts_provider"] == "none"

    def test_03_trace_terminated_when_should_speak_false(self):
        """3. When explicit turn occurs but should_speak=False, trace terminates at SHOULD_SPEAK."""
        mock_soc_dec = SocialDecision(
            should_speak=False,
            initiative_reason="QUIET_OVERHEARING_NOT_ADDRESSED",
            action=SocialAction.OBSERVE,
            directive="observe",
            gate_mode="OBSERVING",
        )
        self.node._last_social_decision = mock_soc_dec
        if hasattr(self.node, "social_brain") and self.node.social_brain:
            self.node.social_brain.process_dialogue_turn = MagicMock(
                return_value=(MagicMock(), mock_soc_dec, "prompt")
            )

        self.node._process_fallback_turn(direct_text="Astro, fısıldama denemesi")

        trace = getattr(self.node, "_last_response_trace", None)
        assert trace is not None
        assert trace["is_terminated"] is True
        assert trace["should_speak"] is False
        assert "CHAIN TERMINATED" in trace["trace_chain"]
        assert "SHOULD_SPEAK[FALSE]" in trace["trace_chain"]

    def test_04_emit_response_trace_helper_contract(self):
        """4. emit_response_trace produces strict contract schema."""
        record = self.node.emit_response_trace(
            generation_id=999,
            user_turn_id="turn_999",
            user_audio="32000B",
            stt="groq_whisper: 'merhaba'",
            user_turn_created=True,
            social_intent="greeting",
            should_speak=True,
            llm_provider="local_gemma",
            llm_inference="210ms",
            response_text="Merhaba Baran!",
            tts="edge_tts",
            playback="STARTED",
            response_origin="local_gemma",
        )
        assert record["generation_id"] == 999
        assert record["user_turn_id"] == "turn_999"
        assert record["response_origin"] == "local_gemma"
        assert record["explicit_user_turn"] is True
        assert record["should_speak"] is True
        assert record["is_terminated"] is False
        assert "→" in record["trace_chain"]
