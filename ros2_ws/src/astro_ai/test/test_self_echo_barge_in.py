#!/usr/bin/env python3
"""ASTRO V1 — Robot kendi sesini "kullanıcı araya girdi" sanmamalı.

Canlı logdan ölçülen gerçek değerler (laptop: hoparlör ve mikrofon aynı
sysdefault cihazı, donanımsal yankı iptali YOK):

    Akustik Yankı Koruması ... RMS 1374  Peak 3326  barge_in_after_ms=968
    Akustik Yankı Koruması ... RMS 1669  Peak 4019  barge_in_after_ms=468
    Akustik Yankı Koruması ... RMS 1717  Peak 5348  barge_in_after_ms=510
    Akustik Yankı Koruması ... RMS 1975  Peak 3955  barge_in_after_ms=565

Hepsi 350 ms'lik koruma penceresinin DIŞINDA ve gevşek eşiği (1200/2800)
aşıyor -> her cümle yarım kalıyordu.

Kök neden: her iki düğüm de çalma sırası için ayrı ve çok daha katı eşikler
TANIMLIYOR (BARGE_IN_PLAYBACK_MIN_RMS=4500, ..._PEAK=14000) ama bunları
hiçbir yerde KULLANMIYORDU.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

# Canlı logdan alınan gerçek kendi-ses seviyeleri
SELF_ECHO_SAMPLES = [
    (1374.0, 3326),
    (1669.0, 4019),
    (1717.0, 5348),
    (1975.0, 3955),
    (1303.0, 3549),
]
# Gerçek kullanıcı konuşması (aynı logdan, STT Telemetry satırları).
# DİKKAT: RMS'leri kendi sesinden DÜŞÜK. Ayıran tek ölçüt peak.
REAL_USER_SAMPLES = [
    (1466.2, 7446),
    (1048.2, 5782),
    (968.7, 8628),
]


class TestPlaybackThresholdsAreUsed(unittest.TestCase):
    """Tanımlanmış katı eşikler gerçekten uygulanmalı."""

    def test_realtime_node_uses_playback_thresholds(self):
        import ast as _ast
        import astro_ai.astro_realtime_node as mod
        with open(mod.__file__, "r", encoding="utf-8") as fh:
            tree = _ast.parse(fh.read())
        # Yalnızca OKUMA (Load) sayılır: atama (Store) "kullanılıyor" demek değil.
        used = {
            n.attr for n in _ast.walk(tree)
            if isinstance(n, _ast.Attribute)
            and n.attr.startswith("barge_in_playback_")
            and isinstance(n.ctx, _ast.Load)
        }
        self.assertIn("barge_in_playback_min_rms", used,
                      "Çalma sırası RMS eşiği tanımlı ama hiç OKUNMUYOR")
        self.assertIn("barge_in_playback_min_peak", used,
                      "Çalma sırası peak eşiği tanımlı ama hiç OKUNMUYOR")

    def test_audio_stream_node_uses_playback_thresholds(self):
        import ast as _ast
        import astro_audio.audio_stream_node as mod
        with open(mod.__file__, "r", encoding="utf-8") as fh:
            tree = _ast.parse(fh.read())
        used = {
            n.attr for n in _ast.walk(tree)
            if isinstance(n, _ast.Attribute)
            and n.attr.startswith("barge_in_playback_")
            and isinstance(n.ctx, _ast.Load)
        }
        self.assertIn("barge_in_playback_min_rms", used)
        self.assertIn("barge_in_playback_min_peak", used)


class TestSelfEchoDoesNotTriggerBargeIn(unittest.TestCase):
    def setUp(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        self.node = AstroRealtimeNode()
        self.node.get_logger = lambda: MagicMock()
        self.node._ambient_rms = 120.0

    def test_measured_self_echo_is_rejected(self):
        for rms, peak in SELF_ECHO_SAMPLES:
            self.assertFalse(
                self.node._is_barge_in_energy(rms, peak, during_playback=True),
                f"Kendi sesi barge-in saydı (RMS={rms}, Peak={peak}) — cümle yarıda kesilir",
            )

    def test_loud_user_speech_still_interrupts(self):
        """Koruma gerçek kullanıcıyı susturmamalı — ama pay dar.

        Ölçüm: kendi sesi peak <= 5348, kullanıcı peak 5782-8628. Eşik ikisinin
        arasına (6000) kondu; en KISIK kullanıcı ifadesi (5782) bu donanımda
        kaçırılır. Bu bilinçli bir takas: kesilmeyen konuşma, kaçırılan
        barge-in'e tercih edildi. Bkz. .env.example BARGE_IN_PLAYBACK_MIN_PEAK.
        """
        for rms, peak in REAL_USER_SAMPLES:
            if peak < 6000:
                continue  # bu donanımda ayrılamıyor
            self.assertTrue(
                self.node._is_barge_in_energy(rms, peak, during_playback=True),
                f"Gerçek kullanıcı sesi barge-in saymadı (RMS={rms}, Peak={peak})",
            )

    def test_quietest_user_sample_is_known_to_be_missed(self):
        """Kaydedilmiş sınır: 5782 peak'lik ifade bu donanımda kaçırılıyor."""
        self.assertFalse(self.node._is_barge_in_energy(1048.2, 5782, during_playback=True))

    def test_idle_listening_uses_lenient_threshold(self):
        """Çalma yokken normal konuşma eşiği geçerli olmalı."""
        self.assertTrue(self.node._is_barge_in_energy(1400.0, 3000, during_playback=False))

    def test_quiet_room_is_never_barge_in(self):
        for during in (True, False):
            self.assertFalse(self.node._is_barge_in_energy(180.0, 700, during_playback=during))

    def test_ambient_noise_raises_the_bar(self):
        """Gürültülü ortamda eşik zemin gürültüsüyle birlikte yükselmeli."""
        self.node._ambient_rms = 2000.0
        self.assertFalse(self.node._is_barge_in_energy(2500.0, 5000, during_playback=False))


class TestAudioStreamNodeSelfEchoGate(unittest.TestCase):
    def setUp(self):
        from astro_audio.audio_stream_node import AudioStreamNode
        self.node = AudioStreamNode.__new__(AudioStreamNode)
        self.node.barge_in_min_rms = 1200.0
        self.node.barge_in_playback_min_rms = 800.0
        self.node.barge_in_min_peak = 2800
        self.node.barge_in_playback_min_peak = 6000
        self.node.barge_in_noise_mult = 3.5
        self.node._ambient_rms = 120.0

    def test_self_echo_is_not_forwarded_during_playback(self):
        for rms, peak in SELF_ECHO_SAMPLES:
            self.assertFalse(
                self.node._is_barge_in_energy(rms, peak, during_playback=True),
                f"Kendi sesi OpenAI'a/beyne iletildi (RMS={rms}, Peak={peak})",
            )

    def test_loud_user_is_forwarded_during_playback(self):
        for rms, peak in REAL_USER_SAMPLES:
            if peak < 6000:
                continue
            self.assertTrue(
                self.node._is_barge_in_energy(rms, peak, during_playback=True)
            )


if __name__ == "__main__":
    unittest.main()
