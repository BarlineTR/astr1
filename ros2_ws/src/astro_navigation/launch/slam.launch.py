#!/usr/bin/env python3
"""ASTRO V1 — SLAM (haritalama).

Simülasyonda:
    ros2 launch astro_sim simulation.launch.py            # 1. terminal
    ros2 launch astro_navigation slam.launch.py           # 2. terminal
    ros2 run teleop_twist_keyboard teleop_twist_keyboard  # 3. terminal, gezdir

Gerçek robotta:
    ros2 launch astro_lidar lidar.launch.py
    ros2 launch astro_navigation slam.launch.py use_sim_time:=false

Harita bittiğinde kaydet:
    ros2 run nav2_map_server map_saver_cli -f \\
      ~/Documents/Projeler/barline/astr1/ros2_ws/src/astro_navigation/maps/astro_indoor

Filtrelenmiş tarama hakkında: astro_lidar/scan_filter_node NaN ve menzil dışı
ışınları temizleyip /scan_filtered yayınlar. slam_toolbox'ı ona bağlamak için
scan_topic:=/scan_filtered verin. Simülasyonda LiDAR zaten temiz olduğu için
varsayılan /scan'dir.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_nav = get_package_share_directory("astro_navigation")
    pkg_sim = get_package_share_directory("astro_sim")

    use_sim_time = LaunchConfiguration("use_sim_time")
    scan_topic = LaunchConfiguration("scan_topic")
    params_file = LaunchConfiguration("params_file")
    rviz = LaunchConfiguration("rviz")

    return LaunchDescription([
        DeclareLaunchArgument(
            "use_sim_time", default_value="true",
            description="Gazebo'da true; gerçek robotta false OLMAK ZORUNDA"),
        DeclareLaunchArgument(
            "scan_topic", default_value="/scan",
            description="LiDAR topic'i (/scan_filtered de kullanılabilir)"),
        DeclareLaunchArgument(
            "params_file",
            default_value=os.path.join(pkg_nav, "config", "slam_toolbox.yaml"),
            description="slam_toolbox parametre dosyası"),
        DeclareLaunchArgument("rviz", default_value="true"),

        Node(
            package="slam_toolbox",
            executable="async_slam_toolbox_node",
            name="slam_toolbox",
            output="screen",
            parameters=[
                params_file,
                {
                    # Launch argümanı YAML'daki değeri ezer; use_sim_time'ın
                    # tek bir yerden gelmesi kritik, karışırsa tf zaman
                    # damgaları tutmaz ve SLAM sessizce durur.
                    "use_sim_time": use_sim_time,
                    "scan_topic": scan_topic,
                },
            ],
        ),

        Node(
            package="rviz2",
            executable="rviz2",
            name="rviz2",
            output="screen",
            condition=IfCondition(rviz),
            arguments=["-d", os.path.join(pkg_sim, "rviz", "astro_sim.rviz")],
            parameters=[{"use_sim_time": use_sim_time}],
        ),
    ])
