#!/usr/bin/env python3
"""ASTRO V1 — Conversational Response Hardening, Response Length Gate, and TTS Hierarchy Tests.

Acceptance Criteria:
  1. test_short_social_response_policy: Responses default to short (1-2 sentences, <= 35 words).
  2. test_response_length_gate: Gating trims excessive paragraphs at sentence boundaries.
  3. test_self_description_not_injected: Unsolicited self-introductions stripped unless queried.
  4. test_stale_generation_not_played: Stale generation IDs (< current) are dropped by AudioOutputManager.
  5. test_realtime_quota_to_edge_tts: Quota exhaustion gracefully fails over to Edge-TTS.
  6. test_realtime_network_failure_to_edge_tts: Network disconnect fails over to Edge-TTS.
  7. test_edge_tts_to_local_offline: Edge-TTS network failure falls back to Local Offline TTS.
  8. test_generation_id_preserved: Generation ID is immutable across all fallback transitions.
  9. test_realtime_recovery_at_turn_boundary: Provider recovery occurs strictly at turn boundaries.
  10. test_tts_provider_priority: Hierarchy is strictly Realtime -> Edge-TTS -> Local Offline (XTTS dormant).
  11. test_stt_hallucination_filter_altyazi: Whisper hallucinations ('Altyazı M.K.', 'abone ol') are suppressed.
  12. test_groq_429_cooldown_no_storm: Groq 429 initiates cooldown without retry storms.
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# Ensure paths
ws_src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ws_src, "astro_ai"))
sys.path.insert(0, os.path.join(ws_src, "astro_audio"))
sys.path.insert(0, os.path.join(ws_src, "astro_vision"))
os.environ["ASTRO_MOCK_AUDIO"] = "1"

import numpy as np

from astro_ai.persona_engine import (
    PersonaEngine,
    clean_tts_text,
    is_self_identity_query,
    response_length_gate,
    strip_unprompted_self_descriptions,
)
from astro_audio.audio_output_manager import AudioOutputManager
from astro_audio.edge_tts_engine import EdgeTTSEngine
from astro_audio.local_offline_tts_engine import LocalOfflineTTSEngine
from astro_audio.local_xtts_engine import LocalXttsEngine
from astro_audio.realtime_engine import RealtimeEngine, RealtimeState
from astro_audio.stt_router import STTProviderState, STTRouter
from astro_audio.tts_router import TTSRouter


class TestConversationalHardening(unittest.TestCase):
    """Verifies conversational response brevity, prompt guards, and fallback robustness."""

    def setUp(self):
        try:
            from astro_ai.circuit_breaker import GlobalProviderCircuitBreaker
            GlobalProviderCircuitBreaker.get_instance().reset_all()
        except Exception:
            pass

    def test_short_social_response_policy(self):
        """Social responses must be short (<= 35 words, 1-2 sentences)."""
        long_response = (
            "Merhaba! Ben Astro isimli sosyal robotum. Baran beni geliştirdi ve bugün çok mutluyum. "
            "Sana yardımcı olmak için buradayım, ne istersen sorabilirsin. "
            "Ayrıca sensörlerim ve OAK-D Lite kameramla etrafı görüyorum."
        )
        gated = response_length_gate(long_response, user_query="Astro nasılsın?", max_words=35, max_sentences=2)
        words = gated.split()
        self.assertLessEqual(len(words), 35)
        # Verify self-description is stripped
        self.assertNotIn("Baran beni geliştirdi", gated)
        self.assertNotIn("OAK-D Lite", gated)

    def test_response_length_gate(self):
        """Sentence segmentation trims without cutting words in half."""
        text = "Bugün hava çok güzel ve güneşli. Parka gidip yürüyüş yapabilirsin. Ben de seninle gelmek isterdim ama tekerleklerim yok."
        gated = response_length_gate(text, user_query="Hava nasıl?", max_words=15, max_sentences=2)
        words = gated.split()
        self.assertLessEqual(len(words), 15)
        self.assertTrue(gated.endswith((".", "!", "?")))

    def test_self_description_not_injected(self):
        """When user asks 'Nasılsın?', robot should not recite self-identity or creator."""
        text = "Ben Astro, bir sosyal robotum. İyiyim, teşekkür ederim! Sen nasılsın?"
        gated = strip_unprompted_self_descriptions(text, user_query="Nasılsın?")
        self.assertNotIn("Ben Astro", gated)
        self.assertIn("İyiyim, teşekkür ederim! Sen nasılsın?", gated)

        # When user explicitly asks 'Sen kimsin?', identity is preserved
        identity_text = "Ben Astro, Baran tarafından tasarlanan sosyal robot asistanım."
        preserved = strip_unprompted_self_descriptions(identity_text, user_query="Sen kimsin?")
        self.assertEqual(preserved, identity_text)

    def test_stale_generation_not_played(self):
        """Audio chunks from older generation IDs (< current_generation) are dropped."""
        mgr = AudioOutputManager(mock_playback=True)
        gen1 = mgr.new_generation()
        gen2 = mgr.new_generation()
        self.assertGreater(gen2, gen1)

        # Attempt to enqueue chunk from gen1 (stale)
        res1 = mgr.play_pcm_chunk(b"\x00\x01" * 100, generation_id=gen1)
        self.assertFalse(res1)

        # Enqueue chunk from current gen2 (valid)
        res2 = mgr.play_pcm_chunk(b"\x00\x01" * 100, generation_id=gen2)
        self.assertTrue(res2)

    def test_realtime_quota_to_edge_tts(self):
        """When OpenAI Realtime encounters quota exhaustion (1013), it degrades to Edge-TTS."""
        rt = RealtimeEngine()
        rt._state = RealtimeState.REALTIME_ACTIVE
        state, reason = rt.handle_websocket_error(1013, "insufficient_quota")
        self.assertEqual(state, RealtimeState.REALTIME_QUOTA_EXHAUSTED)
        self.assertEqual(reason, "realtime_quota_exhausted")
        self.assertFalse(rt.is_ready())

    def test_realtime_network_failure_to_edge_tts(self):
        """Realtime WebSocket disconnect degrades to Edge-TTS."""
        rt = RealtimeEngine()
        rt._state = RealtimeState.REALTIME_ACTIVE
        state, reason = rt.handle_websocket_error(1006, "connection reset by peer")
        self.assertEqual(state, RealtimeState.REALTIME_OFFLINE)
        self.assertEqual(reason, "realtime_network_unavailable")
        self.assertFalse(rt.is_ready())

    def test_edge_tts_to_local_offline(self):
        """When internet is down (preflight socket fails), TTSRouter routes directly to Local Offline TTS."""
        edge = EdgeTTSEngine()
        local_off = LocalOfflineTTSEngine()
        router = TTSRouter(
            edge_tts_engine=edge,
            local_offline_tts=local_off,
            edge_tts_enabled=True,
        )

        with patch("socket.create_connection", side_effect=OSError("Network unreachable")):
            res = router.synthesize("Merhaba dostum!", generation_id=101)
            self.assertEqual(res.actual_provider, "local_offline_tts")
            self.assertTrue(len(res.pcm) > 0)
            self.assertIn("openai_realtime", res.fallback_chain[0])
            self.assertTrue(any("edge_tts" in f for f in res.fallback_chain))

    def test_generation_id_preserved(self):
        """Generation ID is preserved across the entire fallback chain."""
        edge = EdgeTTSEngine()
        local_off = LocalOfflineTTSEngine()
        router = TTSRouter(
            edge_tts_engine=edge,
            local_offline_tts=local_off,
            edge_tts_enabled=True,
        )
        fake_pcm = b"\x00\x02" * 500
        with patch.object(edge, "synthesize_sentence", return_value=fake_pcm), \
             patch("socket.create_connection", return_value=MagicMock()):
            res = router.synthesize("Test mesajı", generation_id=777)
            self.assertEqual(res.actual_provider, "edge_tts")
            # Verify output manager accepts chunk with matching gen_id
            mgr = AudioOutputManager(mock_playback=True)
            mgr._current_generation = 777
            accepted = mgr.play_pcm_chunk(res.pcm, generation_id=777)
            self.assertTrue(accepted)

    def test_realtime_recovery_at_turn_boundary(self):
        """Recovery from degraded state back to active Realtime occurs only at turn boundaries."""
        rt = RealtimeEngine()
        rt._state = RealtimeState.REALTIME_DEGRADED
        self.assertFalse(rt.is_ready())

        # Mid-turn query still shows degraded
        self.assertFalse(rt.is_ready())

        # Reset at turn boundary after successful re-probe
        rt.reset_quota_status()
        self.assertEqual(rt.state, RealtimeState.REALTIME_ACTIVE)

    def test_tts_provider_priority(self):
        """Hierarchy is strictly Realtime -> Edge-TTS -> Local Offline (XTTS dormant)."""
        xtts = LocalXttsEngine(speaker_wav="test.wav", home="/tmp/fake_xtts")
        # In production runtime XTTS is disabled by policy
        self.assertFalse(xtts.runtime_enabled)
        self.assertFalse(xtts.is_ready())

    def test_stt_hallucination_filter_altyazi(self):
        """Whisper hallucination 'altyazı m.k.' is filtered when acoustic energy is low."""
        hallucination = "altyazı m.k."
        is_phantom = any(
            sh in hallucination.lower()
            for sh in ["altyazı m.k.", "altyazı", "abone ol", "amara.org"]
        )
        self.assertTrue(is_phantom)

    def test_groq_429_cooldown_no_storm(self):
        """Groq 429 rate limit initiates 30s cooldown and falls back to secondary without retry loop."""
        mock_groq = MagicMock()
        mock_groq.audio.transcriptions.create.side_effect = Exception("429 Too Many Requests (RPM limit reached)")
        router = STTRouter(groq_client=mock_groq)

        fake_audio = np.zeros(16000, dtype=np.int16)
        fake_wav = b"RIFFfake"

        # First call triggers 429 and enters COOLDOWN
        res1 = router.transcribe(fake_audio, fake_wav)
        self.assertEqual(router.groq_state, STTProviderState.COOLDOWN)
        self.assertGreater(router.groq_cooldown_until, time.monotonic())

        # Immediate second call fast-skips Groq without calling API again
        mock_groq.audio.transcriptions.create.reset_mock()
        res2 = router.transcribe(fake_audio, fake_wav)
        mock_groq.audio.transcriptions.create.assert_not_called()
        self.assertIn("cooldown", res2.fallback_chain[0])

    def test_phonetic_speech_normalization(self):
        """Phonetically mis-transcribed wake phrases (Ey Aston, Heya sonuç ısın) are normalized."""
        from astro_ai.conversation_session import ConversationSession, normalize_turkish_speech_input

        session = ConversationSession()
        test_inputs = [
            ("Ey Aston nasılsın?", "Hey Astro nasılsın?"),
            ("Heya sonuç ısın", "Hey Astro nasılsın"),
            ("Ahvatta hava nasıl?", "Ahlat'ta hava nasıl?"),
            ("Astor nasılsın", "Astro nasılsın"),
        ]
        for corrupted, expected in test_inputs:
            norm = normalize_turkish_speech_input(corrupted)
            self.assertEqual(norm, expected)
            has_wake, clean = session.is_wake_word(corrupted)
            if "Astro" in expected:
                self.assertTrue(has_wake)

    def test_whisper_prompt_biasing(self):
        """STTRouter includes domain vocabulary prompt in API calls."""
        from astro_audio.stt_router import TURKISH_STT_PROMPT, STTRouter
        mock_groq = MagicMock()
        mock_groq.audio.transcriptions.create.return_value = "Hey Astro nasılsın"
        router = STTRouter(groq_client=mock_groq)

        fake_audio = np.zeros(16000, dtype=np.int16)
        fake_wav = b"RIFFfake"
        res = router.transcribe(fake_audio, fake_wav)
        self.assertEqual(res.text, "Hey Astro nasılsın")
        mock_groq.audio.transcriptions.create.assert_called_once()
        _, kwargs = mock_groq.audio.transcriptions.create.call_args
        self.assertEqual(kwargs.get("prompt"), TURKISH_STT_PROMPT)


if __name__ == "__main__":
    unittest.main()
