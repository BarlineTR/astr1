import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    lidar_pkg = get_package_share_directory("astro_lidar")
    audio_pkg = get_package_share_directory("astro_audio")
    vision_pkg = get_package_share_directory("astro_vision")
    use_sim_time = LaunchConfiguration("use_sim_time")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use simulation clock",
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(lidar_pkg, "launch", "lidar.launch.py")
                ),
                launch_arguments={"use_sim_time": use_sim_time}.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(vision_pkg, "launch", "camera.launch.py")
                ),
                launch_arguments={"use_sim_time": use_sim_time}.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(audio_pkg, "launch", "audio.launch.py")
                ),
                launch_arguments={"use_sim_time": use_sim_time}.items(),
            ),
        ]
    )
