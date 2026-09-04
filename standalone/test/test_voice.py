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


if __name__ == "__main__":
    unittest.main()
