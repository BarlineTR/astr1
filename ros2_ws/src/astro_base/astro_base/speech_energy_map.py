#!/usr/bin/env python3
"""Where is the talking coming from?

The ReSpeaker array sits at an angle on top of the dome, so its plane is not horizontal
and its zero mark is not the head's forward axis. A planar bearing estimate taken from a
tilted array is systematically skewed and, in a reverberant room, jumps around sample to
sample. Believing any single bearing is therefore hopeless.

What survives that is energy over time. A person talking pours energy into one direction
for seconds on end; a door slam, a chair scrape or a reflection puts a little into a
scattered set of directions and then stops. So instead of picking a bearing, this module
accumulates speech energy per direction and reports where the talking actually is.

Two pieces, each with one job:

  SpeechFrameGate  decides whether a frame is sustained speech at all
  SpeechEnergyMap  accumulates accepted frames per direction and names the busiest one

Neither knows anything about ROS, so both can be exercised directly.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple


def _wrap_deg(angle: float) -> float:
    """Folds an angle into (-180, +180]."""
    return (angle + 180.0) % 360.0 - 180.0


class SpeechFrameGate:
    """Passes sustained speech and blocks impulsive noise.

    The distinction that matters is shape in time, not loudness: a slam is louder than a
    voice but lasts a moment and collapses, while speech carries on and keeps fluctuating.
    So a frame counts only once its burst has run for `min_duration_s` without a gap, and
    only while its energy is still within `collapse_ratio` of that burst's peak. A slam
    fails the first test outright; a slam long enough to survive it fails the second as
    its tail decays.

    Frames during the onset window are dropped rather than buffered and released later.
    Losing the first ~150 ms costs nothing downstream, because the map integrates over
    seconds, and it keeps this class free of retroactive bookkeeping.
    """

    def __init__(
        self,
        min_duration_s: float = 0.15,
        min_frames: int = 3,
        max_gap_s: float = 0.35,
        collapse_ratio: float = 8.0,
    ):
        self.min_duration_s = float(min_duration_s)
        self.min_frames = int(min_frames)
        self.max_gap_s = float(max_gap_s)
        self.collapse_ratio = float(collapse_ratio)

        self._burst_start: Optional[float] = None
        self._last_time: Optional[float] = None
        self._frames = 0
        self._peak_rms = 0.0

    def accept(self, now: float, rms: float) -> bool:
        """True when this frame is part of an utterance rather than a bang."""
        now = float(now)
        rms = float(rms)

        if self._last_time is None or (now - self._last_time) > self.max_gap_s:
            self._burst_start = now
            self._frames = 0
            self._peak_rms = 0.0

        self._last_time = now
        self._frames += 1
        self._peak_rms = max(self._peak_rms, rms)

        if self._frames < self.min_frames:
            return False
        if (now - (self._burst_start or now)) < self.min_duration_s:
            return False

        # Still-collapsing tail of an impulse: the burst peaked far above where it is now.
        if self._peak_rms > 0.0 and rms * self.collapse_ratio < self._peak_rms:
            return False

        return True

    def reset(self) -> None:
        self._burst_start = None
        self._last_time = None
        self._frames = 0
        self._peak_rms = 0.0


class SpeechEnergyMap:
    """Accumulates speech energy per direction and names the busiest one.

    Directions are bucketed only so that samples scattered by reverberation land
    together; the answer is the energy-weighted centroid across the winning bucket and
    its neighbours, so the reported bearing is far finer than the bucket width. Buckets
    decay with a half life, which is what lets a new talker take over from an old one and
    keeps a burst of noise from mattering ten seconds later.

    peak() returns None rather than a guess when the map cannot honestly separate a
    winner -- too little energy anywhere, or two directions equally busy. Declining is
    the right answer there: a head that turns on a coin toss is the twitching this whole
    approach exists to remove.
    """

    def __init__(
        self,
        bin_width_deg: float = 30.0,
        decay_half_life_s: float = 4.0,
        peak_dominance: float = 1.6,
        min_peak_energy: float = 4000.0,
        neighbour_spread: float = 0.35,
    ):
        self.bin_width_deg = float(bin_width_deg)
        self.decay_half_life_s = float(decay_half_life_s)
        self.peak_dominance = float(peak_dominance)
        self.min_peak_energy = float(min_peak_energy)
        self.neighbour_spread = float(neighbour_spread)

        self.bin_count = max(4, int(round(360.0 / self.bin_width_deg)))
        self._energy: List[float] = [0.0] * self.bin_count
        # Alongside the energy, each bucket keeps the energy-weighted direction vector of
        # the bearings that actually landed in it. Rounding a sample to its bucket centre
        # would throw away exactly the precision the centroid is supposed to recover, and
        # would peg every answer to a multiple of the bucket width.
        self._sin: List[float] = [0.0] * self.bin_count
        self._cos: List[float] = [0.0] * self.bin_count
        self._last_decay_t: Optional[float] = None

    # ----- accumulation -------------------------------------------------------

    def _bin_of(self, bearing_deg: float) -> int:
        return int((_wrap_deg(bearing_deg) + 180.0) // self.bin_width_deg) % self.bin_count

    def _bin_centre(self, index: int) -> float:
        return _wrap_deg(-180.0 + (index + 0.5) * self.bin_width_deg)

    def _decay_to(self, now: float) -> None:
        if self._last_decay_t is None:
            self._last_decay_t = now
            return
        dt = now - self._last_decay_t
        if dt <= 0.0:
            return
        self._last_decay_t = now
        factor = 0.5 ** (dt / self.decay_half_life_s)
        self._energy = [e * factor for e in self._energy]
        self._sin = [v * factor for v in self._sin]
        self._cos = [v * factor for v in self._cos]

    def add(self, now: float, bearing_deg: float, weight: float) -> None:
        """Pour one accepted speech frame into the direction it came from.

        A share of the weight goes to each neighbouring bucket so that a talker standing
        on a bucket boundary stays one source instead of splitting into two rivals that
        then cancel each other out in peak().
        """
        self._decay_to(float(now))

        weight = float(weight)
        if weight <= 0.0:
            return

        bearing = _wrap_deg(float(bearing_deg))
        rad = math.radians(bearing)
        sin_v, cos_v = math.sin(rad), math.cos(rad)

        index = self._bin_of(bearing)
        side = weight * self.neighbour_spread
        for i, w in (
            (index, weight),
            ((index - 1) % self.bin_count, side),
            ((index + 1) % self.bin_count, side),
        ):
            self._energy[i] += w
            self._sin[i] += w * sin_v
            self._cos[i] += w * cos_v

    def clear(self) -> None:
        self._energy = [0.0] * self.bin_count
        self._sin = [0.0] * self.bin_count
        self._cos = [0.0] * self.bin_count
        self._last_decay_t = None

    # ----- readout ------------------------------------------------------------

    def snapshot(self, now: float) -> List[Tuple[float, float]]:
        """(bearing, energy) per bucket, for logging and telemetry."""
        self._decay_to(float(now))
        return [(self._bin_centre(i), self._energy[i]) for i in range(self.bin_count)]

    def peak(self, now: float) -> Optional[float]:
        """The busiest direction in degrees, or None when there is no clear winner."""
        self._decay_to(float(now))

        top = max(range(self.bin_count), key=lambda i: self._energy[i])
        top_energy = self._energy[top]
        if top_energy < self.min_peak_energy:
            return None

        # The winner's own neighbours carry its spill-over, so a rival only counts if it
        # is somewhere else entirely.
        rival = 0.0
        for i in range(self.bin_count):
            if min((i - top) % self.bin_count, (top - i) % self.bin_count) <= 1:
                continue
            rival = max(rival, self._energy[i])

        if rival * self.peak_dominance > top_energy:
            return None

        return self._centroid(top)

    def _centroid(self, top: int) -> float:
        """Energy-weighted circular mean of the bearings in the winning neighbourhood."""
        sin_sum = sum(self._sin[(top + o) % self.bin_count] for o in (-1, 0, 1))
        cos_sum = sum(self._cos[(top + o) % self.bin_count] for o in (-1, 0, 1))

        if sin_sum == 0.0 and cos_sum == 0.0:
            return self._bin_centre(top)
        return _wrap_deg(math.degrees(math.atan2(sin_sum, cos_sum)))
