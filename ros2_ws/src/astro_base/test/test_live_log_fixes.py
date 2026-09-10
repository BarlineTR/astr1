#!/usr/bin/env python3
"""Unit tests verifying live log bug fixes:
1. Gesture sequence priority & 150ms cooldown over social_yaw_offset (prevents ±3° oscillation)
2. Post-speech DOA guard (1.5s echo/reverb suppression window after playback ends)
3. Serial head command throttling (30ms minimum interval guard)
4. Encoder bounds sanity check (±80° mechanical limit protection & open-loop fallback)
"""

import os
import sys
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

pkg_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if pkg_dir not in sys.path:
    sys.path.insert(0, pkg_dir)

from astro_base.standalone_gaze_ros_node import StandaloneGazeRosNode
from astro_base.serial_bridge import SerialBridge


class TestLiveLogFixes(unittest.TestCase):
    def test_gesture_priority_and_cooldown_prevents_oscillation(self):
        """When a gesture is active, social_yaw_offset must be suppressed.
        After gesture finishes, 150ms cooldown prevents immediate ping-pong.
        """
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        t0 = 1000.0

        # Set social yaw offset to +3.0° (Thinking Gaze Aversion)
        node._social_yaw_offset = 3.0
        node._social_offset_expiry = t0 + 5.0

        # Without gesture, social offset is applied
        self.assertEqual(node._current_social_offset(t0), 3.0)

        # Trigger a gesture: nod (+2.5° for 120ms, -2.0° for 120ms, 0.0° for 120ms)
        node._gesture_sequence = [
            (2.5, t0 + 0.12),
            (-2.0, t0 + 0.24),
            (0.0, t0 + 0.36),
        ]

        # Step 1: During gesture step 1, returns gesture target (2.5°), NOT 3.0°
        self.assertEqual(node._current_social_offset(t0 + 0.05), 2.5)

        # Step 2: Pop step 1 when time advances
        self.assertEqual(node._current_social_offset(t0 + 0.15), -2.0)

        # Step 3: Pop step 2
        self.assertEqual(node._current_social_offset(t0 + 0.26), 0.0)

        # Step 4: Gesture sequence completes at t0 + 0.37.
        # Should return 0.0 and enter 150ms cooldown (until t0 + 0.37 + 0.15 = t0 + 0.52)
        offset_at_end = node._current_social_offset(t0 + 0.37)
        self.assertEqual(offset_at_end, 0.0)
        self.assertGreaterEqual(node._gesture_cooldown_until, t0 + 0.37)

        # During cooldown (e.g. t0 + 0.45), social_yaw_offset must STILL be suppressed
        self.assertEqual(node._current_social_offset(t0 + 0.45), 0.0)

        # After cooldown expires (e.g. t0 + 0.60), social_yaw_offset can engage again
        self.assertEqual(node._current_social_offset(t0 + 0.60), 3.0)

        node.destroy_node()

    def test_post_speech_doa_guard_suppression(self):
        """When playback stops, a 1.5s guard window must suppress DOA updates
        to prevent acoustic echoes/reverb from triggering spurious head turns.
        """
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=True)

        with patch("astro_base.standalone_gaze_ros_node.time.monotonic") as mock_time:
            now = 2000.0
            mock_time.return_value = now

            # Simulate playback active
            node._on_playback_active(SimpleNamespace(data=True))
            self.assertTrue(node._playback_active)

            # Playback ends
            node._on_playback_active(SimpleNamespace(data=False))
            self.assertFalse(node._playback_active)
            self.assertEqual(node._post_speech_guard_until, now + 1.5)

            # Mock localizer update
            node.localizer = MagicMock()

            # DOA message arrives during guard period (now + 0.5s)
            mock_time.return_value = now + 0.5
            node._on_audio_doa(SimpleNamespace(data=142.0))

            # Localizer must NOT have been updated
            node.localizer.update.assert_not_called()

            # DOA message arrives AFTER guard period (now + 1.6s)
            mock_time.return_value = now + 1.6
            node.audio_source_mode = "topics"
            node._latest_vad_active = True
            node._on_audio_doa(SimpleNamespace(data=142.0))

            # Localizer should now be called
            node.localizer.update.assert_called_once()

        node.destroy_node()

    def test_serial_bridge_head_cmd_30ms_throttling(self):
        """SerialBridge on_head_cmd must not send packets faster than 30ms
        even if the requested angle changes by >= 0.5°.
        """
        bridge = SerialBridge()
        bridge.ser = MagicMock()
        bridge.ser.is_open = True
        bridge.arduino_alive = True
        bridge._last_sent_angle = 0.0
        bridge._last_sent_angle_time = 100.0

        with patch("astro_base.serial_bridge.time.monotonic") as mock_time:
            # 1. 10ms later: angle changed from 0.0 to 3.0, but only 10ms elapsed (<30ms)
            mock_time.return_value = 100.010
            cmd = SimpleNamespace(angle_deg=3.0)
            bridge.on_head_cmd(cmd)

            # Ser.write should NOT be called due to < 30ms interval
            bridge.ser.write.assert_not_called()
            self.assertEqual(bridge._last_sent_angle, 0.0)

            # 2. 35ms later (100.035): now interval >= 30ms and angle changed
            mock_time.return_value = 100.035
            bridge.on_head_cmd(cmd)

            # Ser.write should now be called
            bridge.ser.write.assert_called_once()
            self.assertEqual(bridge._last_sent_angle, 3.0)
            self.assertEqual(bridge._last_sent_angle_time, 100.035)

        bridge.destroy_node()

    def test_serial_bridge_encoder_sanity_check(self):
        """If raw encoder position exceeds ±80°, it must be rejected as an
        encoder fault and fall back to open-loop (_last_sent_angle).
        Valid positions within ±80° must be accepted.
        """
        bridge = SerialBridge()
        bridge._last_sent_angle = 15.0

        # Normal ticks: e.g. 50 ticks with ticks_per_deg=2.5882 -> ~19.3° (valid)
        bridge.publish_joint_states(left_ticks=0, right_ticks=0, dt_us=20000, head_ticks=50)
        self.assertTrue(bridge.head_encoder_valid)
        self.assertAlmostEqual(bridge.head_pos, 50 / 2.5882, places=1)
        self.assertFalse(bridge._encoder_fault_logged)

        # Huge ticks: e.g. 1,000,000 ticks -> 386368° (runaway EMI / noise)
        bridge.publish_joint_states(left_ticks=0, right_ticks=0, dt_us=20000, head_ticks=1000000)
        self.assertFalse(bridge.head_encoder_valid)
        # Head pos falls back to _last_sent_angle (15.0)
        self.assertEqual(bridge.head_pos, 15.0)
        self.assertTrue(bridge._encoder_fault_logged)

        # Negative huge ticks: e.g. -50000 ticks -> -19318°
        bridge.publish_joint_states(left_ticks=0, right_ticks=0, dt_us=20000, head_ticks=-50000)
        self.assertFalse(bridge.head_encoder_valid)
        self.assertEqual(bridge.head_pos, 15.0)

        # Recovery: valid ticks resume (e.g. 25 ticks -> ~9.6°)
        bridge.publish_joint_states(left_ticks=0, right_ticks=0, dt_us=20000, head_ticks=25)
        self.assertTrue(bridge.head_encoder_valid)
        self.assertAlmostEqual(bridge.head_pos, 25 / 2.5882, places=1)
        self.assertFalse(bridge._encoder_fault_logged)

        bridge.destroy_node()


if __name__ == "__main__":
    unittest.main()
