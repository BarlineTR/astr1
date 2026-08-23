#!/usr/bin/env python3
"""ASTRO V1 — session.update payload üretici birim testleri."""

import os
import sys
import unittest

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))

from astro_ai.realtime.session_config import build_session_update, build_turn_detection


class TestTurnDetectionDefaults(unittest.TestCase):
    def test_defaults_are_server_vad_500ms(self):
        td = build_turn_detection(env={})
        self.assertEqual(td["type"], "server_vad")
        self.assertEqual(td["threshold"], 0.70)
        self.assertEqual(td["prefix_padding_ms"], 300)
        self.assertEqual(td["silence_duration_ms"], 500)

    def test_create_response_is_true(self):
        """Yanıt üretimi sunucunun: manuel response.create kaldırıldı."""
        self.assertIs(build_turn_detection(env={})["create_response"], True)

    def test_interrupt_response_is_true(self):
        """Kesme otoritesi sunucuda: bab0512 regresyonunun onarımı."""
        self.assertIs(build_turn_detection(env={})["interrupt_response"], True)


class TestTurnDetectionOverrides(unittest.TestCase):
    def test_env_overrides_server_vad_fields(self):
        td = build_turn_detection(env={
            "REALTIME_VAD_THRESHOLD": "0.55",
            "REALTIME_VAD_PREFIX_MS": "250",
            "REALTIME_VAD_SILENCE_MS": "400",
        })
        self.assertEqual(td["threshold"], 0.55)
        self.assertEqual(td["prefix_padding_ms"], 250)
        self.assertEqual(td["silence_duration_ms"], 400)

    def test_interrupt_response_can_be_disabled(self):
        td = build_turn_detection(env={"REALTIME_INTERRUPT_RESPONSE": "false"})
        self.assertIs(td["interrupt_response"], False)

    def test_semantic_vad_shape(self):
        td = build_turn_detection(env={
            "REALTIME_VAD_TYPE": "semantic_vad",
            "REALTIME_VAD_EAGERNESS": "medium",
        })
        self.assertEqual(td["type"], "semantic_vad")
        self.assertEqual(td["eagerness"], "medium")
        self.assertIs(td["create_response"], True)
        self.assertIs(td["interrupt_response"], True)
        # semantic_vad server_vad alanlarını taşımaz
        self.assertNotIn("threshold", td)
        self.assertNotIn("silence_duration_ms", td)
        self.assertNotIn("prefix_padding_ms", td)

    def test_semantic_vad_eagerness_defaults_to_auto(self):
        td = build_turn_detection(env={"REALTIME_VAD_TYPE": "semantic_vad"})
        self.assertEqual(td["eagerness"], "auto")

    def test_unknown_vad_type_falls_back_to_server_vad(self):
        td = build_turn_detection(env={"REALTIME_VAD_TYPE": "magic_vad"})
        self.assertEqual(td["type"], "server_vad")

    def test_malformed_numeric_falls_back_to_default(self):
        td = build_turn_detection(env={"REALTIME_VAD_SILENCE_MS": "abc"})
        self.assertEqual(td["silence_duration_ms"], 500)


class TestSessionUpdateShape(unittest.TestCase):
    def setUp(self):
        self.payload = build_session_update(
            instructions="Sen ASTRO'sun.",
            voice="echo",
            tools=[{"type": "function", "name": "noop", "parameters": {}}],
            env={},
        )

    def test_top_level_shape(self):
        self.assertEqual(self.payload["type"], "session.update")
        self.assertEqual(self.payload["session"]["type"], "realtime")
        self.assertEqual(self.payload["session"]["instructions"], "Sen ASTRO'sun.")

    def test_turn_detection_nesting_path(self):
        """Doğrulanmış yol: session.audio.input.turn_detection"""
        td = self.payload["session"]["audio"]["input"]["turn_detection"]
        self.assertEqual(td["type"], "server_vad")

    def test_voice_and_transcription(self):
        audio = self.payload["session"]["audio"]
        self.assertEqual(audio["output"]["voice"], "echo")
        self.assertEqual(audio["input"]["transcription"]["model"], "gpt-live-transcribe")
        self.assertEqual(audio["input"]["transcription"]["language"], "tr")

    def test_tools_passed_through(self):
        self.assertEqual(len(self.payload["session"]["tools"]), 1)
        self.assertEqual(self.payload["session"]["tools"][0]["name"], "noop")

    def test_is_json_serializable(self):
        import json
        json.dumps(self.payload)


if __name__ == "__main__":
    unittest.main()
