#!/usr/bin/env python3
"""Tests for the camera and microphone sources.

Hardware is optional on purpose: this program has to be usable at a desk with no
Arduino and no ReSpeaker, otherwise it cannot be used to answer the question it
exists for. A missing device degrades the program, it does not stop it.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core_path  # noqa: F401
from sources import (  # noqa: E402
    BLOCK_SAMPLES,
    DUPLICATE_BLOCKS_TO_LATCH,
    MIN_RMS,
    SAMPLE_RATE,
    AudioSource,
    CameraSource,
    to_detections,
)
from astro_audio.doa_estimator import (  # noqa: E402
    AcousticDOAEstimator,
    ReSpeakerGeometry,
)


class _FakeCapture:
    def __init__(self, frames=None, opened=True):
        self._frames = list(frames or [])
        self._opened = opened
        self.released = False
        self.props = {}

    def isOpened(self):
        return self._opened

    def set(self, prop, value):
        self.props[prop] = value
        return True

    def get(self, prop):
        return self.props.get(prop, 0.0)

    def read(self):
        if not self._frames:
            return False, None
        return True, self._frames.pop(0)

    def release(self):
        self.released = True


class TestDetectionConversion(unittest.TestCase):
    def test_detector_tuples_become_detections(self):
        found = to_detections([(10, 20, 30, 40, 0.91), (50, 60, 70, 80, 0.5)])

        self.assertEqual([(d.x, d.y, d.w, d.h) for d in found], [(10, 20, 30, 40), (50, 60, 70, 80)])
        self.assertAlmostEqual(found[0].confidence, 0.91)

    def test_nothing_found_is_an_empty_list_not_a_failure(self):
        self.assertEqual(to_detections([]), [])


class TestCameraSource(unittest.TestCase):
    def test_a_frame_is_handed_back_as_read(self):
        frame = np.zeros((480, 640, 3), np.uint8)
        camera = CameraSource(capture=_FakeCapture([frame]))

        ok, out = camera.read()

        self.assertTrue(ok)
        self.assertEqual(out.shape, (480, 640, 3))

    def test_a_camera_that_will_not_open_is_reported_not_raised(self):
        camera = CameraSource(capture=_FakeCapture(opened=False))

        self.assertFalse(camera.available)
        self.assertEqual(camera.read(), (False, None))

    def test_detection_on_an_empty_frame_finds_nobody(self):
        camera = CameraSource(capture=_FakeCapture())

        self.assertEqual(camera.detect(np.zeros((480, 640, 3), np.uint8)), [])

    def test_closing_releases_the_device(self):
        capture = _FakeCapture()
        CameraSource(capture=capture).close()

        self.assertTrue(capture.released)


class TestAudioSource(unittest.TestCase):
    def test_without_a_microphone_there_is_simply_no_bearing(self):
        audio = AudioSource(stream_factory=lambda **_: (_ for _ in ()).throw(RuntimeError("no device")))

        audio.start()

        self.assertFalse(audio.available)
        self.assertIsNone(audio.latest_doa_deg(now=0.0))

    def test_a_bearing_is_offered_while_it_is_fresh(self):
        audio = AudioSource()
        audio._publish(doa_deg=42.0, timestamp=10.0)

        self.assertEqual(audio.latest_doa_deg(now=10.1), 42.0)

    def test_a_stale_bearing_is_withheld_rather_than_reused(self):
        """A DOA from a second ago says nothing about where the talker is now."""
        audio = AudioSource(max_age_s=0.5)
        audio._publish(doa_deg=42.0, timestamp=10.0)

        self.assertIsNone(audio.latest_doa_deg(now=11.0))

    def test_a_frame_of_silence_produces_no_bearing(self):
        audio = AudioSource()

        audio.process_block(np.zeros((512, 4), np.float32), timestamp=10.0)

        self.assertIsNone(audio.latest_doa_deg(now=10.0))

    def test_fewer_than_four_channels_cannot_be_localised(self):
        audio = AudioSource()

        audio.process_block(np.random.rand(512, 2).astype(np.float32) * 1000, timestamp=10.0)

        self.assertIsNone(audio.latest_doa_deg(now=10.0))


class _FakeEstimator:
    """Stands in for the GCC-PHAT estimator and records whether it was reached."""

    def __init__(self):
        self.calls = 0

    def estimate_from_multichannel_pcm(self, channels):
        self.calls += 1
        return 30.0, 0.9, True


def _block(amplitude, channels=4, samples=BLOCK_SAMPLES):
    """A block on the float32 scale the stream actually delivers: [-1.0, +1.0]."""
    rng = np.random.default_rng(1)
    return (rng.standard_normal((samples, channels)) * amplitude).astype(np.float32)


def _detached_source():
    """An AudioSource without opening a microphone."""
    import threading
    src = AudioSource.__new__(AudioSource)
    src._lock = threading.Lock()
    src._doa = None
    src._stamp = 0.0
    src.max_age_s = 0.5
    src._estimator = _FakeEstimator()
    src._array_dead = False
    src._duplicate_blocks = 0
    src.available = True
    src.error = None
    return src


def _plane_wave_array(azimuth_deg, amplitude=0.15, samples=BLOCK_SAMPLES):
    """Four channels as a real ReSpeaker would deliver them, on the float32 scale.

    One noise burst reaching four capsules on a 43mm circle, each delayed by its own
    distance to the source. This is the input the estimator is built for, so it is the
    input that proves whether the plumbing in front of it is right.
    """
    radius = ReSpeakerGeometry.MIC_RADIUS_M if hasattr(ReSpeakerGeometry, "MIC_RADIUS_M") else 0.043
    speed = ReSpeakerGeometry.SPEED_OF_SOUND_MPS
    rng = np.random.default_rng(7)
    burst = (rng.standard_normal(samples) * amplitude).astype(np.float32)

    freqs = np.fft.rfftfreq(samples, 1.0 / SAMPLE_RATE)
    spectrum = np.fft.rfft(burst)
    heading = np.array([np.sin(np.radians(azimuth_deg)), np.cos(np.radians(azimuth_deg))])
    positions = [(0.0, radius), (radius, 0.0), (0.0, -radius), (-radius, 0.0)]

    channels = [
        np.fft.irfft(spectrum * np.exp(-2j * np.pi * freqs * (-np.dot(p, heading) / speed)),
                     samples).astype(np.float32)
        for p in positions
    ]
    return np.stack(channels, axis=1)   # (samples, channels), as the stream delivers


def _real_estimator_source():
    """A detached source wired to the actual GCC-PHAT estimator."""
    src = _detached_source()
    src._estimator = AcousticDOAEstimator(sample_rate=SAMPLE_RATE)
    return src


class TestAudioEnergyGate(unittest.TestCase):
    """The gate that decides whether a block is worth localising.

    It exists because GCC-PHAT will happily return a bearing for room noise. But it
    has to be expressed on the same scale as the samples, and it was not: the stream
    is opened with dtype="float32", so samples arrive normalised to [-1.0, +1.0],
    while the threshold was 300.0 — a value from the int16 scale (+-32768). Nothing
    float32 can reach it, so every block was discarded, the estimator was never
    called, and no bearing ever existed for the head to turn toward.
    """

    def test_threshold_is_on_the_float32_scale(self):
        """A clipped full-scale block has an RMS of about 1.0. A threshold above that
        can never admit anything, which is exactly how this failed silently."""
        self.assertLess(MIN_RMS, 1.0,
                        "MIN_RMS is above full scale for float32 — nothing can pass it")

    def test_speech_level_block_reaches_the_estimator(self):
        src = _detached_source()
        src.process_block(_block(0.15), timestamp=1.0)

        self.assertEqual(src._estimator.calls, 1)
        self.assertEqual(src.latest_doa_deg(1.0), 30.0)

    def test_quiet_room_is_still_rejected(self):
        """The gate must keep doing its job: near-silence should not be localised."""
        src = _detached_source()
        src.process_block(_block(0.0005), timestamp=1.0)

        self.assertEqual(src._estimator.calls, 0)
        self.assertIsNone(src.latest_doa_deg(1.0))

    def test_fewer_than_four_channels_is_rejected(self):
        """No array geometry, no bearing — regardless of how loud it is."""
        src = _detached_source()
        src.process_block(_block(0.3, channels=2), timestamp=1.0)

        self.assertEqual(src._estimator.calls, 0)


class TestEstimatorScale(unittest.TestCase):
    """The estimator is shared with the ROS stack, which feeds it int16 PCM.

    Its energy gate (300.0) and its confidence term (rms / 1500.0) are both calibrated
    for that scale. This stream is float32, so a bearing was never returned even from a
    geometrically perfect array: the confidence term is structurally zero there — no
    float32 block can reach rms 1500 — which capped confidence below the 0.40 validity
    bar. Fixing MIN_RMS alone opened the outer gate onto an inner one that was shut for
    the same reason.
    """

    def test_a_real_array_yields_a_bearing(self):
        """The end-to-end claim: sound with genuine geometry produces a direction."""
        src = _real_estimator_source()
        src.process_block(_plane_wave_array(-40.0), timestamp=1.0)

        self.assertIsNotNone(
            src.latest_doa_deg(1.0),
            "a geometrically valid array produced no bearing — the estimator is being "
            "fed on a scale it was not calibrated for")

    def test_opposite_sides_are_told_apart(self):
        """Absolute convention needs the real device; distinguishing sides does not.

        The estimator's zero direction and rotation sense depend on how the hardware
        orders and times its channels, which cannot be settled without a ReSpeaker in
        hand. What can be settled here is that the bearing tracks the source at all.
        """
        left, right = _real_estimator_source(), _real_estimator_source()
        left.process_block(_plane_wave_array(-60.0), timestamp=1.0)
        right.process_block(_plane_wave_array(60.0), timestamp=1.0)

        a, b = left.latest_doa_deg(1.0), right.latest_doa_deg(1.0)
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertGreater(abs(a - b), 30.0,
                           "left and right produced the same bearing")


class TestDuplicatedChannels(unittest.TestCase):
    """Opening four channels is not proof of four microphones.

    With no ReSpeaker attached the request still succeeds against PulseAudio's virtual
    `default` device, which satisfies it by duplicating the laptop's built-in stereo
    pair — channel 2 a copy of 0, channel 3 of 1, correlation 1.0000. Both GCC-PHAT
    delays are then exactly zero and the estimator returns a confident bearing straight
    down one axis, steady enough to pass for a real one. The head would hold a
    direction no sound came from.
    """

    def _duplicated_block(self, amplitude=0.15):
        rng = np.random.default_rng(3)
        left = (rng.standard_normal(BLOCK_SAMPLES) * amplitude).astype(np.float32)
        right = (rng.standard_normal(BLOCK_SAMPLES) * amplitude).astype(np.float32)
        return np.stack([left, right, left, right], axis=1)

    def test_duplicated_channels_produce_no_bearing(self):
        src = _real_estimator_source()
        for i in range(DUPLICATE_BLOCKS_TO_LATCH + 1):
            src.process_block(self._duplicated_block(), timestamp=1.0 + i * 0.01)

        self.assertIsNone(src.latest_doa_deg(1.1))

    def test_the_missing_array_is_reported_not_hidden(self):
        """A silent fallback to vision is fine; claiming the microphone works is not."""
        src = _real_estimator_source()
        for i in range(DUPLICATE_BLOCKS_TO_LATCH):
            src.process_block(self._duplicated_block(), timestamp=1.0 + i * 0.01)

        self.assertFalse(src.available)
        self.assertIsNotNone(src.error)

    def test_one_odd_block_does_not_condemn_the_array(self):
        """The latch needs repetition, so a single freak block cannot disable audio."""
        src = _real_estimator_source()
        src.process_block(self._duplicated_block(), timestamp=1.0)

        self.assertTrue(src.available)
        self.assertFalse(src._array_dead)

    def test_a_genuine_array_is_not_mistaken_for_duplicates(self):
        """The check must not fire on real microphones hearing the same sound."""
        src = _real_estimator_source()
        for i in range(DUPLICATE_BLOCKS_TO_LATCH + 2):
            src.process_block(_plane_wave_array(25.0), timestamp=1.0 + i * 0.01)

        self.assertTrue(src.available)
        self.assertIsNotNone(src.latest_doa_deg(1.0 + 0.01 * (DUPLICATE_BLOCKS_TO_LATCH + 1)))


if __name__ == "__main__":
    unittest.main()
