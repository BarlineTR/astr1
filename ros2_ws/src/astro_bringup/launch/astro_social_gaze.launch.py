"""ASTRO V1 — Canonical One-Command Social Gaze & Hardware Bringup Launch File.

Starts:
  1. serial_bridge (physical head motor communication via MCU)
  2. standalone_gaze_ros (unified vision + audio + gaze + conversation runtime)

Enforces:
  - Strict Single Gaze Brain invariant (GazeTracker -> /head/command -> serial_bridge)
  - CameraSource and AudioSource run directly inside standalone_gaze_ros process
  - Automatic .env injection (OPENAI_API_KEY, TTS settings)
  - NO duplicate OAK nodes, NO face_detector_node, NO social_gaze_node
"""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _dotenv_launch_actions():
    """Inject astr1/.env into every node process."""
    actions = []
    try:
        from dotenv import dotenv_values
    except ImportError:
        return actions

    search_dirs = [os.getcwd()]
    launch_dir = os.path.dirname(os.path.abspath(__file__))
    if launch_dir not in search_dirs:
        search_dirs.append(launch_dir)

    env_path = None
    seen = set()
    for start in search_dirs:
        current = start
        for _ in range(10):
            if current in seen:
                break
            seen.add(current)
            candidate = os.path.join(current, ".env")
            if os.path.isfile(candidate):
                env_path = candidate
                break
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        if env_path:
            break

    if not env_path:
        return actions

    for key, value in dotenv_values(env_path).items():
        if key and value is not None:
            actions.append(SetEnvironmentVariable(key, value))
    return actions


def generate_launch_description():
    actions = _dotenv_launch_actions()

    launch_args = [
        DeclareLaunchArgument(
            "launch_serial_bridge",
            default_value="true",
            description="Launch serial bridge driver for Arduino Mega / hardware head motor",
        ),
        DeclareLaunchArgument(
            "serial_port",
            default_value="/dev/ttyCH341USB0",
            description="Serial device path for Arduino Mega",
        ),
        DeclareLaunchArgument(
            "camera_device",
            default_value="0",
            description="Camera device index (fallback webcam)",
        ),
        DeclareLaunchArgument(
            "enable_audio",
            default_value="true",
            description="Enable ReSpeaker 4-mic array / audio DOA tracking",
        ),
        DeclareLaunchArgument(
            "enable_voice",
            default_value="true",
            description="Enable Realtime / OpenAI conversation loop and Edge-TTS",
        ),
    ]

    serial_bridge_node = Node(
        package="astro_base",
        executable="serial_bridge",
        name="serial_bridge",
        output="screen",
        condition=IfCondition(LaunchConfiguration("launch_serial_bridge")),
        parameters=[{
            "port": LaunchConfiguration("serial_port"),
            "baud": 115200,
        }],
    )

    standalone_gaze_node = Node(
        package="astro_base",
        executable="standalone_gaze_ros",
        name="standalone_gaze_ros_node",
        output="screen",
        parameters=[{
            "camera_device": LaunchConfiguration("camera_device"),
            "enable_audio": LaunchConfiguration("enable_audio"),
            "enable_voice": LaunchConfiguration("enable_voice"),
        }],
    )

    return LaunchDescription(actions + launch_args + [serial_bridge_node, standalone_gaze_node])
