#!/usr/bin/env python3
"""Sesli yanit dongusu testleri. Donanim ve ag istemez.

Sozce siniri burada test ediliyor: konusma nerede basladi, nerede bitti.
Cumle ici duraklama sozceyi kapatmamali (hece arasi <=0.25 sn, virgul
duraklamasi ~0.5 sn), sozce sonu kapatmali.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core_path  # noqa: F401,E402
from voice import UtteranceTracker  # noqa: E402

SAMPLE_RATE = 16000
BLOCK = 1024
BLOCK_S = BLOCK / SAMPLE_RATE      # 64 ms


def _block(value=0.2):
    return np.full(BLOCK, value, dtype=np.float32)


class UtteranceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tracker = UtteranceTracker(sample_rate=SAMPLE_RATE, silence_s=0.8)

    def _feed(self, pattern, t0=0.0):
        """pattern: her elemani bir blok icin is_speech. Kapanan sozceyi dondurur."""
        closed = []
        t = t0
        for is_speech in pattern:
            out = self.tracker.feed(is_speech, _block(), timestamp=t)
            if out is not None:
                closed.append(out)
            t += BLOCK_S
        return closed

    def test_sessizlik_sozce_acmaz(self):
        self.assertEqual(self._feed([False] * 30), [])

    def test_konusma_sonrasi_yeterli_sessizlik_sozceyi_kapatir(self):
        # 10 blok konusma (0.64 sn), sonra 16 blok sessizlik (1.02 sn > 0.8)
        closed = self._feed([True] * 10 + [False] * 16)

        self.assertEqual(len(closed), 1, "sozce kapanmadi")
        self.assertGreaterEqual(len(closed[0]), 10 * BLOCK,
                                "sozce konusma bloklarinin tamamini icermiyor")

    def test_cumle_ici_duraklama_sozceyi_bolmez(self):
        """Virgul duraklamasi ~0.5 sn; 0.8 sn esigi bunu gecirmemeli."""
        # 6 blok konusma, 7 blok sessizlik (0.45 sn), 6 blok konusma, sonra kapanis
        closed = self._feed([True] * 6 + [False] * 7 + [True] * 6 + [False] * 16)

        self.assertEqual(len(closed), 1,
                         f"cumle ici duraklama sozceyi boldu: {len(closed)} parca")

    def test_sozce_kapanmadan_once_hicbir_sey_dondurulmez(self):
        self.assertEqual(self._feed([True] * 10 + [False] * 5), [])

    def test_cok_uzun_sozce_ust_sinirda_kapanir(self):
        """Susmayan bir kaynak tamponu sonsuza kadar buyutmemeli."""
        tracker = UtteranceTracker(sample_rate=SAMPLE_RATE, silence_s=0.8, max_s=1.0)
        closed = []
        t = 0.0
        for _ in range(40):                        # 2.5 sn kesintisiz konusma
            out = tracker.feed(True, _block(), timestamp=t)
            if out is not None:
                closed.append(out)
            t += BLOCK_S

        self.assertGreaterEqual(len(closed), 1, "ust sinir uygulanmadi")
        self.assertLessEqual(len(closed[0]), int(1.0 * SAMPLE_RATE) + BLOCK)

    def test_kapanan_sozce_sonraki_sozceye_karismaz(self):
        first = self._feed([True] * 8 + [False] * 16)
        second = self._feed([True] * 8 + [False] * 16, t0=100.0)

        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 1)
        # Kapalis sessizligi sozceye dahil ettiginden, uzunlugun ayni olmasi
        # sızıntının olmadığını gösterir — _close() tamamı sıfırlamalı.
        self.assertEqual(len(second[0]), len(first[0]),
                         "ikinci sozce birincinin sesini tasiyor")

    def test_tam_ornek_sayisi_kapanista(self):
        """Sessizlik esiginin tam blok sayisini doğrulamak.

        Konusma + sessizlik duzeninde örnek sayisi hesaplanir:
        silence_s=0.8, BLOCK_S=0.064 ile kapanis koşulu:
        - 1 blok konusma (blok 0, t=0)
        - Blok 1'de sessizlik baslar (t=0.064), silence_started_at=0.064
        - Kapanis esigi: (t - 0.064) >= 0.8 → t >= 0.864
        - 0.864 / 0.064 = 13.5, yani blok 14 ilk kapanisi tetikler
        - Blok 14 (t=0.896): (0.896 - 0.064) = 0.832 >= 0.8 ✓
        - Dahil bloklar: 0-14 = 15 blok = 15360 örnek
        """
        closed = self._feed([True] * 1 + [False] * 16)
        self.assertEqual(len(closed), 1)
        self.assertEqual(len(closed[0]), 15 * BLOCK)


class _FakeStt:
    def __init__(self, text="hey astro nasilsin"):
        self.text = text
        self.calls = []

    def transcribe(self, audio_arr, wav_bytes, sample_rate=16000):
        self.calls.append((len(audio_arr), sample_rate))

        class _Result:
            pass

        result = _Result()
        result.text = self.text
        result.provider = "fake"
        return result


class _FakeLlm:
    def __init__(self, answer="Iyiyim."):
        self.answer = answer
        self.prompts = []
        self.available = True

    def reply(self, user_text):
        self.prompts.append(user_text)
        return self.answer


class _FakeTts:
    def __init__(self):
        self.spoken = []

    def synthesize_and_play(self, text, generation_id, output_manager=None,
                            language="tr", realtime_fallback_reason=None):
        self.spoken.append(text)
        return None


class _FakeOutput:
    def __init__(self):
        self._gen = 0
        self.is_playing = False
        self.interrupts = 0

    def new_generation(self):
        self._gen += 1
        return self._gen

    def interrupt(self, new_generation_id=None):
        self.interrupts += 1
        self._gen += 1
        return self._gen


def _voice(stt=None, llm=None, tts=None, output=None, **kwargs):
    from voice import VoiceLoop

    return VoiceLoop(audio=None, stt=stt or _FakeStt(), llm=llm or _FakeLlm(),
                     tts=tts or _FakeTts(), output=output or _FakeOutput(), **kwargs)


class TurnTests(unittest.TestCase):
    UTTERANCE = np.full(16000, 0.2, dtype=np.float32)

    def test_wake_word_ile_oturum_acilir_ve_cevap_seslendirilir(self):
        tts = _FakeTts()
        loop = _voice(stt=_FakeStt("hey astro nasilsin"), tts=tts)

        said = loop.handle_utterance(self.UTTERANCE, sample_rate=16000)

        self.assertEqual(said, "Iyiyim.")
        self.assertEqual(tts.spoken, ["Iyiyim."])

    def test_oturum_kapaliyken_wake_wordsuz_tur_dusurulur(self):
        tts = _FakeTts()
        loop = _voice(stt=_FakeStt("bugun hava nasil"), tts=tts)

        said = loop.handle_utterance(self.UTTERANCE, sample_rate=16000)

        self.assertIsNone(said)
        self.assertEqual(tts.spoken, [], "oturum kapaliyken konustu")

    def test_oturum_acikken_wake_word_gerekmez(self):
        tts = _FakeTts()
        loop = _voice(stt=_FakeStt("hey astro merhaba"), tts=tts)
        loop.handle_utterance(self.UTTERANCE, sample_rate=16000)

        loop.stt = _FakeStt("bugun hava nasil")
        said = loop.handle_utterance(self.UTTERANCE, sample_rate=16000)

        self.assertIsNotNone(said)
        self.assertEqual(len(tts.spoken), 2)

    def test_devam_turunde_de_turkce_normallestirme_uygulanir(self):
        """is_wake_word() uyandirma sozcugu yokken de normallestirilmis metni
        dondurur (orn. 'ahlatta' -> "Ahlat'ta"); devam turu bunu ham STT
        ciktisiyla ezmemeli, yoksa fonetik duzeltme yalnizca oturumu acan
        soylemde calisir."""
        llm = _FakeLlm()
        loop = _voice(stt=_FakeStt("hey astro merhaba"), llm=llm)
        loop.handle_utterance(self.UTTERANCE, sample_rate=16000)

        loop.stt = _FakeStt("ahlatta oturuyorum")
        loop.handle_utterance(self.UTTERANCE, sample_rate=16000)

        self.assertEqual(llm.prompts[1], "Ahlat'ta oturuyorum",
                         f"devam turu normallestirilmemis ham metinle gitti: {llm.prompts[1]!r}")

    def test_wake_word_metinden_temizlenip_llme_gider(self):
        llm = _FakeLlm()
        loop = _voice(stt=_FakeStt("hey astro bugun hava nasil"), llm=llm)

        loop.handle_utterance(self.UTTERANCE, sample_rate=16000)

        self.assertNotIn("astro", llm.prompts[0].lower(),
                         f"wake word temizlenmemis: {llm.prompts[0]!r}")

    def test_bos_transkript_tur_acmaz(self):
        tts = _FakeTts()
        loop = _voice(stt=_FakeStt(""), tts=tts)

        self.assertIsNone(loop.handle_utterance(self.UTTERANCE, sample_rate=16000))
        self.assertEqual(tts.spoken, [])

    def test_llm_cevap_veremezse_sessiz_kalinir(self):
        tts = _FakeTts()
        loop = _voice(stt=_FakeStt("hey astro selam"), llm=_FakeLlm(answer=None), tts=tts)

        self.assertIsNone(loop.handle_utterance(self.UTTERANCE, sample_rate=16000))
        self.assertEqual(tts.spoken, [], "LLM sussa da TTS konustu")

    def test_stt_16_khze_donusturulmus_ses_gorur(self):
        """Tampon 44.1 kHz olabilir; STT 16 kHz bekler. Donusum tek noktada."""
        stt = _FakeStt("hey astro selam")
        loop = _voice(stt=stt)
        utterance = np.full(44100, 0.2, dtype=np.float32)     # 1 sn @44.1 kHz

        loop.handle_utterance(utterance, sample_rate=44100)

        length, rate = stt.calls[0]
        self.assertEqual(rate, 16000)
        self.assertAlmostEqual(length, 16000, delta=100,
                               msg="ses STT'ye yakalama hizinda verilmis")


if __name__ == "__main__":
    unittest.main()
