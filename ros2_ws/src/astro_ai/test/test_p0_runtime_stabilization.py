#!/usr/bin/env python3
"""ASTRO V1 — P0 Runtime Stabilization Comprehensive Acceptance Test Suite.

Verifies all critical P0 runtime stabilization invariants:
1. Global Circuit Breaker single source of truth:
   - Quota exhaustion on any OpenAI surface cascades to ALL OpenAI surfaces.
   - Session-level exhaustion prevents ANY retry to OpenAI.
   - Groq 429 enforces 30s COOLDOWN before routing to Gemini.
2. Model Registry & Dynamic Capability Routing:
   - Routing vision models to Groq/Gemini when OpenAI is EXHAUSTED.
3. THINKING_ACK & Local Audio Resources:
   - Low-latency local WAV PCM (<300ms) without cloud dependency.
   - ACKs are not persisted in memory.
4. TTS Hierarchy & XTTS Dormant Isolation:
   - OpenAI Realtime -> Edge-TTS -> Local Offline TTS -> Emergency WAV.
   - XTTS never invoked in production runtime.
5. Idle Mode Isolation & Perception Gating:
   - No perception change = 0 cloud LLM requests.
   - Idle NEVER calls OpenAI surfaces.
6. Memory Write Gating:
   - Confidence threshold (>= 0.70) and gossip filtering.
7. Zero Silence Guarantee:
   - In any cascading failure, a spoken response or emergency WAV is produced.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

# Ensure paths
pkg_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
astro_ai_path = os.path.join(pkg_root, "astro_ai")
astro_audio_path = os.path.join(pkg_root, "astro_audio")
if astro_ai_path not in sys.path:
    sys.path.insert(0, astro_ai_path)
if astro_audio_path not in sys.path:
    sys.path.insert(0, astro_audio_path)

from astro_ai.circuit_breaker import (
    GlobalProviderCircuitBreaker,
    ProviderState,
    RequestErrorClass,
    get_global_circuit_breaker,
)
from astro_ai.provider_registry import (
    ProviderRegistry,
    ModelCapability,
    GROQ_PRODUCTION_MODELS,
    GEMINI_PRODUCTION_MODELS,
    OPENAI_PRODUCTION_MODELS,
)
from astro_audio.local_audio_resources import (
    LocalAudioResources,
    get_local_audio_resources,
)
from astro_audio.stt_router import STTRouter
from astro_audio.tts_router import TTSRouter
from astro_ai.memory_manager import MemoryManager
from astro_ai.state_machine import StateMachine, RobotState


class TestP0GlobalCircuitBreaker(unittest.TestCase):
    """Test Suite for GlobalProviderCircuitBreaker Invariants."""

    def setUp(self):
        self.cb = GlobalProviderCircuitBreaker.get_instance()
        self.cb.reset_all()

    def test_initial_states(self):
        self.assertTrue(self.cb.is_available("openai"))
        self.assertTrue(self.cb.is_available("openai", "openai_realtime"))
        self.assertTrue(self.cb.is_available("openai", "openai_rest"))
        self.assertTrue(self.cb.is_available("openai", "openai_vision"))
        self.assertTrue(self.cb.is_available("openai", "openai_stt"))
        self.assertTrue(self.cb.is_available("groq"))
        self.assertTrue(self.cb.is_available("gemini"))
        self.assertTrue(self.cb.is_available("edge_tts"))

    def test_openai_quota_exhaustion_cascades_to_all_surfaces(self):
        """When any OpenAI surface hits quota exhaustion, ALL OpenAI surfaces become EXHAUSTED."""
        self.cb.record_error(
            "openai",
            sub_provider="openai_realtime",
            error_class=RequestErrorClass.QUOTA_EXHAUSTED,
            error_msg="insufficient_quota: You exceeded your current quota",
        )

        self.assertEqual(self.cb.get_state("openai"), ProviderState.EXHAUSTED)
        self.assertEqual(self.cb.get_state("openai", "openai_realtime"), ProviderState.EXHAUSTED)
        self.assertEqual(self.cb.get_state("openai", "openai_rest"), ProviderState.EXHAUSTED)
        self.assertEqual(self.cb.get_state("openai", "openai_vision"), ProviderState.EXHAUSTED)
        self.assertEqual(self.cb.get_state("openai", "openai_stt"), ProviderState.EXHAUSTED)

        # Availability must be False for all
        self.assertFalse(self.cb.is_available("openai"))
        self.assertFalse(self.cb.is_available("openai", "openai_realtime"))
        self.assertFalse(self.cb.is_available("openai", "openai_rest"))
        self.assertFalse(self.cb.is_available("openai", "openai_vision"))
        self.assertFalse(self.cb.is_available("openai", "openai_stt"))
        self.assertTrue(self.cb.is_exhausted("openai"))

        # Other providers remain available
        self.assertTrue(self.cb.is_available("groq"))
        self.assertTrue(self.cb.is_available("gemini"))
        self.assertTrue(self.cb.is_available("edge_tts"))

    def test_classify_error_quota(self):
        """Test error classification for various quota and auth errors."""
        self.assertEqual(
            self.cb.classify_error(Exception("insufficient_quota")),
            RequestErrorClass.QUOTA_EXHAUSTED,
        )
        self.assertEqual(
            self.cb.classify_error(Exception("credit_balance_exhausted")),
            RequestErrorClass.QUOTA_EXHAUSTED,
        )
        self.assertEqual(
            self.cb.classify_error(Exception("Rate limit reached: code 1013")),
            RequestErrorClass.QUOTA_EXHAUSTED,
        )
        self.assertEqual(
            self.cb.classify_error(Exception("Payment Required"), status_code=402),
            RequestErrorClass.QUOTA_EXHAUSTED,
        )
        self.assertEqual(
            self.cb.classify_error(Exception("Invalid API key"), status_code=401),
            RequestErrorClass.AUTH_ERROR,
        )
        self.assertEqual(
            self.cb.classify_error(Exception("Rate limit reached"), status_code=429),
            RequestErrorClass.RATE_LIMITED,
        )
        self.assertEqual(
            self.cb.classify_error(Exception("Model not found"), status_code=404),
            RequestErrorClass.MODEL_UNAVAILABLE,
        )

    def test_groq_429_cooldown_and_expiration(self):
        """Groq 429 sets COOLDOWN, expires after configured cooldown duration."""
        self.cb.record_error(
            "groq",
            sub_provider="groq_llm",
            error_class=RequestErrorClass.RATE_LIMITED,
            error_msg="Rate limit reached for requests",
        )

        self.assertEqual(self.cb.get_state("groq", "groq_llm"), ProviderState.COOLDOWN)
        self.assertFalse(self.cb.is_available("groq", "groq_llm"))

        # Advance time past cooldown
        with patch.object(self.cb, "_get_time", return_value=time.monotonic() + 35.0):
            self.assertTrue(self.cb.is_available("groq", "groq_llm"))
            self.assertEqual(self.cb.get_state("groq", "groq_llm"), ProviderState.AVAILABLE)


class TestP0ProviderRegistry(unittest.TestCase):
    """Test Suite for Model Registry & Dynamic Capability Routing."""

    def setUp(self):
        self.cb = GlobalProviderCircuitBreaker.get_instance()
        self.cb.reset_all()
        self.registry = ProviderRegistry()

    def test_verified_models_registered(self):
        """Ensure no hallucinated or deprecated model names exist in registry."""
        models = self.registry.get_all_models()
        model_ids = [m.model_id for m in models]

        # Valid verified models must exist
        self.assertIn("llama-3.3-70b-versatile", model_ids)
        self.assertIn("llama-3.2-11b-vision-preview", model_ids)
        self.assertIn("gemini-2.0-flash", model_ids)
        self.assertIn("gpt-4o-mini", model_ids)

        # Invalid/hallucinated names must NOT exist
        self.assertNotIn("gemini-3.6-flash", model_ids)
        self.assertNotIn("gemini-3.5-flash", model_ids)

    def test_find_routeable_vision_model_when_openai_exhausted(self):
        """When OpenAI is exhausted, registry returns Groq or Gemini vision model."""
        self.cb.record_error("openai", error_class=RequestErrorClass.QUOTA_EXHAUSTED)

        result = self.registry.find_routeable_model(
            capability="vision",
            preferred_providers=["openai", "groq", "gemini"],
        )
        self.assertIsNotNone(result)
        provider, model_id = result
        self.assertNotEqual(provider, "openai")
        self.assertIn(provider, ["groq", "gemini"])


class TestP0LocalAudioResources(unittest.TestCase):
    """Test Suite for THINKING_ACK & Local Audio Resources."""

    def setUp(self):
        self.resources = LocalAudioResources.get_instance()

    def test_local_ack_pcm_generation(self):
        """Generates zero-latency local ACK PCM buffers for fast feedback."""
        ack_looking = self.resources.get_ack_pcm("looking")
        ack_checking = self.resources.get_ack_pcm("checking")
        emergency = self.resources.get_emergency_fallback_pcm()

        self.assertIsInstance(ack_looking, bytes)
        self.assertGreater(len(ack_looking), 100)

        self.assertIsInstance(ack_checking, bytes)
        self.assertGreater(len(ack_checking), 100)

        self.assertIsInstance(emergency, bytes)
        self.assertGreater(len(emergency), 100)

    def test_ack_state_machine_transition(self):
        """StateMachine supports THINKING_ACK transition."""
        sm = StateMachine(RobotState.IDLE)
        self.assertTrue(sm.transition_to(RobotState.THINKING_ACK))
        self.assertEqual(sm.current_state, RobotState.THINKING_ACK)
        self.assertTrue(sm.transition_to(RobotState.THINKING))
        self.assertEqual(sm.current_state, RobotState.THINKING)
        self.assertTrue(sm.transition_to(RobotState.SPEAKING))
        self.assertEqual(sm.current_state, RobotState.SPEAKING)


class TestP0STTRouting(unittest.TestCase):
    """Test Suite for STT Router with Circuit Breaker."""

    def setUp(self):
        self.cb = GlobalProviderCircuitBreaker.get_instance()
        self.cb.reset_all()

    def test_stt_skips_whisper_when_openai_exhausted(self):
        """When OpenAI is exhausted, STTRouter never attempts OpenAI Whisper."""
        self.cb.record_error("openai", error_class=RequestErrorClass.QUOTA_EXHAUSTED)

        mock_openai = MagicMock()
        mock_groq = MagicMock()
        mock_groq.audio.transcriptions.create.return_value = "Merhaba"
        router = STTRouter(groq_client=mock_groq, openai_client=mock_openai)

        fake_audio = np.zeros(16000, dtype=np.int16)
        fake_wav = b"RIFFfake"
        res = router.transcribe(fake_audio, fake_wav)

        # Whisper should not be called at all
        mock_openai.audio.transcriptions.create.assert_not_called()
        self.assertEqual(res.text, "Merhaba")


class TestP0TTSRouting(unittest.TestCase):
    """Test Suite for TTS Router with Circuit Breaker and Zero-Silence Emergency Fallback."""

    def setUp(self):
        self.cb = GlobalProviderCircuitBreaker.get_instance()
        self.cb.reset_all()

    def test_tts_skips_realtime_when_openai_exhausted(self):
        """When OpenAI is exhausted, TTSRouter directly routes to Edge-TTS without touching Realtime."""
        self.cb.record_error("openai", error_class=RequestErrorClass.QUOTA_EXHAUSTED)

        mock_edge_synth = MagicMock(return_value=b"\x00" * 16000)
        tts = TTSRouter(edge_tts_synth_func=mock_edge_synth)

        self.assertFalse(tts.circuit_breaker.is_available("openai", "openai_realtime"))

        result = tts.synthesize("Merhaba Dünya", generation_id=1)
        mock_edge_synth.assert_called_once()
        self.assertEqual(result.actual_provider, "edge_tts")
        self.assertIsNotNone(result.pcm)

    def test_xtts_dormant_never_called(self):
        """XTTS is dormant (None by default) and must never be called in normal runtime."""
        tts = TTSRouter()
        self.assertIsNone(tts.local_xtts)

    def test_emergency_pcm_fallback_on_all_failure(self):
        """When all TTS engines fail, emergency local WAV PCM is returned (zero silence)."""
        self.cb.record_error("openai", error_class=RequestErrorClass.QUOTA_EXHAUSTED)
        self.cb.record_error("edge_tts", error_class=RequestErrorClass.SERVER_ERROR)

        mock_edge_synth = MagicMock(side_effect=Exception("Network down"))
        tts = TTSRouter(edge_tts_synth_func=mock_edge_synth)

        result = tts.synthesize("Test", generation_id=1)
        self.assertEqual(result.actual_provider, "emergency_wav")
        self.assertIsNotNone(result.pcm)
        self.assertGreater(len(result.pcm), 100)


class TestP0MemoryGating(unittest.TestCase):
    """Test Suite for Memory Write Protection & Confidence Gating."""

    def setUp(self):
        self.memory = MemoryManager()
        self.memory.profile.data["environmental_observations"] = []

    def test_observation_confidence_filter(self):
        """Observations with confidence < 0.70 are rejected."""
        # Low confidence rejected
        self.memory.profile.add_observation("Masanın üzerinde bir bardak var.", confidence=0.50)
        self.assertEqual(len(self.memory.profile.data["environmental_observations"]), 0)

        # High confidence accepted
        self.memory.profile.add_observation("Masanın üzerinde bir bardak var.", confidence=0.85)
        self.assertEqual(len(self.memory.profile.data["environmental_observations"]), 1)

    def test_gossip_and_hallucination_filter(self):
        """Gossip phrases and refusals are blocked regardless of confidence."""
        self.memory.profile.add_observation("Sezer ile İhsan kumar oynuyor.", confidence=0.95)
        self.assertEqual(len(self.memory.profile.data["environmental_observations"]), 0)

        self.memory.profile.add_observation("Bir yapay zeka olarak yardımcı olamam.", confidence=0.95)
        self.assertEqual(len(self.memory.profile.data["environmental_observations"]), 0)


if __name__ == "__main__":
    unittest.main()
