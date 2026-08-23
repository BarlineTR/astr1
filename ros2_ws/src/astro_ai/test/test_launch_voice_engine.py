#!/usr/bin/env python3
"""ASTRO V1 — voice_engine launch ayrımı testleri.

Kapı 1'in ses sahipliği kanıtı: realtime modunda donanıma dokunan eski
düğümlerin hiç başlatılmadığını launch açıklamasından doğrular.
"""

import os
import unittest

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BRINGUP = os.path.join(SRC, "astro_bringup", "launch", "bringup.launch.py")

FORBIDDEN_IN_REALTIME = (
    "audio_capture_node",
    "speech_recognition_node",
    "tts_node",
    "ai_brain_node",
)


def read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class TestVoiceEngineArgument(unittest.TestCase):
    def setUp(self):
        self.src = read(BRINGUP)

    def test_voice_engine_argument_declared(self):
        self.assertIn('"voice_engine"', self.src)

    def test_default_is_realtime(self):
        # DeclareLaunchArgument bloğunu ara: "voice_engine" ilk olarak
        # LaunchConfiguration satırında geçtiği için oradan pencere almak yanıltır.
        idx = self.src.index('DeclareLaunchArgument(\n                "voice_engine"')
        window = self.src[idx: idx + 400]
        self.assertIn('default_value="realtime"', window)

    def test_cascaded_audio_gated_on_realtime(self):
        self.assertIn("is_cascaded_audio", self.src)
        self.assertIn('"enable_audio": is_cascaded_audio', self.src)

    def test_cascaded_ai_gated_on_realtime(self):
        self.assertIn("is_cascaded_ai", self.src)
        self.assertIn('"enable_ai": is_cascaded_ai', self.src)

    def test_realtime_sensors_gated_on_voice_engine(self):
        """realtime_sensors yalnızca use_realtime'a değil, voice_engine'e de bağlı olmalı."""
        self.assertIn("realtime_sensors.launch.py", self.src)
        idx = self.src.index("realtime_sensors.launch.py")
        window = self.src[idx: idx + 400]
        self.assertIn("is_realtime", window)


class TestRealtimeLaunchComposition(unittest.TestCase):
    """realtime_sensors yalnızca tek ses sahibini ve realtime düğümünü başlatır."""

    def setUp(self):
        self.src = read(
            os.path.join(SRC, "astro_bringup", "launch", "realtime_sensors.launch.py")
        )

    def test_starts_audio_stream_node(self):
        self.assertIn('executable="audio_stream_node"', self.src)

    def test_starts_realtime_node(self):
        self.assertIn('executable="astro_realtime_node"', self.src)

    def test_starts_no_legacy_audio_nodes(self):
        for name in FORBIDDEN_IN_REALTIME:
            self.assertNotIn(f'executable="{name}"', self.src)


class TestAudioLaunchIsCascadedOnly(unittest.TestCase):
    """audio.launch.py yalnızca cascaded modda include edilir; içeriği değişmez."""

    def test_audio_launch_still_defines_cascaded_nodes(self):
        src = read(os.path.join(SRC, "astro_audio", "launch", "audio.launch.py"))
        self.assertIn('executable="audio_capture_node"', src)
        self.assertIn('executable="speech_recognition_node"', src)
        self.assertIn('executable="tts_node"', src)


if __name__ == "__main__":
    unittest.main()
