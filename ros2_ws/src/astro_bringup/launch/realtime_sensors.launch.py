#!/usr/bin/env python3
"""ASTRO V1 — OpenAI Realtime Audio-to-Audio (WebSocket E2E) Launch File.

Launches:
  1. OAK-D Lite Spatial Camera & Face Detector Node (3D Gaze, Emotion, SFace Face Recognition)
  2. 24kHz Audio Stream Node (ReSpeaker 4-Mic Array Stream Capture & Low-Latency DAC Playback)
  3. OpenAI Realtime WebSocket Bridge Node (gpt-4o-realtime-preview E2E Voice Engine)
"""

import os
import logging

_LOG = logging.getLogger(__name__)

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
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

    vision_pkg = get_package_share_directory("astro_vision")
    use_sim_time = LaunchConfiguration("use_sim_time")
    enable_vision = LaunchConfiguration("enable_vision")

    return LaunchDescription([
        DeclareLaunchArgument(
            "use_sim_time",
            default_value="false",
            description="Use simulation clock"
        ),
        DeclareLaunchArgument(
            "enable_vision",
            default_value="true",
            description="Start OAK-D camera and face detector"
        ),

        # 1. Vision & Face Detector
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(vision_pkg, "launch", "camera.launch.py")
            ),
            condition=IfCondition(enable_vision),
            launch_arguments={"use_sim_time": use_sim_time}.items(),
        ),

        # 2. 24kHz Real-Time Audio Stream & DAC Playback Node
        Node(
            package="astro_audio",
            executable="audio_stream_node",
            name="audio_stream_node",
            output="screen",
            parameters=[{"use_sim_time": use_sim_time}]
        ),

        # 3. OpenAI Realtime WebSocket Bridge Node (gpt-4o-realtime-preview)
        Node(
            package="astro_ai",
            executable="astro_realtime_node",
            name="astro_realtime_node",
            output="screen",
            parameters=[{"use_sim_time": use_sim_time}]
        ),
    ])
