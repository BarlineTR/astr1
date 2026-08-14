import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetRemap


def generate_launch_description():
    pkg_dir = get_package_share_directory("astro_vision")
    depthai_pkg = get_package_share_directory("depthai_ros_driver")
    params_file = os.path.join(pkg_dir, "config", "camera_params.yaml")
    use_sim_time = LaunchConfiguration("use_sim_time")

    camera_group = GroupAction(
        actions=[
            SetRemap("/camera/color/image_raw", "/oak/rgb/image_raw"),
            SetRemap("/camera/color/camera_info", "/oak/rgb/camera_info"),
            SetRemap("/camera/depth/image_raw", "/oak/depth/image_raw"),
            SetRemap("/camera/points", "/oak/points"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(depthai_pkg, "launch", "camera.launch.py")
                ),
                launch_arguments={
                    "params_file": params_file,
                    "use_sim_time": use_sim_time,
                }.items(),
            ),
        ]
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use simulation clock",
            ),
            camera_group,
            Node(
                package="astro_vision",
                executable="face_detector_node",
                name="face_detector_node",
                output="screen",
                parameters=[params_file, {"use_sim_time": use_sim_time}],
            ),
        ]
    )
