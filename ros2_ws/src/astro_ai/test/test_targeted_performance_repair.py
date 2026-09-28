#!/usr/bin/env python3
import os
import json
import sys
import unittest
from unittest.mock import MagicMock, patch

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

from astro_ai.local_gemma_client import (
    LocalGemmaClient,
    estimate_tokens,
    bound_messages_to_context,
    LocalGemmaError,
    LocalGemmaEmptyResponseError,
    LocalGemmaTimeoutError,
)
from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.contracts.intent_emotion_types import IntentType
from astro_ai.contracts.social_context import SocialDecision
from astro_ai.brain.intent_engine import IntentEngine


class TestTargetedPerformanceRepair(unittest.TestCase):
    def setUp(self):
        self.node = AstroRealtimeNode(connect_realtime=False)
        self.node.use_realtime = False
        self.node.edge_tts_enabled = True
        self.node._is_playback_active = False
        self.node._barge_in_latched = False
        self.node.tts_router = MagicMock()
        mock_route = MagicMock()
        mock_route.actual_provider = "edge_tts"
        mock_route.source_name = "edge_tts_cloud"
        mock_route.model_name = "tr_tr_ahmet"
        mock_route.pcm = b"\x00\x00" * 12000
        mock_route.duration_ms = 500.0
        mock_route.infer_ms = 100.0
        mock_route.queue_wait_ms = 5.0
        self.node.tts_router.synthesize.return_value = mock_route
        self.node.pub_output_pcm = MagicMock()

    def tearDown(self):
        if hasattr(self.node, "destroy_node"):
            try:
                self.node.destroy_node()
            except Exception:
                pass

    def test_problem_1_gemma_failure_enforces_silence(self):
        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.model_name = "gemma-4-E2B-it-Q4_K_S"
        mock_gemma.stream.side_effect = LocalGemmaTimeoutError("Inference timeout")
        self.node.local_gemma_client = mock_gemma
        self.node._current_turn_explicit_user_turn = True
        self.node._process_fallback_turn(direct_text="Merhaba Astro")

        self.node.tts_router.synthesize.assert_not_called()
        self.node.pub_output_pcm.publish.assert_not_called()
        telem = getattr(self.node, "_last_turn_telemetry", {})
        self.assertEqual(telem.get("response_origin"), "local_gemma_failure")
        self.assertFalse(telem.get("llm_inference_completed"))
        self.assertFalse(telem.get("playback_started"))
        self.assertFalse(telem.get("playback_finished"))

    def test_problem_1_gemma_empty_enforces_silence(self):
        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.model_name = "gemma-4-E2B-it-Q4_K_S"
        mock_gemma.stream.return_value = iter([])
        self.node.local_gemma_client = mock_gemma
        self.node._current_turn_explicit_user_turn = True
        self.node._process_fallback_turn(direct_text="Nasılsın?")

        self.node.tts_router.synthesize.assert_not_called()
        self.node.pub_output_pcm.publish.assert_not_called()
        telem = getattr(self.node, "_last_turn_telemetry", {})
        self.assertEqual(telem.get("response_origin"), "local_gemma_failure")
        self.assertFalse(telem.get("llm_inference_completed"))

    def test_problem_2_context_bounding_under_limit(self):
        huge_text = "Bu uzun bir metin ornegidir ve baglam limitini asmamalidir. " * 150
        est_tokens = estimate_tokens(huge_text)
        self.assertGreater(est_tokens, 512)
        messages = [
            {"role": "system", "content": "Sen ASTRO sun."},
            {"role": "user", "content": huge_text},
        ]
        bounded = bound_messages_to_context(messages, max_tokens=450)
        bounded_tokens = sum(estimate_tokens(m.get("content", "")) for m in bounded)
        self.assertLessEqual(bounded_tokens, 450)

    @patch("urllib.request.urlopen")
    def test_problem_2_client_enforces_context_budget_in_stream(self, mock_urlopen):
        client = LocalGemmaClient(base_url="http://127.0.0.1:8080")
        huge_prompt = "Gemma context sinir testi " * 200
        mock_resp = MagicMock()
        mock_resp.__iter__.return_value = [
            b'data: {"choices": [{"delta": {"content": "Cevap"}, "finish_reason": "stop"}]}\n\n',
            b'data: [DONE]\n\n',
        ]
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        tokens = list(client.stream(huge_prompt))
        self.assertEqual(tokens, ["Cevap"])
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        sent_messages = payload["messages"]
        sent_tokens = sum(estimate_tokens(m["content"]) for m in sent_messages)
        self.assertLessEqual(sent_tokens, 450)

    def test_problem_3_latency_telemetry_populated(self):
        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.model_name = "gemma-4-E2B-it-Q4_K_S"
        mock_gemma.stream.return_value = iter(["Merhaba ", "Baran!"])
        self.node.local_gemma_client = mock_gemma
        self.node._current_turn_explicit_user_turn = True
        self.node._process_fallback_turn(direct_text="Selam")

        telem = getattr(self.node, "_last_turn_telemetry", {})
        self.assertTrue(telem.get("llm_inference_completed"))
        self.assertEqual(telem.get("response_origin"), "local_gemma")
        self.assertIn("prompt_build_ms", telem)
        self.assertIn("inference_request_ms", telem)
        self.assertIn("first_token_ms", telem)
        self.assertIn("generation_ms", telem)
        self.assertIn("total_llm_ms", telem)
        self.assertGreaterEqual(telem["prompt_build_ms"], 0.0)
        self.assertGreaterEqual(telem["total_llm_ms"], 0.0)

    def test_problem_4_baran_identity_grounding(self):
        captured_prompt = []
        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.model_name = "gemma-4-E2B-it-Q4_K_S"
        def capture_stream(prompt, **kwargs):
            captured_prompt.append(prompt)
            yield "Sen benim yaraticim Baran sin."
        mock_gemma.stream.side_effect = capture_stream
        self.node.local_gemma_client = mock_gemma
        self.node._recognized_speaker = {
            "name": "Baran",
            "score": 0.95,
            "is_known": True,
            "confidence": 0.95,
            "source": "voice_recognition",
        }
        self.node._active_person_name = "Baran"
        self.node._current_turn_explicit_user_turn = True
        self.node._process_fallback_turn(direct_text="ben kimim?")

        self.assertTrue(len(captured_prompt) > 0)
        prompt_str = captured_prompt[0]
        self.assertIn("Baran", prompt_str)
        self.assertTrue("sahibin" in prompt_str or "yarat" in prompt_str or "mühendisin" in prompt_str)
        self.assertIn("soruyor", prompt_str)

    def test_problem_4_guest_identity_grounding(self):
        captured_prompt = []
        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.model_name = "gemma-4-E2B-it-Q4_K_S"
        def capture_stream(prompt, **kwargs):
            captured_prompt.append(prompt)
            yield "Henuz tanismadik, adini ogrenebilir miyim?"
        mock_gemma.stream.side_effect = capture_stream
        self.node.local_gemma_client = mock_gemma
        self.node._recognized_speaker = None
        self.node._active_person_name = ""
        self.node._person_hold_until = 0.0
        with patch.object(self.node, "_get_active_biometric_identity", return_value={"name": "Misafir", "is_known": False}):
            self.node._current_turn_explicit_user_turn = True
            self.node._process_fallback_turn(direct_text="ben kimim?")

        self.assertTrue(len(captured_prompt) > 0)
        prompt_str = captured_prompt[0]
        self.assertIn("Misafir", prompt_str)
        self.assertIn("tan", prompt_str)

    def test_existing_speech_gate_regression_no_user_turn_no_speech(self):
        self.node._last_social_decision = SocialDecision(
            should_speak=False,
            initiative_reason="gate_closed_test",
            response_strategy=["Sessiz kal"],
            gate_mode="OBSERVING",
        )
        self.node._build_current_system_prompt = MagicMock(return_value="System Prompt")
        mock_gemma = MagicMock(spec=LocalGemmaClient)
        self.node.local_gemma_client = mock_gemma
        self.node._process_fallback_turn(direct_text="Merhaba")
        mock_gemma.stream.assert_not_called()
        self.node.tts_router.synthesize.assert_not_called()
        self.node.pub_output_pcm.publish.assert_not_called()

    def test_existing_intent_regression_activity_query(self):
        intent, _ = IntentEngine.classify_intent("ben şu anda ne yapıyorum?")
        self.assertEqual(intent, IntentType.ACTIVITY_QUERY)


    @patch("urllib.request.urlopen")
    def test_problem_3_local_gemma_latency_optimizations_payload_and_caching(self, mock_urlopen):
        client = LocalGemmaClient(base_url="http://127.0.0.1:8080")
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__iter__.return_value = [
            b'data: {"choices": [{"delta": {"content": "Merhaba!"}, "finish_reason": "stop"}]}\n\n',
            b'data: [DONE]\n\n',
        ]
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        tokens = list(client.stream("Selam"))
        self.assertEqual(tokens, ["Merhaba!"])

        # Verify optimized payload sent to llama-server
        req = mock_urlopen.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        self.assertTrue(payload.get("cache_prompt"))
        self.assertIn("stop", payload)
        self.assertIn("\nKullanıcı:", payload["stop"])
        self.assertIn("<end_of_turn>", payload["stop"])
        self.assertEqual(payload.get("top_k"), 40)
        self.assertEqual(req.headers.get("Connection"), "keep-alive")

        # Verify client health status was cached after successful streaming
        self.assertTrue(client.is_available())
        # No extra urlopen call for /health was needed because health was refreshed by inference
        self.assertEqual(mock_urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
