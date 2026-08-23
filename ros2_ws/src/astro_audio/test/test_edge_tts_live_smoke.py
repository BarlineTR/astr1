#!/usr/bin/env python3
"""ASTRO V1 — Edge-TTS canlı sentez smoke testi (opt-in).

Mock'lu testler "Edge-TTS bağlandı mı" sorusunu cevaplar; bu test
"Edge-TTS GERÇEKTEN konuşma üretiyor mu" sorusunu cevaplar. Ağ ve ffmpeg
gerektirir, o yüzden varsayılan olarak atlanır.

Çalıştırma:
    ASTRO_EDGE_TTS_LIVE=1 .venv/bin/python -m pytest \
        ros2_ws/src/astro_audio/test/test_edge_tts_live_smoke.py -v -s

Sesi duymak için:
    ASTRO_EDGE_TTS_LIVE=1 ASTRO_EDGE_TTS_PLAY=1 ... (aplay ile çalar)
"""

import os
import shutil
import subprocess
import sys
import time
import unittest

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))

LIVE = os.getenv("ASTRO_EDGE_TTS_LIVE", "").strip() == "1"
PLAY = os.getenv("ASTRO_EDGE_TTS_PLAY", "").strip() == "1"

SAMPLE_RATE = 24000  # _play_pcm_chunks bu oranı bekler


@unittest.skipUnless(LIVE, "ASTRO_EDGE_TTS_LIVE=1 gerekli (ağ + ffmpeg)")
class TestEdgeTtsLiveSynthesis(unittest.TestCase):
    def setUp(self):
        from astro_audio.edge_tts_engine import EdgeTTSEngine
        self.logs = []
        self.engine = EdgeTTSEngine(logger=lambda lvl, msg: self.logs.append(f"[{lvl}] {msg}"))

    def test_dependencies_present(self):
        self.assertTrue(self.engine.is_installed, "edge_tts paketi kurulu değil")
        self.assertIsNotNone(shutil.which("ffmpeg"), "ffmpeg yok — PCM dönüşümü yapılamaz")

    def test_produces_real_speech(self):
        """Üretilen PCM gerçekten konuşma olmalı: doğru süre, makul enerji, sessiz değil."""
        import numpy as np

        text = "Merhaba, ben Astro. Şu anda yedek ses motorumu kullanıyorum."
        t0 = time.perf_counter()
        pcm = self.engine.synthesize_sentence(
            text, generation_id=1, voice="tr-TR-AhmetNeural", rate="+8%"
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertTrue(pcm, f"Edge-TTS ses üretmedi. Loglar:\n" + "\n".join(self.logs))

        arr = np.frombuffer(pcm, dtype=np.int16)
        duration_s = len(arr) / float(SAMPLE_RATE)
        rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
        peak = int(np.max(np.abs(arr)))
        voiced_ratio = float(np.mean(np.abs(arr) > 200))

        print(
            f"\n  latency_ms={latency_ms:.0f} duration_s={duration_s:.2f} "
            f"rms={rms:.0f} peak={peak} voiced={voiced_ratio * 100:.1f}%"
        )

        # 60 karakterlik Türkçe cümle ~3-10 saniye sürer.
        self.assertGreater(duration_s, 2.0, "Ses fazla kısa — sentez yarıda kesilmiş olabilir")
        self.assertLess(duration_s, 15.0, "Ses fazla uzun — yanlış örnekleme oranı şüphesi")
        # Sessizlik veya DC değil, kırpılmış da değil.
        self.assertGreater(rms, 500, "Sinyal fazla sessiz — muhtemelen sessizlik üretildi")
        self.assertGreater(peak, 3000, "Tepe değeri fazla düşük")
        self.assertLess(peak, 32760, "Sinyal kırpılmış")
        self.assertGreater(voiced_ratio, 0.15, "Neredeyse tamamı sessizlik — konuşma yok")

        if PLAY and shutil.which("aplay"):
            subprocess.run(
                ["aplay", "-q", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-"],
                input=pcm, timeout=30, check=False,
            )

    def test_pcm_length_is_even(self):
        """int16 PCM tek sayıda byte olamaz — olursa aşağıdaki her tüketici kayar."""
        pcm = self.engine.synthesize_sentence("Test.", generation_id=2)
        self.assertTrue(pcm)
        self.assertEqual(len(pcm) % 2, 0)

    def test_empty_text_returns_none_without_network_call(self):
        self.assertIsNone(self.engine.synthesize_sentence("   ", generation_id=3))

    def test_female_persona_voice_also_works(self):
        pcm = self.engine.synthesize_sentence(
            "Merhaba.", generation_id=4, voice="tr-TR-EmelNeural", rate="+12%"
        )
        self.assertTrue(pcm, "Kadın ses (EmelNeural) sentez üretmedi")


@unittest.skipUnless(LIVE, "ASTRO_EDGE_TTS_LIVE=1 gerekli (ağ + ffmpeg)")
class TestRealtimeNodeEdgeTtsPath(unittest.TestCase):
    """Düğümün fallback zinciri uçtan uca gerçek ses üretmeli."""

    def setUp(self):
        sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
        sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
        os.environ["ASTRO_MOCK_AUDIO"] = "1"
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        self.node = AstroRealtimeNode()

    def test_synthesize_speech_pcm_uses_edge_and_returns_audio(self):
        import numpy as np

        pcm, engine, ms, ready = self.node._synthesize_speech_pcm(
            "Yedek ses motoru devrede."
        )
        print(f"\n  engine={engine} latency_ms={ms:.0f} bytes={len(pcm)}")
        self.assertEqual(engine, "edge_tts")
        self.assertTrue(ready)
        self.assertGreater(len(pcm), 0)

        arr = np.frombuffer(pcm, dtype=np.int16)
        self.assertGreater(float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))), 500)


if __name__ == "__main__":
    unittest.main()
