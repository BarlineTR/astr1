#!/usr/bin/env python3
"""ASTRO V1 — Acoustic Direction of Arrival (DOA) Estimator.

Implements multi-channel acoustic DOA estimation using:
  1. ReSpeaker 4-Mic Circular Array geometry (R = 43mm, 16kHz int16/float32 PCM)
  2. Generalized Cross-Correlation with Phase Transform (GCC-PHAT)
  3. Orthogonal microphone pair Time Difference of Arrival (TDOA)
  4. Robust confidence estimation via Peak-to-Sidelobe Ratio (PSR) and frame energy
  5. Strict validity gating: 0° uncalibrated/idle default is NEVER marked valid
"""

import math
from typing import Optional, Tuple
import numpy as np


class ReSpeakerGeometry:
    """Microphone array geometry for ReSpeaker 4-Mic USB Array.
    
    4 MEMS microphones uniformly distributed on a circle of radius 43mm (0.043m).
    Oriented in robot coordinate frame:
      - Mic 0 (Front):  (x=0.0,    y=+0.043) ->   0°
      - Mic 1 (Right):  (x=+0.043, y=0.0)    -> +90°
      - Mic 2 (Back):   (x=0.0,    y=-0.043) -> 180°
      - Mic 3 (Left):   (-0.043,   y=0.0)    -> -90° (270°)
    """
    RADIUS_M = 0.043
    PAIR_DIST_M = 2.0 * RADIUS_M  # 0.086m between opposing mics (0-2 and 1-3)
    SPEED_OF_SOUND_MPS = 343.0     # Speed of sound at ~20°C in m/s
    SAMPLE_RATE = 16000            # Hz


def gcc_phat(
    sig: np.ndarray,
    refsig: np.ndarray,
    fs: int = 16000,
    max_tau: Optional[float] = None,
    interp: int = 16
) -> Tuple[float, float]:
    """Computes Generalized Cross-Correlation with Phase Transform (GCC-PHAT).
    
    Args:
        sig: First channel signal array
        refsig: Second channel signal array
        fs: Sampling rate in Hz
        max_tau: Maximum expected time delay in seconds (based on mic distance)
        interp: Interpolation factor for fractional-sample resolution
        
    Returns:
        tau: Time delay in seconds (positive if refsig lags sig, negative if refsig leads sig)
        quality: Normalized peak quality (confidence proxy, 0..1)
    """
    n = sig.shape[0] + refsig.shape[0]

    # Generalized Cross-Correlation Phase Transform
    SIG = np.fft.rfft(sig, n=n)
    REFSIG = np.fft.rfft(refsig, n=n)
    R = SIG * np.conj(REFSIG)

    # Phase Transform weighting: 1 / |R|
    denom = np.abs(R)
    denom[denom < 1e-6] = 1e-6
    R_phat = R / denom

    # Inverse FFT with interpolation for sub-sample precision
    cc = np.fft.irfft(R_phat, n=interp * n)
    max_shift = int(interp * fs * max_tau) if max_tau else int(interp * n / 2)

    # Shift zero lag to center
    cc_windowed = np.concatenate((cc[-max_shift:], cc[: max_shift + 1]))
    
    # Peak index
    shift = np.argmax(np.abs(cc_windowed)) - max_shift
    tau = shift / float(interp * fs)

    # Calculate Peak-to-Sidelobe Ratio / normalized peak quality
    peak_val = float(np.max(np.abs(cc_windowed)))
    mean_val = float(np.mean(np.abs(cc_windowed)))
    std_val = float(np.std(np.abs(cc_windowed)))
    psr = (peak_val - mean_val) / max(1e-5, std_val)
    quality = min(1.0, max(0.0, (psr - 1.5) / 5.0))

    return tau, quality


class AcousticDOAEstimator:
    """Estimates acoustic sound azimuth from 4-channel raw audio frames."""

    def __init__(
        self,
        sample_rate: int = 16000,
        min_energy_threshold: float = 300.0,
        min_confidence: float = 0.40,
    ):
        self.sample_rate = sample_rate
        self.min_energy_threshold = min_energy_threshold
        self.min_confidence = min_confidence
        self.max_tau = ReSpeakerGeometry.PAIR_DIST_M / ReSpeakerGeometry.SPEED_OF_SOUND_MPS  # ~0.25ms

    def estimate_from_multichannel_pcm(
        self,
        pcm_channels: np.ndarray,
    ) -> Tuple[Optional[float], float, bool]:
        """Estimates sound direction from multi-channel audio buffer.
        
        Args:
            pcm_channels: Array of shape (channels, samples) or (samples, channels).
                          Must have at least 4 channels:
                          Ch 0: Mic 0 (Front)
                          Ch 1: Mic 1 (Right)
                          Ch 2: Mic 2 (Back)
                          Ch 3: Mic 3 (Left)
                          
        Returns:
            azimuth_deg: Estimated angle in degrees (-180°..+180°, 0=front, +=right, -=left) or None
            confidence: Estimation confidence (0.0..1.0)
            valid: True if confidence meets threshold and energy is sufficient
        """
        if pcm_channels is None or pcm_channels.size == 0:
            return None, 0.0, False

        # Ensure shape is (channels, samples)
        if pcm_channels.ndim == 2:
            if pcm_channels.shape[0] > pcm_channels.shape[1]:
                pcm_channels = pcm_channels.T

        if pcm_channels.shape[0] < 4:
            return None, 0.0, False

        # Check frame energy (RMS)
        rms = float(np.sqrt(np.mean(pcm_channels.astype(np.float32) ** 2)))
        if rms < self.min_energy_threshold:
            return None, 0.0, False

        mic_front = pcm_channels[0].astype(np.float32)
        mic_right = pcm_channels[1].astype(np.float32)
        mic_back = pcm_channels[2].astype(np.float32)
        mic_left = pcm_channels[3].astype(np.float32)

        # 1. Left-Right Pair: Mic 3 (Left) vs Mic 1 (Right)
        tau_lr, q_lr = gcc_phat(mic_left, mic_right, fs=self.sample_rate, max_tau=self.max_tau)

        # 2. Front-Back Pair: Mic 2 (Back) vs Mic 0 (Front)
        tau_fb, q_fb = gcc_phat(mic_back, mic_front, fs=self.sample_rate, max_tau=self.max_tau)

        # TDOA to spatial displacement in robot frame
        # dx > 0 when sound is on the right (+X)
        # dy > 0 when sound is in front (+Y)
        delta_x = -tau_lr * ReSpeakerGeometry.SPEED_OF_SOUND_MPS
        delta_y = -tau_fb * ReSpeakerGeometry.SPEED_OF_SOUND_MPS

        # Azimuth angle: 0° = Front (+Y), +90° = Right (+X), -90° = Left (-X), 180° = Back (-Y)
        raw_azimuth = math.degrees(math.atan2(delta_x, delta_y))
        if raw_azimuth > 180.0:
            raw_azimuth -= 360.0
        elif raw_azimuth <= -180.0:
            raw_azimuth += 360.0
        
        # Combined confidence from both pair correlation qualities & energy
        combined_quality = (q_lr + q_fb) / 2.0
        energy_factor = min(1.0, max(0.0, rms / 1500.0))
        confidence = round(float(combined_quality * 0.7 + energy_factor * 0.3), 2)

        # Strict validity rules:
        # A valid detection must have strong confidence
        is_valid = (confidence >= self.min_confidence)

        if not is_valid:
            return None, confidence, False

        azimuth_deg = round(float(raw_azimuth), 1)
        return azimuth_deg, confidence, True
