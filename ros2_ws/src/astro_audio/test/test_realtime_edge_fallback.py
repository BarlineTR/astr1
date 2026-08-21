"""ASTRO V1 — Realtime Primary + Edge-TTS Fallback Acceptance Test Suite.

Verifies the 12 strict production contract requirements:
  1. Realtime healthy -> Realtime audio streaming
  2. Realtime quota exhausted -> Edge-TTS fallback
  3. Realtime websocket disconnected -> Edge-TTS fallback
  4. Internet unavailable -> Local Offline TTS
  5. Edge-TTS synthesis timeout -> Local Offline TTS
  6. Edge-TTS synthesis error -> Local Offline TTS
  7. XTTS disabled -> worker spawn count == 0 (DORMANT)
  8. generation_id preserved through all fallback hops
  9. Realtime failure produces explicit fallback telemetry [REALTIME DEGRADED]
  10. Edge-TTS playback produces [PLAYBACK STARTED] with actual_provider=edge_tts
  11. Zero-Silence Contract (No silent turn after successful LLM response)
  12. Recovery from Edge-TTS back to Realtime occurs only at turn boundary
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Enforce mock audio
os.environ["ASTRO_MOCK_AUDIO"] = "1"
os.environ["TTS_XTTS_ENABLED"] = "0"  # XTTS DORMANT

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "astro_audio")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "astro_ai")))

from astro_audio.audio_output_manager import AudioOutputManager
from astro_audio.edge_tts_engine import EdgeTTSEngine
from astro_audio.local_offline_tts_engine import LocalOfflineTTSEngine
from astro_audio.local_xtts_engine import LocalXttsEngine
from astro_audio.realtime_engine import RealtimeEngine, RealtimeState, classify_realtime_error
from astro_audio.tts_orchestrator import OrchestratorState, TTSOrchestrator
from astro_audio.tts_router import TTSRouteResult, TTSRouter


class TestRealtimeEdgeFallback(unittest.TestCase):
    """Authoritative Acceptance Tests for Realtime + Edge-TTS Production Contract."""

    def setUp(self):
        self.output_mgr = AudioOutputManager()
        self.log_messages = []

        def _log(lvl, msg):
            self.log_messages.append(f"[{lvl.upper()}] {msg}")

        self.logger = _log

    # --------------------------------------------------------------------------
    # 1. Realtime Healthy -> Primary Audio
    # --------------------------------------------------------------------------
    def test_scenario_1_realtime_healthy_is_primary(self):
        """1. When Realtime is connected and healthy, state is REALTIME_ACTIVE and is_ready=True."""
        engine = RealtimeEngine(logger=self.logger)
        self.assertEqual(engine.state, RealtimeState.REALTIME_STARTING)
        self.assertFalse(engine.is_ready())

        engine.set_connected(True)
        self.assertEqual(engine.state, RealtimeState.REALTIME_ACTIVE)
        self.assertTrue(engine.is_ready())
        self.assertEqual(engine.name, "openai_realtime")

    # --------------------------------------------------------------------------
    # 2. Realtime Quota Exhausted -> Edge-TTS Fallback
    # --------------------------------------------------------------------------
    def test_scenario_2_realtime_quota_exhausted_routes_to_edge_tts(self):
        """2. When Realtime quota is exhausted (1013 / insufficient_quota), routes to Edge-TTS."""
        engine = RealtimeEngine(logger=self.logger)
        engine.set_connected(True)

        new_state, reason = engine.mark_error(1013, "insufficient_quota: You exceeded your current quota")
        self.assertEqual(new_state, RealtimeState.REALTIME_QUOTA_EXHAUSTED)
        self.assertEqual(reason, "realtime_quota_exhausted")
        self.assertFalse(engine.is_ready())

        # Synthesize with TTSRouter
        edge_pcm = b"\x00\x02" * 500
        router = TTSRouter(
            edge_tts_synth_func=lambda text: edge_pcm,
            edge_tts_enabled=True,
            logger=self.logger,
        )
        res = router.synthesize("Merhaba Baran, nasılsın?", generation_id=42, realtime_fallback_reason=reason)

        self.assertEqual(res.actual_provider, "edge_tts")
        self.assertEqual(res.pcm, edge_pcm)
        self.assertEqual(res.fallback_reason, "realtime_quota_exhausted")
        self.assertIn("edge_tts", res.fallback_chain)

    # --------------------------------------------------------------------------
    # 3. Realtime WebSocket Disconnected -> Edge-TTS Fallback
    # --------------------------------------------------------------------------
    def test_scenario_3_realtime_websocket_disconnected_routes_to_edge_tts(self):
        """3. When Realtime disconnects (1006 / connection closed), routes to Edge-TTS."""
        engine = RealtimeEngine(logger=self.logger)
        engine.set_connected(True)
        engine.set_connected(False)

        self.assertEqual(engine.state, RealtimeState.REALTIME_OFFLINE)
        self.assertFalse(engine.is_ready())

        edge_pcm = b"\x00\x03" * 500
        router = TTSRouter(
            edge_tts_synth_func=lambda text: edge_pcm,
            edge_tts_enabled=True,
            logger=self.logger,
        )
        res = router.synthesize("Bağlantı koptu ama konuşuyorum.", generation_id=43, realtime_fallback_reason="realtime_websocket_disconnected")

        self.assertEqual(res.actual_provider, "edge_tts")
        self.assertEqual(res.pcm, edge_pcm)

    # --------------------------------------------------------------------------
    # 4. Internet Unavailable -> Local Offline TTS
    # --------------------------------------------------------------------------
    def test_scenario_4_internet_unavailable_uses_local_offline_tts(self):
        """4. When internet is unavailable, fast-skips Edge-TTS (0ms) and uses Local Offline TTS."""
        mock_edge = MagicMock(spec=EdgeTTSEngine)
        mock_edge.check_network.return_value = False  # No internet

        mock_offline = MagicMock(spec=LocalOfflineTTSEngine)
        mock_offline.is_ready.return_value = True
        mock_offline.state = "READY"
        mock_offline.synthesize_sentence.return_value = b"\x00\x04" * 500

        router = TTSRouter(
            edge_tts_engine=mock_edge,
            local_offline_tts=mock_offline,
            logger=self.logger,
        )
        res = router.synthesize("Çevrimdışı acil durum yanıtı.", generation_id=44)

        self.assertEqual(res.actual_provider, "local_offline_tts")
        self.assertEqual(res.source_name, "local_offline_synth")
        self.assertIn("edge_tts(network_unavailable)", res.fallback_chain)
        self.assertIn("local_offline_tts", res.fallback_chain)

    # --------------------------------------------------------------------------
    # 5. Edge-TTS Synthesis Timeout -> Local Offline TTS
    # --------------------------------------------------------------------------
    def test_scenario_5_edge_tts_timeout_routes_to_local_offline_tts(self):
        """5. When Edge-TTS times out, routes to Local Offline TTS without crashing."""
        mock_edge = MagicMock(spec=EdgeTTSEngine)
        mock_edge.check_network.return_value = True
        mock_edge.synthesize_sentence.return_value = None  # Timed out

        mock_offline = MagicMock(spec=LocalOfflineTTSEngine)
        mock_offline.is_ready.return_value = True
        mock_offline.state = "READY"
        mock_offline.synthesize_sentence.return_value = b"\x00\x05" * 500

        router = TTSRouter(
            edge_tts_engine=mock_edge,
            local_offline_tts=mock_offline,
            logger=self.logger,
        )
        res = router.synthesize("Zaman aşımı sonrası yedek ses.", generation_id=45)

        self.assertEqual(res.actual_provider, "local_offline_tts")
        self.assertIn("edge_tts(synthesis_failed)", res.fallback_chain)

    # --------------------------------------------------------------------------
    # 6. Edge-TTS Synthesis Error -> Local Offline TTS
    # --------------------------------------------------------------------------
    def test_scenario_6_edge_tts_error_routes_to_local_offline_tts(self):
        """6. When Edge-TTS raises an exception, routes to Local Offline TTS."""
        mock_edge = MagicMock(spec=EdgeTTSEngine)
        mock_edge.check_network.return_value = True
        mock_edge.synthesize_sentence.side_effect = Exception("Edge WebSocket 503 Service Unavailable")

        mock_offline = MagicMock(spec=LocalOfflineTTSEngine)
        mock_offline.is_ready.return_value = True
        mock_offline.state = "READY"
        mock_offline.synthesize_sentence.return_value = b"\x00\x06" * 500

        router = TTSRouter(
            edge_tts_engine=mock_edge,
            local_offline_tts=mock_offline,
            logger=self.logger,
        )
        res = router.synthesize("Hata sonrası yedek ses.", generation_id=46)

        self.assertEqual(res.actual_provider, "local_offline_tts")

    # --------------------------------------------------------------------------
    # 7. XTTS Disabled -> Worker Spawn Count == 0
    # --------------------------------------------------------------------------
    def test_scenario_7_xtts_disabled_zero_worker_spawn(self):
        """7. When XTTS is disabled by production policy, start() never spawns worker (spawn count = 0)."""
        xtts = LocalXttsEngine(logger=self.logger)
        self.assertFalse(xtts.runtime_enabled)
        self.assertEqual(xtts.state, "DISABLED")
        self.assertFalse(xtts.is_ready())
        self.assertFalse(xtts.is_healthy())

        # Attempting start should immediately return without launching subprocess or supervisor
        with patch.object(xtts.client, "start") as mock_spawn:
            xtts.start()
            mock_spawn.assert_not_called()

        self.assertEqual(xtts.state, "DISABLED")

    # --------------------------------------------------------------------------
    # 8. Generation ID Preserved Across All Fallback Hops
    # --------------------------------------------------------------------------
    def test_scenario_8_generation_id_preserved_across_all_hops(self):
        """8. generation_id is strictly immutable across Realtime -> Edge -> Local Offline fallback."""
        target_gen_id = 999
        mock_edge = MagicMock(spec=EdgeTTSEngine)
        mock_edge.check_network.return_value = False

        mock_offline = MagicMock(spec=LocalOfflineTTSEngine)
        mock_offline.is_ready.return_value = True
        mock_offline.state = "READY"
        mock_offline.synthesize_sentence.return_value = b"\x00\x08" * 500

        router = TTSRouter(
            edge_tts_engine=mock_edge,
            local_offline_tts=mock_offline,
            logger=self.logger,
        )
        res = router.synthesize("Değişmez generation id testi", generation_id=target_gen_id)

        self.assertEqual(res.actual_provider, "local_offline_tts")
        # Verify generation_id passed to offline engine matches target_gen_id
        mock_offline.synthesize_sentence.assert_called_once_with(
            "Değişmez generation id testi",
            generation_id=target_gen_id,
            language="tr",
        )

    # --------------------------------------------------------------------------
    # 9. Realtime Failure Produces Explicit Fallback Telemetry
    # --------------------------------------------------------------------------
    def test_scenario_9_realtime_failure_produces_explicit_telemetry(self):
        """9. Realtime degradation produces explicit [REALTIME DEGRADED] log with structured fields."""
        logs = []
        engine = RealtimeEngine(logger=lambda lvl, msg: logs.append(msg))
        engine.set_connected(True)
        engine.mark_error(1013, "quota_exhausted: You have exceeded your credit balance")

        all_logs_str = "\n".join(logs)
        self.assertIn("🚨 [REALTIME DEGRADED]", all_logs_str)
        self.assertIn("reason=realtime_quota_exhausted", all_logs_str)
        self.assertIn("previous_state=REALTIME_ACTIVE", all_logs_str)
        self.assertIn("fallback_provider=edge_tts", all_logs_str)

    # --------------------------------------------------------------------------
    # 10. Edge-TTS Playback Produces [PLAYBACK STARTED]
    # --------------------------------------------------------------------------
    def test_scenario_10_edge_tts_playback_produces_playback_started(self):
        """10. Edge-TTS playback sends provenance to AudioOutputManager and emits [Playback Started]."""
        edge_pcm = b"\x00\x0a" * 1200
        output_mgr = AudioOutputManager()
        playback_logs = []

        with patch.object(output_mgr, "play_pcm_chunk") as mock_play:
            router = TTSRouter(
                edge_tts_synth_func=lambda text: edge_pcm,
                edge_tts_enabled=True,
                output_manager=output_mgr,
                logger=lambda lvl, msg: playback_logs.append(msg),
            )
            res = router.synthesize_and_play("Hoparlör testi", generation_id=77)

            self.assertEqual(res.actual_provider, "edge_tts")
            mock_play.assert_called_once()
            call_kwargs = mock_play.call_args[1]
            self.assertEqual(call_kwargs["generation_id"], 77)
            self.assertEqual(call_kwargs["provenance"]["tts_provider"], "edge_tts")
            self.assertEqual(call_kwargs["provenance"]["tts_source"], "edge_tts_cloud")

    # --------------------------------------------------------------------------
    # 11. Zero-Silence Contract (No Silent Turn After Successful LLM Response)
    # --------------------------------------------------------------------------
    def test_scenario_11_zero_silence_contract_all_fail_emits_alarm(self):
        """11. If all TTS engines fail after text response, explicit TTS_ALL_PROVIDERS_FAILED is raised."""
        mock_edge = MagicMock(spec=EdgeTTSEngine)
        mock_edge.check_network.return_value = False

        mock_offline = MagicMock(spec=LocalOfflineTTSEngine)
        mock_offline.is_ready.return_value = False  # Offline also failed

        router = TTSRouter(
            edge_tts_engine=mock_edge,
            local_offline_tts=mock_offline,
            logger=self.logger,
        )
        res = router.synthesize("Bu metin asla sessizce kaybolamaz.", generation_id=123)

        self.assertIsNotNone(res.pcm)
        self.assertEqual(res.actual_provider, "emergency_wav")
        self.assertEqual(res.fallback_reason, "TTS_ALL_PROVIDERS_FAILED")
        self.assertIn(res.tts_state, ["EMERGENCY_PLAYBACK", "ALL_FAILED"])

    # --------------------------------------------------------------------------
    # 12. Recovery from Edge-TTS Back to Realtime Occurs Only at Turn Boundary
    # --------------------------------------------------------------------------
    def test_scenario_12_recovery_to_realtime_at_turn_boundary_only(self):
        """12. Switching from Fallback back to Realtime happens at turn boundary, never mid-turn."""
        engine = RealtimeEngine(logger=self.logger)
        engine.mark_error(1013, "quota")
        self.assertEqual(engine.state, RealtimeState.REALTIME_QUOTA_EXHAUSTED)

        # Mid-turn synthesis remains with Edge-TTS
        router = TTSRouter(
            edge_tts_synth_func=lambda text: b"\x00\x0c" * 200,
            edge_tts_enabled=True,
            logger=self.logger,
        )
        res_mid_turn = router.synthesize("Turn devam ediyor", generation_id=501)
        self.assertEqual(res_mid_turn.actual_provider, "edge_tts")

        # Turn finishes, probe confirms Realtime recovered
        engine.reset_quota_status()
        self.assertEqual(engine.state, RealtimeState.REALTIME_ACTIVE)
        self.assertTrue(engine.is_ready())


if __name__ == "__main__":
    unittest.main()
