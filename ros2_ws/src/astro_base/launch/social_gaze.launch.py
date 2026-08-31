"""ROS 2 Launch file for ASTRO Social Gaze & Hardware System."""

import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory('astro_base')
    default_social_config = os.path.join(pkg_share, 'config', 'social_gaze_params.yaml')
    default_calib_config = os.path.join(pkg_share, 'config', 'calibration_params.yaml')

    return LaunchDescription([
        DeclareLaunchArgument(
            'launch_serial_bridge',
            default_value='true',
            description='Launch serial bridge driver to Arduino Mega hardware',
        ),
        DeclareLaunchArgument(
            'social_config_file',
            default_value=default_social_config,
            description='Path to social gaze parameter yaml file',
        ),
        DeclareLaunchArgument(
            'calib_config_file',
            default_value=default_calib_config,
            description='Path to unified calibration yaml file',
        ),

        # Serial Hardware Bridge Node
        Node(
            package='astro_base',
            executable='serial_bridge',
            name='serial_bridge',
            output='screen',
            condition=IfCondition(LaunchConfiguration('launch_serial_bridge')),
            parameters=[{
                'port': '/dev/ttyCH341USB0',
                'baud': 115200,
            }],
        ),

        # Greenfield Social Gaze Pipeline Node
        Node(
            package='astro_base',
            executable='social_gaze',
            name='social_gaze_node',
            output='screen',
            parameters=[
                LaunchConfiguration('social_config_file'),
                {'calibration_file': LaunchConfiguration('calib_config_file')},
            ],
        ),
    ])
