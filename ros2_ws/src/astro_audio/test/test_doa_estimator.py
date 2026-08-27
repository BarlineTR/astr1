#!/usr/bin/env python3
"""Comprehensive Unit Tests for ReSpeaker 4-Mic Acoustic DOA Estimator and Controlled Left/Right Validation."""

import math
import os
import sys
import unittest
import numpy as np

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)

from astro_audio.doa_estimator import AcousticDOAEstimator, ReSpeakerGeometry, gcc_phat


def generate_multichannel_synthetic_sound(
    azimuth_deg: float,
    duration_s: float = 0.05,
    sample_rate: int = 16000,
    seed: int = 42,
) -> np.ndarray:
    """Generates broadband 4-channel audio representing a sound source at given azimuth.
    
    Geometry:
      Mic 0 (Front): (0.0, +R)
      Mic 1 (Right): (+R, 0.0)
      Mic 2 (Back):  (0.0, -R)
      Mic 3 (Left):  (-R, 0.0)
    """
    n_samples = int(duration_s * sample_rate)
    rad = math.radians(azimuth_deg)
    src_dir = np.array([math.sin(rad), math.cos(rad)])
    
    r = ReSpeakerGeometry.RADIUS_M
    mic_pos = np.array([
        [0.0, +r],   # Mic 0: Front
        [+r, 0.0],   # Mic 1: Right
        [0.0, -r],   # Mic 2: Back
        [-r, 0.0],   # Mic 3: Left
    ])
    
    c = ReSpeakerGeometry.SPEED_OF_SOUND_MPS
    delays = -np.dot(mic_pos, src_dir) / c
    delays -= np.min(delays)
    
    np.random.seed(seed)
    base_signal = np.random.normal(0, 1, n_samples * 2)
    channels = np.zeros((4, n_samples), dtype=np.float32)
    for i in range(4):
        shift_samples = delays[i] * sample_rate
        idx = np.arange(n_samples) + shift_samples
        channels[i] = np.interp(idx, np.arange(len(base_signal)), base_signal) * 10000.0
        
    return channels


class TestAcousticDOAEstimator(unittest.TestCase):
    """Tests GCC-PHAT and spatial triangulation across left/right/front/back directions."""

    def setUp(self):
        self.estimator = AcousticDOAEstimator(sample_rate=16000, min_energy_threshold=300.0)

    def test_controlled_right_sound_source(self):
        """Right (+90°) sound source should produce a positive azimuth (+90° ± 5°)."""
        pcm = generate_multichannel_synthetic_sound(azimuth_deg=90.0)
        azimuth, conf, valid = self.estimator.estimate_from_multichannel_pcm(pcm)
        
        self.assertTrue(valid)
        self.assertIsNotNone(azimuth)
        self.assertGreater(azimuth, 0.0)
        self.assertAlmostEqual(azimuth, 90.0, delta=5.0)
        self.assertGreaterEqual(conf, 0.40)

    def test_controlled_left_sound_source(self):
        """Left (-90°) sound source should produce a negative azimuth (-90° ± 5°)."""
        pcm = generate_multichannel_synthetic_sound(azimuth_deg=-90.0)
        azimuth, conf, valid = self.estimator.estimate_from_multichannel_pcm(pcm)
        
        self.assertTrue(valid)
        self.assertIsNotNone(azimuth)
        self.assertLess(azimuth, 0.0)
        self.assertAlmostEqual(azimuth, -90.0, delta=5.0)
        self.assertGreaterEqual(conf, 0.40)

    def test_controlled_front_right_sound_source(self):
        """Front-Right (+45°) sound source should produce positive azimuth (+45° ± 5°)."""
        pcm = generate_multichannel_synthetic_sound(azimuth_deg=45.0)
        azimuth, conf, valid = self.estimator.estimate_from_multichannel_pcm(pcm)
        
        self.assertTrue(valid)
        self.assertIsNotNone(azimuth)
        self.assertAlmostEqual(azimuth, 45.0, delta=5.0)

    def test_controlled_front_left_sound_source(self):
        """Front-Left (-45°) sound source should produce negative azimuth (-45° ± 5°)."""
        pcm = generate_multichannel_synthetic_sound(azimuth_deg=-45.0)
        azimuth, conf, valid = self.estimator.estimate_from_multichannel_pcm(pcm)
        
        self.assertTrue(valid)
        self.assertIsNotNone(azimuth)
        self.assertAlmostEqual(azimuth, -45.0, delta=5.0)

    def test_controlled_front_sound_source(self):
        """Front (0°) sound source should produce azimuth ~0° with high confidence."""
        pcm = generate_multichannel_synthetic_sound(azimuth_deg=0.0)
        azimuth, conf, valid = self.estimator.estimate_from_multichannel_pcm(pcm)
        
        self.assertTrue(valid)
        self.assertIsNotNone(azimuth)
        self.assertAlmostEqual(azimuth, 0.0, delta=5.0)

    def test_spatial_triangulation_multi_angle_series(self):
        """Validates that as sound location shifts (SOL -> ÖN -> SAĞ), estimated azimuth changes accordingly."""
        # 1. Left series (expect negative angles)
        left_angles = [-30.0, -42.0, -38.0]
        left_results = []
        for ang in left_angles:
            pcm = generate_multichannel_synthetic_sound(azimuth_deg=ang, seed=int(abs(ang) * 10))
            az, _, valid = self.estimator.estimate_from_multichannel_pcm(pcm)
            self.assertTrue(valid)
            self.assertLess(az, 0.0)
            self.assertAlmostEqual(az, ang, delta=5.0)
            left_results.append(az)

        # 2. Front series (expect near zero angles)
        front_angles = [-4.0, +2.0, +5.0]
        front_results = []
        for ang in front_angles:
            pcm = generate_multichannel_synthetic_sound(azimuth_deg=ang, seed=int(abs(ang) * 10 + 100))
            az, _, valid = self.estimator.estimate_from_multichannel_pcm(pcm)
            self.assertTrue(valid)
            self.assertAlmostEqual(az, ang, delta=5.0)
            front_results.append(az)

        # 3. Right series (expect positive angles)
        right_angles = [+35.0, +44.0, +39.0]
        right_results = []
        for ang in right_angles:
            pcm = generate_multichannel_synthetic_sound(azimuth_deg=ang, seed=int(abs(ang) * 10 + 200))
            az, _, valid = self.estimator.estimate_from_multichannel_pcm(pcm)
            self.assertTrue(valid)
            self.assertGreater(az, 0.0)
            self.assertAlmostEqual(az, ang, delta=5.0)
            right_results.append(az)

        # Verify distinct positive, near-zero, and negative separation
        self.assertTrue(all(l < -20.0 for l in left_results))
        self.assertTrue(all(-10.0 <= f <= 10.0 for f in front_results))
        self.assertTrue(all(r > 20.0 for r in right_results))


if __name__ == "__main__":
    unittest.main()
