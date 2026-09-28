#!/usr/bin/env python3
"""ASTRO V1 — kayıtlı haritada konumlanma + navigasyon (Nav2).

Haritalamanın (slam.launch.py) tersi: harita zaten var, robot onun içinde
nerede olduğunu bulur (AMCL) ve verilen hedefe gider.

Simülasyonda:
    ros2 launch astro_sim simulation.launch.py                 # 1. terminal
    ros2 launch astro_navigation navigation.launch.py          # 2. terminal
    # RViz'de "2D Pose Estimate" ile başlangıç konumunu verin,
    # sonra "Nav2 Goal" ile hedef seçin.

Gerçek robotta:
    ros2 launch astro_navigation navigation.launch.py use_sim_time:=false

Başka bir harita ile:
    ros2 launch astro_navigation navigation.launch.py map:=/yol/harita.yaml

AMCL ilk konumu bilmez; "2D Pose Estimate" verilmezse robot haritada
kaybolur ve planlayıcı saçma yollar üretir. set_initial_pose:=true ile
aşağıdaki x/y/yaw değerleri otomatik uygulanır (simülasyonda doğma noktası).
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetParameter
from nav2_common.launch import RewrittenYaml


def generate_launch_description():
    pkg_nav = get_package_share_directory("astro_navigation")
    pkg_sim = get_package_share_directory("astro_sim")

    use_sim_time = LaunchConfiguration("use_sim_time")
    map_yaml = LaunchConfiguration("map")
    params_file = LaunchConfiguration("params_file")
    rviz = LaunchConfiguration("rviz")
    autostart = LaunchConfiguration("autostart")
    set_init = LaunchConfiguration("set_initial_pose")
    ix, iy, iyaw = (LaunchConfiguration(k) for k in ("initial_x", "initial_y", "initial_yaw"))

    # Yaşam döngüsü yöneticisinin sırayla ayağa kaldıracağı düğümler.
    # Sıra önemli: harita ve konumlanma, planlayıcıdan ÖNCE hazır olmalı.
    lifecycle_nodes = [
        "map_server", "amcl",
        "controller_server", "smoother_server", "planner_server",
        "behavior_server", "bt_navigator", "waypoint_follower",
        "velocity_smoother",
    ]

    # RewrittenYaml ZORUNLU. parameters=[params_file, {"anahtar": deger}]
    # ile override DENENDİ ve çalışmadı: dosyadaki değer kazanıyor, map_server
    # "yaml-filename parameter is empty" deyip haritayı hiç yüklemiyor, ardından
    # AMCL ve global_costmap sonsuza kadar haritayı bekliyordu. RewrittenYaml
    # değerleri dosyanın kendisine, düğümler başlamadan önce yazar.
    configured_params = RewrittenYaml(
        source_file=params_file,
        root_key="",
        param_rewrites={
            "use_sim_time": use_sim_time,
            "yaml_filename": map_yaml,
        },
        convert_types=True,
    )

    return LaunchDescription([
        DeclareLaunchArgument("use_sim_time", default_value="true"),
        DeclareLaunchArgument(
            "map",
            default_value=os.path.join(pkg_nav, "maps", "astro_indoor.yaml"),
            description="Harita YAML dosyası"),
        DeclareLaunchArgument(
            "params_file",
            default_value=os.path.join(pkg_nav, "config", "nav2_params.yaml")),
        DeclareLaunchArgument("rviz", default_value="true"),
        DeclareLaunchArgument("autostart", default_value="true"),
        DeclareLaunchArgument("set_initial_pose", default_value="true",
                              description="AMCL başlangıç konumunu otomatik ver"),
        DeclareLaunchArgument("initial_x", default_value="0.0",
                              description="map çerçevesinde başlangıç X"),
        DeclareLaunchArgument("initial_y", default_value="0.0"),
        DeclareLaunchArgument("initial_yaw", default_value="0.0"),

        # Tüm Nav2 düğümlerine tek yerden geçir — ayrı ayrı verilirse
        # birinde unutulduğunda tf zaman damgaları tutmaz.
        SetParameter(name="use_sim_time", value=use_sim_time),

        GroupAction([
            Node(
                package="nav2_map_server", executable="map_server", name="map_server",
                output="screen",
                parameters=[configured_params],
            ),
            Node(
                package="nav2_amcl", executable="amcl", name="amcl",
                output="screen",
                parameters=[configured_params],
            ),
            Node(
                package="nav2_controller", executable="controller_server",
                name="controller_server", output="screen",
                parameters=[configured_params],
                remappings=[("cmd_vel", "cmd_vel_nav")],
            ),
            Node(
                package="nav2_smoother", executable="smoother_server",
                name="smoother_server", output="screen",
                parameters=[configured_params],
            ),
            Node(
                package="nav2_planner", executable="planner_server",
                name="planner_server", output="screen",
                parameters=[configured_params],
            ),
            Node(
                package="nav2_behaviors", executable="behavior_server",
                name="behavior_server", output="screen",
                parameters=[configured_params],
            ),
            Node(
                package="nav2_bt_navigator", executable="bt_navigator",
                name="bt_navigator", output="screen",
                parameters=[configured_params],
            ),
            Node(
                package="nav2_waypoint_follower", executable="waypoint_follower",
                name="waypoint_follower", output="screen",
                parameters=[configured_params],
            ),
            # velocity_smoother, controller'ın cmd_vel_nav çıkışını alıp
            # ivme sınırlarına uydurarak /cmd_vel'e basar. Böylece DiffDrive
            # eklentisinin uygulayamayacağı basamak komutlar gönderilmez.
            Node(
                package="nav2_velocity_smoother", executable="velocity_smoother",
                name="velocity_smoother", output="screen",
                parameters=[configured_params],
                remappings=[("cmd_vel", "cmd_vel_nav"), ("cmd_vel_smoothed", "cmd_vel")],
            ),
            Node(
                package="nav2_lifecycle_manager", executable="lifecycle_manager",
                name="lifecycle_manager_navigation", output="screen",
                parameters=[{
                    "use_sim_time": use_sim_time,
                    "autostart": autostart,
                    "node_names": lifecycle_nodes,
                }],
            ),
        ]),

        Node(
            package="rviz2", executable="rviz2", name="rviz2", output="screen",
            condition=IfCondition(rviz),
            arguments=["-d", os.path.join(pkg_sim, "rviz", "astro_sim.rviz")],
            parameters=[{"use_sim_time": use_sim_time}],
        ),
    ])
