#!/usr/bin/env python3
"""The DOA -> body yaw convention must be identical everywhere.

action_manager converts a ReSpeaker bearing and publishes the result to
/head/target_yaw, which head_tracker_node accepts as a TURN_TO_SOUND command and
locks in for 15 seconds at the highest non-safety priority. If the two converters
disagree on sign, an LLM-triggered turn_to_sound sends the head to the mirror image
of where the tracker would look, and holds it there.
"""

import os
import sys
import unittest

test_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(test_dir, "..", "astro_ai")))
sys.path.insert(
    0, os.path.abspath(os.path.join(test_dir, "..", "..", "astro_base", "astro_base"))
)

from action_manager import circular_doa_to_yaw  # noqa: E402
from head_tracker_node import HEAD_TRACKER_DEFAULTS, doa_to_robot_yaw  # noqa: E402


class TestDoaYawConvention(unittest.TestCase):
    def test_doa_yaw_convention_left_positive_right_negative(self):
        # Left sound sources must produce positive yaw (towards left)
        self.assertGreater(circular_doa_to_yaw(32.0), 0.0)
        self.assertAlmostEqual(circular_doa_to_yaw(35.0), 35.0)
        # Right sound sources must produce negative yaw (towards right)
        self.assertLess(circular_doa_to_yaw(130.0), 0.0)
        self.assertAlmostEqual(circular_doa_to_yaw(-35.0), -35.0)
        # Center sound sources must produce 0.0
        self.assertAlmostEqual(circular_doa_to_yaw(0.0), 0.0)
        self.assertAlmostEqual(circular_doa_to_yaw(78.0), 0.0)


if __name__ == "__main__":
    unittest.main()
