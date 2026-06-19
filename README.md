# ASTRO V1

ASTRO V1 is a modular ROS 2 based robotics project containing drivers and launch files for base movement, LiDAR (RPLIDAR), Vision (OAK-D Lite), and Audio (ReSpeaker 4-Mic Array) systems.

## 🚀 ROS 2 Architecture

The system has been completely modularized into ROS 2 Humble packages:

### 📦 Packages
- `astro_base`: Arduino Mega serial bridge for motor control and base sensors.
- `astro_lidar`: RPLIDAR A1 wrapper and NaN/Range filter node (`scan_filter_node`).
- `astro_vision`: OAK-D Lite driver wrapper and OpenCV Face Detection node.
- `astro_audio`: ReSpeaker array driver handling Audio Capture, Speech Recognition (Vosk), and TTS (pyttsx3/gTTS).
- `astro_ai`: AI Brain Node managing LLM interactions and memory via OpenAI API standard.
- `astro_bringup`: Centralized launch files and parameters for the whole system.
- `astro_description`: URDF models and Robot State Publisher (tf2).

## 🛠️ Installation & Build

Make sure you have ROS 2 Humble installed on your Jetson Orin Nano / Ubuntu 22.04 system.

### 1. Install Dependencies
```bash
sudo apt update
sudo apt install -y python3-rosdep python3-colcon-common-extensions
sudo apt install -y ros-humble-rplidar-ros ros-humble-depthai-ros ros-humble-robot-state-publisher
pip3 install pyusb sounddevice numpy vosk pyttsx3 opencv-python python-dotenv openai
```

### 2. Build the Workspace
```bash
cd ~/Desktop/astr1/ros2_ws
colcon build --symlink-install
source install/setup.bash
```

## 🚦 Usage

With the new ROS 2 structure, you no longer need to run separate scripts. The entire system is managed via `astro_bringup`.

### Launching the Entire Robot (All Sensors + Base)
```bash
ros2 launch astro_bringup robot.launch.py
```
*(This will launch the base, lidar, camera, and audio nodes all at once.)*

### Launching Individual Subsystems
If you want to test or launch sensors individually for debugging:

**Vision (OAK-D + Face Detection):**
```bash
ros2 launch astro_vision camera.launch.py
```

**LiDAR (RPLIDAR + Filter):**
```bash
ros2 launch astro_lidar lidar.launch.py
```

**Audio (Mic Capture + STT + TTS):**
```bash
ros2 launch astro_audio audio.launch.py
```

## ⚙️ Configuration

Centralized parameters are stored in `astro_bringup/config/astro_params.yaml`. You can modify:
- Serial ports (e.g., `/dev/astro_lidar`, `/dev/astro_arduino`)
- Camera resolution and FPS
- VAD thresholds and Audio settings
- RPLIDAR ranges and baud rates

> **Note:** For AI API keys (`AI_API_KEY`), use the `.env` file at the root of the project (copy from `.env.example`). Do not hardcode API keys in the source code!
