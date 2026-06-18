import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


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
        [
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
                default_value="true",
                description="Start Arduino serial bridge",
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
