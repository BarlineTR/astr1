"""Forensic Fix 3 Test — No User Turn, No Speech & Hard Gate Verification.

Verifies:
1. Perception events alone (person detected, face/gaze detected) NEVER initiate speech.
2. "Evet." without wake when no active conversation session produces 0 LLM and 0 TTS.
3. Valid wake + user query ("Astro ben şu anda ne yapıyorum?") admits conversation turn.
4. Default proactive_speech_enabled is False (PROACTIVE_SPEECH = OFF).
5. Hard Gate: without (should_speak and explicit_user_turn), zero Local Gemma, zero Realtime response.create, zero TTS, zero playback.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import json

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"
os.environ["ASTRO_TEST_MODE"] = "1"

try:
    from std_msgs.msg import String
except ImportError:
    class String:  # type: ignore
        def __init__(self, data: str = ""):
            self.data = data

from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.contracts.social_context import SocialDecision
from astro_ai.state_machine import RobotState


class TestForensicFix3NoUserTurnNoSpeech(unittest.TestCase):
    """Test suite ensuring Astro NEVER speaks without an explicit user turn."""

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
        self.node.local_gemma_client = MagicMock()
        self.node.local_gemma_client.is_available.return_value = True
        self.node.local_gemma_client.model_name = "gemma-4-E2B-it-Q4_K_S"
        self.node.local_gemma_client.stream.return_value = ["Cevap"]
        self.node.tts_router = MagicMock()
        mock_route = MagicMock()
        mock_route.actual_provider = "edge_tts"
        mock_route.source_name = "edge_tts_cloud"
        mock_route.model_name = "tr_tr_ahmet"
        mock_route.pcm = b"pcm_16k_test_bytes" * 100
        mock_route.duration_ms = 100.0
        mock_route.infer_ms = 50.0
        mock_route.queue_wait_ms = 0.0
        self.node.tts_router.synthesize.return_value = mock_route
        self.node.pub_output_pcm = MagicMock()

    def test_default_proactive_speech_is_off(self):
        """Default configuration MUST have proactive_speech_enabled == False."""
        self.assertFalse(self.node.proactive_speech_enabled)

    def test_person_detected_alone_does_not_trigger_speech(self):
        """Person detection perception event MUST NOT trigger speech or Realtime greeting."""
        with patch.object(self.node, "_trigger_proactive_greeting") as mock_greet:
            person_msg = String()
            person_msg.data = json.dumps({
                "name": "Baran",
                "title": "Geliştirici",
                "is_known": True,
                "confidence": 0.90,
            })
            self.node._on_recognized_person(person_msg)
            mock_greet.assert_not_called()
            self.node.pub_output_pcm.publish.assert_not_called()

    def test_face_and_gaze_detected_alone_does_not_trigger_speech(self):
        """Face & gaze detection array updates world model and attention but produces NO speech."""
        faces_msg = String()
        faces_msg.data = json.dumps([{
            "name": "Baran",
            "recognized_name": "Baran",
            "is_known": True,
            "distance_m": 1.2,
            "looking_at_robot": True,
            "yaw_deg": 5.0,
        }])
        self.node._on_faces(faces_msg)
        self.node.pub_output_pcm.publish.assert_not_called()
        self.node.local_gemma_client.stream.assert_not_called()

    def test_evet_without_wake_drops_turn_zero_llm_zero_tts(self):
        """Saying 'Evet.' without a wake phrase when no active session drops turn immediately."""
        self.node.session._is_active = False
        self.node._validate_stt_transcript = MagicMock(return_value=("Evet.", {"vad_confidence": 0.9, "rms": 300}))
        
        fake_audio = [b"\x00\x01" * 1600] * 15
        self.node._process_fallback_turn(audio_chunks=fake_audio)

        self.node.local_gemma_client.stream.assert_not_called()
        self.node.tts_router.synthesize.assert_not_called()
        self.node.pub_output_pcm.publish.assert_not_called()
        self.assertFalse(self.node._last_explicit_user_turn)

    def test_valid_wake_and_query_admits_turn_and_speaks(self):
        """Valid wake word + user query ('Astro ben şu anda ne yapıyorum?') admits turn and allows speech."""
        self.node.session._is_active = False
        self.node._validate_stt_transcript = MagicMock(
            return_value=("Astro ben şu anda ne yapıyorum?", {"vad_confidence": 0.9, "rms": 300})
        )
        fake_audio = [b"\x00\x01" * 1600] * 15
        
        self.node._process_fallback_turn(audio_chunks=fake_audio)

        # Turn admitted
        self.assertTrue(self.node._last_explicit_user_turn)
        self.node.local_gemma_client.stream.assert_called_once()
        self.node.tts_router.synthesize.assert_called()

    def test_hard_gate_blocks_when_should_speak_false(self):
        """Even with explicit user turn, if should_speak is False, LLM and TTS are hard blocked."""
        gated_decision = SocialDecision(
            should_speak=False,
            initiative_reason="GATE_OBSERVING_test",
            response_strategy=["Sessiz kal"],
            gate_mode="OBSERVING",
        )
        self.node._last_social_decision = gated_decision
        self.node._build_current_system_prompt = MagicMock(return_value="System Prompt")

        self.node._process_fallback_turn(direct_text="Astro merhaba")

        self.node.local_gemma_client.stream.assert_not_called()
        self.node.tts_router.synthesize.assert_not_called()
        self.node.pub_output_pcm.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
