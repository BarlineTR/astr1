#!/usr/bin/env python3
"""Unit tests for Self-Talk & Echo Loop Prevention, and Multimodal Perception Routing.

Validates:
1. ConversationSession has updated timeouts (7.0s base, 4.0s gaze).
2. Playback / Cooldown guard drops mic frames and purges fallback buffer.
3. Acoustic loud noise does not wake Astro from sleep without wake words.
4. STT validator rejects self-voice reflections and echo cooldown leaks.
5. Contextual queries ('konumu değiştirdim ne yapıyorum') pass through to LLM.
6. Multimodal perception block is injected into system prompt.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))

os.environ["ASTRO_TEST_MODE"] = "1"
os.environ["ASTRO_MOCK_AUDIO"] = "1"

from astro_ai.conversation_session import ConversationSession
from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.contracts.person_state import UnifiedPersonState


class TestSelfTalkAndPerceptionGuard(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-mock", "USE_4O": "true"}):
            self.node = AstroRealtimeNode()

    def test_01_conversation_session_timeouts(self):
        """Default timeouts must be 14.0s base and 5.0s gaze."""
        session = ConversationSession()
        self.assertEqual(session.base_timeout_s, 14.0)
        self.assertEqual(session.gaze_extension_s, 5.0)
        self.assertEqual(self.node.session.base_timeout_s, 14.0)
        self.assertEqual(self.node.session.gaze_extension_s, 5.0)

    def test_02_playback_and_echo_cooldown_drops_fallback_buffer(self):
        """Microphone PCM during active playback or cooldown must NOT accumulate in fallback buffer."""
        dummy_pcm = b"\x10\x00" * 320  # 640 bytes 16kHz
        self.node._is_playback_active = True
        self.node._fallback_audio_buffer = [dummy_pcm]

        # Call _on_input_pcm during playback
        self.node._on_input_pcm(dummy_pcm)
        self.assertEqual(len(self.node._fallback_audio_buffer), 0, "Playback must clear and reject fallback audio buffer!")

        # Call during echo cooldown
        self.node._is_playback_active = False
        self.node._playback_end_time = time.monotonic()  # just ended
        self.node.echo_mute_cooldown_s = 1.0
        self.node._fallback_audio_buffer = [dummy_pcm]

        self.node._on_input_pcm(dummy_pcm)
        self.assertEqual(len(self.node._fallback_audio_buffer), 0, "Echo cooldown must clear and reject fallback audio buffer!")

    def test_03_loud_noise_does_not_wake_robot(self):
        """Loud ambient noise alone must not transition robot out of sleep."""
        self.node._is_sleeping = True
        self.node._node_start_time = time.monotonic() - 10.0  # running for 10s

        # Generate loud noise frames (RMS > 500)
        loud_pcm = (np.ones(320, dtype=np.int16) * 3000).tobytes()
        for _ in range(10):
            self.node._on_input_pcm(loud_pcm)

        self.assertTrue(self.node._is_sleeping, "Robot must NOT wake up on acoustic noise without wake words!")

    def test_04_stt_validator_rejects_self_voice_text_overlap(self):
        """STT transcripts echoing robot's recent phrases must be rejected as self_voice."""
        self.node._recent_robot_phrases = ["sesime dön yüzüme bak durdum merkez"]
        clean_pcm = (np.ones(16000, dtype=np.int16) * 800).tobytes()  # 1 sec audio

        # Whispered echo of robot speech
        transcript, meta = self.node._validate_stt_transcript(
            transcript="sesime dön yüzüme bak durdum merkez",
            raw_pcm=clean_pcm,
            is_playback_active=False,
            is_echo_cooldown=False,
        )
        self.assertTrue(meta["stt_rejected"])
        self.assertEqual(meta["stt_reject_reason"], "self_voice")

    def test_05_stt_validator_rejects_echo_cooldown_leak(self):
        """Transcripts received during echo cooldown with moderate correlation must be rejected."""
        self.node._recent_robot_phrases = ["ben buradayım dinliyorum o zaman seni"]
        clean_pcm = (np.ones(16000, dtype=np.int16) * 500).tobytes()

        transcript, meta = self.node._validate_stt_transcript(
            transcript="dinliyorum o zaman",
            raw_pcm=clean_pcm,
            is_playback_active=False,
            is_echo_cooldown=True,
        )
        self.assertTrue(meta["stt_rejected"])
        self.assertIn(meta["stt_reject_reason"], ("self_voice", "echo_cooldown_leak"))

    def test_06_contextual_activity_query_bypasses_deterministic_regex(self):
        """'Astro konumu değiştirdim. Peki şu anda ne yapıyorum ben?' must route to LLM."""
        user_query = "Astro konumu değiştirdim. Peki şu anda ne yapıyorum ben?"
        is_activity, reply = self.node._is_activity_query(user_query, prefer_llm=True)
        self.assertFalse(is_activity, "Contextual state change query must not be intercepted by static regex!")

    def test_07_stale_camera_query_passes_to_llm_when_available(self):
        """When camera is STALE, query must pass to LLM to allow natural dialogue rather than robotic error string."""
        self.node._get_current_visual_grounding = lambda: {
            "visual_state": "STALE",
            "visual_camera_available": True,
            "visual_person_detected": False,
            "visual_distance": None,
        }
        is_activity, reply = self.node._is_activity_query("Ben ne yapıyorum?", prefer_llm=True)
        self.assertFalse(is_activity, "When LLM is active and camera is STALE, do not return robotic error string!")

    def test_08_system_prompt_contains_multimodal_perception(self):
        """System prompt must contain rich multimodal perception block."""
        prompt = self.node._build_current_system_prompt(explicit_user_turn=True)
        self.assertIn("GÖRSEL VE MEKÂNSAL FARKINDALIK BİLGİSİ", prompt)
        self.assertIn("Kafa Açısı", prompt)
        self.assertIn("ÖNEMLİ ALGI TALİMATI", prompt)


if __name__ == "__main__":
    unittest.main()
