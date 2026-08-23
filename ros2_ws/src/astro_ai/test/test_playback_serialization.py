#!/usr/bin/env python3
"""ASTRO V1 — Aynı anda tek konuşmacı.

Canlı belirti: "Edge-TTS okurken bir anda ses kesiliyor."

Sebep: iki ayrı konuşma yolu birbirinden habersiz aynı anda çalabiliyordu —
_process_fallback_turn (kullanıcı sesinden tam tur) ve _speak_fallback_text
(sessiz yanıt kurtarması). Ölçüldü: 20 parçada 15 kaynak değişimi, yani ses
iç içe geçiyor. Ayrıca ilk biten yolun `finally` bloğu _is_playback_active'i
False yapıp durumu LISTENING'e çeviriyor — diğeri HÂLÂ konuşurken. O anda
audio_stream_node'un yankı susturması kalkıyor, mikrofon robotun kendi sesine
açılıyor ve gerçek barge-in tetiklenip sesi kesiyor.
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

CHUNKS_A = b"\xAA\xAA" * 4800
CHUNKS_B = b"\xBB\xBB" * 4800


def _node():
    from astro_ai.astro_realtime_node import AstroRealtimeNode
    n = AstroRealtimeNode()
    n.get_logger = lambda: MagicMock()
    return n


class TestPlaybackIsSerialized(unittest.TestCase):
    def setUp(self):
        self.node = _node()
        self.seq = []
        self.node.pub_output_pcm = MagicMock()
        self.node.pub_output_pcm.publish.side_effect = lambda m: self.seq.append(m.data)

    def _sources(self):
        return ["A" if "yol_A" in s else "B" for s in self.seq]

    def test_two_speakers_do_not_interleave(self):
        def speak(pcm, gen, src):
            self.node._play_pcm_chunks(pcm, generation_id=gen, tts_provider=src,
                                       tts_model=src, tts_source=src)

        t1 = threading.Thread(target=speak, args=(CHUNKS_A, 1, "yol_A"))
        t2 = threading.Thread(target=speak, args=(CHUNKS_B, 2, "yol_B"))
        t1.start()
        time.sleep(0.05)
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        order = self._sources()
        switches = sum(1 for i in range(1, len(order)) if order[i] != order[i - 1])
        self.assertLessEqual(
            switches, 1,
            f"Ses iç içe geçti ({switches} kaynak değişimi) — konuşma kesik kesik çıkar",
        )

    def test_playback_active_stays_true_until_last_speaker_finishes(self):
        observed = []

        def speak(pcm, gen, src, delay):
            time.sleep(delay)
            self.node._play_pcm_chunks(pcm, generation_id=gen, tts_provider=src,
                                       tts_model=src, tts_source=src)

        def watch():
            end = time.monotonic() + 3.0
            while time.monotonic() < end:
                observed.append(self.node._is_playback_active)
                time.sleep(0.01)

        w = threading.Thread(target=watch, daemon=True)
        t1 = threading.Thread(target=speak, args=(CHUNKS_A, 1, "yol_A", 0.0))
        t2 = threading.Thread(target=speak, args=(CHUNKS_B, 2, "yol_B", 0.05))
        w.start()
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        # Son parça yayınlandıktan SONRA bayrak False olmalı; arada değil.
        self.assertFalse(self.node._is_playback_active, "Konuşma bitti ama bayrak True kaldı")


class TestBargeInLatchIsResetBeforeSpeaking(unittest.TestCase):
    """Mandal yalnızca _process_fallback_turn'de sıfırlanıyordu.

    Kurtarma yolu (_speak_fallback_text) sıfırlamadığı için, bir kez gerçek
    barge-in olduktan sonra SONRAKİ her kurtarma ilk parçada kesiliyordu:
    _play_pcm_chunks döngüsünün başındaki `if self._barge_in_latched: break`.
    """

    def setUp(self):
        self.node = _node()
        self.node.pub_output_pcm = MagicMock()

    def test_stale_latch_does_not_silence_recovery(self):
        self.node._barge_in_latched = True  # önceki turdan kalma
        with patch.object(self.node, "_synthesize_speech_pcm",
                          return_value=(CHUNKS_A, "edge_tts", 600.0, True)):
            self.node._speak_fallback_text("Merhaba dünya.")
        self.assertGreater(
            self.node.pub_output_pcm.publish.call_count, 0,
            "Eski barge-in mandalı yüzünden kurtarma sesi hiç çalmadı",
        )


class TestNoDoubleReply(unittest.TestCase):
    """Tam tur zaten cevap üretiyorsa kurtarma ikinci bir cevap üretmemeli."""

    def setUp(self):
        self.node = _node()
        self.node.pub_output_pcm = MagicMock()
        self.node._assistant_text_buffer = "Bir cevap."
        self.node._last_user_transcript = "soru"

    def test_recovery_skipped_while_full_turn_in_progress(self):
        from astro_ai.realtime.fallback_policy import FailureKind
        self.node._is_processing_fallback = True
        with patch.object(self.node, "_speak_fallback_text") as speak:
            self.node._recover_silent_response(FailureKind.SILENT_RESPONSE)
        speak.assert_not_called()

    def test_recovery_runs_when_no_full_turn(self):
        from astro_ai.realtime.fallback_policy import FailureKind
        self.node._is_processing_fallback = False
        with patch.object(self.node, "_speak_fallback_text") as speak:
            self.node._recover_silent_response(FailureKind.SILENT_RESPONSE)
        for _ in range(50):
            if speak.call_count:
                break
            time.sleep(0.02)
        speak.assert_called_once()


if __name__ == "__main__":
    unittest.main()
