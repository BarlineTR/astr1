#!/usr/bin/env python3
"""ASTRO V1 — "Yanıt kuruldu ama ses gelmedi" durumundan kurtarma.

Canlı logda yakalanan durum:
    [REALTIME RESPONSE CREATED] generation_id=1
    [REALTIME NO AUDIO] generation_id=1 elapsed_ms=68.0
    [TTS FALLBACK] from=openai_realtime to=edge_tts reason=realtime_no_audio
    (…ve hiçbir şey olmadı — robot sessiz kaldı)

O son satır bir YALANDI: yalnızca loglanıyor, hiçbir kurtarma
çalıştırılmıyordu. Buradaki testler artık gerçekten konuşulduğunu doğrular.
"""

import asyncio
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


def _new_node():
    from astro_ai.astro_realtime_node import AstroRealtimeNode
    node = AstroRealtimeNode()
    node.pub_output_pcm = MagicMock()
    node.edge_tts_enabled = True
    node._fallback_mode = False
    node._is_sleeping = False
    return node


def _drive_to_streaming(node, rid="resp_1"):
    node.turn_machine.on_event("input_audio_buffer.speech_started")
    node.turn_machine.on_event("input_audio_buffer.speech_stopped")
    node.turn_machine.on_event("response.created", rid)
    node.realtime_audio_received = False


class TestAssistantTranscriptIsAccumulated(unittest.TestCase):
    """Realtime asistanın sözlerini metin olarak da akıtıyor; eskiden çöpe gidiyordu."""

    def setUp(self):
        self.node = _new_node()

    def test_transcript_deltas_are_collected(self):
        for delta in ("Merhaba ", "Baran, ", "nasılsın?"):
            asyncio.run(self.node._handle_realtime_event(
                MagicMock(), {"type": "response.audio_transcript.delta", "delta": delta}
            ))
        self.assertEqual(self.node._assistant_text_buffer.strip(), "Merhaba Baran, nasılsın?")

    def test_buffer_resets_on_new_response(self):
        asyncio.run(self.node._handle_realtime_event(
            MagicMock(), {"type": "response.audio_transcript.delta", "delta": "eski"}
        ))
        asyncio.run(self.node._handle_realtime_event(
            MagicMock(), {"type": "response.created", "response": {"id": "r2"}}
        ))
        self.assertEqual(self.node._assistant_text_buffer, "")


class TestSilentResponseSpeaksAssistantText(unittest.TestCase):
    """Tier A: model ne diyeceğini yazdı ama sesi gelmedi -> metni seslendir."""

    def setUp(self):
        self.node = _new_node()
        _drive_to_streaming(self.node)
        self.node._assistant_text_buffer = "Bugün hava çok güzel."

    def test_recovery_synthesizes_and_publishes(self):
        with patch.object(self.node, "_synthesize_speech_pcm",
                          return_value=(PCM, "edge_tts", 700.0, True)) as synth:
            asyncio.run(self.node._handle_realtime_event(
                MagicMock(), {"type": "response.done", "response": {"status": "completed"}}
            ))
        synth.assert_called_once()
        self.assertIn("Bugün hava çok güzel.", synth.call_args.args[0])
        # Seslendirme daemon thread'de: yayının gelmesini sınırlı süre bekle.
        import time as _t
        for _ in range(100):
            if self.node.pub_output_pcm.publish.call_count:
                break
            _t.sleep(0.02)
        self.assertGreater(self.node.pub_output_pcm.publish.call_count, 0)

    def test_cancelled_response_triggers_no_recovery(self):
        """Barge-in ile kesilen yanıt hata değildir — üzerine konuşulmamalı."""
        with patch.object(self.node, "_synthesize_speech_pcm") as synth:
            asyncio.run(self.node._handle_realtime_event(
                MagicMock(),
                {"type": "response.done",
                 "response": {"status": "cancelled",
                              "status_details": {"type": "cancelled", "reason": "turn_detected"}}},
            ))
        synth.assert_not_called()

    def test_response_with_audio_triggers_no_recovery(self):
        self.node.realtime_audio_received = True
        with patch.object(self.node, "_synthesize_speech_pcm") as synth:
            asyncio.run(self.node._handle_realtime_event(
                MagicMock(), {"type": "response.done", "response": {"status": "completed"}}
            ))
        synth.assert_not_called()


class TestSilentResponseAnswersUserText(unittest.TestCase):
    """Tier B: asistan metni yok ama kullanıcının ne dediğini biliyoruz."""

    def setUp(self):
        self.node = _new_node()
        _drive_to_streaming(self.node)
        self.node._assistant_text_buffer = ""
        self.node._last_user_transcript = "nasılsın"

    def test_local_answer_is_generated_and_spoken(self):
        with patch.object(self.node, "_synthesize_speech_pcm",
                          return_value=(PCM, "edge_tts", 700.0, True)) as synth:
            asyncio.run(self.node._handle_realtime_event(
                MagicMock(), {"type": "response.done", "response": {"status": "completed"}}
            ))
        synth.assert_called_once()
        self.assertTrue(synth.call_args.args[0].strip(), "Boş metin seslendirilmeye çalışıldı")


class TestResponseDoneStatusIsRead(unittest.TestCase):
    """status / status_details okunmazsa 'neden ses yok' sorusu cevapsız kalır."""

    def setUp(self):
        self.node = _new_node()
        _drive_to_streaming(self.node)
        self.node._assistant_text_buffer = "x"
        self.logs = []
        fake = MagicMock()
        for lvl in ("info", "warn", "error", "debug"):
            setattr(fake, lvl, (lambda m, _l=lvl: self.logs.append(f"{_l}:{m}")))
        self.node.get_logger = lambda: fake

    def test_failure_reason_is_logged(self):
        with patch.object(self.node, "_synthesize_speech_pcm", return_value=(PCM, "edge_tts", 1.0, True)):
            asyncio.run(self.node._handle_realtime_event(
                MagicMock(),
                {"type": "response.done",
                 "response": {"status": "failed",
                              "status_details": {"type": "failed",
                                                 "error": {"code": "rate_limit_exceeded",
                                                           "message": "Rate limit reached"}}}},
            ))
        blob = "\n".join(self.logs)
        self.assertIn("RATE_LIMIT", blob, f"Başarısızlık sebebi loglanmadı:\n{blob}")

    def test_rate_limited_response_enters_fallback_mode(self):
        with patch.object(self.node, "_synthesize_speech_pcm", return_value=(PCM, "edge_tts", 1.0, True)):
            asyncio.run(self.node._handle_realtime_event(
                MagicMock(),
                {"type": "response.done",
                 "response": {"status": "failed",
                              "status_details": {"type": "failed",
                                                 "error": {"code": "rate_limit_exceeded",
                                                           "message": "Rate limit reached"}}}},
            ))
        self.assertTrue(self.node._fallback_mode)

    def test_single_silent_response_does_not_abandon_realtime(self):
        with patch.object(self.node, "_synthesize_speech_pcm", return_value=(PCM, "edge_tts", 1.0, True)):
            asyncio.run(self.node._handle_realtime_event(
                MagicMock(), {"type": "response.done", "response": {"status": "completed"}}
            ))
        self.assertFalse(self.node._fallback_mode)


class TestNoLyingFallbackLog(unittest.TestCase):
    """'to=edge_tts' yazan bir log, gerçekten sentez denenmeden basılmamalı."""

    def test_fallback_log_accompanies_real_synthesis(self):
        node = _new_node()
        _drive_to_streaming(node)
        node._assistant_text_buffer = "bir şey"
        logs = []
        fake = MagicMock()
        for lvl in ("info", "warn", "error", "debug"):
            setattr(fake, lvl, (lambda m, _l=lvl: logs.append(str(m))))
        node.get_logger = lambda: fake

        with patch.object(node, "_synthesize_speech_pcm",
                          return_value=(PCM, "edge_tts", 1.0, True)) as synth:
            asyncio.run(node._handle_realtime_event(
                MagicMock(), {"type": "response.done", "response": {"status": "completed"}}
            ))

        blob = "\n".join(logs)
        if "to=edge_tts" in blob:
            synth.assert_called(), "Log Edge-TTS'e geçtiğini söyledi ama sentez çağrılmadı"


if __name__ == "__main__":
    unittest.main()
