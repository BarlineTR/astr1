"""ASTRO V1 — Native Spatial Perception Launch (OAK-D Native Spatial Node).

Direct entrypoint for:
    ros2 launch astro_vision vision_spatial.launch.py
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, SetEnvironmentVariable
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory("astro_vision")
    use_sim_time = LaunchConfiguration("use_sim_time")

    fastdds_cfg = os.path.join(pkg_dir, "config", "fastdds_shm.xml")

    actions = []
    if os.path.exists(fastdds_cfg):
        actions.append(
            SetEnvironmentVariable("FASTRTPS_DEFAULT_PROFILES_FILE", fastdds_cfg)
        )

    actions.extend([
        DeclareLaunchArgument(
            "use_sim_time", default_value="false", description="Use simulation clock"
        ),
        Node(
            package="astro_vision",
            executable="oak_spatial_native_node",
            name="oak_spatial_native_node",
            output="screen",
            parameters=[{"use_sim_time": use_sim_time}],
        ),
    ])

    return LaunchDescription(actions)
