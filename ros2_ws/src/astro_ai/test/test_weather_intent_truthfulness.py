#!/usr/bin/env python3
"""Hava durumu yolu ne uydurmalı ne de her cümleyi kaçırmalı.

Canlı testte (2026-09-15) bozuk bir transkript — "Bize yazmıştım şimdi senlerine
hava zanaç ayıştırmıyorsun ki." — içinde düz "hava" geçtiği için hava durumu
kesicisine düştü, LLM tamamen atlandı (llm=none, 0 ms) ve robot ağ çağrısı
başarısız olduğu hâlde "Ahlat'ta hava şu an 20 derece ve açık." diye somut bir
sayı söyledi. İki koruma da burada sabitleniyor.
"""

import os
import sys
import unittest
from unittest.mock import patch

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

from astro_ai.astro_realtime_node import AstroRealtimeNode


class TestWeatherIntentTruthfulness(unittest.TestCase):

    def setUp(self):
        try:
            import rclpy
            if not rclpy.ok():
                rclpy.init(args=None)
        except Exception:
            pass
        self.node = AstroRealtimeNode(connect_realtime=False)

    def tearDown(self):
        try:
            self.node.destroy_node()
        except Exception:
            pass

    def test_01_gercek_hava_sorusu_yakalaniyor(self):
        for text in (
            "Ahlat'ta hava nasıl?",
            "bugün hava durumu ne olacak",
            "hava kaç derece",
            "dışarıda yağmur var mı",
        ):
            is_w, _city = self.node._is_weather_query(text)
            self.assertTrue(is_w, f"gerçek hava sorusu kaçtı: {text!r}")

    def test_02_bozuk_transkript_hava_yolunu_kacirmiyor(self):
        """İçinde 'hava' geçen ama hava sorusu olmayan cümleler LLM'e gitmeli."""
        for text in (
            "Bize yazmıştım şimdi senlerine hava zanaç ayıştırmıyorsun ki.",
            "havaalanına nasıl giderim",
            "bu odanın havası çok ağır",
            "havalimanında buluşalım",
        ):
            is_w, _city = self.node._is_weather_query(text)
            self.assertFalse(is_w, f"hava kesicisi yanlış tetiklendi: {text!r}")

    def test_03_ag_hatasinda_sayi_uydurulmuyor(self):
        """wttr.in erişilemezse somut sıcaklık/durum uydurulmamalı."""
        with patch("astro_ai.astro_realtime_node.urllib.request.urlopen",
                   side_effect=OSError("network unreachable")):
            reply = self.node._execute_fallback_weather("Ahlat")

        self.assertNotIn("20", reply)
        self.assertNotIn("derece", reply.lower())
        self.assertNotIn("açık", reply.lower())
        low = reply.lower()
        self.assertTrue(
            any(k in low for k in ("alamıyorum", "ulaşamıyorum", "bilmiyorum", "erişemiyorum")),
            f"dürüst bilinmiyor cevabı bekleniyordu, gelen: {reply!r}",
        )


if __name__ == "__main__":
    unittest.main()
