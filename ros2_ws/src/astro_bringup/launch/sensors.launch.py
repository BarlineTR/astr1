import os
import logging

_LOG = logging.getLogger(__name__)


from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    # .env'i CWD'den ve bu dosyanın konumundan YUKARI DOĞRU yürüyerek ara.
    # Eski hâli yalnızca os.path.abspath(".env")'e bakıyordu; `ros2 launch` komutu
    # repo kökü dışından (ör. ros2_ws içinden) verildiğinde hiçbir aday tutmuyor,
    # anahtarlar çocuk süreçlere geçmiyor ve düğümler "OPENAI_API_KEY eksik"
    # diyordu. env_utils.find_env_file() bringup.launch.py ile aynı aramayı yapar.
    try:
        from astro_bringup.env_utils import load_astro_env
        load_astro_env()
    except Exception as _exc:
        _LOG.debug("generate_launch_description: .env yüklenemedi (%s)", _exc)

    lidar_pkg = get_package_share_directory("astro_lidar")
    audio_pkg = get_package_share_directory("astro_audio")
    vision_pkg = get_package_share_directory("astro_vision")
    ai_pkg = get_package_share_directory("astro_ai")
    use_sim_time = LaunchConfiguration("use_sim_time")
    enable_lidar = LaunchConfiguration("enable_lidar")
    enable_audio = LaunchConfiguration("enable_audio")
    enable_vision = LaunchConfiguration("enable_vision")
    enable_ai = LaunchConfiguration("enable_ai")
    use_native_spatial = LaunchConfiguration("use_native_spatial")
    camera_source = LaunchConfiguration("camera_source")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_sim_time",
                default_value="false",
                description="Use simulation clock",
            ),
            DeclareLaunchArgument(
                "use_native_spatial",
                default_value="false",
                description="Use 100% Native DepthAI on-chip VPU spatial perception pipeline",
            ),
            DeclareLaunchArgument(
                "camera_source",
                default_value="oakd",
                description="Görüntü kaynağı: oakd | webcam | none",
            ),
            DeclareLaunchArgument(
                "enable_lidar",
                default_value="true",
                description="Start RPLIDAR and scan filter",
            ),
            DeclareLaunchArgument(
                "enable_audio",
                default_value="true",
                description="Start ReSpeaker audio pipeline",
            ),
            DeclareLaunchArgument(
                "enable_vision",
                default_value="true",
                description="Start OAK-D camera and face detector",
            ),
            DeclareLaunchArgument(
                "enable_ai",
                default_value="true",
                description="Start AI Brain for NLP processing",
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(lidar_pkg, "launch", "lidar.launch.py")
                ),
                condition=IfCondition(enable_lidar),
                launch_arguments={"use_sim_time": use_sim_time}.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(vision_pkg, "launch", "camera.launch.py")
                ),
                condition=IfCondition(enable_vision),
                launch_arguments={
                    "use_sim_time": use_sim_time,
                    "use_native_spatial": use_native_spatial,
                    "source": camera_source,
                }.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(audio_pkg, "launch", "audio.launch.py")
                ),
                condition=IfCondition(enable_audio),
                launch_arguments={"use_sim_time": use_sim_time}.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(ai_pkg, "launch", "ai.launch.py")
                ),
                condition=IfCondition(enable_ai),
                launch_arguments={"use_sim_time": use_sim_time}.items(),
            ),
        ]
    )
