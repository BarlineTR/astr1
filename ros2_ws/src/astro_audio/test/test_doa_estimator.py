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

    def test_silence_or_ambient_noise_produces_invalid(self):
        """Low energy ambient noise or silence must return valid=False and None azimuth."""
        silence = np.random.normal(0.0, 10.0, (4, 800)).astype(np.float32)  # Low RMS < 50
        azimuth, conf, valid = self.estimator.estimate_from_multichannel_pcm(silence)
        
        self.assertFalse(valid)
        self.assertIsNone(azimuth)


if __name__ == "__main__":
    unittest.main()
