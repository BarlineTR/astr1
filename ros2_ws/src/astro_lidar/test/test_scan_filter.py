#!/usr/bin/env python3
"""Unit tests for ASTRO LiDAR scan filter node."""

import math
import unittest
from unittest.mock import MagicMock


class TestScanFilter(unittest.TestCase):
    def setUp(self):
        self.range_min = 0.15
        self.range_max = 12.0

    def filter_ranges(self, raw_ranges, intensities=None, filter_nan=True):
        filtered_ranges = []
        filtered_intensities = []
        has_intensity = intensities is not None and len(intensities) == len(raw_ranges)

        for i, r in enumerate(raw_ranges):
            if filter_nan and (math.isnan(r) or math.isinf(r) or r <= 0.0):
                filtered_ranges.append(float("inf"))
                if has_intensity:
                    filtered_intensities.append(0.0)
                continue

            if r < self.range_min or r > self.range_max:
                filtered_ranges.append(float("inf"))
                if has_intensity:
                    filtered_intensities.append(0.0)
            else:
                filtered_ranges.append(r)
                if has_intensity:
                    filtered_intensities.append(intensities[i])

        return filtered_ranges, filtered_intensities

    def test_valid_ranges_preserved(self):
        raw = [1.0, 2.5, 5.0, 10.0]
        filt, _ = self.filter_ranges(raw)
        self.assertEqual(filt, raw)

    def test_nan_and_inf_filtered(self):
        raw = [float("nan"), float("inf"), -1.0, 0.0, 2.0]
        filt, _ = self.filter_ranges(raw)
        self.assertTrue(math.isinf(filt[0]))
        self.assertTrue(math.isinf(filt[1]))
        self.assertTrue(math.isinf(filt[2]))
        self.assertTrue(math.isinf(filt[3]))
        self.assertEqual(filt[4], 2.0)

    def test_out_of_range_filtered(self):
        raw = [0.10, 0.14, 0.15, 12.0, 12.01, 15.0]
        filt, _ = self.filter_ranges(raw)
        self.assertTrue(math.isinf(filt[0]))
        self.assertTrue(math.isinf(filt[1]))
        self.assertEqual(filt[2], 0.15)
        self.assertEqual(filt[3], 12.0)
        self.assertTrue(math.isinf(filt[4]))
        self.assertTrue(math.isinf(filt[5]))

    def test_intensity_alignment(self):
        raw = [0.05, 2.0, float("nan")]
        intensities = [100.0, 200.0, 300.0]
        filt, filt_int = self.filter_ranges(raw, intensities)
        self.assertEqual(filt_int[0], 0.0)
        self.assertEqual(filt_int[1], 200.0)
        self.assertEqual(filt_int[2], 0.0)


if __name__ == "__main__":
    unittest.main()
