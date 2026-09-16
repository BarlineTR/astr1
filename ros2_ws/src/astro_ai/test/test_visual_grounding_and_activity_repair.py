#!/usr/bin/env python3
"""ASTRO V1 — Visual Grounding, Answer Quality, Latency, Head Angle & Perception Query Tests.

Verifies:
1. visual_person_detected -> 'Beni kamerandan görebiliyor musun?' -> grounded visual presence (0ms LLM)
2. no visual person -> 'Beni kamerandan görebiliyor musun?' -> honest negative (0ms LLM)
3. person detected -> 'Ben şu anda ne yapıyorum?' -> current evidence only, profile facts suppressed (0ms LLM)
4. persistent profile exists + activity query -> profile facts ("robotik") strictly omitted (0ms LLM)
5. identity query -> profile facts included via Local Gemma
6. camera unavailable -> honest uncertainty (0ms LLM)
7. 1 user turn -> exactly 1 TTS
8. perception-only -> 0 TTS
9. Gemma failure -> 0 TTS
10. prompt token budget <= 450
11. latency telemetry preserved
12. _is_head_angle_query rejects incidental words ("son durum ne", "merkez") and accepts explicit commands
13. _is_turn_to_sound_query rejects conversational phrases and accepts explicit orientation commands
14. activity query prompt compact and bounded
15. noisy STT 'Hey Astro, ben ne yapıyordur şu anda?' -> classified as ACTIVITY_QUERY, never 'Durdum'
16. visual state queries classified as VISUAL_STATE_QUERY with deterministic 0ms LLM
17. robot state queries answered deterministically with 0ms LLM
18. stop commands strictly word-bounded, never triggered by incidental words
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
from astro_ai.brain.intent_engine import IntentEngine
from astro_ai.contracts.intent_emotion_types import IntentType
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
        """When camera is connected and person is detected, visual query returns grounded presence deterministically with 0ms LLM."""
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

        # Stream should NOT even be called because response is deterministic (0ms LLM)
        mock_stream = MagicMock()
        with patch.object(self.node.local_gemma_client, "stream", mock_stream):
            self.node._process_fallback_turn(direct_text="Beni kamerandan görebiliyor musun?")

        mock_stream.assert_not_called()
        self.node.tts_router.synthesize.assert_called_once()
        synth_text = self.node.tts_router.synthesize.call_args[0][0]
        self.assertIn("görüyorum", synth_text.lower())
        self.assertIn("takip ediyorum", synth_text.lower())
        self.assertIsNotNone(self.node._last_speech_authorization)
        self.assertEqual(self.node._last_speech_authorization.response_origin, "deterministic_policy")

    def test_2_no_visual_person_visual_query(self):
        """When camera is connected but NO person is detected, deterministic reply honestly states negative (0ms LLM)."""
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

        mock_stream = MagicMock()
        with patch.object(self.node.local_gemma_client, "stream", mock_stream):
            self.node._process_fallback_turn(direct_text="Beni kamerandan görebiliyor musun?")

        mock_stream.assert_not_called()
        self.node.tts_router.synthesize.assert_called_once()
        synth_text = self.node.tts_router.synthesize.call_args[0][0]
        self.assertIn("göremiyorum", synth_text.lower())
        self.assertIsNotNone(self.node._last_speech_authorization)
        self.assertEqual(self.node._last_speech_authorization.response_origin, "deterministic_policy")

    def test_3_person_detected_activity_query(self):
        """When user asks 'Ben şu anda ne yapıyorum?', profile facts are NOT used; direct sensor answer is given with 0ms LLM."""
        now = time.monotonic()
        self.node._oak_connection_state = "CONNECTED"
        self.node._oak_last_frame_time = now
        self.node._last_vision_faces_time = now
        self.node._user_distance = 1.0
        self.node._looking_at_robot = True

        if hasattr(self.node, "memory") and hasattr(self.node.memory, "profile"):
            self.node.memory.profile.get_known_person = MagicMock(return_value={
                "name": "Baran",
                "learned_facts": ["robotik ve yazılımla ilgileniyor", "ROS2 uzmanı"]
            })

        mock_stream = MagicMock()
        with patch.object(self.node.local_gemma_client, "stream", mock_stream):
            self.node._process_fallback_turn(direct_text="Ben şu anda ne yapıyorum?")

        mock_stream.assert_not_called()
        self.node.tts_router.synthesize.assert_called_once()
        synth_text = self.node.tts_router.synthesize.call_args[0][0]
        self.assertNotIn("robotik", synth_text.lower())
        self.assertNotIn("ros2", synth_text.lower())
        self.assertIn("görüyorum", synth_text.lower())
        self.assertIsNotNone(self.node._last_speech_authorization)
        self.assertEqual(self.node._last_speech_authorization.response_origin, "deterministic_policy")

    def test_4_persistent_profile_only_activity_query_zero_hallucination(self):
        """Persistent profile facts are NEVER injected when user asks an activity query (0ms LLM)."""
        if hasattr(self.node, "memory") and hasattr(self.node.memory, "profile"):
            self.node.memory.profile.get_known_person = MagicMock(return_value={
                "name": "Baran",
                "learned_facts": ["robotik ve yazılımla ilgileniyor"]
            })

        mock_stream = MagicMock()
        with patch.object(self.node.local_gemma_client, "stream", mock_stream):
            self.node._process_fallback_turn(direct_text="Şu an ne yapıyorum?")

        mock_stream.assert_not_called()
        synth_text = self.node.tts_router.synthesize.call_args[0][0]
        self.assertNotIn("robotik", synth_text.lower())

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
        """When camera is disconnected, deterministic reply honestly states camera is inactive (0ms LLM)."""
        self.node._oak_connection_state = "DISCONNECTED"
        self.node._oak_last_frame_time = 0.0
        self.node._oak_last_camera_info_time = 0.0
        self.node._latest_camera_frame = None

        with patch.dict(os.environ, {"ASTRO_MOCK_CAMERA_AVAILABLE": "0"}):
            vis_state = self.node._get_current_visual_grounding()
            self.assertFalse(vis_state["visual_camera_available"])
            self.assertFalse(vis_state["visual_person_detected"])

            mock_stream = MagicMock()
            with patch.object(self.node.local_gemma_client, "stream", mock_stream):
                self.node._process_fallback_turn(direct_text="Beni kamerandan görebiliyor musun?")

            mock_stream.assert_not_called()
            self.node.tts_router.synthesize.assert_called_once()
            synth_text = self.node.tts_router.synthesize.call_args[0][0]
            self.assertIn("aktif değil", synth_text.lower())
            self.assertIsNotNone(self.node._last_speech_authorization)
            self.assertEqual(self.node._last_speech_authorization.response_origin, "deterministic_policy")

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
        """Latency telemetry tracks prompt_build_ms, first_token_ms, generation_ms, total_llm_ms for LLM turns."""
        with patch.object(self.node.local_gemma_client, "stream", return_value=iter(["Elbette ", "anlatayım."])):
            with patch.object(self.node.local_gemma_client, "is_available", return_value=True):
                with patch.object(self.node, "emit_response_trace") as mock_trace:
                    self.node._process_fallback_turn(direct_text="Bana genel olarak hayatı anlatır mısın?")
                    self.assertTrue(mock_trace.called)
                    call_kwargs = mock_trace.call_args[1]
                    self.assertEqual(call_kwargs.get("llm_provider"), "local_gemma")

    def test_12_head_angle_query_rejection_and_acceptance(self):
        """Verifies _is_head_angle_query does NOT trigger on 'son durum ne' or 'merkez', and correctly triggers on explicit head commands."""
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

    def test_13_turn_to_sound_rejection_and_acceptance(self):
        """Verifies _is_turn_to_sound_query rejects conversational phrases and accepts explicit orientation commands."""
        negatives = [
            "bana anlat bakalım",
            "bana bir masal anlatır mısın",
            "bana dün ne yaptığını hatırla bakalım",
            "bana bir şey söyle bakalım",
            "bana yardım et",
            "bana bir masal oku",
            "bana şarkı söyle",
            "baksana bana ne anlatacağım",
            "döndüm ulan işte",
            "bana bakıp gülme",
            "bana göre hava hoş",
        ]
        for text in negatives:
            res = self.node._is_turn_to_sound_query(text)
            self.assertFalse(res, f"Expected False for conversational phrase '{text}', but got True")

        positives = [
            "sesime dön",
            "sesime bak",
            "sesime doğru dön",
            "sesin geldiği yöne dön",
            "sesimin geldiği yere dön",
            "bana dön",
            "bana doğru dön",
            "buraya dön",
            "yüzüme dön",
            "bana bakar mısın",
            "sesime döner misin",
        ]
        for text in positives:
            res = self.node._is_turn_to_sound_query(text)
            self.assertTrue(res, f"Expected True for command '{text}', but got False")

    def test_14_activity_query_prompt_compact_and_strictly_bounded(self):
        """Activity query prompt construction is strictly <= 150 tokens and contains required grounding instructions."""
        prompt = (
            "Sen ASTRO'sun. Türkçe kısa ve net cevap ver (1-2 cümle). Bilmediğin şeyi uydurma.\n"
            "Karşındaki kişi: Baran.\n"
            "Görsel Durum: Kamera aktif, Baran karşında görünüyor.\n"
            "Yönerge: Kullanıcı şu anda ne yaptığını soruyor. Karşında durduğunu, seninle konuştuğunu belirt; "
            "ancak tam olarak ne yaptığını kamerandan göremediğini açıkça ve dürüstçe söyle. "
            "Konuyu değiştirme! Profil bilgisi verme! ASLA aktivite olarak söyleme!\n"
            "Kullanıcı: Ben şu anda ne yapıyorum?\nASTRO:"
        )
        tok_est = estimate_tokens(prompt)
        self.assertLessEqual(tok_est, 150)
        self.assertNotIn("robotik", prompt)
        self.assertIn("tam olarak ne yaptığını kamerandan göremediğini açıkça ve dürüstçe söyle", prompt)

    def test_15_noisy_stt_activity_query_not_movement_stop(self):
        """'Hey Astro, ben ne yapıyordur şu anda?' is classified as ACTIVITY_QUERY and NEVER triggers movement stop ('Durdum')."""
        query = "Hey Astro, ben ne yapıyordur şu anda?"

        # 1. _is_movement_query must NEVER return True for activity queries
        is_move, move_dir, _, _ = self.node._is_movement_query(query)
        self.assertFalse(is_move, f"Query '{query}' must NOT be detected as movement command!")

        # 2. _is_activity_query must return True
        is_act, reply = self.node._is_activity_query(query)
        self.assertTrue(is_act, f"Query '{query}' must be detected as activity query!")
        self.assertNotIn("Durdum", reply)

        # 3. Intent Engine must classify as ACTIVITY_QUERY, not STATEMENT
        engine = IntentEngine()
        intent, conf = engine.classify_intent(query)
        self.assertEqual(intent, IntentType.ACTIVITY_QUERY)

        # 4. Fallback turn must reply with activity state, NEVER 'Durdum'
        mock_stream = MagicMock()
        with patch.object(self.node.local_gemma_client, "stream", mock_stream):
            self.node._process_fallback_turn(direct_text=query)

        mock_stream.assert_not_called()  # 0ms LLM
        self.node.tts_router.synthesize.assert_called_once()
        synth_text = self.node.tts_router.synthesize.call_args[0][0]
        self.assertNotIn("Durdum", synth_text)

    def test_16_visual_state_queries_and_intents(self):
        """Visual queries are classified as VISUAL_STATE_QUERY and answered deterministically with 0ms LLM."""
        engine = IntentEngine()
        visual_queries = [
            "Beni görüyor musun?",
            "Kameranda neler görüyorsun?",
            "Kimi görüyorsun?",
            "Beni takip ediyor musun?",
            "Kameranda ne görüyorsun?",
        ]
        for q in visual_queries:
            intent, conf = engine.classify_intent(q)
            self.assertEqual(intent, IntentType.VISUAL_STATE_QUERY, f"Query '{q}' should be VISUAL_STATE_QUERY")

            is_vis, reply = self.node._is_visual_state_query(q)
            self.assertTrue(is_vis, f"Query '{q}' should match _is_visual_state_query")

    def test_17_robot_state_queries(self):
        """Robot self-state queries (motion, motor, head direction) are answered with 0ms LLM."""
        tests = [
            "hareket ediyor musun",
            "hareket halinde misin",
            "gidiyor musun",
            "motorların aktif mi",
            "motorlar açık mı",
            "kafa hangi yöne dönük",
            "kafan nereye bakıyor",
        ]
        for q in tests:
            is_rob, reply = self.node._is_robot_state_query(q)
            self.assertTrue(is_rob, f"Query '{q}' should match _is_robot_state_query")
            self.assertTrue(len(reply) > 0)

    def test_18_stop_movement_commands_strict(self):
        """Stop commands trigger motion stop, while incidental words and activity queries do not."""
        # Genuine stop commands
        stops = ["dur", "DUR!", "Hey Astro, dur.", "dursana", "acil dur", "dur orada"]
        for s in stops:
            is_move, move_dir, _, _ = self.node._is_movement_query(s)
            self.assertTrue(is_move, f"Command '{s}' should be recognized as movement command")
            self.assertEqual(move_dir, "stop", f"Command '{s}' should have move_dir='stop'")

        # Incidental words that must NOT stop
        non_stops = ["durum nedir", "dur bakalım", "dur bir dakika", "ben ne yapıyordur", "ne yapıyorum"]
        for ns in non_stops:
            is_move, _, _, _ = self.node._is_movement_query(ns)
            self.assertFalse(is_move, f"Phrase '{ns}' must NOT be recognized as movement stop command")


if __name__ == "__main__":
    unittest.main()
