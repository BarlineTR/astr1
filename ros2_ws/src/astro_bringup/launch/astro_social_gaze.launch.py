"""ASTRO V1 — Canonical One-Command Social Gaze, Audio & Realtime Bringup Launch File.

Starts:
  1. serial_bridge (physical head motor communication via MCU)
  2. standalone_gaze_ros (authoritative gaze runtime: CameraSource -> GazeTracker -> /head/command)
  3. audio_stream_node (ReSpeaker 4-Mic capture, GCC-PHAT DOA, VAD, DAC streaming playback)
  4. astro_realtime_node (OpenAI Realtime WebSocket, wake word, memory, identity, Edge-TTS fallback)

Enforces:
  - Strict Single Gaze Brain invariant (GazeTracker -> /head/command -> serial_bridge)
  - Audio and Realtime nodes NEVER publish motor commands
  - Clean separation: audio_stream_node owns ReSpeaker hardware, standalone_gaze_ros subscribes to topics
  - Automatic .env injection (OPENAI_API_KEY, TTS settings)
  - NO duplicate OAK nodes, NO face_detector_node, NO duplicate social_gaze_node
"""

import os

try:
    from launch import LaunchDescription
    from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable
    from launch.conditions import IfCondition
    from launch.launch_description_sources import PythonLaunchDescriptionSource
    from launch.substitutions import LaunchConfiguration
    from launch_ros.actions import Node
except ImportError:
    class LaunchDescription:
        def __init__(self, entities=None):
            self.entities = list(entities or [])
    class DeclareLaunchArgument:
        def __init__(self, name, default_value="", description=""):
            self.name = name
            self.default_value = default_value
            self.description = description
    class IncludeLaunchDescription:
        def __init__(self, source, condition=None, launch_arguments=None):
            self.source = source
            self.condition = condition
            self.launch_arguments = launch_arguments or {}
    class PythonLaunchDescriptionSource:
        def __init__(self, path):
            self.path = path
    class SetEnvironmentVariable:
        def __init__(self, name, value):
            self.name = name
            self.value = value
    class IfCondition:
        def __init__(self, predicate):
            self.predicate = predicate
    class LaunchConfiguration:
        def __init__(self, name):
            self.name = name
    class Node:
        def __init__(self, package="", executable="", name="", output="screen", condition=None, parameters=None):
            self.package = package
            self.executable = executable
            self.name = name
            self.output = output
            self.condition = condition
            self.parameters = parameters or []
            self.node_package = package
            self.node_executable = executable
            self.node_name = name


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
        DeclareLaunchArgument(
            "verbose_diagnostics",
            default_value="false",
            description="Enable verbose per-frame forensic telemetry output",
        ),
        DeclareLaunchArgument(
            "audio_input_channels",
            default_value="0",
            description="Audio input channels for ReSpeaker capture (0=auto-detect 4-mic/fallback)",
        ),
        DeclareLaunchArgument(
            "audio_source_mode",
            default_value="hardware",
            description="Audio localizer mode ('hardware' for direct ReSpeaker HID matching track.py, or 'topics')",
        ),
        DeclareLaunchArgument(
            "audio_hold_grace",
            default_value="5.0",
            description="Grace period in seconds to hold speaker heading before returning to center",
        ),
        DeclareLaunchArgument(
            "audio_deadband",
            default_value="5.0",
            description="Angular deadband in degrees to suppress minor audio jitter",
        ),
        DeclareLaunchArgument(
            "audio_doa_profile",
            default_value="respeaker_sectors",
            description="ReSpeaker sector-based DOA profile (LEFT 60, CENTER 0, RIGHT -60)",
        ),
        DeclareLaunchArgument(
            "enable_lidar",
            default_value="true",
            description="Enable RPLIDAR 2D tracking & blindspot curiosity reflex",
        ),
        DeclareLaunchArgument(
            "lidar_serial_port",
            default_value="/dev/astro_lidar",
            description="Serial device path for RPLIDAR (auto-resolves if not found)",
        ),
        DeclareLaunchArgument(
            "inverted",
            default_value="false",
            description="Invert RPLIDAR scan (flips left/right for upside down or mirrored mount)",
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
            "audio_source_mode": LaunchConfiguration("audio_source_mode"),
            "audio_hold_grace": LaunchConfiguration("audio_hold_grace"),
            "audio_deadband": LaunchConfiguration("audio_deadband"),
            "audio_doa_profile": LaunchConfiguration("audio_doa_profile"),
            "verbose_diagnostics": LaunchConfiguration("verbose_diagnostics"),
        }],
    )

    audio_stream_node = Node(
        package="astro_audio",
        executable="audio_stream_node",
        name="audio_stream_node",
        output="screen",
        condition=IfCondition(LaunchConfiguration("enable_audio")),
        parameters=[{
            "input_channels": LaunchConfiguration("audio_input_channels"),
            "enable_hid_doa": False,
        }],
    )

    astro_realtime_node = Node(
        package="astro_ai",
        executable="astro_realtime_node",
        name="astro_realtime_node",
        output="screen",
        condition=IfCondition(LaunchConfiguration("enable_voice")),
    )

    lidar_launch_entity = None
    try:
        try:
            from ament_index_python.packages import get_package_share_directory
            lidar_share = get_package_share_directory("astro_lidar")
            lidar_launch_path = os.path.join(lidar_share, "launch", "lidar.launch.py")
        except Exception:
            lidar_launch_path = ""

        if not lidar_launch_path or not os.path.exists(lidar_launch_path):
            source_candidate = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "astro_lidar", "launch", "lidar.launch.py")
            )
            if os.path.exists(source_candidate):
                lidar_launch_path = source_candidate

        if lidar_launch_path and os.path.exists(lidar_launch_path):
            lidar_launch_entity = IncludeLaunchDescription(
                PythonLaunchDescriptionSource(lidar_launch_path),
                condition=IfCondition(LaunchConfiguration("enable_lidar")),
                launch_arguments={
                    "serial_port": LaunchConfiguration("lidar_serial_port"),
                    "inverted": LaunchConfiguration("inverted"),
                }.items(),
            )
    except Exception:
        pass

    extra_entities = []
    if lidar_launch_entity is not None:
        extra_entities.append(lidar_launch_entity)

    return LaunchDescription(
        actions
        + launch_args
        + [
            serial_bridge_node,
            standalone_gaze_node,
            audio_stream_node,
            astro_realtime_node,
        ]
        + extra_entities
    )
