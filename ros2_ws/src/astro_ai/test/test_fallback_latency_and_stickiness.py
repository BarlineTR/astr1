#!/usr/bin/env python3
"""ASTRO V1 — Fallback gecikmesi ve fallback modunda kalıcılık.

Ölçüm (gerçek Edge-TTS, bu makine):
    26 karakter  ->  793-1102 ms sentez
    44 karakter  ->  501- 707 ms sentez
    152 karakter -> 1846-2868 ms sentez     <-- uzun cevap pahalı

Gecikmenin ~%90'ı Microsoft'un ilk baytı göndermesi (TTFA ~600 ms) ve bu
düşürülemiyor; ön-ısıtma ölçüldü, FAYDASI YOK. Kalan tek kaldıraç: uzun
cevabı beklemeyip ilk cümleyi hemen söylemek.
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

PCM = b"\x11\x22" * 480

LONG_REPLY = (
    "Ulan hava bugün çok güzel, dışarı çıkıp biraz yürüsen iyi olur. "
    "Güneş var ama rüzgar da serin, ceketini almayı unutma. "
    "Akşama doğru yağmur ihtimali var."
)


def _node():
    from astro_ai.astro_realtime_node import AstroRealtimeNode
    n = AstroRealtimeNode()
    n.pub_output_pcm = MagicMock()
    n.edge_tts_enabled = True
    return n


class TestSingleShotSynthesisIsIntentional(unittest.TestCase):
    """Cevap cümlelere BÖLÜNMEZ ve bu ölçümle verilmiş bir karar.

    Bölmeyi denedik ve geri aldık. Gerçek Edge-TTS ile 6'şar örnek:
        44 karakter  -> medyan 631 ms (521-687)
        152 karakter -> medyan 764 ms (639-820)
    Uzunluk neredeyse etkisiz; süre Microsoft'a sabit gidiş-dönüş. Bölmenin
    kazancı ~130 ms iken her cümle AYRI bir gidiş-dönüş ödüyor.
    """

    def setUp(self):
        self.node = _node()

    def test_long_reply_is_one_synthesis_call(self):
        calls = []
        with patch.object(self.node, "_synthesize_speech_pcm",
                          side_effect=lambda t: (calls.append(t), (PCM, "edge_tts", 600.0, True))[1]):
            self.node._speak_fallback_text(LONG_REPLY)
        self.assertEqual(
            len(calls), 1,
            "Cevap bölündü — her parça ayrı bir ağ gidiş-dönüşü ödüyor, kazanç yok",
        )
        self.assertEqual(calls[0], LONG_REPLY)

    def test_short_reply_is_one_synthesis_call(self):
        calls = []
        with patch.object(self.node, "_synthesize_speech_pcm",
                          side_effect=lambda t: (calls.append(t), (PCM, "edge_tts", 600.0, True))[1]):
            self.node._speak_fallback_text("İyiyim, sen nasılsın?")
        self.assertEqual(len(calls), 1)

    def test_empty_text_synthesizes_nothing(self):
        with patch.object(self.node, "_synthesize_speech_pcm") as synth:
            self.node._speak_fallback_text("   ")
        synth.assert_not_called()

    def test_first_audio_latency_is_logged(self):
        """Gecikme ölçülemezse iyileştirilemez."""
        logs = []
        fake = MagicMock()
        for lvl in ("info", "warn", "error", "debug"):
            setattr(fake, lvl, (lambda m, _l=lvl: logs.append(str(m))))
        self.node.get_logger = lambda: fake
        with patch.object(self.node, "_synthesize_speech_pcm",
                          return_value=(PCM, "edge_tts", 600.0, True)):
            self.node._speak_fallback_text(LONG_REPLY)
        self.assertIn("TTS FALLBACK FIRST AUDIO", "\n".join(logs))

    def test_playback_is_published(self):
        with patch.object(self.node, "_synthesize_speech_pcm",
                          return_value=(PCM, "edge_tts", 600.0, True)):
            self.node._speak_fallback_text(LONG_REPLY)
        self.assertGreater(self.node.pub_output_pcm.publish.call_count, 0)


class TestFallbackModeIsSticky(unittest.TestCase):
    """Fallback'e geçtikten sonra Realtime'a sorgu yağdırılmamalı."""

    def setUp(self):
        self.node = _node()

    def test_reconnect_is_blocked_while_cooldown_active(self):
        import time as _t
        self.node._fallback_mode = True
        self.node._fallback_until = _t.monotonic() + 60.0
        self.assertFalse(
            self.node._should_attempt_realtime_connect(),
            "Bekleme süresi dolmadan Realtime'a yeniden bağlanma denendi",
        )

    def test_enter_fallback_always_sets_a_deadline(self):
        """Süresiz fallback olmaz: aksi hâlde bekçi hiçbir şeyi engellemez."""
        import time as _t
        self.node._fallback_mode = False
        self.node._fallback_until = 0.0
        self.node._enter_fallback_mode("test", None)
        self.assertGreater(self.node._fallback_until, _t.monotonic() + 1.0)
        self.assertFalse(self.node._should_attempt_realtime_connect())

    def test_reconnect_allowed_when_not_in_fallback(self):
        self.node._fallback_mode = False
        self.assertTrue(self.node._should_attempt_realtime_connect())

    def test_retry_after_seconds_is_parsed_from_rate_limit_message(self):
        msg = (
            "Rate limit reached for gpt-realtime-2.1-mini (for limit gpt-4o-mini-realtime) "
            "in organization org-X on requests per day (RPD): Limit 1000, Used 1000, "
            "Requested 1. Please try again in 1m26.4s."
        )
        self.assertAlmostEqual(self.node._parse_retry_after_s(msg), 86.4, places=1)

    def test_retry_after_seconds_only(self):
        self.assertAlmostEqual(self.node._parse_retry_after_s("Please try again in 20s."), 20.0, places=1)

    def test_retry_after_missing_returns_none(self):
        self.assertIsNone(self.node._parse_retry_after_s("Some other error"))

    def test_rate_limit_sets_cooldown_deadline(self):
        import asyncio
        event = {
            "type": "error",
            "error": {
                "type": "requests", "code": "rate_limit_exceeded",
                "message": "Rate limit reached ... Please try again in 1m26.4s.",
            },
        }
        asyncio.run(self.node._handle_realtime_event(MagicMock(), event))
        self.assertTrue(self.node._fallback_mode)
        # Bekleme süresi yaklaşık olarak mesajdan alınmalı (biraz pay ile).
        import time as _t
        remaining = self.node._fallback_until - _t.monotonic()
        self.assertGreater(remaining, 60.0, "Rate limit bekleme süresi mesajdan alınmadı")

    def test_fallback_expires_and_allows_retry(self):
        import time as _t
        self.node._fallback_mode = True
        self.node._fallback_until = _t.monotonic() - 1.0  # süresi doldu
        self.assertTrue(
            self.node._should_attempt_realtime_connect(),
            "Bekleme süresi dolduğu hâlde Realtime'a dönülmedi",
        )


if __name__ == "__main__":
    unittest.main()
