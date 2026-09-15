"""Unit and integration tests for FIX 4: Interaction Gate Hard Runtime Block.

Verifies:
1. When should_speak == False, Local Gemma client is NEVER called (0 stream calls).
2. When should_speak == False, Cloud providers and TTS are NEVER called (0 LLM / 0 TTS).
3. When should_speak == False, Realtime WebSocket orchestrator NEVER dispatches response.create (0 token).
4. When should_speak == True, normal execution proceeds for both Local Gemma and Realtime.
"""

import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.brain.social_brain import SocialBrain
from astro_ai.contracts.social_context import SocialDecision
from astro_ai.state_machine import RobotState


class TestInteractionGateHardBlock(unittest.TestCase):
    """Test suite for FIX 4: Interaction Gate Hard Runtime Block."""

    def setUp(self):
        with patch.dict("os.environ", {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-test1234"}):
            self.node = AstroRealtimeNode(connect_realtime=False)
            self.node.social_brain = SocialBrain(db_path=":memory:", enable_migration=False)
            self.node.state_machine.transition_to(RobotState.LISTENING)
            self.node._is_sleeping = False
            self.node._is_quiet_mode = False

            # Mock local gemma client
            self.mock_gemma = MagicMock()
            self.mock_gemma.is_available.return_value = True
            self.mock_gemma.stream.return_value = iter(["Merhaba ", "nasıl", "sınız?"])
            self.node.local_gemma_client = self.mock_gemma

            # Mock TTS router
            self.mock_tts = MagicMock()
            self.node.tts_router = self.mock_tts

    def test_01_fallback_turn_hard_block_zero_gemma_zero_tts(self):
        """When should_speak is False, _process_fallback_turn hard returns before Gemma or TTS."""
        # Force a social decision with should_speak=False
        gated_decision = SocialDecision(
            should_speak=False,
            initiative_reason="GATE_OBSERVING_BACKGROUND_SPEECH",
            gate_mode="OBSERVING",
        )

        with patch.object(self.node.social_brain, "process_dialogue_turn") as mock_turn:
            mock_ctx = MagicMock()
            mock_ctx.user_intent = "UNKNOWN"
            mock_turn.return_value = (mock_ctx, gated_decision, "[OBSERVING GATE]")

            # Run a fallback turn with a generic query
            self.node._process_fallback_turn(
                direct_text="Ahmet dün ofiste miydi?",
            )

            # Invariant: 0 Local Gemma calls
            self.mock_gemma.stream.assert_not_called()
            # Invariant: 0 TTS synthesis calls
            self.mock_tts.synthesize.assert_not_called()

    def test_02_fallback_turn_allowed_when_should_speak_true(self):
        """When should_speak is True, Local Gemma streams and TTS synthesizes normally."""
        allowed_decision = SocialDecision(
            should_speak=True,
            initiative_reason="DIRECT_ENGAGEMENT",
            gate_mode="ENGAGED",
        )

        with patch.object(self.node.social_brain, "process_dialogue_turn") as mock_turn:
            mock_ctx = MagicMock()
            mock_ctx.user_intent = "GREETING"
            mock_turn.return_value = (mock_ctx, allowed_decision, "[ENGAGED GATE]")

            mock_synth_res = MagicMock()
            mock_synth_res.actual_provider = "local_gemma"
            mock_synth_res.source_name = "local"
            mock_synth_res.model_name = "gemma"
            mock_synth_res.pcm = b"\x00" * 1600
            mock_synth_res.duration_ms = 100.0
            mock_synth_res.infer_ms = 50.0
            mock_synth_res.queue_wait_ms = 0.0
            self.mock_tts.synthesize.return_value = mock_synth_res

            # Run a fallback turn
            self.node._process_fallback_turn(
                direct_text="Astro, selam!",
            )

            # Local Gemma must be invoked
            self.mock_gemma.stream.assert_called_once()

    def test_03_realtime_orchestrator_hard_blocks_response_create(self):
        """When should_speak is False, _orchestrate_turn_after_speech_stopped never sends response.create."""
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()

        self.node._validate_user_speech_acoustics = MagicMock(return_value=True)

        gated_decision = SocialDecision(
            should_speak=False,
            initiative_reason="GATE_OBSERVING_BACKGROUND_SPEECH",
            gate_mode="OBSERVING",
        )
        self.node._last_social_decision = gated_decision

        async def run_test():
            await self.node._orchestrate_turn_after_speech_stopped(ws=mock_ws)

        asyncio.run(run_test())

        # Invariant: 0 response.create messages sent over WebSocket
        mock_ws.send.assert_not_called()

    def test_04_realtime_orchestrator_dispatches_when_should_speak_true(self):
        """When should_speak is True, _orchestrate_turn_after_speech_stopped sends response.create."""
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()

        self.node._validate_user_speech_acoustics = MagicMock(return_value=True)

        allowed_decision = SocialDecision(
            should_speak=True,
            initiative_reason="DIRECT_ENGAGEMENT",
            gate_mode="ENGAGED",
        )
        self.node._last_social_decision = allowed_decision

        async def run_test():
            await self.node._orchestrate_turn_after_speech_stopped(ws=mock_ws)

        asyncio.run(run_test())

        # response.create must have been sent
        mock_ws.send.assert_called_once()
        sent_payload = json.loads(mock_ws.send.call_args[0][0])
        self.assertEqual(sent_payload.get("type"), "response.create")


if __name__ == "__main__":
    unittest.main()
