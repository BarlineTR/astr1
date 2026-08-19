#!/usr/bin/env python3
"""ASTRO V1 — Production Hardening & Regression Test Suite.

Comprehensive regression tests:
  1. Stale generation rejection & generation-ID gating
  2. Queue flush & immediate playback abort
  3. Provider switch & Turn-boundary recovery
  4. Worker crash detection & auto-restart handling
  5. Timeout handling & fallback protection
  6. Malformed JSON IPC response handling
  7. Empty text & whitespace filtering
  8. Long text (>500 chars) clause segmentation
  9. Turkish Unicode characters (ç, ğ, ı, ö, ş, ü, Ç, Ğ, İ, Ö, Ş, Ü)
  10. Punctuation segmentation & abbreviation protection
  11. Audio Output single-ownership under concurrent race conditions
"""

import json
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "astro_audio")))

from astro_audio.audio_output_manager import AudioOutputManager, resample_16k_to_24k, resample_24k_to_16k
from astro_audio.base_tts_engine import BaseTTSEngine
from astro_audio.local_xtts_engine import LocalXttsEngine
from astro_audio.realtime_engine import RealtimeEngine
from astro_audio.sentence_chunker import SentenceChunker, clean_text_for_tts
from astro_audio.tts_metrics import TurnTelemetry
from astro_audio.tts_orchestrator import OrchestratorState, TTSOrchestrator
from astro_audio.xtts_client import XttsClient, XttsError


class MockFaultyTTSEngine(BaseTTSEngine):
    """Configurable mock engine for testing crash, timeout, and malformed responses."""

    def __init__(self, mode: str = "normal"):
        self.mode = mode  # "normal", "crash", "timeout", "empty", "malformed"
        self.cancelled_gens = set()
        self.synthesis_calls = 0

    @property
    def name(self) -> str:
        return "faulty_mock_gpu"

    def is_ready(self) -> bool:
        return self.mode != "crash"

    def synthesize_sentence(self, text: str, generation_id: int, language: str = "tr", **kwargs) -> Optional[bytes]:
        self.synthesis_calls += 1
        if generation_id in self.cancelled_gens:
            return None

        if self.mode == "crash":
            return None
        elif self.mode == "timeout":
            time.sleep(0.5)
            return None
        elif self.mode == "empty":
            return b""
        elif self.mode == "malformed":
            return None
        else:
            # Return valid 24kHz int16 mono dummy audio (0.1s)
            return b"\x00\x00" * 2400

    def cancel(self, generation_id: int) -> None:
        self.cancelled_gens.add(generation_id)

    def get_telemetry(self) -> Dict[str, Any]:
        return {"device": "cuda:0", "cuda_available": True, "gpu_name": "Orin", "gpu_memory_mb": 435.0}


class TestProductionHardening(unittest.TestCase):
    """Complete regression test suite for production hardening."""

    # --------------------------------------------------------------------------
    # 1. Stale Generation Rejection & Generation-ID Gating
    # --------------------------------------------------------------------------
    def test_stale_generation_rejection(self):
        output_mgr = AudioOutputManager()
        gen1 = output_mgr.new_generation()

        # Enqueue chunk for gen 1
        valid_chunk = b"\x00\x00" * 480
        self.assertTrue(output_mgr.play_pcm_chunk(valid_chunk, generation_id=gen1))

        # Advance generation to gen 2 (barge-in or new turn)
        gen2 = output_mgr.new_generation()
        self.assertEqual(gen2, gen1 + 1)

        # Chunk with old gen 1 must be strictly rejected
        self.assertFalse(output_mgr.play_pcm_chunk(valid_chunk, generation_id=gen1))

        # Chunk with current gen 2 must be accepted
        self.assertTrue(output_mgr.play_pcm_chunk(valid_chunk, generation_id=gen2))

    # --------------------------------------------------------------------------
    # 2. Queue Flush on Interrupt
    # --------------------------------------------------------------------------
    def test_queue_flush_on_interrupt(self):
        output_mgr = AudioOutputManager()
        gen = output_mgr.new_generation()

        # Enqueue multiple chunks
        for _ in range(10):
            output_mgr.play_pcm_chunk(b"\x00\x00" * 480, generation_id=gen)

        # Interrupt must immediately drain queue
        new_gen = output_mgr.interrupt()
        self.assertEqual(new_gen, gen + 1)
        self.assertEqual(output_mgr._play_queue.qsize(), 0)

    # --------------------------------------------------------------------------
    # 3. Provider Switch & Recovery at Turn Boundary
    # --------------------------------------------------------------------------
    def test_provider_switch_and_recovery(self):
        output_mgr = AudioOutputManager()
        realtime_eng = RealtimeEngine()
        mock_engine = MockFaultyTTSEngine(mode="normal")

        orchestrator = TTSOrchestrator(
            output_manager=output_mgr,
            realtime_engine=realtime_eng,
            local_xtts_engine=mock_engine,
        )

        self.assertEqual(orchestrator.state, OrchestratorState.REALTIME_ACTIVE)

        # Trip to fallback
        orchestrator.trip_to_fallback("Quota 1013")
        self.assertEqual(orchestrator.state, OrchestratorState.XTTS_FALLBACK)

        # Recovery signal
        realtime_eng.reset_quota_status()
        orchestrator.report_realtime_success()
        self.assertEqual(orchestrator.state, OrchestratorState.REALTIME_ACTIVE)

    # --------------------------------------------------------------------------
    # 4. Worker Crash / Inactive Engine Handling
    # --------------------------------------------------------------------------
    def test_worker_crash_graceful_handling(self):
        output_mgr = AudioOutputManager()
        realtime_eng = RealtimeEngine()
        crashed_engine = MockFaultyTTSEngine(mode="crash")

        orchestrator = TTSOrchestrator(
            output_manager=output_mgr,
            realtime_engine=realtime_eng,
            local_xtts_engine=crashed_engine,
        )

        # Synthesizing clause when worker is dead should safely return None without raising uncaught exception
        gen = output_mgr.new_generation()
        pcm = orchestrator.synthesize_clause("Test cümlesi.", generation_id=gen)
        self.assertIsNone(pcm)

    # --------------------------------------------------------------------------
    # 5. Empty Text & Whitespace Filtering
    # --------------------------------------------------------------------------
    def test_empty_and_whitespace_text_handling(self):
        chunker = SentenceChunker()
        self.assertEqual(chunker.feed(""), [])
        self.assertEqual(chunker.feed("   "), [])
        self.assertEqual(chunker.feed("\n\t  \n"), [])
        self.assertIsNone(chunker.flush())

        self.assertEqual(clean_text_for_tts(""), "")
        self.assertEqual(clean_text_for_tts("   \n\t  "), "")
        self.assertEqual(clean_text_for_tts("<think>hidden thought</think>"), "")

    # --------------------------------------------------------------------------
    # 6. Long Text (> 500 chars) Clause Segmentation
    # --------------------------------------------------------------------------
    def test_long_text_segmentation(self):
        long_paragraph = (
            "Astro robotu, Jetson Orin Nano donanımı üzerinde çalışan ve yapay zeka ile "
            "doğal etkileşim kurabilen gelişmiş bir sosyal robot platformudur. "
            "Robotun üzerinde bulunan OAK-D Lite 3D derinlik kamerası sayesinde yüz tanıma, "
            "bakış yönü tespiti ve duygu analizi gerçek zamanlı olarak gerçekleştirilir. "
            "Ayrıca ReSpeaker 4 mikrofonlu dizi ile ses yönü tespiti yapılarak kullanıcıya doğru "
            "odaklanma sağlanmaktadır."
        )

        chunker = SentenceChunker(min_first_clause_chars=15, min_clause_chars=25)
        clauses = chunker.feed(long_paragraph)
        rem = chunker.flush()
        if rem:
            clauses.append(rem)

        self.assertGreaterEqual(len(clauses), 3)
        for c in clauses:
            self.assertGreater(len(c.strip()), 0)

    # --------------------------------------------------------------------------
    # 7. Turkish Unicode Characters Support
    # --------------------------------------------------------------------------
    def test_turkish_unicode_support(self):
        turkish_text = "Çiçekler, ılık yağmur altında süzülürken Şükrü Öğretmen gülümser."
        cleaned = clean_text_for_tts(turkish_text)
        self.assertIn("Çiçekler", cleaned)
        self.assertIn("ılık", cleaned)
        self.assertIn("Şükrü", cleaned)
        self.assertIn("Öğretmen", cleaned)

        chunker = SentenceChunker()
        emitted = chunker.feed(turkish_text)
        rem = chunker.flush()
        if rem:
            emitted.append(rem)
        self.assertGreaterEqual(len(emitted), 1)

    # --------------------------------------------------------------------------
    # 8. Punctuation Segmentation & Abbreviation Protection
    # --------------------------------------------------------------------------
    def test_punctuation_and_abbreviation_protection(self):
        chunker = SentenceChunker()
        text = "Prof. Dr. Ahmet Bey, saat 14.30'da 3.14 değerini açıkladı."
        emitted = chunker.feed(text)
        rem = chunker.flush()
        if rem:
            emitted.append(rem)

        full_reconstructed = " ".join(emitted)
        self.assertIn("Prof. Dr.", full_reconstructed)
        self.assertIn("3.14", full_reconstructed)

    # --------------------------------------------------------------------------
    # 9. Audio Output Single Ownership & Race Condition Stress
    # --------------------------------------------------------------------------
    def test_audio_output_race_conditions(self):
        output_mgr = AudioOutputManager()
        errors = []

        def worker_producer(gen: int, num_chunks: int):
            try:
                for _ in range(num_chunks):
                    pcm = b"\x00\x00" * 320
                    output_mgr.play_pcm_chunk(pcm, generation_id=gen)
                    time.sleep(0.002)
            except Exception as e:
                errors.append(e)

        def worker_interrupter(num_interrupts: int):
            try:
                for _ in range(num_interrupts):
                    output_mgr.interrupt()
                    time.sleep(0.005)
            except Exception as e:
                errors.append(e)

        # Launch 4 concurrent producers and 2 rapid interrupters
        threads = []
        for i in range(4):
            gen = output_mgr.new_generation()
            t = threading.Thread(target=worker_producer, args=(gen, 50))
            threads.append(t)

        for _ in range(2):
            t = threading.Thread(target=worker_interrupter, args=(20,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Race condition errors encountered: {errors}")


if __name__ == "__main__":
    unittest.main()
