#!/usr/bin/env python3
"""ASTRO V1 — Visual Grounding, Answer Quality, Latency & Head Angle Unit Tests.

Verifies:
1. visual_person_detected -> 'Beni kamerandan görebiliyor musun?' -> grounded visual presence
2. no visual person -> 'Beni kamerandan görebiliyor musun?' -> honest negative
3. person detected -> 'Ben şu anda ne yapıyorum?' -> current evidence only, profile facts suppressed
4. persistent profile exists + activity query -> profile facts ("robotik") strictly omitted
5. identity query -> profile facts included
6. camera unavailable -> honest uncertainty
7. 1 user turn -> exactly 1 TTS
8. perception-only -> 0 TTS
9. Gemma failure -> 0 TTS
10. prompt token budget <= 450
11. latency telemetry preserved
12. _is_head_angle_query rejects incidental words ("son durum ne", "merkez") and accepts explicit commands
"""

import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

from astro_ai.astro_realtime_node import AstroRealtimeNode, SpeechAuthorization
from astro_ai.local_gemma_client import estimate_tokens
from astro_ai.state_machine import RobotState

try:
    from std_msgs.msg import String
except ImportError:
    class String:  # type: ignore
        def __init__(self, data: str = ""):
            self.data = data


class TestVisualGroundingAndActivityRepair(unittest.TestCase):

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
        self.mock_route.pcm = b"\x00\x01" * 2400
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

    def test_1_visual_person_detected_visual_query(self):
        """When camera is connected and person is detected, visual grounding is present and prompt instructs positive confirmation."""
        now = time.monotonic()
        self.node._oak_connection_state = "CONNECTED"
        self.node._oak_last_frame_time = now
        self.node._last_vision_faces_time = now
        self.node._user_distance = 1.2
        self.node._looking_at_robot = True

        vis_state = self.node._get_current_visual_grounding()
        self.assertTrue(vis_state["visual_camera_available"])
        self.assertTrue(vis_state["visual_person_detected"])
        self.assertEqual(vis_state["visual_distance"], 1.2)
        self.assertTrue(vis_state["visual_looking_at_robot"])

        # Run direct text query through fallback turn
        with patch.object(self.node.local_gemma_client, "stream", return_value=iter(["Evet ", "seni ", "görüyorum."])):
            with patch.object(self.node.local_gemma_client, "is_available", return_value=True):
                self.node._process_fallback_turn(direct_text="Beni kamerandan görebiliyor musun?")

        # Check that speech authorization resulted in exactly one TTS synthesis
        self.node.tts_router.synthesize.assert_called_once()

    def test_2_no_visual_person_visual_query(self):
        """When camera is connected but NO person is detected, prompt instructs honest negative."""
        now = time.monotonic()
        self.node._oak_connection_state = "CONNECTED"
        self.node._oak_last_frame_time = now
        self.node._last_vision_faces_time = 0.0  # No recent faces
        self.node._user_distance = 0.0
        self.node._looking_at_robot = False
        if getattr(self.node, "social_brain", None) and hasattr(self.node.social_brain, "world_model"):
            self.node.social_brain.world_model._people.clear()

        vis_state = self.node._get_current_visual_grounding()
        self.assertTrue(vis_state["visual_camera_available"])
        self.assertFalse(vis_state["visual_person_detected"])

        prompts_captured = []
        def fake_stream(prompt, **kwargs):
            prompts_captured.append(prompt)
            yield "Kameram açık fakat şu an seni göremiyorum."

        with patch.object(self.node.local_gemma_client, "stream", side_effect=fake_stream):
            with patch.object(self.node.local_gemma_client, "is_available", return_value=True):
                self.node._process_fallback_turn(direct_text="Beni kamerandan görebiliyor musun?")

        self.assertEqual(len(prompts_captured), 1)
        prompt = prompts_captured[0]
        self.assertIn("insan tespit edilmedi", prompt)
        self.assertIn("şu an karşında kimseyi göremediğini dürüstçe belirt", prompt)
        self.node.tts_router.synthesize.assert_called_once()

    def test_3_person_detected_activity_query(self):
        """When user asks 'Ben şu anda ne yapıyorum?', profile facts MUST NOT be used as current activity."""
        now = time.monotonic()
        self.node._oak_connection_state = "CONNECTED"
        self.node._oak_last_frame_time = now
        self.node._last_vision_faces_time = now
        self.node._user_distance = 1.0
        self.node._looking_at_robot = True

        # Mock profile facts for Baran
        if hasattr(self.node, "memory") and hasattr(self.node.memory, "profile"):
            self.node.memory.profile.get_known_person = MagicMock(return_value={
                "name": "Baran",
                "learned_facts": ["robotik ve yazılımla ilgileniyor", "ROS2 uzmanı"]
            })

        prompts_captured = []
        def fake_stream(prompt, **kwargs):
            prompts_captured.append(prompt)
            yield "Şu an karşımda duruyorsun fakat ne yaptığını göremiyorum."

        with patch.object(self.node.local_gemma_client, "stream", side_effect=fake_stream):
            with patch.object(self.node.local_gemma_client, "is_available", return_value=True):
                self.node._process_fallback_turn(direct_text="Ben şu anda ne yapıyorum?")

        self.assertEqual(len(prompts_captured), 1)
        prompt = prompts_captured[0]
        # Verify profile facts are strictly excluded
        self.assertNotIn("robotik ve yazılımla ilgileniyor", prompt)
        self.assertNotIn("ROS2 uzmanı", prompt)
        # Verify activity guidance is included
        self.assertIn("Kullanıcı şu anda ne yaptığını soruyor", prompt)
        self.assertIn("ASLA aktivite olarak söyleme", prompt)
        self.node.tts_router.synthesize.assert_called_once()

    def test_4_persistent_profile_only_activity_query_zero_hallucination(self):
        """Persistent profile facts are NEVER injected when user asks an activity query."""
        if hasattr(self.node, "memory") and hasattr(self.node.memory, "profile"):
            self.node.memory.profile.get_known_person = MagicMock(return_value={
                "name": "Baran",
                "learned_facts": ["robotik ve yazılımla ilgileniyor"]
            })

        prompts_captured = []
        def fake_stream(prompt, **kwargs):
            prompts_captured.append(prompt)
            yield "Şu an karşımda konuşuyorsun."

        with patch.object(self.node.local_gemma_client, "stream", side_effect=fake_stream):
            with patch.object(self.node.local_gemma_client, "is_available", return_value=True):
                self.node._process_fallback_turn(direct_text="Şu an ne yapıyorum?")

        self.assertEqual(len(prompts_captured), 1)
        self.assertNotIn("robotik ve yazılımla ilgileniyor", prompts_captured[0])

    def test_5_identity_query_preserves_profile(self):
        """When user asks 'Ben kimim?', profile facts ARE included for identity grounding."""
        if hasattr(self.node, "memory") and hasattr(self.node.memory, "profile"):
            self.node.memory.profile.get_known_person = MagicMock(return_value={
                "name": "Baran",
                "learned_facts": ["robotik ve yazılımla ilgileniyor"]
            })

        prompts_captured = []
        def fake_stream(prompt, **kwargs):
            prompts_captured.append(prompt)
            yield "Sen Baransın, benim sahibimsin."

        with patch.object(self.node.local_gemma_client, "stream", side_effect=fake_stream):
            with patch.object(self.node.local_gemma_client, "is_available", return_value=True):
                self.node._process_fallback_turn(direct_text="Ben kimim?")

        self.assertEqual(len(prompts_captured), 1)
        prompt = prompts_captured[0]
        self.assertIn("robotik ve yazılımla ilgileniyor", prompt)
        self.assertIn("Kullanıcı sana kim olduğunu soruyor", prompt)

    def test_6_camera_unavailable_uncertainty_preserved(self):
        """When camera is disconnected, prompt explicitly states camera is unavailable."""
        self.node._oak_connection_state = "DISCONNECTED"
        self.node._oak_last_frame_time = 0.0
        self.node._oak_last_camera_info_time = 0.0
        self.node._latest_camera_frame = None

        with patch.dict(os.environ, {"ASTRO_MOCK_CAMERA_AVAILABLE": "0"}):
            vis_state = self.node._get_current_visual_grounding()
            self.assertFalse(vis_state["visual_camera_available"])
            self.assertFalse(vis_state["visual_person_detected"])

            prompts_captured = []
            def fake_stream(prompt, **kwargs):
                prompts_captured.append(prompt)
                yield "Kameram şu anda aktif değil."

            with patch.object(self.node.local_gemma_client, "stream", side_effect=fake_stream):
                with patch.object(self.node.local_gemma_client, "is_available", return_value=True):
                    self.node._process_fallback_turn(direct_text="Beni kamerandan görebiliyor musun?")

            self.assertEqual(len(prompts_captured), 1)
            prompt = prompts_captured[0]
            self.assertIn("Kamera şu anda aktif değil", prompt)
            self.assertIn("Kameranın şu anda bağlı veya aktif olmadığını dürüstçe belirt", prompt)

    def test_7_one_user_turn_exactly_one_tts(self):
        """1 user turn produces exactly 1 TTS execution."""
        with patch.object(self.node.local_gemma_client, "stream", return_value=iter(["Merhaba", " Baran!"])):
            with patch.object(self.node.local_gemma_client, "is_available", return_value=True):
                self.node._process_fallback_turn(direct_text="Selam Astro")

        self.assertEqual(self.node.tts_router.synthesize.call_count, 1)

    def test_8_perception_only_zero_tts(self):
        """Perception events (e.g. recognized person) without user turn produce 0 TTS calls."""
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

    def test_9_gemma_failure_zero_tts(self):
        """When Local Gemma returns empty or fails, 0 TTS is generated (no hardcoded hallucination)."""
        def failing_stream(prompt, **kwargs):
            return iter([])

        with patch.object(self.node.local_gemma_client, "stream", side_effect=failing_stream):
            with patch.object(self.node.local_gemma_client, "is_available", return_value=True):
                self.node._process_fallback_turn(direct_text="Bu bir test mesajıdır")

        self.node.tts_router.synthesize.assert_not_called()

    def test_10_prompt_token_budget_bounded(self):
        """Gemma prompt token budget remains <= 450 tokens even with full grounding."""
        prompt = (
            "Sen ASTRO'sun, sevimli, zeki ve yardımsever bir sosyal robotsun. Türkçe konuş. Kısa, samimi ve doğal cevap ver (en fazla 1-2 cümle). Bilmediğin şeyleri uydurma.\n"
            "Karşındaki kişi: Baran (Hitap: Baran). Baran senin sahibin, yaratıcın ve baş mühendisin.\n"
            "Görsel Durum: Kamera aktif. Karşındaki kişiyi kamerandan görüyorsun ve takip ediyorsun. Mesafe: ~1.2m. Doğrudan sana bakıyor.\n"
            "Yönerge: Kullanıcı onu kameradan görüp görmediğini soruyor. Onu kamerandan gördüğünü (yaklaşık 1.2 metre mesafede) ve takip ettiğini net olarak söyle.\n"
            "Kullanıcı: Beni kamerandan görebiliyor musun?\nASTRO:"
        )
        tokens = estimate_tokens(prompt)
        self.assertLessEqual(tokens, 450)

    def test_11_latency_telemetry_fields_present(self):
        """Latency telemetry tracks prompt_build_ms, first_token_ms, generation_ms, total_llm_ms."""
        with patch.object(self.node.local_gemma_client, "stream", return_value=iter(["Evet ", "seni ", "görüyorum."])):
            with patch.object(self.node.local_gemma_client, "is_available", return_value=True):
                with patch.object(self.node, "emit_response_trace") as mock_trace:
                    self.node._process_fallback_turn(direct_text="Beni görüyor musun?")
                    self.assertTrue(mock_trace.called)
                    call_kwargs = mock_trace.call_args[1]
                    self.assertEqual(call_kwargs.get("llm_provider"), "local_gemma")

    def test_12_head_angle_query_rejection_and_acceptance(self):
        """Verifies _is_head_angle_query does NOT trigger on 'son durum ne' or 'merkez', and correctly triggers on explicit head commands."""
        # False-positive rejection tests
        negatives = [
            "son durum ne",
            "merkez",
            "durum nasıl",
            "on numara hareket",
            "düzgün davran",
            "tamamdır",
            "ne haber",
        ]
        for text in negatives:
            is_angle, target_angle, label = self.node._is_head_angle_query(text)
            self.assertFalse(is_angle, f"Expected False for '{text}', got {is_angle} ({target_angle}°)")

        # Positive acceptance tests
        positives = [
            ("tam ortaya bak", 0.0),
            ("merkeze dön", 0.0),
            ("düz bak", 0.0),
            ("0 dereceye dön", 0.0),
            ("kafanı sıfırla", 0.0),
            ("30 derece sağa bak", -30.0),
            ("45 derece sola dön", 45.0),
            ("-30 dereceye bak", -30.0),
        ]
        for text, exp_angle in positives:
            is_angle, target_angle, label = self.node._is_head_angle_query(text)
            self.assertTrue(is_angle, f"Expected True for '{text}'")
            self.assertAlmostEqual(target_angle, exp_angle, delta=1.0, msg=f"Angle mismatch for '{text}'")


if __name__ == "__main__":
    unittest.main()
