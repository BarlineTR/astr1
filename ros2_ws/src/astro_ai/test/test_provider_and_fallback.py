#!/usr/bin/env python3
"""Comprehensive Unit & Regression Tests for ASTRO V1 Provider Registry, Repetition Guard, and Fallback Engine."""

import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

# Ensure paths
ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

from astro_ai.provider_registry import (
    ErrorClass,
    ModelCapability,
    ProviderError,
    ProviderRegistry,
    VERIFIED_GEMINI_SEEDS,
    VERIFIED_GROQ_SEEDS,
)
from astro_ai.repetition_guard import (
    RepetitionGuard,
    calculate_jaccard_similarity,
    normalize_turkish_text,
)
from astro_audio.xtts_client import XttsClient


class TestProviderRegistry(unittest.TestCase):
    """Tests for Provider & Model Capability Registry."""

    def setUp(self):
        self.registry = ProviderRegistry()

    def test_error_classification(self):
        # 1. Auth errors
        self.assertEqual(self.registry.classify_error(401, "Invalid API key"), ErrorClass.AUTHENTICATION_ERROR)
        self.assertEqual(self.registry.classify_error(403, "Forbidden"), ErrorClass.AUTHENTICATION_ERROR)

        # 2. 404 Model Not Found
        self.assertEqual(self.registry.classify_error(404, "Model not found"), ErrorClass.MODEL_NOT_FOUND)

        # 3. 429 Quota vs Rate Limit
        self.assertEqual(self.registry.classify_error(429, "You exceeded your current quota"), ErrorClass.QUOTA_EXHAUSTED)
        self.assertEqual(self.registry.classify_error(429, "Insufficient quota / credit"), ErrorClass.QUOTA_EXHAUSTED)
        self.assertEqual(self.registry.classify_error(429, "Rate limit reached for requests per minute"), ErrorClass.RATE_LIMITED)

        # 4. 400 Unsupported Model
        self.assertEqual(self.registry.classify_error(400, "The model `llama-old` does not exist or is deprecated"), ErrorClass.UNSUPPORTED_MODEL)

        # 5. 500 Server Errors
        self.assertEqual(self.registry.classify_error(500, "Internal Server Error"), ErrorClass.SERVER_ERROR)
        self.assertEqual(self.registry.classify_error(503, "Service Unavailable"), ErrorClass.SERVER_ERROR)

        # 6. Timeouts and Network Errors
        self.assertEqual(self.registry.classify_error(0, "Connection timed out", TimeoutError("timed out")), ErrorClass.TIMEOUT)

    def test_groq_discovery_and_capability_filtering(self):
        mock_response_json = {
            "data": [
                {"id": "whisper-large-v3", "active": True},
                {"id": "llama-guard-3-8b", "active": True},
                {"id": "llama-3.1-8b-instant", "active": True},
                {"id": "llama-3.3-70b-versatile", "active": True},
                {"id": "gemma2-9b-it", "active": True},
                {"id": "deprecated-model-old", "active": False},
            ]
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            discovered = self.registry.discover_groq_models("test_key")

        self.assertIn("llama-3.3-70b-versatile", discovered)
        self.assertIn("llama-3.1-8b-instant", discovered)
        self.assertIn("gemma2-9b-it", discovered)
        # Excluded models
        self.assertNotIn("whisper-large-v3", discovered)
        self.assertNotIn("llama-guard-3-8b", discovered)
        self.assertNotIn("deprecated-model-old", discovered)

    def test_gemini_discovery_and_filtering(self):
        mock_response_json = {
            "models": [
                {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-1.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
                {"name": "models/aqa", "supportedGenerationMethods": ["generateAnswer"]},
            ]
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            discovered = self.registry.discover_gemini_models("test_key")

        self.assertIn("gemini-2.0-flash", discovered)
        self.assertIn("gemini-1.5-flash", discovered)
        self.assertNotIn("text-embedding-004", discovered)
        self.assertNotIn("aqa", discovered)

    def test_blacklisting_and_no_retry_storm(self):
        self.registry.register_model(ModelCapability(provider="groq", model_id="broken-model-v1"))
        self.registry.register_model(ModelCapability(provider="groq", model_id="llama-3.1-8b-instant"))

        # 1. Model encounters 400 unsupported
        self.registry.record_error("groq", "broken-model-v1", ErrorClass.UNSUPPORTED_MODEL, "Model is deprecated")
        
        candidates = self.registry.get_candidate_models("groq")
        self.assertNotIn("broken-model-v1", candidates, "Blacklisted model must NOT be returned in candidates!")
        self.assertIn("llama-3.1-8b-instant", candidates)

        # 2. Rate limit cooldown test
        self.registry.record_error("groq", "llama-3.1-8b-instant", ErrorClass.RATE_LIMITED, "Rate limit reached")
        candidates_cooldown = self.registry.get_candidate_models("groq")
        self.assertNotIn("llama-3.1-8b-instant", candidates_cooldown, "Model under cooldown should be skipped temporarily")

        # Check model was not permanently blacklisted
        model_obj = self.registry.get_model("groq", "llama-3.1-8b-instant")
        self.assertFalse(model_obj.is_blacklisted, "Rate-limited model must not be permanently blacklisted")


class TestRepetitionGuard(unittest.TestCase):
    """Tests for Repetition Guard and Standalone Filler Rejection."""

    def setUp(self):
        self.guard = RepetitionGuard(history_size=5)

    def test_forbidden_standalone_fillers(self):
        fillers = [
            "Anladım.",
            "tamamdır",
            "Tamamdır!",
            "Bakıyorum hemen.",
            "Sistemlerimde kaydettim.",
            "Buradayım işte!",
            "Hallederiz rahat ol.",
            "dinliyorum",
        ]
        for f in fillers:
            self.assertTrue(
                self.guard.is_forbidden_standalone_filler(f),
                f"'{f}' should be rejected as a forbidden standalone filler!"
            )

    def test_allowed_contextual_sentences(self):
        valid_sentences = [
            "Bugün Ahlat'ta hava oldukça açık ve güneşli, dışarı çıkmak için harika bir gün.",
            "Robot Astro olarak kameralarımla çevreyi tarıyorum ve projeye devam ediyorum.",
            "Bahsettiğin düğün salonu ve kafe konusunu dinledim, detayları anlat bakalım.",
            "Videoyu beğenip kanala abone olmayı unutmayın, desteğiniz bizim için değerli!",
        ]
        for s in valid_sentences:
            self.assertFalse(
                self.guard.is_forbidden_standalone_filler(s),
                f"'{s}' is a valid sentence and should NOT be rejected as a filler!"
            )

    def test_repetition_detection(self):
        sentence = "Robotik sistemlerim hazır ve seni dinliyor!"
        valid, reason = self.guard.check_and_record(sentence)
        self.assertTrue(valid)

        # Immediate repetition of identical sentence
        valid_dup, reason_dup = self.guard.check_and_record(sentence)
        self.assertFalse(valid_dup)
        self.assertEqual(reason_dup, "repetitive_response")

        # Slight punctuation variation should also be caught
        valid_var, reason_var = self.guard.check_and_record("Robotik sistemlerim hazır ve seni dinliyor.")
        self.assertFalse(valid_var)
        self.assertEqual(reason_var, "repetitive_response")


class TestSingleOwnerWorkerLifecycle(unittest.TestCase):
    """Tests for Single-Owner XTTS Worker Process Lifecycle."""

    def test_single_owner_stop_and_cleanup(self):
        client = XttsClient(speaker_wav="dummy.wav")
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.poll.side_effect = [None, None, 0]  # running, running, terminated
        client.proc = mock_proc

        client.stop()
        self.assertIsNone(client.proc, "Client proc must be cleared to None after stop()")
        mock_proc.terminate.assert_called()

    def test_double_start_prevents_multiple_workers(self):
        client = XttsClient(speaker_wav="dummy.wav")
        mock_proc1 = MagicMock()
        mock_proc1.pid = 11111
        mock_proc1.poll.return_value = None  # alive
        client.proc = mock_proc1
        client.info = {"ready": True}

        # Second start() when alive and ready should NOOP and not spawn new process
        with patch("subprocess.Popen") as mock_popen:
            client.start()
            mock_popen.assert_not_called()
        self.assertEqual(client.proc.pid, 11111)


class TestProductionEdgeScenarios(unittest.TestCase):
    """Tests simulating real-world hardware & network failure scenarios."""

    def setUp(self):
        self.registry = ProviderRegistry()
        self.guard = RepetitionGuard()

    def test_scenario_groq_unsupported_model_switch_without_retry_storm(self):
        """Scenario E: Groq model 400 unsupported -> blacklist immediately, no retry storm, switch to next model."""
        self.registry.register_model(ModelCapability(provider="groq", model_id="llama-unsupported-v1"))
        self.registry.register_model(ModelCapability(provider="groq", model_id="llama-3.1-8b-instant"))

        # First call to llama-unsupported-v1 raises 400
        http_error = urllib.error.HTTPError(
            url="https://api.groq.com",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": {"message": "The model `llama-unsupported-v1` does not exist or is deprecated"}}')
        )

        with patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(ProviderError) as cm:
                list(self.registry.stream_groq_completion("key", "llama-unsupported-v1", [{"role": "user", "content": "hi"}]))
            self.assertEqual(cm.exception.error_class, ErrorClass.UNSUPPORTED_MODEL)

        # Verify model is blacklisted and will NOT be queried again
        candidates = self.registry.get_candidate_models("groq")
        self.assertNotIn("llama-unsupported-v1", candidates)
        self.assertIn("llama-3.1-8b-instant", candidates)

    def test_scenario_gemini_unsupported_model_fallback(self):
        """Scenario F: Gemini model 404 -> blacklist immediately, fallback to verified model."""
        self.registry.register_model(ModelCapability(provider="gemini", model_id="gemini-old-broken"))
        self.registry.register_model(ModelCapability(provider="gemini", model_id="gemini-2.0-flash"))

        http_error = urllib.error.HTTPError(
            url="https://generativelanguage.googleapis.com",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": {"message": "models/gemini-old-broken is not found"}}')
        )

        with patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(ProviderError) as cm:
                self.registry.generate_gemini_content("key", "gemini-old-broken", "prompt", [{"role": "user", "content": "hi"}])
            self.assertEqual(cm.exception.error_class, ErrorClass.MODEL_NOT_FOUND)

        candidates = self.registry.get_candidate_models("gemini")
        self.assertNotIn("gemini-old-broken", candidates)
        self.assertIn("gemini-2.0-flash", candidates)

    def test_scenario_quota_exhausted_failover(self):
        """Scenario B: Realtime / Provider 429 Quota exhausted classified correctly."""
        http_error = urllib.error.HTTPError(
            url="https://api.groq.com",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": {"message": "You exceeded your current quota, please check your plan and billing details."}}')
        )

        with patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(ProviderError) as cm:
                list(self.registry.stream_groq_completion("key", "llama-3.1-8b-instant", []))
            self.assertEqual(cm.exception.error_class, ErrorClass.QUOTA_EXHAUSTED)

    def test_scenario_rate_limit_backoff(self):
        """Scenario: 429 Rate limit applies cooldown without permanent blacklist."""
        http_error = urllib.error.HTTPError(
            url="https://api.groq.com",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=MagicMock(read=lambda: b'{"error": {"message": "Rate limit reached for requests per minute (RPM)"}}')
        )

        with patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(ProviderError) as cm:
                list(self.registry.stream_groq_completion("key", "llama-3.3-70b-versatile", []))
            self.assertEqual(cm.exception.error_class, ErrorClass.RATE_LIMITED)

        # Model is in cooldown, but NOT blacklisted
        model = self.registry.get_model("groq", "llama-3.3-70b-versatile")
        self.assertFalse(model.is_blacklisted)
        self.assertGreater(model.cooldown_until, time.monotonic())


if __name__ == "__main__":
    unittest.main()
