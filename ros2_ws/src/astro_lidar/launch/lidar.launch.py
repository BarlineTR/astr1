import glob
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _is_lidar_port(dev_path: str) -> bool:
    try:
        for l_path in ("/dev/astro_lidar", "/dev/rplidar"):
            if os.path.exists(l_path) and os.path.realpath(dev_path) == os.path.realpath(l_path):
                return True
    except Exception:
        pass
    try:
        import serial.tools.list_ports
        for port_info in serial.tools.list_ports.comports():
            if port_info.device == dev_path and getattr(port_info, "vid", None) == 0x10C4:
                return True
    except Exception:
        pass
    try:
        bname = os.path.basename(dev_path)
        for sys_v_path in (
            f"/sys/class/tty/{bname}/device/../idVendor",
            f"/sys/class/tty/{bname}/device/idVendor",
        ):
            if os.path.exists(sys_v_path):
                with open(sys_v_path, "r") as f:
                    if f.read().strip().lower() == "10c4":
                        return True
    except Exception:
        pass
    return False


def _resolve_serial_port(primary: str):
    if primary and os.path.exists(primary) and (primary in ("/dev/astro_lidar", "/dev/rplidar") or _is_lidar_port(primary)):
        return primary
    for pattern in ("/dev/astro_lidar*", "/dev/rplidar*", "/dev/ttyUSB*", "/dev/ttyACM*"):
        for p in sorted(glob.glob(pattern)):
            if _is_lidar_port(p):
                return p
    return None


def _launch_setup(context, *args, **kwargs):
    pkg_dir = get_package_share_directory("astro_lidar")
    params_file = os.path.join(pkg_dir, "config", "lidar_params.yaml")
    use_sim_time = LaunchConfiguration("use_sim_time")
    serial_port_arg = LaunchConfiguration("serial_port").perform(context)

    port = _resolve_serial_port(serial_port_arg)
    nodes = []

    inverted = LaunchConfiguration("inverted")

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
                    {
                        "serial_port": port,
                        "use_sim_time": use_sim_time,
                        "inverted": inverted,
                    },
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
            DeclareLaunchArgument(
                "inverted",
                default_value="false",
                description="Invert RPLIDAR scan (flips left/right for upside down or mirrored mount)",
            ),
            OpaqueFunction(function=_launch_setup),
        ]
    )
