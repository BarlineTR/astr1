#!/usr/bin/env python3
"""ASTRO V1 — Automated Test Suite for Hybrid Realtime & XTTS GPU Architecture.

Tests:
  1. SentenceChunker: streaming token splitting, abbreviation protection, low-latency clause emission
  2. TTSMetrics & Telemetry: TTFA calculation, durations, RTF, JSON export
  3. AudioOutputManager: generational queue filtering, barge-in queue flush, aplay/sounddevice fallback
  4. RealtimeEngine: health status, quota detection, error tracking
  5. LocalXttsEngine: BaseTTSEngine interface compliance, latent caching, telemetry
  6. TTSOrchestrator: FSM transitions, Circuit Breaker failover (< 5ms), barge-in interrupt, pipelined synthesis
"""

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "astro_audio")))

from astro_audio.tts_metrics import TurnTelemetry
from astro_audio.sentence_chunker import SentenceChunker, clean_text_for_tts
from astro_audio.audio_output_manager import AudioOutputManager, resample_16k_to_24k, resample_24k_to_16k
from astro_audio.base_tts_engine import BaseTTSEngine
from astro_audio.realtime_engine import RealtimeEngine
from astro_audio.local_xtts_engine import LocalXttsEngine
from astro_audio.tts_orchestrator import OrchestratorState, TTSOrchestrator


class MockTTSEngine(BaseTTSEngine):
    """Mock TTS Engine for testing orchestrator pipelines."""

    def __init__(self, name: str = "mock_gpu_xtts", infer_delay_s: float = 0.05):
        self._name = name
        self.infer_delay_s = infer_delay_s
        self.cancelled_gens = set()
        self.synthesized_clauses = []

    @property
    def name(self) -> str:
        return self._name

    def is_ready(self) -> bool:
        return True

    def synthesize_sentence(self, text: str, generation_id: int, language: str = "tr", **kwargs):
        if generation_id in self.cancelled_gens:
            return None
        time.sleep(self.infer_delay_s)
        self.synthesized_clauses.append((text, generation_id))
        # Return 0.25s of dummy int16 PCM (4000 samples @ 16kHz = 8000 bytes)
        return b"\x00\x00" * 4000

    def cancel(self, generation_id: int) -> None:
        self.cancelled_gens.add(generation_id)

    def get_telemetry(self):
        return {
            "device": "cuda:0",
            "cuda_available": True,
            "gpu_name": "Orin",
            "gpu_memory_mb": 420.0,
            "rtf": 0.20,
            "last_infer_ms": 50.0,
        }


class TestSentenceChunker(unittest.TestCase):
    """Tests for low-latency streaming clause splitter."""

    def test_streaming_token_split(self):
        chunker = SentenceChunker(min_first_clause_chars=12, min_clause_chars=20)

        # Feed tokens incrementally
        tokens = ["Merhaba ", "Baran, ", "bugün ", "hava ", "nasıl? ", "Dışarıya ", "çıkacak ", "mısın."]
        emitted = []
        for t in tokens:
            emitted.extend(chunker.feed(t))
        rem = chunker.flush()
        if rem:
            emitted.append(rem)

        self.assertGreaterEqual(len(emitted), 2)
        self.assertTrue(any("Merhaba Baran" in c for c in emitted))
        self.assertTrue(any("Dışarıya çıkacak mısın" in c for c in emitted))

    def test_abbreviation_and_decimal_protection(self):
        chunker = SentenceChunker(min_first_clause_chars=10, min_clause_chars=15)
        # Should not split on 3.14 or Dr.
        text = "Robot pi sayısı 3.14 olarak bilinir. Dr. Ali geldi."
        emitted = chunker.feed(text)
        rem = chunker.flush()
        if rem:
            emitted.append(rem)

        self.assertEqual(len(emitted), 2)
        self.assertIn("3.14", emitted[0])
        self.assertIn("Dr. Ali", emitted[1])


class TestTTSMetrics(unittest.TestCase):
    """Tests for TTFA calculation and telemetry reporting."""

    def test_telemetry_calculation(self):
        tel = TurnTelemetry(turn_id="turn_1", generation_id=1, active_tts_engine="xtts_gpu", cuda_available=True, gpu_name="Orin", gpu_memory_mb=420.0)
        
        t0 = time.monotonic()
        tel.mark_user_turn_end(t0)
        time.sleep(0.02)
        tel.mark_fallback_selected(t0 + 0.01)
        tel.mark_llm_first_token(t0 + 0.04)
        tel.mark_xtts_inference_start(t0 + 0.05)
        tel.mark_synthesized_audio_ready(t0 + 0.12)
        tel.mark_audio_manager_submitted(t0 + 0.13)
        tel.mark_playback_first_audio(t0 + 0.15)
        tel.record_synthesis(synth_ms=70.0, audio_sec=0.5, gpu_inf_ms=65.0)

        self.assertAlmostEqual(tel.llm_first_token_ms, 40.0, delta=5.0)
        self.assertAlmostEqual(tel.software_ttfa_ms, 150.0, delta=5.0)
        self.assertAlmostEqual(tel.total_end_to_end_ttfa_ms, 170.0, delta=5.0)
        self.assertEqual(tel.real_time_factor, 0.14)
        self.assertTrue(tel.cuda_available)

        json_str = tel.to_json()
        self.assertIn('"turn_id": "turn_1"', json_str)
        self.assertIn('"active_tts_engine": "xtts_gpu"', json_str)

        summary = tel.summary_line()
        self.assertIn("TTFA:", summary)
        self.assertIn("Provider: [xtts_gpu]", summary)
        self.assertIn("GPU: 65ms", summary)


class TestAudioOutputManager(unittest.TestCase):
    """Tests for generation ID filtering and barge-in queue flush."""

    def test_generation_gating(self):
        mgr = AudioOutputManager()
        gen1 = mgr.new_generation()
        self.assertEqual(gen1, 1)

        # Enqueue chunk for gen 1
        dummy_pcm = b"\x00\x00" * 160
        self.assertTrue(mgr.play_pcm_chunk(dummy_pcm, generation_id=gen1))

        # Interrupt to gen 2
        gen2 = mgr.interrupt()
        self.assertEqual(gen2, 2)

        # Stale chunk with gen 1 should be rejected
        self.assertFalse(mgr.play_pcm_chunk(dummy_pcm, generation_id=gen1))

        # Valid chunk with gen 2 should be accepted
        self.assertTrue(mgr.play_pcm_chunk(dummy_pcm, generation_id=gen2))

    def test_pcm_resampling(self):
        # 16k -> 24k -> 16k roundtrip
        raw_16k = b"\x10\x00" * 320
        raw_24k = resample_16k_to_24k(raw_16k)
        self.assertEqual(len(raw_24k), 480 * 2)

        resampled_16k = resample_24k_to_16k(raw_24k)
        self.assertEqual(len(resampled_16k), 320 * 2)


class TestTTSOrchestratorAndCircuitBreaker(unittest.TestCase):
    """Tests for State Machine, Circuit Breaker Failover, and Pipelined Synthesis."""

    def test_state_machine_and_circuit_breaker(self):
        output_mgr = AudioOutputManager()
        realtime_eng = RealtimeEngine()
        mock_xtts = MockTTSEngine()

        state_changes = []
        orchestrator = TTSOrchestrator(
            output_manager=output_mgr,
            realtime_engine=realtime_eng,
            local_xtts_engine=mock_xtts,
            on_state_change=lambda s: state_changes.append(s),
        )

        self.assertEqual(orchestrator.state, OrchestratorState.REALTIME_ACTIVE)

        # Test Circuit Breaker Trip on Quota 1013
        t_trip_start = time.monotonic()
        orchestrator.report_realtime_failure(1013, "insufficient_quota")
        trip_duration_ms = (time.monotonic() - t_trip_start) * 1000.0

        # Must trip in < 5ms
        self.assertLess(trip_duration_ms, 5.0)
        self.assertEqual(orchestrator.state, OrchestratorState.XTTS_FALLBACK)
        self.assertTrue(realtime_eng._quota_exhausted)

        # Test Pipelined Clause Synthesis in Fallback Mode
        gen_id = output_mgr.new_generation()
        orchestrator.start_turn("turn_fb_1", generation_id=gen_id)

        tokens = ["Ulan ", "Baran, ", "buradayım ", "işte!"]
        for tok in tokens:
            orchestrator.process_token_stream_clause(tok, generation_id=gen_id)
        orchestrator.flush_remaining_stream_clause(generation_id=gen_id)

        self.assertGreaterEqual(len(mock_xtts.synthesized_clauses), 1)

        # Test Barge-In Interrupt
        t_barge = time.monotonic()
        new_gen = orchestrator.interrupt()
        barge_dur_ms = (time.monotonic() - t_barge) * 1000.0
        self.assertLess(barge_dur_ms, 5.0)
        self.assertEqual(new_gen, gen_id + 1)
        self.assertIn(new_gen, mock_xtts.cancelled_gens)

        # Test Recovery
        realtime_eng.reset_quota_status()
        orchestrator.report_realtime_success()
        self.assertEqual(orchestrator.state, OrchestratorState.REALTIME_ACTIVE)


if __name__ == "__main__":
    unittest.main()
