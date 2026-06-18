import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_dir = get_package_share_directory("astro_lidar")
    params_file = os.path.join(pkg_dir, "config", "lidar_params.yaml")

    use_sim_time = LaunchConfiguration("use_sim_time")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use simulation clock",
            ),
            Node(
                package="rplidar_ros",
                executable="rplidar_node",
                name="rplidar_node",
                output="screen",
                parameters=[params_file, {"use_sim_time": use_sim_time}],
            ),
            Node(
                package="astro_lidar",
                executable="scan_filter_node",
                name="scan_filter_node",
                output="screen",
                parameters=[params_file, {"use_sim_time": use_sim_time}],
            ),
        ]
    )
