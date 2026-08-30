#!/usr/bin/env python3
"""Tests for the spatial speech-energy map that decides where the head should look.

The microphone array is mounted at an angle on top of the dome, so a single DOA sample
is not trustworthy on its own. Instead of believing any one bearing, sustained speech
energy is accumulated per direction and the head goes to the busiest direction. These
tests pin down what may enter that map and what comes out of it.
"""

import os
import sys
import unittest

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
astro_base_inner = os.path.join(pkg_dir, "astro_base")
for p in (pkg_dir, astro_base_inner):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from astro_base.speech_energy_map import SpeechEnergyMap, SpeechFrameGate
except ImportError:
    from speech_energy_map import SpeechEnergyMap, SpeechFrameGate


FRAME_DT = 0.05  # the head tracker runs its DOA path at about 20 Hz


class TestSpeechFrameGate(unittest.TestCase):
    """Only sustained speech may reach the map. A door slam is loud but momentary."""

    def test_a_single_loud_bang_never_gets_through(self):
        gate = SpeechFrameGate()
        self.assertFalse(
            gate.accept(1000.0, 25000.0),
            "Tek karelik bir darbe konusma degildir; haritaya girmemeli.",
        )

    def test_a_slam_with_its_reverberation_tail_is_rejected(self):
        """A slam is a sharp attack followed by a collapse. Speech is not."""
        gate = SpeechFrameGate()
        t = 1000.0
        accepted = []
        for rms in (24000.0, 9000.0, 2600.0, 700.0, 190.0):
            accepted.append(gate.accept(t, rms))
            t += FRAME_DT

        self.assertNotIn(
            True,
            accepted,
            f"Kapi carpmasinin sonumlenen kuyrugu kabul edildi: {accepted}. "
            "Keskin atak + cokme darbenin imzasidir.",
        )

    def test_sustained_speech_gets_through_after_the_onset(self):
        gate = SpeechFrameGate()
        t = 1000.0
        accepted = []
        for rms in (2100.0, 2600.0, 2300.0, 2800.0, 2400.0, 2700.0, 2500.0, 2900.0):
            accepted.append(gate.accept(t, rms))
            t += FRAME_DT

        self.assertTrue(
            any(accepted),
            "Surekli konusma hicbir zaman kabul edilmedi.",
        )
        # The onset window is min_duration_s (0.15 s), so at 20 Hz the first four frames
        # are spent proving the burst is not a bang; everything after must flow.
        self.assertTrue(
            all(accepted[4:]),
            f"Konusma basladiktan sonra kareler duzenli akmali: {accepted}",
        )

    def test_a_pause_restarts_the_onset_requirement(self):
        """After a gap the next burst has to prove itself again, so an isolated bang
        following a conversation cannot ride in on the previous streak."""
        gate = SpeechFrameGate()
        t = 1000.0
        for _ in range(10):
            gate.accept(t, 2500.0)
            t += FRAME_DT

        t += 3.0  # silence
        self.assertFalse(
            gate.accept(t, 26000.0),
            "Sessizlikten sonraki ilk yuksek kare yine tek darbe olabilir; gecmemeli.",
        )


class TestSpeechEnergyMap(unittest.TestCase):
    """The map answers one question: which direction is the talking coming from?"""

    def _pour(self, emap, bearing, rms, frames, t0=1000.0, dt=FRAME_DT):
        t = t0
        for _ in range(frames):
            emap.add(t, bearing, rms)
            t += dt
        return t

    def test_sustained_speech_from_one_direction_wins(self):
        emap = SpeechEnergyMap()
        t = self._pour(emap, 60.0, 2500.0, 40)

        peak = emap.peak(t)
        self.assertIsNotNone(peak, "Tek ve net bir kaynak varken harita karar vermeli.")
        self.assertAlmostEqual(
            peak,
            60.0,
            delta=6.0,
            msg=f"Tepe {peak} derece cikti, kaynak 60 derecede.",
        )

    def test_peak_resolves_finer_than_the_bin_width(self):
        """Binning is an implementation detail, not the output resolution: the answer is
        the energy-weighted centroid, so a talker at 47 deg must not be reported at 45."""
        emap = SpeechEnergyMap(bin_width_deg=30.0)
        t = self._pour(emap, 47.0, 2500.0, 40)

        peak = emap.peak(t)
        self.assertAlmostEqual(
            peak,
            47.0,
            delta=6.0,
            msg=f"Tepe {peak} derece; kova genisligine yuvarlanmis olabilir.",
        )

    def test_a_source_on_a_bin_edge_is_not_split_in_two(self):
        emap = SpeechEnergyMap(bin_width_deg=30.0)
        t = self._pour(emap, 15.0, 2500.0, 40)

        peak = emap.peak(t)
        self.assertIsNotNone(
            peak,
            "Kova sinirindaki kaynak iki kovaya bolununce hicbiri baskin cikamiyor.",
        )
        self.assertAlmostEqual(peak, 15.0, delta=6.0, msg=f"Tepe {peak} derece.")

    def test_wrap_around_is_handled_at_the_180_seam(self):
        """A talker directly behind lands on +180/-180, which must be one source."""
        emap = SpeechEnergyMap(bin_width_deg=30.0)
        t = 1000.0
        for i in range(40):
            emap.add(t, 178.0 if i % 2 else -178.0, 2500.0)
            t += FRAME_DT

        peak = emap.peak(t)
        self.assertIsNotNone(peak, "Arkadaki kaynak dikiste ikiye bolundu.")
        self.assertLessEqual(
            min(abs(peak - 180.0), abs(peak + 180.0)),
            8.0,
            f"Tepe {peak} derece; arkadaki kaynak +-180 civarinda olmali.",
        )

    def test_the_persistent_talker_beats_a_brief_louder_burst(self):
        emap = SpeechEnergyMap()
        t = self._pour(emap, -40.0, 2200.0, 60)
        t = self._pour(emap, 120.0, 9000.0, 4, t0=t)

        peak = emap.peak(t)
        self.assertAlmostEqual(
            peak,
            -40.0,
            delta=10.0,
            msg=f"Tepe {peak} derece; kisa suren gurultu israrli konusmaciyi yendi.",
        )

    def test_energy_decays_so_a_new_talker_can_take_over(self):
        emap = SpeechEnergyMap(decay_half_life_s=4.0)
        t = self._pour(emap, -40.0, 2500.0, 60)
        t += 20.0  # long silence: the old talker's energy must fade away
        t = self._pour(emap, 120.0, 2500.0, 40, t0=t)

        peak = emap.peak(t)
        self.assertAlmostEqual(
            peak,
            120.0,
            delta=10.0,
            msg=f"Tepe {peak} derece; eski konusmacinin enerjisi sonmemis.",
        )

    def test_two_equally_busy_directions_produce_no_decision(self):
        """Moving the head on a coin toss looks like the twitching the operator reported,
        so an ambiguous map must simply decline to answer."""
        emap = SpeechEnergyMap()
        t = 1000.0
        for _ in range(40):
            emap.add(t, -90.0, 2500.0)
            emap.add(t, 90.0, 2500.0)
            t += FRAME_DT

        self.assertIsNone(
            emap.peak(t),
            "Iki yon esit yogunlukta iken harita bir taraf secmemeli.",
        )

    def test_energy_smeared_across_the_room_produces_no_decision(self):
        """The field logs show a tilted array reporting -88, -161, -3, -135 and +45 inside
        300 ms. Every direction is then equally busy, so no direction is worth turning to,
        even though plenty of energy has arrived in total."""
        emap = SpeechEnergyMap()
        t = 1000.0
        for doa in (12.0, -160.0, 88.0, -45.0, 175.0, 44.0, -100.0, 130.0,
                    20.0, -60.0, 95.0, -120.0, 160.0, 60.0):
            emap.add(t, doa, 3000.0)
            t += FRAME_DT

        self.assertIsNone(
            emap.peak(t),
            f"Enerji tum odaya yayilmisken harita {emap.peak(t)} derece dedi; "
            "yogunlasma yok, secim de olmamali.",
        )

    def test_an_almost_empty_map_produces_no_decision(self):
        emap = SpeechEnergyMap()
        t = 1000.0
        emap.add(t, 60.0, 40.0)

        self.assertIsNone(
            emap.peak(t + FRAME_DT),
            "Tek ve cok zayif bir ornek kafayi hareket ettirmemeli.",
        )

    def test_clear_empties_the_map(self):
        emap = SpeechEnergyMap()
        t = self._pour(emap, 60.0, 2500.0, 40)
        emap.clear()
        self.assertIsNone(emap.peak(t), "clear() sonrasi harita bos olmali.")


if __name__ == "__main__":
    unittest.main()
