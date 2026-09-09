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


def test_audio_sector_classification():
    from track import AudioSectorMapper

    mapper = AudioSectorMapper()
    # 0..55 -> LEFT (-55°)
    assert mapper.classify_sector(0.0) == -55.0
    assert mapper.classify_sector(30.0) == -55.0
    assert mapper.classify_sector(55.0) == -55.0

    # 55..95 -> CENTER (0°)
    assert mapper.classify_sector(56.0) == 0.0
    assert mapper.classify_sector(75.0) == 0.0
    assert mapper.classify_sector(95.0) == 0.0

    # 95..300 -> RIGHT (+55°)
    assert mapper.classify_sector(96.0) == 55.0
    assert mapper.classify_sector(150.0) == 55.0
    assert mapper.classify_sector(299.0) == 55.0

    # 300..360 -> LEFT (-55°)
    assert mapper.classify_sector(300.0) == -55.0
    assert mapper.classify_sector(330.0) == -55.0
    assert mapper.classify_sector(359.9) == -55.0


def test_audio_sector_persistence_three_samples():
    from track import AudioSectorMapper

    mapper = AudioSectorMapper(persistence_required=3)

    # 1. İlk 2 örnekte sektör kilitlenmez (None döner)
    assert mapper.update(40.0, is_speech=True, timestamp=1.0) is None
    assert mapper.update(45.0, is_speech=True, timestamp=1.05) is None

    # 2. 3. ardışık örnekte sol sektör (-55°) kilitlenir
    assert mapper.update(50.0, is_speech=True, timestamp=1.10) == -55.0

    # 3. Sektör içinde kalan dalgalanmalarda target sabit kalır
    assert mapper.update(35.0, is_speech=True, timestamp=1.15) == -55.0
    assert mapper.update(20.0, is_speech=True, timestamp=1.20) == -55.0

    # 4. Sağdan gelen tek bir glitch örneği sektörü bozmaz
    assert mapper.update(180.0, is_speech=True, timestamp=1.25) == -55.0
    assert mapper.update(40.0, is_speech=True, timestamp=1.30) == -55.0

    # 5. Yeni sektöre (sağ: +55°) geçiş için 3 ardışık örnek şartı
    assert mapper.update(150.0, is_speech=True, timestamp=1.35) == -55.0
    assert mapper.update(160.0, is_speech=True, timestamp=1.40) == -55.0
    assert mapper.update(155.0, is_speech=True, timestamp=1.45) == 55.0  # 3. örnekte sağa geçer

    # 6. Sağ sektörde kalmaya devam eder
    assert mapper.update(200.0, is_speech=True, timestamp=1.50) == 55.0


def test_audio_target_retention():
    from track import AudioTargetRetention

    ret = AudioTargetRetention(hold_grace_s=1.0)

    # 1. Konuşmacı -55° sektöründe konuştu
    assert ret.on_active_speaker(-55.0, 29.0) == -55.0

    # 2. 500 ms sonra kısa duraklama (dropout) -> -55° korunmalı
    assert ret.on_speech_dropout(active_sector=None, now=29.5) == -55.0

    # 3. 900 ms sonra hala duraklama -> -55° korunmalı
    assert ret.on_speech_dropout(active_sector=None, now=29.9) == -55.0

    # 4. Grace süresi doldu (1.05s sonra) -> hedef düşmeli (None)
    assert ret.on_speech_dropout(active_sector=None, now=30.05) is None

    # 5. Yeni sektör teyit edilirse grace içinde bile anında yeni sektöre geçer
    ret.on_active_speaker(-55.0, 40.0)
    assert ret.on_speech_dropout(active_sector=55.0, now=40.4) == 55.0

    # 6. Vision devreye girerse audio hedefi derhal iptal edilir
    ret.on_vision_active()
    assert ret.retained_target_yaw is None
    assert ret.on_speech_dropout(active_sector=None, now=40.5) is None


def test_audio_retention_prevents_continuous_doa_leak_to_idle():
    """Audio aktifken sektör kilidi (-55°), dropout sırasında hedef koruma,
    grace bitince doğrudan 0.0°'a dönme ve continuous audio yaw'ın (-36.9°, -59.4°)
    ASLA dışarı sızmamasını doğrular.
    """
    from track import AudioSectorMapper, AudioTargetRetention, resolve_target_yaw
    from tracker import GazeResult, PrioritySource, GazeStateEnum, Detection

    mapper = AudioSectorMapper(persistence_required=3)
    retention = AudioTargetRetention(hold_grace_s=1.0)

    # 1. ACTIVE_SPEAKER: Sol sektörde konuşma (-55° sektör kilidi)
    # Tracker continuous raw DOA açısı (-36.9°) üretse bile...
    sector = mapper.update(40.0, is_speech=True, timestamp=10.0)
    assert sector is None  # 1. örnek
    sector = mapper.update(45.0, is_speech=True, timestamp=10.05)
    assert sector is None  # 2. örnek
    sector = mapper.update(50.0, is_speech=True, timestamp=10.10)
    assert sector == -55.0  # 3. örnekte -55° kilitlenir

    result = GazeResult(
        target_yaw_deg=-36.9,  # Continuous audio DOA
        gaze_state=GazeStateEnum.ORIENTING,
        owner=PrioritySource.ACTIVE_SPEAKER,
        target_id="audio_speaker_1",
        confidence=0.85,
        head_angle_deg=0.0,
    )
    target = resolve_target_yaw(
        result=result,
        detections=[],
        active_sector=sector,
        target_retention=retention,
        sector_mapper=mapper,
        now=10.10,
    )
    # Step 1 Assert: Hedef continuous (-36.9°) değil, sektör (-55.0°) olmalı
    assert target == -55.0
    assert result.target_yaw_deg == -55.0
    assert result.owner == PrioritySource.ACTIVE_SPEAKER

    # 2. & 3. Speech dropout: 500 ms sonra konuşma kesildi
    # Tracker IDLE/ACQUIRING'e düşüp continuous DOA (-54.5°) üretse bile...
    sector = mapper.update(raw_doa=None, is_speech=False, timestamp=10.60)
    result_dropout = GazeResult(
        target_yaw_deg=-54.5,  # Continuous audio DOA
        gaze_state=GazeStateEnum.IDLE,
        owner=PrioritySource.IDLE,
        target_id=None,
        confidence=0.0,
        head_angle_deg=-20.0,
    )
    target_held = resolve_target_yaw(
        result=result_dropout,
        detections=[],
        active_sector=sector,
        target_retention=retention,
        sector_mapper=mapper,
        now=10.60,
    )
    # Step 2 & 3 Assert: Grace period içinde (1.0s dolmadı) sektör (-55.0°) korunmalı
    assert target_held == -55.0
    assert result_dropout.target_yaw_deg == -55.0
    assert result_dropout.owner == PrioritySource.ACTIVE_SPEAKER

    # 4. Grace süresi doldu (dropout üzerinden 1.5s geçti, now=12.10)
    # Tracker hala continuous DOA (-59.4°) üretse bile...
    result_expired = GazeResult(
        target_yaw_deg=-59.4,  # Continuous audio DOA
        gaze_state=GazeStateEnum.IDLE,
        owner=PrioritySource.IDLE,
        target_id=None,
        confidence=0.0,
        head_angle_deg=-50.0,
    )
    target_expired = resolve_target_yaw(
        result=result_expired,
        detections=[],
        active_sector=None,
        target_retention=retention,
        sector_mapper=mapper,
        now=12.10,
    )
    # Step 4 Assert: Grace bitince hedef ASLA -59.4° ya da -36.9° olamaz! Kesinlikle 0.0° olmalı!
    assert target_expired == 0.0
    assert result_expired.target_yaw_deg == 0.0
    assert result_expired.target_yaw_deg != -59.4
    assert result_expired.target_yaw_deg != -36.9
    assert retention.retained_target_yaw is None

    # 5. Vision devreye girdiğinde:
    # Audio retention anında düşmeli ve vision hedefi %100 kullanılmalı
    # Tekrar audio sektör kilidi alalım:
    sector = mapper.update(40.0, is_speech=True, timestamp=15.0)
    sector = mapper.update(45.0, is_speech=True, timestamp=15.05)
    sector = mapper.update(50.0, is_speech=True, timestamp=15.10)
    assert sector == -55.0
    res_audio = GazeResult(
        target_yaw_deg=-30.0,
        gaze_state=GazeStateEnum.ORIENTING,
        owner=PrioritySource.ACTIVE_SPEAKER,
        target_id="audio_speaker_1",
        confidence=0.8,
        head_angle_deg=0.0,
    )
    resolve_target_yaw(res_audio, [], sector, retention, mapper, now=15.10)
    assert retention.retained_target_yaw == -55.0

    # Vision yüz gördü (örneğin azimuth +18.5°)
    res_vision = GazeResult(
        target_yaw_deg=18.5,
        gaze_state=GazeStateEnum.TRACKING,
        owner=PrioritySource.VISUAL_TRACKING,
        target_id="person_face_1",
        confidence=0.95,
        head_angle_deg=0.0,
    )
    det = Detection(x=300, y=200, w=80, h=80, confidence=0.95)
    target_vis = resolve_target_yaw(res_vision, [det], sector, retention, mapper, now=15.15)
    assert target_vis == 18.5
    assert res_vision.target_yaw_deg == 18.5
    assert retention.retained_target_yaw is None


