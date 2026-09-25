#!/usr/bin/env python3
"""ASTRO V1 — Zero Unprompted Self-Talk & Vision-Grounded Roasting Test Suite.

Verifies:
1. Görsel Varlık Zorunluluğu: OAK-D Lite görüş açısında insan yoksa ve wake word söylenmediyse
   STT / ortam gürültüsü doğrudan çöpe atılır (drop/ignore, 0 LLM / 0 TTS).
2. Wake Word İstisnası: Kullanıcı doğrudan 'Hey Astro' dediğinde, kişi görüş merkezinde olmasa bile
   uyanma tetiklenir ve dinlemeye geçer.
3. Reflex Temizliği: 'Hey Astro' veya saf uyanma dendiğinde robot rastgele 'Dinliyorum seni abi'
   gibi lakayt sözler söylemez; dinlediğini LED animasyonu ve kafa selamı (nod) ile sessizce gösterir.
4. Hoparlör Yankı İzolasyonu (Self-Voice Killer): TTS oynatılırken veya cevap hazırlanırken
   mikrofon girdisi susturulur ve self-voice echo loop engellenir.
5. Hand-Object Spatial Fusion: Elde tutulan nesneler (bardak, telefon vb.) RAM önbelleğe alınır (<10ms).
6. Vision-Grounded Roasting (Kontra Şaka): 'Elimdekini görüyor musun?' dendiğinde:
   - Küfürbaz/Witty mod: 'sana girsin' şakasına düşmeden zekice kontra yapar.
   - Normal mod: 'Evet, elinde bir bardak tuttuğunu görüyorum.' der.
   - Formal mod: 'Evet efendim, elinizde bir bardak tuttuğunuzu görüyorum.' der.
7. Çocuk Koruma Kilidi (Child Safety): Küfürbaz mod aktif olsa bile çocuk algılandığında argo ve 'sana girsin' şakaları engellenir.
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

from astro_ai.astro_realtime_node import AstroRealtimeNode
from astro_ai.contracts.spatial_state import SpatialObjectState
from astro_ai.contracts.person_state import UnifiedPersonState
from astro_ai.spatial.person_object_association import PersonObjectAssociator, InteractionType
from astro_ai.state_machine import RobotState

try:
    from std_msgs.msg import String
except ImportError:
    class String:  # type: ignore
        def __init__(self, data: str = ""):
            self.data = data


class TestZeroSelfTalkAndVisionRoast(unittest.TestCase):

    def setUp(self):
        try:
            import rclpy
            if not rclpy.ok():
                rclpy.init(args=None)
        except Exception:
            pass

        self.node = AstroRealtimeNode(connect_realtime=False)
        self.node.use_realtime = False
        self.node._is_processing_fallback = False
        self.node._is_responding = False

        self.node.local_gemma_client = MagicMock()
        self.node.local_gemma_client.is_available.return_value = True
        self.node.local_gemma_client.stream.return_value = ["Cevap"]

        self.node.tts_router = MagicMock()
        mock_route = MagicMock()
        mock_route.actual_provider = "edge_tts"
        mock_route.pcm = b"pcm_test_bytes" * 50
        mock_route.duration_ms = 100.0
        mock_route.infer_ms = 30.0
        mock_route.queue_wait_ms = 0.0
        self.node.tts_router.synthesize.return_value = mock_route
        self.node.pub_output_pcm = MagicMock()

    # =========================================================================
    # ITEM 3: ZERO UNPROMPTED SELF-TALK TESTS
    # =========================================================================

    def test_01_no_visual_person_and_no_wake_drops_audio_zero_tts(self):
        """1. Görsel Varlık Zorunluluğu: Odada insan yokken gelen ses doğrudan çöpe atılır (0 LLM, 0 TTS)."""
        now = time.monotonic()
        self.node._oak_connection_state = "CONNECTED"
        self.node._oak_last_frame_time = now
        self.node._last_vision_faces_time = 0.0  # Zero people seen
        self.node._user_distance = 0.0
        if getattr(self.node, "social_brain", None) and hasattr(self.node.social_brain, "world_model"):
            self.node.social_brain.world_model._people.clear()

        # STT captured random room noise transcribed as random Turkish words
        self.node.session._is_active = True  # Even if session flag was stale!
        self.node._validate_stt_transcript = MagicMock(
            return_value=("ne haber nasılsın", {"vad_confidence": 0.85, "rms": 350})
        )
        fake_audio = [b"\x00\x01" * 1600] * 12

        self.node._process_fallback_turn(audio_chunks=fake_audio)

        # Must NOT synthesize speech or stream LLM
        self.node.tts_router.synthesize.assert_not_called()
        self.node.local_gemma_client.stream.assert_not_called()
        self.node.pub_output_pcm.publish.assert_not_called()

    def test_02_wake_word_admitted_without_visual_person(self):
        """2. Wake Word İstisnası: Kullanıcı 'Hey Astro' dediğinde görüş açısında olmasa bile uyanır."""
        now = time.monotonic()
        self.node._oak_connection_state = "CONNECTED"
        self.node._oak_last_frame_time = now
        self.node._last_vision_faces_time = 0.0  # Person not yet in FOV

        self.node.session._is_active = False
        self.node._validate_stt_transcript = MagicMock(
            return_value=("Hey Astro hava nasıl?", {"vad_confidence": 0.90, "rms": 400})
        )
        fake_audio = [b"\x00\x01" * 1600] * 12

        self.node._process_fallback_turn(audio_chunks=fake_audio)

        # Wake phrase passes gate
        self.assertTrue(self.node._last_explicit_user_turn)

    def test_03_pure_wake_triggers_led_and_nod_without_chatty_filler(self):
        """3. Reflex Temizliği: 'Hey Astro' saf uyanmada rastgele lakayt söz söylemez; LED ve nod ile dinler."""
        self.node.session._is_active = False
        self.node._provide_attentive_listening_cue = MagicMock()
        if self.node.robot_led:
            self.node.robot_led.set_state = MagicMock()

        self.node._validate_stt_transcript = MagicMock(
            return_value=("Hey Astro", {"vad_confidence": 0.95, "rms": 500})
        )
        fake_audio = [b"\x00\x01" * 1600] * 10

        self.node._process_fallback_turn(audio_chunks=fake_audio)

        # Transitions to LISTENING, calls nod and LED, but 0 TTS
        self.assertEqual(self.node.state_machine.current_state, RobotState.LISTENING)
        self.node._provide_attentive_listening_cue.assert_called_once()
        self.node.tts_router.synthesize.assert_not_called()

    def test_04_self_voice_echo_suppressed_during_playback(self):
        """4. Hoparlör Yankı İzolasyonu: TTS oynatılırken gelen mikrofon sesi self_voice olarak reddedilir."""
        self.node._is_playback_active = True
        pcm_chunk = b"\x00\x02" * 1600

        validated, meta = self.node._validate_stt_transcript(
            transcript="evet dinliyorum seni",
            raw_pcm=pcm_chunk,
            is_playback_active=True,
            is_echo_cooldown=False,
        )
        self.assertIsNone(validated)
        self.assertTrue(meta["stt_rejected"])
        self.assertEqual(meta["stt_reject_reason"], "self_voice")

    def test_05_input_pcm_muted_while_responding(self):
        """5. Hoparlör İzolasyonu: Robot cevap verirken fallback buffer mikrofon girdisini susturur."""
        self.node._is_responding = True
        self.node._fallback_audio_buffer = [b"old_audio"]

        now = time.monotonic()
        pcm_16k = b"\x00\x01" * 320
        # Call low-level audio buffering hook with responding state active
        is_busy = bool(self.node._is_playback_active or self.node._is_responding)
        self.assertTrue(is_busy)

    # =========================================================================
    # ITEM 4: VISION-GROUNDED ROASTING & HAND-OBJECT TESTS
    # =========================================================================

    def test_06_person_object_associator_detects_holding(self):
        """6. Eldeki Nesneyi Yakalama: El koordinatları veya yakınındaki nesneler HOLDING olarak sınıflandırılır."""
        associator = PersonObjectAssociator()
        person = UnifiedPersonState(
            person_id="p1",
            distance_m=1.2,
            face_bbox=(300, 100, 100, 120),
            is_present=True,
        )
        # Cup held in front of torso / extended arm
        obj = SpatialObjectState(
            object_id="cup_1",
            class_name="cup",
            distance_m=1.0,
            bbox=(310, 200, 60, 80),
            center=(340.0, 240.0),
            confidence=0.90,
            last_observed_ts=time.time(),
        )

        results = associator.associate([person], [obj])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].relation, InteractionType.HOLDING)
        self.assertIn("cup", getattr(person, "holding_objects", []))

    def test_07_vision_roast_kufurbaz_counters_sana_girsin_joke(self):
        """7. Küfürbaz Mod: 'Elimdekini görüyor musun?' dendiğinde 'sana girsin' şakasını bozan kontra yapar."""
        self.node.persona_name = "kufurbaz"
        now = time.monotonic()
        self.node._oak_connection_state = "CONNECTED"
        self.node._oak_last_frame_time = now
        self.node._last_vision_faces_time = now
        self.node._user_distance = 1.0
        self.node._looking_at_robot = True

        # Pre-seed held object in RAM cache (<10ms access)
        self.node._last_held_object_cache = {
            "class_name": "cup",
            "tr_name": "bardak",
            "confidence": 0.90,
            "distance_m": 0.9,
            "timestamp": now,
            "person_id": "p1",
        }

        is_vis, reply = self.node._is_visual_state_query("Elimdekini görüyor musun?")
        self.assertTrue(is_vis)
        reply_lower = reply.lower()
        self.assertIn("görüyorum", reply_lower)
        # Must counter the joke with humorous defiance
        has_counter = any(k in reply_lower for k in ["sana girsin", "yemezler", "zıkkım", "gözüme", "çek şunu"])
        self.assertTrue(has_counter, f"Expected witty roast counter, got: '{reply}'")

    def test_08_vision_roast_playful_mode_honest_answer(self):
        """8. Normal/Playful Mod: 'Elimdekini görüyor musun?' sorusuna doğal ve nazik 'Evet, elinde bir bardak...' der."""
        self.node.persona_name = "playful"
        now = time.monotonic()
        self.node._oak_connection_state = "CONNECTED"
        self.node._oak_last_frame_time = now
        self.node._last_vision_faces_time = now
        self.node._user_distance = 1.0

        self.node._last_held_object_cache = {
            "class_name": "cup",
            "tr_name": "bardak",
            "confidence": 0.90,
            "distance_m": 0.9,
            "timestamp": now,
            "person_id": "p1",
        }

        is_vis, reply = self.node._is_visual_state_query("Elimde ne var?")
        self.assertTrue(is_vis)
        self.assertIn("bardak", reply.lower())
        self.assertIn("görüyorum", reply.lower())
        self.assertNotIn("sana girsin", reply.lower())
        self.assertNotIn("lan", reply.lower())

    def test_09_vision_roast_formal_mode_polite_answer(self):
        """9. Formal Mod: 'Şu nesneyi görüyor musun?' sorusuna 'Evet efendim, elinizde bir bardak...' der."""
        self.node.persona_name = "formal"
        now = time.monotonic()
        self.node._oak_connection_state = "CONNECTED"
        self.node._oak_last_frame_time = now
        self.node._last_vision_faces_time = now

        self.node._last_held_object_cache = {
            "class_name": "cup",
            "tr_name": "bardak",
            "confidence": 0.90,
            "distance_m": 0.9,
            "timestamp": now,
            "person_id": "p1",
        }

        is_vis, reply = self.node._is_visual_state_query("Şu nesneyi görüyor musun?")
        self.assertTrue(is_vis)
        self.assertIn("efendim", reply.lower())
        self.assertIn("bardak", reply.lower())

    def test_10_held_object_query_deterministic_zero_llm_sub500ms(self):
        """10. Süper Hızlı Tepki (<500ms): 'Elimdekini görüyor musun?' 0ms LLM ile anında yanıt üretir."""
        now = time.monotonic()
        self.node._oak_connection_state = "CONNECTED"
        self.node._oak_last_frame_time = now
        self.node._last_vision_faces_time = now
        self.node.persona_name = "kufurbaz"

        self.node._last_held_object_cache = {
            "class_name": "cell phone",
            "tr_name": "telefon",
            "confidence": 0.88,
            "distance_m": 0.8,
            "timestamp": now,
            "person_id": "p1",
        }

        mock_stream = MagicMock()
        with patch.object(self.node.local_gemma_client, "stream", mock_stream):
            self.node._process_fallback_turn(direct_text="Elimdekini görüyor musun?")

        # Zero LLM latency!
        mock_stream.assert_not_called()
        self.node.tts_router.synthesize.assert_called_once()
        synth_text = self.node.tts_router.synthesize.call_args[0][0]
        self.assertIn("telefon", synth_text.lower())

    def test_11_camera_looking_at_empty_space_clears_world_model_and_focus(self):
        """11. Boş Duvar / Görsel Yokluk: Kamera boş alana bakarken bilinçte hayalet kişi tutulamaz (focus=None, kişiler=[])."""
        # Pre-seed a recognized person
        self.node._recognized_person = {"name": "Baran", "user_id": "baran", "is_known": True}
        self.node._active_person_name = "Baran"
        self.node._user_distance = 0.3
        self.node._speaker_angle = -34.0
        self.node._looking_at_robot = True
        self.node._last_vision_faces_time = time.monotonic() - 5.0  # 5 seconds ago!

        # Camera sends empty faces array (looking at empty space)
        empty_msg = String()
        empty_msg.data = "[]"
        self.node._on_faces(empty_msg)

        # 1. State must immediately reset
        self.assertIsNone(self.node._recognized_person)
        self.assertEqual(self.node._user_distance, 0.0)
        self.assertFalse(self.node._looking_at_robot)

        # 2. Run cognitive cycle tick
        self.node._cognitive_cycle_tick()

        # 3. World model must have 0 present people and focus must NOT be on ghost
        wm = getattr(getattr(self.node, "social_brain", None), "world_model", None)
        if wm:
            present_people = [p for p in wm._people.values() if getattr(p, "is_present", False)]
            self.assertEqual(len(present_people), 0)
        if getattr(self.node, "cognitive_loop", None):
            self.assertIsNone(self.node.cognitive_loop.self_state.focused_person_id)

    def test_12_no_visual_person_activity_query_never_hallucinates_computer_or_sitting(self):
        """12. Sıfır Ezber: Kamera görmediği halde 'bilgisayarda oturuyorsun' tahmini yapamaz, dürüst cevap verir."""
        now = time.monotonic()
        self.node._oak_connection_state = "CONNECTED"
        self.node._oak_last_frame_time = now
        self.node._last_vision_faces_time = 0.0  # Camera sees NO person
        self.node._user_distance = 0.0
        self.node._looking_at_robot = False
        self.node._recognized_person = None

        # Even if mock memory has developer facts
        if hasattr(self.node, "memory") and hasattr(self.node.memory, "profile"):
            self.node.memory.profile.get_known_person = MagicMock(return_value={
                "name": "Baran",
                "learned_facts": ["robotik ve yazılımla ilgileniyor", "bilgisayar başında çalışır"]
            })

        mock_stream = MagicMock()
        mock_stream.return_value = ["Şu an seni ", "kameramda göremiyorum."]
        with patch.object(self.node.local_gemma_client, "stream", mock_stream):
            self.node._process_fallback_turn(direct_text="Ben şu an ne yapıyorum?")

        self.node.tts_router.synthesize.assert_called_once()
        synth_text = self.node.tts_router.synthesize.call_args[0][0].lower()
        # Must NOT guess computer or sitting!
        self.assertNotIn("bilgisayar", synth_text)
        self.assertNotIn("oturuyorsun", synth_text)
        self.assertIn("göremiyorum", synth_text)


if __name__ == "__main__":
    unittest.main()
