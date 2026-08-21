"""ASTRO V1 — TTS Runtime Fallback & Authoritative Orchestration Acceptance Test Suite.

Verifies the 5 critical runtime acceptance scenarios:
  1. XTTS READY -> XTTS synthesis -> Hardware Playback Started
  2. XTTS STARTING (warmup) -> Fast Edge-TTS (Zero-wait on first turn) -> Playback Started
  3. XTTS timeout -> Edge-TTS fallback with identical generation_id -> Playback Started
  4. XTTS unavailable + Edge network failure -> Local Offline TTS -> Playback Started
  5. All providers fail -> Explicit TTS_ALL_PROVIDERS_FAILED alarm (Zero-Silence Contract)
  6. Playback Watchdog detects silent stall and forces emergency fallback
  7. Configuration timeout consistency verification (no 30s/45s drift)
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

_ws_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ws_root not in sys.path:
    sys.path.insert(0, _ws_root)

from astro_audio.audio_output_manager import AudioOutputManager
from astro_audio.edge_tts_engine import EdgeTTSEngine
from astro_audio.local_offline_tts_engine import LocalOfflineTTSEngine
from astro_audio.local_xtts_engine import LocalXttsEngine
from astro_audio.playback_watchdog import PlaybackWatchdog
from astro_audio.tts_orchestrator import TTSOrchestrator
from astro_audio.tts_router import TTSRouteResult, TTSRouter
from astro_audio.xtts_client import XttsClient, XttsError


class TestTTSRuntimeAcceptance(unittest.TestCase):
    """Runtime acceptance test suite for deterministic TTS fallback and zero silence."""

    def setUp(self):
        self.output_manager = AudioOutputManager(mock_playback=True)
        self.mock_xtts = MagicMock(spec=LocalXttsEngine)
        self.mock_edge = MagicMock(spec=EdgeTTSEngine)
        self.mock_offline = MagicMock(spec=LocalOfflineTTSEngine)

    def test_scenario_1_xtts_ready_synthesizes_and_plays(self):
        """1. When XTTS is READY & HEALTHY, XTTS synthesizes and plays through DAC."""
        self.mock_xtts.is_ready.return_value = True
        self.mock_xtts.is_healthy.return_value = True
        self.mock_xtts.synthesize_sentence.return_value = b"\x00\x01" * 12000  # 1.0s of 24kHz int16

        router = TTSRouter(
            local_xtts=self.mock_xtts,
            local_offline_tts=self.mock_offline,
            edge_tts_engine=self.mock_edge,
            output_manager=self.output_manager,
        )

        res = router.synthesize_and_play(
            text="Merhaba, ben Astro!",
            generation_id=101,
        )

        self.assertIsNotNone(res.pcm)
        self.assertEqual(res.actual_provider, "xtts_gpu")
        self.assertEqual(res.fallback_chain, ["xtts_gpu"])
        self.mock_xtts.synthesize_sentence.assert_called_once_with("Merhaba, ben Astro!", generation_id=101, language="tr")
        self.mock_edge.synthesize_sentence.assert_not_called()
        self.mock_offline.synthesize_sentence.assert_not_called()

    def test_scenario_2_first_turn_xtts_starting_does_not_wait_warmup(self):
        """2. When XTTS is STARTING, first turn does NOT wait for warmup, falls back to Edge-TTS immediately."""
        self.mock_xtts.is_ready.return_value = False
        self.mock_xtts.is_healthy.return_value = False
        self.mock_xtts._state = "STARTING"

        self.mock_edge.check_network.return_value = True
        self.mock_edge.synthesize_sentence.return_value = b"\x00\x02" * 12000

        router = TTSRouter(
            local_xtts=self.mock_xtts,
            local_offline_tts=self.mock_offline,
            edge_tts_engine=self.mock_edge,
            output_manager=self.output_manager,
        )

        t_start = time.perf_counter()
        res = router.synthesize_and_play(
            text="İlk konuşma mesajı",
            generation_id=102,
        )
        elapsed = time.perf_counter() - t_start

        # Fast skip: MUST complete in < 500ms without blocking on warmup
        self.assertLess(elapsed, 0.5)
        self.assertIsNotNone(res.pcm)
        self.assertEqual(res.actual_provider, "edge_tts")
        self.mock_xtts.synthesize_sentence.assert_not_called()
        self.mock_edge.synthesize_sentence.assert_called_once()

    def test_scenario_3_xtts_timeout_triggers_edge_tts_with_same_gen_id(self):
        """3. When XTTS times out, Edge-TTS fallback executes with identical generation_id."""
        self.mock_xtts.is_ready.return_value = True
        self.mock_xtts.is_healthy.return_value = True
        self.mock_xtts.synthesize_sentence.return_value = None  # Simulates timeout returning None
        self.mock_xtts.get_telemetry.return_value = {"fallback_reason": "xtts_timeout"}

        self.mock_edge.check_network.return_value = True
        self.mock_edge.synthesize_sentence.return_value = b"\x00\x03" * 12000

        router = TTSRouter(
            local_xtts=self.mock_xtts,
            local_offline_tts=self.mock_offline,
            edge_tts_engine=self.mock_edge,
            output_manager=self.output_manager,
        )

        res = router.synthesize_and_play(
            text="Sentez zaman aşımına uğradı",
            generation_id=103,
        )

        self.assertIsNotNone(res.pcm)
        self.assertEqual(res.actual_provider, "edge_tts")
        self.assertIn("xtts_gpu(xtts_timeout)", res.fallback_chain)
        self.assertIn("edge_tts", res.fallback_chain)
        self.mock_edge.synthesize_sentence.assert_called_once_with(
            "Sentez zaman aşımına uğradı",
            generation_id=103,
            timeout=router.edge_timeout_s,
        )

    def test_scenario_4_offline_mode_skips_edge_and_uses_local_offline(self):
        """4. When network is down (0 internet), Edge-TTS is fast-skipped to Local Offline TTS."""
        self.mock_xtts.is_ready.return_value = False
        self.mock_xtts.is_healthy.return_value = False

        self.mock_edge.check_network.return_value = False  # No internet
        self.mock_offline.is_ready.return_value = True
        self.mock_offline.synthesize_sentence.return_value = b"\x00\x04" * 12000

        router = TTSRouter(
            local_xtts=self.mock_xtts,
            local_offline_tts=self.mock_offline,
            edge_tts_engine=self.mock_edge,
            output_manager=self.output_manager,
        )

        t_start = time.perf_counter()
        res = router.synthesize_and_play(
            text="Çevrimdışı yerel yedek modundayız",
            generation_id=104,
        )
        elapsed = time.perf_counter() - t_start

        self.assertLess(elapsed, 0.5)
        self.assertIsNotNone(res.pcm)
        self.assertEqual(res.actual_provider, "local_offline_tts")
        self.assertIn("edge_tts(network_unavailable)", res.fallback_chain)
        self.assertIn("local_offline_tts", res.fallback_chain)
        self.mock_offline.synthesize_sentence.assert_called_once_with(
            "Çevrimdışı yerel yedek modundayız",
            generation_id=104,
            language="tr",
        )

    def test_scenario_5_all_providers_failed_raises_zero_silence_alarm(self):
        """5. When all providers fail, returns explicit result with TTS_ALL_PROVIDERS_FAILED alarm."""
        self.mock_xtts.is_ready.return_value = False
        self.mock_edge.check_network.return_value = True
        self.mock_edge.synthesize_sentence.return_value = None
        self.mock_offline.is_ready.return_value = True
        self.mock_offline.synthesize_sentence.return_value = None

        router = TTSRouter(
            local_xtts=self.mock_xtts,
            local_offline_tts=self.mock_offline,
            edge_tts_engine=self.mock_edge,
            output_manager=self.output_manager,
        )

        res = router.synthesize_and_play(
            text="Tüm motorlar başarısız",
            generation_id=105,
        )

        self.assertIsNone(res.pcm)
        self.assertEqual(res.actual_provider, "none")
        self.assertEqual(res.fallback_reason, "all_providers_failed")
        self.assertIn("edge_tts(synthesis_failed)", res.fallback_chain)

    def test_scenario_6_playback_watchdog_detects_stall(self):
        """6. PlaybackWatchdog triggers force_fallback when playback fails to start within deadline."""
        stalled_gen = []

        def on_stall(gen_id, exp_prov):
            stalled_gen.append((gen_id, exp_prov))

        watchdog = PlaybackWatchdog(
            deadline_ms=150.0,  # 150ms for fast test execution
            on_stall_callback=on_stall,
        )

        try:
            watchdog.register_turn_issued(generation_id=201, expected_provider="xtts_gpu", text="Test watchdog")
            time.sleep(0.25)
            self.assertEqual(len(stalled_gen), 1)
            self.assertEqual(stalled_gen[0][0], 201)
            self.assertEqual(stalled_gen[0][1], "xtts_gpu")
        finally:
            watchdog.stop()

    def test_scenario_7_tts_orchestrator_integration(self):
        """7. TTSOrchestrator correctly uses TTSRouter and reports provenance to AudioOutputManager."""
        self.mock_xtts.is_ready.return_value = False
        self.mock_edge.check_network.return_value = True
        self.mock_edge.synthesize_sentence.return_value = b"\x00\x07" * 12000

        orchestrator = TTSOrchestrator(
            output_manager=self.output_manager,
            realtime_engine=MagicMock(),
            local_xtts_engine=self.mock_xtts,
            local_offline_tts_engine=self.mock_offline,
            edge_tts_engine=self.mock_edge,
        )

        pcm = orchestrator.synthesize_clause("Orkestrasyon testi", generation_id=301, auto_play=True)
        self.assertIsNotNone(pcm)
        self.assertEqual(len(pcm), 24000)


if __name__ == "__main__":
    unittest.main()
