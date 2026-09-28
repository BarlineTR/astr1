#!/usr/bin/env python3
"""Uyandırma tamponu sonsuza kadar büyüyememeli.

2026-09-15 canlı testi: dahili mikrofon analog kazancı doyuma girince her kare
eşiğin üstünde kaldı, `_wake_last_voice_time` sürekli tazelendi ve 0,5 s'lik
sessizlik boşluğu hiç oluşmadı. `_process_wake_candidate` hiç çağrılmadı; tek bir
"cümle" 91.540 ms'ye ulaştı ve robot 10 dakika boyunca tamamen sessiz kaldı —
üstelik logda tek bir hata satırı bile yoktu.

Bu test, enerji hiç düşmese bile tamponun bir üst sınırda boşaltıldığını ve
durumun loglandığını sabitler.
"""

import base64
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

from astro_ai.astro_realtime_node import AstroRealtimeNode

FRAME_MS = 20.0  # 320 örnek @ 16 kHz = 640 bayt


def loud_frame() -> MagicMock:
    """Doymuş mikrofonu taklit eden, tam ölçeğe yakın 20 ms'lik kare."""
    arr = (np.ones(320, dtype=np.int16) * 20000)
    arr[1::2] = -20000  # DC değil, gerçek enerji
    msg = MagicMock()
    msg.data = base64.b64encode(arr.tobytes()).decode("ascii")
    return msg


class TestWakeBufferCap(unittest.TestCase):

    def setUp(self):
        try:
            import rclpy
            if not rclpy.ok():
                rclpy.init(args=None)
        except Exception:
            pass
        self.node = AstroRealtimeNode(connect_realtime=False)
        self.node._is_sleeping = True
        self.node._wake_audio_buffer = []
        self.node._wake_listening = False

    def tearDown(self):
        try:
            self.node.destroy_node()
        except Exception:
            pass

    def test_01_susmayan_ses_tamponu_ust_sinirda_bosaltiliyor(self):
        """Enerji hiç düşmese bile tampon bir üst sınırda STT'ye gönderilmeli."""
        max_s = float(os.getenv("WAKE_MAX_UTTERANCE_S", "12.0"))
        frames_needed = int((max_s * 1000.0) / FRAME_MS) + 20

        with patch.object(self.node, "_process_wake_candidate") as proc:
            for _ in range(frames_needed):
                self.node._on_input_pcm(loud_frame())

            # Boşaltma ayrı bir iş parçacığında STT'ye gidiyor; kısa süre bekle.
            deadline = time.monotonic() + 2.0
            while not proc.called and time.monotonic() < deadline:
                time.sleep(0.01)

            self.assertTrue(
                proc.called,
                "kesintisiz yüksek enerjide uyandırma adayı hiç işlenmedi "
                "(tampon sınırsız büyüyor)",
            )
            sent = proc.call_args[0][0]
            self.assertGreater(len(sent), 10)

        # Boşaltmadan sonra tampon sınırın altında kalmalı.
        self.assertLess(
            len(self.node._wake_audio_buffer) * FRAME_MS / 1000.0, max_s,
            "tampon boşaltılmadı",
        )

    def test_02_normal_akista_ust_sinir_devreye_girmiyor(self):
        """Kısa konuşmalarda üst sınır yolu tetiklenmemeli."""
        with patch.object(self.node, "_process_wake_candidate") as proc:
            for _ in range(25):  # 0,5 s
                self.node._on_input_pcm(loud_frame())
            self.assertFalse(proc.called)


if __name__ == "__main__":
    unittest.main()
