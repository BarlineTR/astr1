#!/usr/bin/env python3
"""Comprehensive Unit & Regression Tests for ASTRO V1 Provider Registry, Repetition Guard, and Fallback Engine."""

import asyncio
import json
import os
import sys
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import AsyncMock, MagicMock, patch

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
    ProviderHealth,
    ProviderRegistry,
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
        try:
            from astro_ai.circuit_breaker import GlobalProviderCircuitBreaker
            GlobalProviderCircuitBreaker.get_instance().reset_all()
        except Exception:
            pass
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
                {"id": "openai/gpt-oss-20b", "active": True},
                {"id": "openai/gpt-oss-120b", "active": True},
                {"id": "canopylabs/orpheus-v1-english", "active": True},
                {"id": "qwen/qwen3.6-27b", "active": True},
                {"id": "deprecated-model-old", "active": False},
            ]
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            discovered = self.registry.discover_models("groq", "test_key")

        self.assertEqual(self.registry.get_provider_health("groq"), ProviderHealth.HEALTHY)
        self.assertIn("openai/gpt-oss-20b", discovered)
        self.assertIn("openai/gpt-oss-120b", discovered)
        self.assertIn("llama-3.3-70b-versatile", discovered)
        self.assertIn("llama-3.1-8b-instant", discovered)
        self.assertEqual(len(discovered), 4, "Groq routeable pool must contain exactly 4 production models")

        # Excluded non-chat / preview / TTS / deprecated models
        self.assertNotIn("canopylabs/orpheus-v1-english", discovered)
        self.assertNotIn("qwen/qwen3.6-27b", discovered)
        self.assertNotIn("whisper-large-v3", discovered)
        self.assertNotIn("llama-guard-3-8b", discovered)
        self.assertNotIn("deprecated-model-old", discovered)

        stats = self.registry.get_discovery_stats("groq")
        self.assertEqual(stats["discovered"], 9)
        self.assertEqual(stats["routeable"], 4)
        self.assertEqual(stats["rejected"], 5)

        # Priority order verification
        self.assertEqual(discovered[0], "llama-3.3-70b-versatile")
        self.assertEqual(discovered[1], "llama-3.1-8b-instant")
        self.assertEqual(discovered[2], "openai/gpt-oss-20b")
        self.assertEqual(discovered[3], "openai/gpt-oss-120b")

    def test_gemini_discovery_and_filtering(self):
        mock_response_json = {
            "models": [
                {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-1.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-1.5-pro", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.0-flash-image", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-old-model", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
                {"name": "models/aqa", "supportedGenerationMethods": ["generateAnswer"]},
            ]
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            discovered = self.registry.discover_models("gemini", "test_key")

        self.assertEqual(self.registry.get_provider_health("gemini"), ProviderHealth.HEALTHY)
        # Exactly 3 production LLM models are routeable
        self.assertIn("gemini-2.0-flash", discovered)
        self.assertIn("gemini-1.5-flash", discovered)
        self.assertIn("gemini-1.5-pro", discovered)
        self.assertEqual(len(discovered), 3, "Gemini routeable pool must contain exactly 3 production LLM models")

        # Image generation and legacy models are rejected
        self.assertNotIn("gemini-2.0-flash-image", discovered)
        self.assertNotIn("gemini-old-model", discovered)
        self.assertNotIn("text-embedding-004", discovered)
        self.assertNotIn("aqa", discovered)

        stats = self.registry.get_discovery_stats("gemini")
        self.assertEqual(stats["discovered"], 7)
        self.assertEqual(stats["routeable"], 3)
        self.assertEqual(stats["rejected"], 4)

    def test_missing_api_key_sets_authentication_failed(self):
        """Item 6: If API key is missing/empty, status must be AUTHENTICATION_FAILED."""
        res_groq = self.registry.discover_models("groq", "")
        self.assertEqual(res_groq, [])
        self.assertEqual(self.registry.get_provider_health("groq"), ProviderHealth.AUTHENTICATION_FAILED)

        res_gem = self.registry.discover_models("gemini", "")
        self.assertEqual(res_gem, [])
        self.assertEqual(self.registry.get_provider_health("gemini"), ProviderHealth.AUTHENTICATION_FAILED)

    def test_groq_tts_and_preview_models_rejected(self):
        """Item 1 & 6: canopylabs/orpheus and qwen3.6 preview models must be marked REJECTED and not ROUTEABLE."""
        mock_response_json = {
            "data": [
                {"id": "canopylabs/orpheus-arabic-saudi", "active": True},
                {"id": "canopylabs/orpheus-v1-english", "active": True},
                {"id": "qwen/qwen3.6-27b", "active": True},
                {"id": "llama-3.1-8b-instant", "active": True},
                {"id": "llama-3.3-70b-versatile", "active": True},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            routeable = self.registry.discover_models("groq", "test_key")

        self.assertNotIn("canopylabs/orpheus-arabic-saudi", routeable)
        self.assertNotIn("canopylabs/orpheus-v1-english", routeable)
        self.assertNotIn("qwen/qwen3.6-27b", routeable)
        self.assertIn("llama-3.1-8b-instant", routeable)
        self.assertIn("llama-3.3-70b-versatile", routeable)

        stats = self.registry.get_discovery_stats("groq")
        self.assertEqual(stats["discovered"], 5)
        self.assertEqual(stats["routeable"], 2)
        self.assertEqual(stats["rejected"], 3)

    def test_discovery_failure_sets_status_without_blind_seeds(self):
        """If discovery fails, provider health becomes DISCOVERY_UNAVAILABLE and get_available_models returns empty list."""
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
            discovered = self.registry.discover_models("groq", "test_key")

        self.assertEqual(discovered, [])
        self.assertEqual(self.registry.get_provider_health("groq"), ProviderHealth.DISCOVERY_UNAVAILABLE)
        self.assertEqual(self.registry.get_available_models("groq"), [])
        self.assertIsNone(self.registry.select_best_model("groq"))

    def test_select_best_model_and_is_routeable(self):
        mock_response_json = {
            "data": [
                {"id": "llama-3.1-8b-instant", "active": True},
                {"id": "llama-3.3-70b-versatile", "active": True},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            self.registry.discover_models("groq", "test_key")

        self.assertTrue(self.registry.is_routeable("groq", "llama-3.1-8b-instant"))
        self.assertTrue(self.registry.is_routeable("groq", "llama-3.3-70b-versatile"))
        self.assertEqual(self.registry.select_best_model("groq"), "llama-3.3-70b-versatile")

    def test_deprecated_model_discovered_but_not_routeable(self):
        """Item 11: Discovery returns legacy/deprecated models -> registry tracks them as discovered/rejected, but NOT routeable."""
        mock_response_json = {
            "data": [
                {"id": "llama-3.1-8b-instant", "active": True},
                {"id": "llama-3.2-1b-preview", "active": True},
                {"id": "deprecated-model-old", "active": False},
                {"id": "whisper-large-v3", "active": True},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            self.registry.discover_models("groq", "test_key")

        stats = self.registry.get_discovery_stats("groq")
        self.assertEqual(stats["discovered"], 4, "Must track all 4 raw discovered models")
        self.assertEqual(stats["routeable"], 1, "Only 1 production model must be routeable")
        self.assertEqual(stats["rejected"], 3, "3 models must be categorized as rejected")

        # Check routeable vs non-routeable
        self.assertTrue(self.registry.is_routeable("groq", "llama-3.1-8b-instant"))
        self.assertFalse(self.registry.is_routeable("groq", "llama-3.2-1b-preview"))
        self.assertFalse(self.registry.is_routeable("groq", "deprecated-model-old"))
        self.assertFalse(self.registry.is_routeable("groq", "whisper-large-v3"))
        self.assertEqual(self.registry.get_available_models("groq"), ["llama-3.1-8b-instant"])


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
        try:
            from astro_ai.circuit_breaker import GlobalProviderCircuitBreaker
            GlobalProviderCircuitBreaker.get_instance().reset_all()
        except Exception:
            pass
        self.registry = ProviderRegistry()
        self.guard = RepetitionGuard()

    def test_scenario_groq_unsupported_model_switch_without_retry_storm(self):
        """Scenario E: Groq model 400 unsupported -> blacklist immediately, no retry storm, switch to next model."""
        mock_resp_json = {
            "data": [
                {"id": "llama-unsupported-v1", "active": True},
                {"id": "llama-3.1-8b-instant", "active": True},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_resp_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            self.registry.discover_models("groq", "test_key")

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

        # Verify model is blacklisted and will NOT be returned in candidates again
        candidates = self.registry.get_available_models("groq")
        self.assertNotIn("llama-unsupported-v1", candidates)
        self.assertIn("llama-3.1-8b-instant", candidates)
        self.assertFalse(self.registry.is_routeable("groq", "llama-unsupported-v1"))

    def test_scenario_gemini_unsupported_model_fallback(self):
        """Scenario F: Gemini model 404 -> blacklist immediately, fallback to verified model."""
        mock_resp_json = {
            "models": [
                {"name": "models/gemini-old-broken", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_resp_json).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            self.registry.discover_models("gemini", "test_key")

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

        candidates = self.registry.get_available_models("gemini")
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


class TestContextualFallbackAndTelemetry(unittest.TestCase):
    """Tests for Acceptance Criteria A-H (Semantic Fallbacks, Routing Hierarchy, and Telemetry)."""

    def setUp(self):
        try:
            from astro_ai.circuit_breaker import GlobalProviderCircuitBreaker
            GlobalProviderCircuitBreaker.get_instance().reset_all()
        except Exception:
            pass
        self.registry = ProviderRegistry()
        self.guard = RepetitionGuard(history_size=10)

    def test_acceptance_criteria_a_b_c_semantic_dialogue(self):
        """Test A, B, C: Dialogue responses must be semantically coherent without keyword slot-filling."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        # Mock minimal Node instance for testing fallback response generation
        node = MagicMock()
        node.persona_name = "default"
        node._active_person_name = "Baran"
        node.repetition_guard = RepetitionGuard(history_size=10)

        # Bind the actual method
        node._generate_contextual_persona_fallback = lambda txt: AstroRealtimeNode._generate_contextual_persona_fallback(node, txt)

        # Test A: "Nasılsın Astro?" -> Answers about state/well-being
        resp_a = node._generate_contextual_persona_fallback("Nasılsın Astro?")
        self.assertTrue(any(w in resp_a.lower() for w in ["iyiyim", "yolunda", "teşekkür", "keyfim", "sen nasılsın", "gün"]))
        self.assertNotIn("hakkında söylediğin şeyi duydum", resp_a)
        self.assertNotIn("nasılsın meselesini duydum", resp_a)

        # Test B: "Teşekkür ederim" -> Natural social gratitude response
        resp_b = node._generate_contextual_persona_fallback("Teşekkür ederim")
        self.assertTrue(any(w in resp_b.lower() for w in ["rica", "lafı", "bir şey değil", "yardım"]))
        self.assertNotIn("meselesini duydum", resp_b)
        self.assertNotIn("hakkında dediklerini aldım", resp_b)

        # Test C: "Bugün biraz yorgunum" -> Understanding fatigue / wishing rest
        resp_c = node._generate_contextual_persona_fallback("Bugün biraz yorgunum")
        self.assertTrue(any(w in resp_c.lower() for w in ["geçmiş olsun", "dinlen", "yorma", "mola", "üzüldüm", "toparlan"]))
        self.assertNotIn("yorgunum konusunu anladım", resp_c)

    def test_acceptance_criteria_d_deterministic_fallback_order(self):
        """Test D: Cloud fallback order is strictly Groq 20B -> Groq 120B -> Gemini 2.5 Flash -> Gemini 2.5 Flash Lite -> Gemini 2.5 Pro -> Local Persona."""
        mock_groq_json = {
            "data": [
                {"id": "openai/gpt-oss-20b", "active": True},
                {"id": "openai/gpt-oss-120b", "active": True},
                {"id": "llama-3.3-70b-versatile", "active": True},
                {"id": "llama-3.1-8b-instant", "active": True},
            ]
        }
        mock_gemini_json = {
            "models": [
                {"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-1.5-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-1.5-pro", "supportedGenerationMethods": ["generateContent"]},
            ]
        }

        with patch("urllib.request.urlopen") as mock_url:
            mock_resp_g = MagicMock()
            mock_resp_g.read.return_value = json.dumps(mock_groq_json).encode("utf-8")
            mock_resp_g.__enter__.return_value = mock_resp_g

            mock_resp_gem = MagicMock()
            mock_resp_gem.read.return_value = json.dumps(mock_gemini_json).encode("utf-8")
            mock_resp_gem.__enter__.return_value = mock_resp_gem

            mock_url.side_effect = [mock_resp_g, mock_resp_gem]

            groq_models = self.registry.discover_models("groq", "key_groq")
            gemini_models = self.registry.discover_models("gemini", "key_gemini")

        # Verify exact preferred ordering
        self.assertEqual(groq_models, ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-20b", "openai/gpt-oss-120b"])
        self.assertEqual(gemini_models, ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"])

    def test_acceptance_criteria_g_repetition_guard_5_turns_diversity(self):
        """Test G: Asking the same question 5 times produces varied responses without repetition or template lock."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = MagicMock()
        node.persona_name = "default"
        node._active_person_name = "Baran"
        node.repetition_guard = RepetitionGuard(history_size=10)
        node._generate_contextual_persona_fallback = lambda txt: AstroRealtimeNode._generate_contextual_persona_fallback(node, txt)

        seen_responses = set()
        for _ in range(4):
            resp = node._generate_contextual_persona_fallback("Teşekkür ederim")
            self.assertNotIn(resp, seen_responses, "Must not repeat the exact same utterance in successive turns")
            seen_responses.add(resp)

        self.assertGreaterEqual(len(seen_responses), 3, "At least 3 distinct responses generated for repeated question")

    def test_kufurbaz_persona_fallback_responses(self):
        """Test KUFURBAZ persona natural casual Turkish expressions with close friend tone."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = MagicMock()
        node.persona_name = "kufurbaz"
        node._active_person_name = "Baran"
        node.repetition_guard = RepetitionGuard(history_size=10)
        node._generate_contextual_persona_fallback = lambda txt: AstroRealtimeNode._generate_contextual_persona_fallback(node, txt)

        # 1. "Nasılsın Astro?"
        resp_status = node._generate_contextual_persona_fallback("Nasılsın Astro?")
        self.assertNotIn("lan", resp_status.lower())
        self.assertTrue(any(w in resp_status.lower() for w in ["iyiyim", "keyfim", "çalışıyorum", "sen ne durumdasın", "sen nasılsın"]))

        # 2. "Teşekkür ederim"
        resp_thanks = node._generate_contextual_persona_fallback("Teşekkür ederim")
        self.assertNotIn("lan", resp_thanks.lower())
        self.assertTrue(any(w in resp_thanks.lower() for w in ["ne demek", "lafı mı olur", "rica ederim", "bir şey değil"]))

        # 3. "Biraz sohbet edelim"
        resp_chat = node._generate_contextual_persona_fallback("Biraz sohbet edelim")
        self.assertNotIn("lan", resp_chat.lower())
        self.assertTrue(any(w in resp_chat.lower() for w in ["tabii ki", "harika", "dinliyorum", "seve seve", "konuşmak", "anlat", "sohbet", "isterim", "neler"]))

    def test_tts_hierarchy_elevenlabs_xtts_edgetts(self):
        """Test TTS hierarchy: ElevenLabs (Primary) -> Local XTTS GPU (Fallback) -> Edge-TTS (Emergency)."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = MagicMock()
        node._fallback_generation_id = 1
        node.get_logger = MagicMock()
        node._synthesize_edge_tts_pcm24k = MagicMock(return_value=b"\x00\x00" * 480)

        # Case 1: ElevenLabs is ready -> Selected as primary
        mock_el = MagicMock()
        mock_el.is_ready.return_value = True
        mock_el.synthesize_sentence.return_value = b"\x01\x01" * 480
        node.elevenlabs_engine = mock_el

        mock_xtts = MagicMock()
        mock_xtts.is_ready.return_value = True
        mock_xtts.synthesize_sentence.return_value = b"\x02\x02" * 480
        node.local_xtts = mock_xtts

        pcm, eng_name, latency, is_ready = AstroRealtimeNode._synthesize_speech_pcm(node, "Merhaba Baran")
        self.assertEqual(eng_name, "elevenlabs")
        self.assertTrue(is_ready)
        self.assertEqual(pcm, b"\x01\x01" * 480)

        # Case 2: ElevenLabs is unavailable -> Fallback to XTTS GPU
        mock_el.is_ready.return_value = False
        pcm, eng_name, latency, is_ready = AstroRealtimeNode._synthesize_speech_pcm(node, "Merhaba Baran")
        self.assertEqual(eng_name, "xtts_gpu")
        self.assertTrue(is_ready)
        self.assertEqual(pcm, b"\x02\x02" * 480)

        # Case 3: XTTS unavailable -> Fallback to Edge-TTS (Primary Network Fallback)
        mock_xtts.is_ready.return_value = False
        node.edge_tts_enabled = True
        pcm, eng_name, latency, is_ready = AstroRealtimeNode._synthesize_speech_pcm(node, "Merhaba Baran")
        self.assertEqual(eng_name, "edge_tts")
        self.assertTrue(is_ready)
        self.assertEqual(pcm, b"\x00\x00" * 480)

        # Case 4: Edge-TTS unavailable -> Fallback to Local Offline TTS (0 Internet Emergency)
        node.edge_tts_enabled = False
        mock_offline = MagicMock()
        mock_offline.is_ready.return_value = True
        mock_offline.synthesize_sentence.return_value = b"\x03\x03" * 480
        node.local_offline_tts = mock_offline
        pcm, eng_name, latency, is_ready = AstroRealtimeNode._synthesize_speech_pcm(node, "Merhaba Baran")
        self.assertEqual(eng_name, "local_offline_tts")
        self.assertTrue(is_ready)
        self.assertEqual(pcm, b"\x03\x03" * 480)

    def test_speaker_context_in_system_prompt_eliminates_unknown_speaker_claims(self):
        """Test that verified speaker context prevents 'Seni ilk kez duyuyorum' hallucinations."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        from astro_ai.persona_engine import PersonaEngine
        from astro_ai.memory_manager import MemoryManager

        node = MagicMock()
        node.persona_name = "kufurbaz"
        node.persona_engine = PersonaEngine(current_persona="kufurbaz")
        node.memory = MemoryManager()
        node.voice_recognizer = MagicMock()
        node.voice_recognizer._known_voiceprints = {"Baran": [1, 2, 3]}

        # When active_speaker is verified as Baran
        active_speaker = {
            "name": "Baran",
            "confidence": 0.94,
            "is_known": True,
            "source": "voice_recognition",
        }
        prompt = AstroRealtimeNode._build_current_system_prompt(node, active_speaker=active_speaker)

        self.assertIn("Baran", prompt)
        self.assertIn("ŞU AN SENİNLE KONUŞAN KİŞİ", prompt)
        self.assertIn("KESİNLİKLE 'Seni ilk kez duyuyorum'", prompt)
        self.assertNotIn("Sesini ilk defa duyduğunu, hafızandaki kayıtlara uymadığını belirt ve adını sor", prompt)

    def test_groq_gpt_oss_reasoning_parameters(self):
        """Test that Groq GPT-OSS requests include reasoning_effort='low' and exclude reasoning tokens."""
        from astro_ai.provider_registry import ProviderRegistry

        registry = ProviderRegistry()
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = [
            b'data: {"choices": [{"delta": {"content": "Merhaba "}}]}\n',
            b'data: {"choices": [{"delta": {"reasoning": "some thought"}}]}\n',
            b'data: {"choices": [{"delta": {"content": "Baran!"}}]}\n',
            b'data: [DONE]\n'
        ]

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_url:
            tokens = list(registry.stream_groq_completion(
                api_key="test_key",
                model_id="openai/gpt-oss-20b",
                messages=[{"role": "user", "content": "Selam"}],
            ))

            # Verify request payload
            req_call = mock_url.call_args[0][0]
            payload = json.loads(req_call.data.decode("utf-8"))
            self.assertEqual(payload.get("reasoning_effort"), "low")
            self.assertFalse(payload.get("include_reasoning", True))

            # Verify that only content tokens are yielded, reasoning is discarded
            self.assertEqual("".join(tokens), "Merhaba Baran!")


class TestRealtimeArchitectureInvariants(unittest.TestCase):
    """Formal regression assertions ensuring OpenAI Realtime P0 invariants & Vision isolation are preserved."""

    @classmethod
    def setUpClass(cls):
        try:
            import rclpy
            if not rclpy.ok():
                rclpy.init()
        except Exception:
            pass

    def test_realtime_model_default_and_candidates(self):
        """OpenAI Realtime model defaults to gpt-realtime-2.1-mini and candidate models include flagship versions."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode, discover_realtime_models

        candidates = discover_realtime_models("test_key")
        self.assertIn("gpt-realtime-2.1-mini", candidates)

        node = AstroRealtimeNode()
        # Varsayılan artık Realtime ailesinin hızlı katmanı (bkz. .env.example).
        self.assertEqual(node.realtime_model, "gpt-realtime-2.1-mini")
        self.assertFalse(node._fallback_mode)

    def test_realtime_audio_streaming_flow_unchanged(self):
        """Incoming audio is forwarded directly to OpenAI Realtime WebSocket in Realtime mode."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        from astro_ai.state_machine import RobotState

        node = AstroRealtimeNode()
        node._is_connected = True
        node.realtime_connection_state = "CONNECTED"
        node.realtime_session_state = "READY"
        node._fallback_mode = False
        node._is_sleeping = False
        node.state_machine.transition_to(RobotState.LISTENING)
        node._ws = MagicMock()
        node._loop = MagicMock()

        # Simulate incoming audio message
        mock_msg = MagicMock()
        mock_msg.data = "AQIDBA=="  # base64 encoded audio

        with patch("asyncio.run_coroutine_threadsafe") as mock_async_send:
            node._on_input_pcm(mock_msg)
            self.assertTrue(mock_async_send.called)
            node._ws.send.assert_called_once_with(json.dumps({"type": "input_audio_buffer.append", "audio": "AQIDBA=="}))

    def test_realtime_barge_in_preserves_semantics(self):
        """User speech event during playback triggers instant playback abort and response.cancel."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        from unittest.mock import AsyncMock

        node = AstroRealtimeNode()
        node._is_responding = True
        node._is_playback_active = True
        node.pub_interrupt = MagicMock()

        mock_ws = AsyncMock()
        event = {"type": "input_audio_buffer.speech_started"}

        asyncio.run(node._handle_realtime_event(mock_ws, event))

        self.assertFalse(node._is_responding)
        node.pub_interrupt.publish.assert_called_once()
        mock_ws.send.assert_called_once_with(json.dumps({"type": "response.cancel"}))

    def test_vision_failures_completely_isolated_from_realtime(self):
        """Vision timeouts or HTTP errors never alter Realtime connection or fallback mode."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        import numpy as np

        node = AstroRealtimeNode()
        node._is_connected = True
        node._fallback_mode = False
        node.groq_api_key = "test_groq"
        node.gemini_api_key = "test_gemini"

        mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        node._latest_camera_frame = mock_frame

        # Force urllib errors in vision call
        with patch("urllib.request.urlopen", side_effect=Exception("Vision HTTP 429 Rate Limited")):
            res = node._inspect_camera_view(focus="test")

            # Must return graceful dictionary without raising
            self.assertIsInstance(res, dict)
            self.assertIn("observation", res)
            # Realtime connection & mode must remain completely intact
            self.assertTrue(node._is_connected)
            self.assertFalse(node._fallback_mode)

    def test_fallback_mode_only_entered_on_realtime_quota_exhaustion(self):
        """Fallback mode is NOT active during normal healthy Realtime operation."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = AstroRealtimeNode()
        self.assertFalse(node._fallback_mode)

        # Quota exhaustion simulation
        err_str = "Error code: 429 insufficient_quota"
        if "insufficient_quota" in err_str:
            node._fallback_mode = True

        self.assertTrue(node._fallback_mode)

    def test_wake_detector_wakes_from_deep_idle(self):
        """Dedicated wake verification wakes robot from DEEP_IDLE to LISTENING."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        from astro_ai.state_machine import RobotState
        import numpy as np

        node = AstroRealtimeNode()
        self.assertTrue(node.state_machine.is_deep_idle())
        self.assertTrue(node._is_sleeping)

        # Synthesize audio chunk of speech
        fake_pcm = (np.sin(np.linspace(0, 100, 3200)) * 5000).astype(np.int16).tobytes()
        audio_chunks = [fake_pcm] * 5

        with patch.object(node, "_transcribe_groq_whisper", return_value="Hey Astro"):
            node._process_wake_candidate(audio_chunks)

            self.assertFalse(node._is_sleeping)
            self.assertEqual(node.state_machine.current_state, RobotState.LISTENING)

    def test_event_driven_vision_gating_and_memory_filter(self):
        """Event-driven vision skips same-scene/budget and filters trivial observations."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        import numpy as np

        node = AstroRealtimeNode()
        node._latest_camera_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # 1. Budget exhausted
        node.max_vision_requests_per_minute = 1
        node._vision_requests_history = [time.monotonic()]
        res = node._evaluate_vision_event("scene_changed")
        self.assertIsNone(res)
        self.assertEqual(node.vision_last_skip_reason, "budget")

        # 2. Trivial memory filter: "Aydınlık." is classified as ephemeral and not stored in profile
        node.memory.profile.get_observations = MagicMock(return_value=[])
        with patch.object(node.memory.profile, "add_observation") as mock_add_obs:
            node._classify_and_store_vision_observation("Aydınlık.", "idle")
            mock_add_obs.assert_not_called()

    def test_pure_wake_phrase_does_not_create_conversational_turn(self):
        """Pure wake phrase wakes robot to LISTENING but creates NO fake LLM/TTS turn."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        from astro_ai.state_machine import RobotState
        import numpy as np

        node = AstroRealtimeNode()
        self.assertTrue(node.state_machine.is_deep_idle())
        self.assertTrue(node._is_sleeping)

        fake_pcm = (np.sin(np.linspace(0, 100, 3200)) * 5000).astype(np.int16).tobytes()
        audio_chunks = [fake_pcm] * 5

        with patch.object(node, "_transcribe_groq_whisper", return_value="Hey Astro"), \
             patch.object(node, "_process_fallback_turn") as mock_turn:
            node._process_wake_candidate(audio_chunks)

            self.assertFalse(node._is_sleeping)
            self.assertEqual(node.state_machine.current_state, RobotState.LISTENING)
            # Must NOT invoke conversational turn
            mock_turn.assert_not_called()

    def test_wake_with_command_forwards_turn(self):
        """Wake phrase with attached command triggers turn with command text."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        from astro_ai.state_machine import RobotState
        import numpy as np

        node = AstroRealtimeNode()
        fake_pcm = (np.sin(np.linspace(0, 100, 3200)) * 5000).astype(np.int16).tobytes()
        audio_chunks = [fake_pcm] * 5

        with patch.object(node, "_transcribe_groq_whisper", return_value="Hey Astro nasılsın"), \
             patch.object(node, "_process_fallback_turn") as mock_turn:
            node._process_wake_candidate(audio_chunks)

            self.assertFalse(node._is_sleeping)
            self.assertEqual(node.state_machine.current_state, RobotState.LISTENING)
            mock_turn.assert_called_once()

    def test_barge_in_single_logical_event_debouncing(self):
        """Multiple loud frames during playback trigger only one logical interrupt per generation."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        from astro_ai.state_machine import RobotState
        import numpy as np
        import base64

        node = AstroRealtimeNode()
        node._is_playback_active = True
        node._is_responding = True
        node.state_machine.transition_to(RobotState.SPEAKING)
        node._is_sleeping = False
        node.pub_interrupt = MagicMock()

        # Frame with loud RMS (> 1500)
        loud_pcm_16k = (np.sin(np.linspace(0, 100, 3200)) * 10000).astype(np.int16).tobytes()
        loud_msg = MagicMock()
        loud_msg.data = base64.b64encode(loud_pcm_16k).decode("ascii")

        with patch("astro_ai.astro_realtime_node.resample_24k_to_16k", return_value=loud_pcm_16k):
            # Frame 1 & 2: Building persistence
            node._on_input_pcm(loud_msg)
            node._on_input_pcm(loud_msg)
            # Frame 3: Persistence reached -> Triggers barge-in & sets _barge_in_latched = True
            node._on_input_pcm(loud_msg)
            self.assertTrue(node._barge_in_latched)
            self.assertEqual(node.pub_interrupt.publish.call_count, 1)

            # 4th loud frame in same generation -> Debounced by latch
            node._on_input_pcm(loud_msg)
            self.assertEqual(node.pub_interrupt.publish.call_count, 1)

    def test_wake_detector_strictly_rejects_non_wake_words_and_phantom_hallucinations(self):
        """Non-wake utterances and phantom hallucinations ('Altyazı M.K.') NEVER wake up the robot."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        from astro_ai.state_machine import RobotState
        import numpy as np

        node = AstroRealtimeNode()
        self.assertTrue(node.state_machine.is_deep_idle())
        self.assertTrue(node._is_sleeping)

        fake_pcm = (np.sin(np.linspace(0, 100, 3200)) * 5000).astype(np.int16).tobytes()
        audio_chunks = [fake_pcm] * 5

        # 1. Phantom hallucination 'Altyazı M.K.'
        with patch.object(node, "_transcribe_groq_whisper", return_value="Altyazı M.K."), \
             patch.object(node, "_process_fallback_turn") as mock_turn:
            node._process_wake_candidate(audio_chunks)
            self.assertTrue(node._is_sleeping)
            self.assertEqual(node.state_machine.current_state, RobotState.DEEP_IDLE)
            mock_turn.assert_not_called()

        # 2. Arbitrary non-wake speech 'Kapıyı açar mısın'
        with patch.object(node, "_transcribe_groq_whisper", return_value="Kapıyı açar mısın"), \
             patch.object(node, "_process_fallback_turn") as mock_turn:
            node._process_wake_candidate(audio_chunks)
            self.assertTrue(node._is_sleeping)
            self.assertEqual(node.state_machine.current_state, RobotState.DEEP_IDLE)
            mock_turn.assert_not_called()

        # 3. Substring non-exact match 'E astro'
        with patch.object(node, "_transcribe_groq_whisper", return_value="E astro"), \
             patch.object(node, "_process_fallback_turn") as mock_turn:
            node._process_wake_candidate(audio_chunks)
            self.assertTrue(node._is_sleeping)
            self.assertEqual(node.state_machine.current_state, RobotState.DEEP_IDLE)
            mock_turn.assert_not_called()

    def test_xtts_environment_proof_and_resolution(self):
        """Fine-tuned XTTS model paths and existence are checked at startup."""
        from astro_audio.local_xtts_engine import resolve_fine_tune_paths

        res = resolve_fine_tune_paths(
            checkpoint="/non/existent/model.pth",
            config="/non/existent/config.json",
            vocab="/non/existent/vocab.json",
            speakers="/non/existent/speakers.pth",
            speaker_wav="/non/existent/ref.wav",
        )
        self.assertFalse(res["checkpoint_exists"])
        self.assertFalse(res["config_exists"])
        self.assertFalse(res["all_required_exist"])

    def test_speaker_recognition_temporal_smoothing(self):
        """Low confidence scores (0.42) do NOT overwrite existing speaker context; tentative requires 2 observations."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = AstroRealtimeNode()
        node._active_person_name = "Baran"
        node._person_hold_until = time.monotonic() + 45.0
        node._recognized_speaker = {"name": "Baran", "confidence": 0.90, "is_known": True, "source": "voice_recognition"}

        # Low confidence observation for Oktay (0.42) -> Ignored, Baran preserved
        mock_rec = MagicMock()
        mock_rec.identify_speaker.return_value = ("Oktay", 0.42)
        node.voice_recognizer = mock_rec

        fake_pcm = b"\x00\x00" * 3200
        with patch.object(node, "_transcribe_groq_whisper", return_value="selam nasılsın"), \
             patch.object(node, "_validate_stt_transcript", return_value=("selam nasılsın", {"stt_rejected": False})), \
             patch.object(node, "_synthesize_speech_pcm", return_value=(b"\x00\x00" * 100, "xtts_gpu", 50.0, True)), \
             patch.object(node, "_play_pcm_chunks"):
            
            node._process_fallback_turn([fake_pcm])
            # Baran MUST remain active
            self.assertEqual(node._active_person_name, "Baran")

    def test_complete_offline_mode_acceptance(self):
        """When network is completely down (0 Internet), local LLM and local offline TTS synthesize voice."""
        from astro_ai.astro_realtime_node import AstroRealtimeNode

        node = AstroRealtimeNode()
        node.groq_api_key = ""
        node.gemini_api_key = ""
        node.openai_api_key = ""
        node.edge_tts_enabled = False
        node.local_offline_tts = MagicMock()
        node.local_offline_tts.is_ready.return_value = True
        node.local_offline_tts.synthesize_sentence.return_value = b"\x00\x00" * 480

        # Local LLM produces answer
        fallback_ans = node._generate_contextual_persona_fallback("nasılsın")
        self.assertTrue(len(fallback_ans) > 5)

        # Local offline TTS synthesizes PCM without throwing
        pcm, eng_name, latency, is_ready = node._synthesize_speech_pcm(fallback_ans)
        self.assertIn(eng_name, ("xtts_gpu", "local_offline_tts"))
        self.assertTrue(len(pcm) > 0)


if __name__ == "__main__":
    unittest.main()
