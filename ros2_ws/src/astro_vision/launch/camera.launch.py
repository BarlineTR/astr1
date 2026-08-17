"""ASTRO V1 — kamera + yüz tanıma launch.

    ros2 launch astro_vision camera.launch.py                 # OAK-D (varsayılan)
    ros2 launch astro_vision camera.launch.py source:=webcam  # USB webcam
    ros2 launch astro_vision camera.launch.py source:=none    # yalnızca yüz düğümü

İki kaynak da aynı konuya (/oak/rgb/image_raw) yayınlar; face_detector_node
hangisinin yayınladığını bilmek zorunda değildir.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription, LogInfo
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node, SetRemap


def _depthai_camera(params_file, use_sim_time):
    """OAK-D sürücüsü — paket kurulu değilse launch'u komple düşürmemek için ayrı."""
    try:
        depthai_pkg = get_package_share_directory("depthai_ros_driver")
    except Exception:
        return LogInfo(
            msg=(
                "⚠️  depthai_ros_driver bulunamadı — OAK-D başlatılamıyor.\n"
                "    Kurmak için: sudo apt install ros-humble-depthai-ros\n"
                "    USB kamerayla denemek için: "
                "ros2 launch astro_vision camera.launch.py source:=webcam"
            )
        )

    return GroupAction(
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
        ],
        condition=IfCondition(PythonExpression(["'", LaunchConfiguration("source"), "' == 'oakd'"])),
    )


def generate_launch_description():
    pkg_dir = get_package_share_directory("astro_vision")
    params_file = os.path.join(pkg_dir, "config", "camera_params.yaml")
    use_sim_time = LaunchConfiguration("use_sim_time")
    source = LaunchConfiguration("source")

    return LaunchDescription([
        DeclareLaunchArgument(
            "use_sim_time", default_value="false", description="Use simulation clock"
        ),
        DeclareLaunchArgument(
            "source",
            default_value="oakd",
            description="Görüntü kaynağı: oakd | webcam | none",
        ),
        _depthai_camera(params_file, use_sim_time),
        Node(
            package="astro_vision",
            executable="webcam_publisher_node",
            name="webcam_publisher_node",
            output="screen",
            parameters=[params_file, {"use_sim_time": use_sim_time}],
            condition=IfCondition(PythonExpression(["'", source, "' == 'webcam'"])),
        ),
        Node(
            package="astro_vision",
            executable="face_detector_node",
            name="face_detector_node",
            output="screen",
            parameters=[params_file, {"use_sim_time": use_sim_time}],
        ),
    ])
