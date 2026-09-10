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
