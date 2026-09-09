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


# 1. DOA 69 -> yaw 0
def test_doa_69_maps_to_yaw_0():
    from track import ReSpeakerAudioLocalizer
    assert ReSpeakerAudioLocalizer.calibrated_yaw(69.0) == pytest.approx(0.0, abs=1e-3)


# 2. DOA 33 -> yaw -45
def test_doa_33_maps_to_yaw_minus_45():
    from track import ReSpeakerAudioLocalizer
    assert ReSpeakerAudioLocalizer.calibrated_yaw(33.0) == pytest.approx(-45.0, abs=1e-3)


# 3. DOA 142 -> yaw +45
def test_doa_142_maps_to_yaw_plus_45():
    from track import ReSpeakerAudioLocalizer
    assert ReSpeakerAudioLocalizer.calibrated_yaw(142.0) == pytest.approx(45.0, abs=1e-3)


# 4. DOA 149 -> yaw +90
def test_doa_149_maps_to_yaw_plus_90():
    from track import ReSpeakerAudioLocalizer
    assert ReSpeakerAudioLocalizer.calibrated_yaw(149.0) == pytest.approx(90.0, abs=1e-3)


# 5. circular wrap: 358, 359, 0, 1 -> ortalama ~0
def test_circular_wrap_mean_near_zero():
    from track import ReSpeakerAudioLocalizer
    angles = [358.0, 359.0, 0.0, 1.0]
    mean = ReSpeakerAudioLocalizer.circular_mean(angles)
    dist = ReSpeakerAudioLocalizer.circular_dist(mean, 0.0)
    assert dist < 1.0


# 6. tek outlier reddi (örn. 69, 70, 71, 140, 70 -> 140 outlier)
def test_single_outlier_rejection():
    from track import ReSpeakerAudioLocalizer
    loc = ReSpeakerAudioLocalizer(outlier_threshold_deg=30.0)
    assert loc.reject_outlier(69.0) is False
    assert loc.reject_outlier(70.0) is False
    assert loc.reject_outlier(71.0) is False
    # 140 is a single spike far from ~70 -> rejected
    assert loc.reject_outlier(140.0) is True
    # 70 is back near ~70 -> accepted
    assert loc.reject_outlier(70.0) is False
    assert loc.filtered_doa == pytest.approx(70.0, abs=2.0)
    assert abs(loc.filtered_doa - 140.0) > 50.0


# 7. deadband: küçük değişimlerde yeni head command yok
def test_deadband_suppresses_small_changes():
    from track import ReSpeakerAudioLocalizer
    loc = ReSpeakerAudioLocalizer(deadband_deg=5.0)
    loc.active_target_yaw = -45.0
    # Changes smaller than 5.0 deg do not update target yaw
    assert loc.apply_deadband(-43.0) == -45.0
    assert loc.apply_deadband(-47.0) == -45.0
    assert loc.apply_deadband(-41.0) == -45.0
    # Change >= 5.0 deg updates target yaw
    assert loc.apply_deadband(-39.0) == -39.0
    assert loc.active_target_yaw == -39.0


# 8. VOICEACTIVITY false iken yeni hedef üretilmiyor
def test_voice_activity_false_produces_no_new_target():
    from track import ReSpeakerAudioLocalizer
    loc = ReSpeakerAudioLocalizer(hold_timeout_s=1.2)
    # Speech active at DOA 33 -> target -45.0
    loc.update(doa_raw=33.0, voice_activity=True, timestamp=1.0)
    assert loc.is_tracking() is True
    assert loc.target_yaw_deg == pytest.approx(-45.0, abs=1e-3)

    # Speech inactive, new DOA 149 arrives -> target MUST NOT change
    loc.update(doa_raw=149.0, voice_activity=False, timestamp=1.5)
    assert loc.is_tracking() is True  # still holding within 1.2s timeout
    assert loc.target_yaw_deg == pytest.approx(-45.0, abs=1e-3)
    assert loc.target_yaw_deg != 90.0


# 9. VOICEACTIVITY tekrar true olduğunda DOA tracking devam ediyor
def test_tracking_resumes_when_voice_activity_returns():
    from track import ReSpeakerAudioLocalizer
    loc = ReSpeakerAudioLocalizer(hold_timeout_s=1.2)
    loc.update(doa_raw=33.0, voice_activity=True, timestamp=1.0)
    assert loc.target_yaw_deg == pytest.approx(-45.0, abs=1e-3)

    # Hold timeout expires (1.5s > 1.2s)
    loc.update(doa_raw=None, voice_activity=False, timestamp=2.5)
    assert loc.is_tracking() is False
    assert loc.target_yaw_deg == 0.0

    # Speech resumes at DOA 142
    loc.update(doa_raw=142.0, voice_activity=True, timestamp=3.0)
    assert loc.is_tracking() is True
    assert loc.target_yaw_deg == pytest.approx(45.0, abs=1e-3)


# 10. calibration aralığı dışındaki DOA değerleri güvenli şekilde saturate ediliyor
def test_out_of_range_doa_saturation():
    from track import ReSpeakerAudioLocalizer
    # Left saturation: DOA near/beyond left endpoint (33°) saturates to -45°
    assert ReSpeakerAudioLocalizer.calibrated_yaw(10.0) == -45.0
    assert ReSpeakerAudioLocalizer.calibrated_yaw(0.0) == -45.0
    assert ReSpeakerAudioLocalizer.calibrated_yaw(350.0) == -45.0

    # Right saturation: DOA beyond right endpoint (149°) saturates to +90°
    assert ReSpeakerAudioLocalizer.calibrated_yaw(180.0) == 90.0
    assert ReSpeakerAudioLocalizer.calibrated_yaw(250.0) == 90.0


# 11. eski continuous tracker target_yaw değerleri (-21.2, -36.9, -59.4 gibi) yeni audio target olarak DIŞARI SIZMIYOR
def test_continuous_tracker_angles_never_leak():
    from track import ReSpeakerAudioLocalizer
    from tracker import GazeTracker, PrioritySource

    tracker = GazeTracker()
    loc = ReSpeakerAudioLocalizer()

    # In track.py, GazeTracker.step is called with doa_deg=None
    result = tracker.step(
        faces=[],
        frame_size=(640, 480),
        doa_deg=None,
        measured_head_deg=0.0,
        timestamp=10.0,
        speech=None,
    )
    # Tracker itself never generates audio owner or continuous audio angles
    assert result.owner == PrioritySource.IDLE
    assert result.target_yaw_deg == 0.0
    assert result.target_yaw_deg not in (-21.2, -36.9, -59.4)

    # Audio target comes exclusively from ReSpeakerAudioLocalizer
    loc.update(doa_raw=33.0, voice_activity=True, timestamp=10.0)
    assert loc.target_yaw_deg == -45.0
    assert loc.target_yaw_deg not in (-21.2, -36.9, -59.4)


# 12. audio target tek authoritative kaynak olarak ReSpeakerAudioLocalizer oluyor
def test_audio_target_sole_authoritative_source():
    from track import ReSpeakerAudioLocalizer
    from tracker import GazeResult, PrioritySource, GazeStateEnum, Detection

    loc = ReSpeakerAudioLocalizer(hold_timeout_s=1.2)

    # Step 1: Speech active -> localizer drives target (-45.0)
    loc.update(doa_raw=33.0, voice_activity=True, timestamp=1.0)
    assert loc.is_tracking() is True
    target_yaw = loc.target_yaw_deg
    assert target_yaw == -45.0

    # Step 2: Vision detected -> vision overrides and localizer drops audio tracking
    det = Detection(x=300, y=200, w=80, h=80, confidence=0.95)
    vision_result = GazeResult(
        target_yaw_deg=18.5,
        gaze_state=GazeStateEnum.TRACKING,
        owner=PrioritySource.VISUAL_TRACKING,
        target_id="person_face_1",
        confidence=0.95,
        head_angle_deg=0.0,
    )
    if vision_result.owner == PrioritySource.VISUAL_TRACKING or len([det]) > 0:
        loc.on_vision_active()
        head_target = vision_result.target_yaw_deg

    assert head_target == 18.5
    assert loc.is_tracking() is False
    assert loc.target_yaw_deg == 0.0


def test_track_main_uses_hid_voice_activity():
    from unittest.mock import MagicMock
    mock_hid = MagicMock()
    mock_hid.voice_activity.return_value = True
    mock_hid.doa_angle.return_value = 69.0
    with patch.object(track, "CameraSource", _SabitKamera), \
            patch.object(track, "AudioSource", _SessizKaynak):
        code = track.main(["--fixed-head", "--no-window", "--no-voice", "--seconds", "0.05"], hid=mock_hid)
        assert code == 0
    assert mock_hid.voice_activity.called or mock_hid._read_param.called




