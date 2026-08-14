import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def _dotenv_launch_actions():
    """Inject astr1/.env into every node process (works even when CWD is ros2_ws)."""
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
    bringup_pkg = get_package_share_directory("astro_bringup")
    description_pkg = get_package_share_directory("astro_description")
    use_sim_time = LaunchConfiguration("use_sim_time")
    enable_description = LaunchConfiguration("enable_description")
    enable_base = LaunchConfiguration("enable_base")
    enable_lidar = LaunchConfiguration("enable_lidar")
    enable_audio = LaunchConfiguration("enable_audio")
    enable_vision = LaunchConfiguration("enable_vision")
    enable_ai = LaunchConfiguration("enable_ai")

    return LaunchDescription(
        _dotenv_launch_actions()
        + [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use simulation clock",
            ),
            DeclareLaunchArgument(
                "enable_description",
                default_value="true",
                description="Start robot_state_publisher (URDF/TF)",
            ),
            DeclareLaunchArgument(
                "enable_base",
                default_value="false",
                description="Start Arduino serial bridge (requires /dev/astro_arduino)",
            ),
            DeclareLaunchArgument(
                "enable_lidar",
                default_value="true",
                description="Start RPLIDAR and scan filter",
            ),
            DeclareLaunchArgument(
                "enable_audio",
                default_value="true",
                description="Start ReSpeaker audio pipeline",
            ),
            DeclareLaunchArgument(
                "enable_vision",
                default_value="true",
                description="Start OAK-D camera and face detector",
            ),
            DeclareLaunchArgument(
                "enable_ai",
                default_value="true",
                description="Start AI Brain for NLP processing",
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(description_pkg, "launch", "description.launch.py")
                ),
                condition=IfCondition(enable_description),
                launch_arguments={"use_sim_time": use_sim_time}.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(bringup_pkg, "launch", "base.launch.py")
                ),
                condition=IfCondition(enable_base),
                launch_arguments={"use_sim_time": use_sim_time}.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(bringup_pkg, "launch", "sensors.launch.py")
                ),
                launch_arguments={
                    "use_sim_time": use_sim_time,
                    "enable_lidar": enable_lidar,
                    "enable_audio": enable_audio,
                    "enable_vision": enable_vision,
                    "enable_ai": enable_ai,
                }.items(),
            ),
        ]
    )
