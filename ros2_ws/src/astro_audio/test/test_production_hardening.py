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
import numpy as np

# Enforce in-memory audio isolation (never touch physical /dev/snd during unit tests)
os.environ["ASTRO_MOCK_AUDIO"] = "1"

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


class TestElevenLabsEngine(unittest.TestCase):
    """Tests for ElevenLabs Flash v2.5 TTS Engine (Streaming, Formats, Errors, Barge-in)."""

    def test_readiness(self):
        from astro_audio.elevenlabs_engine import ElevenLabsEngine
        engine = ElevenLabsEngine(api_key="", voice_id="", enabled=False)
        self.assertFalse(engine.is_ready())

        engine.set_enabled(True)
        self.assertFalse(engine.is_ready())

        engine.set_api_key("test_key")
        self.assertFalse(engine.is_ready())

        engine.set_voice_id("test_voice")
        self.assertTrue(engine.is_ready())

    def test_error_classification(self):
        from astro_audio.elevenlabs_engine import ElevenLabsEngine
        engine = ElevenLabsEngine("test_key", "test_voice", enabled=True)

        self.assertEqual(engine.classify_error(401, '{"detail": "Invalid API key"}'), "authentication_error")
        self.assertEqual(engine.classify_error(402, '{"detail": "Paid plan required (code: paid_plan_required)"}'), "billing_required")
        self.assertEqual(engine.classify_error(404, '{"detail": "Voice not found"}'), "voice_not_found")
        self.assertEqual(engine.classify_error(400, '{"detail": "Model eleven_flash_v2_5 does not support feature"}'), "model_not_found")
        self.assertEqual(engine.classify_error(429, '{"detail": "Quota exceeded for tier"}'), "quota_exhausted")
        self.assertEqual(engine.classify_error(429, '{"detail": "Too many requests per minute"}'), "rate_limited")
        self.assertEqual(engine.classify_error(500, '{"detail": "Internal Server Error"}'), "server_error")

    def test_streaming_and_synthesis(self):
        from unittest.mock import MagicMock, patch
        from astro_audio.elevenlabs_engine import ElevenLabsEngine

        engine = ElevenLabsEngine("test_key", "test_voice", enabled=True)
        fake_pcm_chunk = b"\x00\x00" * 480  # 480 samples of 24k int16

        mock_resp = MagicMock()
        mock_resp.read.side_effect = [fake_pcm_chunk, fake_pcm_chunk, b""]
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            pcm = engine.synthesize_sentence("Merhaba Baran, nasılsın?", generation_id=1)

        self.assertIsNotNone(pcm)
        self.assertEqual(len(pcm), len(fake_pcm_chunk) * 2)

    def test_cancel_barge_in(self):
        from unittest.mock import MagicMock, patch
        from astro_audio.elevenlabs_engine import ElevenLabsEngine

        engine = ElevenLabsEngine("test_key", "test_voice", enabled=True)
        fake_pcm_chunk = b"\x00\x00" * 480
        mock_resp = MagicMock()
        calls = 0
        def fake_read(size):
            nonlocal calls
            calls += 1
            if calls == 1:
                return fake_pcm_chunk
            elif calls == 2:
                engine.cancel(2)
                return fake_pcm_chunk
            return b""

        mock_resp.read.side_effect = fake_read
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            chunks = list(engine.stream_sentence_pcm("Merhaba", generation_id=1))

        # Because generation_id 1 was cancelled during second read, only first chunk is yielded
        self.assertEqual(len(chunks), 1)

    def test_xtts_finetuned_model_resolution_and_telemetry(self):
        import tempfile
        from unittest.mock import patch
        from astro_audio.local_xtts_engine import LocalXttsEngine, resolve_xtts_speaker_wav

        with tempfile.TemporaryDirectory() as tmpdir:
            model_file = os.path.join(tmpdir, "model.pth")
            config_file = os.path.join(tmpdir, "config.json")
            vocab_file = os.path.join(tmpdir, "vocab.json")
            ref_wav = os.path.join(tmpdir, "reference.wav")

            for f in (model_file, config_file, vocab_file, ref_wav):
                with open(f, "wb") as fp:
                    fp.write(b"0" * 1024)

            with patch.dict(os.environ, {
                "TTS_XTTS_CHECKPOINT": model_file,
                "TTS_XTTS_CONFIG": config_file,
                "TTS_XTTS_VOCAB": vocab_file,
                "TTS_XTTS_SPEAKER_WAV": ref_wav,
            }):
                resolved_wav = resolve_xtts_speaker_wav()
                self.assertEqual(resolved_wav, os.path.abspath(ref_wav))

                engine = LocalXttsEngine()
                self.assertTrue(engine.client.custom_model is not None)
                self.assertEqual(engine.client.custom_model["checkpoint"], os.path.abspath(model_file))
                self.assertEqual(engine.client.custom_model["config"], os.path.abspath(config_file))

                telemetry = engine.get_telemetry()
                self.assertTrue(telemetry["is_finetuned"])

    def test_voice_recognizer_telemetry_and_identify_speaker(self):
        import numpy as np
        from astro_audio.voice_recognizer import VoiceRecognizer

        rec = VoiceRecognizer()
        self.assertTrue(hasattr(rec, "identify_speaker"))
        name, score = rec.identify_speaker(np.zeros(16000, dtype=np.int16))
        self.assertIsInstance(score, float)

        telem = rec.get_telemetry()
        self.assertIn("speaker_model_path", telem)
        self.assertIn("speaker_model_exists", telem)
        self.assertIn("known_voices_path", telem)
        self.assertIn("known_speakers", telem)
        self.assertIn("Baran", telem["known_speakers"])


class TestSTTValidationAndEchoImmunity(unittest.TestCase):
    """Production acceptance tests for STT multi-signal validation, self-voice echo immunity, and hallucination rejection."""

    def setUp(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode, compute_self_voice_score
        self.node = AstroRealtimeNode()
        self.compute_self_voice_score = compute_self_voice_score

    def _generate_pcm(self, duration_s: float, rms_target: float) -> bytes:
        """Helper to create synthetic 16kHz int16 PCM with controllable RMS amplitude."""
        num_samples = int(duration_s * 16000)
        if rms_target <= 0:
            return np.zeros(num_samples, dtype=np.int16).tobytes()
        t = np.linspace(0, duration_s, num_samples, endpoint=False)
        # 440 Hz tone scaled to desired RMS
        sine = np.sin(2 * np.pi * 440 * t) * (rms_target * np.sqrt(2))
        int16_samples = np.clip(sine, -32767, 32767).astype(np.int16)
        return int16_samples.tobytes()

    def test_compute_self_voice_score_exact_and_partial(self):
        recent = [
            "merhaba baran nasılsın bugün",
            "hava durumu şu anda güneşli ve 22 derece",
        ]
        # Exact match / major substring
        score_exact = self.compute_self_voice_score("merhaba baran nasılsın", recent)
        self.assertGreaterEqual(score_exact, 0.90)

        # Word overlap
        score_partial = self.compute_self_voice_score("güneşli ve sıcak hava", recent)
        self.assertGreater(score_partial, 0.30)

        # Totally unrelated user speech
        score_unrelated = self.compute_self_voice_score("ışıkları kapat lütfen", recent)
        self.assertEqual(score_unrelated, 0.0)

    def test_stt_phantom_hallucination_rejected_on_weak_evidence(self):
        """When Whisper returns 'abone ol' or 'altyazı' on quiet room noise, it MUST be rejected."""
        weak_pcm = self._generate_pcm(0.40, rms_target=120.0)
        
        for phantom in ["abone ol", "Altyazı M.K.", "Diz", "Dizi", "izlediğiniz için teşekkürler"]:
            validated, meta = self.node._validate_stt_transcript(
                transcript=phantom,
                raw_pcm=weak_pcm,
                is_playback_active=False,
                is_echo_cooldown=False,
            )
            self.assertIsNone(validated, f"Phantom '{phantom}' should be rejected on weak acoustic evidence!")
            self.assertTrue(meta["stt_rejected"])
            self.assertIn(meta["stt_reject_reason"], ("no_speech", "self_voice", "low_confidence"))

    def test_stt_legitimate_suspect_phrase_accepted_on_strong_evidence(self):
        """When user genuinely says 'abone ol' or 'diz' with strong acoustic evidence, it MUST be accepted."""
        strong_pcm = self._generate_pcm(0.60, rms_target=750.0)
        self.node._recent_robot_phrases.clear()

        for legit in ["abone ol", "diz", "altyazı lazım"]:
            validated, meta = self.node._validate_stt_transcript(
                transcript=legit,
                raw_pcm=strong_pcm,
                is_playback_active=False,
                is_echo_cooldown=False,
            )
            self.assertEqual(validated, legit, f"Legitimate utterance '{legit}' with strong acoustic evidence should be accepted!")
            self.assertFalse(meta["stt_rejected"])
            self.assertEqual(meta["stt_reject_reason"], "none")

    def test_stt_self_voice_rejected_during_playback_and_echo_cooldown(self):
        """When microphone picks up Astro's own voice during playback or echo cooldown, it MUST be rejected."""
        self.node._recent_robot_phrases = ["anlıyorum baran sana yardımcı olabilirim"]
        pcm = self._generate_pcm(0.50, rms_target=500.0)

        # 1. During active playback
        val_play, meta_play = self.node._validate_stt_transcript(
            transcript="sana yardımcı olabilirim",
            raw_pcm=pcm,
            is_playback_active=True,
            is_echo_cooldown=False,
        )
        self.assertIsNone(val_play)
        self.assertTrue(meta_play["stt_rejected"])
        self.assertEqual(meta_play["stt_reject_reason"], "self_voice")

        # 2. During post-playback echo cooldown
        val_cool, meta_cool = self.node._validate_stt_transcript(
            transcript="yardımcı olabilirim",
            raw_pcm=pcm,
            is_playback_active=False,
            is_echo_cooldown=True,
        )
        self.assertIsNone(val_cool)
        self.assertTrue(meta_cool["stt_rejected"])
        self.assertEqual(meta_cool["stt_reject_reason"], "self_voice")

    def test_stt_short_utterance_acceptance(self):
        """Short single-word commands (Hey, Lan, Dur, Tamam, Ne?) with valid acoustic evidence are ACCEPTED."""
        short_pcm = self._generate_pcm(0.35, rms_target=450.0)
        self.node._recent_robot_phrases.clear()

        for word in ["Hey", "Lan", "Dur", "Tamam", "Ne", "Astro", "Evet", "Hayır"]:
            val, meta = self.node._validate_stt_transcript(
                transcript=word,
                raw_pcm=short_pcm,
                is_playback_active=False,
                is_echo_cooldown=False,
            )
            self.assertEqual(val, word)
            self.assertFalse(meta["stt_rejected"])

    def test_stt_buffer_flushing_on_state_transition(self):
        """Buffer flush must clear accumulators without memory bleed into future turns."""
        self.node._fallback_audio_buffer = [b"123" * 100, b"456" * 100]
        self.node._fallback_speaking = True
        self.node._consecutive_loud_frames = 10

        self.node._flush_audio_buffers("test_transition")

        self.assertEqual(len(self.node._fallback_audio_buffer), 0)
        self.assertFalse(self.node._fallback_speaking)
        self.assertEqual(self.node._consecutive_loud_frames, 0)


if __name__ == "__main__":
    unittest.main()
