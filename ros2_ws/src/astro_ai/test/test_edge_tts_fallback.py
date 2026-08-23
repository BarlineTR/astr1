#!/usr/bin/env python3
"""ASTRO V1 — Edge-TTS öncelikli fallback zinciri testleri.

Kapsam notu: XTTS bilerek test EDİLMİYOR. Edge-TTS zincirin başında olduğu
için XTTS'in sırası ancak Edge-TTS düşerse gelir; buradaki testler yalnızca
"XTTS'e HİÇ dokunulmadığını" doğrular.
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


class TestEdgeTtsIsFirstInChain(unittest.TestCase):
    def setUp(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        self.node = AstroRealtimeNode()
        self.node.edge_tts_enabled = True

    def test_edge_tts_is_used_first_and_xtts_is_never_touched(self):
        """Edge-TTS ses üretiyorsa XTTS'e HİÇ gidilmez."""
        xtts = MagicMock()
        self.node.local_xtts = xtts
        self.node._synthesize_edge_tts_pcm24k = MagicMock(return_value=PCM)

        pcm, engine, _ms, _ready = self.node._synthesize_speech_pcm("Merhaba")

        self.assertEqual(engine, "edge_tts")
        self.assertEqual(pcm, PCM)
        xtts.is_ready.assert_not_called()
        xtts.synthesize_sentence.assert_not_called()

    def test_elevenlabs_is_not_in_the_chain(self):
        """ElevenLabs bulut ve ücretli — fallback zincirinden çıkarıldı."""
        eleven = MagicMock()
        eleven.is_ready.return_value = True
        eleven.synthesize_sentence.return_value = b"\x01\x02" * 480
        self.node.elevenlabs_engine = eleven
        self.node._synthesize_edge_tts_pcm24k = MagicMock(return_value=PCM)

        _pcm, engine, _ms, _ready = self.node._synthesize_speech_pcm("Merhaba")

        self.assertEqual(engine, "edge_tts")
        eleven.synthesize_sentence.assert_not_called()

    def test_falls_through_to_offline_when_edge_returns_nothing(self):
        """Edge-TTS boş dönerse zincir devam eder, patlamaz."""
        self.node._synthesize_edge_tts_pcm24k = MagicMock(return_value=b"")
        self.node.local_xtts = None
        offline = MagicMock()
        offline.is_ready.return_value = True
        offline.synthesize_sentence.return_value = b"\x03\x04" * 480
        self.node.local_offline_tts = offline

        _pcm, engine, _ms, _ready = self.node._synthesize_speech_pcm("Merhaba")
        self.assertEqual(engine, "local_offline_tts")

    def test_edge_exception_does_not_break_chain(self):
        self.node._synthesize_edge_tts_pcm24k = MagicMock(side_effect=RuntimeError("ağ yok"))
        self.node.local_xtts = None
        self.node.local_offline_tts = None

        pcm, engine, _ms, _ready = self.node._synthesize_speech_pcm("Merhaba")
        self.assertEqual(pcm, b"")
        self.assertEqual(engine, "none")

    def test_edge_disabled_skips_edge(self):
        self.node.edge_tts_enabled = False
        self.node._synthesize_edge_tts_pcm24k = MagicMock(return_value=PCM)
        self.node.local_xtts = None
        self.node.local_offline_tts = None

        _pcm, engine, _ms, _ready = self.node._synthesize_speech_pcm("Merhaba")
        self.assertEqual(engine, "none")
        self.node._synthesize_edge_tts_pcm24k.assert_not_called()

    def test_empty_text_returns_none_engine(self):
        pcm, engine, _ms, _ready = self.node._synthesize_speech_pcm("")
        self.assertEqual(pcm, b"")
        self.assertEqual(engine, "none")


class TestEdgeTtsDelegatesToHardenedEngine(unittest.TestCase):
    """Sızdıran satır içi kopya yerine astro_audio.EdgeTTSEngine kullanılmalı."""

    def setUp(self):
        from astro_ai.astro_realtime_node import AstroRealtimeNode
        self.node = AstroRealtimeNode()

    def test_engine_instance_exists(self):
        from astro_audio.edge_tts_engine import EdgeTTSEngine
        self.assertIsInstance(self.node.edge_tts_engine, EdgeTTSEngine)

    def test_synthesis_delegates_to_engine(self):
        self.node.edge_tts_engine = MagicMock()
        self.node.edge_tts_engine.synthesize_sentence.return_value = PCM

        out = self.node._synthesize_edge_tts_pcm24k("Merhaba dünya")

        self.assertEqual(out, PCM)
        self.node.edge_tts_engine.synthesize_sentence.assert_called_once()

    def test_engine_returning_none_becomes_empty_bytes(self):
        """Motor None döner; çağıranlar bytes bekliyor."""
        self.node.edge_tts_engine = MagicMock()
        self.node.edge_tts_engine.synthesize_sentence.return_value = None
        self.assertEqual(self.node._synthesize_edge_tts_pcm24k("Merhaba"), b"")

    def test_engine_exception_becomes_empty_bytes(self):
        self.node.edge_tts_engine = MagicMock()
        self.node.edge_tts_engine.synthesize_sentence.side_effect = RuntimeError("boom")
        self.assertEqual(self.node._synthesize_edge_tts_pcm24k("Merhaba"), b"")

    def test_persona_voice_mapping_is_preserved(self):
        """Kişilik → ses/hız eşlemesi kopyadan motora taşınırken kaybolmamalı."""
        self.node.edge_tts_engine = MagicMock()
        self.node.edge_tts_engine.synthesize_sentence.return_value = PCM

        self.node.persona_name = "flirt"
        self.node._synthesize_edge_tts_pcm24k("Merhaba")
        kwargs_flirt = self.node.edge_tts_engine.synthesize_sentence.call_args.kwargs
        self.assertEqual(kwargs_flirt["voice"], "tr-TR-EmelNeural")

        self.node.edge_tts_engine.synthesize_sentence.reset_mock()
        self.node.persona_name = "formal"
        self.node._synthesize_edge_tts_pcm24k("Merhaba")
        kwargs_formal = self.node.edge_tts_engine.synthesize_sentence.call_args.kwargs
        self.assertEqual(kwargs_formal["voice"], "tr-TR-AhmetNeural")

    def test_generation_id_is_passed_for_cancellation(self):
        self.node.edge_tts_engine = MagicMock()
        self.node.edge_tts_engine.synthesize_sentence.return_value = PCM
        self.node._fallback_generation_id = 42

        self.node._synthesize_edge_tts_pcm24k("Merhaba")
        kwargs = self.node.edge_tts_engine.synthesize_sentence.call_args.kwargs
        self.assertEqual(kwargs["generation_id"], 42)


class TestLeakyDuplicateIsGone(unittest.TestCase):
    """Statik kanıt: kopyadaki event-loop sızıntısı ve öldürülmeyen ffmpeg gitti."""

    def setUp(self):
        import astro_ai.astro_realtime_node as mod
        with open(mod.__file__, "r", encoding="utf-8") as fh:
            src = fh.read()
        start = src.index("def _synthesize_edge_tts_pcm24k")
        end = src.index("def ", start + 10)
        self.body = src[start:end]

    def test_no_manual_event_loop(self):
        """asyncio.new_event_loop + loop.close() yalnızca başarı yolundaydı; her hata bir fd sızdırıyordu."""
        self.assertNotIn("new_event_loop", self.body)

    def test_no_unmanaged_ffmpeg_subprocess(self):
        """ffmpeg timeout'ta öldürülmüyordu; artık motor hallediyor."""
        self.assertNotIn("subprocess.Popen", self.body)

    def test_no_direct_edge_tts_import(self):
        self.assertNotIn("import edge_tts", self.body)


if __name__ == "__main__":
    unittest.main()
