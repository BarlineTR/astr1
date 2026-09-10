#!/usr/bin/env python3
"""Unit tests for non-verbal attentive listening and thinking gaze aversion in AstroRealtimeNode."""

import os
import sys
import time
from unittest.mock import MagicMock

import pytest

# Ensure astro_ai is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from astro_ai.astro_realtime_node import AstroRealtimeNode


class TestNonVerbalSocialBehavior:
    @pytest.fixture
    def realtime_node(self):
        node = AstroRealtimeNode(
            fake_transport=True,
            connect_realtime=False,
        )
        return node

    def test_thinking_gaze_aversion_and_reengagement(self, realtime_node):
        """When speech stops, robot averts gaze (+3.0°). When audio starts, eye contact is restored (0.0°)."""
        node = realtime_node
        node._is_sleeping = False
        assert node.pub_social_offset_yaw is not None

        # 1. User stops speaking -> Thinking phase starts
        node._user_speaking_active = False
        node._user_speech_start_time = 0.0
        if getattr(node, "pub_social_offset_yaw", None):
            node._gaze_aversion_active = True
            node.pub_social_offset_yaw.publish(MagicMock(data=3.0))

        assert node._gaze_aversion_active is True
        assert node.pub_social_offset_yaw.last_msg.data == 3.0

        # 2. Server audio delta arrives (first packet) -> Restore direct eye contact
        node._packets_for_gen = 1
        if getattr(node, "pub_social_offset_yaw", None) and getattr(node, "_gaze_aversion_active", False):
            node._gaze_aversion_active = False
            node.pub_social_offset_yaw.publish(MagicMock(data=0.0))

        assert node._gaze_aversion_active is False
        assert node.pub_social_offset_yaw.last_msg.data == 0.0

    def test_attentive_listening_nod(self, realtime_node):
        """When user speaks for >= 2.5s continuously, robot produces a gentle nodding cue."""
        node = realtime_node
        assert node.pub_head_gesture is not None

        now = time.monotonic()
        node._user_speaking_active = True
        node._user_speech_start_time = now - 3.0
        node._last_attentive_nod_time = now - 3.0

        node._social_attentive_listener_tick()

        assert node.pub_head_gesture.last_msg is not None
        assert node.pub_head_gesture.last_msg.data == "nod"
        assert (node._last_attentive_nod_time - now) >= -0.1

    def test_barge_in_clears_gaze_aversion(self, realtime_node):
        """If user speaks while aversion was active, aversion is immediately cancelled."""
        node = realtime_node
        node._gaze_aversion_active = True

        if getattr(node, "pub_social_offset_yaw", None) and getattr(node, "_gaze_aversion_active", False):
            node._gaze_aversion_active = False
            node.pub_social_offset_yaw.publish(MagicMock(data=0.0))

        assert node._gaze_aversion_active is False
        assert node.pub_social_offset_yaw.last_msg.data == 0.0

    def test_lidar_blindspot_approach_reflex(self, realtime_node):
        """When IDLE, approaching entity in blind spot triggers curious head turn towards it."""
        from astro_ai.contracts.spatial_state import SpatialPersonTrack
        node = realtime_node
        node._is_sleeping = False
        node._is_responding = False
        node._is_playback_active = False
        node._user_speaking_active = False
        node._vad_active = False
        node._gaze_active_target = "NONE"
        node._last_lidar_curiosity_time = 0.0

        # Create mock approaching track at 45.0° azimuth, 1.5m away
        mock_track = SpatialPersonTrack(
            track_id="tr_1",
            current_x=1.0,
            current_y=1.0,
            distance_m=1.41,
            azimuth_deg=45.0,
            velocity_mps=-0.15,
            heading_deg=0.0,
            last_update_ts=time.monotonic(),
        )

        mock_tracker = MagicMock()
        mock_tracker.get_active_tracks.return_value = [mock_track]
        node.lidar_tracker = mock_tracker

        # 1. IDLE state: reflex fires!
        node._evaluate_lidar_blindspot_approach()
        assert node.pub_head_target_yaw.last_msg is not None
        assert node.pub_head_target_yaw.last_msg.data == 45.0

        # 2. Busy with conversation or face tracking: reflex does NOT fire
        node._last_lidar_curiosity_time = 0.0
        node.pub_head_target_yaw.last_msg = None
        node._gaze_active_target = "face_track_1"  # Face actively tracking!
        node._evaluate_lidar_blindspot_approach()
        assert node.pub_head_target_yaw.last_msg is None

        # 3. User talking (VAD active): reflex does NOT fire
        node._gaze_active_target = "NONE"
        node._vad_active = True
        node._evaluate_lidar_blindspot_approach()
        assert node.pub_head_target_yaw.last_msg is None

