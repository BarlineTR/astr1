import glob
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _resolve_serial_port(primary: str):
    for port in (
        primary,
        "/dev/ttyUSB1",
        "/dev/ttyUSB0",
        "/dev/ttyACM1",
        "/dev/ttyACM0",
    ):
        if port and os.path.exists(port):
            return port
    for pattern in ("/dev/astro_*", "/dev/ttyUSB*", "/dev/ttyACM*"):
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    return None


def _launch_setup(context, *args, **kwargs):
    pkg_dir = get_package_share_directory("astro_lidar")
    params_file = os.path.join(pkg_dir, "config", "lidar_params.yaml")
    use_sim_time = LaunchConfiguration("use_sim_time")
    serial_port_arg = LaunchConfiguration("serial_port").perform(context)

    port = _resolve_serial_port(serial_port_arg)
    nodes = []

    if port is None:
        nodes.append(
            LogInfo(
                msg=(
                    f"LiDAR port '{serial_port_arg}' not found — skipping rplidar_node. "
                    "Connect RPLIDAR or install udev rules, then relaunch."
                )
            )
        )
    else:
        if port != serial_port_arg:
            nodes.append(
                LogInfo(msg=f"LiDAR using resolved port: {port} (requested {serial_port_arg})")
            )
        nodes.append(
            Node(
                package="rplidar_ros",
                executable="rplidar_node",
                name="rplidar_node",
                output="screen",
                parameters=[
                    params_file,
                    {"serial_port": port, "use_sim_time": use_sim_time},
                ],
            )
        )

    nodes.append(
        Node(
            package="astro_lidar",
            executable="scan_filter_node",
            name="scan_filter_node",
            output="screen",
            parameters=[params_file, {"use_sim_time": use_sim_time}],
        )
    )
    return nodes


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use simulation clock",
            ),
            DeclareLaunchArgument(
                "serial_port",
                default_value="/dev/astro_lidar",
                description="RPLIDAR serial port",
            ),
            OpaqueFunction(function=_launch_setup),
        ]
    )
