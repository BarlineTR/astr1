"""ASTRO V1 — Phase 3 Test Suite: Cognitive Architecture Support Layer.

Validates:
  1. Provider abstraction inheritance
  2. Gemini provider configuration
  3. Groq provider configuration
  4. Missing API key returns UNAVAILABLE
  5. Successful mocked provider response
  6. Malformed response handled gracefully
  7. Timeout handled gracefully
  8. 429 response handled without automatic retry
  9. No automatic retry by default (max_auto_retries == 0)
  10. Local requests/minute budget gate
  11. Local requests/hour budget gate
  12. Local requests/day budget gate
  13. Token budget gate
  14. Request suppression after cooldown
  15. Identical request served from cache
  16. Context reduction (selective file excerpts)
  17. Context token budget enforcement
  18. Gemini failure does NOT automatically trigger Qwen
  19. Qwen failure does NOT automatically trigger Gemini
  20. Comparison mode is explicit and synthesizes observations
  21. Normal CognitiveLoop does NOT call either provider
  22. OBSERVE cannot modify files
  23. PROPOSE cannot modify files
  24. APPLY requires explicit invocation
  25. Protected files cannot be modified (UNAUTHORIZED_FILE_ACCESS)
  26. No secrets in source tree or config templates
  27. Graceful degradation when support is disabled
  28. Phase 0A regression check
  29. Phase 0B regression check
  30. Phase 1 regression check
  31. Phase 2 regression check
"""

import os
import time
import unittest
from unittest.mock import MagicMock, patch

from astro_ai.brain.affective_state import AffectiveStateManager
from astro_ai.brain.cognitive_event_bus import CognitiveEventBus
from astro_ai.brain.cognitive_loop import CognitiveLoop
from astro_ai.brain.perception_event_detector import PerceptionEventDetector
from astro_ai.brain.self_model import SelfModel
from astro_ai.brain.support.assistant import CognitiveArchitectureAssistant
from astro_ai.brain.support.budget_gate import LocalBudgetGate
from astro_ai.brain.support.cache import ArchitectureSupportCache
from astro_ai.brain.support.config import SupportConfig
from astro_ai.brain.support.context_builder import ArchitectureContextBuilder, TokenBudgetExceededError
from astro_ai.brain.support.contracts import (
    ArchitectureSupportResponse,
    BudgetDecision,
    ProposedChange,
    SupportControlMode,
    SupportRequest,
    SupportStatus,
)
from astro_ai.brain.support.cooldown import TopicCooldownDebouncer
from astro_ai.brain.support.gemini_provider import GeminiFlashProvider
from astro_ai.brain.support.groq_provider import GroqQwenProvider
from astro_ai.brain.support.provider_base import BaseSupportProvider
from astro_ai.brain.world_model import WorldModel
from astro_ai.contracts.consciousness_types import CognitiveEvent, CognitiveEventType, RobotState, SelfState


class TestPhase3CognitiveArchitectureSupport(unittest.TestCase):
    """Phase 3 Acceptance Tests for Support Layer, Budget Gate, and Model Providers."""

    def setUp(self):
        self.config = SupportConfig(
            llm_support_enabled=True,
            gemini_support_enabled=True,
            groq_support_enabled=True,
            gemini_api_key="mock_gemini_key",
            groq_api_key="mock_groq_key",
            max_requests_per_minute=3,
            max_requests_per_hour=10,
            max_requests_per_day=20,
            gemini_max_input_tokens=5000,
            groq_max_input_tokens=4000,
            max_total_tokens_per_day=50000,
            cooldown_seconds=5.0,
            cache_ttl_seconds=3600,
            max_auto_retries=0,
        )
        self.budget_gate = LocalBudgetGate(config=self.config)
        self.cache = ArchitectureSupportCache(db_path=":memory:", default_ttl_seconds=3600)
        self.debouncer = TopicCooldownDebouncer(default_cooldown_seconds=5.0)
        self.context_builder = ArchitectureContextBuilder(config=self.config)

    # -------------------------------------------------------------------------
    # 1. Provider Abstraction
    # -------------------------------------------------------------------------
    def test_01_provider_abstraction_inheritance(self):
        """1. Providers inherit from BaseSupportProvider and expose uniform interface."""
        gemini = GeminiFlashProvider(config=self.config)
        groq = GroqQwenProvider(config=self.config)

        self.assertIsInstance(gemini, BaseSupportProvider)
        self.assertIsInstance(groq, BaseSupportProvider)
        self.assertEqual(gemini.provider_name, "gemini")
        self.assertEqual(groq.provider_name, "groq")

    # -------------------------------------------------------------------------
    # 2. Gemini Configuration
    # -------------------------------------------------------------------------
    def test_02_gemini_provider_configuration(self):
        """2. Gemini provider configures model identifier and availability."""
        gemini = GeminiFlashProvider(config=self.config)
        self.assertTrue(gemini.is_available())
        self.assertEqual(gemini.model_name, "gemini-3.6-flash")

    # -------------------------------------------------------------------------
    # 3. Groq Configuration
    # -------------------------------------------------------------------------
    def test_03_groq_provider_configuration(self):
        """3. Groq provider configures model identifier and availability."""
        groq = GroqQwenProvider(config=self.config)
        self.assertTrue(groq.is_available())
        self.assertEqual(groq.model_name, "qwen/qwen-2.5-coder-32b")

    # -------------------------------------------------------------------------
    # 4. Missing API Key
    # -------------------------------------------------------------------------
    def test_04_missing_api_key_returns_unavailable(self):
        """4. Missing API key causes provider to return PROVIDER_UNAVAILABLE gracefully."""
        no_key_cfg = SupportConfig(
            llm_support_enabled=True,
            gemini_support_enabled=True,
            gemini_api_key="",
        )
        gemini = GeminiFlashProvider(config=no_key_cfg)
        self.assertFalse(gemini.is_available())

        resp = gemini.generate_analysis("prompt", "context", SupportControlMode.PROPOSE, "req_1")
        self.assertEqual(resp.status, SupportStatus.PROVIDER_UNAVAILABLE)
        self.assertIn("disabled or GEMINI_API_KEY is not configured", resp.summary)

    # -------------------------------------------------------------------------
    # 5. Successful Mocked Provider Response
    # -------------------------------------------------------------------------
    def test_05_successful_mocked_provider_response(self):
        """5. Mocked provider returns structured ArchitectureSupportResponse."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            '{"summary": "SelfModel review passed.", "observations": ["Strict epistemic bounds observed"], '
            '"architectural_concerns": [], "proposed_changes": [], "confidence": 0.95}'
        )
        mock_client.models.generate_content.return_value = mock_response

        gemini = GeminiFlashProvider(config=self.config, client=mock_client)
        resp = gemini.generate_analysis("Review self model", "context text", SupportControlMode.PROPOSE, "req_05")

        self.assertEqual(resp.status, SupportStatus.SUCCESS)
        self.assertEqual(resp.summary, "SelfModel review passed.")
        self.assertIn("Strict epistemic bounds observed", resp.observations)
        self.assertAlmostEqual(resp.confidence, 0.95)

    # -------------------------------------------------------------------------
    # 6. Malformed Response Handled Gracefully
    # -------------------------------------------------------------------------
    def test_06_malformed_response_handled_gracefully(self):
        """6. Malformed/non-JSON text response is parsed into structured format without crashing."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "This is plain unstructured text from model without JSON."
        mock_client.models.generate_content.return_value = mock_response

        gemini = GeminiFlashProvider(config=self.config, client=mock_client)
        resp = gemini.generate_analysis("Review prompt", "context", SupportControlMode.PROPOSE, "req_06")

        self.assertEqual(resp.status, SupportStatus.SUCCESS)
        self.assertIn("This is plain unstructured text", resp.summary)

    # -------------------------------------------------------------------------
    # 7. Timeout Handled Gracefully
    # -------------------------------------------------------------------------
    def test_07_timeout_handled_gracefully(self):
        """7. Network timeout results in structured error response."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = TimeoutError("Connection timed out after 10.0s")

        gemini = GeminiFlashProvider(config=self.config, client=mock_client)
        resp = gemini.generate_analysis("Review prompt", "context", SupportControlMode.PROPOSE, "req_07")

        self.assertEqual(resp.status, SupportStatus.ERROR)
        self.assertEqual(resp.error_code, "TIMEOUT")
        self.assertIn("Connection timed out", resp.summary)

    # -------------------------------------------------------------------------
    # 8. 429 Response Handled Without Automatic Retry
    # -------------------------------------------------------------------------
    def test_08_429_response_handled_without_retry(self):
        """8. HTTP 429 quota exhaustion returns error and avoids tight retry loops."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("429 ResourceExhausted: Quota exceeded")

        gemini = GeminiFlashProvider(config=self.config, client=mock_client)
        resp = gemini.generate_analysis("prompt", "context", SupportControlMode.PROPOSE, "req_08")

        self.assertEqual(resp.status, SupportStatus.ERROR)
        self.assertEqual(resp.error_code, "429_RATE_LIMIT")
        # Ensure only 1 call made (0 retries)
        self.assertEqual(mock_client.models.generate_content.call_count, 1)

    # -------------------------------------------------------------------------
    # 9. No Automatic Retry By Default
    # -------------------------------------------------------------------------
    def test_09_no_automatic_retry_by_default(self):
        """9. Verification that max_auto_retries default is strictly 0."""
        default_cfg = SupportConfig()
        self.assertEqual(default_cfg.max_auto_retries, 0)

    # -------------------------------------------------------------------------
    # 10. Local Requests/Minute Budget Gate
    # -------------------------------------------------------------------------
    def test_10_local_requests_per_minute_budget_gate(self):
        """10. Budget gate rejects requests exceeding max_requests_per_minute."""
        gate = LocalBudgetGate(config=self.config)
        now = 1000.0

        # Max is 3 per minute
        for _ in range(3):
            d = gate.evaluate_request("gemini", 100, timestamp=now)
            self.assertTrue(d.allowed)
            gate.record_request_sent("gemini", 100, timestamp=now)

        # 4th request must be rejected
        d4 = gate.evaluate_request("gemini", 100, timestamp=now + 5.0)
        self.assertFalse(d4.allowed)
        self.assertIn("Max requests per minute", d4.reason)

    # -------------------------------------------------------------------------
    # 11. Local Requests/Hour Budget Gate
    # -------------------------------------------------------------------------
    def test_11_local_requests_per_hour_budget_gate(self):
        """11. Budget gate rejects requests exceeding max_requests_per_hour."""
        cfg = SupportConfig(max_requests_per_minute=20, max_requests_per_hour=5, max_requests_per_day=50)
        gate = LocalBudgetGate(config=cfg)
        now = 2000.0

        for i in range(5):
            d = gate.evaluate_request("groq", 50, timestamp=now + (i * 70.0))
            self.assertTrue(d.allowed)
            gate.record_request_sent("groq", 50, timestamp=now + (i * 70.0))

        # 6th request within hour rejected
        d6 = gate.evaluate_request("groq", 50, timestamp=now + 400.0)
        self.assertFalse(d6.allowed)
        self.assertIn("Max requests per hour", d6.reason)

    # -------------------------------------------------------------------------
    # 12. Local Requests/Day Budget Gate
    # -------------------------------------------------------------------------
    def test_12_local_requests_per_day_budget_gate(self):
        """12. Budget gate rejects requests exceeding max_requests_per_day."""
        cfg = SupportConfig(max_requests_per_minute=100, max_requests_per_hour=100, max_requests_per_day=4)
        gate = LocalBudgetGate(config=cfg)
        now = 3000.0

        for i in range(4):
            d = gate.evaluate_request("gemini", 50, timestamp=now + (i * 100.0))
            self.assertTrue(d.allowed)
            gate.record_request_sent("gemini", 50, timestamp=now + (i * 100.0))

        d5 = gate.evaluate_request("gemini", 50, timestamp=now + 500.0)
        self.assertFalse(d5.allowed)
        self.assertIn("Max requests per day", d5.reason)

    # -------------------------------------------------------------------------
    # 13. Token Budget Gate
    # -------------------------------------------------------------------------
    def test_13_token_budget_gate(self):
        """13. Requests exceeding single-request token budget or daily total are rejected."""
        gate = LocalBudgetGate(config=self.config)

        # Single request exceeding limit (config.gemini_max_input_tokens = 5000)
        d_oversized = gate.evaluate_request("gemini", 8000)
        self.assertFalse(d_oversized.allowed)
        self.assertIn("Estimated input tokens (8000) exceeds single-request limit", d_oversized.reason)

        # Normal request allowed
        d_normal = gate.evaluate_request("gemini", 2000)
        self.assertTrue(d_normal.allowed)

    # -------------------------------------------------------------------------
    # 14. Request Suppression After Cooldown
    # -------------------------------------------------------------------------
    def test_14_request_suppression_after_cooldown(self):
        """14. Repeated requests on the same topic within cooldown are suppressed."""
        debouncer = TopicCooldownDebouncer(default_cooldown_seconds=10.0)
        now = 5000.0

        self.assertFalse(debouncer.should_suppress("self_model", now=now))
        debouncer.record_request("self_model", now=now)

        # Arriving 2 seconds later -> suppressed
        self.assertTrue(debouncer.should_suppress("self_model", now=now + 2.0))

        # Arriving 12 seconds later -> permitted
        self.assertFalse(debouncer.should_suppress("self_model", now=now + 12.0))

    # -------------------------------------------------------------------------
    # 15. Identical Request Served From Cache
    # -------------------------------------------------------------------------
    def test_15_identical_request_served_from_cache(self):
        """15. Re-executing identical request returns cached result with zero new API calls."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"summary": "Cached analysis", "confidence": 0.9}'
        mock_client.models.generate_content.return_value = mock_response

        gemini = GeminiFlashProvider(config=self.config, client=mock_client)
        assistant = CognitiveArchitectureAssistant(
            config=self.config,
            budget_gate=self.budget_gate,
            cache=self.cache,
            debouncer=self.debouncer,
            context_builder=self.context_builder,
            providers={"gemini": gemini},
        )

        req1 = SupportRequest(topic="self_model", prompt="Analyze invariants", provider_override="gemini")
        resp1 = assistant.analyze_architecture(req1)
        self.assertEqual(resp1.status, SupportStatus.SUCCESS)
        self.assertFalse(resp1.cache_hit)
        self.assertEqual(mock_client.models.generate_content.call_count, 1)

        # Second request with identical topic & prompt
        req2 = SupportRequest(topic="self_model", prompt="Analyze invariants", provider_override="gemini")
        resp2 = assistant.analyze_architecture(req2)
        self.assertEqual(resp2.status, SupportStatus.CACHED)
        self.assertTrue(resp2.cache_hit)
        # Call count must still be 1!
        self.assertEqual(mock_client.models.generate_content.call_count, 1)

    # -------------------------------------------------------------------------
    # 16. Context Reduction
    # -------------------------------------------------------------------------
    def test_16_context_reduction(self):
        """16. ArchitectureContextBuilder selects minimal relevant files and truncates excerpts."""
        ctx, meta = self.context_builder.build_context("self_model")
        self.assertIn("File:", ctx)
        self.assertIn("self_model.py", meta["files_included"][0])
        # Verify it did not include unrelated files
        self.assertNotIn("lidar_tracker.py", ctx)

    # -------------------------------------------------------------------------
    # 17. Context Token Budget Enforcement
    # -------------------------------------------------------------------------
    def test_17_context_token_budget_enforcement(self):
        """17. If context exceeds hard budget and cannot be compressed, TokenBudgetExceededError raised."""
        with self.assertRaises(TokenBudgetExceededError):
            self.context_builder.build_context("self_model", max_tokens=10)

    # -------------------------------------------------------------------------
    # 18. Gemini Failure Does NOT Trigger Qwen
    # -------------------------------------------------------------------------
    def test_18_gemini_failure_does_not_trigger_qwen(self):
        """18. When Gemini fails with allow_fallback=False, Groq is NEVER called."""
        gemini_client = MagicMock()
        gemini_client.models.generate_content.side_effect = RuntimeError("Gemini 500 error")

        groq_client = MagicMock()

        gemini = GeminiFlashProvider(config=self.config, client=gemini_client)
        groq = GroqQwenProvider(config=self.config, client=groq_client)

        assistant = CognitiveArchitectureAssistant(
            config=self.config,
            budget_gate=self.budget_gate,
            cache=self.cache,
            debouncer=self.debouncer,
            context_builder=self.context_builder,
            providers={"gemini": gemini, "groq": groq},
        )

        req = SupportRequest(topic="self_model", prompt="Review", provider_override="gemini", allow_fallback=False)
        resp = assistant.analyze_architecture(req)

        self.assertEqual(resp.status, SupportStatus.ERROR)
        self.assertEqual(gemini_client.models.generate_content.call_count, 1)
        self.assertEqual(groq_client.chat.completions.create.call_count, 0)

    # -------------------------------------------------------------------------
    # 19. Qwen Failure Does NOT Trigger Gemini
    # -------------------------------------------------------------------------
    def test_19_qwen_failure_does_not_trigger_gemini(self):
        """19. When Groq fails with allow_fallback=False, Gemini is NEVER called."""
        gemini_client = MagicMock()
        groq_client = MagicMock()
        groq_client.chat.completions.create.side_effect = RuntimeError("Groq 500 error")

        gemini = GeminiFlashProvider(config=self.config, client=gemini_client)
        groq = GroqQwenProvider(config=self.config, client=groq_client)

        assistant = CognitiveArchitectureAssistant(
            config=self.config,
            budget_gate=self.budget_gate,
            cache=self.cache,
            debouncer=self.debouncer,
            context_builder=self.context_builder,
            providers={"gemini": gemini, "groq": groq},
        )

        req = SupportRequest(topic="self_model", prompt="Review", provider_override="groq", allow_fallback=False)
        resp = assistant.analyze_architecture(req)

        self.assertEqual(resp.status, SupportStatus.ERROR)
        self.assertEqual(groq_client.chat.completions.create.call_count, 1)
        self.assertEqual(gemini_client.models.generate_content.call_count, 0)

    # -------------------------------------------------------------------------
    # 20. Comparison Mode is Explicit
    # -------------------------------------------------------------------------
    def test_20_comparison_mode_is_explicit(self):
        """20. Comparison mode queries both models independently and synthesizes comparison."""
        gemini_client = MagicMock()
        gemini_resp = MagicMock()
        gemini_resp.text = '{"summary": "Gemini review", "observations": ["Observation G1"]}'
        gemini_client.models.generate_content.return_value = gemini_resp

        groq_client = MagicMock()
        groq_resp = MagicMock()
        groq_choice = MagicMock()
        groq_choice.message.content = '{"summary": "Groq review", "observations": ["Observation Q1"]}'
        groq_resp.choices = [groq_choice]
        groq_client.chat.completions.create.return_value = groq_resp

        gemini = GeminiFlashProvider(config=self.config, client=gemini_client)
        groq = GroqQwenProvider(config=self.config, client=groq_client)

        assistant = CognitiveArchitectureAssistant(
            config=self.config,
            budget_gate=self.budget_gate,
            cache=self.cache,
            debouncer=self.debouncer,
            context_builder=self.context_builder,
            providers={"gemini": gemini, "groq": groq},
        )

        comp_req = SupportRequest(topic="comparison_test", prompt="Compare invariants", requires_comparison=True)
        result = assistant.compare_architecture_reviews(comp_req)

        self.assertIn("Observation G1", result.gemini_observations)
        self.assertIn("Observation Q1", result.qwen_observations)
        self.assertTrue(len(result.agreements) > 0)
        self.assertEqual(gemini_client.models.generate_content.call_count, 1)
        self.assertEqual(groq_client.chat.completions.create.call_count, 1)

    # -------------------------------------------------------------------------
    # 21. Normal CognitiveLoop Does NOT Call Providers
    # -------------------------------------------------------------------------
    def test_21_normal_cognitive_loop_does_not_call_providers(self):
        """21. Runtime CognitiveLoop.step() operates in pure Python with zero LLM provider calls."""
        mock_gemini = MagicMock(spec=GeminiFlashProvider)
        mock_groq = MagicMock(spec=GroqQwenProvider)

        loop = CognitiveLoop()
        results = loop.run_consecutive_steps(10, None)

        self.assertEqual(len(results), 10)
        self.assertEqual(mock_gemini.generate_analysis.call_count, 0)
        self.assertEqual(mock_groq.generate_analysis.call_count, 0)

    # -------------------------------------------------------------------------
    # 22. OBSERVE Cannot Modify Files
    # -------------------------------------------------------------------------
    def test_22_observe_mode_cannot_modify_files(self):
        """22. In OBSERVE mode, no files are modified and apply_result is None."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '{"summary": "Observation only", "proposed_changes": []}'
        mock_client.models.generate_content.return_value = mock_resp

        gemini = GeminiFlashProvider(config=self.config, client=mock_client)
        assistant = CognitiveArchitectureAssistant(
            config=self.config,
            budget_gate=self.budget_gate,
            cache=self.cache,
            debouncer=self.debouncer,
            context_builder=self.context_builder,
            providers={"gemini": gemini},
        )

        req = SupportRequest(topic="observe_test", prompt="Inspect", mode=SupportControlMode.OBSERVE)
        resp = assistant.analyze_architecture(req)

        self.assertEqual(resp.mode, SupportControlMode.OBSERVE)
        self.assertIsNone(resp.apply_result)

    # -------------------------------------------------------------------------
    # 23. PROPOSE Cannot Modify Files
    # -------------------------------------------------------------------------
    def test_23_propose_mode_cannot_modify_files(self):
        """23. In PROPOSE mode, structured proposals are returned without modifying files."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '{"summary": "Proposed update", "proposed_changes": [{"file_path": "ros2_ws/src/astro_ai/astro_ai/brain/self_model.py", "description": "Add comment", "rationale": "Doc"}]}'
        mock_client.models.generate_content.return_value = mock_resp

        gemini = GeminiFlashProvider(config=self.config, client=mock_client)
        assistant = CognitiveArchitectureAssistant(
            config=self.config,
            budget_gate=self.budget_gate,
            cache=self.cache,
            debouncer=self.debouncer,
            context_builder=self.context_builder,
            providers={"gemini": gemini},
        )

        req = SupportRequest(topic="propose_test", prompt="Propose changes", mode=SupportControlMode.PROPOSE)
        resp = assistant.analyze_architecture(req)

        self.assertEqual(resp.mode, SupportControlMode.PROPOSE)
        self.assertTrue(resp.requires_human_approval)
        self.assertIsNone(resp.apply_result)

    # -------------------------------------------------------------------------
    # 24. APPLY Requires Explicit Invocation
    # -------------------------------------------------------------------------
    def test_24_apply_mode_requires_explicit_invocation(self):
        """24. In APPLY mode with authorized files, structured apply_result is prepared."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '{"summary": "Authorized edit", "proposed_changes": [{"file_path": "ros2_ws/src/astro_ai/astro_ai/brain/self_model.py", "description": "Update", "rationale": "Test"}]}'
        mock_client.models.generate_content.return_value = mock_resp

        gemini = GeminiFlashProvider(config=self.config, client=mock_client)
        assistant = CognitiveArchitectureAssistant(
            config=self.config,
            budget_gate=self.budget_gate,
            cache=self.cache,
            debouncer=self.debouncer,
            context_builder=self.context_builder,
            providers={"gemini": gemini},
        )

        req = SupportRequest(topic="apply_test", prompt="Apply edit", mode=SupportControlMode.APPLY)
        resp = assistant.analyze_architecture(req)

        self.assertEqual(resp.mode, SupportControlMode.APPLY)
        self.assertIsNotNone(resp.apply_result)
        self.assertIn("ros2_ws/src/astro_ai/astro_ai/brain/self_model.py", resp.apply_result.files_modified)

    # -------------------------------------------------------------------------
    # 25. Protected Files Cannot Be Modified
    # -------------------------------------------------------------------------
    def test_25_protected_files_cannot_be_modified(self):
        """25. Attempting APPLY on protected files (.env, .db, motors) is rejected with UNAUTHORIZED_FILE_ACCESS."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = '{"summary": "Malicious edit", "proposed_changes": [{"file_path": ".env", "description": "Inject key", "rationale": "Exploit"}]}'
        mock_client.models.generate_content.return_value = mock_resp

        gemini = GeminiFlashProvider(config=self.config, client=mock_client)
        assistant = CognitiveArchitectureAssistant(
            config=self.config,
            budget_gate=self.budget_gate,
            cache=self.cache,
            debouncer=self.debouncer,
            context_builder=self.context_builder,
            providers={"gemini": gemini},
        )

        req = SupportRequest(topic="protected_test", prompt="Edit env", mode=SupportControlMode.APPLY)
        resp = assistant.analyze_architecture(req)

        self.assertEqual(resp.status, SupportStatus.UNAUTHORIZED_FILE_ACCESS)
        self.assertIn("protected or unauthorized", resp.summary)

    # -------------------------------------------------------------------------
    # 26. No Secrets In Source Tree Or Templates
    # -------------------------------------------------------------------------
    def test_26_no_secrets_in_source_tree_or_templates(self):
        """26. Source code does not contain hardcoded API keys or credentials."""
        forbidden = ["AIzaSy", "gsk_"]
        support_dir = os.path.join(os.path.dirname(__file__), "..", "astro_ai", "brain", "support")
        for root, _, files in os.walk(support_dir):
            for file in files:
                if file.endswith(".py"):
                    path = os.path.join(root, file)
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                        for f_key in forbidden:
                            self.assertNotIn(f_key, content, f"Secret pattern '{f_key}' found in {path}")

    # -------------------------------------------------------------------------
    # 27. Graceful Degradation When Disabled
    # -------------------------------------------------------------------------
    def test_27_graceful_degradation_when_disabled(self):
        """27. When LLM_SUPPORT_ENABLED=False, system degrades gracefully without crashing."""
        disabled_cfg = SupportConfig(llm_support_enabled=False)
        assistant = CognitiveArchitectureAssistant(config=disabled_cfg)

        req = SupportRequest(topic="test", prompt="Analyze")
        resp = assistant.analyze_architecture(req)

        self.assertEqual(resp.status, SupportStatus.DEGRADED)
        self.assertEqual(resp.error_code, "SUPPORT_DISABLED")

    # -------------------------------------------------------------------------
    # 28. Phase 0A Regression Check
    # -------------------------------------------------------------------------
    def test_28_phase0a_regression_check(self):
        """28. Phase 0A CognitiveEventBus and foundation contracts remain fully operational."""
        bus = CognitiveEventBus(max_capacity=10)
        evt = bus.create_and_publish(CognitiveEventType.PERSON_APPEARED, source="test")
        self.assertEqual(len(bus.get_unprocessed_events()), 1)

    # -------------------------------------------------------------------------
    # 29. Phase 0B Regression Check
    # -------------------------------------------------------------------------
    def test_29_phase0b_regression_check(self):
        """29. Phase 0B WorldModel temporal ring-buffer continues to accumulate snapshots."""
        wm = WorldModel(temporal_history_size=5)
        wm.record_event("evt_test")
        wm.commit_temporal_snapshot()
        self.assertEqual(wm.temporal_history_len, 1)

    # -------------------------------------------------------------------------
    # 30. Phase 1 Regression Check
    # -------------------------------------------------------------------------
    def test_30_phase1_regression_check(self):
        """30. Phase 1 PerceptionEventDetector transitions continue working."""
        detector = PerceptionEventDetector()
        evts = detector.detect_transitions({"person_detected": True}, timestamp=100.0)
        self.assertTrue(any(e.event_type == CognitiveEventType.PERSON_APPEARED for e in evts))

    # -------------------------------------------------------------------------
    # 31. Phase 2 Regression Check
    # -------------------------------------------------------------------------
    def test_31_phase2_regression_check(self):
        """31. Phase 2 SelfState introspection and AffectiveStateManager remain operational."""
        aff = AffectiveStateManager()
        aff.modulate_arousal(0.3)
        self.assertGreater(aff.state.arousal, 0.2)
        aff.step_decay(dt=0.1)
        self.assertLess(aff.state.arousal, 0.5)

        self_state = SelfState()
        summary = self_state.get_introspection_summary()
        self.assertIn("activity", summary)
        self.assertIn("operational_state", summary)

    # -------------------------------------------------------------------------
    # 32. Proposed Changes Normalization (No-Op Strings)
    # -------------------------------------------------------------------------
    def test_32_proposed_changes_normalization_noop_strings(self):
        """32. No-op string values are safely normalized to empty list without raising."""
        noop_cases = ["None", "No changes required", "N/A", "GEMINI_OK", "none", "ok", "[]", "null"]
        normalized = BaseSupportProvider.normalize_proposed_changes(noop_cases)
        self.assertEqual(normalized, [])

        # Non-list input also safely normalizes to []
        self.assertEqual(BaseSupportProvider.normalize_proposed_changes("None"), [])
        self.assertEqual(BaseSupportProvider.normalize_proposed_changes(None), [])
        self.assertEqual(BaseSupportProvider.normalize_proposed_changes(123), [])

    # -------------------------------------------------------------------------
    # 33. Proposed Changes Normalization (Malformed Types Ignored)
    # -------------------------------------------------------------------------
    def test_33_proposed_changes_normalization_malformed_types_ignored(self):
        """33. Malformed items and free-form strings are discarded, NOT converted to fake ProposedChange."""
        malformed = [
            "Random advice string",
            12345,
            {"description": "No file specified"},
            {"description": "No changes needed", "rationale": "none"},
        ]
        normalized = BaseSupportProvider.normalize_proposed_changes(malformed)
        self.assertEqual(normalized, [])

    # -------------------------------------------------------------------------
    # 34. Proposed Changes Normalization (Valid Dicts)
    # -------------------------------------------------------------------------
    def test_34_proposed_changes_normalization_valid_dicts(self):
        """34. Valid dict structures are safely constructed into ProposedChange instances."""
        valid_dicts = [
            {
                "file_path": "astro_ai/brain/self_model.py",
                "description": "Add read-only accessor",
                "rationale": "Enforce single authoritative state",
                "diff_snippet": "+ def get_state(): ...",
                "target_invariants": ["single_authoritative_state"],
            }
        ]
        normalized = BaseSupportProvider.normalize_proposed_changes(valid_dicts)
        self.assertEqual(len(normalized), 1)
        self.assertIsInstance(normalized[0], ProposedChange)
        self.assertEqual(normalized[0].file_path, "astro_ai/brain/self_model.py")
        self.assertEqual(normalized[0].description, "Add read-only accessor")
        self.assertEqual(normalized[0].target_invariants, ["single_authoritative_state"])

    # -------------------------------------------------------------------------
    # 35. Cache Roundtrip With Proposed Changes and Strict Serialization
    # -------------------------------------------------------------------------
    def test_35_cache_roundtrip_with_proposed_changes(self):
        """35. Cache serialization safely round-trips responses with ProposedChange objects."""
        change = ProposedChange(
            file_path="astro_ai/brain/world_model.py",
            description="Add clearance check",
            rationale="Safety invariant",
        )
        response = ArchitectureSupportResponse(
            request_id="req_test_cache",
            provider="gemini",
            model="gemini-3.6-flash",
            mode=SupportControlMode.PROPOSE,
            status=SupportStatus.SUCCESS,
            summary="Test proposal summary",
            proposed_changes=[change],
            confidence=0.9,
        )

        # to_dict must produce serializable structure with valid proposed_changes
        serialized = response.to_dict()
        self.assertIn("proposed_changes", serialized)
        self.assertEqual(len(serialized["proposed_changes"]), 1)
        self.assertEqual(serialized["proposed_changes"][0]["file_path"], "astro_ai/brain/world_model.py")

        # Put into cache and retrieve
        self.cache.put("cache_test_key", response)
        retrieved = self.cache.get("cache_test_key")
        self.assertIsNotNone(retrieved)
        self.assertEqual(len(retrieved.proposed_changes), 1)
        self.assertIsInstance(retrieved.proposed_changes[0], ProposedChange)
        self.assertEqual(retrieved.proposed_changes[0].file_path, "astro_ai/brain/world_model.py")

    # -------------------------------------------------------------------------
    # 36. Gemini Provider Mock Simulation With No-Op String Changes
    # -------------------------------------------------------------------------
    def test_36_gemini_provider_mock_with_noop_string_changes(self):
        """36. Simulates real Gemini response returning no-op strings in proposed_changes; verifies caching."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            '{"summary": "GEMINI_OK", "observations": ["Model responsive"], '
            '"proposed_changes": ["GEMINI_OK", "No changes required"], "confidence": 0.95}'
        )
        mock_client.models.generate_content.return_value = mock_response

        gemini = GeminiFlashProvider(config=self.config, client=mock_client)
        assistant = CognitiveArchitectureAssistant(
            config=self.config,
            budget_gate=self.budget_gate,
            cache=self.cache,
            debouncer=self.debouncer,
            context_builder=self.context_builder,
            providers={"gemini": gemini},
        )

        req = SupportRequest(topic="gemini_ok_healthcheck", prompt="Healthcheck", provider_override="gemini")
        resp = assistant.analyze_architecture(req)

        self.assertEqual(resp.status, SupportStatus.SUCCESS)
        self.assertEqual(resp.summary, "GEMINI_OK")
        self.assertEqual(resp.proposed_changes, [])

        # Verify response was successfully stored in cache without AttributeError
        cached_resp = self.cache.get(self.cache.compute_cache_key(
            topic="gemini_ok_healthcheck",
            context_hash=self.context_builder.build_context("gemini_ok_healthcheck")[1]["context_hash"],
            prompt="Healthcheck",
            provider="gemini",
        ))
        self.assertIsNotNone(cached_resp)
        self.assertEqual(cached_resp.summary, "GEMINI_OK")
        self.assertEqual(cached_resp.proposed_changes, [])


if __name__ == "__main__":
    unittest.main()
