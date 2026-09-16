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

from astro_ai.local_gemma_client import LocalGemmaClient, LocalGemmaTimeoutError
from astro_ai.astro_realtime_node import AstroRealtimeNode, SpeechAuthorization
from astro_ai.state_machine import RobotState
try:
    from std_msgs.msg import String
except ImportError:
    class String:  # type: ignore
        def __init__(self, data: str = ""):
            self.data = data


class TestSpeechAuthorizationHardFix(unittest.TestCase):
    """Authoritative test suite verifying Rule 1-15 of ASTRO Speech Authorization Hard Fix.
    Enforces the invariant:
    validated user_turn_id + explicit_user_turn=True + should_speak=True + current/valid generation_id + valid speech_authorization -> TTS
    Missing any of these -> NO TTS, NO playback.
    """

    def setUp(self):
        try:
            import rclpy
            if not rclpy.ok():
                rclpy.init(args=None)
        except Exception:
            pass

        self.node = AstroRealtimeNode(connect_realtime=False)
        self.node.use_realtime = False
        self.node.edge_tts_enabled = True
        self.node._is_playback_active = False
        self.node._barge_in_latched = False
        self.node._is_processing_fallback = False
        self.node._is_responding = False
        self.node._is_sleeping = False
        self.node._is_quiet_mode = False
        if hasattr(self.node, "state_machine"):
            self.node.state_machine.transition_to(RobotState.LISTENING)

        self.mock_route = MagicMock()
        self.mock_route.actual_provider = "edge_tts"
        self.mock_route.source_name = "edge_tts_cloud"
        self.mock_route.model_name = "tr_tr_ahmet"
        self.mock_route.pcm = b"\x00\x01" * 2400  # 100ms 24kHz int16
        self.mock_route.duration_ms = 100.0
        self.mock_route.infer_ms = 40.0
        self.mock_route.queue_wait_ms = 0.0

        self.node.tts_router = MagicMock()
        self.node.tts_router.synthesize.return_value = self.mock_route
        self.node.pub_output_pcm = MagicMock()

    def tearDown(self):
        if hasattr(self.node, "destroy_node"):
            try:
                self.node.destroy_node()
            except Exception:
                pass

    # A. person detected, no user turn -> 0 TTS
    def test_A_person_detected_no_user_turn_zero_tts(self):
        with patch.object(self.node, "_trigger_proactive_greeting") as mock_greet:
            person_msg = String()
            person_msg.data = json.dumps({
                "name": "Baran",
                "title": "Geliştirici",
                "is_known": True,
                "confidence": 0.95,
            })
            self.node._on_recognized_person(person_msg)
            mock_greet.assert_not_called()
            self.node.tts_router.synthesize.assert_not_called()
            self.node.pub_output_pcm.publish.assert_not_called()

    # B. cognition ACTIVE_SOCIAL_ENGAGEMENT, no user turn -> 0 TTS
    def test_B_cognition_active_social_engagement_no_user_turn_zero_tts(self):
        for reason in [
            "person_detected", "orient_to_stimulus", "active_social_engagement",
            "visual_tracking", "speaking_active_dialogue_engagement", "cognition_only"
        ]:
            allowed, block_reason = self.node.authorize_speech(
                user_turn_id="turn_99",
                generation_id=99,
                response_text="Ben konuşmaya çalışıyorum",
                is_final_response=True,
                is_deterministic=False,
                is_llm_completed=True,
                caller_reason=reason,
            )
            self.assertFalse(allowed, f"Should block for reason {reason}")
            self.assertEqual(block_reason, "cognition_only")
        self.node.tts_router.synthesize.assert_not_called()
        self.node.pub_output_pcm.publish.assert_not_called()

    # C. visual tracking for multiple cycles -> 0 TTS
    def test_C_visual_tracking_multiple_cycles_zero_tts(self):
        faces_msg = String()
        faces_msg.data = json.dumps([{
            "name": "Baran",
            "recognized_name": "Baran",
            "is_known": True,
            "distance_m": 1.2,
            "looking_at_robot": True,
            "yaw_deg": 5.0,
        }])
        for _ in range(50):
            self.node._on_faces(faces_msg)
        self.node.tts_router.synthesize.assert_not_called()
        self.node.pub_output_pcm.publish.assert_not_called()

    # D. phantom STT -> 0 TTS
    def test_D_phantom_stt_drops_turn_zero_tts(self):
        self.node.session._is_active = False
        self.node._validate_stt_transcript = MagicMock(return_value=("Evet.", {"vad_confidence": 0.9, "rms": 300}))
        fake_audio = [b"\x00\x01" * 1600] * 15
        self.node._process_fallback_turn(audio_chunks=fake_audio)
        self.node.tts_router.synthesize.assert_not_called()
        self.node.pub_output_pcm.publish.assert_not_called()
        self.assertFalse(self.node._last_explicit_user_turn)

    # E. one valid user turn + Gemma success -> exactly 1 generation + exactly 1 TTS
    def test_E_one_valid_user_turn_gemma_success_single_tts(self):
        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.model_name = "gemma-4-E2B-it-Q4_K_S"
        mock_gemma.stream.return_value = ["Merhaba ", "Baran, ", "nasılsın?"]
        self.node.local_gemma_client = mock_gemma
        self.node._current_turn_explicit_user_turn = True

        self.node._process_fallback_turn(direct_text="Merhaba Astro")

        self.assertEqual(self.node.tts_router.synthesize.call_count, 1)
        call_kwargs = self.node.tts_router.synthesize.call_args[1]
        self.assertEqual(call_kwargs.get("realtime_fallback_reason"), "local_mode_configured")
        self.assertTrue(self.node.pub_output_pcm.publish.called)

    # F. one valid user turn + deterministic response -> exactly 1 TTS
    def test_F_one_valid_user_turn_deterministic_response_single_tts(self):
        self.node.pub_head_target_yaw = MagicMock()
        self.node._current_turn_explicit_user_turn = True

        self.node._process_fallback_turn(direct_text="0 dereceye dön")

        self.assertEqual(self.node.tts_router.synthesize.call_count, 1)
        call_kwargs = self.node.tts_router.synthesize.call_args[1]
        self.assertEqual(call_kwargs.get("realtime_fallback_reason"), "local_mode_configured")
        self.assertTrue(self.node.pub_output_pcm.publish.called)

    # G. same generation_id second TTS request -> BLOCKED (authorization_consumed)
    def test_G_same_generation_second_tts_blocked(self):
        gen_id = 42
        turn_id = f"turn_{gen_id}"
        self.node._fallback_generation_id = gen_id
        self.node._current_user_turn_id = turn_id
        self.node._current_turn_explicit_user_turn = True
        self.node._speech_authorization = SpeechAuthorization(
            user_turn_id=turn_id,
            generation_id=gen_id,
            explicit_user_turn=True,
            should_speak=True,
            response_origin="local_gemma",
            llm_inference_completed=True,
            response_final=True,
        )

        allowed1, reason1 = self.node.authorize_speech(
            user_turn_id=turn_id,
            generation_id=gen_id,
            response_text="İlk yetkili cevap.",
            is_final_response=True,
            is_deterministic=False,
            is_llm_completed=True,
            caller_reason="user_turn_response",
        )
        self.assertTrue(allowed1)
        self.assertEqual(reason1, "authorized")

        allowed2, reason2 = self.node.authorize_speech(
            user_turn_id=turn_id,
            generation_id=gen_id,
            response_text="İkinci izinsiz istek.",
            is_final_response=True,
            is_deterministic=False,
            is_llm_completed=True,
            caller_reason="user_turn_response",
        )
        self.assertFalse(allowed2)
        self.assertEqual(reason2, "authorization_consumed")

    # H. TTS request before LLM completion -> BLOCKED (llm_not_completed)
    def test_H_tts_request_before_llm_completion_blocked(self):
        gen_id = 43
        turn_id = f"turn_{gen_id}"
        self.node._fallback_generation_id = gen_id
        self.node._current_user_turn_id = turn_id
        self.node._current_turn_explicit_user_turn = True
        self.node._speech_authorization = SpeechAuthorization(
            user_turn_id=turn_id,
            generation_id=gen_id,
            explicit_user_turn=True,
            should_speak=True,
            response_origin="local_gemma",
            llm_inference_completed=False,
            response_final=False,
        )

        allowed, reason = self.node.authorize_speech(
            user_turn_id=turn_id,
            generation_id=gen_id,
            response_text="Erken parça",
            is_final_response=False,
            is_deterministic=False,
            is_llm_completed=False,
            caller_reason="streaming_chunk",
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "llm_not_completed")

    # I. Gemma failure -> 0 TTS
    def test_I_gemma_failure_enforces_zero_tts(self):
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

    # J. old turn reused after completion -> BLOCKED (stale_turn / no_user_turn)
    def test_J_old_turn_reused_after_completion_blocked(self):
        mock_gemma = MagicMock(spec=LocalGemmaClient)
        mock_gemma.is_available.return_value = True
        mock_gemma.model_name = "gemma-4-E2B-it-Q4_K_S"
        mock_gemma.stream.return_value = ["Cevap tamamlandı."]
        self.node.local_gemma_client = mock_gemma
        self.node._current_turn_explicit_user_turn = True

        self.node._process_fallback_turn(direct_text="Merhaba")
        finished_gen_id = self.node._fallback_generation_id
        old_turn_id = f"turn_{finished_gen_id}"

        self.assertIsNone(self.node._current_user_turn_id)
        self.assertIsNone(self.node._speech_authorization)

        allowed, reason = self.node.authorize_speech(
            user_turn_id=old_turn_id,
            generation_id=finished_gen_id,
            response_text="Eski turn üzerinden konuşma",
            is_final_response=True,
            is_deterministic=False,
            is_llm_completed=True,
            caller_reason="user_turn_response",
        )
        self.assertFalse(allowed)
        self.assertIn(reason, ("no_user_turn", "stale_turn"))

    # K. quiet / deep idle without new user turn -> 0 TTS
    def test_K_quiet_or_deep_idle_without_new_user_turn_zero_tts(self):
        self.node._is_quiet_mode = True
        self.node._current_turn_explicit_user_turn = False
        allowed, reason = self.node.authorize_speech(
            user_turn_id="turn_50",
            generation_id=50,
            response_text="Sessiz modda konuşma",
            is_final_response=True,
            is_deterministic=False,
            is_llm_completed=True,
            caller_reason="user_turn_response",
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "quiet_or_sleep")
        self.node.tts_router.synthesize.assert_not_called()
        self.node.pub_output_pcm.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
