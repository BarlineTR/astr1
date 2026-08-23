#!/usr/bin/env python3
"""ASTRO V1 — Ses sahipliği ve cascaded hat sökümü statik testleri.

Bu testler kaynağı metin olarak okur. Sebep: "kimse bu topic'e abone
olmamalı" ve "bu kod yolu kalmamalı" gibi mimari değişmezler, çalışma zamanı
mock'larıyla değil kaynağın kendisiyle kanıtlanır.
"""

import os
import unittest

SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
REALTIME_NODE = os.path.join(SRC, "astro_ai", "astro_ai", "astro_realtime_node.py")
TTS_NODE = os.path.join(SRC, "astro_audio", "astro_audio", "tts_node.py")
AUDIO_STREAM = os.path.join(SRC, "astro_audio", "astro_audio", "audio_stream_node.py")


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class TestCascadedPathRemoved(unittest.TestCase):
    def setUp(self):
        self.src = read(REALTIME_NODE)

    def test_no_realtime_request_subscription(self):
        self.assertNotIn("/tts/realtime_request", self.src)

    def test_no_turn_request_handler(self):
        self.assertNotIn("_on_realtime_turn_request", self.src)

    def test_no_dispatch_turn(self):
        self.assertNotIn("_dispatch_turn", self.src)

    def test_no_text_injection_prompt(self):
        """Realtime'a 'şunu seslendir' diye metin enjekte eden yol kalmamalı."""
        self.assertNotIn("Lütfen şu cevabı tam olarak seslendir", self.src)

    def test_no_audio_delta_watchdog(self):
        self.assertNotIn("_check_audio_delta_timeout", self.src)

    def test_no_turn_queue(self):
        self.assertNotIn("_turn_queue", self.src)


class TestAiBrainPreserved(unittest.TestCase):
    """ai_brain_node silinmez — cascaded mod ve gelecekteki fallback için durur."""

    def test_ai_brain_node_file_exists(self):
        self.assertTrue(
            os.path.isfile(os.path.join(SRC, "astro_ai", "astro_ai", "ai_brain_node.py"))
        )

    def test_tts_node_file_exists(self):
        self.assertTrue(os.path.isfile(TTS_NODE))


class TestSinglePlaybackOwner(unittest.TestCase):
    """Task 5'te yeşile döner."""

    def test_only_audio_stream_node_subscribes_to_output_pcm(self):
        subscribers = []
        for path in (TTS_NODE, AUDIO_STREAM):
            src = read(path)
            for line in src.splitlines():
                if "create_subscription" in line and "realtime_output_pcm" in line:
                    subscribers.append(os.path.basename(path))
        self.assertEqual(subscribers, ["audio_stream_node.py"])

    def test_tts_node_has_no_realtime_pcm_handler(self):
        self.assertNotIn("_on_realtime_output_pcm", read(TTS_NODE))


if __name__ == "__main__":
    unittest.main()
