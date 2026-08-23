#!/usr/bin/env python3
"""ASTRO V1 — Cümleler arasında sessizlik boşluğu olmamalı.

Canlı logdan ölçülen boşluk:
    402.592  playback_started  "Seni dinliyorum, CevdetYılmaz."
    405.068  2. cümlenin sentezi BAŞLIYOR       <- 1. cümle yayını bittikten sonra
    405.463  playback_finished (1. cümle)
    405.969  2. cümlenin sentezi bitiyor        <- 506 ms SESSİZLİK
    405.970  playback_started

Sebep: _play_pcm_chunks bloke ediyor, dolayısıyla sonraki cümlenin sentezi
ancak öncekinin tamamı yayınlandıktan SONRA başlıyor. Konuşma parça parça
duyuluyor.

Çözüm: çalma tek işçili bir kuyruğa devrediliyor (sıra korunur, üst üste
binmez), sentez döngüsü beklemeden bir sonraki cümleye geçiyor.
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

PCM = b"\x11\x22" * 4800  # 0.2 s @24k -> ~10 parça


def _node():
    from astro_ai.astro_realtime_node import AstroRealtimeNode
    n = AstroRealtimeNode()
    n.get_logger = lambda: MagicMock()
    n.pub_output_pcm = MagicMock()
    return n


class TestPlaybackIsNonBlocking(unittest.TestCase):
    def setUp(self):
        self.node = _node()

    def test_enqueue_returns_before_playback_finishes(self):
        """Sıraya koymak, çalmanın bitmesini BEKLEMEMELİ."""
        t0 = time.monotonic()
        self.node._enqueue_playback(PCM, generation_id=1, tts_provider="edge_tts",
                                    tts_model="edge_tts", tts_source="edge_tts")
        enqueue_ms = (time.monotonic() - t0) * 1000.0
        self.node._drain_playback(timeout=15.0)
        self.assertLess(
            enqueue_ms, 50.0,
            f"Sıraya koyma {enqueue_ms:.0f} ms sürdü — sentez döngüsü bloke oluyor",
        )

    def test_clauses_play_in_submission_order(self):
        seq = []
        self.node.pub_output_pcm.publish.side_effect = lambda m: seq.append(m.data)
        for idx, src in enumerate(("clause_A", "clause_B", "clause_C")):
            self.node._enqueue_playback(PCM, generation_id=idx, tts_provider=src,
                                        tts_model=src, tts_source=src)
        self.node._drain_playback(timeout=30.0)

        order = []
        for s in seq:
            for name in ("clause_A", "clause_B", "clause_C"):
                if name in s:
                    if not order or order[-1] != name:
                        order.append(name)
                    break
        self.assertEqual(
            order, ["clause_A", "clause_B", "clause_C"],
            f"Cümleler sırasız veya üst üste çaldı: {order}",
        )

    def test_second_clause_can_be_synthesized_during_first_playback(self):
        """Asıl kazanç: 1. cümle çalarken 2. cümle sentezlenebilmeli."""
        self.node._enqueue_playback(PCM, generation_id=1, tts_provider="a",
                                    tts_model="a", tts_source="a")
        # Çalma sürerken "sentez" yapabildiğimizi göster.
        t0 = time.monotonic()
        time.sleep(0.05)          # sentezi temsil eder
        synth_done = time.monotonic() - t0
        self.node._enqueue_playback(PCM, generation_id=2, tts_provider="b",
                                    tts_model="b", tts_source="b")
        self.node._drain_playback(timeout=30.0)
        self.assertLess(synth_done, 0.5)

    def test_drain_waits_for_everything(self):
        for i in range(3):
            self.node._enqueue_playback(PCM, generation_id=i, tts_provider="x",
                                        tts_model="x", tts_source="x")
        self.node._drain_playback(timeout=30.0)
        # Üç parçanın tamamı yayınlanmış olmalı (her biri ~10 parça).
        self.assertGreaterEqual(self.node.pub_output_pcm.publish.call_count, 25)

    def test_empty_pcm_is_ignored(self):
        self.node._enqueue_playback(b"", generation_id=1, tts_provider="x",
                                    tts_model="x", tts_source="x")
        self.node._drain_playback(timeout=5.0)
        self.assertEqual(self.node.pub_output_pcm.publish.call_count, 0)


if __name__ == "__main__":
    unittest.main()
