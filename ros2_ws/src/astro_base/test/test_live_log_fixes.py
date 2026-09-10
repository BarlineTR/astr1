#!/usr/bin/env python3
"""Unit tests verifying live log bug fixes:
1. Gesture sequence priority & 150ms cooldown over social_yaw_offset (prevents ±3° oscillation)
2. Comprehensive post-speech DOA/VAD/reverb guard (1.5s suppression across all callbacks & sampling)
3. Serial head command throttling (30ms guard) AND periodic setpoint refresh (300ms when lagging)
4. Duplicate /head/cmd_pos suppression when /head/command is active
5. Encoder bounds sanity check (±80° mechanical limit protection & open-loop fallback)
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

    def test_post_speech_doa_and_vad_guard_suppression(self):
        """When playback or speech stops, a 1.5s guard window must suppress
        both DOA and VAD updates, and _sample_acoustic_state must report is_speaking=True
        to prevent acoustic echoes/reverb from triggering spurious head turns.
        """
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=True)

        with patch("astro_base.standalone_gaze_ros_node.time.monotonic") as mock_time:
            now = 2000.0
            mock_time.return_value = now

            # 1. Simulate playback active -> playback ends
            node._on_playback_active(SimpleNamespace(data=True))
            self.assertTrue(node._playback_active)
            node._on_playback_active(SimpleNamespace(data=False))
            self.assertFalse(node._playback_active)
            self.assertEqual(node._post_speech_guard_until, now + 1.5)

            # Mock localizer
            node.localizer = MagicMock()

            # During guard (now + 0.5s): DOA arriving should be ignored
            mock_time.return_value = now + 0.5
            node._on_audio_doa(SimpleNamespace(data=142.0))
            node.localizer.update.assert_not_called()

            # During guard: VAD arriving should also be ignored
            node._on_audio_vad(SimpleNamespace(data=True))
            node.localizer.update.assert_not_called()

            # During guard: _sample_acoustic_state must suppress DOA/speech
            doa, speech, is_speaking = node._sample_acoustic_state(now + 0.5)
            self.assertIsNone(doa)
            self.assertIsNone(speech)

            # 2. After guard expires (now + 1.6s)
            mock_time.return_value = now + 1.6
            node.audio_source_mode = "topics"
            node._latest_vad_active = True
            node._on_audio_doa(SimpleNamespace(data=142.0))
            node.localizer.update.assert_called_once()

            # 3. Test /robot/is_speaking transition also triggers guard
            mock_time.return_value = now + 10.0
            node._on_robot_speaking(SimpleNamespace(data=True))
            self.assertTrue(node._robot_speaking)
            mock_time.return_value = now + 12.0
            node._on_robot_speaking(SimpleNamespace(data=False))
            self.assertFalse(node._robot_speaking)
            self.assertEqual(node._post_speech_guard_until, now + 12.0 + 1.5)

        node.destroy_node()

    def test_serial_bridge_head_cmd_30ms_throttling(self):
        """SerialBridge on_head_cmd must not send packets faster than 30ms
        when the angle changes rapidly.
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

    def test_serial_bridge_head_cmd_periodic_refresh_when_lagging(self):
        """When the head command stays constant (e.g. 4.4°) but actual head position
        has not converged (|actual - target| > 2.0°), on_head_cmd must re-transmit
        the setpoint every 300ms to prevent Arduino stall lockup.
        """
        bridge = SerialBridge()
        bridge.ser = MagicMock()
        bridge.ser.is_open = True
        bridge.arduino_alive = True
        bridge.head_pos = 31.7  # Actual head lagging at 31.7°
        bridge._last_sent_angle = 4.4
        bridge._last_sent_angle_time = 100.0

        with patch("astro_base.serial_bridge.time.monotonic") as mock_time:
            cmd = SimpleNamespace(angle_deg=4.4)

            # At t = 100.100 (100ms later): angle didn't change and dt < 300ms -> NOT sent
            mock_time.return_value = 100.100
            bridge.on_head_cmd(cmd)
            bridge.ser.write.assert_not_called()

            # At t = 100.350 (350ms later): angle didn't change BUT dt >= 300ms and |31.7 - 4.4| = 27.3° > 2.0°
            # Must trigger periodic setpoint refresh!
            mock_time.return_value = 100.350
            bridge.on_head_cmd(cmd)
            bridge.ser.write.assert_called_once()
            self.assertEqual(bridge._last_sent_angle_time, 100.350)

            # Once head reaches target (|4.4 - 4.4| = 0 <= 2.0°): no further refresh needed
            bridge.ser.write.reset_mock()
            bridge.head_pos = 4.5  # Reached target within 2°
            mock_time.return_value = 100.700  # 350ms later again
            bridge.on_head_cmd(cmd)
            bridge.ser.write.assert_not_called()

        bridge.destroy_node()

    def test_on_head_pos_cmd_duplicate_suppression(self):
        """When /head/command is actively transmitting, duplicate commands from
        /head/cmd_pos within 100ms must be suppressed.
        """
        bridge = SerialBridge()
        bridge.ser = MagicMock()
        bridge.ser.is_open = True
        bridge.arduino_alive = True

        with patch("astro_base.serial_bridge.time.monotonic") as mock_time:
            mock_time.return_value = 500.0
            # Canonical /head/command arrives
            bridge.on_head_cmd(SimpleNamespace(angle_deg=10.0))
            self.assertEqual(bridge.ser.write.call_count, 1)

            # Duplicate /head/cmd_pos arrives 2ms later
            mock_time.return_value = 500.002
            bridge.on_head_pos_cmd(SimpleNamespace(data=10.0))
            # Must NOT trigger extra call
            self.assertEqual(bridge.ser.write.call_count, 1)

            # Standalone usage of /head/cmd_pos (e.g. from test script after 500ms without /head/command)
            mock_time.return_value = 500.600
            bridge.on_head_pos_cmd(SimpleNamespace(data=20.0))
            self.assertEqual(bridge.ser.write.call_count, 2)

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

    def test_visual_deadband_suppresses_hunting_when_centered(self):
        """When settled in HOLDING_ATTENTION and face is within ±2.5° of camera center,
        target_yaw must remain stable and not produce hunting motor jitter.
        """
        from tracker import Detection
        from astro_base.gaze.types import GazeStateEnum
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        det = [Detection(x=320, y=200, w=80, h=80, confidence=0.9)]

        # Settle into HOLDING_ATTENTION
        for i in range(50):
            t = 10.0 + i * 0.033
            node._on_head_state(type("HState", (), {"position_deg": node.last_published_yaw, "velocity_deg_s": 0.0})())
            node.step_frame(detections=det, frame_size=(640, 480), timestamp=t)

        self.assertEqual(node.latest_result.gaze_state, GazeStateEnum.HOLDING_ATTENTION)
        prev_target = node.last_published_yaw

        # Face slightly jitters (+1.1° optical bearing from center: x=310 instead of 320)
        det_jitter = [Detection(x=310, y=200, w=80, h=80, confidence=0.9)]
        res = node.step_frame(detections=det_jitter, frame_size=(640, 480), timestamp=10.0 + 51 * 0.033)

        # target_yaw must be held at prev_target rather than hunting
        self.assertEqual(node.last_published_yaw, prev_target)
        node.destroy_node()

    def test_kalman_velocity_damping_prevents_runaway(self):
        """KalmanTrack3D must dampen velocity during coasting to prevent drift."""
        from astro_base.gaze.visual_tracker import KalmanTrack3D
        from astro_base.gaze.types import VisualObservation

        mock_obs = VisualObservation(
            timestamp=1.0,
            valid=True,
            bbox=(300, 200, 60, 60),
            u_norm=0.0,
            v_norm=0.0,
            depth_m=1.0,
            pos_3d_camera=(0.0, 0.0, 1.0),
            camera_azimuth_deg=0.0,
            camera_elevation_deg=0.0,
            body_azimuth_deg=0.0,
            confidence=0.85,
        )
        track = KalmanTrack3D(track_id="p1", initial_pos_3d=(1.0, 0.0, 0.0), timestamp=1.0, obs=mock_obs)
        track.x[3:6] = [0.1, 0.5, 0.0]

        for i in range(10):
            track.mark_missed(timestamp=1.0 + (i + 1) * 0.05, coast_timeout_s=2.0)

        speed = float((track.x[3]**2 + track.x[4]**2 + track.x[5]**2)**0.5)
        self.assertLess(speed, 0.10)

    def test_visual_grace_window_and_audio_reacq_vad_guard(self):
        """Visual target loss must hold heading for 1.5s before allowing fallback.
        Audio reacquisition must require fresh active speech VAD, preventing
        background TV/noise from snapping the head to +60°.
        """
        from tracker import Detection
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=True)
        node.audio_source_mode = "topics"
        t0 = 50.0

        # 1. Visual lock at +20.0°
        face_det = [Detection(x=150, y=200, w=80, h=80, confidence=0.9)]
        res = node.step_frame(detections=face_det, frame_size=(640, 480), timestamp=t0)
        self.assertAlmostEqual(node._last_visual_yaw, node.last_published_yaw, places=1)
        last_yaw = node._last_visual_yaw

        # 2. Face is temporarily missed (0.5s later)
        node.localizer._tracking_active = True
        node.localizer.active_target_yaw = 60.0  # LEFT = +60.0°
        node.localizer._last_valid_target_time = t0 + 0.5
        node._latest_vad_active = False  # NO human speech currently active

        res_missed = node.step_frame(detections=[], frame_size=(640, 480), timestamp=t0 + 0.5)

        # Must HOLD last visual yaw due to 1.5s visual grace window, NOT snap to +60.0°!
        self.assertEqual(node.last_published_yaw, last_yaw)
        self.assertNotEqual(node.last_published_yaw, 60.0)

        # 3. After visual tracking expires and goes to IDLE without active speech VAD
        # Step through to t0 + 6.0
        for dt in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]:
            res_expired = node.step_frame(detections=[], frame_size=(640, 480), timestamp=t0 + dt)
        # Should go to IDLE (0.0°), NOT snap to +60.0°!
        self.assertEqual(node.last_published_yaw, 0.0)

        # 4. Now user actually speaks (VAD True)
        node._latest_vad_active = True
        node._latest_vad_time = t0 + 7.0
        node.localizer._tracking_active = True
        node.localizer.active_target_yaw = 60.0
        node.localizer._last_valid_target_time = t0 + 7.0
        res_speech = node.step_frame(detections=[], frame_size=(640, 480), timestamp=t0 + 7.0)
        self.assertEqual(node.last_published_yaw, 60.0)

        # 5. User stops speaking 0.5s later (VAD False) -> MUST retain hold grace!
        node._latest_vad_active = False
        res_hold = node.step_frame(detections=[], frame_size=(640, 480), timestamp=t0 + 7.5)
        self.assertEqual(node.last_published_yaw, 60.0)

        # 6. After hold_grace expires (e.g. 5.5s after speech ended at t0 + 7.0 -> t0 + 12.5)
        res_expired = node.step_frame(detections=[], frame_size=(640, 480), timestamp=t0 + 12.5)
        self.assertEqual(node.last_published_yaw, 0.0)

        node.destroy_node()

    def test_keepalive_does_not_double_add_social_offset(self):
        """step_frame() and _passive_keepalive_cycle() must output the exact same
        effective yaw when social_offset is active, eliminating 3° oscillation.
        """
        node = StandaloneGazeRosNode(use_camera_source=False, enable_audio=False)
        t0 = 1000.0

        # Set social offset = +3.0°
        node._social_yaw_offset = 3.0
        node._social_offset_expiry = t0 + 10.0

        # Step frame with no detections (motor_yaw = 0.0)
        res = node.step_frame(detections=[], frame_size=(640, 480), timestamp=t0)
        self.assertEqual(node.last_published_yaw, 3.0)
        self.assertEqual(node.runtime.last_target_yaw_deg, 0.0)  # Stores un-offset base motor_yaw!

        # Capture published command from _passive_keepalive_cycle
        published_cmds = []
        node.pub_head_cmd_pos.publish = lambda msg: published_cmds.append(msg.data)
        node.pub_head_command.publish = lambda msg: None

        with patch("astro_base.standalone_gaze_ros_node.time.monotonic", return_value=t0 + 0.020):
            node._passive_keepalive_cycle()

        self.assertEqual(len(published_cmds), 1)
        # Keepalive must publish 3.0°, NOT 6.0° (no doubling!)
        self.assertEqual(published_cmds[0], 3.0)

        # Now test with active audio target (motor_yaw = 60.0)
        node.localizer._tracking_active = True
        node.localizer.active_target_yaw = 60.0
        node.localizer._last_valid_target_time = t0 + 1.0

        res_audio = node.step_frame(detections=[], frame_size=(640, 480), timestamp=t0 + 1.0)
        self.assertEqual(node.last_published_yaw, 63.0)  # 60.0 + 3.0
        self.assertEqual(node.runtime.last_target_yaw_deg, 60.0)

        published_cmds.clear()
        with patch("astro_base.standalone_gaze_ros_node.time.monotonic", return_value=t0 + 1.020):
            node._passive_keepalive_cycle()

        self.assertEqual(len(published_cmds), 1)
        # Keepalive must publish 63.0°, NOT 66.0°!
        self.assertEqual(published_cmds[0], 63.0)

        node.destroy_node()

    def test_sector_confirmation_from_idle_filters_phantom_spikes(self):
        """When confirm_from_idle=True, 1 reading must not trigger a turn;
        2 consecutive readings in the same sector are required to confirm.
        """
        from astro_base.gaze.respeaker_localizer import ReSpeakerAudioLocalizer
        loc = ReSpeakerAudioLocalizer(confirm_from_idle=True, sector_confirm_count=2)

        # 1. Single phantom noise spike in LEFT (DOA 32)
        loc.update(doa_raw=32.0, voice_activity=True, timestamp=10.0)
        self.assertFalse(loc.is_tracking())
        self.assertIsNone(loc.confirmed_sector)
        self.assertEqual(loc.target_yaw_deg, 0.0)

        # 2. Silence > 0.5s resets pending candidate
        loc.update(doa_raw=None, voice_activity=False, timestamp=10.6)

        # 3. Another isolated spike in RIGHT (DOA 142)
        loc.update(doa_raw=142.0, voice_activity=True, timestamp=11.0)
        self.assertFalse(loc.is_tracking())
        self.assertIsNone(loc.confirmed_sector)
        self.assertEqual(loc.target_yaw_deg, 0.0)

        # 4. Sustained human speech: 2nd consecutive reading in RIGHT arrives 30ms later
        loc.update(doa_raw=142.0, voice_activity=True, timestamp=11.030)
        self.assertTrue(loc.is_tracking())
        self.assertEqual(loc.confirmed_sector, "RIGHT")
        self.assertEqual(loc.target_yaw_deg, -60.0)

        # 5. Speech pauses (VAD False): tracking must remain active during hold grace
        loc.update(doa_raw=None, voice_activity=False, timestamp=12.0)
        self.assertTrue(loc.is_tracking(12.0))
        self.assertEqual(loc.target_yaw_deg, -60.0)


if __name__ == "__main__":
    unittest.main()
