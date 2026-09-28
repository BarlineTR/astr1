#!/usr/bin/env python3
"""Unit tests for ASTRO vision face detector and temporal smoothing logic."""

from collections import deque
import unittest
import numpy as np


class TestFaceDetectorLogic(unittest.TestCase):
    def test_gaze_smoothing_majority_vote(self):
        """Test that gaze history deque correctly determines looking state via majority threshold."""
        gaze_history = deque(maxlen=5)
        # Empty
        self.assertFalse(sum(gaze_history) >= 3)

        # 2 positive, 3 negative -> False
        # 3 positive in maxlen=5 -> True
        gaze_history.clear()
        for val in [True, True, True, False, False]:
            gaze_history.append(val)
        self.assertTrue(sum(gaze_history) >= 3)

    def test_bounding_box_nms_overlap(self):
        """Test IoU overlap helper for bounding boxes."""
        def compute_iou(box1, box2):
            x1, y1, w1, h1 = box1
            x2, y2, w2, h2 = box2

            xi1 = max(x1, x2)
            yi1 = max(y1, y2)
            xi2 = min(x1 + w1, x2 + w2)
            yi2 = min(y1 + h1, y2 + h2)

            inter_area = max(0, xi2 - xi1) * max(0, yi2 - yi1)
            box1_area = w1 * h1
            box2_area = w2 * h2
            union_area = box1_area + box2_area - inter_area

            return inter_area / float(union_area) if union_area > 0 else 0.0

        # Identical boxes
        self.assertAlmostEqual(compute_iou((0, 0, 100, 100), (0, 0, 100, 100)), 1.0)
        # Non-overlapping
        self.assertAlmostEqual(compute_iou((0, 0, 50, 50), (100, 100, 50, 50)), 0.0)
        # 50% overlap
        iou = compute_iou((0, 0, 100, 100), (50, 0, 100, 100))
        self.assertAlmostEqual(iou, 5000.0 / 15000.0, places=3)

    def test_depth_median_estimation(self):
        """Test distance extraction from depth array around center region."""
        depth_frame = np.ones((480, 640), dtype=np.uint16) * 1500  # 1.5m in mm
        # Add some noise
        depth_frame[200:280, 280:360] = 1450
        crop = depth_frame[200:280, 280:360]
        valid = crop[crop > 0]
        med_dist_m = float(np.median(valid)) / 1000.0
        self.assertAlmostEqual(med_dist_m, 1.45, places=2)


if __name__ == "__main__":
    unittest.main()
