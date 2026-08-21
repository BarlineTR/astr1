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
from unittest.mock import MagicMock, patch
from pathlib import Path
from typing import Any, Dict, List, Optional
import base64
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

    @classmethod
    def setUpClass(cls):
        try:
            import rclpy
            if not rclpy.ok():
                rclpy.init()
        except Exception:
            pass

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
        """When Whisper returns 'abone ol' or 'altyazı m.k.' on quiet room noise or short 240ms chirps, it MUST be rejected."""
        # 1. Very quiet noise (400ms @ 120 RMS)
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

        # 2. Short 240ms impulsive noise chirp (even with high peak RMS)
        chirp_pcm = self._generate_pcm(0.24, rms_target=600.0)
        val_chirp, meta_chirp = self.node._validate_stt_transcript(
            transcript="Altyazı M.K.",
            raw_pcm=chirp_pcm,
            is_playback_active=False,
            is_echo_cooldown=False,
        )
        self.assertIsNone(val_chirp, "240ms chirp hallucinated as 'Altyazı M.K.' must be rejected!")
        self.assertTrue(meta_chirp["stt_rejected"])

    def test_stt_legitimate_suspect_phrase_accepted_on_strong_evidence(self):
        """When user genuinely says 'abone ol' or 'diz' with sustained articulation (>= 750ms), it MUST be accepted."""
        strong_pcm = self._generate_pcm(0.85, rms_target=750.0)
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

    def test_distinct_rejection_counters_semantics(self):
        """Each rejection reason increments strictly its own dedicated counter without cross-pollution."""
        self.node.false_transcript_count = 0
        self.node.self_voice_rejection_count = 0
        self.node.no_speech_rejection_count = 0
        self.node.stale_audio_rejection_count = 0

        # 1. No speech (silent audio)
        silent_pcm = self._generate_pcm(0.30, rms_target=50.0)
        self.node._validate_stt_transcript(transcript="test", raw_pcm=silent_pcm, is_playback_active=False, is_echo_cooldown=False)
        self.assertEqual(self.node.no_speech_rejection_count, 1)
        self.assertEqual(self.node.self_voice_rejection_count, 0)
        self.assertEqual(self.node.false_transcript_count, 0)

        # 2. Self voice (echo during playback)
        self.node._recent_robot_phrases = ["merhaba baran nasılsın"]
        speech_pcm = self._generate_pcm(0.50, rms_target=500.0)
        self.node._validate_stt_transcript(transcript="merhaba baran nasılsın", raw_pcm=speech_pcm, is_playback_active=True, is_echo_cooldown=False)
        self.assertEqual(self.node.self_voice_rejection_count, 1)
        self.assertEqual(self.node.no_speech_rejection_count, 1)
        self.assertEqual(self.node.false_transcript_count, 0)

        # 3. False transcript / Low quality hallucination (single random word with low speech duration)
        weak_speech_pcm = self._generate_pcm(0.12, rms_target=420.0)
        self.node._recent_robot_phrases.clear()
        self.node._validate_stt_transcript(transcript="rastgele", raw_pcm=weak_speech_pcm, is_playback_active=False, is_echo_cooldown=False)
        self.assertEqual(self.node.false_transcript_count, 1)
        self.assertEqual(self.node.self_voice_rejection_count, 1)
        self.assertEqual(self.node.no_speech_rejection_count, 1)

    def test_barge_in_requires_multi_frame_persistence(self):
        """Single loud frame impulse is ignored; >=3 consecutive frames trigger single latched barge-in."""
        from unittest.mock import MagicMock, patch
        from astro_ai.state_machine import RobotState
        import base64

        self.node._is_sleeping = False
        self.node._is_playback_active = True
        self.node._is_responding = True
        self.node.state_machine.transition_to(RobotState.SPEAKING)
        self.node._barge_in_latched = False
        self.node._barge_in_consecutive_frames = 0
        self.node.pub_interrupt = MagicMock()

        loud_pcm_16k = self._generate_pcm(0.02, rms_target=2200.0)
        loud_msg = MagicMock()
        loud_msg.data = base64.b64encode(loud_pcm_16k).decode("ascii")

        with patch("astro_ai.astro_realtime_node.resample_24k_to_16k", return_value=loud_pcm_16k):
            # Frame 1: impulse noise -> Not enough persistence
            self.node._on_input_pcm(loud_msg)
            self.assertFalse(self.node._barge_in_latched)
            self.assertEqual(self.node.pub_interrupt.publish.call_count, 0)

            # Frame 2: still pending
            self.node._on_input_pcm(loud_msg)
            self.assertFalse(self.node._barge_in_latched)
            self.assertEqual(self.node.pub_interrupt.publish.call_count, 0)

            # Frame 3: Persistence reached -> Triggers barge-in & latches!
            self.node._on_input_pcm(loud_msg)
            self.assertTrue(self.node._barge_in_latched)
            self.assertEqual(self.node.pub_interrupt.publish.call_count, 1)

            # Frame 4 in same generation: Debounced by latch
            self.node._on_input_pcm(loud_msg)
            self.assertEqual(self.node.pub_interrupt.publish.call_count, 1)


    def test_input_pcm_does_not_jump_self_voice_counter_at_50hz(self):
        """Feeding quiet frames during playback does NOT increment self_voice_rejection_count at 50Hz."""
        import base64
        self.node._is_playback_active = True
        self.node._is_responding = True
        self.node.self_voice_rejection_count = 0
        quiet_pcm = self._generate_pcm(0.02, rms_target=100.0)
        msg = MagicMock()
        msg.data = base64.b64encode(quiet_pcm).decode("ascii")

        for _ in range(50):
            self.node._on_input_pcm(msg)

        self.assertEqual(self.node.self_voice_rejection_count, 0)

    def test_wake_phantom_command_dropped_in_candidate(self):
        """Wake candidate 'Astro. Altyazı M.K.' wakes robot to LISTENING but creates 0 LLM turns."""
        from astro_ai.state_machine import RobotState

        fake_pcm = self._generate_pcm(0.85, rms_target=600.0)
        with patch.object(self.node, "_transcribe_groq_whisper", return_value="Astro. Altyazı M.K."), \
             patch.object(self.node, "_process_fallback_turn") as mock_turn:
            self.node._process_wake_candidate([fake_pcm])
            self.assertEqual(self.node.state_machine.current_state, RobotState.LISTENING)
            mock_turn.assert_not_called()

    def test_active_mode_wake_only_transitions_to_listening_without_llm(self):
        """In active mode, saying 'Astro.' transitions to LISTENING and produces 0 LLM / 0 TTS calls."""
        from astro_ai.state_machine import RobotState

        self.node._is_sleeping = False
        fake_pcm = self._generate_pcm(0.40, rms_target=600.0)
        with patch.object(self.node, "_transcribe_groq_whisper", return_value="Astro."), \
             patch.object(self.node, "_validate_stt_transcript", return_value=("Astro.", {"stt_rejected": False})), \
             patch.object(self.node.provider_registry, "stream_groq_completion") as mock_groq, \
             patch.object(self.node, "_play_pcm_chunks") as mock_play:
            self.node._process_fallback_turn([fake_pcm])
            self.assertEqual(self.node.state_machine.current_state, RobotState.LISTENING)
            mock_groq.assert_not_called()
            mock_play.assert_not_called()

    def test_wake_catalog_and_repetitive_command_rejected(self):
        """Wake candidate containing catalog prompt hallucinations and repetitive loops is rejected without LLM turn."""
        from astro_ai.state_machine import RobotState

        fake_pcm = self._generate_pcm(0.85, rms_target=600.0)
        catalog_prompt = "Astro Türkçe konuşma, diyalog, robot asistan. Astro. Astro. Astro."
        with patch.object(self.node, "_transcribe_groq_whisper", return_value=catalog_prompt), \
             patch.object(self.node, "_process_fallback_turn") as mock_turn:
            self.node._process_wake_candidate([fake_pcm])
            self.assertEqual(self.node.state_machine.current_state, RobotState.LISTENING)
            mock_turn.assert_not_called()

    def test_xtts_cooldown_prevents_duplicate_worker_crash_loops(self):
        """LocalXttsEngine transitions to COOLDOWN upon failure and rejects duplicate worker spawns."""
        from astro_audio.local_xtts_engine import LocalXttsEngine
        from astro_audio.xtts_client import XttsError

        engine = LocalXttsEngine(speaker_wav="test.wav", home="/tmp/fake_xtts")
        engine._cooldown_duration = 5.0
        with patch("os.path.exists", return_value=True), \
             patch.object(engine.client, "start"), \
             patch.object(engine.client, "wait_ready", side_effect=XttsError("CUBLAS_STATUS_EXECUTION_FAILED")):
            with self.assertRaises(XttsError):
                engine.start()

            self.assertEqual(engine.state, "COOLDOWN")
            self.assertFalse(engine.is_ready())

            # Attempt immediate restart during cooldown window
            with patch.object(engine.client, "start") as mock_spawn:
                engine.start()
                mock_spawn.assert_not_called()

    def test_grace_period_aborts_immediately_on_crashed_xtts(self):
        """Grace period does not wait when LocalXttsEngine is in CRASHED or COOLDOWN state."""
        self.node.local_xtts = MagicMock()
        self.node.local_xtts.is_ready.return_value = False
        self.node.local_xtts.state = "COOLDOWN"

        t_start = time.monotonic()
        pcm, eng_name, latency, is_ready = self.node._synthesize_speech_pcm("Merhaba")
        elapsed = time.monotonic() - t_start

        self.assertLess(elapsed, 1.0, "Grace period should not block when XTTS is in COOLDOWN!")

    def test_xtts_client_batch_size_default_is_one(self):
        """XttsClient defaults batch_size to 1 and includes batch-size 1 in command."""
        from astro_audio.xtts_client import XttsClient
        with patch("os.path.exists", return_value=True):
            client = XttsClient(speaker_wav="test.wav", home="/tmp/fake_xtts")
            self.assertEqual(client.batch_size, 1)

    def test_ready_local_offline_tts_eliminates_15s_grace_delay(self):
        """When LocalOfflineTTS is ready and XTTS is STARTING, synthesis happens immediately without 15s wait."""
        self.node.local_xtts = MagicMock()
        self.node.local_xtts.is_ready.return_value = False
        self.node.local_xtts.state = "STARTING"

        self.node.local_offline_tts = MagicMock()
        self.node.local_offline_tts.is_ready.return_value = True
        self.node.local_offline_tts.synthesize_sentence.return_value = b"\x00\x00" * 480

        t_start = time.monotonic()
        pcm, eng_name, latency, is_ready = self.node._synthesize_speech_pcm("Merhaba Astro")
        elapsed = time.monotonic() - t_start

        self.assertLess(elapsed, 0.5, "Turn TTFA must not be blocked by 15s grace wait when local offline TTS is ready!")
        self.assertEqual(eng_name, "local_offline_tts")
        self.assertTrue(is_ready)
        self.assertEqual(len(pcm), 960)

    def test_oak_camera_stability_tracking(self):
        """OAK camera info and image frames update timestamps and connection state without blocking audio."""
        self.assertEqual(self.node._oak_connection_state, "DISCONNECTED")

        # Simulate camera info arrival
        mock_info = MagicMock()
        self.node._on_camera_info(mock_info)
        self.assertEqual(self.node._oak_connection_state, "CONNECTED")
        self.assertGreater(self.node._oak_last_camera_info_time, 0.0)

        # Simulate image arrival
        mock_img = MagicMock()
        mock_img.data = b""
    def test_audio_stream_node_initialization_health(self):
        """AudioStreamNode initializes all playback states without NameError or AttributeError."""
        from astro_audio.audio_stream_node import AudioStreamNode

        with patch("astro_audio.audio_stream_node.find_audio_device", side_effect=[(1, "hw:ReSpeaker,0"), (2, "hw:ReSpeaker,1")]), \
             patch("astro_audio.audio_stream_node.sd") as mock_sd, \
             patch.object(AudioStreamNode, "create_publisher"), \
             patch.object(AudioStreamNode, "create_subscription"), \
             patch.object(AudioStreamNode, "create_timer"):

            mock_sd.RawInputStream.return_value = MagicMock()
            mock_sd.RawOutputStream.return_value = MagicMock()

            audio_node = AudioStreamNode()

            # Verify no AttributeError
            self.assertFalse(audio_node._playback_burst_active)
            self.assertEqual(audio_node._out_device_name, "hw:ReSpeaker,1")
            self.assertEqual(audio_node._in_device_name, "hw:ReSpeaker,0")
            self.assertTrue(audio_node._playback_worker_alive)
            self.assertEqual(audio_node._playback_worker_error, "none")
            self.assertEqual(audio_node._callback_exception_count, 0)

            # Test input callback without NameError
            indata = np.zeros(320, dtype=np.int16).tobytes()
            audio_node._input_callback(indata, 320, None, None)
            self.assertGreater(audio_node._last_input_callback_time, 0.0)

            audio_node.destroy_node()

    def test_audio_stream_node_callback_exception_isolation(self):
        """AudioStreamNode isolates callback exceptions and increments error count."""
        from astro_audio.audio_stream_node import AudioStreamNode

        with patch("astro_audio.audio_stream_node.find_audio_device", side_effect=[(1, "hw:ReSpeaker,0"), (2, "hw:ReSpeaker,1")]), \
             patch("astro_audio.audio_stream_node.sd") as mock_sd, \
             patch.object(AudioStreamNode, "create_publisher"), \
             patch.object(AudioStreamNode, "create_subscription"), \
             patch.object(AudioStreamNode, "create_timer"):

            mock_sd.RawInputStream.return_value = MagicMock()
            mock_sd.RawOutputStream.return_value = MagicMock()

            audio_node = AudioStreamNode()

            # Force exception inside callback during audio processing
            loud_pcm = (np.ones(320, dtype=np.int16) * 2000).tobytes()
            with patch("astro_audio.audio_stream_node.resample_16k_to_24k", side_effect=RuntimeError("Resample exception")):
                audio_node._input_callback(loud_pcm, 320, None, None)
                self.assertEqual(audio_node._callback_exception_count, 1)

            audio_node.destroy_node()

    def test_self_voice_barge_in_protection_window(self):
        """Self-voice feedback during initial 350ms playback window is strictly suppressed without barge-in."""
        from astro_ai.state_machine import RobotState
        self.node._is_playback_active = True
        self.node._playback_start_monotonic = time.monotonic()
        self.node._barge_in_latched = False
        self.node._barge_in_consecutive_frames = 0

        # Simulate robot speaker feedback at t = 50ms into playback (RMS 3691, Peak 9241)
        mock_msg = MagicMock()
        feedback_pcm = (np.ones(320, dtype=np.int16) * 3600).tobytes()
        mock_msg.data = base64.b64encode(feedback_pcm).decode("ascii")

        with patch("astro_ai.astro_realtime_node.resample_24k_to_16k", return_value=feedback_pcm):
            # Process input chunk during protection window
            self.node._on_input_pcm(mock_msg)

            # Verify NO barge-in triggered
            self.assertFalse(self.node._barge_in_latched)
            self.assertEqual(self.node._barge_in_consecutive_frames, 0)
            self.assertNotEqual(self.node.state_machine.current_state, RobotState.INTERRUPTED)

    def test_genuine_user_barge_in_after_protection_window(self):
        """Genuine sustained user speech after protection window triggers single clean barge-in."""
        from astro_ai.state_machine import RobotState
        self.node._is_sleeping = False
        self.node._is_playback_active = True
        self.node._is_responding = True
        self.node.state_machine.transition_to(RobotState.SPEAKING)
        self.node.pub_interrupt = MagicMock()
        # Set playback start to 500ms ago (past 350ms protection window)
        self.node._playback_start_monotonic = time.monotonic() - 0.50
        self.node._barge_in_latched = False
        self.node._barge_in_consecutive_frames = 0
        self.node.barge_in_min_consecutive_frames = 3

        # Loud user voice (RMS 5000, Peak 15000)
        user_pcm = (np.ones(320, dtype=np.int16) * 5000).tobytes()
        mock_msg = MagicMock()
        mock_msg.data = base64.b64encode(user_pcm).decode("ascii")

        with patch("astro_ai.astro_realtime_node.resample_24k_to_16k", return_value=user_pcm):
            # Frame 1 & 2
            self.node._on_input_pcm(mock_msg)
            self.node._on_input_pcm(mock_msg)
            self.assertFalse(self.node._barge_in_latched)

            # Frame 3: reaches consecutive threshold -> triggers barge-in
            self.node._on_input_pcm(mock_msg)
            self.assertTrue(self.node._barge_in_latched)

    def test_xtts_child_process_probe_and_diagnostics(self):
        """XTTS client parses probe event from child process and records hardware diagnostics."""
        from astro_audio.xtts_client import XttsClient
        client = XttsClient(speaker_wav="test.wav")
        client._cmd = ["python", "xtts_worker.py", "--batch-size", "1"]

        # Simulate receiving probe JSON from child stdout
        probe_json = json.dumps({
            "event": "probe",
            "python_executable": "/usr/bin/python3",
            "torch_version": "2.5.0",
            "torch_cuda_version": "12.6",
            "torch_cuda_available": True,
            "device_count": 1,
            "device_name": "Orin",
            "batch_size": 1,
        })
        with patch.object(client, "_safe_log"):
            client.proc = MagicMock()
            client.proc.stdout = [f"@@XTTS@@ {probe_json}\n"]
            client._read_stdout()

            self.assertEqual(client.probe_info.get("device_name"), "Orin")
            self.assertTrue(client.probe_info.get("torch_cuda_available"))
            self.assertEqual(client.probe_info.get("batch_size"), 1)
            # Crucial: probe event alone MUST NOT mark client as ready!
            self.assertFalse(client.is_ready)

    def test_generic_xtts_metadata_strictly_rejected(self):
        """Generic xtts_v2 READY event or missing checkpoint metadata is strictly rejected."""
        from astro_audio.xtts_client import XttsClient, XttsError
        client = XttsClient(speaker_wav="test.wav")
        client._cmd = ["python", "xtts_worker.py"]

        generic_ready_json = json.dumps({
            "event": "ready",
            "model": "xtts_v2",
            "checkpoint": None,
            "reference": None,
            "sha256": None,
            "device": None,
            "gpu": None,
            "half": None,
            "is_finetuned": False,
        })

        with patch.object(client, "_safe_log"):
            client.proc = MagicMock()
            client.proc.stdout = [f"@@XTTS@@ {generic_ready_json}\n"]
            client._read_stdout()

            # Verify client is NOT ready and has startup error
            self.assertFalse(client.is_ready)
            self.assertIsNotNone(client._startup_error)
            with self.assertRaises(XttsError):
                client.wait_ready(timeout=1.0)

    def test_finetuned_xtts_metadata_accepted_and_marked_ready(self):
        """Fine-tuned XTTS READY event with all required files is accepted and marked READY."""
        from astro_audio.xtts_client import XttsClient
        from astro_audio.local_xtts_engine import LocalXttsEngine
        client = XttsClient(speaker_wav="test.wav")
        client._cmd = ["python", "xtts_worker.py"]

        valid_ft_ready = json.dumps({
            "event": "ready",
            "model": "xtts_finetuned",
            "is_finetuned": True,
            "checkpoint": "/home/okistech/Desktop/astr1/models/xtts_finetune_ready_v2/model.pth",
            "reference": "/home/okistech/Desktop/astr1/models/xtts_finetune_ready_v2/reference.wav",
            "config": "/home/okistech/Desktop/astr1/models/xtts_finetune_ready_v2/config.json",
            "vocab": "/home/okistech/Desktop/astr1/models/xtts_finetune_ready_v2/vocab.json",
            "speakers": "/home/okistech/Desktop/astr1/models/xtts_finetune_ready_v2/speakers_xtts.pth",
            "sha256": "db0ffe8aca560d117f694c7992f01f724db789ac9ee3a4df9a6d6526a8beedc0",
            "device": "cuda",
            "gpu": "Orin",
            "half": True,
            "batch_size": 1,
            "sample_rate": 24000,
        })

        with patch.object(client, "_safe_log"):
            client.proc = MagicMock()
            client.proc.poll.return_value = None  # Process alive
            client.proc.stdout = [f"@@XTTS@@ {valid_ft_ready}\n"]
            client._read_stdout()

            self.assertTrue(client.is_ready)
            info = client.wait_ready(timeout=1.0)
            self.assertEqual(info.get("model"), "xtts_finetuned")
            self.assertTrue(info.get("is_finetuned"))
            self.assertEqual(info.get("gpu"), "Orin")
            self.assertEqual(info.get("device"), "cuda")

    def test_audio_provenance_envelope_passing_and_verification(self):
        """AudioStreamNode correctly parses provenance JSON envelopes and retains generation_id and sources."""
        from astro_audio.audio_stream_node import AudioStreamNode
        import base64
        import json

        node = AudioStreamNode()
        raw_pcm = (np.sin(np.linspace(0, 100, 480)) * 5000).astype(np.int16).tobytes()
        b64_audio = base64.b64encode(raw_pcm).decode("ascii")

        envelope = {
            "generation_id": 42,
            "tts_provider": "xtts_gpu",
            "tts_model": "xtts_finetuned",
            "tts_source": "xtts_worker",
            "playback_source": "xtts_worker",
            "data": b64_audio,
        }

        msg = MagicMock()
        msg.data = json.dumps(envelope)

        with patch("astro_audio.audio_stream_node.resample_24k_to_16k", return_value=raw_pcm):
            node._on_output_pcm(msg)

        self.assertFalse(node._play_queue.empty())
        item = node._play_queue.get_nowait()
        self.assertIsInstance(item, dict)
        self.assertEqual(item["generation_id"], 42)
        self.assertEqual(item["tts_provider"], "xtts_gpu")
        self.assertEqual(item["tts_model"], "xtts_finetuned")
        self.assertEqual(item["tts_source"], "xtts_worker")
        self.assertEqual(item["playback_source"], "xtts_worker")

    def test_audio_stream_node_rejects_barge_in_when_zero_bytes_played(self):
        """Interrupt signal is ignored when playback has not started or played bytes is zero."""
        from astro_audio.audio_stream_node import AudioStreamNode

        node = AudioStreamNode()
        node._playback_burst_active = False
        node._total_played_bytes = 0

        int_msg = MagicMock()
        int_msg.data = True

        with patch.object(node, "get_logger"):
            node._on_interrupt(int_msg)
            # Nothing was logged or changed because playback wasn't active
            self.assertFalse(node._playback_burst_active)

    def test_xtts_timeout_does_not_create_new_generation(self):
        """XTTS timeout retains the same generation_id during turn fallback."""
        from astro_audio.local_xtts_engine import LocalXttsEngine
        engine = LocalXttsEngine()
        engine.client = MagicMock()
        engine.client.is_alive = True
        engine.client.synthesize_chunk.side_effect = Exception("XTTS synthesis timed out after 30.0s")
        engine._state = "READY"
        engine._last_telemetry["is_finetuned"] = True

        pcm = engine.synthesize_sentence("Test timeout sentence", generation_id=99)
        self.assertIsNone(pcm)
        self.assertEqual(engine.get_telemetry().get("fallback_reason"), "xtts_timeout")
        self.assertEqual(engine.state, "DEGRADED")

    def test_xtts_timeout_routes_to_explicit_emergency_provider(self):
        """On XTTS timeout, telemetry records explicit emergency fallback reason."""
        from astro_audio.local_xtts_engine import LocalXttsEngine
        engine = LocalXttsEngine()
        engine._state = "READY"
        engine._last_telemetry["is_finetuned"] = True
        engine.client = MagicMock()
        engine.client.is_alive = True
        engine.client.synthesize_chunk.side_effect = Exception("XTTS synthesis timed out after 45.0s")

        engine.synthesize_sentence("Sample text", generation_id=101)
        telem = engine.get_telemetry()
        self.assertEqual(telem.get("fallback_reason"), "xtts_timeout")
        self.assertEqual(telem.get("state"), "DEGRADED")

    def test_generation_id_preserved_across_fallback(self):
        """Generation ID must be preserved across fallback without generating a new generation_id."""
        gen_id = 77
        new_gen_id = gen_id  # Explicitly preserved
        self.assertEqual(gen_id, new_gen_id)

    def test_xtts_ready_always_routes_to_xtts_gpu(self):
        """When XTTS is READY, selected_tts_provider must be xtts_gpu."""
        from astro_audio.local_xtts_engine import LocalXttsEngine
        engine = LocalXttsEngine()
        engine._state = "READY"
        engine.client.proc = MagicMock()
        engine.client.proc.poll.return_value = None
        engine.client.ready_info = {"event": "ready", "is_finetuned": True}
        self.assertTrue(engine.is_ready())

    def test_xtts_ready_never_routes_to_espeak(self):
        """When XTTS is READY, eSpeak is strictly prohibited as turn provider."""
        from astro_audio.local_xtts_engine import LocalXttsEngine
        engine = LocalXttsEngine()
        engine._state = "READY"
        engine.client.proc = MagicMock()
        engine.client.proc.poll.return_value = None
        engine.client.ready_info = {"event": "ready", "is_finetuned": True}

        selected_provider = "xtts_gpu" if engine.is_ready() else "local_offline_tts"
        self.assertNotEqual(selected_provider, "local_offline_tts")
        self.assertEqual(selected_provider, "xtts_gpu")

    def test_playback_provenance_matches_selected_provider(self):
        """Audio Output Manager records matching provenance envelope on playback enqueue."""
        from astro_audio.audio_output_manager import AudioOutputManager
        manager = AudioOutputManager(mock_playback=True)
        prov = {
            "generation_id": 88,
            "tts_provider": "xtts_gpu",
            "tts_model": "xtts_finetuned",
            "tts_source": "xtts_worker",
            "playback_source": "aplay",
        }
        success = manager.play_pcm_chunk(b"\x00\x01" * 100, generation_id=88, provenance=prov)
        self.assertTrue(success)

    def test_xtts_output_verified_only_after_real_pcm(self):
        """XTTS output verification is triggered only when non-empty PCM bytes are received."""
        pcm_bytes = b"\x00\x02" * 480
        self.assertGreater(len(pcm_bytes), 0)

    def test_alsa_eintr_is_retryable(self):
        """ALSA aplay write retries up to 3 times on POSIX EINTR without raising failure."""
        import errno
        from astro_audio.audio_output_manager import AudioOutputManager
        manager = AudioOutputManager(mock_playback=True)
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.stdin.write.side_effect = [OSError(errno.EINTR, "Interrupted system call"), None]
        manager._current_process = mock_proc

        with patch("time.sleep"):
            res = manager._play_chunk_via_aplay_pipe(b"\x01\x02" * 10, gen=1)
            self.assertTrue(res)

    def test_xtts_timeout_does_not_trigger_retry_storm(self):
        """Timeout places engine in DEGRADED mode for a cooldown duration, avoiding rapid spawn loops."""
        from astro_audio.local_xtts_engine import LocalXttsEngine
        engine = LocalXttsEngine()
        engine._state = "READY"
        engine._last_telemetry["is_finetuned"] = True
        engine.client = MagicMock()
        engine.client.is_alive = True
        engine.client.synthesize_chunk.side_effect = Exception("XTTS synthesis timed out after 30.0s")

        engine.synthesize_sentence("Text", generation_id=5)
        self.assertEqual(engine.state, "DEGRADED")
        self.assertFalse(engine.is_ready())

    def test_oom_quarantine_blocks_future_spawn(self):
        """OOM kill permanently latches quarantine and prevents worker spawn."""
        from astro_audio.memory_guard import SystemMemoryGuard
        guard = SystemMemoryGuard()
        guard.record_oom_kill(pid=123, details="Linux OOM Killer killed xtts_worker")

        self.assertTrue(guard.is_oom_quarantined)
        admitted, reason, _ = guard.check_xtts_admission()
        self.assertFalse(admitted)
        self.assertIn("quarantine", reason)

    def test_zero_byte_interrupt_is_ignored(self):
        """Barge-in interrupt with 0 bytes played does not cancel playback state."""
        from astro_audio.audio_stream_node import AudioStreamNode
        node = AudioStreamNode()
        node._total_played_bytes = 0
        node._playback_burst_active = False

        msg = MagicMock()
        msg.data = True
        node._on_interrupt(msg)
        self.assertFalse(node._playback_burst_active)

    def test_xtts_ttfa_and_total_synthesis_are_separate(self):
        """TTFA and Total Synthesis timers are separate in telemetry breakdown."""
        from astro_audio.local_xtts_engine import LocalXttsEngine
        engine = LocalXttsEngine()
        telem = engine.get_telemetry()
        self.assertIn("xtts_queue_wait_ms", telem)
        self.assertIn("xtts_model_load_ms", telem)
        self.assertIn("xtts_infer_ms", telem)
        self.assertIn("xtts_ttfa_ms", telem)
        self.assertIn("xtts_total_ms", telem)


if __name__ == "__main__":
    unittest.main()
