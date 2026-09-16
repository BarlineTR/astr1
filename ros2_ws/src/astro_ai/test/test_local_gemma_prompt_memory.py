#!/usr/bin/env python3
"""Yerel Gemma prompt'u hafızayı taşımalı.

Canlı masaüstü testinde (2026-09-15) 14 turun tamamında prompt_len ~1050'de sabit
kaldı: yerel yol `gemma_prompt`'u yalnızca güncel cümleden kuruyordu. Sonuç olarak
"Hangi tür bir hikaye istersin?" -> "Roman olsun." -> "Merhaba. Ne hakkında konuşmak
istersin?" gibi bağlam kayıpları ve "en son ne söylemiştim?" sorusuna cevapsızlık
oluştu. Bulut (Groq/OpenAI) yolu `messages` listesiyle geçmişi zaten taşıyor;
bu testler yerel yolun da taşıdığını sabitler.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

from astro_ai.local_gemma_client import LocalGemmaClient
from astro_ai.astro_realtime_node import AstroRealtimeNode


class TestLocalGemmaPromptMemory(unittest.TestCase):

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

        self.captured = []
        mock_client = MagicMock(spec=LocalGemmaClient)
        mock_client.is_available.return_value = True
        mock_client.model_name = "gemma4:e2b"

        def fake_stream(prompt, **kwargs):
            self.captured.append(prompt)
            yield "Tamam."

        mock_client.stream.side_effect = fake_stream
        self.node.local_gemma_client = mock_client

    def tearDown(self):
        try:
            self.node.destroy_node()
        except Exception:
            pass

    def _run_turn(self, text: str):
        mock_pcm = b"\x00\x00" * 2400
        mock_route = MagicMock(pcm=mock_pcm, duration_ms=100.0, infer_ms=10.0, queue_wait_ms=0.0,
                               actual_provider="edge_tts", source_name="edge_tts_cloud",
                               model_name="tr_tr_ahmet")
        with patch.object(self.node.tts_router, "synthesize", return_value=mock_route), \
             patch.object(self.node, "_play_pcm_chunks"):
            self.node._process_fallback_turn(direct_text=text)

    def test_01_onceki_diyalog_prompta_giriyor(self):
        """Yerel prompt, epizodik tampondaki önceki kullanıcı/robot repliklerini içermeli."""
        self.node.memory.episodic.add_message("user", "Bana hızlı bir hikaye anlat.")
        self.node.memory.episodic.add_message("assistant", "Hangi tür bir hikaye istersin? Fantastik mi?")

        self._run_turn("Roman olsun.")

        self.assertTrue(self.captured, "Yerel Gemma prompt'u yakalanamadı")
        prompt = self.captured[0]
        self.assertIn("Roman olsun.", prompt)
        self.assertIn("Bana hızlı bir hikaye anlat.", prompt)
        self.assertIn("Hangi tür bir hikaye istersin?", prompt)

    def test_02_kalici_profil_bilgisi_prompta_giriyor(self):
        """Yerel prompt, kalıcı profildeki doğrulanmış bilgileri içermeli."""
        self.node.memory.profile.add_verified_fact("Kullanıcının adı Yunus Emre.")

        self._run_turn("Ben kimim?")

        self.assertTrue(self.captured, "Yerel Gemma prompt'u yakalanamadı")
        self.assertIn("Yunus Emre", self.captured[0])

    def test_03_gecmis_sinirli_tutuluyor(self):
        """Prompt sınırsız büyümemeli: yalnızca son replikler taşınmalı."""
        for i in range(20):
            self.node.memory.episodic.add_message("user", f"eski-kullanici-mesaji-{i}")
            self.node.memory.episodic.add_message("assistant", f"eski-robot-cevabi-{i}")

        self._run_turn("Son soru.")

        prompt = self.captured[0]
        self.assertIn("eski-robot-cevabi-19", prompt)
        self.assertNotIn("eski-kullanici-mesaji-0", prompt)


if __name__ == "__main__":
    unittest.main()
