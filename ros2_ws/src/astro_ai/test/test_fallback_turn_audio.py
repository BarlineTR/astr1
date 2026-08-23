#!/usr/bin/env python3
"""ASTRO V1 — Rate limit / kesinti sonrası fallback turunun GERÇEKTEN ses üretmesi.

Canlı logda yakalanan hata:
    Fallback turn notice: 'AstroRealtimeNode' object has no attribute 'audio_output_manager'
Fallback turu çalışıyor, kullanıcı deşifre ediliyor, sonra telemetri satırında
AttributeError ile patlıyor ve hata except içinde yutuluyordu. Sonuç: rate
limit'te robot tamamen sessiz.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

PCM24K = b"\x11\x22" * 4800  # ~0.2 s @24kHz


def _speechy_chunks():
    """STT öncesi yerel VAD kapısını geçecek kadar 'konuşma benzeri' 16 kHz ses."""
    rng = np.random.default_rng(7)
    sig = (rng.normal(0, 2500, 16000 * 2)).astype(np.int16)  # 2 s, RMS ~2500
    raw = sig.tobytes()
    return [raw[i:i + 640] for i in range(0, len(raw), 640)]


class TestNodeHasNoAudioOutputManager(unittest.TestCase):
    """Realtime düğümünün AudioOutputManager'ı YOKTUR ve olmamalıdır.

    Sesin tek sahibi audio_stream_node'dur (Spec #1 §5.2). Düğüm ona
    /audio/realtime_output_pcm üzerinden yayın yapar.
    """

    def test_playback_source_resolution_never_raises(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        node = AstroRealtimeNode()
        self.assertFalse(
            hasattr(node, "audio_output_manager"),
            "Realtime düğümü ses donanımına sahip olmamalı",
        )
        # Çözücü var olmalı ve patlamamalı.
        self.assertIsInstance(node._playback_source_name(), str)
        self.assertTrue(node._playback_source_name())

    def test_source_code_has_no_bare_audio_output_manager_access(self):
        """`getattr(self.audio_output_manager, ..., default)` varsayılanı KURTARMAZ:

        varsayılan yalnızca nesnenin EKSİK ATTRIBUTE'unu karşılar; nesnenin
        kendisi yoksa erişim daha getattr çalışmadan AttributeError atar.

        Metin araması değil AST kullanılıyor: bu dosyadaki açıklamalar ve
        docstring'ler ismi bilerek anıyor, onlar eşleşmemeli.
        """
        import ast as _ast

        import astro_ai.astro_realtime_node as mod
        with open(mod.__file__, "r", encoding="utf-8") as fh:
            tree = _ast.parse(fh.read())

        # Bu düğümde HİÇ var olmayan, ama koda sızmış ortak nesneler.
        never_exist = ("audio_output_manager", "realtime_engine")
        offenders = [
            (node.attr, node.lineno)
            for node in _ast.walk(tree)
            if isinstance(node, _ast.Attribute)
            and node.attr in never_exist
            and isinstance(node.value, _ast.Name)
            and node.value.id == "self"
        ]
        self.assertEqual(
            offenders, [],
            f"Var olmayan nesnelere gerçek erişim kaldı: {offenders}",
        )


class TestFallbackTurnProducesAudio(unittest.TestCase):
    def setUp(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        self.node = AstroRealtimeNode()
        self.node.pub_output_pcm = MagicMock()
        self.node.edge_tts_enabled = True
        self.node._ambient_rms = 100.0
        self.node._is_processing_fallback = False

        self.warns = []
        real_logger = self.node.get_logger()
        fake = MagicMock()
        fake.info = lambda m: None
        fake.debug = lambda m: None
        fake.error = lambda m: self.warns.append(("error", m))
        fake.warn = lambda m: self.warns.append(("warn", m))
        self.node.get_logger = lambda: fake

    def _run_turn(self):
        with patch.object(self.node, "_transcribe_wav", return_value="Nasılsın"), \
             patch.object(self.node, "_synthesize_edge_tts_pcm24k", return_value=PCM24K), \
             patch.object(self.node, "_stream_fallback_llm", create=True, return_value="İyiyim, teşekkürler."):
            self.node._process_fallback_turn(_speechy_chunks())

    def test_no_attribute_error_swallowed(self):
        self._run_turn()
        notices = [m for lvl, m in self.warns if "Fallback turn notice" in str(m)]
        self.assertEqual(
            notices, [],
            "Fallback turu sessizce yutulan bir hata ile çöktü:\n" + "\n".join(str(n) for n in notices),
        )

    def test_audio_is_published_to_output_topic(self):
        self._run_turn()
        self.assertGreater(
            self.node.pub_output_pcm.publish.call_count, 0,
            "Fallback turu hiç ses yayınlamadı — robot rate limit'te sessiz kalıyor",
        )


class TestRateLimitTriggersFallbackMode(unittest.TestCase):
    """Rate limit, quota gibi kalıcı bir engeldir: fallback moduna geçilmeli."""

    def setUp(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        self.node = AstroRealtimeNode()
        self.node._fallback_mode = False

    def test_rate_limit_error_event_enables_fallback_mode(self):
        import asyncio
        event = {
            "type": "error",
            "error": {
                "type": "requests",
                "code": "rate_limit_exceeded",
                "message": (
                    "Rate limit reached for gpt-realtime-2.1-mini on requests per day "
                    "(RPD): Limit 1000, Used 1000, Requested 1."
                ),
            },
        }
        asyncio.run(self.node._handle_realtime_event(MagicMock(), event))
        self.assertTrue(
            self.node._fallback_mode,
            "rate_limit_exceeded fallback moduna geçirmedi — düğüm boşuna yeniden bağlanmayı deniyor",
        )

    def test_unrelated_error_does_not_enable_fallback_mode(self):
        import asyncio
        event = {
            "type": "error",
            "error": {"type": "invalid_request_error", "code": "bad_param", "message": "nope"},
        }
        asyncio.run(self.node._handle_realtime_event(MagicMock(), event))
        self.assertFalse(self.node._fallback_mode)


if __name__ == "__main__":
    unittest.main()
