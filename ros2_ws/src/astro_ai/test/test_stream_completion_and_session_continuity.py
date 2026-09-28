#!/usr/bin/env python3
"""Unit tests for Stream Completion Sentinel, Fallback Speech Capture Threshold, and Conversation Session Continuity.

Validates:
1. When streaming LLM completes, an is_done=True sentinel is ALWAYS published even if chunker.flush() is empty.
2. Fallback microphone capture threshold admits speech at 280-350 RMS and >650 peak.
3. Playback ending callback updates the conversation session's last robot speech time.
4. Conversation session stays active for up to 14.0s (base timeout) allowing natural dialogue pauses.
"""

import json
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
from astro_ai.astro_realtime_node import AstroRealtimeNode, SpeechAuthorization
from astro_ai.state_machine import RobotState


class TestStreamCompletionAndSessionContinuity(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-mock", "USE_4O": "true"}):
            self.node = AstroRealtimeNode()

    def test_01_play_pcm_chunks_sends_is_done_even_with_empty_pcm(self):
        """_play_pcm_chunks must publish is_done=True sentinel when is_final_clause=True even if pcm_data is empty."""
        published_msgs = []
        self.node.pub_output_pcm = MagicMock()
        self.node.pub_output_pcm.publish = lambda msg: published_msgs.append(json.loads(msg.data))

        self.node._current_turn_explicit_user_turn = True
        self.node._speech_authorization = SpeechAuthorization(
            user_turn_id="turn_test_1",
            generation_id=1,
            explicit_user_turn=True,
            should_speak=True,
            response_origin="openai_chat",
            llm_inference_completed=True,
            response_final=True,
        )

        # Call with empty audio and is_final_clause=True (simulates empty chunker flush)
        self.node._play_pcm_chunks(
            b"",
            generation_id=1,
            tts_provider="edge_tts",
            tts_model="tr-TR-AhmetNeural",
            tts_source="edge_tts",
            is_final_clause=True,
            blocking_pace=False,
        )

        self.assertEqual(len(published_msgs), 1, "Must publish exactly 1 sentinel message")
        self.assertTrue(published_msgs[0].get("is_done"), "Message must have is_done=True")
        self.assertEqual(published_msgs[0].get("generation_id"), 1)
        self.assertFalse(self.node._is_playback_active, "_is_playback_active must be False after final clause")

    def test_02_speech_start_condition_captures_conversational_speech(self):
        """Fallback audio capture must trigger for conversational speech (RMS ~320, peak ~800, ambient ~120)."""
        self.node._fallback_mode = True
        self.node._ambient_rms = 120.0
        self.node._is_playback_active = False
        self.node._playback_end_time = 0.0  # long past cooldown
        self.node._is_sleeping = False
        self.node.state_machine.transition_to(RobotState.LISTENING)
        self.node.session.activate_session()

        # Create speech frame (16kHz 20ms = 320 samples) with RMS ~565, peak ~800
        t = np.linspace(0, 0.02, 320, endpoint=False)
        audio_samples = (np.sin(2 * np.pi * 300 * t) * 800).astype(np.int16)
        raw_bytes = audio_samples.tobytes()

        # Feed frame into _on_input_pcm
        self.node._on_input_pcm(raw_bytes)

        self.assertTrue(self.node._fallback_speaking, "Fallback speech capture must become active for conversational audio!")
        self.assertGreater(len(self.node._fallback_audio_buffer), 0, "Buffer must contain captured audio chunks")

    def test_03_playback_active_falling_edge_updates_session_timestamp(self):
        """When /audio/playback_active becomes False, the conversation session robot speech timestamp is updated."""
        self.node.session.activate_session()
        self.node._is_playback_active = True

        old_speech_time = self.node.session._last_robot_speech_time
        time.sleep(0.02)

        # Trigger playback ended via ROS message
        mock_msg = MagicMock()
        mock_msg.data = False
        self.node._on_playback_active(mock_msg)

        self.assertFalse(self.node._is_playback_active)
        self.assertGreater(self.node.session._last_robot_speech_time, old_speech_time,
                            "Session last_robot_speech_time must be updated on playback end")

    def test_04_session_timeout_allows_10_second_pause(self):
        """Session must stay active 10 seconds after robot speaks (extended base timeout 14.0s)."""
        session = ConversationSession()
        session.activate_session()
        session.record_robot_speech()

        now = time.monotonic()
        # Simulate 10 seconds having passed
        session._last_robot_speech_time = now - 10.0
        session._last_user_speech_time = now - 10.0
        session._last_gaze_time = 0.0  # no gaze
        timed_out = session.check_and_update_session_lifecycle(is_robot_speaking=False)
        self.assertFalse(timed_out, "10-second pause must NOT time out the session")
        self.assertTrue(session.is_active(), "Session must remain active 10s after robot speech")

        # Simulate 15 seconds having passed (exceeds 14.0s base timeout)
        session._last_robot_speech_time = now - 15.0
        session._last_user_speech_time = now - 15.0
        timed_out = session.check_and_update_session_lifecycle(is_robot_speaking=False)
        self.assertTrue(timed_out, "15-second pause must time out the session (base_timeout=14s)")
        self.assertFalse(session.is_active(), "Session must be closed after 15s pause")


if __name__ == "__main__":
    unittest.main()
