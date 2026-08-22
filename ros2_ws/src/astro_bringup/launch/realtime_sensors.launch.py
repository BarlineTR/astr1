#!/usr/bin/env python3
"""ASTRO V1 — OpenAI Realtime Audio-to-Audio (WebSocket E2E) Launch File.

Launches:
  1. 24kHz Audio Stream Node (ReSpeaker 4-Mic Array Stream Capture & Low-Latency DAC Playback)
  2. OpenAI Realtime WebSocket Bridge Node (gpt-4o-realtime-preview E2E Voice Engine)
"""

import os
import logging

_LOG = logging.getLogger(__name__)

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    try:
        from dotenv import load_dotenv
        for env_path in [
            os.path.abspath(".env"),
            os.path.abspath(".env.production"),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".env")),
        ]:
            if os.path.exists(env_path):
                load_dotenv(env_path, override=True)
    except Exception as _exc:
        _LOG.debug("generate_launch_description: yok sayılan hata (%s)", _exc)

    use_sim_time = LaunchConfiguration("use_sim_time")

    return LaunchDescription([
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="false",
            description="Use simulation clock"
        ),

        # 1. 24kHz Real-Time Audio Stream & DAC Playback Node
        Node(
            package="astro_audio",
            executable="audio_stream_node",
            name="audio_stream_node",
            output="screen",
            parameters=[{"use_sim_time": use_sim_time}]
        ),

        # 2. OpenAI Realtime WebSocket Bridge Node (gpt-4o-realtime-preview)
        Node(
            package="astro_ai",
            executable="astro_realtime_node",
            name="astro_realtime_node",
            output="screen",
            parameters=[{"use_sim_time": use_sim_time}]
        ),
    ])
