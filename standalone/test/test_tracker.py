#!/usr/bin/env python3
"""Tests for the ROS-free tracker.

This is the same brain the ROS node runs — the fusion, target manager and FSM are
imported, not reimplemented — so what is tested here is the wiring around them, and
that the guarantees the ROS side already has survive the move: bearings that account
for where the head is, audio that says who rather than where, and a head estimate
that does not collapse to centre when the encoder stays silent.

If behaviour here and under ROS ever differ, the difference is the plumbing. That is
the whole reason this exists.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core_path  # noqa: F401
from astro_base.gaze.types import GazeStateEnum, PrioritySource  # noqa: E402

from tracker import Detection, GazeTracker  # noqa: E402


FRAME = (640, 480)


def _face_at(u_fraction: float, confidence: float = 0.92) -> Detection:
    """A face box centred at the given fraction across the frame (0 left, 1 right)."""
    w = h = 90
    cx = u_fraction * FRAME[0]
    return Detection(x=int(cx - w / 2), y=195, w=w, h=h, confidence=confidence)


class TestAFaceMovesTheHead(unittest.TestCase):
    def setUp(self):
        self.tracker = GazeTracker()

    def _settle(self, faces, cycles=40, t0=100.0, head=0.0):
        result = None
        for i in range(cycles):
            result = self.tracker.step(
                faces=faces, frame_size=FRAME, doa_deg=None,
                measured_head_deg=head, timestamp=t0 + i * 0.02,
            )
        return result

    def test_a_face_on_the_left_is_answered_with_a_leftward_command(self):
        """Image left is positive yaw in REP-103, which is the convention the whole
        stack uses and the easiest thing to get backwards."""
        result = self._settle([_face_at(0.15)])

        self.assertGreater(result.target_yaw_deg, 5.0)

    def test_a_face_on_the_right_is_answered_with_a_rightward_command(self):
        result = self._settle([_face_at(0.85)])

        self.assertLess(result.target_yaw_deg, -5.0)

    def test_a_centred_face_leaves_the_head_where_it_is(self):
        result = self._settle([_face_at(0.5)])

        self.assertAlmostEqual(result.target_yaw_deg, 0.0, delta=4.0)

    def test_a_visible_face_owns_the_attention(self):
        result = self._settle([_face_at(0.3)])

        self.assertIn(
            result.owner, (PrioritySource.VISUAL_TRACKING, PrioritySource.ACTIVE_SPEAKER)
        )

    def test_an_empty_scene_stays_idle_at_centre(self):
        result = self._settle([])

        self.assertEqual(result.owner, PrioritySource.IDLE)
        self.assertEqual(result.gaze_state, GazeStateEnum.IDLE)
        self.assertAlmostEqual(result.target_yaw_deg, 0.0, delta=0.1)


class TestBearingsAccountForWhereTheHeadIs(unittest.TestCase):
    """`body_azimuth = head_yaw + camera_azimuth`. Getting this wrong is what made
    the ROS version drive back to centre the moment the head moved."""

    def test_a_centred_face_seen_from_a_turned_head_is_not_at_zero(self):
        tracker = GazeTracker()
        result = None
        for i in range(40):
            result = tracker.step(
                faces=[_face_at(0.5)], frame_size=FRAME, doa_deg=None,
                measured_head_deg=30.0, timestamp=100.0 + i * 0.02,
            )

        self.assertGreater(result.target_yaw_deg, 25.0)


class TestTheHeadEstimateWithoutAnEncoder(unittest.TestCase):
    def test_a_silent_encoder_is_reported_rather_than_assumed_to_be_zero(self):
        tracker = GazeTracker()

        tracker.step(faces=[], frame_size=FRAME, doa_deg=None,
                     measured_head_deg=None, timestamp=100.0)

        self.assertTrue(tracker.head_feedback_missing)

    def test_the_estimate_follows_the_command_instead_of_sitting_at_zero(self):
        tracker = GazeTracker()
        for i in range(400):
            tracker.step(faces=[_face_at(0.05)], frame_size=FRAME, doa_deg=None,
                         measured_head_deg=None, timestamp=100.0 + i * 0.02)

        self.assertGreater(tracker.head_angle_deg, 5.0)

    def test_a_real_reading_takes_over_from_the_estimate(self):
        tracker = GazeTracker()
        for i in range(20):
            tracker.step(faces=[_face_at(0.05)], frame_size=FRAME, doa_deg=None,
                         measured_head_deg=None, timestamp=100.0 + i * 0.02)

        tracker.step(faces=[], frame_size=FRAME, doa_deg=None,
                     measured_head_deg=-12.0, timestamp=101.0)

        self.assertEqual(tracker.head_angle_deg, -12.0)
        self.assertFalse(tracker.head_feedback_missing)


class TestAudioSaysWhoNotWhere(unittest.TestCase):
    """The same guarantee the ROS side has: a wandering DOA must not drag the aim."""

    def test_the_aim_is_unchanged_across_the_doa_spread(self):
        aims = set()
        for raw_doa in (0.0, 15.0, 330.0, 345.0):
            tracker = GazeTracker()
            result = None
            for i in range(40):
                result = tracker.step(
                    faces=[_face_at(0.3)], frame_size=FRAME, doa_deg=raw_doa,
                    measured_head_deg=0.0, timestamp=100.0 + i * 0.02,
                )
            aims.add(round(result.target_yaw_deg, 1))

        self.assertEqual(len(aims), 1, f"audio moved the aim: {aims}")


class TestOnlySpeechEarnsTheHead(unittest.TestCase):
    """Yalnizca insan sesi kafayi cevirebilir.

    Sahadaki 130 saniyelik bir kosuda kafa, yuz kaybolduktan sonra 90 saniye
    boyunca +-75 arasinda salindi: kerteriz ureten her yuksek ses hedefi ele
    geciriyordu ve guven sabit 0.85 verildigi icin 0.45'lik ses edinme esigini
    her seferinde asiyordu. Pencereden gelen bir araba da, bir ugultu da yuksek
    ve israrcidir; onlari enerji de yon kararliligi da elemez.

    Bu iki test ciftin iki yarisi: gurultu kafayi kapamamali, ama konusma hala
    kapabilmeli. Ikincisi olmadan birincisi "sesle takibi kapatmak" olurdu.
    """

    NOISE_BEARING = -18.0

    def _run(self, speech, cycles=60, faces=None):
        tracker = GazeTracker()
        result = None
        face_list = [_face_at(0.25, confidence=0.60)] if faces is None else faces
        for i in range(cycles):
            result = tracker.step(
                faces=face_list, frame_size=FRAME, doa_deg=self.NOISE_BEARING,
                speech=speech, measured_head_deg=0.0, timestamp=200.0 + i * 0.02,
            )
        return result

    def test_araba_gurultusu_kafayi_kapamaz(self):
        from astro_audio.speech_detector import SpeechVerdict

        not_speech = SpeechVerdict(is_speech=False, confidence=0.0, harmonicity=0.32,
                                   modulation=0.03, rms=0.2,
                                   reason="ne harmonik ne modulasyonlu")

        result = self._run(not_speech)

        # Görsel hedef olsa bile gürültü ACTIVE_SPEAKER yapamaz, VISUAL_TRACKING kalır
        self.assertNotEqual(result.owner, PrioritySource.ACTIVE_SPEAKER,
                            "konusma olmayan bir ses aktif konusmaci oldu")

    def test_konusma_yuz_varken_kafayi_kapabilir(self):
        """Görsel yüz ile eşleşen konuşma aktif konuşmacı olur."""
        from astro_audio.speech_detector import SpeechVerdict

        speech = SpeechVerdict(is_speech=True, confidence=0.76, harmonicity=0.59,
                               modulation=0.83, rms=0.2)

        result = self._run(speech)

        self.assertEqual(result.owner, PrioritySource.ACTIVE_SPEAKER,
                         "konusma kafayi cevirmedi -- gurultu filtresi ozelligi de kapatmis")
        self.assertEqual(result.commands_from_audio, 0)
        self.assertEqual(result.command_source, "VISUAL")

    def test_yuz_yokken_raw_doa_kafayi_ceviremez(self):
        """Kritik mimari karar: Görsel hedef yoksa ve konuşma doğrulanmamışsa raw DOA motora komut veremez."""
        from astro_audio.speech_detector import SpeechVerdict

        speech = SpeechVerdict(is_speech=False, confidence=0.0, harmonicity=0.20,
                               modulation=0.10, rms=0.2)

        result = self._run(speech, faces=[])

        self.assertEqual(result.owner, PrioritySource.IDLE)
        self.assertEqual(result.target_yaw_deg, 0.0)
        self.assertEqual(result.commands_from_audio, 0)

    def test_guven_konusma_olcusunden_gelir_sabit_085_ten_degil(self):
        """Sabit 0.85, kestiricinin kendi guveni olcumde ayirt etmedigi icin konmustu
        (dort akustik kosulda 0.40-0.46). Yerine konusma olcusunun guveni geciyor."""
        from astro_audio.speech_detector import SpeechVerdict

        weak = SpeechVerdict(is_speech=True, confidence=0.52, harmonicity=0.47,
                             modulation=0.22, rms=0.2)
        strong = SpeechVerdict(is_speech=True, confidence=0.95, harmonicity=0.90,
                               modulation=0.90, rms=0.2)

        self.assertLess(self._run(weak, cycles=6).confidence,
                        self._run(strong, cycles=6).confidence,
                        "guven konusma olcusunu izlemiyor -- hala sabit")


class TestCalibrationIsRead(unittest.TestCase):
    """Kalibrasyon dosyasi standalone tarafina da ulasmali.

    `GazeTracker` cıplak `CalibrationConfig()` kuruyordu, yani
    astro_base/config/calibration_params.yaml hic okunmuyordu. Onemi su: dizinin
    fiziksel montaj kaymasi olculdugunde yazilacagi yer `audio.yaw_offset_deg` ve
    o deger standalone'a hic ulasmiyordu -- ROS tarafi ayari alir, bu program
    almazdi, ve ikisi ayni beyni calistirdigi iddiasi orada sessizce bozulurdu.
    """

    def _config(self, tmpdir, yaw_offset):
        path = Path(tmpdir) / "calibration_params.yaml"
        path.write_text(
            "/**:\n"
            "  ros__parameters:\n"
            "    audio:\n"
            f"      yaw_offset_deg: {yaw_offset}\n"
            "      invert: true\n",
            encoding="utf-8")
        return path

    def test_dosyadaki_ses_kaymasi_kerterize_uygulanir(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tracker = GazeTracker(calibration_path=self._config(tmp, 25.0))

        self.assertAlmostEqual(tracker.calib.audio.yaw_offset_deg, 25.0)
        self.assertAlmostEqual(
            tracker.transformer.raw_audio_doa_to_head_bearing(0.0), -25.0, places=3,
            msg="kayma okundu ama kerterize uygulanmiyor")

    def test_acikca_verilen_kalibrasyon_dosyayi_ezer(self):
        """Testler ve deneyler icin dosyaya dokunmadan ayar verebilmek gerekiyor."""
        from astro_base.gaze.coordinate_frames import AudioCalibration, CalibrationConfig

        explicit = CalibrationConfig()
        explicit.audio = AudioCalibration(yaw_offset_deg=7.0, invert=True)

        tracker = GazeTracker(calibration=explicit)

        self.assertAlmostEqual(tracker.calib.audio.yaw_offset_deg, 7.0)

    def test_dosya_yoksa_program_varsayilanlarla_calisir(self):
        """Masaustunde depo duzeni farkli olabilir; eksik dosya durdurmamali."""
        tracker = GazeTracker(calibration_path=Path("/yok/boyle/bir/dosya.yaml"))

        self.assertIsNotNone(tracker.calib)
        self.assertAlmostEqual(tracker.calib.head.max_angle_deg, 85.0)


class TestRobotDoesNotChaseItsOwnVoice(unittest.TestCase):
    """Robot konusurken kendi sesi kafayi cevirmemeli.

    `process_raw_doa` `is_robot_speaking` parametresini zaten kabul ediyor ve
    guveni 0.15 ile carpiyor; standalone bu parametreyi hic gecirmiyordu.
    Hoparlor mikrofonun yaninda oldugu icin robot konustugu anda gucla bir
    kerteriz uretilir ve o kerteriz her zaman hoparlorun yonunu gosterir.
    """

    def _run(self, is_robot_speaking):
        from astro_audio.speech_detector import SpeechVerdict

        speech = SpeechVerdict(is_speech=True, confidence=0.85, harmonicity=0.60,
                               modulation=0.85, rms=0.2)
        tracker = GazeTracker()
        result = None
        for i in range(60):
            result = tracker.step(
                faces=[_face_at(0.25)], frame_size=FRAME, doa_deg=-18.0, speech=speech,
                is_robot_speaking=is_robot_speaking,
                measured_head_deg=0.0, timestamp=300.0 + i * 0.02,
            )
        return result

    def test_robot_konusurken_ses_hedefi_ele_geciremez(self):
        result = self._run(is_robot_speaking=True)

        self.assertNotEqual(result.owner, PrioritySource.ACTIVE_SPEAKER,
                            "robot kendi sesine dondu")

    def test_robot_susarken_ayni_ses_hedefi_ele_gecirir(self):
        """Bastirma calisiyor diye ozelligi kapatmis olmayalim."""
        result = self._run(is_robot_speaking=False)

        self.assertEqual(result.owner, PrioritySource.ACTIVE_SPEAKER)


class TestControlledAudioReacquisition(unittest.TestCase):
    """Rigorous acceptance tests for 5-state attention ownership and controlled audio reacquisition.

    1. test_audio_episode_generates_only_one_reacquisition
    2. test_repeated_audio_samples_do_not_change_active_reacquisition_target
    3. test_visual_target_cancels_audio_reacquisition
    4. test_audio_outside_75deg_cannot_reacquire
    5. test_119deg_audio_cannot_reacquire
    6. test_180deg_audio_cannot_reacquire
    7. test_audio_reacquisition_does_not_spin
    8. test_visual_coast_then_audio_reacquisition
    9. test_visual_coast_then_idle
    10. test_visual_target_blocks_audio_reacquisition
    """

    def _speech(self, is_speech=True, confidence=0.85):
        from astro_audio.speech_detector import SpeechVerdict
        return SpeechVerdict(
            is_speech=is_speech,
            confidence=confidence,
            harmonicity=0.80,
            modulation=0.80,
            rms=0.25,
        )

    def test_audio_episode_generates_only_one_reacquisition(self):
        tracker = GazeTracker()
        speech = self._speech()
        result = None
        for i in range(25):
            result = tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=-30.0,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=speech,
            )

        self.assertEqual(tracker.audio_reacquisition_count, 1)
        self.assertEqual(result.commands_from_audio, 0)
        self.assertEqual(result.command_source, "AUDIO_REACQUISITION")
        self.assertTrue(result.audio_reacquisition_active)

    def test_repeated_audio_samples_do_not_change_active_reacquisition_target(self):
        tracker = GazeTracker()
        speech = self._speech()
        # Initialize and trigger reacquisition
        for i in range(5):
            result = tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=-30.0,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=speech,
            )
        self.assertEqual(tracker.audio_reacquisition_count, 1)
        locked_yaw = result.target_yaw_deg

        # Subsequent audio samples with shifting DOAs during ongoing speech
        shifting_doas = [-45.0, -15.0, -50.0, -20.0, -35.0]
        for i, doa in enumerate(shifting_doas):
            res = tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=doa,
                measured_head_deg=0.0,
                timestamp=100.1 + i * 0.02,
                speech=speech,
            )
            self.assertEqual(res.target_yaw_deg, locked_yaw,
                             "repeated audio samples shifted the locked reacquisition target")
            self.assertEqual(tracker.audio_reacquisition_count, 1)

    def test_visual_target_cancels_audio_reacquisition(self):
        tracker = GazeTracker()
        speech = self._speech()
        # Start reacquisition without faces
        for i in range(5):
            tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=-30.0,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=speech,
            )
        self.assertTrue(tracker._audio_reacq_active)
        self.assertEqual(tracker.audio_reacquisition_count, 1)

        # Visual target appears: instant handover
        face = _face_at(0.40, confidence=0.90)
        result = tracker.step(
            faces=[face],
            frame_size=FRAME,
            doa_deg=-30.0,
            measured_head_deg=0.0,
            timestamp=100.15,
            speech=speech,
        )
        self.assertFalse(tracker._audio_reacq_active)
        self.assertEqual(tracker.visual_handover_count, 1)
        self.assertEqual(result.command_source, "VISUAL")

    def test_audio_outside_75deg_cannot_reacquire(self):
        tracker = GazeTracker()
        speech = self._speech()
        # 80 deg DOA -> transformed bearing exceeds [-75°, +75°]
        for i in range(10):
            result = tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=80.0,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=speech,
            )

        self.assertEqual(tracker.audio_reacquisition_count, 0)
        self.assertNotEqual(result.command_source, "AUDIO_REACQUISITION")
        self.assertEqual(result.target_yaw_deg, 0.0)

    def test_119deg_audio_cannot_reacquire(self):
        tracker = GazeTracker()
        speech = self._speech()
        for i in range(10):
            result = tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=119.0,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=speech,
            )

        self.assertEqual(tracker.audio_reacquisition_count, 0)
        self.assertNotEqual(result.command_source, "AUDIO_REACQUISITION")
        self.assertNotEqual(result.target_yaw_deg, 75.0, "119 deg must not be clamped to 75 deg")
        self.assertEqual(result.target_yaw_deg, 0.0)

    def test_180deg_audio_cannot_reacquire(self):
        tracker = GazeTracker()
        speech = self._speech()
        for i in range(10):
            result = tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=180.0,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=speech,
            )

        self.assertEqual(tracker.audio_reacquisition_count, 0)
        self.assertNotEqual(result.command_source, "AUDIO_REACQUISITION")
        self.assertEqual(result.target_yaw_deg, 0.0)

    def test_audio_reacquisition_does_not_spin(self):
        tracker = GazeTracker()
        speech = self._speech()
        # Alternating left and right DOAs during one continuous speech episode
        targets = []
        for i in range(30):
            doa = -35.0 if (i % 4 < 2) else 35.0
            result = tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=doa,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=speech,
            )
            if result.command_source == "AUDIO_REACQUISITION":
                targets.append(result.target_yaw_deg)

        self.assertEqual(tracker.audio_reacquisition_count, 1)
        # All recorded reacquisition targets must be identical (no flipping / spinning)
        self.assertTrue(all(t == targets[0] for t in targets),
                        f"target yaw flipped during speech episode: {targets}")

    def test_visual_coast_then_audio_reacquisition(self):
        tracker = GazeTracker()
        speech = self._speech()
        face = _face_at(0.30, confidence=0.85)

        # 1. Lock onto visual target
        for i in range(10):
            tracker.step(
                faces=[face],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=None,
            )

        # 2. Visual target drops; audio speech arrives at t = 100.5s (< 1.0s coast)
        for i in range(5):
            res = tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=-40.0,
                measured_head_deg=0.0,
                timestamp=100.3 + i * 0.02,
                speech=speech,
            )
            self.assertEqual(res.command_source, "VISUAL_COAST")
            self.assertTrue(res.coast_active)
            self.assertEqual(tracker.audio_reacquisition_count, 0)

        # 3. Advance time past coast timeout (1.0s) -> t = 101.5s
        for i in range(5):
            res = tracker.step(
                faces=[],
                frame_size=FRAME,
                doa_deg=-40.0,
                measured_head_deg=0.0,
                timestamp=101.5 + i * 0.02,
                speech=speech,
            )

        self.assertEqual(res.command_source, "AUDIO_REACQUISITION")
        self.assertEqual(tracker.audio_reacquisition_count, 1)

    def test_visual_coast_then_idle(self):
        tracker = GazeTracker()
        face = _face_at(0.30, confidence=0.85)

        # 1. Lock onto visual target
        for i in range(10):
            tracker.step(
                faces=[face],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=None,
            )

        # 2. Visual drops, no speech: during coast (<= 1.0s)
        res_coast = tracker.step(
            faces=[],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=0.0,
            timestamp=100.5,
            speech=None,
        )
        self.assertEqual(res_coast.command_source, "VISUAL_COAST")
        self.assertTrue(res_coast.coast_active)

        # 3. Coast expires (> 1.0s), still no speech: returns to stationary
        res_idle = tracker.step(
            faces=[],
            frame_size=FRAME,
            doa_deg=None,
            measured_head_deg=0.0,
            timestamp=102.0,
            speech=None,
        )
        self.assertEqual(res_idle.command_source, "SAFETY_ZERO")
        self.assertEqual(res_idle.owner, PrioritySource.IDLE)
        self.assertFalse(res_idle.coast_active)

    def test_visual_target_blocks_audio_reacquisition(self):
        tracker = GazeTracker()
        speech = self._speech()
        face = _face_at(0.25, confidence=0.90)

        # Visual target active while loud speech occurs at a different angle
        for i in range(15):
            res = tracker.step(
                faces=[face],
                frame_size=FRAME,
                doa_deg=-60.0,
                measured_head_deg=0.0,
                timestamp=100.0 + i * 0.02,
                speech=speech,
            )

        self.assertEqual(res.command_source, "VISUAL")
        self.assertEqual(tracker.audio_reacquisition_count, 0)
        self.assertEqual(res.commands_from_audio, 0)
        self.assertFalse(res.audio_reacquisition_active)


class TestForensicTelemetry(unittest.TestCase):
    """Verifies that forensic telemetry captures complete causal chains without changing behavior."""

    def test_forensic_telemetry_fields_and_causal_chain(self):
        import io
        from unittest.mock import patch

        tracker = GazeTracker()
        face = Detection(x=200, y=180, w=100, h=100, confidence=0.88, detector_source="yunet")

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            result = tracker.step(
                faces=[face],
                frame_size=FRAME,
                doa_deg=None,
                measured_head_deg=0.0,
                timestamp=100.0,
            )
            output = mock_stdout.getvalue()

        # 1. Verify forensic payload presence
        self.assertIsNotNone(result.forensic)
        forensic = result.forensic

        # 2. Verify visual detection telemetry (8 fields)
        self.assertEqual(len(forensic["detections"]), 1)
        det = forensic["detections"][0]
        self.assertIn("frame_id", det)
        self.assertIn("timestamp", det)
        self.assertIn("bbox", det)
        self.assertIn("bearing", det)
        self.assertIn("confidence", det)
        self.assertIn("detector_source", det)
        self.assertIn("track_id", det)
        self.assertIn("track_state", det)
        self.assertEqual(det["detector_source"], "yunet")
        self.assertEqual(det["bbox"], [200, 180, 100, 100])
        self.assertEqual(det["confidence"], 0.88)

        # 3. Verify target manager telemetry (3 fields)
        tm = forensic["target_manager"]
        self.assertIn("previous_active_target", tm)
        self.assertIn("new_active_target", tm)
        self.assertIn("reason", tm)

        # 4. Verify attention decision telemetry (4 fields)
        att = forensic["attention"]
        self.assertIn("old_owner", att)
        self.assertIn("new_owner", att)
        self.assertIn("reason", att)
        self.assertIn("preempted_target", att)

        # 5. Verify head command telemetry (5 fields)
        cmd = forensic["command"]
        self.assertIn("previous_target_yaw", cmd)
        self.assertIn("new_target_yaw", cmd)
        self.assertIn("command_source", cmd)
        self.assertIn("target_source", cmd)
        self.assertIn("reason", cmd)

        # 6. Verify causal chain output when delta_yaw > 3.0 degrees
        if forensic["delta_yaw"] > 3.0:
            self.assertIn("DETECTION → TRACK → TARGET → ATTENTION → COMMAND", output)
            self.assertIn("[FORENSIC CAUSAL CHAIN]", output)
            self.assertIn("DETECTION:", output)
            self.assertIn("TRACK    :", output)
            self.assertIn("TARGET   :", output)
            self.assertIn("ATTENTION:", output)
            self.assertIn("COMMAND  :", output)


if __name__ == "__main__":
    unittest.main()
