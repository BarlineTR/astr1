import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    bringup_pkg = get_package_share_directory("astro_bringup")

    return LaunchDescription(
        [
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(bringup_pkg, "launch", "bringup.launch.py")
                )
            ),
        ]
    )
