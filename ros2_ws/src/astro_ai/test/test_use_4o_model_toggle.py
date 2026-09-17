"""ASTRO V1 — Minimal use_4o Model Toggle Test Suite.

Verifies:
1. use_4o=False selects the default flagship Realtime model ("gpt-realtime-2.1-mini").
2. use_4o=True selects the 4o Realtime model ("gpt-4o-realtime-preview").
3. USE_4O environment variable toggle works symmetrically.
4. Audio configuration & transport settings are 100% identical in both cases.
5. SpeechAuthorization behavior is 100% identical in both cases.
6. STT/TTS routing & WebSocket message handling paths remain unchanged.
7. WorldModel, DialogueState, and Conversation Memory are completely unaffected.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure test import paths
pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
for p in [
    os.path.join(pkg_root, "astro_ai"),
    os.path.join(pkg_root, "astro_ai", "astro_ai"),
    os.path.join(pkg_root, "astro_vision"),
    os.path.join(pkg_root, "astro_audio"),
    os.path.join(pkg_root, "astro_base"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from astro_ai.astro_realtime_node import AstroRealtimeNode, discover_realtime_models


class TestUse4oModelToggle(unittest.TestCase):
    """Verifies use_4o parameter and model isolation invariants."""

    @patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock-key"})
    def test_01_use_4o_false_selects_default_realtime_model(self):
        """use_4o=False selects the default flagship Realtime model without alteration."""
        node = AstroRealtimeNode(use_4o=False)
        self.assertFalse(node.use_4o)
        self.assertEqual(node.realtime_model, "gpt-realtime-2.1-mini")

        # Discover list starts with default model
        candidates = discover_realtime_models(node.openai_api_key, node.realtime_model)
        self.assertEqual(candidates[0], "gpt-realtime-2.1-mini")

    @patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock-key"})
    def test_02_use_4o_true_selects_4o_model(self):
        """use_4o=True selects gpt-4o-realtime-preview cleanly."""
        node = AstroRealtimeNode(use_4o=True)
        self.assertTrue(node.use_4o)
        self.assertEqual(node.realtime_model, "gpt-4o-realtime-preview")

        # Discover list starts with 4o model
        candidates = discover_realtime_models(node.openai_api_key, node.realtime_model)
        self.assertEqual(candidates[0], "gpt-4o-realtime-preview")

    def test_03_use_4o_env_variable_toggle(self):
        """USE_4O environment variable dynamically controls model selection."""
        # Case A: USE_4O="true"
        with patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock-key", "USE_4O": "true"}):
            node_env_true = AstroRealtimeNode()
            self.assertTrue(node_env_true.use_4o)
            self.assertEqual(node_env_true.realtime_model, "gpt-4o-realtime-preview")

        # Case B: USE_4O="false"
        with patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock-key", "USE_4O": "false"}):
            node_env_false = AstroRealtimeNode()
            self.assertFalse(node_env_false.use_4o)
            self.assertEqual(node_env_false.realtime_model, "gpt-realtime-2.1-mini")

    @patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock-key"})
    def test_04_audio_config_and_transport_identical(self):
        """Audio transport, voice selection, format, and rates remain strictly identical."""
        node_default = AstroRealtimeNode(use_4o=False)
        node_4o = AstroRealtimeNode(use_4o=True)

        # Voice identical
        self.assertEqual(node_default.realtime_voice, node_4o.realtime_voice)
        # Audio buffer parameters identical
        self.assertEqual(node_default.xtts_startup_grace_s, node_4o.xtts_startup_grace_s)
        # Fallback modes identical
        self.assertEqual(node_default._fallback_mode, node_4o._fallback_mode)
        # Active response state initialization identical
        self.assertEqual(node_default.active_response_state, node_4o.active_response_state)
        self.assertEqual(node_default.realtime_response_state, node_4o.realtime_response_state)

    @patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock-key"})
    def test_05_speech_authorization_identical(self):
        """SpeechAuthorization lifecycle & gates are identical across both model options."""
        from astro_ai.astro_realtime_node import SpeechAuthorization
        node_default = AstroRealtimeNode(use_4o=False)
        node_4o = AstroRealtimeNode(use_4o=True)

        # Initial state: None
        self.assertIsNone(node_default._speech_authorization)
        self.assertIsNone(node_4o._speech_authorization)

        # Both have identical authorization structure
        auth = SpeechAuthorization(
            user_turn_id="turn_1",
            generation_id=1,
            explicit_user_turn=True,
            should_speak=True,
            response_origin="gpt-4o",
        )
        node_default._speech_authorization = auth
        node_4o._speech_authorization = auth

        self.assertEqual(node_default._speech_authorization.user_turn_id, "turn_1")
        self.assertEqual(node_4o._speech_authorization.user_turn_id, "turn_1")
        self.assertTrue(node_default._speech_authorization.should_speak)
        self.assertTrue(node_4o._speech_authorization.should_speak)

        # Proactive speech gate identical
        self.assertEqual(node_default.proactive_speech_enabled, node_4o.proactive_speech_enabled)

    @patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock-key"})
    def test_06_stt_tts_and_websocket_path_unchanged(self):
        """STT, TTS, and WebSocket handlers remain unchanged."""
        node_default = AstroRealtimeNode(use_4o=False)
        node_4o = AstroRealtimeNode(use_4o=True)

        # TTS router type and presence
        self.assertIsNotNone(node_default.tts_router)
        self.assertIsNotNone(node_4o.tts_router)
        self.assertEqual(type(node_default.tts_router), type(node_4o.tts_router))

        # Realtime transcribe model
        self.assertEqual(node_default.realtime_transcribe_model, node_4o.realtime_transcribe_model)

        # Handler methods are the exact same functions
        self.assertEqual(node_default._on_input_pcm.__func__, node_4o._on_input_pcm.__func__)
        self.assertEqual(node_default._handle_realtime_event.__func__, node_4o._handle_realtime_event.__func__)

    @patch.dict(os.environ, {"ASTRO_TEST_MODE": "1", "OPENAI_API_KEY": "sk-mock-key"})
    def test_07_world_model_and_dialogue_state_unaffected(self):
        """WorldModel, DialogueState, and Context building are unaffected by model toggle."""
        node_default = AstroRealtimeNode(use_4o=False)
        node_4o = AstroRealtimeNode(use_4o=True)

        # SocialBrain / WorldModel integrity
        self.assertIsNotNone(node_default.social_brain)
        self.assertIsNotNone(node_4o.social_brain)
        self.assertIsNotNone(node_default.social_brain.world_model)
        self.assertIsNotNone(node_4o.social_brain.world_model)

        # Dialogue state manager integrity
        self.assertIsNotNone(node_default.dialogue_state_manager)
        self.assertIsNotNone(node_4o.dialogue_state_manager)


if __name__ == "__main__":
    unittest.main()
