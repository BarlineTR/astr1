"""Sabit dizüstü kamerası, dönmeyen kafayı dönmüş gibi göstermemeli."""

import contextlib
import io
import re
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import track
from tracker import Detection


class _SabitKamera:
    available = True
    backend = "webcam"
    detector_name = "test"

    def __init__(self, **kwargs):
        self.kalan = 200
        self.frame = np.zeros((480, 640, 3), dtype=np.uint8)

    def read(self):
        self.kalan -= 1
        return self.kalan >= 0, self.frame

    def detect(self, frame):
        # Merkez x=380: 640 piksellik görüntüde hafif sağda sabit bir yüz.
        return [Detection(x=330, y=160, w=100, h=100, confidence=0.95)]

    def close(self):
        pass


class _SessizKaynak:
    available = False
    error = "testte ses yok"

    def __init__(self, **kwargs):
        pass

    def start(self):
        pass

    def close(self):
        pass


def test_sabit_kamera_yuzu_kafa_limitine_suruklemez():
    """Gerçek main ve ortak beyin; yalnız aygıtlar ve saat denetim altında."""
    saat = iter(100 + i / 30 for i in range(1000))
    cikti = io.StringIO()
    with patch.object(track, "CameraSource", _SabitKamera), \
            patch.object(track, "AudioSource", _SessizKaynak), \
            patch.object(track.time, "monotonic", side_effect=lambda: next(saat)), \
            contextlib.redirect_stdout(cikti):
        assert track.main(["--no-window", "--no-voice", "--fixed-head"]) == 0

    satirlar = [line for line in cikti.getvalue().splitlines() if "istenen" in line]
    hedefler = [float(re.search(r"istenen\s*([+-][\d.]+)", line)[1]) for line in satirlar]
    assert len(hedefler) > 3
    assert all(-10 < hedef < -3 for hedef in hedefler)
    assert max(hedefler) - min(hedefler) < 0.1
    assert all("sabit" in line and "kafa:X" in line for line in satirlar)
    assert "gercek" not in cikti.getvalue()
    assert "Encoder hiç konuşmadı" not in cikti.getvalue()


def test_sabit_referans_motor_baglantisiyla_birlikte_acilamaz():
    with pytest.raises(SystemExit) as exc:
        track.main(["--fixed-head", "--serial", "/dev/test"])
    assert exc.value.code == 2

