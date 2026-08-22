#!/usr/bin/env python3
"""ASTRO V1 — Gazebo Harmonic simülasyonu.

Başlattıkları:
  1. gz sim            — fizik + sensörler (astro_indoor.sdf dünyası)
  2. robot_state_publisher — URDF'ten sabit eklem tf'leri
  3. ros_gz_sim create — robotu dünyaya doğurur
  4. parameter_bridge  — gz <-> ROS 2 topic köprüsü
  5. rviz2             — isteğe bağlı

Kullanım:
    ros2 launch astro_sim simulation.launch.py
    ros2 launch astro_sim simulation.launch.py rviz:=false headless:=true
    ros2 launch astro_sim simulation.launch.py x:=-4.0 y:=3.0

Not: use_sim_time bu boru hattındaki HER düğümde true olmak zorundadır.
Bir düğüm duvar saatini kullanırsa tf zaman damgaları tutmaz ve SLAM
"lookup would require extrapolation into the future" hatasıyla susar.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (Command, LaunchConfiguration, PathJoinSubstitution,
                                  PythonExpression)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    pkg_sim = get_package_share_directory("astro_sim")
    pkg_desc = get_package_share_directory("astro_description")
    pkg_ros_gz_sim = get_package_share_directory("ros_gz_sim")

    world = LaunchConfiguration("world")
    rviz = LaunchConfiguration("rviz")
    headless = LaunchConfiguration("headless")
    x, y, z, yaw = (LaunchConfiguration(k) for k in ("x", "y", "z", "yaw"))

    xacro_file = os.path.join(pkg_desc, "urdf", "astro.urdf.xacro")
    # sim_mode:=true -> Gazebo eklentileri ve sensörleri URDF'e dahil edilir.
    # ParameterValue(..., value_type=str) ZORUNLU: aksi hâlde launch, xacro
    # çıktısını YAML sanıp "Unable to parse the value of parameter
    # robot_description as yaml" ile düşer.
    robot_description = ParameterValue(
        Command(["xacro ", xacro_file, " sim_mode:=true"]), value_type=str)

    # gz sim'in dünya dosyasını ve robotun mesh'lerini bulabilmesi için
    GZ_RESOURCE_PATH = os.pathsep.join(
        [os.path.join(pkg_sim, "worlds"), os.path.dirname(pkg_desc)]
    )

    # headless:=true -> "gz sim -s": sunucu var, pencere yok (CI / uzak makine)
    headless_flag = PythonExpression(["'-s ' if '", headless, "' == 'true' else ''"])

    # ── gz-sim <-> ROS 2 köprüsü ───────────────────────────────────────
    #   [  gz -> ROS      ]  ROS -> gz      @  çift yönlü
    bridge_args = [
        "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
        "/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist",
        "/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry",
        "/tf@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V",
        "/scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan",
        "/imu@sensor_msgs/msg/Imu[gz.msgs.IMU",
        "/joint_states@sensor_msgs/msg/JointState[gz.msgs.Model",
        "/head_yaw_cmd@std_msgs/msg/Float64]gz.msgs.Double",
    ]

    return LaunchDescription([
        DeclareLaunchArgument("world", default_value="astro_indoor.sdf",
                              description="astro_sim/worlds altındaki dünya dosyası"),
        DeclareLaunchArgument("rviz", default_value="true",
                              description="RViz2'yi de başlat"),
        DeclareLaunchArgument("headless", default_value="false",
                              description="Gazebo penceresi olmadan çalıştır (sunucu -s)"),
        DeclareLaunchArgument("x", default_value="-4.0", description="doğma X (ODA A)"),
        DeclareLaunchArgument("y", default_value="0.0", description="doğma Y (koridor)"),
        DeclareLaunchArgument("z", default_value="0.10", description="doğma Z"),
        DeclareLaunchArgument("yaw", default_value="0.0", description="doğma yaw"),

        # 1) Gazebo
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(pkg_ros_gz_sim, "launch", "gz_sim.launch.py")),
            launch_arguments={
                "gz_args": [
                    PathJoinSubstitution([pkg_sim, "worlds", world]),
                    " -r ",          # başlar başlamaz fiziği çalıştır
                    " -v 2 ",        # uyarı seviyesi log
                    " ", headless_flag,
                ],
                "on_exit_shutdown": "true",
            }.items(),
        ),

        # 2) URDF -> tf
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="robot_state_publisher",
            output="screen",
            parameters=[{
                "robot_description": robot_description,
                "use_sim_time": True,
            }],
        ),

        # 3) Robotu dünyaya doğur
        Node(
            package="ros_gz_sim",
            executable="create",
            name="spawn_astro",
            output="screen",
            arguments=[
                "-name", "astro",
                "-topic", "robot_description",
                "-x", x, "-y", y, "-z", z, "-Y", yaw,
            ],
        ),

        # 4) Köprü
        Node(
            package="ros_gz_bridge",
            executable="parameter_bridge",
            name="gz_bridge",
            output="screen",
            arguments=bridge_args,
            parameters=[{"use_sim_time": True}],
        ),

        # Kamera görüntüsü ayrı köprüden geçer (image_transport sıkıştırması için)
        Node(
            package="ros_gz_image",
            executable="image_bridge",
            name="oak_rgb_bridge",
            output="screen",
            arguments=["/oak/rgb/image_raw"],
            parameters=[{"use_sim_time": True}],
        ),

        # 5) RViz
        Node(
            package="rviz2",
            executable="rviz2",
            name="rviz2",
            output="screen",
            condition=IfCondition(rviz),
            arguments=["-d", os.path.join(pkg_sim, "rviz", "astro_sim.rviz")],
            parameters=[{"use_sim_time": True}],
        ),
    ])
